# Phase 1: Orientation helper + Tier 2 integration + smoke v18

**Status**: In progress
**Started**: 2026-05-20
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Wire per-site reference-base lookup into the Tier 2 forced-genotyping flow so `bcftools call --constrain alleles` accepts the wrapper's emitted alleles file. Land the fix end-to-end + validate by running the real-data smoke against `MPNRGLQ2K.cram` + PGS000018.

## Scope

- New: `_get_reference_bases(fasta, sites)` (bulk samtools faidx wrapper) + `_orient_pgs_sites_against_fasta(rows, fasta)` (per-row orientation).
- Modified: `prepare_coverage_tier2` invokes orientation between extract + force-genotype; `tier2.qc.json` schema bumped to v2 with orientation counts.
- New tests: 6 unit + 1 integration (per work-notes).
- Real-tool smoke v18 as the validation gate.

## TDD Steps

### Step 1.1 — RED

Write 7 tests as listed in work-notes. Tests fail with `ImportError` until `_orient_pgs_sites_against_fasta` exists.

### Step 1.2 — GREEN

1. Add `_parse_faidx_fasta(text) -> dict[(chrom, pos), base]`.
2. Add `_get_reference_bases(fasta, sites) -> dict[(chrom, pos), base]` (bulk samtools faidx).
3. Add `_orient_pgs_sites_against_fasta(rows, fasta) -> (kept, skipped_count, swapped_count)`.
4. Wire into `prepare_coverage_tier2`: call orientation between extract + force-genotype; pass `oriented_rows` to `_force_genotype_tier2`; update QC json.
5. Bump `SCHEMA_VERSION` from "1" to "2".

### Step 1.3 — REFACTOR

- Ruff + mypy clean.
- Full suite green.
- Image rebuild.
- Smoke v18.

## Files

| Action | Path | Purpose |
|--------|------|---------|
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` | + 3 helpers, wire into `prepare_coverage_tier2`, QC schema v2 |
| MODIFY | `packages/toolkit/tests/integration/test_prs_coverage_fill_tier2.py` | + 7 tests |
| MODIFY | `bin/genomeclaw-prs-smoke` | none expected (driver passes fasta already) |

## Verification

```bash
# Local:
cd packages/toolkit
uv run pytest tests/integration/test_prs_coverage_fill_tier2.py -v --no-header
uv run pytest tests/unit tests/integration tests/invariants --no-header
uv run ruff check src/genomeclaw_toolkit/prep/coverage_fill.py tests/integration/test_prs_coverage_fill_tier2.py
uv run mypy src/genomeclaw_toolkit/prep/coverage_fill.py

# Real-tool smoke:
docker build -t genomeclaw/toolkit:phase6 -f packages/toolkit/Dockerfile packages/toolkit
rm -rf /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/{pgsc_calc_work,derived/prs_coverage/MPNRGLQ2K/v1/pgs}
mkdir -p /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z/pgsc_calc_work
GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:phase6 \
GENOMECLAW_PHASE5_SMOKE_DIR_OVERRIDE=/Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/2026-05-18T22-22-13Z \
  bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018
```

## Completion Criteria

- [ ] 7 new tests pass; full suite green; ruff + mypy clean.
- [ ] Image rebuilt.
- [ ] Smoke v18 produces a non-empty `tier2.vcf.gz` (record count documented in work-notes).
- [ ] Smoke v18's `cli_envelope.json` is a success envelope with `percentile_in_user_ancestry` populated.
- [ ] `tier2.qc.json` schema v2 carries orientation counts.
- [ ] Plan moved to `docs/plans/completed/`.
