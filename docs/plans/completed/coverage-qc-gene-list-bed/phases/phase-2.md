# Phase 2 — Bundle BED + auto-engage on ingest

**Status**: COMPLETE
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Wire the bundled default-panel BED into `pipeline ingest` (and transitively `pipeline run`) so that providing `--bam <CRAM>` without `--bed` auto-engages the default panel + populates `coverage_qc`. Adds opt-out flag + provenance recording + 7 tests.

## Scope Boundaries

- **In scope**:
  - Default-BED path resolver that handles the bundled-or-missing cases.
  - Auto-engage logic in `prep/ingest.py`: when `bam` provided + `bed` is None + default BED exists.
  - Opt-out flag (Phase 1 picks the name; default `--no-coverage-qc`).
  - Provenance: `params_json` records the panel filename + version + threshold.
  - Tests cover all branches.
- **Out of scope**:
  - Live verification against the canonical run-dir (Phase 3).
  - Per-exon mean-depth granularity (existing mosdepth output shape unchanged).
  - Cross-sample / multi-CRAM (one sample per run-dir).

## Invariants enforced in this phase

- **INV-R001** — `params_json` records the panel BED filename + version + low-coverage threshold; covered by `test_invR001_params_json_records_panel_provenance`.
- **INV-T001** — mosdepth wrapper unchanged; `MosdepthConventions` + `tools/mosdepth/probe-output.txt` baseline holds.

---

## TDD Steps

### Step 2.1 — RED: write failing tests

New file: `tests/integration/test_coverage_qc_default_panel.py`.

Uses a minimal-CRAM fixture (existing under `tests/fixtures/` if one is there, else create a tiny synthetic CRAM during test setup) + a panel BED stub covering 2-3 fake genes.

**Test cases**:

1. `test_ingest_with_cram_auto_engages_default_panel` — call `ingest(vcf=..., bam=<CRAM>, ...)` without `bed=`; assert mosdepth ran + `coverage_qc` populated + rows match the bundled panel's gene set.
2. `test_ingest_with_cram_and_explicit_bed_overrides_default` — call `ingest(..., bam=<CRAM>, bed=<custom_BED>)`; assert custom panel was used (rows match custom genes, not default).
3. `test_ingest_with_cram_and_opt_out_skips_coverage_qc` — call `ingest(..., bam=<CRAM>, no_coverage_qc=True)`; assert `coverage_qc` is empty + ingest succeeded.
4. `test_ingest_without_cram_does_not_engage` — call `ingest(..., bam=None)`; assert `coverage_qc` stays empty (unchanged behavior).
5. `test_default_panel_missing_warns_and_skips` — patch `_default_panel_path()` to return a nonexistent path; call `ingest(bam=<CRAM>)`; assert WARNING log line about missing panel + ingest continues + `coverage_qc` empty.
6. `test_invR001_params_json_records_panel_provenance` — after a successful auto-engage, query `coverage_qc.params_json`; assert it includes the panel filename, version, and threshold.
7. `test_default_panel_v1_contains_disease_area_genes` — load the bundled BED; assert it contains every gene from the disease-area sysprompt panels (CFH, BRCA1, APOE, MYOC, ABCA4, etc.). This is the cross-link between the sysprompt + the panel; if they drift, this test catches it.

After authoring, run the suite — **all 7 should fail** (default BED resolver doesn't exist; auto-engage logic missing; opt-out flag missing).

### Step 2.2 — GREEN: minimal implementation

**`prep/ingest.py`** (MODIFY):

```python
_DEFAULT_PANEL_BED_NAME = "coverage_panel_default_v1.bed.gz"

def _default_panel_bed_path() -> Path | None:
    """Resolve the bundled default-panel BED, or None if not staged."""
    candidate = (
        Path(__file__).parent.parent / "data" / _DEFAULT_PANEL_BED_NAME
    )
    return candidate if candidate.exists() else None

def ingest(
    *,
    vcf: Path,
    bam: Path | None = None,
    bed: Path | None = None,
    no_coverage_qc: bool = False,
    ...,
) -> None:
    ...
    # Existing: bam given + bed given → existing path
    # New: bam given + bed=None + not no_coverage_qc + default BED present →
    #      use default BED + log INFO with panel filename
    if bam is not None and bed is None and not no_coverage_qc:
        default_panel = _default_panel_bed_path()
        if default_panel is not None:
            log.info(
                "Auto-engaging default coverage-QC panel",
                extra={
                    "panel_path": str(default_panel),
                    "panel_version": "v1",
                },
            )
            bed = default_panel
        else:
            log.warning(
                "Default coverage-QC panel BED not found at the canonical path; "
                "skipping coverage_qc step. Run `genomeclaw doctor` to verify install."
            )
    # Existing mosdepth path runs only when bed is not None
```

Threading the panel-version + threshold through to `params_json`:

```python
# Inside the existing mosdepth path, when bed is the bundled default:
panel_provenance = {
    "panel_version": "v1",
    "panel_path": str(bed.name),
    "low_coverage_threshold": "20x",  # Phase 1's pick
}
write_coverage_qc(
    rows,
    tag=ProvenanceTag(
        source_path=str(bam),
        ...,
        params_json=json.dumps(panel_provenance),
    ),
)
```

**`_cli/commands/pipeline.py`** (MODIFY): add the `--no-coverage-qc` flag to `pipeline ingest`. Propagates through to `ingest(no_coverage_qc=...)`.

### Step 2.3 — REFACTOR

- If the default-BED path resolution is needed elsewhere (Phase 3's verification or future plans), extract `_default_panel_bed_path()` into `prep/_panels.py`.
- Document the new flag in `docs/reference/architecture.md`'s pipeline-ingest section.
- Ensure the `--no-coverage-qc` flag is also exposed on `pipeline run` (which wraps ingest).

---

## Implementation Details

### Default-BED path canonicalization

The toolkit image bundles assets at `packages/toolkit/data/`. At install-time the BED lives in the Python package; at runtime `Path(__file__).parent.parent / "data"` resolves to it. Works inside the toolkit container + on the bare host venv.

### Provenance shape

`coverage_qc` rows already have INV-R001 columns. The new addition is the `params_json` JSON payload:

```json
{
  "panel_version": "v1",
  "panel_path": "coverage_panel_default_v1.bed.gz",
  "low_coverage_threshold": "20x"
}
```

If the operator passes an explicit `--bed <custom>`, `params_json` records the path + omits the `panel_version`/`low_coverage_threshold` keys (or sets them to `"custom"` / unknown). Phase 1 picks the exact shape.

### Edge Cases to Handle

- **Default panel staged at a non-canonical path** (e.g. someone moved the file): the resolver returns None → WARNING + skip. Operator-actionable.
- **Custom BED passed AND opt-out flag set**: opt-out wins; the custom BED is ignored + coverage_qc skipped. Document this in the flag's help text.
- **Existing coverage_qc rows from a prior run**: each `pipeline ingest` invocation starts a fresh derived store; `coverage_qc` is per-run. No cross-run state.

### Privacy / Egress Notes

- No new egress; mosdepth is local.
- The default panel BED is bundled with the toolkit; no per-run download.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` | MODIFY | Auto-engage default-panel logic + provenance threading |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | Add `--no-coverage-qc` flag |
| `packages/toolkit/tests/integration/test_coverage_qc_default_panel.py` | CREATE | 7 tests covering all branches |
| `docs/reference/architecture.md` | MODIFY (light) | Document the `--no-coverage-qc` flag + default-panel auto-engage |

---

## Verification

```bash
cd packages/toolkit

uv run pytest tests/integration/test_coverage_qc_default_panel.py -v
# Expect: 7/7 PASS

# Existing ingest tests still pass
uv run pytest tests/integration/test_ingest_orchestrator.py -v
# Expect: no regression

# Full sweep
uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: 874+ passed (was 867; +7 new), no regressions

uv run mypy src/genomeclaw_toolkit/prep/ingest.py src/genomeclaw_toolkit/_cli/commands/pipeline.py
uv run ruff check src/genomeclaw_toolkit/prep/ingest.py src/genomeclaw_toolkit/_cli/commands/pipeline.py tests/integration/test_coverage_qc_default_panel.py
```

---

## Completion Criteria

- [ ] All 7 new tests pass.
- [ ] Existing ingest tests still pass.
- [ ] Full toolkit suite stays green.
- [ ] mypy + ruff clean on touched files.
- [ ] `--no-coverage-qc` flag documented in architecture.md.
- [ ] `work-notes.md` updated with implementation notes + a sample log-output excerpt showing the auto-engage line.

## Next

[Phase 3 — Live verification](phase-3.md).
