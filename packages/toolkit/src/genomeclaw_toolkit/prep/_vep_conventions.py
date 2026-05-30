"""VEP plugin + invocation conventions, pinned per `INV-T001`.

GenomeClaw wraps Ensembl VEP (`packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py`
+ `annotate_vep.py`); this module captures the conventions that the
wrapper would otherwise hardcode, so a future pin bump that flips a flag
produces a typed test failure rather than a silent annotation regression.

Verified against VEP 114.1 (see `_vep.py` line 169 — the existing
"verified at VEP 114.1" comment; the empirical probe path
`tools/vep/probe-output.txt` is deferred to a follow-up plan).

Per `bioreview-small-fixes` Fix 2 the dataclass adds the
`alphamissense_plugin_args` tuple — the canonical AlphaMissense plugin
arg set that aligns scores to the user's transcript when MANE Select is
active. Without `transcript_match=1` the plugin falls back to gene-level
aggregation and silently emits one score per gene instead of per
transcript.

This is the fourth canonical implementation of `INV-T001` alongside
:class:`PgscCalcConventions`, :class:`CyriusConventions`, and
:class:`PharmCATConventions`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VepConventions:
    """VEP 114.1 invocation + plugin conventions, pinned to one version."""

    verified_against_version: str = "114.1"
    """The VEP release this convention set was verified against. The
    `_vep.py` `build_vep_flags` orchestrator currently bakes flags that
    pass `vep --help` at 114.1; bumping VEP must re-run the probe and
    bump this field. The INV-T001 strict-tools discovery test
    (`test_invT001_strict_tools_have_conventions_dataclass`) fails if
    this field is empty or absent."""

    alphamissense_plugin_args: tuple[str, ...] = (
        "transcript_match=1",
    )
    """Per `bioreview-small-fixes` Fix 2: the canonical AlphaMissense
    plugin args (beyond `file=<path>`, which is path-dependent and is
    added by the orchestrator). `transcript_match=1` aligns scores to
    the user's transcript when MANE Select is active — without it the
    plugin falls back to gene-level aggregation and silently emits one
    score per gene rather than per transcript. See AlphaMissense plugin
    documentation: https://github.com/Ensembl/VEP_plugins/blob/main/AlphaMissense.pm"""

    # ------------------------------------------------------------------
    # vep-mane-plus-clinical Phase 1: MANE Plus Clinical recovery
    # ------------------------------------------------------------------

    mane_flag: str = "--mane"
    """The VEP flag that activates BOTH MANE_SELECT and MANE_PLUS_CLINICAL
    CSQ fields. Replaces the previous `--mane_select` (which activated
    only the Select subset). Per Pozo et al. 2022 (npj Genomic Medicine
    7:59), the 73 MANE Plus Clinical genes carry pathogenic variants in
    alternative transcripts that the Select-only flag silently drops
    from the canonical row. See vep-mane-plus-clinical/initial_findings.md
    Section A for the verification trail."""

    pick_order_flag: str = "--pick_order"
    """VEP's tie-breaking-order flag. We emit it as a forward-compat
    declaration (we don't currently pass `--pick`, so it's a no-op at
    the CSQ-emit layer per VEP's documented behaviour). Emitting it
    makes the flag set self-documenting and ensures any future
    `--pick` adoption breaks ties in the same order as our
    materialize-side `pick_canonical_entry`. See
    initial_findings.md Section B."""

    pick_order_value: str = (
        "rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length"
    )
    """The canonical pVACtools/GDC `--pick_order` ranking. `rank` is
    consequence-impact rank; `mane_select` then `mane_plus_clinical`
    give the two MANE sets priority over CANONICAL/APPRIS/TSL/biotype/
    CCDS/transcript-length tie-breakers. Mirrors the
    `pick_canonical_entry` tier order in `_csq.py`."""

    mane_select_csq_field: str = "MANE_SELECT"
    """The CSQ-header field name VEP populates for MANE Select transcripts
    (with the `--mane` or `--mane_select` flag active). Bound here so
    the materialize layer reads from the dataclass rather than a magic
    string."""

    mane_plus_clinical_csq_field: str = "MANE_PLUS_CLINICAL"
    """The CSQ-header field name VEP populates for MANE Plus Clinical
    transcripts (with the `--mane` flag active — NOT populated under
    `--mane_select` alone). The 73 MANE Plus Clinical genes (MANE v1.5,
    March 2026) get a non-empty value on their respective transcript
    entries; other variants have an empty string."""


def _read_alphamissense_ensembl_release(am_file: Path) -> str | None:
    """Read the AlphaMissense pre-compute file's Ensembl release header.

    The AlphaMissense_hg38.tsv.gz header contains a comment line like
    ``#ensembl_release=111`` recording the release the precomputed
    scores were aligned against. Returns the release string (e.g.
    ``"111"``) or ``None`` if the header is absent or unreadable.

    Reads only the first few KB of the file (gzip-aware), so the call
    is fast even on the multi-GB AlphaMissense bundle.
    """
    import gzip

    if not am_file.exists():
        return None
    opener = gzip.open if am_file.suffix == ".gz" else open
    try:
        with opener(am_file, "rt") as fh:
            for _ in range(50):  # AlphaMissense header is in the first ~10 lines
                try:
                    line = next(fh)
                except StopIteration:
                    break
                if line.startswith("#") and "ensembl" in line.lower():
                    # Expected shape: `#ensembl_release=111` or similar.
                    if "=" in line:
                        return line.split("=", 1)[1].strip()
    except (OSError, EOFError):
        return None
    return None


def _read_vep_cache_release(vep_cache_dir: Path) -> str | None:
    """Read the VEP cache's Ensembl release from `<species>/<release>_<assembly>/info.txt`.

    VEP's offline cache directory layout: `<vep_cache_dir>/<species>/
    <release>_<assembly>/info.txt`. The release is encoded in the directory
    name (e.g. `homo_sapiens/111_GRCh38/`) and also written as a `release`
    line inside `info.txt`. Returns the release string or `None` if the
    cache layout doesn't match expectations (e.g. partial fetch, no info.txt).
    """
    if not vep_cache_dir.exists() or not vep_cache_dir.is_dir():
        return None
    # Look for the canonical homo_sapiens species dir; other species are
    # out of scope for GenomeClaw.
    species_dir = vep_cache_dir / "homo_sapiens"
    if not species_dir.exists():
        # Some installs may place release dirs directly under vep_cache_dir.
        species_dir = vep_cache_dir
    for release_dir in species_dir.iterdir():
        if not release_dir.is_dir():
            continue
        # Release dir name shape: `<release>_<assembly>`, e.g. `111_GRCh38`.
        name = release_dir.name
        if "_" not in name:
            continue
        release_token = name.split("_", 1)[0]
        if not release_token.isdigit():
            continue
        # Confirm by reading info.txt if present.
        info_txt = release_dir / "info.txt"
        if info_txt.exists():
            try:
                for line in info_txt.read_text().splitlines():
                    if line.startswith("release"):
                        # Shape: `release\t111` or `release: 111`.
                        parts = line.replace("\t", " ").replace(":", " ").split()
                        if len(parts) >= 2 and parts[1].isdigit():
                            return parts[1]
            except OSError:
                pass
        return release_token
    return None


def check_alphamissense_vep_release_alignment(reference_root: Path) -> list[str]:
    """Compare AlphaMissense + VEP-cache Ensembl releases; return warning strings.

    Per `bioreview-small-fixes` Fix 2: a mismatched Ensembl release
    between the AlphaMissense pre-compute file and the VEP cache silently
    drops AM scores for transcripts that changed between releases. This
    helper reads both files' Ensembl release markers and emits a
    human-readable warning (not a hard failure — pre-existing installs
    may legitimately be on different releases) when they disagree.

    Returns an empty list when:
    - Either source is absent (graceful skip — the user hasn't fetched
      one of them yet).
    - The releases match.

    Returns a single-element warning list when both sources are present
    but the releases disagree.
    """
    am_root = reference_root / "alphamissense"
    vep_cache_root = reference_root / "vep_cache"

    if not am_root.exists() or not vep_cache_root.exists():
        return []

    # Find the newest AM release dir (matches `_latest_release_dir` in annotate_vep.py).
    am_releases = sorted(
        [d for d in am_root.iterdir() if d.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not am_releases:
        return []
    am_file = am_releases[0] / "AlphaMissense" / "AlphaMissense_hg38.tsv.gz"
    am_release = _read_alphamissense_ensembl_release(am_file)
    if am_release is None:
        return []

    vep_cache_releases = sorted(
        [d for d in vep_cache_root.iterdir() if d.is_dir()],
        key=lambda p: p.name,
        reverse=True,
    )
    if not vep_cache_releases:
        return []
    vep_release = _read_vep_cache_release(vep_cache_releases[0])
    if vep_release is None:
        return []

    if am_release == vep_release:
        return []

    return [
        f"AlphaMissense ↔ VEP cache Ensembl-release mismatch: "
        f"AlphaMissense file at {am_file.name} was computed against Ensembl "
        f"release {am_release}, but the VEP cache at "
        f"{vep_cache_releases[0].name} is release {vep_release}. "
        "AlphaMissense scores will be silently dropped for transcripts that "
        "changed between these releases. Re-fetch the VEP cache at the "
        "matching release, or re-fetch the AlphaMissense bundle for the "
        "current VEP cache release."
    ]


__all__ = [
    "VepConventions",
    "check_alphamissense_vep_release_alignment",
]
