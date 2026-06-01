# README Accuracy Refresh — Development Plan

**Status**: Complete (2026-06-01) — all 4 phases done; 8-assertion consistency gate green; README accurate; privacy pass clean; plan archived to completed/.
**Created**: 2026-06-01
**Branch**: `docs/readme-accuracy-refresh` (to be created at implementation start)
**Spec**: [spec.md](spec.md)

---

## Summary

Repair `README.md` to match the shipped CLI / host-service / plugin / invariants surface, and add one code-derived consistency test that pins the enumerable facts so the doc can't silently drift again. Docs + one test only — no code/behaviour change.

## Critical Invariants to Respect

- **INV-C002** (CLI Output Contract Stability) — the README is the prose face of the CLI surface; the rewrite documents the real command tree + flags, and the consistency test pins the enumerable subset.
- **INV-P001 / INV-P002** (Privacy default / minimal-sufficient egress) — the rewritten Privacy Posture + agent-integration sections must keep the egress model accurate (host-side-only raw data; NemoClaw as the named egress; topic-only web_search; host profile sensitive + read-only). Blocking privacy-safety-reviewer pass before merge.
- **INV-D002** (Raw artifacts host-side only) — storage/architecture framing stays accurate.
- **INV-V001** (Verification methodology) — the consistency test is structural inspection over a source doc + code (the sanctioned mechanism); retired-string-absence checks target the static README and are annotated `# INV-V001-allow`.

## Proposed New Invariants

- Provisional **INV-C-docs-accuracy** — deferred (see spec). The Phase-1 test is the deliverable; promotion decided in Phase 4 only if warranted.

## Current State Analysis

The README is the canonical entry point and is factually wrong in the CLI / agent-integration / status sections (full audited table in [spec.md § Background](spec.md)). Ground truth (verified 2026-06-01 from code):

- **CLI groups**: `host`, `refs`, `runs`, `pipeline`, `completion`.
  - `host`: `doctor`, `setup`, `eject`, `service`, **`profile {init,show,set,review,edit}`**.
  - `refs`: `fetch`, `list`, `verify`, `info`.
  - `runs`: `list`, `show`, `current`.
  - `pipeline`: `ingest`, `normalize`, `annotate`, `materialize`, `run`, `pgs-compute`, `prs-prepare-coverage`, `prs-compute`, `pharmcat`, `cyp2d6-call`, `pgs-config-write`.
- **Host service**: port **8645**; routes `/v1/health`, `/v1/variants`(+`/{key}`), `/v1/findings`(+`/{id}`), `/v1/evidence/{ref}`, `/v1/provenance/{run_id}`, `/v1/gene/{symbol}`, `/v1/pgs/computed`(+`/{pgs_id}`), `POST /v1/pgs/compute`, `/v1/pgs/compute/{task_id}`, `/v1/capabilities`, **`/v1/host/profile`**, **`/v1/host/profile/completeness`**.
- **Plugin tools** (`openclaw.plugin.json` `contracts.tools`): 10 — `genomeclaw_status/findings/variant/evidence/gene` + `genomeclaw_pgs_list/_get/_compute/_compute_status` + `genomeclaw_host_profile`.
- **Versions**: `SCHEMA_VERSION = v0.4`; `INVARIANTS.md` Version **1.26**.

### Files to Modify
- `README.md` — CLI section (host group incl. profile + setup flags; refs/runs/pipeline command lists), agent-integration section (10 tools, 8645, real endpoint list), Status/overview freshness, invariants reference.

### Files to Create
- `packages/toolkit/tests/invariants/test_readme_accuracy.py` — code-derived consistency gate.
- This plan's `work-notes.md` (continuous log) + `phases/phase-{1,2,3,4}.md`.

## Solution Design

The consistency test is the spine. It derives ground truth at test time and asserts the README matches:

1. **Plugin tools** — parse `openclaw.plugin.json` `contracts.tools`; assert every tool name appears in the README and the README does not say "six … tools".
2. **CLI command tree (curated)** — import the Typer app (or parse the command-group sources) and assert the README documents the five groups + the `host profile` subcommands + the `pipeline` subcommand set; assert `refs fetch` (not "pipeline fetch").
3. **Host-service port** — assert `8645` appears and there is no `8643` associated with the GenomeClaw service (DevRelClaw's 8643 may still be mentioned by name in the coexistence section — the assertion targets the *GenomeClaw service* port lines).
4. **Endpoints** — assert `/v1/host/profile` is present and the retired `/v1/pgs/{trait}` is absent.
5. **Invariants link** — assert the README links `docs/reference/INVARIANTS.md`; (Q1) either version-less or matching the current Version string.

The README edits then make each assertion pass. Prose quality (read-through) is human-verified; the test pins only enumerable facts, deliberately not wording (avoids brittle over-pinning).

### Key Design Decisions

1. **Code-derived, not hardcoded, ground truth** — the test reads the manifest + Typer app + routes so it tracks the code, not a second copy of the facts that could itself drift. (Hardcoding "10 tools" in the test just moves the drift.)
2. **Curated command subset, not every leaf** (Q2) — pin groups + host-profile + pipeline subcommands + the `refs fetch` placement; don't pin every rarely-changing leaf, to avoid brittleness.
3. **Phase the rewrite by README section** so each phase is reviewable and turns a coherent subset of the gate green.
4. **Privacy-safety-reviewer pass is blocking** — the README describes the privacy model; an inaccurate description is itself a safety issue.

### Schema / Provenance Impact
None.

### Privacy & Egress Impact
None introduced. AC10 verifies the *described* model stays accurate.

## Phase Overview

| Phase | Description | TDD focus | Est. tests | Scope |
|-------|-------------|-----------|-----------|-------|
| 1 | Audit lock-in + consistency-test harness | RED: `test_readme_accuracy.py` derives ground truth, fails on current README | 1 test file (~6–9 assertions) | Resolve Q1/Q2; write the gate RED |
| 2 | CLI surface section rewrite | GREEN: CLI/host-profile/pipeline assertions | — | host group (incl. profile) + setup flags + refs/runs/pipeline lists |
| 3 | Agent-integration section rewrite | GREEN: tools/port/endpoints assertions | — | 10 tools, 8645, real endpoint list incl. host profile; privacy pass |
| 4 | Freshness + cross-links + final verify | GREEN: invariants-link assertion; full gate + suite | — | Status/overview accuracy, invariants version, read-through, close-out |

## Phase 1: Audit lock-in + consistency-test harness

### Deliverables
- `test_readme_accuracy.py` (RED against current README).
- Q1 (version-pin) + Q2 (command subset) resolved + recorded in work-notes.

### Invariants Enforced Here
- INV-V001 (structural-doc gate; retired-string checks annotated).

### Success Criteria
- The test fails for the *right* reasons (missing host_profile tool, "six tools", 8643, missing `/v1/host/profile`, missing `host profile` commands) — RED output captured in work-notes.

## Phase 2: CLI surface section rewrite

### Deliverables
- README CLI sections updated: `host` group incl. the `profile {init,show,set,review,edit}` subgroup with one-line purposes + the `host setup --skip-profile`/`--thorough-profile` flags; `refs`/`runs`/`pipeline` command lists corrected (`fetch` under `refs`).

### Success Criteria
- The CLI/host-profile/pipeline assertions of the gate pass; AC1, AC5 met.

## Phase 3: Agent-integration section rewrite

### Deliverables
- README agent-integration section: ten tools (names + one-liners), port 8645, the real endpoint list (incl. `/v1/host/profile`(+`/completeness`) + the agent-driven PRS endpoints; drop `/v1/pgs/{trait}`), and a one-line note that the agent retrieves the host profile before genome-informable replies (INV-C004).
- Blocking privacy-safety-reviewer pass on the rewritten privacy + agent-integration sections.

### Success Criteria
- Tools/port/endpoints assertions pass; AC2, AC3, AC4, AC10 met.

## Phase 4: Freshness + cross-links + final verify

### Deliverables
- Status/"Architecture at a glance" framing reflects shipped reality; invariants reference de-staled (Q1 resolution); cross-links checked.
- Full consistency gate green; full toolkit suite green; manual read-through.
- INV-C-docs-accuracy promotion decision recorded; plan moved to `completed/`.

### Success Criteria
- AC6, AC7, AC8, AC9 met; suite green; plan archived.

## Testing Strategy

### Unit Tests
- `test_readme_accuracy.py` — the consistency gate (the only new test).

### Integration / Provenance / Determinism / Privacy-Default / Evidence-Binding / Report-Rendering Tests
- N/A (docs-only). The privacy posture is verified by the privacy-safety-reviewer pass (AC10), not an automated egress test (no code path changes).

### Invariant Tests
- The consistency gate is the INV-C002-prose / doc-accuracy check; INV-V001-annotated for the retired-string assertions.

## Documentation Updates

- `README.md` — the subject of the plan (CLI surface, agent integration, Status, privacy citations, architecture diagram, repo-layout tree).
- `docs/reference/INVARIANTS.md` — companion 1-line fix: INV-P001 named-egress host-service port `8643` → `8645` (the review surfaced a pre-existing error). **No** INV-C-docs-accuracy promotion (deferred; the consistency test stands alone).
- `docs/reference/cli-output-schemas.md` — verified current (host-profile envelopes already landed); no change.

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Complete | 2026-06-01 | 2026-06-01 | `test_readme_accuracy.py` (8 gates, code-derived); RED on current README. Q1=version-less link, Q2=curated subset. |
| Phase 2 | Complete | 2026-06-01 | 2026-06-01 | `host profile` subgroup + `host setup` profile flags documented; CLI/host-profile gate green. |
| Phase 3 | Complete | 2026-06-01 | 2026-06-01 | Agent-integration rewrite (10 tools, 8645, real endpoint list incl. `/v1/host/profile`); blocking privacy pass — accept-with-changes, all fixes applied (incl. retired curated_notes / INV-C001 v1.5 fossils + companion INVARIANTS port fix). |
| Phase 4 | Complete | 2026-06-01 | 2026-06-01 | Status/overview de-staled, invariants link version-less, full gate + suite green (1260 passed; 7 pre-existing failures). INV-C-docs-accuracy: NOT promoted (test stands alone). |

---

## Open Risks & Follow-ups

- **Over-pinning risk** — the consistency test must pin enumerable facts, not prose, or routine README wording edits will break it. Mitigated by the curated-subset decision (Q2).
- **README contradicts itself today** (8643 vs 8645) — the rewrite must sweep *all* port references, not just the agent-integration one; the gate's "no 8643 for the service" assertion guards this.
- **Other `docs/reference/*` drift** — out of scope here; if the rewrite surfaces a stale reference doc, file a separate follow-up rather than expanding this plan.
- **INV-C-docs-accuracy promotion** — left as a Phase-4 decision; the test stands on its own regardless.
