# Phase 6 Slice E (v2): Agent-driven PRS

**Status**: In Progress (E.1 + E.2 complete 2026-05-17; E.3 + E.4 pending)
**Started**: 2026-05-17 (E.1)
**Completed**:
**Parent Phase**: [phase-6.md](phase-6.md) (Slice E expansion)
**Spec**: [MVP spec Q8 v1.6](../spec.md#q8--prs-via-pgsc_calc--fixed-three-trait-panel--genomeclaw_pgs-6th-tool--agent-driven-four-tool-surface-no-pre-curated-panel) (AC9 v1.6)
**Architecture report**: [docs/reports/agent-driven-prs-computation.md](../../../../reports/agent-driven-prs-computation.md)
**Supersedes**: [phase-6-slice-e.md](phase-6-slice-e.md) (v1; static-panel design; SUPERSEDED 2026-05-17)

---

## Objective

Stand up the PRS layer as an **agent-driven, host-computed, memory-cached** capability per the v1.6 architecture: the agent picks a PGS Catalog scorefile per question, persists its choice rationale + alternatives considered, triggers an async host-side `pgsc_calc` compute, and returns a calibrated result. Three sub-slices ship in sequence; each is a single RED → GREEN → REFACTOR cycle.

After Slice E v2 lands:
- Story 10 ("my dad had a heart attack at 58. is there anything in my genome about cad risk?") becomes fully data-backed against a real (agent-computed) PRS — not the synthetic fixture the agent-research-and-synthesis plan's slice-2 live test currently uses.
- The long-tail of trait questions ("what about asthma? T2D? prostate?") works through the same code path; no spec amendments, no Dockerfile rebuilds, no per-trait curation.
- The PRS-decline pattern (per `INV-C001` v1.7) prevents computes against trait literatures that aren't mature enough to produce a meaningful percentile.

## Scope Boundaries

### In scope

- **Schema additions** (host-side):
  - `pgs_scores` table in `variants.duckdb`. Keyed by `pgs_id` (PGS Catalog ID; e.g. `PGS000018`); columns: `pgs_id` (PK), `trait_label`, `percentile_in_user_ancestry`, `raw_score`, `study_population`, `calibration_warning`, **`agent_choice_rationale`** (per `INV-A003`), **`requested_for_question`** (per `INV-A003`), **`superseded_by`** (NULL for current rows; PGS Catalog ID of the superseding row when superseded), plus the seven canonical provenance columns.
  - `pgs_compute_tasks.sqlite` under `derived/<run-id>/`: small SQLite holding `(task_id, pgs_id, trait_label, rationale, requested_for_question, status, requested_at, started_at, completed_at, error)` for in-flight + completed agent-triggered compute requests. Status enum: `queued | running | done | failed`. The `failed` status carries an error message; one specific failure mode is `compute_path_disabled` (kill-switch on).
  - `PgsRow` / `PgsRowResponse` / `PgsListResponse` / `PgsComputeRequest` / `PgsComputeTaskResponse` Pydantic models in [schemas/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py).

- **`pgsc_calc` wrapper** at [prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py):
  - `compute_pgs(*, vcf, pgs_id, derived_root, reference_root) -> PgsRow` invokes Nextflow + `pgsc_calc`, parses the score table, applies continuous-ancestry calibration, returns a typed row.
  - **PGS Catalog scoring-weight fetch** is host-side, INV-P001 install-time-consent. Cache under `<reference_root>/pgs_catalog/PGS<id>/`. No per-fetch user approval per the [report's "Why no per-request user approval?" section](../../../../reports/agent-driven-prs-computation.md).
  - `PgsReferenceMissingError` (typed) when `<reference_root>/ancestry/{1000g,hgdp}/` is missing — surfaces a one-line install hint.

- **CLI subcommand** at [`_cli/commands/pipeline.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py):
  - `genomeclaw pipeline pgs-compute --pgs PGS000018 --vcf <path> --reference-root <X> --rationale '<text>' --question '<text>'` — manual invocation outside the agent path. Useful for the project owner's real-data smoke + for E.3's tests.
  - Output: `{run_id, pgs_id, percentile, calibration_warning, duration_s}` envelope per `INV-C002`.

- **Four host-service endpoints** at [service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) + [service/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py):
  - `GET /v1/pgs/computed` → `PgsListResponse` (one row per computed PRS for this user).
  - `GET /v1/pgs/computed/{pgs_id}` → `PgsRowResponse` (single PRS in full, including `agent_choice_rationale` + `requested_for_question`).
  - `POST /v1/pgs/compute` → `PgsComputeTaskResponse` (returns `task_id` + `status=queued|running`). Body: `PgsComputeRequest`. Enforces concurrency cap; on kill-switch active returns `status=failed` with error `compute_path_disabled`.
  - `GET /v1/pgs/compute/{task_id}` → `PgsComputeTaskResponse` (status polling).

- **Async compute orchestrator** at [service/pgs_compute_orchestrator.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/) (new module):
  - Background worker that drains the `queued` rows of `pgs_compute_tasks.sqlite` in single-concurrency, invokes `compute_pgs(...)`, updates status, on completion writes the `pgs_scores` row + the matching `clinical-non-actionable` `findings` row.
  - **Concurrency cap**: 1 in-flight `pgsc_calc` at a time. Additional requests queue.
  - **Kill-switch**: `genomeclaw config set pgs.compute_enabled false` makes every `POST /v1/pgs/compute` return `status=failed` with error `compute_path_disabled`. This is the user's full-revocation lever.
  - **No daily wall-clock budget** *(decision recorded 2026-05-17)*: a per-day cumulative-wall-clock cap was considered but rejected for the single-user PoC. The concurrency cap (no simultaneous waste) + the natural per-compute time bound (~5 min for `pgsc_calc` on one PGS) + the kill-switch (full revocation) bound runaway-compute risk without the budget mechanism's tracking + race-condition complexity. Add back later if a real failure surfaces.

- **Four plugin tools** at [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts):
  - `genomeclaw_pgs_list` — `Type.Object({})` → `GET /v1/pgs/computed`
  - `genomeclaw_pgs_get` — `Type.Object({ pgs_id: Type.String({ minLength: 1 }) })` → `GET /v1/pgs/computed/{pgs_id}`
  - `genomeclaw_pgs_compute` — `Type.Object({ pgs_id, trait_label, rationale: Type.String({ minLength: 50 }), requested_for_question })` → `POST /v1/pgs/compute`
  - `genomeclaw_pgs_compute_status` — `Type.Object({ task_id: Type.String({ minLength: 1 }) })` → `GET /v1/pgs/compute/{task_id}`

  All four are `output_class: "summary"` per `INV-P002`. The plugin's registration-summary log line goes from "(5 tools)" to "(9 tools)". Sandbox image bake includes the agent-research-and-synthesis baseline (workspace bootstrap, web_search config, thinkingDefault: xhigh).

- **Agent system prompt additions** at [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md):
  - **§4 Step 3 / Step 4 PGS-compute flow paragraph**: when to invoke `_compute`, what to write in `rationale` (alternatives considered + why this one), what to write in `requested_for_question` (verbatim user question), how to surface the in-flight wait to the user ("I'm computing…; ~5 min").
  - **§9 PRS-decline pattern** as a peer to the existing hard-genes decline:
    - Four decline criteria: top-decile RR < ~1.5×; no independent replication; ancestry-calibration failure for this user; no biologically-grounded polygenic basis.
    - Two-named-reasons rule (decline must enumerate two specific criteria from the four-set).
    - Worked example trait that should decline (e.g. creativity PRS).
    - Decline turn writes a memory note with `compute_decision: decline` so future sessions hit the decline note before re-deciding.

- **Policy preset update** at [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml): allowlist the four new `/v1/pgs/*` paths.

- **Side fix while in `index.ts`**: drop the stale `gene_note:CYP1A2 / topic:hard-genes` examples from `genomeclaw_evidence`'s description (retired in the agent-research-and-synthesis plan but the description still names them).

### Out of scope (Slice E.4 — deferred per the methodological-review pass)

- **Validation study** of agent PGS-selection quality against expert-curated benchmarks for 8-12 canonical traits. Personal-use PoC accepts the risk; production deployment requires this before launch.
- **Pre-compute consent turn** analogous to clinical genetic-counseling pre-test discussion. Personal-use PoC accepts the risk; production deployment requires this.
- **Outcomes capture** (whether the user acted on a PRS finding, whether their lipid panel changed, etc.). Open-loop is endemic to all personal-genomics tools; not solvable in this slice.
- **Production-grade Nextflow runner image bundling**. `pgsc_calc` is a heavy Nextflow + per-workflow Docker dependency; the host system needs Nextflow installed for the wrapper to invoke `pgsc_calc`. Image-level integration tests stay `needs_bio` + skipped on the host venv; the real-data smoke runs against the project owner's already-installed `pgsc_calc`.

### Out of scope (Slice F or later)

- **Story 10 live snapshot re-staging** against a real (agent-computed) PRS — currently the agent-research-and-synthesis plan's slice-2 test runs against a synthetic `clinical-non-actionable` fixture. Re-staging is a slice-F task, not blocking E.

## Invariants Enforced in This Slice

- **`INV-A003`** *(promoted at v1.11)* — `pgs_scores` rows carry `agent_choice_rationale` + `requested_for_question` non-null non-empty; memory-note cross-reference; decline-pattern persistence; supersession trail with `superseded_by`.
- **`INV-C001` v1.7** — PRS-decline pattern documented in agent system prompt + two-named-reasons rule + four criteria + worked example. Behavioural decline test against an immature trait.
- **`INV-A002`** — synthesis-reasoning floor applies to the PGS-choice reasoning step (it IS a health-interpretation turn). The agent reads PGS Catalog metadata + literature at the model's ceiling.
- **`INV-A001`** — every `pgs_compute` (success or decline) is paired with a memory note carrying the agent's reasoning trail.
- **`INV-P001`** v1.7 — PGS Catalog egress is INV-P001-class install-time consent; no per-compute approval; sandbox does NOT add `pgscatalog.org` to any allowlist (the egress is host-side only).
- **`INV-P002`** — all 4 new PGS tools carry `output_class: "summary"`; never return raw PGS variant lists.
- **`INV-E001`** — PRS findings (in `findings`) carry `evidence_ref=pgs_catalog:PGS<id>` non-empty.
- **`INV-R001`** — `pgs_scores` + `pgs_compute_tasks.sqlite` rows carry the seven canonical provenance columns.

---

## TDD Steps

### Sub-slice E.1 — Schema + endpoint contracts + plugin tool surface (host-side, fast)

**Step E.1.1 — RED: write the failing tests**

Host-side tests (`packages/toolkit/tests/integration/` + `packages/toolkit/tests/invariants/`):

1. `test_pgs_model.py::test_pgs_row_response_model_pinned_shape` — `PgsRowResponse` carries exactly the documented fields with `extra="forbid"`.
2. `test_pgs_model.py::test_pgs_compute_request_requires_long_rationale` — `PgsComputeRequest` rejects a `rationale` shorter than 50 chars (force the agent to explain).
3. `test_pgs_model.py::test_pgs_finding_category_pinned_to_non_actionable` — constructing a `Finding(category="clinical-non-actionable", evidence_ref="pgs_catalog:PGS000018", clinical_escalation=None)` succeeds; setting `clinical_escalation` non-None raises.
4. `test_pgs_scores_ddl.py::test_create_store_emits_pgs_scores_with_invA003_columns` — `create_store()` emits the `pgs_scores` table with all 6 domain columns + `agent_choice_rationale` + `requested_for_question` + `superseded_by` + the 7 provenance columns; double-create is idempotent.
5. `test_pgs_scores_ddl.py::test_pgs_compute_tasks_sqlite_schema` — `pgs_compute_tasks.sqlite` carries the documented status enum + timestamps.
6. `test_service_pgs.py::test_pgs_list_returns_empty_when_no_rows` — `GET /v1/pgs/computed` returns 200 + `{rows: [], total: 0}` when no `pgs_scores` rows exist.
7. `test_service_pgs.py::test_pgs_list_returns_rows_when_present` — stage two `pgs_scores` rows; assert `GET /v1/pgs/computed` returns both with field shape matching `PgsListResponse`.
8. `test_service_pgs.py::test_pgs_get_returns_row_for_known_id` — stage a row for `PGS000018`; `GET /v1/pgs/computed/PGS000018` returns 200 + full `PgsRowResponse`.
9. `test_service_pgs.py::test_pgs_get_returns_404_for_unknown_id` — `GET /v1/pgs/computed/PGS999999` returns 404 + typed error body.
10. `test_service_pgs.py::test_pgs_compute_request_enqueues_task` — `POST /v1/pgs/compute` with a valid `PgsComputeRequest` returns 202 + `task_id` + `status=queued` (orchestrator stubbed; just inserts the row).
11. `test_service_pgs.py::test_pgs_compute_request_rejects_short_rationale` — `POST /v1/pgs/compute` with `rationale=""` returns 422.
12. `test_service_pgs.py::test_pgs_compute_status_returns_task_state` — given a `task_id`, `GET /v1/pgs/compute/{task_id}` returns the typed `PgsComputeTaskResponse`.
13. `test_service_pgs.py::test_pgs_compute_status_returns_404_for_unknown_task` — unknown `task_id` → 404.
14. `test_service_pgs.py::test_pgs_endpoint_response_excludes_bulk_fields_invP002` — `GET /v1/pgs/computed/{pgs_id}` response body has exactly the 9 documented fields; no raw variant list ever surfaces.

Plugin-side tests (`packages/nemoclaw-plugin/tests/index.test.ts`):

15. `test_genomeclaw_pgs_list_tool_registered` — after `register(api)`, the api's tool registry holds 9 entries including the 4 new `genomeclaw_pgs_*` tools.
16. `test_genomeclaw_pgs_get_routes_to_endpoint` — invoking with `{ pgs_id: "PGS000018" }` calls `safeCall(host, "/v1/pgs/computed/PGS000018")`.
17. `test_genomeclaw_pgs_compute_routes_to_endpoint_with_body` — invoking with `{pgs_id, trait_label, rationale, requested_for_question}` posts to `/v1/pgs/compute` with the body shape.
18. `test_genomeclaw_pgs_compute_rejects_short_rationale_at_schema_layer` — TypeBox rejects `rationale=""` at the plugin schema layer (defence-in-depth with the host-service 422).
19. `test_genomeclaw_pgs_compute_status_routes_to_endpoint` — invoking with `{task_id}` calls `safeCall(host, "/v1/pgs/compute/{task_id}")`.

**Step E.1.2 — GREEN: implement the minimum**

1. Author [schemas/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py) — 5 models.
2. Extend [prep/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) with `_PGS_SCORES_DDL` + `_PGS_COMPUTE_TASKS_DDL`; wire into `create_store()`.
3. Add `query_pgs_computed_list`, `query_pgs_computed`, `enqueue_pgs_compute`, `query_pgs_compute_status` to [service/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py). Orchestrator logic is stubbed; just inserts into the tasks table.
4. Add 4 route handlers to [service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) (mirror `/v1/evidence/{ref}`'s pattern).
5. Register the 4 new `genomeclaw_pgs_*` tools in [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts); bump log line to `(9 tools)`. Drop stale `gene_note:` / `topic:` examples from the `genomeclaw_evidence` description.
6. Extend [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml) with the 4 new `/v1/pgs/*` paths.

**Step E.1.3 — REFACTOR + verify**

- Ruff + format clean on all touched files.
- All 14 host tests + 5 plugin vitest pass.
- Full host suite + `needs_sandbox` sweep (against the new image) stay green.
- Update Phase 6 row in [development-plan.md](../development-plan.md) progress-tracking table.

### Sub-slice E.2 — pgsc_calc wrapper + provenance + CLI

**Step E.2.1 — RED: write the failing tests**

1. `test_pgsc_calc_wrapper.py::test_compute_pgs_invokes_pgsc_calc_with_run_ancestry` — wrapper calls `pgsc_calc` with `--run_ancestry` AND the scorefile for the supplied `pgs_id`. Asserts on captured argv (subprocess mocked).
2. `test_pgsc_calc_wrapper.py::test_compute_pgs_parses_aggregated_scores_norm` — wrapper consumes fixture `<work_dir>/score/aggregated_scores.txt` + `<work_dir>/ancestry/aggregated_scores_norm.txt` + returns a `PgsRow` with `percentile_in_user_ancestry` populated.
3. `test_pgsc_calc_wrapper.py::test_compute_pgs_surfaces_calibration_warning_for_oo_distribution_ancestry` — fixture where the ancestry estimate falls outside the training distribution → `calibration_warning` is non-null.
4. `test_pgsc_calc_wrapper.py::test_compute_pgs_raises_pgs_reference_missing_when_ancestry_data_absent` — when `<reference_root>/ancestry/{1000g,hgdp}/` is missing, raises `PgsReferenceMissingError` with a clean install hint.
5. `test_pgsc_calc_wrapper.py::test_compute_pgs_returns_pgs_row_with_invA003_provenance` — the returned `PgsRow` carries `agent_choice_rationale` + `requested_for_question` populated from the wrapper's inputs.
6. `test_cli_pipeline_pgs_compute.py::test_cli_pipeline_pgs_compute_writes_pgs_scores_row` — invoking the subcommand against a fixture VCF + a mocked `pgsc_calc` produces a `pgs_scores` row carrying the 6 domain columns + 3 INV-A003 columns + 7 provenance columns.
7. `test_cli_pipeline_pgs_compute.py::test_cli_pipeline_pgs_compute_inserts_matching_clinical_non_actionable_finding` — after a successful compute, a row in `findings` exists with `evidence_ref=pgs_catalog:PGS<id>`, `category=clinical-non-actionable`, no `clinical_escalation`.
8. `test_cli_pipeline_pgs_compute.py::test_cli_pipeline_pgs_compute_json_envelope_shape` — `--json` mode emits the documented envelope per `INV-C002`.

**Step E.2.2 — GREEN: implement the minimum**

1. Author [prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) — `compute_pgs(...)`, `PgsRow` dataclass, `PgsReferenceMissingError`. Returns a `(PgsRow, ProvenanceTag)` tuple per the bcftools-wrapper pattern.
2. Add `pipeline pgs-compute` subcommand to [_cli/commands/pipeline.py](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py). JSON envelope per `INV-C002`; rich-mode summary for humans.
3. Add post-step that INSERTs the matching `clinical-non-actionable` `findings` row after the `pgs_scores` row lands.

**Step E.2.3 — REFACTOR + real-data smoke**

- Extract the aggregated-scores parser into a private helper.
- Ruff + format clean.
- All 8 new host tests pass.
- **Real-data smoke (manual; needs_bio)**: stage `<reference_root>/ancestry/{1000g,hgdp}/`; run `genomeclaw pipeline pgs-compute --pgs PGS000018 --vcf $NEBULA_VCF --rationale '<text>' --question '<text>'`; inspect the resulting `pgs_scores` row + matching `findings` row.

### Sub-slice E.3 — Async orchestration + concurrency + kill-switch + decline pattern + system-prompt update

**Step E.3.1 — RED: write the failing tests**

Host-side orchestration tests:

1. `test_pgs_compute_orchestrator.py::test_orchestrator_runs_queued_task_to_completion` — enqueue a task; orchestrator picks it up, invokes `compute_pgs` (mocked), updates status `queued → running → done`, writes the `pgs_scores` row.
2. `test_pgs_compute_orchestrator.py::test_orchestrator_enforces_concurrency_cap_of_one` — enqueue two tasks; assert the second stays `queued` until the first finishes.
3. `test_pgs_compute_orchestrator.py::test_kill_switch_disables_compute_path` — set `pgs.compute_enabled false`; new request returns `status=failed` with error `compute_path_disabled`; `pgsc_calc` is not invoked.
4. `test_pgs_compute_orchestrator.py::test_orchestrator_writes_matching_findings_row_on_done` — successful compute also INSERTs the `clinical-non-actionable` `findings` row.
5. `test_pgs_compute_orchestrator.py::test_orchestrator_supersession_marks_prior_row` — pre-stage a `pgs_scores` row; a second compute for the same `pgs_id` (e.g., re-research with a newer scorefile lands; agent supersedes) sets `superseded_by` on the prior row.

`needs_sandbox` invariant tests:

6. `test_invA003_pgs_provenance_columns.py::test_pgs_scores_row_carries_agent_choice_rationale_non_null` — schema column-existence gate; column is NOT NULL.
7. `test_invA003_pgs_provenance_columns.py::test_pgs_scores_row_carries_requested_for_question_non_null` — same.
8. `test_invP001_pgsc_calc_sandbox_has_no_pgscatalog_allowlist.py::test_sandbox_policy_preset_does_not_allow_pgscatalog_org` — the sandbox image's policy preset does NOT include `pgscatalog.org` in any `endpoints` allowlist (compute happens host-side; sandbox should never reach PGS Catalog directly).

Prompt-content gates (in [test_agent_system_prompt_contract.py](../../../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)):

9. `test_agent_system_prompt_documents_pgs_compute_flow` — §4 Step 3/4 names the four PGS tools + when to invoke `_compute` + the in-flight wait pattern.
10. `test_invC001_v17_system_prompt_documents_prs_decline_pattern` — §9 enumerates the four decline criteria + the two-named-reasons rule + at least one worked-example trait (e.g., creativity PRS).

Live `live_llm` tests (extends the agent-research-and-synthesis live-smoke harness):

11. `test_live_story10_pgs_compute_end_to_end.py::test_story10_real_pgs_compute_live` — Story-10 question; agent picks a PGS, invokes `_compute`, polls until `done`, surfaces calibrated framing citing the chosen PGS Catalog ID. Asserts (a) `genomeclaw_pgs_compute` was invoked, (b) the resulting `pgs_scores` row's `agent_choice_rationale` enumerates ≥1 alternative scorefile + states why this one over them, (c) the matching memory note is well-formed per `INV-A001`, (d) the reply cites the chosen `pgs_catalog:PGS<id>` + at least one primary source (PubMed / URL) from the choice rationale.
12. `test_live_prs_decline_immature_trait.py::test_creativity_prs_declines_with_two_reasons` — ask the agent about a known-immature trait (e.g. creativity); assert (a) the agent does NOT invoke `genomeclaw_pgs_compute`, (b) the reply names two specific decline reasons from the four-criteria set, (c) the trace shows the agent did the research step before declining (reasoned decline, not hardcoded refusal), (d) a decline-shaped memory note lands on disk with `compute_decision: decline`.
13. `test_live_prs_decline_rehydration.py::test_creativity_prs_second_session_hits_decline_note` — second session asking the same immature-trait question hits the prior decline note via `memory_search` + validates it (INV-C001 v1.6 three-check) + replies from the validated decline note rather than re-researching.

**Step E.3.2 — GREEN: implement the minimum**

1. Author [service/pgs_compute_orchestrator.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py) — background-worker loop, concurrency cap, kill-switch enforcement, status transitions, supersession on duplicate `pgs_id`.
2. Wire the orchestrator into the host service startup (FastAPI lifespan).
3. Extend [agent-system-prompt.md](../../../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md):
   - §4 Step 3/4: PGS-compute flow paragraph (when to call `_compute`, what to write in `rationale`, in-flight wait pattern).
   - §9: PRS-decline pattern with four criteria + two-named-reasons rule + worked example.
4. Rebuild the sandbox image as `genomeclaw/sandbox:phase-6e-v2`.
5. Extend [packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py](../../../../packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py) to accept memory notes with a `compute_decision` section (`success | decline`).

**Step E.3.3 — REFACTOR + verify**

- All 14 new tests (host + needs_sandbox + prompt-content + live_llm) pass.
- The live `live_llm` decline test costs one real OpenAI call (~$0.20 + ~4 min); the decline-rehydration test costs a second call. Story-10 compute end-to-end costs ~$0.50 + ~8-10 min (real `pgsc_calc` background compute + agent reasoning).
- Cumulative live-test runtime budget after E.3: ~22-25 min wall-clock + ~$1.20 for the full Slice E v2 live sweep (Story 10 compute + Story 10 cached re-ask + decline + decline rehydration).
- Mark Slice E v2 complete in [development-plan.md](../development-plan.md) progress-tracking.

---

## Files

| File | Action | Slice | Purpose |
|------|--------|-------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` | CREATE | E.1 | 5 Pydantic models |
| `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | MODIFY | E.1 | Add `_PGS_SCORES_DDL` + `_PGS_COMPUTE_TASKS_DDL` |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY | E.1 | `query_pgs_*` + `enqueue_pgs_compute` |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | E.1 | 4 new routes |
| `packages/toolkit/tests/integration/test_pgs_model.py` | CREATE | E.1 | 3 model tests |
| `packages/toolkit/tests/integration/test_pgs_scores_ddl.py` | CREATE | E.1 | 2 DDL tests |
| `packages/toolkit/tests/integration/test_service_pgs.py` | CREATE | E.1 | 9 endpoint tests |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY | E.1 | Register 4 new tools; bump log line to "(9 tools)"; drop stale `gene_note:` / `topic:` examples from `genomeclaw_evidence` description |
| `packages/nemoclaw-plugin/tests/index.test.ts` | MODIFY | E.1 | 5 new vitest tests |
| `packages/nemoclaw-plugin/policy-preset.yaml` | MODIFY | E.1 | Allowlist `/v1/pgs/*` (4 new paths) |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | CREATE | E.2 | `compute_pgs(...)` + `PgsRow` + `PgsReferenceMissingError` |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | E.2 | Add `pgs-compute` subcommand |
| `packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py` | CREATE | E.2 | 5 wrapper tests |
| `packages/toolkit/tests/integration/test_cli_pipeline_pgs_compute.py` | CREATE | E.2 | 3 CLI tests |
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | CREATE | E.3 | Background worker + concurrency cap + kill-switch + supersession |
| `packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py` | MODIFY | E.3 | Accept `compute_decision` section |
| `packages/toolkit/tests/integration/test_pgs_compute_orchestrator.py` | CREATE | E.3 | 6 orchestrator tests |
| `packages/toolkit/tests/invariants/test_invA003_pgs_provenance_columns.py` | CREATE | E.3 | 2 `needs_sandbox` gates |
| `packages/toolkit/tests/invariants/test_invP001_pgsc_calc_sandbox_has_no_pgscatalog_allowlist.py` | CREATE | E.3 | 1 `needs_sandbox` gate |
| `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` | MODIFY | E.3 | 2 new prompt-content gates |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY | E.3 | §4 Step 3/4 PGS-compute flow + §9 PRS-decline pattern |
| `packages/toolkit/tests/integration/test_live_story10_pgs_compute_end_to_end.py` | CREATE | E.3 | 1 `live_llm` end-to-end |
| `packages/toolkit/tests/integration/test_live_prs_decline_immature_trait.py` | CREATE | E.3 | 1 `live_llm` decline behavioural |
| `packages/toolkit/tests/integration/test_live_prs_decline_rehydration.py` | CREATE | E.3 | 1 `live_llm` decline-rehydration |

---

## Verification

```bash
cd packages/toolkit

# E.1 — host-side, fast (no sandbox image, no OPENAI_API_KEY, no real pgsc_calc)
uv run pytest \
  tests/integration/test_pgs_model.py \
  tests/integration/test_pgs_scores_ddl.py \
  tests/integration/test_service_pgs.py \
  -v
uv run ruff check src/genomeclaw_toolkit/schemas/pgs.py \
  src/genomeclaw_toolkit/prep/store.py \
  src/genomeclaw_toolkit/service/store.py \
  src/genomeclaw_toolkit/service/app.py

cd ../nemoclaw-plugin
npm test

# E.2 — wrapper + CLI (host-side; pgsc_calc subprocess mocked in unit tests)
cd ../toolkit
uv run pytest \
  tests/integration/test_pgsc_calc_wrapper.py \
  tests/integration/test_cli_pipeline_pgs_compute.py \
  -v

# E.2 real-data smoke (manual, against the project owner's Nebula VCF; needs pgsc_calc + 1000G/HGDP ancestry data installed)
genomeclaw refs fetch --source pgs_catalog_ancestry --reference-root $REFS  # one-time
genomeclaw pipeline pgs-compute \
  --pgs PGS000018 \
  --vcf $VCF \
  --reference-root $REFS \
  --rationale 'Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS; best cross-ancestry calibration metadata.' \
  --question 'my dad had a heart attack at 58. is there anything in my genome about cad risk?' \
  --json
duckdb $DERIVED/CURRENT/variants.duckdb "SELECT * FROM pgs_scores WHERE pgs_id='PGS000018'"

# E.3 — orchestrator + needs_sandbox + live
uv run pytest \
  tests/integration/test_pgs_compute_orchestrator.py \
  tests/invariants/test_agent_system_prompt_contract.py \
  -v

# Build sandbox image
docker build -f packages/nemoclaw-plugin/sandbox/Dockerfile -t genomeclaw/sandbox:phase-6e-v2 packages/nemoclaw-plugin
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-6e-v2 uv run pytest -m needs_sandbox -v

# live_llm gates (cost: ~$1.20 + ~22-25 min total)
set -a ; source /Users/hugi/GitRepos/GenomeClaw/.env ; set +a
OPENAI_API_KEY="${OPENAI_API_KEY:-$OPEN_AI_API_KEY}" \
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-6e-v2 \
  uv run pytest -m live_llm tests/integration/test_live_story10_pgs_compute_end_to_end.py \
                            tests/integration/test_live_prs_decline_immature_trait.py \
                            tests/integration/test_live_prs_decline_rehydration.py \
                            -v
```

---

## Completion Criteria

Slice E v2 is complete when:

- [x] **E.1: complete 2026-05-17**. Shipped: 15 host tests (3 model + 3 DDL + 9 endpoint) + 5 plugin vitest. Host suite 570 → 585 pass; plugin vitest 16 → 21 pass; ruff + format clean on all 8 new/modified Python files + 3 new/modified TypeScript files. Two pre-existing invariant tests updated to reflect the v1.6 surface (`test_invP002_policy_preset_shape.py` — 4 new paths + `/v1/pgs/compute` is the first allow-listed POST; `test_invP001_plugin_default_egress.py` — `fetch(` matcher now ignores JSDoc lines). The plugin's `callHostService` was consolidated to dispatch GET/POST off the `body` arg (the v1.6 first-POST tool required this) so the INV-P001 single-fetch-call-site invariant survives the addition. Stale `gene_note:CYP1A2 / topic:hard-genes` examples dropped from the `genomeclaw_evidence` description while in `index.ts`. **Sandbox image rebuild deferred to E.3** (no image-bake-touching change in E.1 — only host-side schemas + service routes + plugin tool registrations).
- [x] **E.2: complete 2026-05-17 (sub-slice impl + tests)**. Shipped: [`prep/pgs.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) with `compute_pgs(...)` + `PgsRow` + `PgsReferenceMissingError`; [`pipeline pgs-compute`](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py) subcommand that drives the wrapper + INSERTs the matching `clinical-non-actionable` finding row in the same call. 8 new tests (5 wrapper + 3 CLI; subprocess-mocked); host suite 585 → 593 pass. **Real-data smoke against the project owner's Nebula VCF is the manual-run gate** — requires `pgsc_calc` + Nextflow + 1000G/HGDP ancestry data installed host-side. Defer to the user; the wrapper's surface is verified end-to-end by the mocked tests.
- [ ] E.3: 5 orchestrator tests + 3 `needs_sandbox` gates + 2 prompt-content gates + 3 `live_llm` tests all pass. Image `genomeclaw/sandbox:phase-6e-v2` carries the updated agent system prompt.
- [ ] INVARIANTS.md v1.11 + INV-A003 + INV-C001 v1.7 are referenced consistently across spec + dev-plan + phase docs + the report.
- [ ] Slice E row in [development-plan.md](../development-plan.md) progress-tracking marked complete with a one-line outcome.
- [ ] [phase-6-slice-e.md](phase-6-slice-e.md) v1 stays on disk as Status: SUPERSEDED for historical reference.

---

## Open Questions (carried over from the report; require project-owner decision)

- **Q-E2'**: supersession schema — when a later `pgs_compute` for the same `pgs_id` supersedes an earlier one (newer scorefile version lands; agent recomputes), do we keep both rows (audit trail) or replace? **My lean: keep both**, with the `superseded_by` field on the prior row pointing at the newer row's `pgs_id` — mirrors INV-A001's "prior note stays on disk" rule for memory notes. **Decision needed before Slice E.3.**
- **Q-E3'**: does PGS Catalog have a stable JSON API that's preferable to the agent doing `web_fetch` + HTML parsing? If yes, a thin `genomeclaw_pgs_catalog_lookup` (host-side) tool might simplify the agent's PGS-discovery work. **Lean: investigate first** — if PGS Catalog's REST API is stable + well-documented, the thin tool is high-value; if not, the agent's existing `web_search` + `web_fetch` are sufficient. **Decision can wait until after E.2.**

(An earlier draft of this plan included a Q-E2' around the default value for a daily wall-clock budget on `pgsc_calc`. The budget mechanism itself was removed 2026-05-17 — see the "Why no daily wall-clock budget?" note in the [report's Layer 3](../../../../reports/agent-driven-prs-computation.md). The remaining runaway-compute safeguards are the concurrency cap of 1 + the `pgs.compute_enabled` kill-switch + the natural ~5-min-per-compute time bound.)

---

## Risks + Mitigations (carried over from the report; abbreviated)

- **Agent picks a poor-quality PGS** → memory rationale + INV-C001 v1.6 validation + the user's after-the-fact audit via `genomeclaw_pgs_get`. Reviewer's deferred validation study (Slice E.4) raises confidence further.
- **Agent computes a confident-looking PRS for a trait with no evidence base** → the **PRS-decline pattern** (Layer 5 in the report; INV-C001 v1.7) is the structural gate. Behavioural test 13 + rehydration test 14 verify enforcement.
- **Agent runs away with computes** → concurrency cap of 1 + kill-switch. Tests 2 + 3 verify enforcement. A daily wall-clock budget was considered + rejected as overengineering for the single-user PoC (see Open Questions).
- **`pgsc_calc` consumes the personal-host envelope** → sequential per-request compute model; failure surfaces as `failed` task status.
- **The compute step blocks reasoning** → async + polling shape; agent surfaces in-flight message and can resume on the next turn.
- **Provenance audit hard** → every layer carries the seven canonical provenance columns; `agent_choice_rationale` + `requested_for_question` columns on every row; memory-note cross-reference. Audit is reconstructible end-to-end.
- **Agent PGS-selection quality not benchmarked against expert curation** → deferred to Slice E.4 per the methodological review. Personal-use PoC scope accepts the risk; production deployment requires the validation study before launch.
- **User receives sensitive PRS result without pre-test counseling** → deferred to Slice E.4. Personal-use PoC scope accepts the risk; production deployment requires a pre-compute consent turn.
