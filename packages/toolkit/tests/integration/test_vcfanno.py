"""Phase 4C.2 — ``vcfanno`` subprocess wrapper unit tests.

The wrapper has three concerns:
1. **TOML config rendering** — `build_vcfanno_toml(configs)` produces
   the inline TOML vcfanno consumes. Pure-Python; host-runnable.
2. **Subprocess execution** — `run_vcfanno(...)` shells out to the
   ``vcfanno`` binary. Needs the binary; in-image only.
3. **Version capture** — `vcfanno_version()` parses ``vcfanno`` (no
   ``--version`` flag; the program prints its banner to stderr on
   first arg and includes the version there). Needs the binary.

These tests cover the host-runnable surface (concern 1). End-to-end
``run_vcfanno`` behaviour is exercised by the orchestrator tests in
``test_annotate_vcfanno.py`` (in-image, needs_bio).
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_build_vcfanno_toml_single_source() -> None:
    """A single ``VcfannoConfig`` renders as one ``[[annotation]]`` block."""
    from genomeclaw_toolkit.prep._vcfanno import VcfannoConfig, build_vcfanno_toml

    toml = build_vcfanno_toml(
        (
            VcfannoConfig(
                file=Path("/mnt/genomeclaw/reference/clinvar/2026-04/clinvar.vcf.gz"),
                fields=("CLNSIG", "CLNREVSTAT"),
                names=("clinvar_classification", "clinvar_review_status"),
                ops=("self", "self"),
            ),
        )
    )

    # Structural assertions — exact whitespace is up to the TOML
    # renderer, but the keys and values must be present and in the
    # vcfanno-canonical block shape.
    assert "[[annotation]]" in toml
    assert 'file = "/mnt/genomeclaw/reference/clinvar/2026-04/clinvar.vcf.gz"' in toml
    assert 'fields = ["CLNSIG", "CLNREVSTAT"]' in toml
    assert 'names = ["clinvar_classification", "clinvar_review_status"]' in toml
    assert 'ops = ["self", "self"]' in toml


def test_build_vcfanno_toml_multiple_sources() -> None:
    """Multiple ``VcfannoConfig``s render as multiple ``[[annotation]]`` blocks in order."""
    from genomeclaw_toolkit.prep._vcfanno import VcfannoConfig, build_vcfanno_toml

    toml = build_vcfanno_toml(
        (
            VcfannoConfig(
                file=Path("/r/clinvar.vcf.gz"),
                fields=("CLNSIG",),
                names=("clinvar_classification",),
                ops=("self",),
            ),
            VcfannoConfig(
                file=Path("/r/gnomad-exomes/by_chrom/chr1.vcf.bgz"),
                fields=("AF_grpmax_joint",),
                names=("gnomad_af_popmax",),
                ops=("self",),
            ),
            VcfannoConfig(
                file=Path("/r/dbsnp.vcf.gz"),
                fields=("RS",),
                names=("dbsnp_rsid",),
                ops=("self",),
            ),
        )
    )

    # Three [[annotation]] blocks; each block's file appears exactly once.
    assert toml.count("[[annotation]]") == 3
    assert "/r/clinvar.vcf.gz" in toml
    assert "/r/gnomad-exomes/by_chrom/chr1.vcf.bgz" in toml
    assert "/r/dbsnp.vcf.gz" in toml
    # Order: ClinVar first, gnomAD next, dbSNP last (matches the
    # canonical pipeline ordering for downstream materialize predictability).
    assert toml.index("clinvar.vcf.gz") < toml.index("gnomad-exomes")
    assert toml.index("gnomad-exomes") < toml.index("dbsnp.vcf.gz")


def test_build_vcfanno_toml_rejects_mismatched_lengths() -> None:
    """`fields` / `names` / `ops` must have the same length within one block."""
    from genomeclaw_toolkit.prep._vcfanno import VcfannoConfig

    with pytest.raises(ValueError, match="length"):
        VcfannoConfig(
            file=Path("/r/clinvar.vcf.gz"),
            fields=("CLNSIG", "CLNREVSTAT"),
            names=("clinvar_classification",),  # one short
            ops=("self", "self"),
        )


# ---------------------------------------------------------------------------
# run_vcfanno — stderr streaming + error-tail behavior
#
# A real ``vcfanno`` binary is not on the host venv path. We stand up a
# tiny Python shim on ``PATH`` that mimics what the wrapper depends on:
# writes a line to stdout (becomes the plain VCF), writes a few lines
# to stderr (mimics vcfanno's progress markers), and exits 0 (or 7 for
# the error path). ``bgzip`` is also stubbed since the success path
# pipes the intermediate through it.
# ---------------------------------------------------------------------------


def _install_shim(
    bin_dir: Path,
    name: str,
    *,
    stdout: str = "",
    stderr_lines: tuple[str, ...] = (),
    exit_code: int = 0,
) -> None:
    """Write an executable Python shim that mimics one of the binaries."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    script = bin_dir / name
    stderr_block = "\n".join(
        f'    sys.stderr.write({line!r} + "\\n"); sys.stderr.flush()' for line in stderr_lines
    )
    script.write_text(
        "#!/usr/bin/env python3\n"
        "import sys\n"
        "def main():\n"
        f"    sys.stdout.write({stdout!r})\n"
        f"{stderr_block or '    pass'}\n"
        f"    sys.exit({exit_code})\n"
        "main()\n"
    )
    script.chmod(0o755)


def test_run_vcfanno_streams_stderr_to_parent_in_real_time(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture
) -> None:
    """``run_vcfanno`` must surface vcfanno's stderr to ``sys.stderr`` as it arrives.

    Without this, a multi-minute vcfanno run on real-scale data looks
    like a silent stall — the user's prior pipeline run was waiting on
    exactly this surface.
    """
    from genomeclaw_toolkit.prep._vcfanno import run_vcfanno

    bin_dir = tmp_path / "bin"
    _install_shim(
        bin_dir,
        "vcfanno",
        stdout="##fileformat=VCFv4.2\n",
        stderr_lines=(
            "vcfanno version 0.3.5",
            "annotated 100000 variants in 30.4s (3300/second)",
        ),
        exit_code=0,
    )
    _install_shim(bin_dir, "bgzip", stdout="")
    monkeypatch.setenv(
        "PATH", f"{bin_dir}:{monkeypatch.delenv('PATH', raising=False) or '/usr/bin:/bin'}"
    )

    work_dir = tmp_path / "work"
    output = tmp_path / "out.vcf.gz"
    run_vcfanno(
        input_vcf=tmp_path / "input.vcf.gz",  # unread by the shim
        output_vcf=output,
        config_toml=('[[annotation]]\nfile = "x"\nfields = ["X"]\nnames = ["x"]\nops = ["self"]\n'),
        work_dir=work_dir,
    )

    captured = capfd.readouterr()
    assert "vcfanno version 0.3.5" in captured.err
    assert "annotated 100000 variants" in captured.err


def test_run_vcfanno_raises_with_stderr_tail_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Non-zero exit raises ``VcfannoError`` carrying the captured stderr tail."""
    from genomeclaw_toolkit.prep._vcfanno import VcfannoError, run_vcfanno

    bin_dir = tmp_path / "bin"
    _install_shim(
        bin_dir,
        "vcfanno",
        stdout="",
        stderr_lines=(
            "vcfanno version 0.3.5",
            "Error: no such file or directory: clinvar.vcf.gz",
        ),
        exit_code=7,
    )
    _install_shim(bin_dir, "bgzip", stdout="")
    monkeypatch.setenv(
        "PATH", f"{bin_dir}:{monkeypatch.delenv('PATH', raising=False) or '/usr/bin:/bin'}"
    )

    with pytest.raises(VcfannoError, match="no such file or directory") as exc_info:
        run_vcfanno(
            input_vcf=tmp_path / "input.vcf.gz",
            output_vcf=tmp_path / "out.vcf.gz",
            config_toml=(
                '[[annotation]]\nfile = "x"\nfields = ["X"]\nnames = ["x"]\nops = ["self"]\n'
            ),
            work_dir=tmp_path / "work",
        )

    assert "rc=7" in str(exc_info.value)
