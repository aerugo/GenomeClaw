"""Parse pgsc_calc's per-variant match log for the calibration classifier.

pgsc_calc v2.2.0 emits ``<work_dir>/<nextflow_hash>/<sampleset>_log.csv.gz``
with a per-row ``match_status`` column. The four observed values:

- ``matched``: scoring-file variant successfully matched into a user dosage.
- ``unmatched``: scoring-file variant absent from the user's input — the
  variant-only-VCF problem this whole plan exists to solve.
- ``not_best`` / ``excluded``: duplicate-handling artefacts (the same
  underlying variant also appears under ``matched`` or ``unmatched``).
  Counting them double-counts the variants they describe.

The match rate is ``matched / (matched + unmatched)`` per PGS accession,
mirroring the 2026-05-17 smoke's reported 28.37% on PGS000018:

    matched   = 495,434
    unmatched = 1,249,188
    → match_rate = 0.2839
"""

from __future__ import annotations

import csv
import gzip
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class MatchStats:
    """Per-PGS-accession match statistics from a pgsc_calc log CSV."""

    pgs_accession: str
    matched: int
    unmatched: int
    uncallable_excluded: int = 0
    """Per `INV-C002` (force-genotype-callable-mask Phase 3): number of
    scoring sites excluded from BOTH `matched` and `unmatched` because
    the per-site genotype-source classifier flagged them `uncallable`.
    Zero when `parse_match_stats` is called without `uncallable_sites=`
    or when the sidecar is empty/missing. Surfaced to the agent layer
    via `pgs_scores` provenance so the audit trail records how many
    sites were dropped."""

    @property
    def match_rate(self) -> float:
        """``matched / (matched + unmatched)``; ``0.0`` when both are zero.

        The empty-denominator guard is defensive — :func:`parse_match_stats`
        returns ``None`` rather than zero-count stats, so callers shouldn't
        hit this path in practice. Kept for completeness.
        """
        total = self.matched + self.unmatched
        return self.matched / total if total else 0.0


# Status values that count toward the matched/unmatched totals. Other
# values (``not_best``, ``excluded``, future pgsc_calc additions) are
# silently skipped — they represent duplicate-handling buckets, not
# distinct scoring variants.
_MATCHED = "matched"
_UNMATCHED = "unmatched"


def _normalise_chrom(value: str) -> str:
    """Return `value` with a `chr` prefix.

    pgsc_calc emits bare-chrom (`"1"`, `"22"`, `"X"`); the genotype-source
    sidecar uses `chr`-prefixed names (`"chr1"`, `"chr22"`, `"chrX"`).
    Normalise both sides to `chr`-prefixed so the uncallable-set lookup
    is exact.
    """
    if value.startswith("chr"):
        return value
    return f"chr{value}"


def parse_match_stats(
    log_csv_gz: Path,
    *,
    pgs_accession: str,
    uncallable_sites: set[tuple[str, int]] | None = None,
) -> MatchStats | None:
    """Walk a gzipped pgsc_calc log CSV; return per-accession match stats.

    Args:
        log_csv_gz: Path to ``<sampleset>_log.csv.gz`` inside a pgsc_calc
            Nextflow work-dir hash directory.
        pgs_accession: The PGS Catalog accession the user is computing
            (e.g. ``"PGS000018_hmPOS_GRCh38"``) — note the suffix matches
            pgsc_calc's internal naming.
        uncallable_sites: optional set of `(chrom, pos)` tuples to
            exclude from BOTH `matched` and `unmatched` counts. Per
            proposed `INV-C002` (force-genotype-callable-mask Phase 3):
            sites whose per-site genotype-source classifier value is
            `"uncallable"` must not inflate the PGS denominator. The
            count of excluded sites is reported as
            :attr:`MatchStats.uncallable_excluded`. Chrom prefixes are
            normalised to `"chr"`-style on both sides so the sidecar's
            `"chr1"` matches pgsc_calc's `"1"`.

    Returns:
        :class:`MatchStats` with the counts for that accession, or
        ``None`` when the accession isn't present or the log is empty.
        ``None`` signals to the orchestrator to skip classification
        rather than fabricating a zero-match-rate decline.
    """
    matched = 0
    unmatched = 0
    uncallable_excluded = 0

    # Normalise the uncallable set's chrom prefix to chr-style for the
    # lookup loop; cheaper than per-row normalisation on the sidecar side.
    if uncallable_sites is not None:
        normalised_uncallable = {
            (_normalise_chrom(chrom), pos) for chrom, pos in uncallable_sites
        }
    else:
        normalised_uncallable = set()

    with gzip.open(log_csv_gz, "rt") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "match_status" not in reader.fieldnames:
            return None
        for row in reader:
            if row.get("accession") != pgs_accession:
                continue
            status = row.get("match_status")
            if status not in (_MATCHED, _UNMATCHED):
                # Other status values (``not_best`` / ``excluded`` / future
                # values) are intentionally not counted — see module docstring.
                continue

            # INV-C002 filter: if the site is in the uncallable set,
            # skip it from BOTH counters and tally the exclusion.
            if normalised_uncallable:
                chrom_raw = row.get("chr_name", "")
                pos_raw = row.get("chr_position", "")
                if chrom_raw and pos_raw.isdigit():
                    chrom_norm = _normalise_chrom(chrom_raw)
                    key = (chrom_norm, int(pos_raw))
                    if key in normalised_uncallable:
                        uncallable_excluded += 1
                        continue

            if status == _MATCHED:
                matched += 1
            elif status == _UNMATCHED:
                unmatched += 1

    if matched == 0 and unmatched == 0:
        return None
    return MatchStats(
        pgs_accession=pgs_accession,
        matched=matched,
        unmatched=unmatched,
        uncallable_excluded=uncallable_excluded,
    )


def parse_effect_weights(
    scoring_file: Path,
) -> dict[tuple[str, int, str, str], float] | None:
    """Read the PGS Catalog scoring file's `effect_weight` column into a dict.

    Returns `{(chr-prefixed chrom, int pos, effect_allele, other_allele): |β|}`.
    The keys are normalised to `chr`-prefix on the chrom so they match
    the convention used by :func:`compute_weighted_match_rate` against
    pgsc_calc's `chr_name` column (which is bare-chrom in v2.2.0).

    Returns `None` when the scoring file has no `effect_weight` column —
    common for legacy / non-PGS-Catalog scoring files. The orchestrator
    treats `None` as "weight axis not computable" and falls back to the
    raw count match rate only.

    Accepts both gzipped (.gz) and plain-text scoring files.

    Per `prs-calibration-phase3b` Phase 1 + `INV-C001` v1.7.
    """
    import csv

    opener = gzip.open if scoring_file.suffix == ".gz" else open
    weights: dict[tuple[str, int, str, str], float] = {}
    with opener(scoring_file, "rt", encoding="utf-8") as fh:
        # Skip PGS Catalog comment lines (start with `#`); the column
        # header is the first non-comment line.
        header_line: str | None = None
        comment_pos = fh.tell()
        for line in fh:
            if not line.startswith("#"):
                header_line = line.rstrip("\n")
                break
            comment_pos = fh.tell()
        if header_line is None:
            return None

        fields = header_line.split("\t")
        if "effect_weight" not in fields:
            return None
        try:
            chrom_idx = fields.index("hm_chr")
            pos_idx = fields.index("hm_pos")
            ea_idx = fields.index("effect_allele")
            oa_idx = fields.index("other_allele")
            weight_idx = fields.index("effect_weight")
        except ValueError:
            return None

        for line in fh:
            line = line.rstrip("\n")
            if not line or line.startswith("#"):
                continue
            parts = line.split("\t")
            if len(parts) <= weight_idx:
                continue
            try:
                pos = int(parts[pos_idx])
                weight = abs(float(parts[weight_idx]))
            except (ValueError, IndexError):
                continue
            chrom_raw = parts[chrom_idx]
            chrom = chrom_raw if chrom_raw.startswith("chr") else f"chr{chrom_raw}"
            key = (chrom, pos, parts[ea_idx], parts[oa_idx])
            weights[key] = weight

    return weights


def compute_weighted_match_rate(
    log_csv_gz: Path,
    *,
    pgs_accession: str,
    weight_dict: dict[tuple[str, int, str, str], float] | None,
    uncallable_sites: set[tuple[str, int]] | None = None,
) -> float | None:
    """Compute `Σ|β|_matched / Σ|β|_total` per PGS accession.

    Walks the pgsc_calc per-variant match log; for each row of the
    requested accession, looks up `(chrom, pos, effect_allele,
    other_allele)` in `weight_dict`. Sites in `uncallable_sites` are
    excluded from BOTH numerator and denominator (INV-C003 contract).

    Returns:
        - `None` if `weight_dict` is `None` (no effect_weight column in
          the scoring file → weight axis not computable).
        - `None` if `Σ|β|_total == 0` (defensive guard against div-by-zero).
        - Else the ratio in `[0.0, 1.0]`.

    Per `prs-calibration-phase3b` Phase 1.
    """
    if weight_dict is None:
        return None

    if uncallable_sites is not None:
        normalised_uncallable = {
            (_normalise_chrom(chrom), pos) for chrom, pos in uncallable_sites
        }
    else:
        normalised_uncallable = set()

    matched_weight = 0.0
    total_weight = 0.0
    with gzip.open(log_csv_gz, "rt") as fh:
        reader = csv.DictReader(fh)
        if reader.fieldnames is None or "match_status" not in reader.fieldnames:
            return None
        for row in reader:
            if row.get("accession") != pgs_accession:
                continue
            status = row.get("match_status")
            if status not in (_MATCHED, _UNMATCHED):
                continue
            chrom_raw = row.get("chr_name", "")
            pos_raw = row.get("chr_position", "")
            if not chrom_raw or not pos_raw.isdigit():
                continue
            pos = int(pos_raw)
            chrom_norm = _normalise_chrom(chrom_raw)
            if (chrom_norm, pos) in normalised_uncallable:
                continue
            ea = row.get("effect_allele", "")
            oa = row.get("other_allele", "")
            key = (chrom_norm, pos, ea, oa)
            weight = weight_dict.get(key)
            if weight is None:
                continue
            total_weight += weight
            if status == _MATCHED:
                matched_weight += weight

    if total_weight == 0:
        return None
    return matched_weight / total_weight


def load_uncallable_sites_from_sidecar(sidecar_path: Path) -> set[tuple[str, int]]:
    """Read a genotype-source sidecar TSV; return the `uncallable` site set.

    Per `INV-C002`: the sidecar (5-col TSV produced by
    :func:`genomeclaw_toolkit.prep._genotype_source.write_genotype_source_sidecar`)
    carries one row per force-genotyped site with a `genotype_source`
    in the four-class enum. This helper extracts only the `uncallable`
    rows into a `(chrom, pos)` set, ready to pass as
    `uncallable_sites=` to :func:`parse_match_stats`.

    A missing sidecar returns an empty set (no filter applied) — the
    plan's fallback policy when the operator hasn't fetched GIAB or
    when Phase 2's classifier hasn't run.
    """
    if not sidecar_path.exists():
        return set()
    sites: set[tuple[str, int]] = set()
    with sidecar_path.open("r", encoding="utf-8") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        if reader.fieldnames is None or "genotype_source" not in reader.fieldnames:
            return set()
        for row in reader:
            if row.get("genotype_source") != "uncallable":
                continue
            chrom = row.get("chrom", "")
            pos_raw = row.get("pos", "")
            if chrom and pos_raw.isdigit():
                sites.add((chrom, int(pos_raw)))
    return sites


def find_pgsc_calc_log_csv(work_dir: Path, *, sampleset: str) -> Path | None:
    """Recursively glob ``<work_dir>`` for a pgsc_calc per-variant match log.

    pgsc_calc's Nextflow work-dir has the shape
    ``<work>/<two_hex>/<long_hex>/<sampleset>_log.csv.gz``. The orchestrator
    doesn't know the hash names ahead of time, so the parser uses a glob.

    Discovery strategy (Phase 4 follow-up — 2026-05-26 smoke surfaced
    that pgsc_calc internally derives the sampleset from the merged-norm
    VCF basename, NOT from the orchestrator's ``--sample`` arg; globbing
    by the exact sampleset therefore mismatches the on-disk filename):

    1. Prefer the strict ``<sampleset>_log.csv.gz`` match when one
       exists — keeps the original contract for callers that DO know the
       on-disk sampleset.
    2. Otherwise fall back to ``*_log.csv.gz`` and return the first
       match. pgsc_calc emits one match log per run (with the per-PGS
       accession filter applied downstream by :func:`parse_match_stats`),
       so a single glob match is the expected case.

    Returns ``None`` only when no ``*_log.csv.gz`` exists anywhere under
    the work-dir — the orchestrator then skips classification.
    """
    strict = sorted(work_dir.rglob(f"{sampleset}_log.csv.gz"))
    if strict:
        return strict[0]
    flexible = sorted(work_dir.rglob("*_log.csv.gz"))
    return flexible[0] if flexible else None


__all__ = [
    "MatchStats",
    "compute_weighted_match_rate",
    "find_pgsc_calc_log_csv",
    "load_uncallable_sites_from_sidecar",
    "parse_effect_weights",
    "parse_match_stats",
]
