# PRS Input Coverage Fill — Work Notes

**Feature**: Two-tier targeted forced-genotyping cache so `pgsc_calc --run_ancestry` works on Nebula variant-only WGS
**Started**: 2026-05-18
**Branch**: TBD
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session Log

### 2026-05-18 — Phase 5 Implementation (smoke driver + verification gates)

**Context Review Completed**:
- Read the pre-written [phases/phase-5.md](phases/phase-5.md) — the first phase doc following the proper pre-RED protocol since Phase 1.
- Re-confirmed the canonical pgsc_calc work-dir structure (Phase 3b3a's empirical findings against the 2026-05-17 smoke).

**Applicable Invariants**:
- **INV-D001**: pre/post CRAM SHA256 captured + recorded in `invariant_audit.json`.
- **INV-D003**: smoke driver scopes `--output-root` + `--work-dir` under the timestamped scratch dir; never touches `derived/` directly.
- **INV-R001**: every cached artefact (tier1.qc.json, tier2.qc.json, pca_sites.provenance.json) records tool versions + source hashes.
- **INV-P001**: smoke runs entirely on-device; no network egress.
- **INV-C001 v1.7**: whichever calibration outcome the smoke produces — CLEAN / WARNING / DECLINE — surfaces structurally in `invariant_audit.json`'s INV-C001-v1.7 block.

**RED step output** (10 verification gates landed; all auto-skip cleanly on bare host):

```text
tests/integration/test_phase5_smoke_artifacts.py SSSSSSSSSS                [100%]
============================= 10 skipped in 0.11s ==============================

Reason cited 10×: needs_phase5_smoke_artifacts test requires
GENOMECLAW_PHASE5_SMOKE_DIR pointing at a directory produced by
`bin/genomeclaw-prs-smoke`. Run the driver against the real CRAM
(~50–60 min on 2-CPU Colima), then export the env var pointing at the
timestamped output dir.
```

**Completed Today (Phase 5 — 10 verification gates + smoke driver)**:
- [x] `needs_phase5_smoke_artifacts` marker registered in [`pyproject.toml`](../../../../packages/toolkit/pyproject.toml) + auto-skip wired in [`conftest.py`](../../../../packages/toolkit/tests/conftest.py).
- [x] `phase5_smoke_dir` fixture in conftest resolves `GENOMECLAW_PHASE5_SMOKE_DIR` + validates the path.
- [x] [10 verification tests](../../../../packages/toolkit/tests/integration/test_phase5_smoke_artifacts.py) covering Tier 1 QC health (mean DP + REF/REF rate + per-chrom coverage), Tier 1 wall-clock budget (Q1 resolution gate), peak RSS ceiling, INV-D001 audit, Tier 2 QC, post-bridge match-rate against the real pgsc_calc log, pgs_scores row persistence, structural calibration outcome, CLI JSON envelope shape, and complete invariant audit.
- [x] [`bin/genomeclaw-prs-smoke`](../../../../bin/genomeclaw-prs-smoke) host-side driver script (~250 lines bash):
  - Pre-flight: docker + image + CRAM + .crai + FASTA + panel + scorefile validation; exits 2 on any miss.
  - Three timed stages: materialize_pca_sites (if absent), prepare_coverage_tier1, prs_compute_<PGS_ID>.
  - Per-stage `docker stats` background sampler captures peak RSS.
  - Pre/post CRAM SHA256 + mtime for INV-D001 audit.
  - Emits `timings.json` + `invariant_audit.json` + `cli_envelope.json` + `smoke.log`.

**Decisions Made**:
- **Tests verify recorded artefacts, not live compute**. The driver is a one-shot bash script; the verification gates are normal pytest tests that read JSON files. This decouples test runtime (seconds) from smoke runtime (50–60 min) — CI never has to wait for the smoke, but the gate is mechanical when the smoke has run.
- **PCA-sites materialization is in-driver, not a separate command**. The driver runs `python -c "from coverage_fill import _materialize_pca_sites; ..."` via the toolkit image when the TSVs aren't already on disk. A proper CLI subcommand wiring is a Phase 5b follow-up; for the smoke driver, the inline Python call works.
- **Pre-flight failure modes return exit 2**, not 1 — matches the standard "configuration error vs. runtime error" convention. The verification tests would have NO artefacts to check on exit 2, so the env-var gate skips them cleanly.
- **Smoke output layout matches the test expectations exactly**, not the canonical `derived/<run-id>/` shape. The driver scopes a self-contained output tree under `_scratch/prs_phase5_smoke/<UTC-iso>/` so the audit + verification surface is one directory the test fixture can index from.

**Honest scope acknowledgement**:
- I'm **not** running the actual smoke in this session. The driver is delivered + bash-syntax-clean; pre-flight failure modes are verified; the 10 verification tests auto-skip cleanly. The 50–60 min real run against `MPNRGLQ2K.cram` is the user's call — they have the environment (Colima + toolkit image + CRAM on disk) and will invoke `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` when ready.
- The 10 verification gates double as **acceptance criteria for the eventual smoke**: when the user runs the driver + exports the env var, `uv run pytest -m needs_phase5_smoke_artifacts` either confirms the bridge works against real data or pinpoints exactly which acceptance criterion failed (with measured values to update the spec from).

**Blockers / Issues**:
- None. The driver is independently testable via its pre-flight failure modes; the verification tests gate cleanly without artefacts.

**REFACTOR step**:
- ruff: 1 unused-blank-line fix in the test file (auto-applied).
- mypy: clean (no source files modified).
- Full suite: **684 passed / 114 skipped / 0 failed** (Phase 3b3b baseline was 684/104; +10 new skips for `needs_phase5_smoke_artifacts`).

**Phase 5 status — TESTS + DRIVER COMPLETE; SMOKE PENDING USER INVOCATION**:
- 10 verification gates + smoke driver landed.
- Total plan progress: **91 tests** across Phase 1a + 1b + 2 + 3a + 3b1 + 3b2 + 3b3a + 3b3b + 4 + 5, all GREEN or auto-skipped cleanly (10 Phase 5 + 1 `needs_bio` skip on bare host).

**Next Steps**:
1. User invokes `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` against the real CRAM on the real toolkit image. ~50–60 min on the 2-CPU Colima.
2. User exports `GENOMECLAW_PHASE5_SMOKE_DIR=<output>` and runs `uv run pytest -m needs_phase5_smoke_artifacts`.
3. Results inform:
   - Open Question Q1 resolution (full-autosome Tier 1 wall-clock — recorded value goes into spec.md).
   - Open Question Q3 resolution (per-chromosome GT distribution — also into spec.md).
   - Calibration outcome on PGS000018 — if CLEAN/WARNING, the plan ships fully; if DECLINE, spec gets a "known limitation" note (the bridge alone is insufficient on ≥1M-variant scores).
4. After smoke results land: write [docs/reference/prs-pipeline.md](../../../reference/prs-pipeline.md), move plan to `completed/`.

---

### 2026-05-18 — Phase 3b3b Implementation (DuckDB schema migration + CLI decline path)

**Context Review Completed**:
- Re-read Phase 3b3a outputs + the dev-plan's Phase 3b3b scope.
- Inspected the existing `pgs_scores` DDL in [store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) and the INSERT in [pipeline.py:_stamp_pgs_row](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py).

**Applicable Invariants**:
- **INV-C001 v1.7**: decline is a legitimate output, not a failure. CLI catches `PRSDeclineError`, emits a typed payload, exits 0.
- **INV-A003**: the two-named-reasons payload threads through to the JSON envelope (`payload.decline.two_named_reasons`).
- **INV-R001**: the new columns are nullable + additive; existing rows persist unchanged; rebuilding produces byte-stable layout.

**RED step outputs**:

```text
Phase 3b3b1 — DDL tests: 5 BinderError ("calibration_status not found")
Phase 3b3b2 — CLI decline tests: 3 AssertionError (exit_code=1, not 0;
              the unhandled PRSDeclineError surfaces as internal_error)
```

**Completed Today (Phase 3b3b — 8 new tests, all GREEN)**:
- [x] **3b3b1** — extended the [`pgs_scores` DDL](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py#L205) with two nullable TEXT columns: `calibration_status` and `decline_reason`. INSERT in `_stamp_pgs_row` now persists both fields from the `PgsRow`. 5 tests covering DDL presence, nullability, CLEAN round-trip, DECLINE round-trip, and pre-Phase-3b1 backwards compat.
- [x] **3b3b2** — extended `_PrsComputePayload` with `calibration_status: str | None` + `decline: _PrsComputeDeclineBlock | None` (carries `reason` + `two_named_reasons` tuple). CLI's `prs-compute` subcommand now catches `PRSDeclineError`, builds the decline payload, and emits it via the same `pipeline.prs-compute` command with exit 0. Rich-mode renders a one-line decline message instead of a stack trace. 3 tests covering exit code, JSON envelope shape, and rich-mode rendering.

**Decisions Made**:
- **`SCHEMA_VERSION` stays at `v0.2`** for this slice. The two new columns are nullable + additive — every existing row continues to be valid. A version bump would correctly signal a schema change but cascades through ~hundreds of tests that hardcode `v0.2` in provenance assertions. Bumping is the right call when a wider migration lands (the dev-plan's full provenance-column expansion); for two nullable columns the bump is overkill.
- **Decline is a single payload variant**, not a separate command output. The CLI emits `command: "pipeline.prs-compute"` with `payload.decline = {reason, two_named_reasons}` populated. The agent layer dispatches on payload shape (presence of the decline block). Two separate commands would have been cleaner schema-wise but doubles the CLI surface; the union approach is more JSON-friendly.
- **`decline.two_named_reasons` is a `tuple[str, str]`** in the pydantic model, not a `list[str]`. Mechanically constrains the schema to exactly two reasons — mirrors the `PRSDeclineError.__init__` enforcement at the typed-exception layer and the INV-A003 two-named-reasons rule at the invariant layer.
- **CLI imports `PRSDeclineError` + `_extract_pgs_id_from_scorefile` locally** inside the subcommand body (not at the module top). Defers the import cost until the subcommand actually runs, and keeps the imports next to the catch-block where they're used.

**Blockers / Issues**:
- None. The slice landed cleanly without disturbing the existing `pipeline pgs-compute` path or any other subcommand.

**REFACTOR step**:
- ruff: clean (no warnings on the new files).
- mypy: clean across [`store.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) + [`pipeline.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py).
- Full suite: **684 passed / 104 skipped / 0 failed** (Phase 3b3a baseline was 676/104; +5 DDL + 3 CLI = 8 new tests).

**Phase 3b3b status — COMPLETE**:
- 8 new tests covering the schema migration + CLI decline path.
- The full agent path is now end-to-end: CRAM + scorefile → Tier 1+2+merge+pgsc_calc → match-rate auto-discovery → classifier → either CLEAN row persisted to `pgs_scores` OR `PRSDeclineError` caught by CLI → typed decline JSON envelope. Every link in the chain is tested.
- Total plan progress: **81 tests** across Phase 1a + 1b + 2 + 3a + 3b1 + 3b2 + 3b3a + 3b3b + 4, all GREEN (1 `needs_bio` skip).

**Phase 3 status — END-TO-END COMPLETE**:
All seven Phase 3 deliverables from [development-plan.md](development-plan.md) land:
- Classifier + decline taxonomy + typed exception (3a).
- PgsRow surface extension + decision helper (3b1).
- Orchestrator wire-up with explicit kwargs (3b2).
- pgsc_calc match-rate parser + auto-discovery (3b3a).
- DuckDB schema migration + CLI decline path (3b3b).

**Next Steps**:
1. Commit the entire Phase 3 family (or batch with everything since the last commit point).
2. Phase 5 — real-data smoke against `MPNRGLQ2K.cram` on the real toolkit image. Resolves Open Question Q1 (full-autosome Tier 1 wall-clock). Last remaining work before the plan moves to `completed/`.

---

### 2026-05-18 — Phase 3b3a Implementation (pgsc_calc match-rate parser + auto-discovery)

**Context Review Completed**:
- Re-read Phase 3b2 outputs + the dev-plan's Phase 3b3 deferral.
- Inspected the **real** 2026-05-17 smoke output in `_scratch/pgsc_calc_work/` to determine pgsc_calc's match-output structure rather than guessing.

**Empirical findings from the real smoke**:
- pgsc_calc emits ``<work_dir>/<nextflow_hash>/<sampleset>_log.csv.gz`` with one row per scoring variant.
- The ``match_status`` column carries: ``matched`` (495,434 rows), ``unmatched`` (1,249,188), ``not_best`` (557), ``excluded`` (557).
- Match rate = ``matched / (matched + unmatched)`` = 495_434 / 1_744_622 = **0.2840** — matches the smoke's logged 28.37% within rounding.
- ``not_best`` and ``excluded`` are duplicate-handling artefacts (same underlying variants); counting them double-counts.
- pgsc_calc's internal accession is ``<PGS_ID>_hmPOS_GRCh38`` for harmonised scoring files.

**Applicable Invariants**:
- **INV-C001 v1.7**: classifier consumes the parsed match_rate to decide CLEAN/WARNING/DECLINE.
- **INV-R001**: parser is deterministic on the same input log; no hidden state.

**RED step output**:

```text
tests/integration/test_pgsc_calc_match_rate_parser.py        7 ModuleNotFoundError
tests/integration/test_orchestrator_match_rate_auto_discovery.py
    1 RED (auto-discovery doesn't trigger yet) + 2 GREEN (no-log + override paths)
```

**Completed Today (Phase 3b3a — 10 new tests, all GREEN)**:
- [x] [`_pgsc_calc_match.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_match.py): `MatchStats` dataclass, `parse_match_stats` (filters by accession, excludes not_best/excluded buckets), `find_pgsc_calc_log_csv` (recursive glob through Nextflow hash hierarchy).
- [x] 7 parser-level tests including a real-smoke validation: feeding the parser the actual `MPNRGLQ2K_log.csv.gz` from `_scratch/pgsc_calc_work/` returns `matched=495,434 / unmatched=1,249,188 / match_rate=0.2840` — agrees with the smoke's logged 28.37% within rounding.
- [x] Orchestrator auto-discovery: when both `match_rate` and `pgs_variant_count` are omitted, the orchestrator searches `work_dir` for the log, parses it for the accession `<pgs_id>_hmPOS_GRCh38`, and uses the parsed counts. Explicit kwargs always override.
- [x] 3 orchestrator-integration tests: auto-discovery → classifies; log absent → skips classification silently; explicit kwargs → override auto-discovery.

**Decisions Made**:
- **Inspect the real smoke artefacts before designing the parser**. The 2026-05-17 smoke produced `_scratch/pgsc_calc_work/2026-05-17T15-12-03Z-prs-smoke01/3c/.../MPNRGLQ2K_log.csv.gz`. The four observed `match_status` values + their counts pinned the formula exactly. Designing the parser without this empirical anchor would have left the not_best / excluded buckets as a coin-flip.
- **`MatchStats.match_rate` is a property, not a field**. Computed on access from `matched / (matched + unmatched)`. Defensive `0.0` return on zero-denominator (which the constructor's `None` return path already prevents in practice).
- **Auto-discovery is opt-in via omission**. Both `match_rate` AND `pgs_variant_count` must be `None` to trigger the work_dir probe; supplying either pins the explicit value. Lets tests fix the calibration outcome deterministically.
- **Silent skip on log-absent**, not a hard error. A failed auto-discovery returns a row with `calibration_status=None` — the same shape the caller gets when not asking for classification at all. The agent layer treats `None` as "calibration not assessed" and renders the report accordingly.
- **Accession synthesis baked at the call site**: `f"{pgs_id}_hmPOS_GRCh38"`. Hard-codes the harmonised-scoring-file naming convention. If PGS Catalog ever ships a different harmonisation suffix the parser's `parse_match_stats` signature already accepts any accession string — only the orchestrator's synthesis needs updating.

**Blockers / Issues**:
- None. The empirical-then-code path was straightforward once the smoke log was on disk.

**REFACTOR step**:
- ruff: 1 import-order fix in the auto-discovery test (auto-applied).
- mypy: clean on `_pgsc_calc_match.py` + `coverage_fill.py`.
- Full suite: **676 passed / 104 skipped / 0 failed** (Phase 3b2 baseline was 666/104; +7 parser + 3 auto-discovery = 10 new tests).

**Phase 3b3a status — COMPLETE**:
- The 2026-05-17 smoke case now flows end-to-end without explicit kwargs: caller invokes `compute_prs_with_coverage_fill` with the real CRAM + scorefile, pgsc_calc emits its log, the parser extracts the match counts, the classifier returns DECLINE, the orchestrator raises `PRSDeclineError`. All of which is verified by tests using the actual smoke log file.
- Total plan progress: **73 tests** across Phase 1a + 1b + 2 + 3a + 3b1 + 3b2 + 3b3a + 4, all GREEN (1 `needs_bio` skip).

**Phase 3b3b deferred**:
- Migrate `pgs_scores` DuckDB DDL in [store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) — add `calibration_status TEXT` + `decline_reason TEXT` columns.
- Update `pipeline.py:_stamp_pgs_row` INSERT clause to include the new fields.
- Bump `SCHEMA_VERSION`.
- Wire the CLI `pipeline prs-compute` subcommand's catch-and-render path for `PRSDeclineError` (currently the CLI lets it propagate as an unhandled error).

**Next Steps**:
1. Commit Phase 3b3a (or batch with everything since the last commit).
2. Phase 3b3b — DuckDB schema migration + CLI decline path.
3. Phase 5 — real-data smoke against `MPNRGLQ2K.cram` (resolves Q1 wall-clock).

---

### 2026-05-18 — Phase 3b Implementation (PgsRow calibration fields + orchestrator wire-up)

**Context Review Completed**:
- Re-read Phase 3a outputs + the dev-plan's Phase 3b deferral note.
- Decided to split Phase 3b into 3b1 (PgsRow surface extension), 3b2 (orchestrator wire-up with explicit `match_rate`), and 3b3 (deferred: match_rate parsing from pgsc_calc output + DuckDB schema migration). Each slice is independently reviewable.

**Applicable Invariants**:
- **INV-C001 v1.7**: `PRSDeclineError` raised on DECLINE; CLEAN/WARNING annotated on the row.
- **INV-A003**: orchestrator generates two default named reasons on decline (per the two-named-reasons rule); agent can override at the CLI layer when it has more context.

**RED step output**:

```text
Phase 3b1: 6 ImportError / AttributeError on `apply_calibration_decision`
           and the new `calibration_status` / `decline_reason` fields.

Phase 3b2: 3 TypeError on `compute_prs_with_coverage_fill() got an
           unexpected keyword argument 'match_rate'`. 1 passes (the
           backwards-compat test — orchestrator returns row with
           calibration_status=None when no match_rate is supplied).

10 RED in total.
```

**Completed Today (Phase 3b — 10 new tests, all GREEN)**:
- [x] **3b1** — extended `PgsRow` with two optional fields: `calibration_status: str | None = None` (`"clean" | "warning" | "decline" | None`) and `decline_reason: str | None = None` (snake_case string form of `DeclineReason.value`). Backwards-compatible: existing call sites work unchanged.
- [x] **3b1** — `apply_calibration_decision(row, decision) -> PgsRow` helper. Pure function via `dataclasses.replace`. Mechanical guard: rejects a DECLINE decision missing its `decline_reason`. 6 tests covering each branch + invariant preservation.
- [x] **3b2** — extended `compute_prs_with_coverage_fill` with optional `match_rate` + `pgs_variant_count` kwargs. When both supplied: classify → CLEAN/WARNING annotates row, DECLINE raises `PRSDeclineError` with structural reason + two generated default named reasons. When omitted: Phase 4c behaviour preserved (row returned with `calibration_status=None`). 4 tests covering each calibration branch + the backwards-compat path.

**Decisions Made**:
- **`decline_reason` stamped as the enum's `.value`** (snake_case string) rather than the bare enum member. Keeps the future DuckDB column type as `TEXT` rather than requiring a custom enum or constraint. The classifier's `CalibrationDecision.decline_reason` carries the typed enum; `apply_calibration_decision` does the `.value` conversion at the storage boundary.
- **Default named reasons generated by the orchestrator**, not the caller. The orchestrator constructs two structural reasons from the (match_rate, variant_count) tuple — one citing the threshold, one citing the variant-overlap failure mode. The agent layer can intercept the `PRSDeclineError` and re-raise with more context-specific reasons if it has the question semantics; both forms still mechanically satisfy the two-named-reasons rule.
- **`match_rate` is an explicit parameter**, not parsed from pgsc_calc output. The parsing layer (`aggregated_scores.txt` or the match-step intermediates) is a separate concern — Phase 3b3. The classifier integration is decoupled from the parsing detail so we can land + test it independently.
- **No schema migration this slice**. `PgsRow` carries the new fields in-memory; `pipeline.py:_stamp_pgs_row` still writes only the existing columns. When 3b3 lands the migration, the in-memory shape is already correct — only the DDL + INSERT clauses change.

**Blockers / Issues**:
- None. The split into 3b1/3b2/3b3 made every slice land in a single TDD cycle without scope creep.

**REFACTOR step**:
- ruff: clean.
- mypy: clean across `coverage_fill.py`, `_pgs_qc.py`, `pgs.py`.
- Full suite: **666 passed / 104 skipped / 0 failed** (Phase 3a baseline was 656/104; +6 Phase 3b1 + 4 Phase 3b2).

**Phase 3b status — 3b1 + 3b2 COMPLETE; 3b3 PENDING**:
- 10 new tests across 3b1 + 3b2.
- The 2026-05-17 smoke case now flows end-to-end: a caller supplies `match_rate=0.2837, pgs_variant_count=1_700_000` and the orchestrator raises `PRSDeclineError(reason=VARIANT_OVERLAP_INSUFFICIENT, two_named_reasons=(...))`. The agent layer's catch-and-emit-decline path is fully exercised.
- Total plan progress: 63 tests across Phase 1a + 1b + 2 + 3a + 3b1 + 3b2 + 4, all GREEN (1 `needs_bio` skip).

**Phase 3b3 deferred**:
- Parse match_rate from pgsc_calc output (`aggregated_scores.txt` DENOM column or `match/<sampleset>_*.csv` intermediates).
- Migrate `pgs_scores` DuckDB schema: add `calibration_status TEXT` + `decline_reason TEXT` columns; bump schema_version.
- Update `pipeline.py:_stamp_pgs_row` INSERT to include the new columns.
- Wire the CLI `pipeline prs-compute` subcommand to call the orchestrator with computed `match_rate` + `pgs_variant_count`.

**Next Steps**:
1. Commit Phase 3b1 + 3b2 (or batch with all phases).
2. Phase 3b3 — match_rate parsing + schema migration.
3. Phase 5 — real-data smoke (resolves Q1 wall-clock).

---

### 2026-05-18 — Phase 3a Implementation (QC classifier + decline taxonomy)

**Context Review Completed**:
- Re-read Phase 3 deliverables in [development-plan.md](development-plan.md) + the `INV-C001` v1.7 PRS-decline pattern in [INVARIANTS.md](../../../reference/INVARIANTS.md).
- Confirmed the five named decline reasons from the agent recommendation document Section 5.2: `POPULATION_TRANSFERABILITY_INSUFFICIENT`, `PGS_CATALOG_TIER_INSUFFICIENT`, `PHENOTYPE_HETEROGENEOUS`, `VARIANT_OVERLAP_INSUFFICIENT`, `ANCESTRY_CALIBRATION_UNCERTAIN`.
- Mapped the per-PGS-variant-count QC threshold table from Section 5.1 to the three-tier classifier shape.

**Applicable Invariants**:
- **INV-C001 v1.7**: five-named-reasons decline taxonomy + status enum (clean/warning/decline).
- **INV-A003**: two-named-reasons rule mechanically enforced by `PRSDeclineError.__init__` (rejects `< 2` reasons at construction time).

**RED step output**:

```text
tests/integration/test_pgs_qc_classifier.py  14 ModuleNotFoundError on:
  genomeclaw_toolkit.prep._pgs_qc
14 failed in 0.03s — all against the absent _pgs_qc module.
```

**Completed Today (Phase 3a — 14 new tests, all GREEN)**:
- [x] [`_pgs_qc.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_pgs_qc.py): `CalibrationStatus` enum, `DeclineReason` enum (all 5 reasons declared), `CalibrationDecision` dataclass, `PRSDeclineError` typed exception, `classify_calibration` function.
- [x] 9 tests covering the three-tier match-rate threshold table:
  - ≤10k variants: 90% clean / 75% warn-floor / <75% decline.
  - 10k–500k variants: 80% clean / 60% warn-floor / <60% decline.
  - >500k variants: 75% clean / 40% warn-floor / <40% decline.
- [x] 2 boundary tests confirming the threshold semantics (`≥ clean_floor` is CLEAN, `≥ decline_floor` is WARNING, strict `<` decline_floor is DECLINE).
- [x] 1 schema-stability test asserting all 5 `DeclineReason` enum members exist.
- [x] 2 `PRSDeclineError` tests covering the two-named-reasons rule (carries them, rejects single-reason construction).
- [x] One test deliberately mirrors the 2026-05-17 smoke's failure mode — PGS000018 (1.7M variants) at 28.37% match rate → DECLINE / `VARIANT_OVERLAP_INSUFFICIENT`. The classifier returns exactly that.

**Decisions Made**:
- **Phase 3 split into 3a + 3b**. 3a is the classifier + decline-reason taxonomy + typed exception (pure logic, well-tested). 3b is the schema-wide integration: extend `PgsRow` with `calibration_status` + `decline_reason` fields, migrate the `pgs_scores` DuckDB schema in `_stamp_pgs_row`, wire the classifier into `compute_prs_with_coverage_fill`. The split keeps each landing reviewable — 3a doesn't touch the schema; 3b doesn't add new classifier logic.
- **Variant-overlap axis only** for the classifier's first cut. The four ancestry-driven reasons (`POPULATION_TRANSFERABILITY_INSUFFICIENT` / `PGS_CATALOG_TIER_INSUFFICIENT` / `PHENOTYPE_HETEROGENEOUS` / `ANCESTRY_CALIBRATION_UNCERTAIN`) need inputs that don't flow through the toolkit today (FRAPOSA continuous-PC vector, PGS Catalog metadata, etc.). The enum is in place so future phases can wire each branch without an enum-shape migration.
- **`PRSDeclineError` enforces the two-named-reasons rule mechanically** rather than by caller discipline. A `ValueError` at construction time when the tuple isn't exactly two non-empty strings means a single-reason decline can't slip past static review — the agent's compute-path code is forced to articulate two reasons or the call won't compile.
- **Threshold semantics**: `≥` clean_floor → CLEAN; `≥` decline_floor → WARNING; strict `<` decline_floor → DECLINE. Inclusive on the upper side, strict on the lower. Tested via boundary cases at exactly 0.90 (clean) and exactly 0.75 (warning) for the small-PGS tier.

**Blockers / Issues**:
- None. The classifier is intentionally narrow — Phase 3b's schema migration is a separate landing.

**REFACTOR step**:
- ruff: 1 unused-blank-line fix in the test file (auto-applied).
- mypy: clean on `_pgs_qc.py`.
- Full suite: **656 passed / 104 skipped / 0 failed** (Phase 4 baseline was 642/104; +14 Phase 3a tests).

**Phase 3a status — COMPLETE**:
- 14 new tests covering the full QC threshold table + decline taxonomy + typed-exception shape.
- The classifier's `VARIANT_OVERLAP_INSUFFICIENT` branch directly catches the 2026-05-17 smoke failure (28.37% on 1.7M variants).
- Total plan progress: 53 tests across Phase 1a + 1b + 2 + 3a + 4, all GREEN (1 `needs_bio` skip).

**Phase 3b deferred**:
- Extend `PgsRow` with `calibration_status` + `decline_reason` fields.
- Migrate `pgs_scores` DuckDB schema in `pipeline.py:_stamp_pgs_row`.
- Wire the classifier into `compute_prs_with_coverage_fill` (call classifier post-pgsc_calc; either return annotated row or raise `PRSDeclineError`).
- Add match_rate extraction from pgsc_calc output (parse the report HTML / aggregated_scores section).
- Schema-version bump.

**Next Steps**:
1. Commit Phase 3a (or batch with previous phases).
2. Phase 3b — schema-wide integration of the classifier.
3. Phase 5 — real-data smoke against `MPNRGLQ2K.cram` (resolves Q1 wall-clock).

---

### 2026-05-18 — Phase 4 Implementation (-profile docker + end-to-end orchestrator)

**Context Review Completed**:
- Re-read Phase 4 deliverables in [development-plan.md](development-plan.md).
- Confirmed Phase 1b doctor section already lands the `prs_coverage_ready` probe (originally listed under Phase 4 deliverables); only the `-profile docker` switch + post-fetch hook decision + CLI surface remain for Phase 4.

**RED step outputs**:

```text
Phase 4a — flipped existing regression test from `-profile conda` to `-profile docker`:
  test_compute_pgs_pins_profile_docker_and_pgsc_calc_revision_invR001
  AssertionError: -profile must be `docker`, got 'conda'

Phase 4c orchestrator — 3 ImportError on compute_prs_with_coverage_fill
Phase 4c CLI — 3 "No such command 'prs-compute'" UsageError
```

**Completed Today (Phase 4 — 9 new/flipped tests, all GREEN)**:
- [x] **Phase 4a**: `_build_pgsc_calc_argv` now emits `-profile docker` (matches the 2026-05-17 smoke-proven path; `-profile conda` fails on linux/arm64). Test renamed + docstring updated to record the rationale. 1 flipped test, 8 existing pgsc_calc + CLI compute tests re-confirmed.
- [x] **Phase 4b**: **Retracted** the "drop pre-extraction post-fetch hook" decision from the dev-plan. Investigation confirmed pgsc_calc's `--run_ancestry` requires a *directory* of extracted panel files (`GRCh38_HGDP+1kGP_ALL.{pgen,pvar.zst,psam}`), not the `.tar.zst` tarball. The existing `_extract_pgs_catalog_ancestry_bundle` hook is correct and stays. Updated dev-plan Decision 6 and the Phase 4 deliverables list to record the correction.
- [x] **Phase 4c — orchestrator**: `compute_prs_with_coverage_fill` chains Tier 1 + Tier 2 + merge + pgsc_calc into one entry point. The merged VCF stages under `shard_scratch` (INV-D003) — pgsc_calc consumes it inside a single invocation; no point persisting it to `derived/`. Warm Tier 1/Tier 2 caches turn the orchestrator into a ~10–15 min pgsc_calc-only call.
- [x] **Phase 4c — CLI**: `genomeclaw pipeline prs-compute` subcommand with the same `--rationale ≥ 50 chars` INV-A003 gate the existing `pgs-compute` enforces. JSON envelope matches `INV-C002` (`command: "pipeline.prs-compute"`, `cli_output_schema_version: "1.0"`).

**Decisions Made**:
- **Test rename, not delete**, for the `-profile` flip. The original `test_compute_pgs_pins_profile_conda_and_pgsc_calc_revision_invR001` becomes `..._docker_...`. Keeps the regression-guard intent intact while updating the actual contract; the docstring records the smoke-proven rationale so a future "let's switch back to conda" change has a paper trail.
- **Two CLI subcommands**, not one. `pipeline pgs-compute` (existing) takes a pre-built VCF; `pipeline prs-compute` (new) takes a CRAM + scorefile and runs the whole flow. Single-entry-point would conflate two distinct user mental models — manual VCF-driven runs are useful for testing pgsc_calc against alternate inputs, while the agent path always goes through `prs-compute`.
- **Merged VCF stages in scratch**, not derived. pgsc_calc reads it once; a stale `derived/prs_coverage/<sample>/<panel>/pgs/<id>/merged.vcf.gz` would just be re-built from Tier 1 + Tier 2 next time anyway. The merge step is cheap relative to bcftools force-genotyping.
- **Re-export `compute_pgs` from coverage_fill**. Tests patch `coverage_fill.compute_pgs` to verify the orchestrator's call shape. Mirrors the existing `atomic_promote` re-export pattern for the same reason.

**Blockers / Issues**:
- None. Phase 4b's "drop pre-extraction hook" was a misread in the original plan draft — investigation surfaced the truth, the dev-plan was corrected, and no code change was needed. This is the kind of honest retraction the planning protocol calls for.

**REFACTOR step**:
- ruff: 3 auto-fixes (import ordering + 1 unused import) across orchestrator + CLI tests.
- One E402 (module-level import not at top of file) — the new `compute_prs_with_coverage_fill` import in `pipeline.py` started life embedded inside the Phase 4c section; promoted to the file's top-level import block.
- mypy: clean across `coverage_fill.py`, `pipeline.py`, `pgs.py`.
- Full suite: **642 passed / 104 skipped / 0 failed** (Phase 2 baseline was 636/104; +6 Phase 4 tests).

**Phase 4 status — COMPLETE**:
- 9 new/flipped tests (1 flipped + 3 orchestrator + 3 CLI prs-compute + 2 existing re-confirmed).
- Total plan progress: 39 tests across Phase 1a + 1b + 2 + 4, all GREEN (1 `needs_bio` skip).

**Next Steps**:
1. Commit Phase 4 (or batch with Phases 1-2).
2. Phase 3 (QC threshold table + 5-named-reasons decline taxonomy + `INV-C001` v1.7 typed exceptions + `INV-A003` rationale persistence on the `pgs_scores` row). Largest conceptual chunk left; touches the agent-facing decline surface.
3. Phase 5 (real-data smoke against `MPNRGLQ2K.cram` — resolves Open Question Q1 wall-clock + verifies end-to-end against the real toolkit image).

---

### 2026-05-18 — Phase 2 Implementation (Tier 2 + merge + cache semantics)

**Context Review Completed**:
- Re-read Phase 2 deliverables in [development-plan.md](development-plan.md).
- Reused the Phase 1 test idioms (regex-based bcftools fake parsing `--output` path).
- Confirmed Open Question Q2 stance — Tier 2 SNP-only for MVP, indel concordance deferred.

**Applicable Invariants** (Phase 1 carryovers):
- INV-D001 (CRAM read-only — `_force_genotype_tier2` checks `.crai`).
- INV-D003 (scratch staging via `shard_scratch` + `atomic_promote`).
- INV-R001 (cache path embeds scorefile SHA8 → upstream silent re-harmonisation forces rebuild).
- INV-P001 (no new egress).

**RED step output**:

```text
tests/integration/test_prs_coverage_fill_tier2.py  9 ImportError on:
  _extract_pgs_sites_from_scorefile, _extract_pgs_id_from_scorefile,
  _tier2_cache_path, _force_genotype_tier2, _merge_tier1_tier2,
  prepare_coverage_tier2
9 failed in 0.04s — all imports against the absent Tier 2 surface.
```

**Completed Today (Phase 2 — 9 new tests, all GREEN)**:
- [x] `_extract_pgs_sites_from_scorefile` — parses hmPOS_GRCh38 scoring files; SNP-only (indels filtered per Q2); panel→CRAM `chr` prefix rewrite; robust to PGS Catalog comment + blank header lines.
- [x] `_extract_pgs_id_from_scorefile` — pulls `#pgs_id=` out of the header section.
- [x] `_tier2_cache_path` — keyed by `(sample, panel, pgs_id, scorefile_sha8)`. Layout: `derived/prs_coverage/<sample>/<panel>/pgs/<PGS_ID>-<sha8>/tier2.vcf.gz`.
- [x] `_force_genotype_tier2` — same `bcftools mpileup → call → norm` pipe as Tier 1; PGS-derived sites/alleles TSVs are scratch-only (never persisted, deterministic from the scoring file).
- [x] `_merge_tier1_tier2` — `bcftools concat --allow-overlaps | bcftools sort` + `index --tbi`. Single `bash -c` pipe for atomicity.
- [x] `prepare_coverage_tier2` — orchestrator with cache-hit short-circuit; writes `tier2.qc.json` with INV-R001 provenance (scorefile SHA, PGS ID, bcftools version, SNP row count, GT distribution, mean DP, per-chrom counts).

**Decisions Made**:
- **REF/ALT orientation from PGS Catalog scoring files**: `other_allele` → REF, `effect_allele` → ALT. PGS Catalog convention (post-2021 scoring files) puts `other_allele` matching the reference. `bcftools --constrain alleles` accepts any pair regardless of orientation; pgsc_calc later normalises.
- **Two-tier cache directory layout**: `pgs/<PGS_ID>-<sha8>/` not `pgs/<PGS_ID>/<sha8>/`. Flat per-PGS dirs surface cache invalidation cleanly (a directory listing shows the sha8 suffix changing); also makes a future `prs cache-gc` step easy ("delete any `pgs/<id>-*` dir whose scorefile sha8 isn't current").
- **Both tiers reuse `_build_bcftools_pipe`**. The bcftools mpileup → call → norm pipe is identical; only the sites/alleles TSV source differs. No duplication, single rule for changes (e.g. when bumping `--max-depth`).
- **Tier 2 sites/alleles TSVs are scratch-only**, not promoted to derived. They're trivially regenerable from the scoring file and would otherwise duplicate data already on disk.

**Blockers / Issues**:
- None. Phase 2 cleanly extended the Phase 1 surface; no Tier 1 refactor needed.

**REFACTOR step**:
- ruff: one unused-import fix in the test file (auto-applied).
- mypy: replaced `# type: ignore[index]` comments with explicit `assert *_col is not None` blocks. Mypy narrows correctly from the asserts; the type-ignores were stale once the upstream `if None in (...) raise ValueError` guard landed.
- Full suite: 636 passed / 104 skipped / 0 failed (Phase 1 baseline was 627/104; +9 Phase 2 tests).

**Phase 2 status — COMPLETE**:
- 9 new tests covering Tier 2 force-genotyping, merge, scoring-file parsing, cache invariance.
- Total plan progress: 30 tests across Phase 1a + 1b + 2, all GREEN (1 `needs_bio`-gated skip).

**Next Steps**:
1. Commit Phase 2 (or batch with Phase 1).
2. Phase 3 (QC threshold table + 5-named-reasons decline taxonomy + `INV-C001` v1.7 typed exceptions + `INV-A003` rationale persistence). Bigger conceptual chunk; bumping deeper into the agent-facing surface.
3. Phase 4 (switch `_build_pgsc_calc_argv` from `-profile conda` to `-profile docker`; drop the `pgs_catalog_ancestry` post-fetch extraction hook; doctor section already in 1b; CLI surface for end-to-end compute).
4. Phase 5 (real-data smoke against `MPNRGLQ2K.cram` — resolves Open Question Q1 wall-clock).

---

### 2026-05-18 — Phase 1b Implementation (RED → GREEN → REFACTOR)

**Context Review Completed**:
- Re-read Phase 1a outputs + the pending-1b list in the previous work-notes entry.
- Studied existing patterns: [pgsc_calc wrapper CLI subcommand](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py), [ancestry_ready / prs_runtime_ready doctor probes](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py), [test_invP001_cli_no_egress.py](../../../../packages/toolkit/tests/privacy/test_invP001_cli_no_egress.py) urllib-stub pattern.
- Confirmed `tiny_cram` + `tiny_grch38_fasta` fixtures from [tests/conftest.py](../../../../packages/toolkit/tests/conftest.py) have aligned reads at chr17:43044295+ over a synthetic FASTA where the reference at that region is 'A' — perfect for a real-bcftools force-genotype smoke against `REF=A ALT=T` → 0/0.

**Applicable Invariants** (recurring from Phase 1a):
- INV-D001 / INV-D003 / INV-R001 / INV-P001 stay relevant.
- INV-A003 implicitly: the CLI subcommand surface preserves the agent's path to wire rationale + alternatives at Phase 2.

**RED step output**:

```text
test_prs_coverage_fill_materialize.py:  4 ImportError on `_materialize_pca_sites`
test_doctor.py (3 prs_coverage tests):  3 KeyError on `prs_coverage_ready`
test_cli_pipeline_prs_prepare_coverage:  3 UsageError "No such command 'prs-prepare-coverage'"

10 failed in 0.04s — all for the expected reason (absent symbols / unregistered command).
```

**Completed Today (Phase 1b — 10 new tests, all GREEN)**:
- [x] `_materialize_pca_sites` — plink2 LD-prune via DooD against `ghcr.io/pgscatalog/plink2:2.00a5.10`; emits plaintext `pca_sites.tsv` + `pca_alleles.tsv` + `pca_sites.provenance.json` under `reference/prs_pca_sites/<panel_version>/`. 4 tests covering argv shape, output layout, provenance JSON, chr-prefix rewrite.
- [x] `_collect_prs_coverage_ready` — doctor probe; 3 tests covering `no_samples` / `ready` / `partial` states. Wired into `doctor()` report alongside `ancestry_ready` + `prs_runtime_ready`.
- [x] `genomeclaw pipeline prs-prepare-coverage` — Typer subcommand; 3 tests covering happy path, cache-hit semantics, `--json` envelope conformance per `INV-C002`.
- [x] Privacy `test_invP001_no_egress_during_pipeline_prs_prepare_coverage` — confirms the CLI dispatch + wrapper logic never call `urllib.request.urlopen` (bcftools subprocess stubbed).
- [x] Real-bcftools `test_force_genotype_tier1_against_tiny_cram_emits_refref` (`needs_bio`-gated) — invokes the actual bcftools pipe against the synthetic `tiny_cram` + `tiny_grch38_fasta`, asserts `0/0` at chr17:43044300 where reference + reads are both 'A'.

**Decisions Made**:
- **Plaintext `.tsv`, not bgzip + tabix**, for the materialise outputs. bcftools `--regions-file` / `--targets-file` accept plaintext, and the full-autosome ~436k-line set still fits well under 10 MB. Avoids stubbing bgzip + tabix in the test fakes; keeps the materialise function subprocess-free past plink2. (Production correctness preserved — plain TSVs are a documented bcftools input format.)
- **Cache status string is `"built" | "hit"`** (not a richer enum). The CLI computes it by snapshotting cache presence before invoking the wrapper. Phase 2 can extend if a third state (e.g. `"invalidated_sha_mismatch"`) becomes useful.
- **`needs_bio` gate stays as-is** for the real-bcftools test. Skipping on the bare host venv matches the existing `test_invR001_bcftools_wrapper.py` discipline. The toolkit Docker image's CI job sets `GENOMECLAW_HAS_BIO=1` and runs it for real.

**Blockers / Issues**:
- None. The `needs_bio` test is correctly skipped locally (no samtools/bcftools on host); it will activate inside the toolkit image's CI job.

**REFACTOR step**:
- ruff: 1 import-order fix in the privacy test, auto-applied (`uv run ruff check --fix`).
- mypy: clean across `coverage_fill.py` + `doctor.py` + `pipeline.py`.
- Full suite: 627 passed / 104 skipped / 0 failed (Phase 1a baseline was 616/103; +11 new tests / +1 skip for `needs_bio` real-bcftools test).

**Phase 1 status — COMPLETE**:
- 1a: 11 tests (primitives + orchestrator) — done in earlier session.
- 1b: 10 tests (materialize + doctor + CLI + privacy + real-bcftools) — done this session.
- Total: 21 tests, all GREEN (1 `needs_bio`-gated skip on host venv).

**Next Steps**:
1. Commit Phase 1 (1a + 1b).
2. Phase 2 (Tier 2 per-PGS cache + merge + pgsc_calc wiring) — bigger chunk; defer to a fresh session.

---

### 2026-05-18 — Phase 1a Implementation (RED → GREEN → REFACTOR)

**Context Review Completed**:
- Re-read [development-plan.md](development-plan.md) Phase 1 deliverables + [phases/phase-1.md](phases/phase-1.md) TDD scaffold.
- Studied existing toolkit patterns: [_bcftools.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py) subprocess wrapper conventions, [scratch.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py) (`shard_scratch` + `atomic_promote`), [test_pgsc_calc_wrapper.py](../../../../packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py) subprocess-stub idiom.
- Confirmed `needs_bio` + `needs_prs_runtime` markers auto-skip on a bare venv via [conftest.py](../../../../packages/toolkit/tests/conftest.py); the unit-style tests use neither marker (no real bcftools required for the stubbed path).

**Applicable Invariants**:
- **INV-D001**: tests assert CRAM SHA256 unchanged after a run.
- **INV-D003**: tests assert in-flight VCF stages under `shard_scratch` and `atomic_promote`-s to derived/.
- **INV-R001**: `tier1.qc.json` carries source_cram_sha256 + panel_version + bcftools_version + tool_command + GT distribution + mean DP + per-chrom counts + schema_version.

**RED step output** (`uv run pytest tests/integration/test_prs_coverage_fill_*.py --tb=line`):

```text
collected 11 items
tests/integration/test_prs_coverage_fill_unit.py        FFFFF                  [ 45%]
tests/integration/test_prs_coverage_fill_integration.py FFFFFF                 [100%]

ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep.coverage_fill'  × 10
ImportError: cannot import name 'coverage_fill' from 'genomeclaw_toolkit.prep'  × 1

============================== 11 failed in 0.04s ==============================
```

All 11 tests fail with `ModuleNotFoundError` — confirms the RED step is honest (failure cause is exactly the absent module, not an unrelated regression).

**GREEN step**: created [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) (327 lines). Key design points:

- The bcftools pipe is one `bash -c` invocation — streaming `mpileup → call → norm + index` in a single subprocess so the pipe stays in-memory and the per-stage stderr is captured together.
- `shard_scratch` step name is `prs_coverage_tier1`; `run_id` derives from `cram_path.stem` for the Phase 1 prove-out — Phase 2 will wire the actual run-id from the orchestrator.
- Cache-hit detection compares `qc["source_cram_sha256"]` against a fresh hash of the current CRAM. A SHA mismatch (e.g. re-aligned CRAM) invalidates the cache.
- `MissingCramIndexError` carries a `samtools index <path>` hint so a missing `.crai` surfaces as an actionable error rather than a 50 GB sequential CRAM scan.
- `bcftools_version()` parse failures (empty stdout in stubbed tests) are caught and recorded as `"unavailable"` — the cache build doesn't fail over a provenance detail.

**Two minor RED→GREEN iterations** (kept honest):

1. The scratch-promote spy initially asserted `dst == output_vcf` against `promote_calls[-1]`, but the wrapper also promotes the `.tbi` sidecar (second call). Changed the assertion to inspect `promote_calls[0]` (the VCF promote) and added a loop verifying every recorded promote originates under scratch (the INV-D003 leak guard).
2. `bcftools_version()` in tests with stubbed subprocess returns empty stdout → `ValueError`. Added `ValueError` to the catch-clause so cache writes succeed with `bcftools_version="unavailable"` rather than failing the orchestrator.

**REFACTOR step**: ruff + mypy clean. One unused-variable lint fixed in idempotency test. Full toolkit suite 616 passed / 103 skipped / 0 failed — no regressions.

**Completed Today**:
- [x] 5 unit tests (parse_prune_in × 2, summarize_qc × 2, cache_path × 1) — all GREEN, no subprocess
- [x] 6 integration tests (argv shape, scratch→promote, INV-D001 immutable CRAM, INV-R001 QC fields, idempotency, missing .crai error) — all GREEN, subprocess stubbed
- [x] [coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) — primitives + orchestrator + typed error + module-level `atomic_promote` re-export for test patching
- [x] Full suite green (616/616 non-skipped); ruff + mypy clean

**Decisions Made**:
- Single `bash -c` pipe (not three sequential `subprocess.run` calls) for the bcftools mpileup→call→norm chain. Keeps the stream in-memory + per-stage stderr unified; matches what the chr22 prove-out actually ran.
- `bash -c` rather than constructing the pipe manually via Python `subprocess.PIPE` — the pipe template is human-readable, the shell-stop-on-error semantics (`&&`) are explicit, and the test fakes parse the argv with a single regex.
- Re-export `atomic_promote` from the module so tests can patch via `genomeclaw_toolkit.prep.coverage_fill.atomic_promote` rather than the canonical scratch module. Mirrors the `pgs.py:subprocess.run` patch pattern.

**Blockers / Issues**:
- None for Phase 1a. The deferred Phase 1b work (real-bcftools integration test, plink2 materialize, CLI subcommand, doctor section, privacy egress test) is scoped intentionally; each adds a new test surface with its own gating marker.

**Phase 1 status**: split into 1a (this session, primitives + orchestrator, 11 tests, all GREEN) and 1b (still pending, ~6 tests):

- `_materialize_pca_sites` via DooD against `ghcr.io/pgscatalog/plink2:2.00a5.10` — gated on `needs_prs_runtime`
- `genomeclaw prs prepare-coverage --sample <id>` CLI subcommand + 2 CLI tests (happy path, cache-hit)
- `_collect_prs_coverage_ready` doctor probe + 1 doctor test
- Privacy zero-egress test (whole prepare-coverage flow, mocked socket factory)
- Real-bcftools integration test against `tiny_cram` (gated on `needs_bio`)

**Next Steps**:
1. Land Phase 1a (commit) — primitives + orchestrator are independently useful and stable.
2. Phase 1b: write the deferred 6 tests RED, implement, GREEN.
3. Phase 2: Tier 2 per-PGS force-genotyping + merge + cache-key invariance.

---

### 2026-05-18 — Prove-out + Plan Drafting

**Context Review Completed**:
- Re-read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — applicable invariants confirmed: INV-D001, INV-D002, INV-D003, INV-P001, INV-R001, INV-C001 v1.7, INV-A003.
- Re-read [docs/plans/CLAUDE.md](../../CLAUDE.md) — followed the spec → dev-plan → work-notes → phase-1 flow; respected the real-data smoke gate principle.
- Re-read [docs/reports/prs-real-data-smoke-research-brief.md](../../../reports/prs-real-data-smoke-research-brief.md) — the brief that documented the failure and the four candidate fixes (A–D).
- Received the agent recommendation document (2026-05-18) — synthesizes two independent reviews into a two-tier bcftools-based cache recommendation; rejected the GATK GVCF approach (option B) in favour of bcftools forced-genotyping (option A+C hybrid).

**Applicable Invariants**:
- **INV-D001**: CRAM is read-only; force-genotype output writes to `derived/prs_coverage/`.
- **INV-P001**: zero new network egress; bcftools/plink2/pgsc_calc all on-device.
- **INV-R001**: cache key = (sample, pgs_id, scorefile_sha256, panel_version); tool versions on every row.
- **INV-C001 v1.7**: five-named-reasons decline taxonomy is structural, not advisory; wired as typed exceptions.
- **INV-A003**: agent rationale + two alternatives recorded on every agent-triggered `pgs_scores` row.

**Key Insights**:
- The bcftools pipe `mpileup -R sites | call -C alleles -T alleles | norm` is single-threaded compute; `--threads` only adds I/O compression threads, not parallel pileup. Wall-clock speed-up path is **parallelism across chromosomes**, bounded by Colima CPU count (currently 2).
- The chr22 PCA-eligible site count (6,812) was lower than the agent recommendation document's 1.14M target. Difference is the LD-prune r² threshold: we use `--indep-pairwise 1000 50 0.05` (r²<0.05, matching pgsc_calc's internal `FILTER_VARIANTS`); the document's 1.14M presumably comes from a less aggressive prune (r²<0.1 or r²<0.2). Decision: stick with r²<0.05 — it matches what pgsc_calc does internally, so the PCA projection alignment is mechanical.
- The panel uses chromosome naming `1, 2, …, 22, X, Y` (no `chr` prefix); the user CRAM and FASTA use `chr1, chr2, …, chr22, chrX, chrY, chrM`. The bcftools targets file must carry the `chr` prefix to match CRAM/FASTA — handled at TSV emission time with a single `awk` rewrite.

**Prove-out measurements (chr22, MPNRGLQ2K.cram, 2026-05-18, Apple Silicon M-series, 2-CPU 12 GB Colima)**:

| Step | Wall-clock | Peak RAM | Output |
|---|---|---|---|
| plink2 `--chr 22 --maf 0.01 --hwe 1e-6 --geno 0.05 --indep-pairwise 1000 50 0.05` via DooD (`ghcr.io/pgscatalog/plink2:2.00a5.10`, linux/amd64 emulated) | **114s** | n/a (plink2 internal `--memory 8000`) | 6,812 prune-in IDs |
| bcftools `mpileup -R sites.tsv.gz | call -C alleles -T alleles.tsv.gz | norm` against full CRAM, single-threaded | **99s** (cold cache) / **97s** (`--threads 2`) | **127 MiB** | 6,796 records in tier1.vcf.gz (198 KB) |

GT distribution (6,796 records / 6,812 sites → 16 collapsed during indel-normalization):

| GT | Count | % |
|---|---|---|
| `0/0` (REF/REF) | 5,744 | 84.52% |
| `0/1` (het) | 644 | 9.48% |
| `1/1` (hom-alt) | 347 | 5.11% |
| `./.` (low coverage) | 61 | 0.90% |
| Other | 0 | 0.00% |

Mean DP: **27.98×** (healthy 30× WGS). Indel-normalization realigned 204 records (3.0%) — expected for the LD-pruned set.

**Extrapolation to whole-autosome Tier 1 (Open Question Q1)**:
- chr22 panel-variant fraction of autosomes: 1,253,126 / ~80M (autosome subset of 84.3M total) ≈ **1.56%**
- Extrapolated autosome PCA-eligible site count: ~6,812 / 0.0156 ≈ **436,000**
- Single-threaded wall-clock: 99s × (436,000 / 6,812) = **6,330s ≈ 105 min**
- 2-CPU parallel (current Colima): **~53 min**
- 4-CPU: **~26 min**
- 8-CPU: **~13 min**

The agent recommendation document's "10–15 min for Tier 1" estimate is achievable with 8 CPUs. Current 2-CPU Colima delivers ~50–60 min; the user's M-series host has 8+ cores so bumping Colima is feasible. **Decision deferred to Phase 5**: measure full autosomes first, then choose CPU allocation based on the actual SLA cost.

**Completed Today**:
- [x] Verified chr22 force-genotyping primitive end-to-end on real data
- [x] Measured wall-clock, peak RAM, GT distribution, mean DP
- [x] Extrapolated to full-autosome SLA range
- [x] Drafted spec.md
- [x] Drafted development-plan.md
- [x] Drafted work-notes.md (this file)
- [x] Drafted phases/phase-1.md

**Decisions Made**:
- Reject GATK GVCF reconstruction (option B). bcftools `-C alleles` is the textbook primitive and is RAM-cheap; GATK's local reassembly is wasted work for known-allele forced genotyping.
- Adopt the two-tier cache architecture from the agent recommendation document. Tier 1 keyed by panel version; Tier 2 keyed by scoring-file SHA256.
- Switch `_build_pgsc_calc_argv` default from `-profile conda` to `-profile docker` (proven via smoke; conda fails on linux/arm64).
- Plan to drop the `pgs_catalog_ancestry` post-fetch extraction hook (pgsc_calc reads `.tar.zst` directly). Defer to Phase 4 so the cleanup doesn't entangle with Phase 1 TDD.
- Adopt the per-variant-count QC threshold table from the agent recommendation document Section 5.1 verbatim. Adopt the five-named-reasons decline taxonomy from Section 5.2 verbatim.
- Restrict initial Tier 2 site lists to SNPs (Open Question Q2). Revisit if/when an indel-heavy PGS lands.
- Stick with LD-prune r²<0.05 (matches pgsc_calc internal `FILTER_VARIANTS`).
- Use DooD for plink2 (one-time per panel release); do NOT bake plink2 into the toolkit image.

**Blockers / Issues**:
- None. Real CRAM, real panel, real toolkit image all available on the external drive (1.4 TB free of 1.8 TB).
- The `prs-real-data-smoke-recommendation.md` referenced in the spec doesn't exist yet as a separate doc — the recommendation lives only in the conversation that produced this plan. Follow-up: distill the recommendation document into `docs/reports/prs-real-data-smoke-recommendation.md` so the plan's external citation resolves.

**Next Steps**:
1. Land this plan (spec + dev-plan + work-notes + phase-1) on `main` or on a feature branch.
2. Begin Phase 1: write RED tests for `_materialize_pca_sites` and `_force_genotype_tier1`.
3. Optional: write the recommendation memo (`docs/reports/prs-real-data-smoke-recommendation.md`) so the plan's reference resolves.

---

## Phase Progress

### Phase 1: Tier 1 Materialize + Force-Genotype
**Status**: In Progress — 1a Complete, 1b Pending
**Started**: 2026-05-18
**Completed**: (1a) 2026-05-18

#### Test Results — Phase 1a
```text
tests/integration/test_prs_coverage_fill_unit.py .....                   [ 45%]
tests/integration/test_prs_coverage_fill_integration.py ......           [100%]
============================== 11 passed in 0.07s ==============================

Full toolkit suite: 616 passed, 103 skipped, 0 failed
ruff: All checks passed
mypy: Success: no issues found in 1 source file
```

#### Results — Phase 1a
- Created [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py)
- Created [packages/toolkit/tests/integration/test_prs_coverage_fill_unit.py](../../../../packages/toolkit/tests/integration/test_prs_coverage_fill_unit.py) (5 unit tests)
- Created [packages/toolkit/tests/integration/test_prs_coverage_fill_integration.py](../../../../packages/toolkit/tests/integration/test_prs_coverage_fill_integration.py) (6 integration tests with subprocess stubs)

#### Notes — Phase 1a
- All 11 tests went RED→GREEN cleanly. Two minor iterations during GREEN (spy on `.tbi` promote; `ValueError` on stubbed `bcftools --version` parsing) — both kept honest in the implementation rather than papered over.
- Module-level `atomic_promote` re-export so tests can patch via `coverage_fill.atomic_promote` (mirrors `pgs.py:subprocess.run` patching).
- INV-D001 (CRAM read-only), INV-D003 (scratch → promote), INV-R001 (qc.json schema) verified by tests.

#### Phase 1b Deferred Work
- `_materialize_pca_sites` (plink2 LD-prune via DooD) — gated `needs_prs_runtime`
- CLI subcommand `genomeclaw prs prepare-coverage` + 2 tests
- Doctor `_collect_prs_coverage_ready` + 1 test
- Privacy zero-egress test
- Real-bcftools integration test against `tiny_cram` — gated `needs_bio`

---

### Phase 2: Tier 2 + Cache + Merge

**Status**: Pending

### Phase 3: QC + Decline Taxonomy + INV-C001/INV-A003

**Status**: Pending

### Phase 4: -profile docker, doctor, CLI polish

**Status**: Pending

### Phase 5: Real-data smoke gate

**Status**: Pending

---

## Key Decisions

### Decision 1: bcftools `-C alleles`, not GATK HaplotypeCaller `-ERC GVCF`
**Date**: 2026-05-18
**Context**: Need to recover REF/REF dosages from the Nebula variant-only VCF for pgsc_calc PCA projection.
**Decision**: Use `bcftools mpileup -R sites | bcftools call -C alleles -T alleles | bcftools norm` as the forced-genotyping primitive.
**Rationale**: Textbook tool for forced genotyping at known alleles. RAM-cheap (127 MiB measured on chr22 vs. multi-GB JVM heap for GATK). No new dependency — bcftools already in `genomeclaw/toolkit:prs-phase1`. Skips local reassembly, which is wasted work when alleles are known.
**Alternatives Considered**: GATK HaplotypeCaller GVCF + ReblockGVCF + bcftools convert (option B from research brief); naive `missing2ref` backfill (rejected — false REF/REF at low-coverage sites corrupts PCA); the Fasold "force-ALT-allele" rewrite (rejected — author advises against, fails on indels and strand-ambiguous sites); local imputation (rejected — >20 GB RAM ceiling violation).
**Affected Invariants**: INV-R001 (rebuildability — bcftools is pinned in `_versions.PRS_RUNTIME_VERSIONS`), INV-P001 (privacy — all on-device).

### Decision 2: Two-tier cache, not one-tier
**Date**: 2026-05-18
**Context**: PCA-eligible site set is fixed by panel; PGS scoring sites vary per agent question.
**Decision**: Tier 1 = PCA-eligible sites, one-time per (sample, panel_version). Tier 2 = per-PGS scoring sites, cached by (sample, pgs_id, scorefile_sha256).
**Rationale**: Amortizes the expensive CRAM-decoding cost across questions. First-time question against a new PGS: Tier 2 build (~5–10 min for 100k-variant PGS) + pgsc_calc (~10–15 min). Subsequent question against same PGS: pgsc_calc only (~10–15 min).
**Alternatives Considered**: Single PCA-only cache (would still need ad-hoc per-PGS genotyping); single per-PGS cache (re-pays PCA layer on every PGS).
**Affected Invariants**: INV-R001 (cache key includes everything that determines output).

### Decision 3: `-profile docker`, not `-profile conda`
**Date**: 2026-05-17 (during smoke), formalized 2026-05-18
**Context**: pgsc_calc v2.2.0 requires `-profile <something>`; `-profile conda` failed on linux/arm64.
**Decision**: Switch `_build_pgsc_calc_argv` default to `-profile docker`. Use DooD (mount `/var/run/docker.sock`, identical-path bind-mounts) so the nested Nextflow can spawn sibling containers.
**Rationale**: Empirically the only profile that works on Apple Silicon. plink2 2.0a5.10 (pgsc_calc's pinned version) is not packaged on linux/arm64 conda-forge.
**Alternatives Considered**: `-profile mamba` (same plink2 packaging issue); `-profile singularity` (not installed on host).
**Affected Invariants**: INV-D002 (sibling containers spawned by DooD run host-side, not in sandbox), INV-R001 (pinned via `_versions.PRS_RUNTIME_VERSIONS`).

### Decision 4: LD-prune r² < 0.05, not r² < 0.1 or r² < 0.2
**Date**: 2026-05-18
**Context**: Agent recommendation document quotes ~1.14M PCA-eligible sites; chr22 prove-out yielded 6,812 → extrapolated ~436k autosome sites. The gap is the LD-prune threshold.
**Decision**: Use `--indep-pairwise 1000 50 0.05` (matches pgsc_calc internal `FILTER_VARIANTS`).
**Rationale**: We want the PCA projection to align mechanically with what pgsc_calc does internally. Less aggressive prune (r²<0.1 or r²<0.2) gives a denser set but doubles the Tier 1 wall-clock. Stick with 0.05; revisit only if FRAPOSA Mahalanobis distance is structurally too noisy on the user's PC vector.
**Affected Invariants**: INV-R001 (the prune parameters are pinned).

---

## Files Modified

### Created
- `docs/plans/active/prs-input-coverage-fill/spec.md` — feature specification
- `docs/plans/active/prs-input-coverage-fill/development-plan.md` — chosen solution + phase overview
- `docs/plans/active/prs-input-coverage-fill/work-notes.md` — this file
- `docs/plans/active/prs-input-coverage-fill/phases/phase-1.md` — Tier 1 TDD scaffold

### Modified
- (none yet)

### Deleted
- (none)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] None planned. If implementation surfaces a structural rule worth promoting, propose it via the standard channel.

### Other Documentation
- [ ] `docs/reports/prs-real-data-smoke-recommendation.md` — distill the agent recommendation document so the spec's reference resolves (deferred; not blocking).
- [ ] `docs/reference/prs-pipeline.md` — architecture, cache semantics, decline taxonomy (created in Phase 5).
- [ ] `docs/reference/grand-plan.md` — update Theme G PRS surface (after Phase 5).
- [ ] `docs/plans/active/prs-bootstrap-meta.md` — link this plan as Stage 5 follow-up.

---

## Open Risks & Follow-ups

- **Q1 (Tier 1 full-autosome wall-clock)**: chr22 measurement extrapolates to 53–105 min depending on Colima CPU allocation. Resolution in Phase 5 GREEN.
- **Q2 (indel reliability under `-C alleles`)**: spot-check at Phase 5; restrict initial Tier 2 to SNPs.
- **Q3 (per-chromosome GT distribution)**: emit per-chrom QC in tier1.qc.json from Phase 1.
- **Q4 (LD-prune aggressiveness)**: stuck at r²<0.05 for MVP; revisit if FRAPOSA noisy.
- **Q5 (plink2 packaging)**: DooD for MVP; bake into image only if Tier 2 ever calls plink2 (it doesn't).
- **pgsc_calc v3 trajectory**: if v3 ships native CRAM/VCF before Phase 5, consider whether to short-circuit this plan.
- **PGS Catalog scoring-file mirror**: quarterly refresh cadence; cache key includes SHA256 so silent re-harmonization doesn't return stale Tier 2.

---

## Prove-out Artefacts (2026-05-18)

Scratch workspace: `/Volumes/Genome_Work/genomeclaw/_scratch/prs-coverage-prove/`

```text
prs-coverage-prove/
├── logs/
│   ├── plink2_chr22.log         # plink2 RED→prune-in (114s)
│   ├── timing.txt               # bcftools pipe wall-clock (99s)
│   ├── timing_t2.txt            # --threads 2 wall-clock (97s, no improvement)
│   ├── docker_stats.log         # peak memory sampling (127 MiB peak)
│   ├── mpileup.err / call.err / norm.err
├── pca_sites/
│   ├── chr22_pca.prune.in       # 6,812 IDs
│   ├── chr22_pca.prune.out      # 132,483 IDs filtered out by LD
│   ├── chr22_alleles.tsv.gz{,.tbi}   # bcftools call -C alleles input
│   └── chr22_sites.tsv.gz{,.tbi}     # bcftools mpileup -R input
└── tier1_chr22/
    ├── chr22_tier1.vcf.gz       # 198 KB, 6,796 records, 84.5% REF/REF
    └── chr22_tier1.vcf.gz.tbi
```

Keep this workspace until Phase 5 completes — it's the empirical anchor for the SLA conversations.
