# Phase 6: Findings + evidence + ~~lifestyle (curated_notes/)~~ + Cyrius CYP2D6 + PRS

**Status**: In Progress — Slices A + B shipped 2026-05-15. **Slice C (7 curated gene notes) superseded 2026-05-15** by the [agent-research-and-synthesis plan](../../agent-research-and-synthesis/spec.md) — lifestyle calibration moves to agent memory + reasoned research per `INV-C001` v1.6 + `INV-A001` + `INV-A002`. Phase 1 of the new plan does the surgical code cleanup (drops `gene_note:` + `topic:` evidence kinds + the `_resolve_gene_note` / `_resolve_topic` helpers + the 3 curated-notes test cases from Slice B; configures `web_search` off-by-default per `INV-P001`).
**Started**: 2026-05-15
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)
**Spec**: [spec.md § AC4 / AC5 / AC10 / AC13 / AC14](../spec.md), and decisions [Q1](../spec.md) / [Q6](../spec.md) / [Q8](../spec.md) / [Q9 revised v1.6](../spec.md).
**Companion plan**: [docs/plans/active/agent-research-and-synthesis/](../../agent-research-and-synthesis/spec.md) — handles the lifestyle-calibration half of Phase 6 (formerly Slice C; now its own plan).

---

## Objective

Stand up the **findings + evidence layer** that turns the per-variant data from Phase 4 into agent-consumable, evidence-bound, escalation-marked recommendations. Layer in two upstream callers from outside the host-toolkit envelope: **Cyrius** (CYP2D6 diplotype calling — per spec Q6) and **`pgsc_calc`** (polygenic risk scoring — per spec Q8). Author seven curated gene notes (per spec Q9) that anchor the lifestyle track. Land the four remaining v0 endpoints (`/v1/findings`, `/v1/findings/{id}`, `/v1/evidence/{ref}`, `/v1/pgs/{trait}`) and the 6th plugin tool (`genomeclaw_pgs`).

The phase is built around a single contract: **every assistant claim is bound to an evidence reference** (`INV-E001`), and **clinical-actionable findings carry a `clinical_escalation` marker** (`INV-C001`). The agent never invents medical advice; it composes natural-language framing on top of typed, traceable primitives.

## Scope Boundaries

- **In scope** (per [development-plan.md § Phase 6](../development-plan.md#phase-6-findings--evidence--lifestyle-support-curated_notes--cyrius-cyp2d6-outside-call--prs)):
  - Pydantic `Finding` model (`category`, `clinical_escalation`, `evidence_ref`, `evidence_quality`).
  - Pydantic `EvidenceRecord` model + resolver accepting:
    - variant-keyed kinds: `clinvar:rcv...`, `pubmed:pmid...`
    - curated-notes kinds: `gene_note:<gene>`, `topic:<topic>`
    - PGS Catalog kind: `pgs_catalog:<id>`
  - **Four new host-service endpoints**:
    - `GET /v1/findings?...` — paginated list with `category` / `genes` / `drugs` / `limit` filters
    - `GET /v1/findings/{id}` — single finding detail
    - `GET /v1/evidence/{ref}` — single evidence record
    - `GET /v1/pgs/{trait}` — single PRS score + interpretation band
  - **Sixth plugin tool**: `genomeclaw_pgs` registered via `registerTool` + `Type.Object({ trait: Type.String({ minLength: 1 }) })`.
  - **Cyrius `cyp2d6-call` subcommand** (host-side bioinformatics): runs Cyrius against the project owner's BAM/CRAM, writes `derived/<run-id>/cyp2d6_diplotype.json`. PharmCAT outside-call consumes this for the `*1/*4`-class PGx findings.
  - **`pgsc_calc pgs-compute` subcommand** (host-side, deliberate, opt-in PGS Catalog egress): fetches scoring weights, ancestry-normalises, writes a `pgs_scores` table.
  - **`reference/curated_notes/` directory** with seven gene notes (LCT, CYP1A2, ADORA2A, ALDH2, ADH1B, APOE, MTHFR) + `topics/hard-genes.md`. Each diff reviewed by the `privacy-safety-reviewer` agent before merge (per `INV-C001` v1.5).
  - **Policy preset extension**: `/v1/findings`, `/v1/findings/*`, `/v1/evidence/*`, `/v1/pgs/*` added to the GET allowlist in [packages/nemoclaw-plugin/policy-preset.yaml](../../../../packages/nemoclaw-plugin/policy-preset.yaml). Static INV-P002 test (already in [tests/invariants/test_invP002_policy_preset_shape.py](../../../../packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py)) extends to cover the new paths.
- **Out of scope** (deferred):
  - `/v1/report` endpoint — explicitly dropped per spec Q3; the agent composes report-shaped responses from the primitives.
  - PER3, CLOCK, ACTN3 lifestyle findings — dropped per spec Q9.
  - Bulk-mode PGS variant dumps — INV-P002 prohibits; agent gets the band, not the underlying genome-wide variant list.
  - Further bioinformatics tools beyond Cyrius + pgsc_calc.

## Invariants Enforced in This Phase

- **`INV-E001`** — every emitted `Finding` carries a non-empty `evidence_ref`. Schema rejects findings without one. Verified by `test_invE001_finding_rejects_without_evidence`.
- **`INV-C001` v1.5** — `clinical-actionable` findings carry `clinical_escalation` set; the `category` enum is enforced; PRS findings are `clinical-non-actionable` with a structurally-surfaced calibration warning. Snapshot tests over agent-rendered prose for Stories 2/4/9/10 enforce the curated-note framing.
- **`INV-P001`** — PGS Catalog fetch is a separate, deliberate user invocation (`genomeclaw pgs fetch-weights`); not background. Default-config tests assert no PGS Catalog calls happen during routine pipeline runs.
- **`INV-P002`** — bulk-class endpoints rejected with a typed error. PRS responses never include the raw scoring variant list — only the score + interpretation band + `pgs_catalog:<id>` evidence reference.

---

## Slice Plan

Phase 6 is large; ship it in 6 reviewable slices.

### Slice A — Finding + Evidence schemas + `/v1/findings` endpoints *(host-side; pure Python)*

Lands the typed primitives + the two finding endpoints. Synthetic findings in a new `findings.duckdb` table; no curated notes, no Cyrius, no PGS yet.

**TDD scope** (~6 tests):
- `test_finding_model_rejects_actionable_without_escalation` (`INV-C001`)
- `test_finding_model_rejects_without_evidence_ref` (`INV-E001`)
- `test_findings_list_returns_paginated_rows`
- `test_findings_by_id_returns_single_or_404`
- `test_findings_filter_by_category_and_genes`
- `test_invP002_findings_response_excludes_bulk_fields`

### Slice B — `/v1/evidence/{ref}` + curated-notes resolver *(host-side)*

Extends the store layer with an `EvidenceResolver` that dispatches on the `<kind>:<id>` prefix. Curated-notes resolution reads from `reference/curated_notes/`. Variant-keyed evidence resolves via the existing variant table (ClinVar / dbSNP fields).

**TDD scope** (~5 tests):
- `test_evidence_resolves_gene_note_from_curated_dir`
- `test_evidence_resolves_topic_from_curated_dir`
- `test_evidence_resolves_clinvar_from_variants_table`
- `test_evidence_returns_404_for_unknown_ref`
- `test_invP002_evidence_response_excludes_raw_variant_dump`

### ~~Slice C — Seven curated gene notes + `topics/hard-genes.md`~~ **SUPERSEDED 2026-05-15**

This slice is **retired**. It planned 7 pre-authored Markdown files under `reference/curated_notes/` with the project owner's calibrated stance per gene. The pattern was reviewed and replaced by the **agent research-and-synthesis pattern** which leverages OpenClaw's memory + web_search built-ins + extended-reasoning effort for the synthesis step. See:

- **Plan**: [docs/plans/active/agent-research-and-synthesis/spec.md](../../agent-research-and-synthesis/spec.md)
- **Invariant changes**: [INVARIANTS.md v1.8](../../../reference/INVARIANTS.md) — `INV-C001` v1.6 (curated_notes retired) + `INV-A001` (memory provenance) + `INV-A002` (synthesis reasoning floor) + `INV-P001` (web_search as 3rd named egress, off by default).
- **Code cleanup**: Phase 1 of the new plan drops the `gene_note:` + `topic:` evidence kinds from `_SUPPORTED_EVIDENCE_KINDS`, deletes `_resolve_gene_note` + `_resolve_topic`, and removes the 4 curated-notes test cases from `test_service_evidence.py` (which Slice B shipped today and which Phase 1 will now retire).
- **Spec changes**: `AC5`, `AC10`, Q9 in [spec.md](../spec.md) — all revised 2026-05-15.

**Why retired** *(2026-05-15)*: the v1.5 curated-notes pattern (a) didn't leverage the frontier model's training knowledge, (b) didn't scale beyond the curator's pre-defined topic set, (c) didn't self-update with new literature. The research-and-synthesis pattern composes calibrated answers from (training knowledge + current web sources + memory) at the maximum reasoning level for any health-interpretation turn — handling the long-tail of gene questions through the same path that handles the canonical ones.

### Slice D — Cyrius `cyp2d6-call` subcommand *(bioinformatics; needs BAM/CRAM)*

Adds `genomeclaw pipeline cyp2d6-call --bam <path>` that wraps Cyrius. Writes `derived/<run-id>/cyp2d6_diplotype.json`. Extends `annotate` to feed the diplotype into PharmCAT's outside-call interface for the `*1/*4`-class PGx findings.

**TDD scope** (~4 tests): wrapper unit tests + 1 INV-R001 provenance test + 1 `needs_bio` integration test against a fixture BAM (deferred to first real run).

### Slice E — agent-driven PRS *(structurally pivoted 2026-05-17; per Q8 v1.6)*

**Pivot note**: the v1.5 design — a `pgs-compute --traits cad,t2d,prostate` one-shot CLI + a single `genomeclaw_pgs(trait)` lookup tool + a single `/v1/pgs/{trait}` endpoint — is **retired** per [Q8 v1.6](../spec.md) + [agent-driven PRS report](../../../reports/agent-driven-prs-computation.md). The static-panel framing recapitulated the v1.5 curated_notes mistake in PRS form. The replacement is **agent-driven, host-computed, memory-cached** PRS:
- **Four host tools** (plugin count 5→9): `genomeclaw_pgs_list`, `genomeclaw_pgs_get`, `genomeclaw_pgs_compute` (async; agent-triggered), `genomeclaw_pgs_compute_status` (polling).
- **Four host endpoints**: `/v1/pgs/computed`, `/v1/pgs/computed/{pgs_id}`, `POST /v1/pgs/compute`, `/v1/pgs/compute/{task_id}`.
- **PGS Catalog ID is the canonical key**, not curator-named trait. `pgs_scores` table keyed by `pgs_id`; carries `agent_choice_rationale` + `requested_for_question` columns per `INV-A003`.
- **No pre-curated trait panel** in `reference/pgs_panel/<trait>.yaml`. The agent picks per question; the "panel" is what the agent has computed for this user.
- **PRS-decline pattern** in the agent system prompt per `INV-C001` v1.7 — four criteria, two-named-reasons rule, peer to the existing hard-genes decline.
- **Async compute** orchestration: 1-in-flight concurrency cap + kill-switch (`genomeclaw config set pgs.compute_enabled false`) + INV-P001 install-time consent (no per-compute approval). A daily wall-clock budget was considered + rejected as overengineering for the single-user PoC.

**Detailed plan**: the v1 plan at [phase-6-slice-e.md](phase-6-slice-e.md) is **Status: Superseded**. A v2 slice plan at [phase-6-slice-e-v2.md](phase-6-slice-e-v2.md) replaces it, scoped against the agent-driven design above; sub-slices E.1 (schema + 4 tools + 4 endpoints), E.2 (`pgsc_calc` wrapper + provenance), E.3 (async orchestration + concurrency cap + kill-switch + decline pattern + system-prompt update). Slice E.4 (validation study + pre-compute consent) is deferred per the methodological-review pass recorded in the report.

**Bootstrap dependencies**: Q-E1' (accept Q8 v1.6 rewrite) — answered yes 2026-05-17 by the propagation of canonical-doc updates. Q-E2' (daily wall-clock budget) — removed 2026-05-17 (the budget mechanism was rejected as overengineering for the single-user PoC). Q-E3' (supersession schema) + Q-E4' (PGS Catalog REST API investigation) remain open; tracked under the v2 slice plan.

### Slice F — Story 2/4/9/10 agent-prose snapshot tests *(integration; needs live LLM)*

Final integration sweep: run the agent against fixture conversations covering Stories 2, 4, 9, 10 (clinical-actionable, CYP2D6 PGx, lifestyle, PRS). Snapshot the agent's natural-language framing; assert structural correctness:

- `clinical_escalation` surfaces where applicable
- Evidence references cited verbatim
- Curated-note framing tracked (no over-claim, no over-defer)
- PER3/CLOCK/ACTN3 gracefully declined
- **PRS-decline pattern fires** *(v1.6, per `INV-C001` v1.7)*: an "asthma PRS" / "creativity PRS" / similar immature-trait question declines with two named reasons + writes a decline-shaped memory note. The agent does NOT invoke `genomeclaw_pgs_compute` for the immature trait.

**Status of Stories 4 / 9 / 10 / supersession**: already shipped via the [agent-research-and-synthesis companion plan](../../../completed/agent-research-and-synthesis/) (4 `live_llm` tests against `genomeclaw/sandbox:ars-phase-2d`). **Story 2** ("what do you know about me?") remains as the only outstanding live snapshot. **Story 10** can be re-staged after Slice E v2 lands a real (agent-computed) PRS row in `pgs_scores`; the current Story 10 live test runs against a synthetic `clinical-non-actionable` finding under the agent-research-and-synthesis plan's fixture set.

Uses the same OpenAI gpt-5.5 setup from the Phase 5 live sweep.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/finding.py` | CREATE | Pydantic `Finding` + `FindingsListResponse` |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/evidence.py` | CREATE | Pydantic `EvidenceRecord` + variants |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/pgs.py` | CREATE | Pydantic `PgsResponse` |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY | Add `query_findings`, `query_finding_by_id`, `EvidenceResolver`, `query_pgs` |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Add 4 new routes |
| `packages/toolkit/src/genomeclaw_toolkit/prep/store.py` | MODIFY | Add `findings` + `pgs_scores` tables to schema |
| `packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py` | CREATE | Cyrius wrapper for the `cyp2d6-call` subcommand |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | CREATE | pgsc_calc wrapper for the `pgs-compute` subcommand |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | Add `cyp2d6-call` + `pgs-compute` subcommands |
| `packages/toolkit/tests/integration/test_service_findings.py` | CREATE | Slice A endpoint tests |
| `packages/toolkit/tests/integration/test_service_evidence.py` | CREATE | Slice B endpoint tests |
| `packages/toolkit/tests/integration/test_service_pgs.py` | CREATE | Slice E endpoint tests |
| `packages/toolkit/tests/integration/test_finding_model.py` | CREATE | Slice A model tests (INV-E001, INV-C001) |
| `packages/toolkit/tests/integration/test_cyrius_wrapper.py` | CREATE | Slice D wrapper tests |
| `packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py` | CREATE | Slice E wrapper tests |
| `packages/toolkit/tests/integration/test_invE001_findings_have_evidence.py` | CREATE | Slice A INV-E001 enforcement |
| `packages/toolkit/tests/integration/test_invC001_clinical_escalation.py` | CREATE | Slice A/F INV-C001 enforcement |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY | Register 6th tool `genomeclaw_pgs` |
| `packages/nemoclaw-plugin/tests/index.test.ts` | MODIFY | Extend vitest to cover the 6-tool registration |
| `packages/nemoclaw-plugin/policy-preset.yaml` | MODIFY | Already covers `/v1/findings/*`, `/v1/evidence/*`; extend with `/v1/pgs/*` |
| ~~`reference/curated_notes/*.md`~~ | ~~CREATE~~ | **Retired 2026-05-15** — see Slice C note above; superseded by [agent-research-and-synthesis plan](../../agent-research-and-synthesis/spec.md). |

---

## Verification

Per slice:

```bash
# Slice A/B/E (host-side, fast)
cd packages/toolkit
uv run pytest tests/integration/test_service_findings.py tests/integration/test_service_evidence.py tests/integration/test_service_pgs.py -v
uv run pytest tests/integration/test_finding_model.py tests/integration/test_invE001_findings_have_evidence.py tests/integration/test_invC001_clinical_escalation.py -v

# Slice D (Cyrius, needs_bio)
GENOMECLAW_HAS_BIO=1 uv run pytest tests/integration/test_cyrius_wrapper.py -v

# Slice F (live agent, needs OPENAI_API_KEY)
# Reuses the Slice E live-sweep harness: launch host service, run sandbox container,
# invoke agent with each Story's fixture conversation, snapshot the prose, assert.
```

---

## Completion Criteria

- [ ] All 6 slices' test cases pass
- [ ] Static checks pass (ruff, format, mypy for new modules; vitest + typecheck for plugin)
- [ ] Each enforced `INV-xxx` is verified by at least one test in this phase (`INV-E001`, `INV-C001`, `INV-P001`, `INV-P002`)
- [ ] All seven curated-notes files exist + passed `privacy-safety-reviewer` review
- [ ] CYP2D6 `*1/*4`-class PGx finding renders with `clinical_escalation` set (using Cyrius output against the project owner's BAM)
- [ ] CAD PRS finding renders with `clinical-non-actionable` category + calibration warning surfaced
- [ ] Snapshot tests pass for Stories 2/4/9/10 against gpt-5.5
- [ ] Sixth plugin tool `genomeclaw_pgs` registers via `registerTool`
- [ ] Policy preset extended; `test_invP002_policy_preset_path_set_matches_documented_surface` covers new paths
- [ ] [work-notes.md](../work-notes.md) updated per slice
- [ ] [phases/phase-7.md](phase-7.md) authored before Phase 6 closes (end-to-end MVP demo + invariant sweep)

### Open Questions for Resolution During Phase 6

- **Cyrius execution model**: native binary vs. Docker image? Cyrius isn't in the existing `genomeclaw/toolkit` image; should it land there or run via a separate `cyrius` image? Probably the former for v0 (one image; pinned versions in `manifest.tools`).
- **PGS trait → PGS Catalog ID mapping**: who curates the mapping? Spec Q8 mentions a panel of conditions; the mapping table likely lives at `reference/pgs_panel/<trait>.yaml`. Decision needed before Slice E.
- **Finding deduplication**: a variant can produce both an ACMG SF clinical-actionable finding AND a lifestyle finding. Are these two findings or one finding with multiple categories? Lean towards: two findings with cross-references in `related_finding_ids: [...]` for clarity.
- **Story-snapshot test brittleness**: gpt-5.5 prose varies turn-to-turn. Snapshot tests assert *structural* correctness (escalation marker present, evidence ref cited, no forbidden phrases), not exact text. Worth a small lint-style rubric file documenting "what passes".
