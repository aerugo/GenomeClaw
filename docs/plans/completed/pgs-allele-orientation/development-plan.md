# PGS Site Allele Orientation — Development Plan

**Plan**: [spec.md](spec.md) | **Work Notes**: [work-notes.md](work-notes.md)
**Lineage**: F7 of [prs-runtime-hardening](../../completed/prs-runtime-hardening/)

---

## Critical Invariants to Respect

- **`INV-D001`** — fasta read read-only; samtools faidx queries don't mutate.
- **`INV-D003`** — orientation step runs in `shard_scratch`; no persisted artifacts beyond the existing tier2.vcf.gz.
- **`INV-R001`** — `tier2.qc.json` records orientation counts so the cache key + provenance reflect the correction.
- **`INV-R002`** *(v1.14)* — empty-cache guard stays in place; if the orientation result still produces 0 rows (e.g., fasta-CRAM build mismatch), the guard surfaces it.

## Proposed New Invariants

**None.** The orientation fix is a correctness improvement to an existing flow; no cross-cutting rule is introduced.

## Current State Analysis

**What's already in place** (from prs-input-coverage-fill + prs-runtime-hardening):

- `_extract_pgs_sites_from_scorefile(scorefile_path) -> list[tuple[str, int, str, str]]` parses the scorefile, returns `(chr<N>, hm_pos, other_allele, effect_allele)`. **Assumes other_allele is REF — this is the bug.**
- `_force_genotype_tier2(*, cram_path, pgs_rows, fasta, output_vcf)` writes sites + alleles TSVs from `pgs_rows`, runs the bcftools pipe, validates non-empty output (INV-R002 guard).
- `prepare_coverage_tier2(*, sample_id, cram_path, scorefile_path, fasta, panel_version, output_root)` is the orchestrator that calls `_extract_pgs_sites_from_scorefile`, then `_force_genotype_tier2`.
- The wrapper already has access to the FASTA via the `fasta` parameter — so the orientation step can run without new plumbing.

**What's left for THIS plan to deliver:**

1. `_get_reference_bases(fasta_path, sites) -> dict[(chrom, pos), str]` — bulk reference-base lookup via `samtools faidx <fasta> -r <regions_file>`.
2. `_orient_pgs_sites_against_fasta(rows, fasta_path) -> tuple[list[oriented_row], int]` — per-row orientation; returns (kept_rows, skipped_count).
3. Wire the orientation step into `prepare_coverage_tier2` between extraction and `_force_genotype_tier2`.
4. Extend `tier2.qc.json` schema with `orientation_skipped_count` + `orientation_swapped_count`.
5. Tests covering the three orientation cases + the batch-faidx parser + integration coverage of the wired path.

## Solution Design

**Single phase, TDD.**

### `_get_reference_bases(fasta_path, sites)`

```python
def _get_reference_bases(
    fasta_path: Path,
    sites: list[tuple[str, int]],
) -> dict[tuple[str, int], str]:
    """Batch-fetch the reference base at each (chrom, pos) via
    ``samtools faidx -r <regions>``.

    Returns a dict keyed by (chrom, pos), values uppercased single bases.
    Sites that samtools can't resolve (out-of-range pos, missing contig)
    are absent from the dict — the orientation step treats those as
    skipped.
    """
    with shard_scratch(...) as shard:
        regions = shard / "regions.tsv"
        with regions.open("w") as fh:
            for chrom, pos in sites:
                fh.write(f"{chrom}:{pos}-{pos}\n")
        proc = subprocess.run(
            ["samtools", "faidx", str(fasta_path), "-r", str(regions)],
            capture_output=True, check=False,
        )
        if proc.returncode != 0:
            raise SamtoolsError(...)
        return _parse_faidx_fasta(proc.stdout.decode())
```

### `_orient_pgs_sites_against_fasta(rows, fasta_path)`

```python
def _orient_pgs_sites_against_fasta(
    rows: list[tuple[str, int, str, str]],  # (chrom, pos, other, effect)
    fasta_path: Path,
) -> tuple[list[tuple[str, int, str, str]], int, int]:
    """Returns (kept_oriented_rows, skipped_count, swapped_count).

    For each row:
    - actual_ref = ref_bases[(chrom, pos)]
    - if actual_ref == other: KEEP (REF=other, ALT=effect) — original assumption holds
    - if actual_ref == effect: SWAP (REF=effect, ALT=other) — orientation reversed
    - else: SKIP (count toward skipped; tri-allelic / wrong-build / strand)
    """
    sites = [(c, p) for (c, p, _, _) in rows]
    ref_bases = _get_reference_bases(fasta_path, sites)
    kept, skipped, swapped = [], 0, 0
    for chrom, pos, other, effect in rows:
        actual_ref = ref_bases.get((chrom, pos), "").upper()
        other_u, effect_u = other.upper(), effect.upper()
        if not actual_ref:
            skipped += 1
        elif actual_ref == other_u:
            kept.append((chrom, pos, other, effect))  # REF=other, ALT=effect
        elif actual_ref == effect_u:
            kept.append((chrom, pos, effect, other))  # REF=effect, ALT=other (swapped)
            swapped += 1
        else:
            skipped += 1
    return kept, skipped, swapped
```

### Wire into `prepare_coverage_tier2`

```python
# Existing flow:
pgs_rows = _extract_pgs_sites_from_scorefile(scorefile_path)

# NEW after extraction, before force-genotype:
oriented_rows, skipped, swapped = _orient_pgs_sites_against_fasta(pgs_rows, fasta)

# Pass oriented_rows (NOT raw pgs_rows) to _force_genotype_tier2:
_force_genotype_tier2(cram_path=cram_path, pgs_rows=oriented_rows, ...)

# Record the orientation stats in tier2.qc.json:
qc.update({
    "orientation_input_count": len(pgs_rows),
    "orientation_kept_count": len(oriented_rows),
    "orientation_skipped_count": skipped,
    "orientation_swapped_count": swapped,
})
```

### `tier2.qc.json` schema extension

Bump the `schema_version` (currently "1") to "2" + add the four counts:
- `orientation_input_count` (raw extracted SNP rows)
- `orientation_kept_count` (rows that survived orientation)
- `orientation_skipped_count` (neither allele matched the reference)
- `orientation_swapped_count` (REF/ALT swapped from the scorefile assumption)

Existing fields (`total_records`, `gt_distribution`, etc.) are preserved.

## Phase Overview

| Phase | TDD focus | Tests | Promotes |
|-------|-----------|-------|----------|
| **Phase 1** (this plan, single phase) | Orientation helper + integration + QC schema bump | 5 new tests (parser + 3 orientation cases + wired integration) | — (no new invariants) |

## Testing Strategy

### Unit Tests
- `test_parse_faidx_fasta` — parses the samtools faidx output format
  ```
  >chr1:12345-12345
  A
  >chr1:67890-67890
  C
  ```
  into `dict[(chrom, pos), base]`.
- `test_orient_pgs_sites_keeps_correct_orientation` — site where other_allele matches reference; kept as-is.
- `test_orient_pgs_sites_swaps_reversed_orientation` — site where effect_allele matches reference; REF/ALT swapped.
- `test_orient_pgs_sites_skips_when_neither_matches` — tri-allelic-style; counted, not silently dropped.

### Integration Tests
- `test_prepare_coverage_tier2_orients_before_force_genotype` — stubbed subprocess + fake fasta lookup; asserts:
  - The alleles TSV passed to bcftools has the corrected REF/ALT.
  - `tier2.qc.json` carries the new orientation counts.
  - Skipped sites don't appear in the alleles TSV.

### Real-tool smoke
- Smoke v18 against `MPNRGLQ2K.cram` + PGS000018. Acceptance: Tier 2 produces > 1M records (orientation-skipped count documented in QC json); pgsc_calc match rate > 75%; `pgs_scores` row materialised with non-null percentile.

## Documentation Updates

- [docs/plans/completed/prs-runtime-hardening/work-notes.md](../../completed/prs-runtime-hardening/work-notes.md): F7 closed; cross-link to this plan.
- This plan's `work-notes.md`: session log + smoke v18 trace.
- No INVARIANTS.md update needed (no new invariants).
- No architecture.md update needed.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 — orientation helper + integration + smoke | Complete | 2026-05-20 | 2026-05-20 | TDD: RED → GREEN → REFACTOR. Orientation helper + Tier 2 wiring + tier2.qc.json schema v1 → v2 + sort fix (smoke v20 follow-up). 8 new + 1 sort-fix regression test; 22/22 tier2 suite green; 710 passed / 108 skipped / 0 failed full suite. Smoke v18 produced first oriented Tier 2 records; smoke v21 hit pgsc_calc's `--min_overlap 0.75` gate at 52.97% match rate (input-class-mismatch, not an orientation bug). **Smoke-gate for "real `pgs_scores` row" transferred to [prs-non-imputed-wgs](../prs-non-imputed-wgs/) Phase 4 smoke v22.** |

**Plan status**: Closed 2026-05-20. Moved to `docs/plans/completed/pgs-allele-orientation/`. See [work-notes.md § 2026-05-20 — Plan closed (smoke-gate transferred to prs-non-imputed-wgs)](work-notes.md) for the close-out rationale.
