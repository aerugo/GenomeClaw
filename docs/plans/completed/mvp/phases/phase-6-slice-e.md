# Phase 6 Slice E: pgsc_calc PRS + `/v1/pgs/{trait}` + `genomeclaw_pgs` tool

**Status**: **SUPERSEDED 2026-05-17** by the agent-driven PRS architecture at [docs/reports/agent-driven-prs-computation.md](../../../../reports/agent-driven-prs-computation.md) (per [Q8 v1.6 amendment](../spec.md#q8--prs-via-pgsc_calc--fixed-three-trait-panel--genomeclaw_pgs-6th-tool--agent-driven-four-tool-surface-no-pre-curated-panel)). The static-panel design this file describes — three fixed traits (CAD / T2D / breast or prostate), one `genomeclaw_pgs(trait)` lookup tool, one `/v1/pgs/{trait}` endpoint, a `reference/pgs_panel/<trait>.yaml` mapping curated by the project owner — was identified during pre-implementation review as recapitulating the v1.5 curated_notes mistake in PRS form. The v2 slice plan replaces this one; sub-slices E.1 (schema + 4 tools + 4 endpoints) / E.2 (pgsc_calc wrapper + provenance) / E.3 (async orchestration + decline pattern + system-prompt update) follow the structure laid out in the report.

**This file is kept on disk** as the historical record of the rejected approach + the open questions that surfaced during its drafting. Future authors of the v2 plan can read here for context on why the structural pivot was needed.

**Started**: 2026-05-15 (drafted)
**Completed**: N/A — superseded before RED tests landed
**Parent Phase**: [phase-6.md](phase-6.md) (Slice E expansion)
**Spec**: [MVP spec Q8 v1.6](../spec.md#q8--prs-via-pgsc_calc--fixed-three-trait-panel--genomeclaw_pgs-6th-tool--agent-driven-four-tool-surface-no-pre-curated-panel) (AC9 v1.6)
**Supersession reason**: see [docs/reports/agent-driven-prs-computation.md § Problem](../../../../reports/agent-driven-prs-computation.md) — the static-panel framing pre-bakes editorial decisions (which traits matter, which PGS Catalog scorefile is best for each, what to call them) that the agent + long-horizon reasoning can make better per-question. The v1.5 curated_notes plan made the parallel mistake for lifestyle calibration; this would have made it for PRS.

---

## Objective

Stand up the polygenic risk score (PRS) layer: a new `pgs_scores` derived-store table; a `genomeclaw pipeline pgs-compute` subcommand wrapping `pgsc_calc` (PGS Catalog Calculator, Nextflow); a new `/v1/pgs/{trait}` host-service endpoint; the 6th plugin tool `genomeclaw_pgs`. Three initial traits per MVP spec Q8: **CAD, T2D, and one user-choice trait (breast or prostate)**. All scores **ancestry-normalized** via `pgsc_calc --run_ancestry` (continuous-ancestry against 1000G + HGDP).

After Slice E, the Story-10 user-stories.md exchange (`my dad had a heart attack at 58. is there anything in my genome about cad risk?`) is fully data-backed: the agent's existing Story-10 live snapshot (shipped via the agent-research-and-synthesis plan against a *synthetic* `clinical-non-actionable` finding) becomes able to run against a *real* PRS computed from the project owner's VCF.

## Scope Boundaries

- **In scope** (per [phase-6.md § Slice E](phase-6.md#slice-e--pgsc_calc-pgs-compute--v1pgstrait--genomeclaw_pgs-tool) + spec Q8):
  - **Schema additions** (host-side):
    - `pgs_scores` table in `variants.duckdb`. Columns: `trait`, `percentile_in_user_ancestry`, `raw_score`, `source_pgs_id`, `study_population`, `calibration_warning`, plus the 7 canonical provenance columns per `INV-R001`.
    - `PgsResponse` Pydantic model in [schemas/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py).
    - `PgsErrorResponse` for 404 / 503 paths.
  - **`pgsc_calc` wrapper** at [prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py):
    - `compute_pgs(*, vcf, traits, derived_root, reference_root) -> list[PgsRow]` invokes Nextflow + `pgsc_calc` per trait, parses the score table, applies continuous-ancestry calibration, returns typed rows.
    - **PGS Catalog scoring-weight fetch** is host-side, deliberate, opt-in per `INV-P001`. Cache under `<reference_root>/pgs_catalog/PGS<id>/`.
  - **`pgs-compute` CLI subcommand** at [`_cli/commands/pipeline.py`](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py):
    - `genomeclaw pipeline pgs-compute --vcf <path> --traits cad,t2d,prostate --reference-root <X>` runs the wrapper + writes results into `pgs_scores`.
    - Output: `{run_id, traits, rows: int, duration_s, calibration_warnings}`.
  - **Host service endpoint** at [service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) + [service/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py):
    - `GET /v1/pgs/{trait}` returns `PgsResponse` (or 404 for unknown trait).
    - `query_pgs(*, run_dir, trait) -> dict[str, Any] | None` resolver function.
  - **6th plugin tool** at [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts):
    - `genomeclaw_pgs` registered via `registerTool` with `Type.Object({ trait: Type.String({ minLength: 1 }) })`.
    - `output_class: "summary"` per `INV-P002`; never returns the raw PGS variant list (which would leak the user's genotype across the boundary at scale).
  - **Policy preset** at [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml): add `/v1/pgs/*` to the allowed path list.
  - **Plugin description audit**: while editing the plugin to add `genomeclaw_pgs`, remove the stale `gene_note:CYP1A2 / topic:hard-genes` examples from `genomeclaw_evidence`'s description (retired in the agent-research-and-synthesis plan, but the description still names them).

- **Out of scope** (this slice):
  - **PharmCAT outside-call integration** — Slice D (Cyrius CYP2D6) couples here; Slice E doesn't touch it.
  - **Bundling pgsc_calc in the host toolkit image** — pgsc_calc is heavy (Nextflow + per-workflow Docker). Image-level integration tests stay `needs_bio` + skipped on the host venv; real-data smoke uses the project owner's already-installed pgsc_calc or runs against the existing toolkit image after a manual `pgs-compute` invocation.
  - **Continuous-ancestry reference data fetch** — assume `<reference_root>/ancestry/{1000g,hgdp}/` is staged by the existing `refs fetch` flow before `pgs-compute` runs. If it's missing, fail cleanly with a one-line install hint; don't auto-fetch as part of `pgs-compute`.
  - **PRS-finding row in `findings` table** — Story 10 needs the PRS to surface via `genomeclaw_findings`. Decision: yes, but the row gets materialised by a new `pgs-compute` post-step that INSERTs a `{category=clinical-non-actionable, evidence_ref=pgs_catalog:PGS<id>}` finding row pointing at the `pgs_scores` row. Folds into this slice rather than a follow-up; keeps the contract tight.
  - **Live `live_llm` Story 2 / Story 10 re-runs** — Story 10's existing live snapshot uses a synthetic finding; after Slice E it can be re-staged against a real `pgs-compute` run. That re-stage is a slice-F task, not blocking E.

## Invariants Enforced in This Slice

- **`INV-D001`** — raw genomic source files stay host-side. `pgsc_calc` reads the user's VCF host-side; only PGS scoring weights cross the network (inbound). Verified by inspection of the wrapper's egress: it makes HTTPS GETs to `https://www.pgscatalog.org/score/PGS{id}/get/` and nothing else.
- **`INV-R001`** — every `pgs_scores` row carries the 7 provenance columns. Provenance test enumerates a sample row + asserts the column set.
- **`INV-E001`** — every PRS-derived finding row in `findings` carries `evidence_ref=pgs_catalog:PGS<id>` (non-empty + variant-keyed). Existing `EvidenceKind` Literal already includes `pgs_catalog`.
- **`INV-C001` v1.6** — PRS findings carry `category: clinical-non-actionable` and **no** `clinical_escalation` marker (per spec Q8 + the Pydantic model's `_enforce_inv_c001` validator). The `calibration_warning` string is the user-facing nuance, not an escalation.
- **`INV-P001` v1.7** — PGS Catalog egress is a deliberate, host-side, opt-in operation. The `pgs-compute` CLI subcommand is the explicit user trigger; the fetch is rate-limited + caches into the reference-root tree. The sandbox container's policy preset stays unchanged: no new egress destination opens for the agent.
- **`INV-P002`** — `genomeclaw_pgs` is `output_class: "summary"`; the response carries the `percentile_in_user_ancestry` + `raw_score` + a few framing fields. The raw PGS variant list (potentially thousands of rows for the user) never leaves the host.

---

## TDD Steps

Slice E breaks into four sub-steps that ship in sequence. Each sub-step is a single TDD cycle (RED → GREEN → REFACTOR); each is independently verifiable.

### Step E.1 — Schema + `PgsResponse` model

**RED tests** (host-side, fast):

1. `test_pgs_response_model_pinned_shape` — `PgsResponse` carries exactly the documented fields; `extra="forbid"`.
2. `test_pgs_scores_table_in_create_store` — `create_store()` emits the new table with the 6 domain columns + 7 provenance columns; double-create is idempotent.
3. `test_pgs_finding_category_pinned_to_non_actionable` — constructing a `Finding(category="clinical-non-actionable", evidence_ref="pgs_catalog:PGS003725", ...)` succeeds; constructing the same with `category="clinical-actionable"` AND no escalation marker raises (existing `_enforce_inv_c001` covers; verify via parametrize).

**GREEN**:
- Author [schemas/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py) — `PgsResponse` + `PgsErrorResponse`.
- Extend [prep/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/store.py) with the `pgs_scores` DDL block (mirror the `findings` DDL pattern at line 172).
- No model changes needed to `Finding` — its `EvidenceKind` already accepts `pgs_catalog`.

**Refactor**: tighten docstrings; cite spec Q8 inline.

### Step E.2 — pgsc_calc wrapper + `pgs-compute` subcommand

**RED tests** (host-side; `pgsc_calc` invocations mocked via `subprocess.run` patching):

4. `test_compute_pgs_invokes_pgsc_calc_with_run_ancestry` — wrapper calls `pgsc_calc` with `--run_ancestry` AND the right per-trait scorefile (`PGS<id>`). Asserts on the captured argv.
5. `test_compute_pgs_parses_score_table` — wrapper consumes a fixture `<work_dir>/score/aggregated_scores.txt` + `<work_dir>/ancestry/aggregated_scores_norm.txt` + returns rows with the right percentiles + calibration warnings.
6. `test_compute_pgs_skips_when_reference_ancestry_data_absent` — when `<reference_root>/ancestry/{1000g,hgdp}/` is missing, the wrapper raises a clean `PgsReferenceMissingError` with the install hint, not a Nextflow stack trace.

**GREEN**:
- Author [prep/pgs.py](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py): `compute_pgs(...)` + `PgsRow` dataclass + `PgsReferenceMissingError`. Mirror the bcftools-wrapper provenance pattern (return a `(rows, ProvenanceTag)` tuple so the subcommand can stamp).
- Add CLI subcommand `pipeline pgs-compute` to [_cli/commands/pipeline.py](../../../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py) following the existing `materialize` / `annotate` orchestrator pattern. JSON-mode output for the rich-cli envelope; rich-mode summary for human use.

**Refactor**: extract the score-table parser into a private helper if both .txt files share parsing logic.

### Step E.3 — `/v1/pgs/{trait}` endpoint + `genomeclaw_pgs` plugin tool

**RED tests**:

7. `test_pgs_endpoint_returns_row_for_known_trait` — stage a `pgs_scores` table row for `cad`; `GET /v1/pgs/cad` returns 200 + the `PgsResponse` shape; field values match.
8. `test_pgs_endpoint_returns_404_for_unknown_trait` — `GET /v1/pgs/zzz_unknown_trait` returns 404 + the typed error body.
9. `test_pgs_endpoint_only_returns_summary_fields_inv_p002` — assert the response body has exactly the 5 documented fields; no raw variant list ever surfaces.

**Plugin-side RED** (vitest in [packages/nemoclaw-plugin/tests/index.test.ts](../../../../packages/nemoclaw-plugin/tests/index.test.ts)):

10. `test_genomeclaw_pgs_tool_registered` — after `register(api)`, the api's tool registry holds 6 entries including `genomeclaw_pgs`; the registered TypeBox schema for `genomeclaw_pgs` accepts `{ trait: "cad" }` + rejects `{ trait: "" }`.
11. `test_genomeclaw_pgs_routes_to_pgs_endpoint` — invoking the registered tool with `{ trait: "cad" }` calls `safeCall(host, "/v1/pgs/cad")`.

**GREEN**:
- Add `query_pgs(*, run_dir, trait) -> dict[str, Any] | None` to [service/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py).
- Add the route handler in [service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py) (mirror `/v1/evidence/{ref}`'s pattern: query store → return `PgsResponse` or 404).
- Register the 6th `genomeclaw_pgs` tool in [packages/nemoclaw-plugin/src/index.ts](../../../../packages/nemoclaw-plugin/src/index.ts); update the registration-summary log line to say "(6 tools)".
- Update [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml) to allowlist `/v1/pgs/*`.

**Refactor**: while in `index.ts`, drop the stale `gene_note:CYP1A2 / topic:hard-genes` examples from the `genomeclaw_evidence` tool description (retired in the agent-research-and-synthesis plan).

### Step E.4 — `INV-P001` + `INV-P002` deployment gates

**RED tests** (`needs_sandbox`-gated):

12. `test_invP002_pgs_response_shape_pinned` — inside a sandbox container, exercise the `genomeclaw_pgs` tool against a fixture run + assert the JSON payload has exactly the 5 documented fields.
13. `test_invP001_pgsc_calc_fetch_is_opt_in` — host-side test that the sandbox image's policy preset does NOT include `pgscatalog.org` in any allowlist (egress from the *sandbox* to PGS Catalog is forbidden; the fetch happens host-side via `genomeclaw pipeline pgs-compute`).

**GREEN**: these are pure assertion tests over existing artifacts; no implementation needed beyond the earlier steps.

**Refactor**: nothing.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` | CREATE | `PgsResponse`, `PgsErrorResponse` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | CREATE | `compute_pgs(...)` + `PgsRow` + `PgsReferenceMissingError` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | MODIFY | Add `_PGS_SCORES_DDL`; extend `create_store()` |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY | Add `query_pgs(...)` |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Add `/v1/pgs/{trait}` route |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | Add `pgs-compute` subcommand |
| `packages/toolkit/tests/integration/test_pgs_model.py` | CREATE | Step E.1 model tests |
| `packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py` | CREATE | Step E.2 wrapper tests |
| `packages/toolkit/tests/integration/test_service_pgs.py` | CREATE | Step E.3 endpoint tests |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY | Register `genomeclaw_pgs`; drop stale `gene_note:` example from `genomeclaw_evidence` description |
| `packages/nemoclaw-plugin/tests/index.test.ts` | MODIFY | Extend vitest with the 2 new tool tests |
| `packages/nemoclaw-plugin/policy-preset.yaml` | MODIFY | Allowlist `/v1/pgs/*` |
| `packages/toolkit/tests/invariants/test_invP002_pgs_response_shape.py` | CREATE | `needs_sandbox` gate |
| `packages/toolkit/tests/invariants/test_invP001_pgsc_calc_opt_in.py` | CREATE | Step E.4 INV-P001 gate |

---

## Verification

```bash
cd packages/toolkit

# Host-side (no sandbox image, no OPENAI_API_KEY)
uv run pytest \
  tests/integration/test_pgs_model.py \
  tests/integration/test_pgsc_calc_wrapper.py \
  tests/integration/test_service_pgs.py \
  -v
uv run ruff check src/genomeclaw_toolkit/schemas/pgs.py \
  src/genomeclaw_toolkit/prep/pgs.py \
  src/genomeclaw_toolkit/service/store.py \
  src/genomeclaw_toolkit/service/app.py \
  src/genomeclaw_toolkit/_cli/commands/pipeline.py

# Plugin side
cd ../nemoclaw-plugin
npm test

# Rebuild sandbox image (slice E doesn't add bio binaries; only a new endpoint
# allowlist + a new plugin tool registration). Tag it `ars-phase-2e` or
# `phase-6e` per the current naming convention.
docker build -f packages/nemoclaw-plugin/sandbox/Dockerfile \
  -t genomeclaw/sandbox:phase-6e packages/nemoclaw-plugin
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-6e \
  uv run pytest -m needs_sandbox -v

# Real-data smoke (manual, against the project owner's Nebula VCF):
# 1. Stage the ancestry reference data (one-time):
#    genomeclaw refs fetch --source pgs_catalog_ancestry --reference-root $REFS
# 2. Compute PRS for the three traits:
#    genomeclaw pipeline pgs-compute --vcf $VCF \
#      --traits cad,t2d,prostate --reference-root $REFS --json
# 3. Inspect the pgs_scores table + the new clinical-non-actionable rows in findings.
# 4. (Optional) re-run the Story-10 live_llm test against the real-data run instead
#    of the synthetic STORY10_CAD_PRS_FINDINGS fixture (slice F).
```

---

## Completion Criteria

Slice E is complete when:

- [ ] 11 host-side tests pass: `test_pgs_model.py` (3) + `test_pgsc_calc_wrapper.py` (3) + `test_service_pgs.py` (3) + `test_invP001_pgsc_calc_opt_in.py` (1) + `test_invP002_pgs_response_shape.py` (1, `needs_sandbox`).
- [ ] Plugin vitest passes including the 2 new `genomeclaw_pgs` tests.
- [ ] Full host toolkit suite + `needs_sandbox` sweep stay green on the new image.
- [ ] Real-data smoke (manual) produces non-empty `pgs_scores` table rows for all 3 traits + a matching set of `clinical-non-actionable` findings rows pointing at the PGS Catalog scorefile IDs.
- [ ] `genomeclaw pipeline pgs-compute --help` documents the new subcommand; `--json` envelope renders cleanly.
- [ ] Phase 6 row in [development-plan.md](../development-plan.md) progress-tracking table marks Slice E complete with a one-line outcome.

---

## Open Questions (pre-implementation)

- **Q-E1**: which third trait? Spec Q8 says "breast cancer or prostate cancer (project owner's choice; PRS313/BCAC for breast, PRS269 for prostate)". Pick one before authoring the trait → PGS-ID mapping table at [reference/pgs_panel/<trait>.yaml](../../../../reference/pgs_panel/). **Decision needed before Step E.2**.
- **Q-E2**: where does the trait → PGS-ID mapping live? Two options: (a) static YAML under `reference/pgs_panel/<trait>.yaml`, fetched alongside the scoring weights; (b) inline `_PGS_PANEL: dict[str, str]` constant in `prep/pgs.py`. The YAML form is more honest about it being curator-edited; the constant is simpler. **Lean (a)** — matches the `release_sets/default.toml` pattern under `prep/`.
- **Q-E3**: how does `pgs-compute` decide which subset of the user's VCF to feed `pgsc_calc`? Two patterns: (a) feed the full normalised VCF; `pgsc_calc` extracts the variants it needs from the scorefile. (b) Pre-filter to a per-trait subset; faster but adds custom logic. **Lean (a)** — `pgsc_calc` is designed for this; pre-filtering risks subtle variant-coordinate-matching bugs.
- **Q-E4**: does the new `pgs_scores → findings` insert run automatically as a post-step of `pgs-compute`, or as a separate `pipeline materialize-findings` step? **Lean post-step** — keeps the user's mental model "I ran `pgs-compute`; my findings have PRS rows now" instead of "run two commands". The materialize step is non-destructive (DELETE + INSERT for PRS-class rows only).

Sign off on Q-E1 + Q-E2 + Q-E3 + Q-E4 before Step E.1's RED tests are authored.
