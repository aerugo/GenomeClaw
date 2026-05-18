# Decoy-Variant Provenance — Single-File Plan

**Status**: Filed 2026-05-15; pending implementation
**Created**: 2026-05-15
**Parent context**: surfaced during the 2026-05-15 real-data smoke (commit-pending). VEP silently drops variants on GRCh38 decoy / non-canonical contigs from its output VCF because its annotation cache only covers the canonical genome. Today the drop is real but invisible — `provenance.json` doesn't record the count, so `materialize`'s row count silently undershoots `normalize`'s row count. INV-R001 (Rebuildability) is intact for each *surviving* row, but the trail loses the aggregate fact "N variants were dropped because they lived on contigs VEP can't annotate."

---

## Summary

When VEP encounters a variant whose contig isn't in its annotation cache (`chrUn_*_decoy`, `chrUn_*_alt`, `*_random`, etc.), it emits `WARNING: line X skipped (...): Chromosome <name> not found in annotation sources or synonyms` and **filters the variant out of its output VCF entirely**. This is conventional + scientifically defensible — decoy contigs aren't biologically interpretable — but the orchestrator should record the drop in provenance so a future audit can reconcile the row-count delta between normalize and materialize.

Capture VEP's skipped-variant count + per-chrom breakdown, record both in the `vep` provenance step's `params` block. No change to the variants-table contents (decoys still dropped, by design). One small TDD slice.

## Critical Invariants to Respect

- **`INV-R001`** Rebuildability — extends. Records the aggregate skip count + per-chrom breakdown in `provenance.json` so the post-VEP row count is reconstructible: `normalize_rowcount - sum(vep_skipped_chroms.values()) == materialize_rowcount`.
- **No change to variants table contents.** Decoy variants are not added back. The fix is purely the audit trail.

## Proposed New Invariants

None.

## Solution Design

VEP streams its stderr through `_vep.py`'s wrapper. The wrapper already captures a bounded tail (200 lines) for error messages. Extend it to **also** count `WARNING: line N skipped` lines and group by the chromosome name that appears in the warning.

The wrapper's return shape becomes a small `VepRunStats` dataclass (today it returns None). `annotate_vep.py` reads the stats off the return value and writes them into the `vep` step's `params` block:

```jsonc
{
  "step": "vep",
  "params": {
    "cache_release": "114",
    "plugins": [...],
    "flags": [...],
    "fork": 0,
    "vep_skipped_variants": 1234,          // NEW
    "vep_skipped_chroms": {                // NEW
      "chrUn_JTFH01001998v1_decoy": 6,
      "chrUn_KI270742v1": 12,
      "chr1_KI270706v1_random": 3,
      ...
    }
  }
}
```

### Pure-Python parser

Centralized regex captures both the skip count and the chrom name:

```python
_VEP_SKIPPED_VARIANT_RE = re.compile(
    r"^WARNING: line \d+ skipped \((\S+)\s"
)
```

The capture group is the contig name VEP couldn't annotate.

### Wrapper return

```python
@dataclass(frozen=True)
class VepRunStats:
    """Counts surfaced from VEP's stderr stream for provenance."""
    skipped_variants: int
    skipped_chroms: dict[str, int]
```

`vep_run(config) -> VepRunStats` (was `-> None`). Callers ignoring the return value still work.

## TDD Scope

### Unit (host-runnable, ~3 tests)

In `tests/unit/test_vep_wrapper.py`:

- `test_skipped_variant_regex_matches_canonical_vep_warning` — feed in a real VEP warning line; assert the regex matches + captures the right chrom name.
- `test_skipped_variant_regex_ignores_other_warnings` — feed a `WARNING:` line that isn't a skip; assert no match. (Defends against false positives — e.g., LOFTEE compile warnings.)
- `test_vep_run_stats_counts_skipped_variants_from_stderr` — monkeypatch `subprocess.Popen` to a fake that yields known stderr lines + asserts the returned `VepRunStats.skipped_variants` and `skipped_chroms` match.

### Integration (host-runnable, ~1 test)

Extend `tests/integration/test_annotate_vep_invariants.py::test_invR001_annotate_vep_appends_step_to_provenance`:

- Configure the stubbed `vep_run` (in `stubbed_vep` fixture) to return a `VepRunStats` with synthetic skip counts.
- Assert the `vep` provenance step's `params` block contains `vep_skipped_variants` (int) + `vep_skipped_chroms` (dict).

Plus a new test:

- `test_invR001_annotate_vep_records_skip_breakdown_in_provenance` — pin the dict shape so a future refactor that changes the field name surfaces.

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py` | MODIFY | Add `VepRunStats` dataclass; extend `vep_run` to count skipped variants per chrom; change return type. |
| `packages/toolkit/src/genomeclaw_toolkit/prep/annotate_vep.py` | MODIFY | Capture `VepRunStats` from `vep_run`; write `vep_skipped_variants` + `vep_skipped_chroms` into the `vep` provenance step. |
| `packages/toolkit/tests/unit/test_vep_wrapper.py` | MODIFY | Add 3 unit tests for regex + wrapper accounting. |
| `packages/toolkit/tests/integration/test_annotate_vep_invariants.py` | MODIFY | Update `stubbed_vep` fixture to return a `VepRunStats`; extend the INV-R001 provenance test; add 1 new test for the skip breakdown. |

## Verification

```bash
# Unit + integration tests
cd packages/toolkit
uv run pytest tests/unit/test_vep_wrapper.py tests/integration/test_annotate_vep_invariants.py -v

# Lint + format
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Optional: re-inspect the most recent real-data run's provenance to see the new fields
RUN_DIR=$(readlink /Volumes/Genome_Work/genomeclaw/derived/CURRENT)
cat /Volumes/Genome_Work/genomeclaw/derived/$RUN_DIR/provenance.json \
  | python3 -c "import json,sys; p=json.load(sys.stdin); vep=next(s for s in p['steps'] if s['step']=='vep'); print('skipped:', vep['params'].get('vep_skipped_variants')); print('per-chrom:', list(vep['params'].get('vep_skipped_chroms', {}).items())[:5])"
```

(Note: the re-inspect step only works **after** the next real-data run that uses the updated wrapper. The 2026-05-15 run's provenance file pre-dates this change and won't have the fields.)

## Completion Criteria

- [ ] `VepRunStats` dataclass shipped; `vep_run` returns it.
- [ ] `annotate_vep` writes `vep_skipped_variants` + `vep_skipped_chroms` into the `vep` provenance step's `params` block.
- [ ] 3 unit tests + 2 integration tests pass.
- [ ] Full host suite green; ruff/format clean.
- [ ] Next real-data run produces `provenance.json` with the new fields populated. (Validation deferred to whichever real-data run lands next — could be the LOFTEE follow-up run or a Phase 5 acceptance run.)
- [ ] Plan moved to `docs/plans/completed/decoy-variant-provenance.md`.

## Why Not Filter Upstream Instead

Pre-filtering at normalize (drop non-canonical contigs before annotate) was considered as an alternative. Rejected for v0: it imposes an opinion ("you shouldn't have decoy variants in your table") that future users might disagree with — e.g., someone debugging mapping artifacts might want to see exactly which decoys their reads called variants against. The audit-trail approach is opinion-free: the table is what VEP could annotate; provenance records what VEP couldn't. Pre-filtering remains a future option behind a flag if the use case appears.
