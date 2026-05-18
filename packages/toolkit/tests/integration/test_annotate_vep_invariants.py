"""Phase 4D — INV-D001 / INV-D003 / INV-R001 contract tests for ``annotate_vep``.

These three tests close the per-orchestrator-invariant-coverage asymmetry:
every other Phase-4 orchestrator (``ingest``, ``normalize``,
``annotate_vcfanno``) has explicit ``test_invXxxx_*`` tests; without these
``annotate_vep`` would be the only one without.

Scope (deliberately narrow — option #2 of the 2026-05-13 phase-4-completion
revision):

- We **don't** invoke the ``vep`` binary. The orchestrator's interactions
  with the binary are stubbed out so the tests run on the host venv (no
  ``needs_bio`` marker, no fixture VEP cache).
- We **do** exercise the orchestrator's accounting around the binary:
  reference-source immutability (INV-D001), scratch usage (INV-D003), and
  provenance-step recording (INV-R001).

Full ``needs_bio`` integration testing of ``annotate_vep`` against a real
fixture VEP cache is deferred (see [phase-4-completion.md § W5
needs_bio integration tests](../../../docs/plans/active/mvp/phases/phase-4-completion.md)
— the cost of a hand-rolled VEP cache fixture vs. the marginal value over
unit tests + the real-data smoke didn't pencil out in the 2026-05-13
reassessment). When that file lands, the three tests here become a subset
of its coverage; they stay valuable as the fast-feedback host-only layer.

Stubs:

- ``vep_run`` — writes a canned bgzipped VCF to ``config.output_vcf`` and
  records the invocation for the INV-D003 assertion.
- ``vep_version`` — returns a stub version string for the INV-R001
  provenance assertion.
- ``bcftools_index_tbi`` — writes a stub ``.tbi`` sidecar and returns its
  path so ``atomic_promote`` has a real file to move.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from genomeclaw_toolkit.prep import annotate_vep as annotate_vep_module
from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER
from genomeclaw_toolkit.prep._vep import VepConfig, VepRunStats


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _stub_bgz(path: Path) -> None:
    """Write a minimal well-formed bgzipped file at ``path``.

    Two consecutive BGZF EOF markers — a degenerate but valid bgzip
    body that ``_sha256_file`` and ``atomic_promote`` will read happily.
    Downstream code in the orchestrator never decompresses these files;
    only sha256 + size matter.
    """
    path.write_bytes(BGZF_EOF_MARKER + BGZF_EOF_MARKER)


def _stub_tbi(path: Path) -> None:
    """Write a stub tabix index sidecar."""
    path.write_bytes(b"\x1f\x8b\x08\x04stub")


def _stage_run_dir(genomeclaw_layout: dict[str, Path]) -> Path:
    """Stage a run_dir with the manifest + provenance + vcfanno.vcf.gz the
    orchestrator expects to find."""
    run_dir = genomeclaw_layout["derived"] / "vep-inv-001"
    run_dir.mkdir(parents=True)

    (run_dir / "manifest.json").write_text(json.dumps({"sample_id": "vep-inv-001", "outputs": {}}))
    (run_dir / "provenance.json").write_text(json.dumps({"steps": []}))
    _stub_bgz(run_dir / "vcfanno.vcf.gz")
    _stub_tbi(run_dir / "vcfanno.vcf.gz.tbi")
    return run_dir


def _stage_vep_reference(
    reference_dir: Path, *, with_plugins: bool, with_grch38: bool = True
) -> None:
    """Stage a fixture ``vep_cache/`` + (optionally) ``loftee/`` + ``alphamissense/``
    + ``grch38/`` per-source dirs.

    File **contents** are placeholders; the orchestrator's ``_resolve_*``
    helpers only probe for path existence. The bytes still matter for the
    INV-D001 SHA256 check below — they're what we'll re-hash post-run to
    verify nothing was mutated.
    """
    cache_dir = reference_dir / "vep_cache" / "114"
    cache_dir.mkdir(parents=True)
    (cache_dir / "homo_sapiens").mkdir()
    (cache_dir / "homo_sapiens" / "info.txt").write_text(
        "stub vep_cache info — content shape doesn't matter for these tests"
    )

    if with_grch38:
        grch38 = reference_dir / "grch38" / "ncbi-2014"
        grch38.mkdir(parents=True)
        (grch38 / "grch38.fa.gz").write_bytes(b"stub-grch38-fasta-bytes")
        (grch38 / "grch38.fa.gz.fai").write_bytes(b"stub-fai-bytes")
        (grch38 / "grch38.fa.gz.gzi").write_bytes(b"stub-gzi-bytes")

    if with_plugins:
        loftee = reference_dir / "loftee" / "v1.0"
        loftee.mkdir(parents=True)
        (loftee / "human_ancestor.fa.gz").write_bytes(b"stub-fasta-bytes")
        (loftee / "loftee.sql").write_bytes(b"stub-sql-bytes")
        (loftee / "gerp_conservation_scores.homo_sapiens.GRCh38.bw").write_bytes(
            b"stub-bigwig-bytes"
        )

        am = reference_dir / "alphamissense" / "v1.0" / "AlphaMissense"
        am.mkdir(parents=True)
        (am / "AlphaMissense_hg38.tsv.gz").write_bytes(b"stub-am-tsv-bytes")


# Canned skip-stats the stubbed vep_run returns. Synthetic but realistic:
# three contigs with a small per-chrom count, mixing decoy / random / alt
# patterns. Tests pin this through to the provenance step so a regression
# that drops the pass-through of skip stats surfaces as a test failure.
_STUBBED_VEP_SKIP_STATS = VepRunStats(
    skipped_variants=15,
    skipped_chroms={
        "chrUn_JTFH01001998v1_decoy": 6,
        "chrUn_KI270742v1": 6,
        "chr1_KI270706v1_random": 3,
    },
)


@pytest.fixture
def stubbed_vep(monkeypatch: pytest.MonkeyPatch) -> list[VepConfig]:
    """Stub ``vep_run`` + ``vep_version`` + ``bcftools_index_tbi`` so the
    orchestrator runs end-to-end on the host venv.

    Returns the list of ``VepConfig`` instances each stub-call received,
    so tests can assert on the orchestrator's call shape (used by
    INV-D003 to verify where the intermediate landed).
    """
    invocations: list[VepConfig] = []

    def _fake_vep_run(config: VepConfig) -> VepRunStats:
        config.output_vcf.parent.mkdir(parents=True, exist_ok=True)
        _stub_bgz(config.output_vcf)
        invocations.append(config)
        return _STUBBED_VEP_SKIP_STATS

    def _fake_index_tbi(*, vcf: Path, derived_dir: Path) -> Path:  # noqa: ARG001
        tbi = vcf.with_suffix(vcf.suffix + ".tbi")
        _stub_tbi(tbi)
        return tbi

    monkeypatch.setattr(annotate_vep_module, "vep_run", _fake_vep_run)
    monkeypatch.setattr(annotate_vep_module, "vep_version", lambda: "114.1-stub")
    monkeypatch.setattr(annotate_vep_module, "bcftools_index_tbi", _fake_index_tbi)
    return invocations


def test_invD001_annotate_vep_does_not_mutate_cache_or_plugins(
    genomeclaw_layout: dict[str, Path],
    stubbed_vep: list[VepConfig],  # noqa: ARG001 — fixture is for side effects
) -> None:
    """``INV-D001``: VEP cache + plugin-data files are not mutated by the run.

    The orchestrator passes ``cache_dir`` to ``--dir_cache`` and per-plugin
    data paths into the ``--plugin`` flags. VEP itself only reads these,
    but the *orchestrator* could in principle mutate them via the staging
    step (e.g. a misplaced chr-rename copy-in-place). This test pins the
    contract end-to-end.
    """
    reference_dir = genomeclaw_layout["reference"]
    _stage_vep_reference(reference_dir, with_plugins=True)
    run_dir = _stage_run_dir(genomeclaw_layout)

    # Capture SHA256s of every staged reference file before the run.
    reference_files: list[Path] = []
    for source in ("vep_cache", "loftee", "alphamissense"):
        reference_files.extend(p for p in (reference_dir / source).rglob("*") if p.is_file())
    before = {p: _sha256(p) for p in reference_files}
    assert before, "test setup error: no reference files staged"

    out = annotate_vep_module.annotate_vep(
        run_dir=run_dir,
        reference_dir=reference_dir,
    )

    assert out is not None, "annotate_vep returned None — cache resolver failed"

    for path, before_sha in before.items():
        assert _sha256(path) == before_sha, (
            f"INV-D001 violation: {path} was mutated by annotate_vep"
        )


def test_invD003_annotate_vep_uses_shard_scratch(
    genomeclaw_layout: dict[str, Path],
    stubbed_vep: list[VepConfig],
) -> None:
    """``INV-D003``: heavy intermediates land under the ephemeral scratch
    base (container-local; off virtiofs), not under the run dir.

    Asserted via the stub-recorded ``VepConfig.output_vcf`` path. Phase A
    of [annotate-shard-resilience](../../../docs/plans/active/annotate-shard-resilience/development-plan.md)
    split scratch into two tiers — the ephemeral tier is where heavy
    intermediates land. The persistent tier (``genomeclaw_layout["scratch"]``)
    is now only for the ``_cache/`` subtree.
    """
    reference_dir = genomeclaw_layout["reference"]
    _stage_vep_reference(reference_dir, with_plugins=True)
    run_dir = _stage_run_dir(genomeclaw_layout)
    ephemeral_root = genomeclaw_layout["ephemeral_scratch"]

    annotate_vep_module.annotate_vep(
        run_dir=run_dir,
        reference_dir=reference_dir,
    )

    assert len(stubbed_vep) == 1, f"expected one vep_run call, got {len(stubbed_vep)}"
    intermediate = stubbed_vep[0].output_vcf

    # The intermediate must live under the ephemeral scratch root, not
    # under derived/ and not under the persistent scratch.
    assert ephemeral_root in intermediate.parents, (
        f"INV-D003 violation: vep_run output {intermediate} is not under "
        f"the ephemeral scratch root {ephemeral_root}"
    )
    assert run_dir not in intermediate.parents, (
        f"INV-D003 violation: vep_run output {intermediate} lives inside the run dir {run_dir}"
    )

    # The shard_scratch dir name follows the ``<step>-<run_id>`` convention
    # documented in prep/scratch.py — pin it so a future rename of the step
    # label surfaces here rather than silently breaking the scratch
    # observability story.
    assert any(p.name == f"annotate-vep-{run_dir.name}" for p in intermediate.parents), (
        f"INV-D003 violation: vep_run output {intermediate} not inside a "
        f"shard_scratch(step='annotate-vep', run_id='{run_dir.name}', ...) dir"
    )

    # And the final promoted output IS in run_dir (that's atomic_promote's
    # destination by design). Belt-and-suspenders against a regression that
    # would leave the run dir without the canonical name.
    assert (run_dir / "vep.vcf.gz").exists()
    assert (run_dir / "vep.vcf.gz.tbi").exists()


def test_invR001_annotate_vep_appends_step_to_provenance(
    genomeclaw_layout: dict[str, Path],
    stubbed_vep: list[VepConfig],  # noqa: ARG001
) -> None:
    """``INV-R001``: provenance.json gains a complete ``vep`` step after the run.

    The step must record every piece the rebuildability contract depends
    on: tool identity + version, input + output SHA256s, the exact CLI
    flags used, the cache release tag, plugins enabled, and timestamps.
    """
    reference_dir = genomeclaw_layout["reference"]
    _stage_vep_reference(reference_dir, with_plugins=True)
    run_dir = _stage_run_dir(genomeclaw_layout)

    annotate_vep_module.annotate_vep(
        run_dir=run_dir,
        reference_dir=reference_dir,
    )

    provenance = json.loads((run_dir / "provenance.json").read_text())
    vep_step: dict[str, Any] | None = next(
        (s for s in provenance["steps"] if s["step"] == "vep"), None
    )
    assert vep_step is not None, (
        f"no vep step in provenance.json: steps={[s['step'] for s in provenance['steps']]}"
    )

    # Tool identity.
    assert vep_step["tool"] == "vep"
    assert vep_step["tool_version"] == "114.1-stub"

    # Timestamps present (ISO-8601 strings; the orchestrator's
    # ``_serialise_for_json`` formats them as ``YYYY-MM-DDTHH:MM:SSZ``).
    assert vep_step["started_at"]
    assert vep_step["completed_at"]

    # Inputs: the vcfanno.vcf.gz the orchestrator read + the reference
    # FASTA threaded into VEP's ``--fasta``. Each carries a sha256 so a
    # rerun against the same bytes reproduces the same annotation columns.
    inputs = vep_step["inputs"]
    vcfanno_input = next((i for i in inputs if i["path"].endswith("vcfanno.vcf.gz")), None)
    assert vcfanno_input is not None, f"no vcfanno.vcf.gz input recorded: {inputs}"
    assert len(vcfanno_input["sha256"]) == 64, "vcfanno sha256 isn't 64 hex chars"

    # Outputs: the promoted vep.vcf.gz with sha256.
    outputs = vep_step["outputs"]
    assert len(outputs) == 1
    assert outputs[0]["path"] == "vep.vcf.gz"
    assert len(outputs[0]["sha256"]) == 64

    # Params: cache release + plugins enabled + the exact flag list + fork.
    params = vep_step["params"]
    assert params["cache_release"] == "114"
    assert params["fork"] == 0
    assert isinstance(params["flags"], list)
    # Sanity-check the flag list carries the production-defining VEP flags
    # so a future regression that drops e.g. --mane_select surfaces here.
    for required_flag in ("--mane_select", "--hgvs", "--symbol", "--canonical", "--cache"):
        assert required_flag in params["flags"], (
            f"missing required flag in provenance.params.flags: {required_flag}"
        )
    # Plugins: both LoF + AlphaMissense were staged in the reference layout,
    # so both must appear in the recorded plugin list.
    plugins = params["plugins"]
    assert isinstance(plugins, list)
    plugin_names = {p.split(",", 1)[0] for p in plugins}
    assert plugin_names == {"LoF", "AlphaMissense"}, (
        f"unexpected plugin set in provenance: {plugin_names}"
    )

    # Skip accounting (decoy-variant-provenance plan, 2026-05-15): every
    # ``vep`` step must record the per-run skipped-variant total + the
    # per-chrom breakdown surfaced by VEP's stderr. Lets a future audit
    # reconcile ``normalize_rowcount - sum(vep_skipped_chroms.values()) ==
    # materialize_rowcount`` without re-running VEP.
    assert params["vep_skipped_variants"] == _STUBBED_VEP_SKIP_STATS.skipped_variants
    assert params["vep_skipped_chroms"] == _STUBBED_VEP_SKIP_STATS.skipped_chroms


def test_invR001_annotate_vep_records_skip_breakdown_in_provenance(
    genomeclaw_layout: dict[str, Path],
    stubbed_vep: list[VepConfig],  # noqa: ARG001
) -> None:
    """``INV-R001`` extension: pin the field name + dict shape of the
    decoy-skip breakdown so a future refactor that renames the keys
    surfaces here.

    Field contract (decoy-variant-provenance plan):
    - ``vep_skipped_variants`` is an int (the aggregate skip count)
    - ``vep_skipped_chroms`` is a ``dict[str, int]`` mapping contig name
      to per-chrom skip count.

    Both live under the ``vep`` step's ``params`` block; the rest of the
    block is exercised by ``test_invR001_annotate_vep_appends_step_to_provenance``.
    """
    reference_dir = genomeclaw_layout["reference"]
    _stage_vep_reference(reference_dir, with_plugins=True)
    run_dir = _stage_run_dir(genomeclaw_layout)

    annotate_vep_module.annotate_vep(
        run_dir=run_dir,
        reference_dir=reference_dir,
    )

    provenance = json.loads((run_dir / "provenance.json").read_text())
    vep_step = next((s for s in provenance["steps"] if s["step"] == "vep"), None)
    assert vep_step is not None
    params = vep_step["params"]

    skipped_total = params["vep_skipped_variants"]
    assert isinstance(skipped_total, int)
    assert skipped_total == _STUBBED_VEP_SKIP_STATS.skipped_variants

    per_chrom = params["vep_skipped_chroms"]
    assert isinstance(per_chrom, dict)
    assert all(isinstance(k, str) for k in per_chrom)
    assert all(isinstance(v, int) for v in per_chrom.values())
    # Sum of per-chrom counts equals the aggregate — defends the audit-
    # trail invariant the field is there to support.
    assert sum(per_chrom.values()) == skipped_total
    assert per_chrom == _STUBBED_VEP_SKIP_STATS.skipped_chroms


def test_invR001_annotate_vep_records_no_plugins_when_data_absent(
    genomeclaw_layout: dict[str, Path],
    stubbed_vep: list[VepConfig],  # noqa: ARG001
) -> None:
    """``INV-R001`` corollary: when plugin data is absent from the reference
    layout, the recorded ``params.plugins`` list is empty.

    Defends the "partial reference layouts still annotate everything they
    can" contract documented in ``_resolve_plugins``: a user who fetched
    only the VEP cache (no LOFTEE / AlphaMissense data) gets a valid run
    whose provenance honestly reflects that no plugins ran. A future
    regression that hard-codes a plugin into the orchestrator would
    surface here.
    """
    reference_dir = genomeclaw_layout["reference"]
    _stage_vep_reference(reference_dir, with_plugins=False)
    run_dir = _stage_run_dir(genomeclaw_layout)

    annotate_vep_module.annotate_vep(
        run_dir=run_dir,
        reference_dir=reference_dir,
    )

    provenance = json.loads((run_dir / "provenance.json").read_text())
    vep_step = next((s for s in provenance["steps"] if s["step"] == "vep"), None)
    assert vep_step is not None
    assert vep_step["params"]["plugins"] == []


def test_annotate_vep_threads_reference_fasta_to_vep_config(
    genomeclaw_layout: dict[str, Path],
    stubbed_vep: list[VepConfig],
) -> None:
    """The orchestrator resolves ``reference/grch38/<release>/grch38.fa.gz``
    and threads it to ``VepConfig.reference_fasta``.

    Without this, VEP's ``--hgvs`` flag fails in offline mode with
    ``ERROR: Cannot generate HGVS coordinates (--hgvs and --hgvsg) in
    offline mode without a FASTA file`` — discovered in the 2026-05-14
    real-data smoke after 1.5h of compute. This test would have caught
    it in milliseconds.
    """
    reference_dir = genomeclaw_layout["reference"]
    _stage_vep_reference(reference_dir, with_plugins=True, with_grch38=True)
    run_dir = _stage_run_dir(genomeclaw_layout)

    annotate_vep_module.annotate_vep(
        run_dir=run_dir,
        reference_dir=reference_dir,
    )

    assert len(stubbed_vep) == 1
    expected_fasta = reference_dir / "grch38" / "ncbi-2014" / "grch38.fa.gz"
    assert stubbed_vep[0].reference_fasta == expected_fasta, (
        f"VepConfig.reference_fasta should be {expected_fasta}, "
        f"got {stubbed_vep[0].reference_fasta}"
    )


def test_invR001_annotate_vep_records_reference_fasta_in_provenance(
    genomeclaw_layout: dict[str, Path],
    stubbed_vep: list[VepConfig],  # noqa: ARG001
) -> None:
    """The ``vep`` provenance step records the reference FASTA path + sha256
    so a rerun against the same FASTA produces byte-equivalent HGVS columns.

    Defends INV-R001 for the new FASTA dependency — same shape as the
    existing input recording (vcfanno.vcf.gz path + sha256).
    """
    reference_dir = genomeclaw_layout["reference"]
    _stage_vep_reference(reference_dir, with_plugins=True, with_grch38=True)
    run_dir = _stage_run_dir(genomeclaw_layout)

    annotate_vep_module.annotate_vep(
        run_dir=run_dir,
        reference_dir=reference_dir,
    )

    provenance = json.loads((run_dir / "provenance.json").read_text())
    vep_step = next((s for s in provenance["steps"] if s["step"] == "vep"), None)
    assert vep_step is not None
    fasta_input = next((i for i in vep_step["inputs"] if "grch38.fa.gz" in i["path"]), None)
    assert fasta_input is not None, (
        f"vep step missing grch38.fa.gz input: inputs={[i['path'] for i in vep_step['inputs']]}"
    )
    assert len(fasta_input["sha256"]) == 64
