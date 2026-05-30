# Work Notes: CYP2D6 No-Call as Indeterminate Finding

**Plan status**: Draft — spec and development-plan written; phase-1 drafted;
no implementation started.

---

## Session log

### 2026-05-25 — Initial planning

**Context reviewed**:
- `/packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py` (full file)
- `/packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py` (full file)
- `/packages/toolkit/src/genomeclaw_toolkit/prep/store.py` (full file)
- `/packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py`
  lines 1186–1461 (pharmcat + cyp2d6-call commands)
- `/packages/toolkit/src/genomeclaw_toolkit/schemas/finding.py` (full file)
- `/packages/toolkit/tests/unit/test_cyrius_wrapper.py` (partial)
- `docs/plans/active/bioreview-followup-meta/meta-plan.md` (full file)
- `docs/reference/INVARIANTS.md` (header + INV-D/E/P/R/C sections)

**Applicable invariants reaffirmed**:
- INV-C001 v1.7 — `clinical-actionable` requires `clinical_escalation`;
  the model validator enforces this at construction time.
- INV-E001 — `evidence_ref` must be non-empty; the `Finding` model enforces
  this. The sentinel file is the evidence.
- INV-R001 — seven provenance columns on both the sentinel JSON and the
  DB row.
- INV-D001 — no mutation of source BAM/CRAM.
- INV-P001 — `evidence_ref` is a local path; no data leaves the device.

**Key design decisions taken**:
1. `call_cyp2d6` return type changes from `CyriusDiplotypeRow` to
   `CyriusDiplotypeRow | None`. The `CyriusNoGenotypeError` for the
   empty-genotype case is caught inside `call_cyp2d6`; all other
   error paths still raise. Rationale: an uncallable locus is an expected
   outcome, not a caller error.
2. `cyp2d6_status` field added to both envelope files (
   `'called'` / `'no_call'`) for machine-readable distinction.
3. Finding ID is deterministic: `fnd-cyp2d6-no-call-<bam_sha256[:8]>`.
4. `evidence_quality = 'low'` for the indeterminate finding (not a
   curated database entry).
5. `pharmcat` skip is via auto-detection of `cyp2d6_no_call_envelope.json`
   in `run_dir`, not via an explicit new CLI flag.

**Open questions logged in spec.md**:
- Q1: re-run overwrite behavior (preference: overwrite silently)
- Q2: finding ID stability (preference: deterministic)
- Q3: pharmcat skip verbosity (preference: auto-detect + rich warning)
- Q4: wording alignment with meta-plan exit gate

**Files created this session**:
- `spec.md`
- `development-plan.md`
- `work-notes.md` (this file)
- `phases/phase-1.md`

**Next steps**:
- Obtain spec approval (open questions Q1–Q4 resolved with project owner).
- Begin Phase 1 RED step: write the failing tests enumerated in
  `phases/phase-1.md` step 1.1.
- Run the existing Cyrius + PharmCAT tests to confirm baseline state before
  any code changes.

---

### 2026-05-25 — Phase 1 RED → GREEN → REFACTOR (complete)

**Open questions Q1–Q4 resolution** (recorded in spec.md):
- Q1 → overwrite silently (matches `cyp2d6_diplotype.json` re-run behaviour). Implemented as `DELETE FROM findings WHERE id = ?` before `INSERT` in `_insert_cyp2d6_indeterminate_finding`.
- Q2 → deterministic id `fnd-cyp2d6-no-call-<bam_sha256[:8]>`.
- Q3 → auto-detect + rich warning. Implemented in `pipeline_pharmcat` before the `run_pharmcat` call.
- Q4 → aligned with meta-plan exit gate item 3.

**Test results**:

RED (before any implementation):
```text
8 failed, 3 passed in 0.46s
```
The 3 incidentally-passing tests were the schema-only `Finding` validation tests (test_cyp2d6_no_call_finding_validates_pydantic, test_invC001_cyp2d6_indeterminate_finding_has_escalation, test_invE001_cyp2d6_indeterminate_finding_has_evidence_ref) — the `Finding` model already accepts the indeterminate shape, so they pass without any code change. This is the documented "schema-only" group from phase-1.md.

GREEN (after the cyrius.py + pipeline.py implementation):
```text
24 passed in 0.60s
```
All 10 new tests pass; the 11 existing test_cyrius_wrapper.py tests pass; the 4 existing test_cli_pipeline_pharmcat.py tests pass (regression).

Full toolkit suite:
```text
4 failed, 930 passed, 136 skipped, 1 warning in 17.71s
```
The 4 failures are the same pre-existing failures documented in the Plan 1 work-notes (`test_shim_host_service_publishes_port_and_appends_host_0_0_0_0`, `test_invP002_policy_preset_targets_host_openshell_internal`, two `test_invP001_plugin_default_egress` tests). All 11 net-new tests (10 added in Phase 1 + the `cyp2d6_status='called'` regression in test_cyrius_wrapper.py) pass.

Type + lint:
- `mypy src/genomeclaw_toolkit/prep/cyrius.py src/genomeclaw_toolkit/_cli/commands/pipeline.py`: no errors.
- `ruff check --fix` resolved one BLE001 (broad-except in the test file — narrowed to `pydantic.ValidationError`) plus one import-order autofix.

**Files modified**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/cyrius.py`:
  - `call_cyp2d6` return type widened from `CyriusDiplotypeRow` to `CyriusDiplotypeRow | None`.
  - Empty-Genotype `CyriusNoGenotypeError` is caught internally; the wrapper writes `cyp2d6_no_call_envelope.json` via the new `_write_no_call_envelope` and returns `None`. The multi-sample-manifest path of `CyriusNoGenotypeError` is preserved as a re-raise (programmer error, not a data outcome).
  - Extracted `_build_provenance_block(bam, params)` shared by both envelope writers (rule-of-three: now used by two envelopes).
  - `_write_diplotype_envelope` envelope dict now includes `"cyp2d6_status": "called"`.
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py`:
  - New module-level constants `_CYP2D6_NO_CALL_SUMMARY` (the binding "do not interpret as Normal Metabolizer" prose) and `_CYP2D6_NO_CALL_DRUGS` (8 CPIC Strong/Moderate substrates).
  - New `_insert_cyp2d6_indeterminate_finding` helper: inserts the indeterminate `findings` row with deterministic id, `category='clinical-actionable'`, `clinical_escalation='confirm_with_provider'`, `evidence_ref='cyrius_no_call:<sentinel>'`, `evidence_quality='low'`, the eight CPIC substrates, and the seven INV-R001 provenance columns. Idempotent on re-run via `DELETE FROM findings WHERE id = ?` before `INSERT`.
  - `_Cyp2d6CallPayload` widened: `cyp2d6_status: str` added; `diplotype` typed `str | None`.
  - `pipeline_cyp2d6_call` handler branches on `row is None`: no-call path emits the indeterminate finding + payload with `cyp2d6_status='no_call'`, success path emits `cyp2d6_status='called'` with the diplotype.
  - `pipeline_pharmcat` handler auto-detects `cyp2d6_no_call_envelope.json` in `run_dir` (when no explicit `--cyp2d6-diplotype-json` is passed) and emits a `get_console().print()` warning before `run_pharmcat` runs. The no-`-po` behaviour is unchanged from the existing `run_pharmcat(cyp2d6_diplotype_json=None)` path.

**Files created**:
- `packages/toolkit/tests/unit/test_cyrius_no_call.py` (7 tests: 4 wrapper-behaviour, 3 schema-pin).
- `packages/toolkit/tests/integration/test_cli_pipeline_cyp2d6_no_call.py` (3 CLI integration tests).

**Files modified (existing tests)**:
- `packages/toolkit/tests/unit/test_cyrius_wrapper.py` — added `test_call_cyp2d6_successful_call_stamps_cyp2d6_status_called` regression test asserting the success envelope carries `cyp2d6_status='called'`.

**Implementation surprises / decisions**:
1. The CLI envelope JSON serializes with `model_dump_json(exclude_none=True)` (per `_cli/__init__.py:96`). The `diplotype` field on the no-call path is `None`, so it's absent from the JSON rather than literal `null`. The test was adjusted to accept either shape: `"diplotype" not in payload or payload["diplotype"] is None`. Both shapes are semantically equivalent for downstream consumers.
2. The `cyrius_no_call:` evidence-ref prefix is currently not in `EvidenceKind` (which lists `clinvar | pgs_catalog | pharmgkb`). The agent's `genomeclaw_evidence` tool will 404 on this prefix. The plan's scope is intentionally limited to emitting the row; adding an evidence resolver is a follow-up (the sentinel JSON is the evidence and lives on disk for audit, so INV-E001 is structurally satisfied by the path-as-evidence-ref pattern). See follow-up note below.
3. The integration test's "rich-output warning" assertion checks combined stdout+stderr because typer's rich console writes to stderr in JSON-mode-off runs.

**Status**: Phase 1 GREEN. Ready for Phase 2 (agent surface + system-prompt addition + smoke).

---

### 2026-05-25 — Phase 2 RED → GREEN (complete; synthetic smoke green)

**Scope landed**: evidence resolver for `cyrius_no_call:<path>` refs; system prompt § 6 amendment with the CYP2D6 indeterminate clause; integration test confirming the indeterminate row reaches the agent via `/v1/findings?genes=CYP2D6`.

**Test results**:

RED (before implementation):
```text
5 failed, 2 passed in 0.48s
```
The 2 incidentally-passing tests were `test_evidence_resolver_rejects_unknown_kind_still` (unchanged behaviour) and `test_indeterminate_finding_reaches_findings_api` — the latter passed in RED because Phase 1 already inserted the row + the `/v1/findings` filter was already in place. This means the API observability of the indeterminate row was structurally complete after Phase 1; Phase 2 added the *resolver* + *prompt* layers.

GREEN (after the three implementation steps):
```text
25 passed in 0.56s
```
All Phase 2 + Phase 1 tests green; the cross-language schema-diff test (Plan 1's INV-A004) still green.

Full toolkit regression:
```text
4 failed, 937 passed, 136 skipped, 1 warning in 16.68s
```
The 4 failures are the same pre-existing failures from Plan 1's baseline.

**Files modified**:
- `packages/toolkit/src/genomeclaw_toolkit/schemas/evidence.py` — added `"cyrius_no_call"` to the `EvidenceKind` Literal; updated docstring to document the new local-artefact-keyed kind.
- `packages/toolkit/src/genomeclaw_toolkit/service/store.py` — added `"cyrius_no_call"` to `_SUPPORTED_EVIDENCE_KINDS`; added `_resolve_cyrius_no_call(sentinel_path)` which reads the JSON sentinel and returns a summary-class `{kind, id, body, source}` dict; dispatched the new kind in `resolve_evidence`. Per INV-P002, the response body does NOT include `raw_cyrius_output` — that lives on disk for audit.
- `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` — added a `#### CYP2D6 indeterminate (no-call)` sub-section under § 6 teaching the agent the binding "MUST NOT present as Normal Metabolizer" rule, naming the eight CYP2D6 substrates, and pointing at the `cyrius_no_call:` evidence-ref marker.
- `packages/toolkit/tests/integration/test_service_evidence.py` — renamed `test_supported_evidence_kinds_pinned_to_variant_keyed_only` → `test_supported_evidence_kinds_pinned`; updated the asserted set to include `cyrius_no_call`; updated docstring to document the new kind class.

**Files created**:
- `packages/toolkit/tests/integration/test_evidence_cyrius_no_call.py` — 5 tests covering the resolver's happy path, body content (forbids NM phrase), INV-P002 (raw output excluded), missing-sentinel returns None, and unknown-kind-still-rejected.

**Files modified (existing tests)**:
- `packages/toolkit/tests/integration/test_cli_pipeline_cyp2d6_no_call.py` — added `test_indeterminate_finding_reaches_findings_api` (Phase 2 integration: end-to-end through `/v1/findings` filter).
- `packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py` — added `test_system_prompt_teaches_cyp2d6_indeterminate_handling` (Phase 2 prompt contract).

**Implementation notes**:
1. The phase-2.md spec called for `summary` / `classification` / `review_status` / `url` fields in the resolver response. The actual `EvidenceRecord` schema has only `{kind, id, body, source}`. Aligned the resolver to the existing schema rather than extending it — the schema extension would be a separate plan.
2. The `_resolve_cyrius_no_call` body explicitly names "Normal Metabolizer" and the eight substrates so the test contract (`test_evidence_resolver_cyrius_no_call_body_forbids_normal_metabolizer`) can pin the prose verbatim. Drift between the resolver body and the system-prompt clause would create a coverage gap; both were written to match.
3. INV-P002 minimal-sufficient guard: the body summarizes the indeterminate state but does NOT include the raw Cyrius output block. The on-disk sentinel JSON carries the full audit trail; the agent only needs the rendered prose to communicate with the user.

**Real-data smoke**: pending project-owner manual run per the meta-plan cross-cutting requirement. The synthetic-DB smoke is covered by `test_indeterminate_finding_reaches_findings_api` (FastAPI TestClient end-to-end against a fresh DuckDB seeded by the CLI). The expensive real-data portion (`bin/genomeclaw-prs-smoke` against the owner's actual CRAM) is the manual gate before the plan moves to `docs/plans/completed/`.

**Status**: Phase 2 GREEN. Plan code-complete; awaits real-data smoke before close-out.

---

*Append new sessions below this line.*

---

### 2026-05-25 — End-to-end HTTP smoke against running v0.3 host service

**Setup**:
- Host service restarted natively on `127.0.0.1:8645` using the new source (`SCHEMA_VERSION="v0.3"`).
- Seeded a synthetic v0.3 derived store at `/Volumes/Genome_Work/genomeclaw/derived/2026-05-25T17-00-00Z-bioreviewsmoke/` via `prep.store.create_store` + `write_coverage_qc` + `prep.pgs.stamp_pgs_row`.
- CURRENT symlink repointed; service restarted to pick up new run; `/v1/health` → `{"status":"ok","schema_version":"v0.3"}`.

**Result for this plan**: **GREEN** at the HTTP layer (the smoke evidence specific to this plan is in the synthesis block below).

The smokes covered (across all 7 plans):
- **Plan 1**: `/v1/pgs/computed/PGS999999` returns `"calibration_status": "decline"` + `"decline_reason": "variant_overlap_insufficient"`; `/v1/pgs/computed/PGS000018` returns `"calibration_status": "clean"` + `"decline_reason": null`. Both fields visible to the agent. INV-A004 verified end-to-end.
- **Plan 2**: `/v1/evidence/cyrius_no_call:<sentinel>` resolves to a `body` carrying the binding "Do not interpret as Normal Metabolizer" prose + the 8 CPIC substrates. Evidence kind registered.
- **Plan 3**: `RefsVerifyPayload.alignment_warnings` field present in the Pydantic model.
- **Plan 4**: `/v1/health` returns `schema_version="v0.3"`; `variants` table DDL carries `mane_plus_clinical_transcript` + `transcript_discordant`.
- **Plan 5**: `/v1/gene/PMS2` returns `region_class="difficult_pseudogene"` + a non-null `caveat` quoting the canonical short-read-WGS warning; `/v1/gene/CYP2D6` returns `requires_dedicated_caller` + Cyrius-specific caveat; `/v1/gene/BRCA1` (standard) returns `caveat=null` (no signal dilution).
- **Plan 6**: `load_uncallable_sites_from_sidecar` correctly extracts the 2 `uncallable` rows from a 5-row sidecar TSV.
- **Plan 7 Phase 1**: `classify_calibration` produces the correct verdict on all 4 scenarios (clean / weight-axis-decline / count-axis-decline / backwards-compat).

**What this smoke does NOT cover** (still project-owner manual gate before move to `completed/`):
- Full `pipeline run` against the real CRAM exercising annotate (`--mane` flag through real VEP), materialize (dual-row emit), mosdepth-against-real-CRAM with v2 panel, force-genotyping with real bcftools, end-to-end pgsc_calc + sidecar consumption. Those need a toolkit Docker image rebuild + a 30 min – 6 hour wall-clock run.
