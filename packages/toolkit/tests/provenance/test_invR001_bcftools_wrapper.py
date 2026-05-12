"""Phase 2 — ``bcftools`` subprocess wrapper tests.

These cover the **wrapper layer** that lives at
[genomeclaw_toolkit.prep._bcftools][]. The wrapper:

- captures ``bcftools --version`` output into a parsed (program,
  version, htslib) triple so the manifest's ``tools`` block can pin both
  the bcftools and the embedded htslib versions;
- runs ``bcftools index --tbi`` against a VCF, writing the output index
  to a path under ``derived/`` (never alongside the source — Phase 2
  case 10 / `INV-D001`);
- surfaces subprocess errors with full stderr captured.

The version-capture tests run pure-Python against a fake stdout buffer
so they work on the host venv. The actual ``bcftools index`` invocation
is marked ``@pytest.mark.needs_bio`` and runs only inside the
``genomeclaw/toolkit`` image (or on a host that has ``bcftools`` on
PATH).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# The exact stdout from ``bcftools --version`` on the toolkit image as of
# 2026-05-08. New bcftools releases will rev the version + git ref but
# preserve the format. The parser tolerates extra trailing lines
# (e.g. copyright notice).
_BCFTOOLS_VERSION_STDOUT = b"""\
bcftools 1.21
Using htslib 1.21
Copyright (C) 2024 Genome Research Ltd.
License Expat: The MIT/Expat license
This is free software: you are free to change and redistribute it.
There is NO WARRANTY, to the extent permitted by law.
"""


# ---------------------------------------------------------------------------
# Pure-Python tests (host venv): version-string parser
# ---------------------------------------------------------------------------


def test_parse_version_extracts_program_and_htslib_versions() -> None:
    """``bcftools --version`` output yields both the bcftools and htslib versions."""
    from genomeclaw_toolkit.prep._bcftools import parse_version_output

    info = parse_version_output(_BCFTOOLS_VERSION_STDOUT)
    assert info.program == "bcftools"
    assert info.version == "1.21"
    assert info.htslib_version == "1.21"


def test_parse_version_rejects_unexpected_first_line() -> None:
    """If the first line isn't ``bcftools <version>``, refuse rather than guess."""
    from genomeclaw_toolkit.prep._bcftools import parse_version_output

    with pytest.raises(ValueError, match="bcftools"):
        parse_version_output(b"samtools 1.21\nUsing htslib 1.21\n")


def test_parse_version_returns_no_htslib_when_missing() -> None:
    """Older ``bcftools`` builds may omit the htslib line; allow ``None``."""
    from genomeclaw_toolkit.prep._bcftools import parse_version_output

    info = parse_version_output(b"bcftools 1.10.2\n")
    assert info.program == "bcftools"
    assert info.version == "1.10.2"
    assert info.htslib_version is None


# ---------------------------------------------------------------------------
# needs_bio tests: real bcftools subprocess invocations
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_bcftools_version_runs_against_real_binary() -> None:
    """Invoking ``bcftools --version`` on PATH returns a parsed VersionInfo."""
    from genomeclaw_toolkit.prep._bcftools import bcftools_version

    info = bcftools_version()
    assert info.program == "bcftools"
    assert info.version  # at minimum a non-empty version string


@pytest.mark.needs_bio
def test_bcftools_index_writes_under_derived_not_alongside_source(
    tmp_path: Path,
) -> None:
    """Case 10 / `INV-D001`: tabix index lands under derived/, not next to source."""
    import gzip
    import subprocess

    from genomeclaw_toolkit.prep._bcftools import bcftools_index_tbi

    # Build a minimal VCF on the fly: header + one variant, bgzipped.
    raw_dir = tmp_path / "raw"
    derived_dir = tmp_path / "derived"
    raw_dir.mkdir()
    derived_dir.mkdir()

    vcf_text = (
        "##fileformat=VCFv4.2\n"
        "##contig=<ID=chr1,length=248956422>\n"
        '##INFO=<ID=DP,Number=1,Type=Integer,Description="depth">\n'
        "#CHROM\tPOS\tID\tREF\tALT\tQUAL\tFILTER\tINFO\n"
        "chr1\t1000\trs1\tA\tG\t.\tPASS\t.\n"
    )

    # bgzip the file via bcftools view → bgzipped output.
    plain = raw_dir / "tiny.vcf"
    plain.write_text(vcf_text)
    bgz = raw_dir / "tiny.vcf.gz"
    subprocess.run(
        ["bcftools", "view", "-Oz", "-o", str(bgz), str(plain)],
        check=True,
        capture_output=True,
    )

    # Capture source identity before invoking the wrapper.
    source_bytes_before = bgz.read_bytes()

    # Now exercise the wrapper.
    out = bcftools_index_tbi(vcf=bgz, derived_dir=derived_dir)

    # Index lives under derived/, not next to source.
    assert out.parent == derived_dir
    assert out.exists()
    assert not (raw_dir / "tiny.vcf.gz.tbi").exists()

    # Source unchanged at the byte level.
    assert bgz.read_bytes() == source_bytes_before
    # And the tabix file is non-trivial.
    with gzip.open(out, "rb") as fh:
        head = fh.read(8)
    # tabix tbi files start with a 4-byte magic 'TBI\x01'.
    assert head[:4] == b"TBI\x01"


@pytest.mark.needs_bio
def test_bcftools_run_surfaces_stderr_on_failure() -> None:
    """A bad bcftools invocation propagates the stderr in the exception."""
    from genomeclaw_toolkit.prep._bcftools import BcftoolsError, bcftools_run

    with pytest.raises(BcftoolsError) as excinfo:
        bcftools_run(["view", "/nonexistent/not-a-vcf.vcf.gz"])
    assert "Could not" in str(excinfo.value) or "fail" in str(excinfo.value).lower()
