"""VCF-header reference-build sniffer.

Parses ``##contig=<ID=...,length=...>`` records into a list of
``(contig_name, length)`` pairs and matches them against a small built-in
lookup of canonical chromosome lengths per build. All canonical contigs
in the VCF must agree with one and only one build.

The lookup is intentionally tiny (autosomes 1–22 + X + Y + MT for GRCh37
and GRCh38). Non-canonical contigs (HLA-*, chrEBV, GL000* decoys, etc.)
are ignored — short-read pipelines emit them routinely and they don't
identify the build.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from typing import Final, Literal, get_args

ReferenceBuild = Literal["grch37", "grch38"]

_KNOWN_BUILDS: Final[frozenset[str]] = frozenset(get_args(ReferenceBuild))


class AmbiguousReferenceBuild(ValueError):
    """No single build cleanly explains the VCF's contig list.

    Raised when:
    - All contigs match different builds (mixed-build VCF).
    - No canonical contigs are present (empty / non-canonical only).
    - Some canonical contigs match while others contradict every build.
    """


_GRCH38_CONTIGS: Final[dict[str, int]] = {
    # Chromosomes (UCSC-style ``chr`` prefix).
    "chr1": 248956422,
    "chr2": 242193529,
    "chr3": 198295559,
    "chr4": 190214555,
    "chr5": 181538259,
    "chr6": 170805979,
    "chr7": 159345973,
    "chr8": 145138636,
    "chr9": 138394717,
    "chr10": 133797422,
    "chr11": 135086622,
    "chr12": 133275309,
    "chr13": 114364328,
    "chr14": 107043718,
    "chr15": 101991189,
    "chr16": 90338345,
    "chr17": 83257441,
    "chr18": 80373285,
    "chr19": 58617616,
    "chr20": 64444167,
    "chr21": 46709983,
    "chr22": 50818468,
    "chrX": 156040895,
    "chrY": 57227415,
    "chrM": 16569,
    # Same lengths under Ensembl-style names.
    "1": 248956422,
    "2": 242193529,
    "3": 198295559,
    "4": 190214555,
    "5": 181538259,
    "6": 170805979,
    "7": 159345973,
    "8": 145138636,
    "9": 138394717,
    "10": 133797422,
    "11": 135086622,
    "12": 133275309,
    "13": 114364328,
    "14": 107043718,
    "15": 101991189,
    "16": 90338345,
    "17": 83257441,
    "18": 80373285,
    "19": 58617616,
    "20": 64444167,
    "21": 46709983,
    "22": 50818468,
    "X": 156040895,
    "Y": 57227415,
    "MT": 16569,
}

_GRCH37_CONTIGS: Final[dict[str, int]] = {
    "chr1": 249250621,
    "chr2": 243199373,
    "chr3": 198022430,
    "chr4": 191154276,
    "chr5": 180915260,
    "chr6": 171115067,
    "chr7": 159138663,
    "chr8": 146364022,
    "chr9": 141213431,
    "chr10": 135534747,
    "chr11": 135006516,
    "chr12": 133851895,
    "chr13": 115169878,
    "chr14": 107349540,
    "chr15": 102531392,
    "chr16": 90354753,
    "chr17": 81195210,
    "chr18": 78077248,
    "chr19": 59128983,
    "chr20": 63025520,
    "chr21": 48129895,
    "chr22": 51304566,
    "chrX": 155270560,
    "chrY": 59373566,
    "chrM": 16571,
    "1": 249250621,
    "2": 243199373,
    "3": 198022430,
    "4": 191154276,
    "5": 180915260,
    "6": 171115067,
    "7": 159138663,
    "8": 146364022,
    "9": 141213431,
    "10": 135534747,
    "11": 135006516,
    "12": 133851895,
    "13": 115169878,
    "14": 107349540,
    "15": 102531392,
    "16": 90354753,
    "17": 81195210,
    "18": 78077248,
    "19": 59128983,
    "20": 63025520,
    "21": 48129895,
    "22": 51304566,
    "X": 155270560,
    "Y": 59373566,
    "MT": 16571,
}

_BUILDS: Final[dict[ReferenceBuild, dict[str, int]]] = {
    "grch38": _GRCH38_CONTIGS,
    "grch37": _GRCH37_CONTIGS,
}


def sniff_reference_build(
    contigs: Iterable[tuple[str, int]],
) -> ReferenceBuild:
    """Match a VCF's canonical contigs against the build lookup.

    Args:
        contigs: iterable of ``(name, length)`` pairs from the VCF's
            ``##contig=...`` header lines.

    Returns:
        ``"grch38"`` or ``"grch37"`` when exactly one build matches every
        canonical contig present.

    Raises:
        AmbiguousReferenceBuild: when no canonical contigs match, or when
            any canonical contig contradicts the candidate build, or when
            multiple builds match equally.
    """
    contig_list = list(contigs)

    # For each candidate build, count how many provided contigs are
    # **canonical for that build** (name + length both match) and how
    # many are **canonical-named but length-mismatched** (positively
    # contradicts that build). Non-canonical names are ignored.
    candidates: list[ReferenceBuild] = []
    for build, lookup in _BUILDS.items():
        matches = 0
        contradictions = 0
        for name, length in contig_list:
            if name in lookup:
                if lookup[name] == length:
                    matches += 1
                else:
                    contradictions += 1
        if matches > 0 and contradictions == 0:
            candidates.append(build)

    if len(candidates) == 1:
        return candidates[0]

    raise AmbiguousReferenceBuild(
        f"reference build could not be inferred unambiguously; "
        f"candidates={candidates!r}, contigs={contig_list!r}"
    )


class ReferenceBuildMismatch(ValueError):
    """The reference directory's path positively contradicts the inferred build.

    Raised when one canonical build name appears in the reference path's
    components (e.g. ``grch37``) and the VCF's contig headers infer the
    other one (``grch38``). Catches the common typo where the user picks
    the wrong build directory.
    """


def autodetect_reference_dir(reference_root: Path) -> Path:
    """Resolve a reference build directory under ``reference_root``.

    Scans ``reference_root`` for subdirectories whose names match a known
    build (``grch37`` / ``grch38``). Returns the unique match. Raises
    ``ValueError`` if zero or more than one build directory is present —
    the caller is expected to surface the message to the user with a
    hint to pass ``--reference`` explicitly.

    Non-build subdirectories (``clinvar/``, ``dbsnp/``, ``gnomad-exomes/``,
    etc.) are ignored, so the canonical layout produced by ``genomeclaw
    setup`` resolves cleanly to its single build dir.
    """
    if not reference_root.is_dir():
        raise ValueError(f"reference root not found: {reference_root}")

    build_dirs = sorted(
        p for p in reference_root.iterdir() if p.is_dir() and p.name in _KNOWN_BUILDS
    )
    if not build_dirs:
        raise ValueError(
            f"reference root {reference_root} has no build subdirectories "
            f"(expected one of: {sorted(_KNOWN_BUILDS)}); "
            "run `genomeclaw refs fetch --source grch38 --release <tag>` or pass --reference <path>"
        )
    if len(build_dirs) > 1:
        names = ", ".join(p.name for p in build_dirs)
        raise ValueError(
            f"reference root {reference_root} has multiple build subdirectories ({names}); "
            "pass --reference <path> to pick one"
        )
    return build_dirs[0]


def validate_reference_build_match(reference_dir: Path, build: ReferenceBuild) -> None:
    """Soft-check that ``reference_dir``'s path agrees with the inferred build.

    Walks the components of ``reference_dir`` (resolved). If a known
    build name appears in any component and contradicts ``build``,
    raises ``ReferenceBuildMismatch``. If the inferred build appears, or
    if no known build name appears at all, returns silently — the
    latter covers custom layouts that don't encode the build in the
    path.

    Designed to catch the typo case (user passes ``reference/grch37/``
    but the VCF infers GRCh38) without over-rejecting layouts that
    legitimately omit the build from the path.
    """
    parts_lower = {p.lower() for p in reference_dir.parts}
    contradicting = parts_lower & _KNOWN_BUILDS - {build}
    if contradicting:
        other = sorted(contradicting)[0]
        raise ReferenceBuildMismatch(
            f"reference dir {reference_dir} appears to be a {other} layout, "
            f"but the VCF's contig headers infer {build}; "
            "pass --reference <path> to a directory matching the VCF's build"
        )


__all__ = [
    "AmbiguousReferenceBuild",
    "ReferenceBuild",
    "ReferenceBuildMismatch",
    "autodetect_reference_dir",
    "sniff_reference_build",
    "validate_reference_build_match",
]
