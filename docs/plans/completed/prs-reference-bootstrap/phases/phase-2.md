# Phase 2: Doctor `ancestry_ready` Gate

**Status**: Pending
**Goal**: Make `genomeclaw host doctor` surface PRS readiness via a new `ancestry_ready` section that probes the canonical post-fetch layout. Partial fetches (one of two subtrees) are flagged explicitly per `INV-C001` v1.7's ancestry-calibration requirement; the section is informational (does not change exit code), matching the pattern already set by `references_section`.

---

## Invariants Enforced in This Phase

- **INV-C001 v1.7** PRS Findings Must Be Ancestry-Calibrated — covered by the `partial` case test: when only one of `1000g/` or `hgdp/` is present, doctor reports `ancestry_ready.status == "partial"` so the user (or the Slice E.3 orchestrator) refuses to ship PRS output until both subtrees land.

---

## Why Informational, Not a Hard `_check` Entry

The existing doctor `_run_checks` table (`raw_present`, `reference_present`, `derived_writable`, `scratch_writable`) drives the exit code: any FAIL → exit 1. The downstream `references_section` is informational — missing reference data does NOT exit non-zero (per [doctor.py:481-484](../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py#L481-L484): "missing reference data / no raw sample / no derived runs / stale colima mount entries do not change the exit code (they're 'what to do next' signals, not corrupted-state alarms)").

`ancestry_ready` follows the same pattern: a missing PGS Catalog reference is not corrupted state — it's a "run `refs fetch` next" signal. The Slice E.3 orchestrator + the existing `_check_ancestry_reference` guard at compute-time are the actual enforcement layer for INV-C001 v1.7; doctor surfaces the precondition so the user can see it before invoking compute.

---

## TDD Steps

### Step 2.1 — RED: failing test cases

Append to `packages/toolkit/tests/integration/test_doctor.py`:

1. **`test_doctor_reports_ancestry_ready_when_canonical_layout_staged`** — stage `reference/pgs_catalog_ancestry/v1/{1000g,hgdp}/` with the canonical presence files (`1000G.pgen` + `HGDP.pgen`); assert `report["ancestry_ready"]["status"] == "ready"` and `report["ancestry_ready"]["path"]` points at the canonical dir.

2. **`test_doctor_reports_ancestry_partial_invC001_when_only_one_subtree_present`** — stage `reference/pgs_catalog_ancestry/v1/1000g/1000G.pgen` only (no hgdp); assert `report["ancestry_ready"]["status"] == "partial"` and the message names which subtree is missing. Exit code stays 0 (informational).

3. **`test_doctor_reports_ancestry_missing_with_install_hint`** — empty `reference/`; assert `report["ancestry_ready"]["status"] == "missing"` and the `fix` field contains the literal `genomeclaw refs fetch --source pgs_catalog_ancestry`. Exit code stays 0.

**Run**: `uv run pytest packages/toolkit/tests/integration/test_doctor.py -k ancestry -v` — confirm all three fail (no `ancestry_ready` key in report).

### Step 2.2 — GREEN: minimal implementation

1. Add `_collect_ancestry_ready(reference_root: Path) -> dict[str, Any]` to `prep/doctor.py`. Probes `reference_root / "pgs_catalog_ancestry" / "v1" / {1000g/1000G.pgen, hgdp/HGDP.pgen}`. Returns one of:
   - `{"status": "ready", "path": <str>}` when both presence files exist
   - `{"status": "partial", "path": <str>, "subtree_1000g_present": bool, "subtree_hgdp_present": bool, "fix": <str>}` when one of two exists
   - `{"status": "missing", "path": <str>, "fix": <str>}` when neither exists

   The release tag `v1` is the constant from [prep/pgs.py:_PGS_ANCESTRY_RELEASE](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py); import it (or duplicate it — the constant is the source of truth either way).

2. Add `report["ancestry_ready"] = _collect_ancestry_ready(paths["reference"])` to the `doctor()` return dict (alongside `references_section`).

3. Run tests until all three pass.

### Step 2.3 — REFACTOR

- The presence-file pair (`1000g/1000G.pgen`, `hgdp/HGDP.pgen`) duplicates the marker in `_LAYOUTS["pgs_catalog_ancestry"].presence_relpath`. Decide: extract a `_PGS_ANCESTRY_PRESENCE_FILES` constant in `prep/pgs.py`, or accept the small duplication. Tilt: extract — keeps the canonical-file pair in one place.
- Re-run full toolkit suite: confirm no regressions in the existing 599-pass baseline + 3 new tests.
- `ruff check` + `ruff format` clean on touched files.

---

## Files

### MODIFY

| File | Change |
|------|--------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | Add `_collect_ancestry_ready` + wire into `doctor()` report dict |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | (Optional REFACTOR) Add `_PGS_ANCESTRY_PRESENCE_FILES` constant so doctor + the fetch presence_relpath share one source of truth |
| `packages/toolkit/tests/integration/test_doctor.py` | Add 3 ancestry-readiness tests |

---

## Verification

```bash
# Phase-scoped
uv run pytest packages/toolkit/tests/integration/test_doctor.py -k ancestry -v

# Full suite (regression guard)
uv run pytest packages/toolkit/tests
uv run ruff check packages/toolkit
uv run ruff format --check packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py packages/toolkit/tests/integration/test_doctor.py
```

---

## Completion Criteria

- [ ] All 3 phase tests pass (RED → GREEN → REFACTOR visible in commit history)
- [ ] `ruff check` + `ruff format` clean on touched files
- [ ] Full toolkit test suite still green (no regressions in the Phase 1 baseline of 599 pass / 99 skip + 3 new tests = 602 pass / 99 skip)
- [ ] At least one test references `INV-C001` v1.7 (the partial-subtree case)
- [ ] `report["ancestry_ready"]` is JSON-serialisable (round-trips via `json.dumps`/`loads`)
- [ ] Exit code unchanged by `ancestry_ready` status (matches `references_section` informational pattern)
- [ ] Phase status updated to **Complete** in `development-plan.md` and `work-notes.md`
- [ ] Meta-plan Stage 1 row updated to "Phase 1 + 2 complete; ready to start Stage 2"
