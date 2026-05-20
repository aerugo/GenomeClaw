# PGS Site Allele Orientation — Work Notes

**Plan**: [development-plan.md](development-plan.md) | **Spec**: [spec.md](spec.md)
**Lineage**: F7 of [prs-runtime-hardening](../../completed/prs-runtime-hardening/)

Append-only session log.

---

## 2026-05-20 — Plan creation + RED tests

**Context reviewed**:
- [prs-runtime-hardening/work-notes.md F7 entry](../../completed/prs-runtime-hardening/work-notes.md): smoke v17 surfaced this bug via the empty-cache guard. Manual probe at chr1:21806025 confirmed PGS Catalog scorefile says `A,G` (other=A, effect=G) but GRCh38 reference at that position is `G`, so `bcftools call --constrain alleles` rejects the row with "The reference alleles are not compatible at chr1:21806025 .. A vs G".
- [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py): `_extract_pgs_sites_from_scorefile` (the buggy assumer) + `_force_genotype_tier2` (the consumer) + `prepare_coverage_tier2` (the orchestrator). The wrapper already has `fasta` in scope at the right point — no new plumbing needed.

**Invariants reaffirmed**:
- **INV-D001** — fasta read read-only; samtools faidx is non-mutating.
- **INV-R001** — `tier2.qc.json` gains orientation counts so the cache + provenance reflect the correction.
- **INV-R002** — the empty-cache guard stays in place; if orientation still produces 0 rows (e.g., wrong-build fasta), the guard surfaces it loudly.

**RED test cases** (Phase 1 Step 1.1):

1. `test_parse_faidx_fasta` — parses `>chr1:12345-12345\nA\n>chr1:67890-67890\nC\n` into `dict[(chrom, pos), base]`.
2. `test_get_reference_bases_bulk_query` — stubs samtools subprocess; asserts:
   - regions.tsv has `chr1:12345-12345\n` per input site.
   - Single subprocess call (not N).
3. `test_orient_pgs_sites_keeps_correct_orientation` — site (`chr1`, `100`, `A`, `G`), reference is `A`: returns (`A`, `G`); not swapped.
4. `test_orient_pgs_sites_swaps_reversed_orientation` — site (`chr1`, `100`, `A`, `G`), reference is `G`: returns (`G`, `A`); swapped counter += 1.
5. `test_orient_pgs_sites_skips_when_neither_matches` — site (`chr1`, `100`, `A`, `G`), reference is `T`: skipped (not in output); skipped counter += 1.
6. `test_orient_pgs_sites_skips_when_fasta_lookup_missing` — site whose (chrom, pos) isn't in the ref_bases dict: skipped.
7. `test_prepare_coverage_tier2_orients_before_force_genotype` — integration test: stubbed faidx + bcftools; asserts alleles TSV passed to bcftools has corrected REF/ALT + QC json has the new orientation counts.

**Expected RED**: `ImportError: cannot import name '_orient_pgs_sites_against_fasta' from 'genomeclaw_toolkit.prep.coverage_fill'`.

**RED confirmed**: 8 failures (the 7 listed + the integration test had a small `_re` import bug that I fixed; once fixed, 7 hit ImportError and 1 hit the missing test setup). All 8 then green after GREEN landed.

---

## 2026-05-20 — Phase 1 GREEN

**Code shipped**:

- `coverage_fill.py:_parse_faidx_fasta(text)` — parses samtools faidx multi-record output into `{(chrom, pos): base}`. Uppercases bases (soft-masked tolerance).
- `coverage_fill.py:_get_reference_bases(fasta, sites)` — bulk lookup via single `samtools faidx <fasta> -r <regions>` subprocess. Runs inside `shard_scratch(step="orient_pgs_sites", ...)`. Raises new `SamtoolsError` on rc != 0.
- `coverage_fill.py:_orient_pgs_sites_against_fasta(rows, fasta)` — per-row orientation: KEEP (other=ref), SWAP (effect=ref → REF/ALT swapped), or SKIP (neither). Returns `(kept_rows, skipped_count, swapped_count)`.
- `coverage_fill.py:prepare_coverage_tier2` — wires orientation between `_extract_pgs_sites_from_scorefile` and `_force_genotype_tier2`. Passes `oriented_rows` to bcftools (not raw `pgs_rows`).
- `coverage_fill.py:SCHEMA_VERSION` bumped "1" → "2" — `tier2.qc.json` now carries `orientation_input_count`, `orientation_kept_count`, `orientation_skipped_count`, `orientation_swapped_count` alongside the existing fields.
- `coverage_fill.py:SamtoolsError(RuntimeError)` — new error class for samtools faidx failures.

**Test results**:
- 8/8 new orientation tests green.
- Full suite: **710 passed / 108 skipped / 0 failed** (was 702; +8 from this phase).
- ruff clean on touched files.
- mypy clean on `coverage_fill.py`.

**Test runner fix detail**: the integration test initially had two `import re as _re` inside the closure which created an `UnboundLocalError` (Python's scope inference). Fixed by using the module-level `re` import already at the top of the test file. Also corrected the test's expected positions to match the synthetic scorefile (chr22:20001/20002/20005, not the placeholder chr22:42126499/42126510 I'd put in the initial draft).

**Decisions made**:
1. **Orientation runs inside `prepare_coverage_tier2` (the orchestrator), not inside `_extract_pgs_sites_from_scorefile`**. Extraction stays pure (no fasta dependency); orientation runs at the orchestrator where the fasta is already in scope. Easier to unit-test in isolation.
2. **Single bulk samtools call (not per-site)**. 1.7M individual subprocess calls would be infeasible (process-spawn overhead alone would be hours); a single `samtools faidx -r <regions>` is O(seek) per region against the .fai-indexed bgzip.
3. **Skip count, don't raise** for sites where neither allele matches the reference. Tri-allelic / wrong-build / strand sites are common enough that raising would block normal runs; the count surfaces in tier2.qc.json so a high skip rate flags a setup issue.
4. **No INVARIANTS.md update**. The orientation fix is a correctness improvement to an existing flow, not a new cross-cutting rule. INV-R001 (rebuildability) is implicitly strengthened — the cache key now reflects oriented (not raw) rows.

**Next**: rebuild image + nuke pgsc_calc_work + tier2 cache + run smoke v18.

---

## 2026-05-20 — Plan closed (smoke-gate transferred to prs-non-imputed-wgs)

**Outcome summary**:
- Phase 1 (orientation helper + Tier 2 integration) GREEN. 8 new tests + the 22/22 tier2 suite. Full toolkit suite 710 passed / 108 skipped / 0 failed. ruff + mypy clean.
- Smoke v18 produced the first oriented Tier 2 records (orientation works against the real fasta).
- Smoke v20 caught a follow-up bug — `bcftools index` rejected the alleles file because oriented rows were no longer in chrom/pos order after the SWAP path. Fix: sort `oriented_rows` by `(chrom, pos)` before `_force_genotype_tier2`. Regression test landed; 22/22 tier2 tests green.
- Smoke v21 ran 7586s (2h 6m, peak 7 GiB RSS) before SIGTERM at the background-task system's 2h cap. Tier 1 hit cache cleanly; the kill landed inside pgsc_calc's MATCH_COMBINE region with `--min_overlap 0.75` still rejecting the input class's ~53% match rate.

**Why this plan is closing now, before smoke v18+ produces a `pgs_scores` row**:

This plan's deliverable was the orientation correctness fix at the wrapper layer — the work that turns scorefile rows into reference-correct REF/ALT pairs before `bcftools call --constrain alleles` ever sees them. That work is shipped, tested, and behaves correctly on the real fasta against the real PGS000018 scorefile. The original Phase 1 completion criterion "smoke v18 produces a real `pgs_scores` row" assumed the only remaining gap was orientation. Smoke v18–v21 showed that's not true: a *second* gap (the input-class-inappropriate `--min_overlap 0.75` default; see [docs/reports/prs-real-data-smoke-research-findings.md](../../../reports/prs-real-data-smoke-research-findings.md)) sits between the oriented Tier 2 VCF and the calibrated `pgs_scores` row.

The smoke gate for "a real `pgs_scores` row" has **transferred to [prs-non-imputed-wgs](../prs-non-imputed-wgs/) Phase 4 smoke v22**. That plan exposes `--min_overlap` as per-input-class (default `0.5`), adds `bcftools norm -m -any` upstream, and steers scorefile selection toward HapMap3+/C+T. Combined with this plan's orientation fix, smoke v22 is the new Stage 3 GREEN gate of [prs-bootstrap-meta](../prs-bootstrap-meta.md).

Keeping this plan open would conflate two independent concerns (orientation correctness vs. match-rate-gate calibration) and stretch the smoke ledger past the point where the lineage is informative. Closing here keeps the F7 ledger co-located with the orientation change in the completed/ archive; the post-orientation smoke story continues under prs-non-imputed-wgs.

**Open follow-ups** (none added by this plan; all carried forward from prs-runtime-hardening F3–F7 are still tracked in [prs-bootstrap-meta § Cascade](../prs-bootstrap-meta.md#cascade-of-follow-up-plans-2026-05-18--2026-05-20)):
- F3 host doctor checks for VM resource budget
- F4 sex-info handling for chrX scoring
- F5 `bin/genomeclaw refs materialize` CLI subcommand
- F6 CI gate on `tools/pgsc_calc/probe.sh` pin bumps

F7 was THIS plan and is now closed.

**Plan moved to**: `docs/plans/completed/pgs-allele-orientation/`.

---
