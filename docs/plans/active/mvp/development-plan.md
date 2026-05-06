# MVP — Development Plan

**Status**: Draft
**Created**: 2026-05-06
**Branch**: `feature/mvp` (target — not yet created)
**Spec**: [spec.md](spec.md)

---

## Summary

Seven sequential phases that take the repo from "scaffolding only" to "a NemoClaw agent over Telegram answers real clinical and lifestyle questions about a real Nebula genome." Each phase is reviewable independently and ships its own RED → GREEN → REFACTOR test cycle.

## Critical Invariants to Respect

The MVP is the first place all canonical invariants land in code. Every phase enforces a subset; the full set is enforced by the end of Phase 7.

- **INV-D001** Raw genomic files source-of-truth — Phase 2 introduces it; every later phase preserves it.
- **INV-D002** Raw artifacts host-side only — Phase 5 lands the sandbox image with no bioinformatics binaries; smoke test enforces.
- **INV-E001** Evidence traceability — Phase 6 lands the finding schema requirement.
- **INV-P001** Privacy default — Phases 4 and 5 land the network policy preset and the integration tests.
- **INV-P002** Agent egress is named, minimal-sufficient — Phases 4, 5, 6 each contribute a layer.
- **INV-R001** Rebuildability — Phases 2 and 3 introduce provenance columns and the determinism test.
- **INV-C001** Clinical / lifestyle distinction — Phase 6 lands the four-category schema and `evidence_quality` field.

## Proposed New Invariants

None. The MVP exercises existing invariants; no new ones are proposed.

## Current State Analysis

### What exists today

- `packages/nemoclaw-plugin/` — TypeScript plugin skeleton, manifest, policy preset, sandbox `Dockerfile`. **No live build, no integration tested.**
- `docs/` — full reference set: invariants, grand plan, architecture, user stories, planning protocol, agents.
- `.claude/agents/` — six specialized subagents.

### What's missing

- `packages/toolkit/` — the entire host-side stack. Pipeline, host service, schemas, tests.
- A working CI shape.
- A built sandbox image.
- Any live data flow.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `packages/nemoclaw-plugin/src/index.ts` | TS skeleton with placeholders | Phase 5 — wire to live host service, add JSON-encoded responses, run against real sandbox |
| `packages/nemoclaw-plugin/openclaw.plugin.json` | Manifest with config schema | Phase 5 — possibly extend `configSchema` if Phase 5 surfaces gaps |
| `packages/nemoclaw-plugin/policy-preset.yaml` | Read-only paths whitelisted | Phase 4/5 — verify final endpoint list matches host service routes |

### Files to Create (high-level)

| Path | Purpose |
|------|---------|
| `packages/toolkit/pyproject.toml` | Python package (uv-managed) |
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | `genomeclaw-prep` entrypoint |
| `packages/toolkit/src/genomeclaw_toolkit/prep/` | ingest / normalize / annotate / materialize |
| `packages/toolkit/src/genomeclaw_toolkit/service/` | FastAPI host service |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/` | finding / evidence / provenance Pydantic models |
| `packages/toolkit/tests/` | unit + integration + provenance + determinism + privacy tests |
| `.github/workflows/test.yml` | CI |

## Solution Design

The two-domain architecture in [architecture.md](../../reference/architecture.md) is the design. The MVP doesn't reinvent it — it implements it.

```text
[user, Telegram] → [OpenClaw + GenomeClaw plugin in sandbox]
                              ↓ HTTP
                   [genomeclaw-service on host:8643]
                              ↓ DuckDB read
                   [/mnt/genomeclaw/derived/CURRENT/]
                              ↑ written by
                   [genomeclaw-prep ingest|normalize|annotate|materialize]
                              ↑ reads (RO)
                   [/mnt/genomeclaw/raw/, /mnt/genomeclaw/reference/]
```

### Key Design Decisions

1. **Python + uv for the toolkit** — matches the bioinformatics ecosystem (`cyvcf2`, `pysam`, DuckDB Python bindings, PharmCAT bindings). Already a Decision Taken in [grand-plan.md](../../reference/grand-plan.md).
2. **FastAPI for the host service** — minimal, async, fits the host service's small surface area and shapes minimal-sufficient JSON cleanly with Pydantic.
3. **SnpEff as the default annotator for the MVP** — simplest of the three candidates (Q1 in spec). Switchable later via Theme B follow-up.
4. **One lifestyle finding for the MVP — *CYP1A2* / caffeine** — proves the lifestyle track without bloating Phase 6.
5. **The `CURRENT` symlink resolves the active run** — atomic update by `genomeclaw-prep`, the host service reads the symlink target on startup and on `SIGHUP`.

### Schema / Provenance Impact

- Schema v0.1 introduced. The host service refuses to load anything not v0.1.
- Provenance columns required on every derived row: `source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`.

### Privacy & Egress Impact

- **New egress points**: agent → OpenAI (managed by OpenShell, not by GenomeClaw); plugin → host service (whitelisted by policy preset); `genomeclaw-prep fetch` → annotation source URLs (host-side, deliberate).
- **No new secret-handling surfaces** in the MVP — credentials for OpenAI live in the OpenShell gateway store; `fetch` uses no auth for ClinVar/gnomAD/dbSNP downloads.
- **Redaction**: not strictly needed for the MVP because the host service constructs minimal-sufficient JSON from a curated finding schema. The redaction utility lands when the first non-curated path appears (post-MVP).

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Repo scaffolding & test infrastructure | smoke + import + CI shape | ~5 |
| 2 | Host CLI: ingest + reference fetch + minimal derived store | provenance, integrity checks, source-RO | ~10 |
| 3 | Host pipeline: normalize + materialize | determinism, provenance | ~12 |
| 4 | Host pipeline: annotate (ClinVar + gnomAD + dbSNP) | annotation correctness, determinism, provenance | ~12 |
| 5 | Host service + plugin wiring + sandbox image | privacy default, policy preset, plugin round-trip | ~15 |
| 6 | Findings + evidence + report (with lifestyle support) | evidence binding, escalation markers, lifestyle calibration | ~18 |
| 7 | End-to-end MVP demo + invariant sweep | full agent flow, all invariants live | ~10 |

Total estimated tests: ~80, distributed across the first-class categories.

---

## Phase 1: Repo scaffolding & test infrastructure

**Goal**: a working `packages/toolkit/` Python package with a test harness, a `genomeclaw-prep --help` command that prints, and a CI workflow that runs the test suite.
**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `packages/toolkit/pyproject.toml`
2. `packages/toolkit/src/genomeclaw_toolkit/{cli,prep,service,schemas}/`
3. `packages/toolkit/tests/test_smoke.py`
4. `.github/workflows/test.yml`

### Invariants Enforced Here
None of `INV-Dxxx` / `INV-Exxx` / `INV-Pxxx` / `INV-Cxxx` yet — this phase is foundations. The smoke test only asserts the package imports and the entrypoint runs.

### Success Criteria
- [ ] `uv run pytest` passes on a fresh clone.
- [ ] `uv run genomeclaw-prep --help` prints subcommand list.
- [ ] CI workflow runs the test suite and lint.

## Phase 2: Host CLI — ingest + reference fetch + minimal derived store

**Goal**: `genomeclaw-prep ingest` and `genomeclaw-prep fetch` work against fixtures; a derived store with provenance columns is produced.

### Deliverables
1. `genomeclaw-prep ingest` subcommand (integrity checks + indexing + reference-build sniffing).
2. `genomeclaw-prep fetch --source clinvar|gnomad|dbsnp` subcommand.
3. Minimal DuckDB derived store with provenance columns + `manifest.json` + `provenance.json`.
4. `CURRENT` symlink semantics.

### Invariants Enforced Here
- **INV-D001** — pipeline tests assert source files unchanged after a run.
- **INV-R001** — provenance columns populated; `created_at` recorded; tool versions pinned in the manifest.

### Success Criteria
- [ ] Fixture ingest produces a populated derived store with all seven provenance columns.
- [ ] Source file SHA256 unchanged after `ingest`.
- [ ] `CURRENT` symlink atomically updated.

## Phase 3: Host pipeline — normalize + materialize

**Goal**: VCF normalization (left-align, split multi-allelics, canonical representation) and materialization into the DuckDB store. Determinism test passes.

### Deliverables
1. `genomeclaw-prep normalize` subcommand wrapping `bcftools norm`.
2. `genomeclaw-prep materialize` subcommand producing the canonical `variants` table.

### Invariants Enforced Here
- **INV-R001** — determinism test runs the pipeline twice and diffs byte-for-byte.

### Success Criteria
- [ ] Normalization is deterministic against a fixture.
- [ ] Two consecutive `materialize` runs produce byte-equivalent DuckDB files (modulo declared non-determinism — none expected).

## Phase 4: Host pipeline — annotate

**Goal**: Annotation against ClinVar + gnomAD + dbSNP via SnpEff/SnpSift. Annotated variants land in the derived store with provenance for each annotation source.

### Deliverables
1. `genomeclaw-prep annotate` subcommand.
2. Annotation source resolution from `/mnt/genomeclaw/reference/`.
3. Annotation tables in the derived store (one per source) joined to the canonical `variants` table.

### Invariants Enforced Here
- **INV-R001** — annotation step is deterministic; annotation source versions pinned.
- **INV-D001** — annotation files in `reference/` are not mutated.

### Success Criteria
- [ ] Fixture VCF annotates against fixture ClinVar / gnomAD / dbSNP slices.
- [ ] Annotation versions appear in the run's `manifest.json`.
- [ ] Annotation tables include provenance columns.

## Phase 5: Host service + plugin wiring + sandbox image

**Goal**: A live network round-trip from a NemoClaw sandbox to the host service. The privacy posture is enforced for the first time.

### Deliverables
1. `genomeclaw-service` FastAPI app: `/v1/health`, `/v1/variants`, `/v1/variants/{key}`, `/v1/provenance/{run-id}`.
2. Wired plugin (`packages/nemoclaw-plugin/src/index.ts`) calling the live service.
3. Sandbox image built from `packages/nemoclaw-plugin/sandbox/Dockerfile`; onboarded via `nemoclaw onboard --from`.
4. `INV-D002` smoke test on the built image (no bioinformatics binaries present).

### Invariants Enforced Here
- **INV-D002** — sandbox image inspection.
- **INV-P001** — privacy-default integration test asserts the plugin reaches only the host service and inference.local.
- **INV-P002** — policy preset enforced; live-test asserts SSRF guard rejects un-allowlisted hosts/ports; minimal-sufficient JSON shape verified.

### Success Criteria
- [ ] `genomeclaw_status` round-trip works from inside the sandbox.
- [ ] Sandbox image has no `samtools` / `bcftools` / `bgzip` on PATH.
- [ ] Live policy probe: sandbox reaches only the configured host:port.

## Phase 6: Findings + evidence + report

**Goal**: The lifestyle and clinical tracks both work. The agent can answer Story 2, Story 4, and Story 9 questions correctly.

### Deliverables
1. Finding schema (`category`, `clinical_escalation`, `evidence_quality`).
2. Evidence record schema (variant-keyed and non-variant-keyed kinds).
3. Initial finding set: ACMG SF + PharmCAT actionable + *CYP1A2* (caffeine).
4. `/v1/findings`, `/v1/findings/{id}`, `/v1/evidence/{ref}`, `/v1/report?scope=...`.
5. Report scopes: `physician-handoff`, `pgx-overview`, `acmg-sf-overview`, `lifestyle-experiment`, `default`.
6. Plugin tools `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_report` wired and returning structured JSON.

### Invariants Enforced Here
- **INV-E001** — every finding has an evidence reference; schema rejects findings without one.
- **INV-C001** — `clinical_escalation` set on `clinical-actionable`; `evidence_quality` set on `lifestyle`; over-deferral and over-claim snapshot tests pass.
- **INV-P002** — bulk-class endpoints wired but disabled in the MVP; reject-with-error tests confirm.

### Success Criteria
- [ ] Snapshot tests pass for the three reference user-stories conversations (Story 2, Story 4, Story 9).
- [ ] *CYP1A2* finding renders with `evidence_quality` populated, `clinical_escalation` unset.
- [ ] BRCA2 pathogenic finding (if present in fixture) renders with `clinical_escalation` set.

## Phase 7: End-to-end MVP demo + invariant sweep

**Goal**: All seven AC items from `spec.md` pass on the project owner's actual hardware with a real Nebula VCF.

### Deliverables
1. Full ingest → normalize → annotate → materialize → query → finding loop on the project owner's actual genome.
2. A live conversation transcript demonstrating Stories 2, 4, 9 (clinical-actionable + PGx + lifestyle).
3. Final invariant sweep: all `INV-xxx` tests green together.
4. Documentation updates: any architecture.md drift discovered during implementation lands here.

### Invariants Enforced Here
**All canonical invariants together**, in a single integration sweep.

### Success Criteria
- [ ] All seven `spec.md` ACs check off.
- [ ] All `tests/invariants/test_invXxxx_*.py` pass.
- [ ] No outbound calls observed except to the configured agent endpoint and host service.
- [ ] Plan moves to `docs/plans/completed/mvp/`.

---

## Testing Strategy

### Unit Tests (co-located)
- `packages/toolkit/src/genomeclaw_toolkit/**/*_test.py`: pure-function behavior on each pipeline step.

### Integration Tests
- `packages/toolkit/tests/integration/`: ingest → normalize → annotate → materialize → query end-to-end against fixture data.

### Provenance Tests
- `packages/toolkit/tests/provenance/`: every emitted derived row carries the seven canonical columns; manifest.json carries tool versions.

### Determinism Tests
- `packages/toolkit/tests/determinism/`: pipeline run twice on the same fixture; diff byte-for-byte.

### Privacy-Default Tests
- `packages/toolkit/tests/privacy/`: simulate full agent flow under default config; assert outbound calls limited to the configured agent endpoint and the configured host service.

### Evidence-Binding Tests
- `packages/toolkit/tests/evidence/`: every finding emitted by the host service has a non-null evidence reference; deleting an evidence record marks dependent findings stale on next rebuild.

### Report Rendering Tests
- `packages/toolkit/tests/reports/`: snapshot tests on `/v1/report?scope=...` outputs against fixture findings; over-claim and over-deferral both fail.

### Invariant Tests
- `packages/toolkit/tests/invariants/test_invXxxx_*.py`: one or more tests per `INV-xxx`, named so the ID appears in the test name.

---

## Documentation Updates

After Phase 7 lands:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — only if Phase 7's invariant sweep surfaces a needed new invariant; not expected.
- [ ] [docs/reference/architecture.md](../../reference/architecture.md) — update any drift discovered during implementation.
- [ ] [docs/reference/grand-plan.md](../../reference/grand-plan.md) — update Horizon 1–3 to "delivered" status; advance the deferred-decision rows where applicable.
- [ ] [docs/reference/user-stories.md](../../reference/user-stories.md) — mark resolved gap-analysis items.
- [ ] [README.md](../../../README.md) — replace "Getting Started" placeholder with the real ingest + service-start commands.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| Phase 1 | Pending | | | |
| Phase 2 | Pending | | | |
| Phase 3 | Pending | | | |
| Phase 4 | Pending | | | |
| Phase 5 | Pending | | | |
| Phase 6 | Pending | | | |
| Phase 7 | Pending | | | |

---

## Open Risks & Follow-ups

- **Plugin tool-return shape** (spec Q2) is unresolved until live-tested in Phase 5. If structured JSON returns aren't supported, the v0 `GENOMECLAW_JSON:` text-encoding ships and the work to upgrade is filed under a follow-up plan.
- **Annotator choice** (spec Q1) — SnpEff is the default; if Phase 4 shows it's too slow on the project owner's host, switch decision happens during Phase 4.
- **Sandbox image size** — bioinformatics deps are absent (per `INV-D002`), so the image stays small. But Node + the plugin's runtime deps still inflate it. Worth measuring in Phase 5.
- **Real-genome fixture in CI** — the project owner's actual Nebula VCF must never be committed. CI uses a small synthetic fixture; end-to-end on the real genome is run locally in Phase 7.
