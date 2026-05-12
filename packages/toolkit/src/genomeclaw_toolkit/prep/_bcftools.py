"""Thin subprocess wrapper around ``bcftools``.

The wrapper isolates three concerns:

1. **Version capture** — ``bcftools --version`` is parsed once at run start
   so the manifest's ``tools`` block can pin both the bcftools version
   and the embedded htslib version (`INV-R001`).
2. **Indexing under ``derived/``** — ``bcftools index --tbi`` writes its
   output next to the input by default. We pass ``--output`` explicitly
   so the index lands inside ``derived/<run-id>/`` and the source under
   ``raw/`` stays unchanged (`INV-D001`, case 10).
3. **Error surfacing** — subprocess failures wrap their stderr into
   ``BcftoolsError`` so callers don't have to dig through CompletedProcess.

The module deliberately doesn't try to be a complete bcftools
abstraction. Each Phase-2 caller stitches together the three primitives
above; specialised wrappers (e.g. ``_bcftools_stats.py``, ``norm`` in
Phase 3) live in their own modules.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_PROGRAM_RE = re.compile(r"^bcftools\s+(\S+)\s*$")
_HTSLIB_RE = re.compile(r"^Using htslib\s+(\S+)\s*$")


@dataclass(frozen=True)
class VersionInfo:
    program: str
    version: str
    htslib_version: str | None


class BcftoolsError(RuntimeError):
    """A ``bcftools`` invocation exited non-zero. Stderr is captured in
    the exception message so the user sees the actual error.
    """


def parse_version_output(stdout: bytes) -> VersionInfo:
    """Parse ``bcftools --version`` stdout.

    The first line must be ``bcftools <version>``. The second line, when
    present, is ``Using htslib <version>``. Trailing license / copyright
    lines are ignored.

    Raises:
        ValueError: if the first line isn't a bcftools version banner.
    """
    text = stdout.decode("utf-8", errors="replace")
    lines = text.splitlines()
    if not lines:
        raise ValueError("bcftools --version produced empty output")

    program_match = _PROGRAM_RE.match(lines[0])
    if not program_match:
        raise ValueError(
            f"unexpected bcftools --version banner: {lines[0]!r} "
            "(expected first line to start with 'bcftools ')"
        )

    htslib_version: str | None = None
    for line in lines[1:]:
        m = _HTSLIB_RE.match(line)
        if m:
            htslib_version = m.group(1)
            break

    return VersionInfo(
        program="bcftools",
        version=program_match.group(1),
        htslib_version=htslib_version,
    )


def bcftools_run(args: Sequence[str], *, check: bool = True) -> subprocess.CompletedProcess[bytes]:
    """Run ``bcftools <args>`` capturing stdout + stderr.

    Args:
        args: arguments to pass to ``bcftools``; e.g. ``["index", "--tbi", path]``.
        check: when True (default), non-zero exit raises ``BcftoolsError``
            with the captured stderr.
    """
    proc = subprocess.run(
        ["bcftools", *args],
        capture_output=True,
        check=False,
    )
    if check and proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        raise BcftoolsError(
            f"bcftools {' '.join(args)!s} failed (rc={proc.returncode}):\n{stderr_text}"
        )
    return proc


def bcftools_version() -> VersionInfo:
    """Capture the running ``bcftools`` version + embedded htslib version."""
    proc = bcftools_run(["--version"])
    return parse_version_output(proc.stdout)


def bcftools_index_tbi(*, vcf: Path, derived_dir: Path) -> Path:
    """Build a tabix ``.tbi`` index for ``vcf``, writing it under ``derived_dir``.

    Per `INV-D001` / case 10: the index file is *never* placed alongside
    the source VCF. The output path is always ``derived_dir/<vcf-name>.tbi``.

    Args:
        vcf: path to a bgzipped VCF (under ``raw/``).
        derived_dir: target directory for the index; typically
            ``/mnt/genomeclaw/derived/<run-id>/``.

    Returns:
        Path to the freshly-written ``.tbi`` index.
    """
    derived_dir.mkdir(parents=True, exist_ok=True)
    out = derived_dir / f"{vcf.name}.tbi"
    bcftools_run(
        [
            "index",
            "--tbi",
            "--output",
            str(out),
            str(vcf),
        ]
    )
    return out


def bcftools_annotate_clinvar(
    *,
    input_vcf: Path,
    clinvar_vcf: Path,
    output_vcf: Path,
) -> None:
    """Overlay ClinVar's ``CLNSIG`` / ``CLNREVSTAT`` INFO fields onto ``input_vcf``.

    Output INFO fields are renamed to ``clinvar_classification`` and
    ``clinvar_review_status`` to match the v0.2 schema. The destination
    header lines are added via ``-H``.

    Args:
        input_vcf: bgzipped VCF to annotate (must be tabix-indexed).
        clinvar_vcf: bgzipped + tabix-indexed ClinVar VCF.
        output_vcf: target bgzipped VCF; parent dir created if missing.

    Raises:
        BcftoolsError: subprocess exit non-zero. Stderr captured.

    Why ``bcftools annotate`` and not ``vcfanno``: on a 4.8M-variant +
    3M-ClinVar pair, vcfanno's Go-runtime workers entered ``futex_wait``
    at end-of-stream and never closed stdout, leaving the downstream
    bgzip writer blocked indefinitely (reproduced with ``-p 1``,
    /tmp-staged inputs, and overlay-backed scratch). bcftools annotate
    is single-process, well-tested at this scale, and shares its
    dependency footprint with the rest of the toolkit.
    """
    output_vcf.parent.mkdir(parents=True, exist_ok=True)
    bcftools_run(
        [
            "annotate",
            "-a",
            str(clinvar_vcf),
            "-c",
            "INFO/clinvar_classification:=INFO/CLNSIG,INFO/clinvar_review_status:=INFO/CLNREVSTAT",
            "-H",
            (
                "##INFO=<ID=clinvar_classification,Number=.,Type=String,"
                'Description="ClinVar CLNSIG (clinical significance) — '
                'overlaid by genomeclaw pipeline annotate.">'
            ),
            "-H",
            (
                "##INFO=<ID=clinvar_review_status,Number=.,Type=String,"
                'Description="ClinVar CLNREVSTAT (review status) — '
                'overlaid by genomeclaw pipeline annotate.">'
            ),
            "-O",
            "z",
            "-o",
            str(output_vcf),
            str(input_vcf),
        ]
    )


__all__ = [
    "BcftoolsError",
    "VersionInfo",
    "bcftools_annotate_clinvar",
    "bcftools_index_tbi",
    "bcftools_run",
    "bcftools_version",
    "parse_version_output",
]
