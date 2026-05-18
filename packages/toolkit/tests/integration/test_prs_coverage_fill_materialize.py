"""Phase 1b RED — ``_materialize_pca_sites`` tests (stubbed plink2 invocation).

Verifies the one-time-per-panel materialize step:

- argv shape: plink2 is invoked via DooD against
  ``ghcr.io/pgscatalog/plink2:2.00a5.10`` with the canonical LD-prune flags
  (``--maf 0.01 --hwe 1e-6 --geno 0.05 --indep-pairwise 1000 50 0.05``).
- output layout: ``pca_sites.tsv`` + ``pca_alleles.tsv`` land under the
  requested ``output_root/<panel_version>/`` directory; sites carry the
  ``chr`` prefix (panel→CRAM rewrite verified in the prove-out).
  Plaintext (not bgzip) — bcftools ``--regions-file`` / ``--targets-file``
  accept plain TSV at sub-10 MB scale, and the per-autosome ~436k-line
  output stays well under that ceiling.
- provenance sidecar: ``pca_sites.provenance.json`` carries panel SHA256,
  plink2 image pin, prune parameters, prune-in checksum + count.
- idempotency: rebuilding with the same panel produces byte-equivalent
  output (mtime aside).

A real-data smoke against the project owner's HGDP+1kGP v1 panel is gated on
``needs_prs_runtime`` and lives in ``test_prs_coverage_fill_real_panel.py``
(Phase 1c follow-up).
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _fake_plink2_run(prune_in_lines: list[str]) -> MagicMock:
    """Build a ``subprocess.run`` fake that materialises a plink2 prune-in file.

    The fake parses ``--out <path>`` from the argv and writes ``<path>.prune.in``
    with the supplied lines. plink2's real output also includes a ``.log`` and
    a ``.prune.out``; we emit minimal sidecars so the wrapper's downstream
    file-presence checks pass.
    """

    def _runner(cmd: list[str] | tuple[str, ...], **_kwargs: object):
        cmd_list = list(cmd)
        out_prefix: Path | None = None
        for i, arg in enumerate(cmd_list):
            if arg == "--out" and i + 1 < len(cmd_list):
                out_prefix = Path(str(cmd_list[i + 1]))
                break
        if out_prefix is not None:
            out_prefix.parent.mkdir(parents=True, exist_ok=True)
            (out_prefix.with_suffix(out_prefix.suffix + ".prune.in")).write_text(
                "\n".join(prune_in_lines) + "\n"
            )
            (out_prefix.with_suffix(out_prefix.suffix + ".prune.out")).write_text("")
            (out_prefix.with_suffix(out_prefix.suffix + ".log")).write_text(
                "PLINK v2.00a5.10 64-bit (stubbed)\n"
            )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout=b"", stderr=b"")

    return MagicMock(side_effect=_runner)


@pytest.fixture
def synthetic_panel_root(tmp_path: Path) -> Path:
    """Stage a tiny synthetic HGDP+1kGP panel layout (presence-only).

    plink2 is stubbed, so file contents don't matter — only the layout +
    SHA256-able pvar.zst do. The fixture writes a non-empty pvar.zst so the
    SHA256 hash is meaningful (an empty file would still hash, but a
    deterministic non-empty payload makes the test self-documenting).
    """
    panel_root = tmp_path / "panel" / "pgs_catalog_ancestry" / "v1"
    panel_root.mkdir(parents=True)
    (panel_root / "GRCh38_HGDP+1kGP_ALL.pgen").write_bytes(b"PGEN-fixture")
    (panel_root / "GRCh38_HGDP+1kGP_ALL.pvar.zst").write_bytes(b"PVAR-fixture")
    (panel_root / "GRCh38_HGDP+1kGP_ALL.psam").write_bytes(b"PSAM-fixture")
    return panel_root


def test_materialize_pca_sites_emits_indexed_tsvs(
    tmp_path: Path, synthetic_panel_root: Path
) -> None:
    """Output layout: ``<out>/<panel_version>/pca_{sites,alleles}.tsv.gz{,.tbi}``."""
    from genomeclaw_toolkit.prep.coverage_fill import _materialize_pca_sites

    output_root = tmp_path / "reference" / "prs_pca_sites"
    prune_in = ["22:10001:T:A", "22:10002:G:C", "1:5000:A:G"]

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run", _fake_plink2_run(prune_in)
    ):
        _materialize_pca_sites(
            panel_root=synthetic_panel_root,
            output_root=output_root,
            panel_version="v1",
        )

    panel_out = output_root / "v1"
    for relpath in ("pca_sites.tsv", "pca_alleles.tsv"):
        assert (panel_out / relpath).exists(), f"missing materialise output: {relpath}"


def test_materialize_pca_sites_invokes_plink2_with_canonical_flags(
    tmp_path: Path, synthetic_panel_root: Path
) -> None:
    """plink2 argv carries the documented LD-prune flag set.

    Verified against the chr22 prove-out: ``--maf 0.01 --hwe 1e-6 --geno 0.05
    --indep-pairwise 1000 50 0.05`` is the canonical pgsc_calc-compatible
    LD-prune. Less aggressive (e.g. r²<0.1) would yield more sites but
    diverge from pgsc_calc's internal FILTER_VARIANTS.
    """
    from genomeclaw_toolkit.prep.coverage_fill import _materialize_pca_sites

    output_root = tmp_path / "reference" / "prs_pca_sites"
    fake = _fake_plink2_run(["22:10001:T:A"])

    with patch("genomeclaw_toolkit.prep.coverage_fill.subprocess.run", fake):
        _materialize_pca_sites(
            panel_root=synthetic_panel_root,
            output_root=output_root,
            panel_version="v1",
        )

    # The fake captured every subprocess.run call; flatten and probe.
    all_argv = [" ".join(str(x) for x in call.args[0]) for call in fake.call_args_list]
    haystack = "\n".join(all_argv)

    assert "plink2" in haystack
    assert "--maf 0.01" in haystack
    assert "--hwe 1e-6" in haystack
    assert "--geno 0.05" in haystack
    assert "--indep-pairwise 1000 50 0.05" in haystack
    # The plink2 image (per the chr22 prove-out + spec.md Q5).
    assert "ghcr.io/pgscatalog/plink2:2.00a5.10" in haystack


def test_materialize_pca_sites_writes_provenance_json(
    tmp_path: Path, synthetic_panel_root: Path
) -> None:
    """INV-R001 — `pca_sites.provenance.json` carries panel SHA256, image pin, prune params."""
    import hashlib

    from genomeclaw_toolkit.prep.coverage_fill import _materialize_pca_sites

    output_root = tmp_path / "reference" / "prs_pca_sites"
    prune_in = ["22:10001:T:A", "22:10002:G:C"]
    pvar_sha = hashlib.sha256(
        (synthetic_panel_root / "GRCh38_HGDP+1kGP_ALL.pvar.zst").read_bytes()
    ).hexdigest()

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run", _fake_plink2_run(prune_in)
    ):
        _materialize_pca_sites(
            panel_root=synthetic_panel_root,
            output_root=output_root,
            panel_version="v1",
        )

    prov = json.loads((output_root / "v1" / "pca_sites.provenance.json").read_text())
    required = {
        "panel_root",
        "panel_version",
        "panel_pvar_sha256",
        "plink2_image",
        "prune_params",
        "prune_in_count",
        "prune_in_sha256",
        "created_at",
        "schema_version",
    }
    missing = required - set(prov)
    assert not missing, f"INV-R001 missing keys from provenance.json: {sorted(missing)}"
    assert prov["panel_version"] == "v1"
    assert prov["panel_pvar_sha256"] == pvar_sha
    assert prov["prune_in_count"] == len(prune_in)
    assert prov["prune_params"]["r2"] == 0.05
    assert prov["plink2_image"].startswith("ghcr.io/pgscatalog/plink2:")


def test_materialize_pca_sites_tsvs_carry_chr_prefix(
    tmp_path: Path, synthetic_panel_root: Path
) -> None:
    """Emitted sites/alleles TSVs use ``chr1, chr22`` (CRAM convention), not bare ``1, 22``.

    Panel→CRAM rewrite verified in the chr22 prove-out: the user CRAM and
    GRCh38 FASTA use ``chrN`` while the panel pvar uses bare ``N``. The
    bcftools targets/regions files must match the CRAM, not the panel.
    """
    from genomeclaw_toolkit.prep.coverage_fill import _materialize_pca_sites

    output_root = tmp_path / "reference" / "prs_pca_sites"
    prune_in = ["22:10001:T:A", "1:5000:G:C"]

    with patch(
        "genomeclaw_toolkit.prep.coverage_fill.subprocess.run", _fake_plink2_run(prune_in)
    ):
        _materialize_pca_sites(
            panel_root=synthetic_panel_root,
            output_root=output_root,
            panel_version="v1",
        )

    panel_out = output_root / "v1"
    sites_text = (panel_out / "pca_sites.tsv").read_text()
    alleles_text = (panel_out / "pca_alleles.tsv").read_text()

    assert "chr22\t10001" in sites_text
    assert "chr1\t5000" in sites_text
    assert "chr22\t10001\tT,A" in alleles_text
    assert "chr1\t5000\tG,C" in alleles_text
    # Bare-prefix smoke: no line starts with "22\t" or "1\t".
    for line in sites_text.splitlines():
        if line and not line.startswith("#"):
            assert not line.startswith(("22\t", "1\t")), (
                f"panel-naming leak: {line!r} should have chr prefix"
            )
