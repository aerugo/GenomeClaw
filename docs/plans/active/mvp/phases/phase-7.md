# Phase 7: End-to-end MVP demo + invariant sweep

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)
**Spec**: [spec.md § AC1–AC14](../spec.md)

---

## Objective

Drive the full ingest → normalize → annotate → materialize → query → finding → live-agent loop against the project owner's real Nebula VCF + CRAM on the project owner's actual hardware, then sweep every `INV-xxx` in a single run. This is the phase that converts the MVP plan's claim ("a NemoClaw agent over Telegram answers real clinical and lifestyle questions about a real Nebula genome") from a list of unit-test green-bars into one live demonstration backed by passing invariant tests. The phase also lands the Phase-5-deferred SSRF probe (OpenShell L7 proxy under full Landlock + seccomp + netns isolation) so the runtime privacy floor is verified, not just the policy preset's static shape.

The phase is **not** about writing new pipeline code — Phases 1–6 are responsible for that. It is about driving the assembled system end-to-end, capturing the demo transcripts, and confirming the invariant tests pass together rather than only in isolated test files.

## Scope Boundaries

- **In scope**:
  - One end-to-end pipeline run on the project owner's real Nebula VCF (`MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz`) + real CRAM (`MPNRGLQ2K.mm2.sortdup.bqsr.cram`): `genomeclaw pipeline run` → `pgs-compute --pgs <id> --run-dir` → `cyp2d6-call` (Slice D output) — landing one DuckDB at `/Volumes/Genome_Work/genomeclaw/derived/<run-id>/variants.duckdb` that the host service serves.
  - Three live agent transcripts (gpt-5.5 over the OpenAI live-LLM harness, sandbox-resident): Story 1 (any actionable findings?), Story 4 (CYP2D6 PGx — requires Slice D), Story 9 (lifestyle caffeine — already shipped via agent-research-and-synthesis; re-stage against the real run's variants/coverage).
  - **Invariant sweep**: a single `pytest tests/invariants/ -v` run that exercises every `INV-xxx` test file together — INV-D001/D002/D003/D005/D006/D007/D008 + INV-E001 + INV-P001/P002 + INV-R001/R002 + INV-C001 + INV-T001 + INV-A001/A002/A003. The sweep happens against the live derived store from the real run, not against a synthetic fixture.
  - **SSRF probe** (deferred from Phase 5 per [phase-5.md](phase-5.md)): in the sandbox under full Landlock + seccomp + netns + OpenShell L7 proxy, attempt to reach un-allowlisted RFC 1918 hosts/ports + the public internet; assert the L7 proxy rejects all of them. Verifies OpenShell runtime behavior, not GenomeClaw behavior — but the GenomeClaw policy preset is the configuration under test.
  - **Documentation drift sweep**: any architecture.md, INVARIANTS.md, grand-plan.md, user-stories.md drift surfaced during the end-to-end run lands in this phase's commits. README.md "Getting Started" replaces its placeholder with the real ingest + service-start commands.
  - **Plan close-out paperwork**: development-plan.md, work-notes.md, and spec.md all reflect the final shipped design (not the original guess); the plan moves from `docs/plans/active/mvp/` to `docs/plans/completed/mvp/`.
- **Out of scope**:
  - Any new pipeline subcommand, schema column, evidence kind, or invariant.
  - Validation studies, eval harnesses, or additional Stories beyond 1, 4, 9 (the user-story-driven AC4/AC5 path).
  - Story 2 ("what do you know about me?") — already shipped under Phase 6 Slice F; re-staged here only if the Phase 6 run materially changed the derived store's shape.
  - Story 10 (PRS) live re-stage — optional polish per the 2026-05-22 EOD checkpoint; only landed if time permits and the v23 PRS row is still on-disk.
  - Cyrius / PharmCAT outside-call code — Slice D / D' deliverables. Phase 7 consumes them.
  - Onboarding additional PRS traits, expanding curated notes (retired), or any other Phase-2-onward subsystem extension.

## Invariants Enforced in This Phase

This phase **re-exercises** every canonical invariant in a single sweep rather than introducing new tests. The list below is the live-sweep checklist; each invariant must have at least one passing test that touched the real run's derived store.

- **INV-D001** Raw genomic files source-of-truth — VCF + CRAM SHA256 unchanged after the full run (`bin/genomeclaw-prs-smoke` / equivalent).
- **INV-D002** Sandbox image has no bioinformatics binaries — re-run `test_invD002_sandbox_image_minimal.py` against the current sandbox image tag.
- **INV-D003** Heavy scratch separated from authoritative outputs — preflight assertion at each orchestrator entry; verify `_scratch/` and `derived/` are non-nested on the project owner's drive.
- **INV-D005 / INV-D006 / INV-D007 / INV-D008** Path-crossing discipline — `test_invD00*` files green against the real run's argv emissions.
- **INV-E001** Every emitted finding carries `evidence_ref` — assert against `findings` rows in the real derived store.
- **INV-P001** Privacy default — sandbox flow with default config produces no outbound calls beyond `host.openshell.internal` + `inference.local` (re-run `test_invP001_*.py`).
- **INV-P002** Minimal-sufficient JSON + policy preset shape — `test_invP002_*.py` green; **SSRF probe under full Landlock + seccomp + netns** confirms runtime enforcement, not just static config.
- **INV-R001** Provenance columns on every derived row — assert against the real `variants` / `pgs_scores` / `findings` / `coverage_qc` tables.
- **INV-R002** Rebuildability — re-run the pipeline against the same VCF + same reference + same tool versions; diff the derived stores; expect byte-equivalent output modulo declared non-determinism.
- **INV-C001** v1.7 — clinical-actionable findings carry `clinical_escalation`; PRS findings are `clinical-non-actionable`; PRS decline pattern fires on an immature-trait question; snapshot tests over the three live transcripts pass.
- **INV-T001** Tool-conventions dataclasses match pinned versions — `test_invT001_tool_conventions_exist.py` green; the post-Phase-6 dataclass set (PgscCalc + Cyrius + any others) all show `verified_against_version` matching `_versions.py` pins.
- **INV-A001 / INV-A002 / INV-A003** Agent memory provenance + reasoning floor + PRS compute provenance — re-run `live_llm` tests against the post-Phase-6 sandbox image; assert `executionTrace.thinking` populated on the Story 9 + Story 4 turns and a memory note landed before each reply.

---

## TDD Steps

Phase 7 is integration + sweep, not RED/GREEN/REFACTOR per-feature. The "tests" already exist in `tests/invariants/`, `tests/privacy/`, `tests/provenance/`, `tests/determinism/`, and the `live_llm`-marked suites from prior phases. The phase-7 work is to **run them together against the real derived store** and reconcile any divergence — typically a stale test fixture that needs widening to admit the real data's shape, not a code bug.

### Step 7.1 — Stage the real run

1. Confirm `/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/` carries the canonical VCF + CRAM + indexes.
2. Confirm the reference layout under `/Volumes/Genome_Work/genomeclaw/reference/` is current (VEP cache + LOFTEE + AlphaMissense + gnomAD-exomes + dbSNP + gnomAD-constraint + pgs_catalog_ancestry).
3. Drive `genomeclaw pipeline run` end-to-end. Expected wall-clock: ≤4h30m on the project owner's hardware (Phase 4 closed at 4h08m58s; Phase 6 Slice D + pgs-compute add ~20–30 min).
4. Drive `genomeclaw pipeline cyp2d6-call` (Slice D output) — writes `derived/<run-id>/cyp2d6_diplotype.json`.
5. Drive `genomeclaw pipeline pgs-compute --pgs PGS000018 --run-dir <run-dir>` (already verified end-to-end via smoke v23 2026-05-22; re-stage if the v23 run's derived store has been pruned).
6. Update the `CURRENT` symlink atomically once all three artifacts are in place.

### Step 7.2 — Run the invariant sweep

```bash
cd packages/toolkit
GENOMECLAW_DERIVED_DIR=/Volumes/Genome_Work/genomeclaw/derived/CURRENT \
  uv run pytest tests/invariants tests/privacy tests/provenance tests/determinism -v
```

Reconcile any failures: a stale fixture (most likely — Phase 4/6 changed schemas; the invariant test may still admit the synthetic shape but the real shape differs) gets widened to admit both. A real bug gets a one-line fix or a follow-up plan, not a phase-7 commit.

### Step 7.3 — Capture the live transcripts

Re-use the agent-research-and-synthesis sandbox image (`genomeclaw/sandbox:ars-phase-2d` or its post-Phase-6 successor):

```bash
# Story 1: "Any actionable findings I should know about?"
uv run pytest tests/live_llm/test_story1_actionable_findings.py -v

# Story 4: "I'm being prescribed codeine — anything I should know?" (Cyrius + PharmCAT path)
uv run pytest tests/live_llm/test_story4_cyp2d6_codeine.py -v

# Story 9: "What does my genome say about caffeine?" (lifestyle; ARS pattern)
uv run pytest tests/live_llm/test_story9_caffeine.py -v
```

Each test snapshots the agent's prose + asserts the structural rules from `INV-C001` v1.7 + `INV-A001` + `INV-A002`. The transcripts themselves land in `docs/reference/transcripts/phase-7/` for the close-out narrative.

### Step 7.4 — SSRF probe under full isolation

The Phase 5 deferred work. The probe is parameterised over a list of (host, port, expected-outcome) tuples — RFC 1918 allowlist hosts + public internet hosts + non-allowlisted ports. Inside the sandbox under full Landlock + seccomp + netns + OpenShell L7 proxy, attempt connection; assert allowed connections reach the proxy + non-allowed connections fail at the netns boundary (not at the L7 reject layer — the netns hardening is the runtime backstop).

```bash
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:<current-tag> \
  uv run pytest tests/invariants/test_invP002_ssrf_runtime_probe.py -v
```

### Step 7.5 — Documentation drift sweep + close-out

1. `docs/reference/architecture.md` — verify the diagrams + endpoint sketches match the shipped code; reconcile drift.
2. `docs/reference/INVARIANTS.md` — verify version + Invariant Index match the latest invariants; no new invariants expected.
3. `docs/reference/grand-plan.md` — mark Horizons 1–3 as Delivered; advance deferred-decision rows where applicable.
4. `docs/reference/user-stories.md` — mark resolved gap-analysis items.
5. `README.md` — replace "Getting Started" placeholder with real ingest + service-start commands.
6. `docs/plans/active/mvp/development-plan.md` — final progress table; all phases at Complete.
7. `docs/plans/active/mvp/work-notes.md` — phase-7 close-out block.
8. Move `docs/plans/active/mvp/` → `docs/plans/completed/mvp/`.

---

## Implementation Details

### Tracing what actually runs

Phase 7 is the first place every `INV-xxx` test has the real derived store available. Expect 1–3 invariant tests to fail-then-widen on first pass: the real data carries shapes synthetic fixtures don't cover (e.g., the `coverage_qc` table has ~20,000 gene-level rows vs. the fixture's 7; the `findings` table has the Cyrius-derived PGx row in addition to whatever fixture rows were assumed). Widening means admitting the real shape, not regressing on the invariant.

### Sequencing inside Step 7.1

If the project owner's hardware can re-run the full pipeline from scratch in ≤4h30m, that is the canonical run. If wall-clock is constrained, the v23 (2026-05-22) PRS run's derived store under `/Volumes/Genome_Work/genomeclaw/derived/<v23-run-id>/` is acceptable as a starting point; layer in the Phase 6 Slice D output (Cyrius `cyp2d6_diplotype.json`) by running just `genomeclaw pipeline cyp2d6-call` against the v23-staged BAM.

### Edge cases

- **Sandbox image rebuild lag**: if Phase 6 closed without rebuilding the sandbox image, Step 7.3's `live_llm` tests skip. Resolution: rebuild the image as part of phase-7 setup (no plan changes; just one `docker build` + `nemoclaw onboard --from`).
- **PGS Catalog rate-limiting**: the SSRF probe must NOT exercise the PGS Catalog endpoint (the probe is a SSRF-attempt test, not a fetch test). Use a mock RFC 1918 destination + a public-internet destination unrelated to GenomeClaw's allowlist.
- **OpenShell L7 proxy version drift**: the Phase-5-deferred work was deferred *because* it required pinning a specific OpenShell version's policy enforcement. If the current OpenShell version's probe interface differs from Phase 5's expectations, the test gets a thin probe-runtime-version dataclass per INV-T001 before shipping.

### Privacy / egress notes

Phase 7 introduces **no new egress surfaces**. The four documented surfaces (agent → OpenAI managed by OpenShell L7 proxy; plugin → host service; `genomeclaw refs fetch` → annotation sources; `pgsc_calc` → PGS Catalog) are exercised here for the last time as part of the MVP close-out. Story 9 re-stage may trigger `web_search` if the agent's memory has aged out — that is the AC13 path (a fresh `web_search` call when memory is past freshness date), expected, and recorded in the transcript.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/mvp/phases/phase-7.md` | THIS FILE | Authoring + tracking the close-out phase |
| `docs/reference/transcripts/phase-7/story-1.md` | CREATE | Story 1 live transcript (actionable findings) |
| `docs/reference/transcripts/phase-7/story-4.md` | CREATE | Story 4 live transcript (CYP2D6 PGx) |
| `docs/reference/transcripts/phase-7/story-9.md` | CREATE | Story 9 live transcript (caffeine lifestyle) |
| `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` | CREATE | Phase-5-deferred SSRF runtime probe |
| `docs/reference/architecture.md` | MODIFY (drift) | Reconcile any post-Phase-6 drift |
| `docs/reference/INVARIANTS.md` | MODIFY (close-out) | Version stamp + Invariant Index sweep |
| `docs/reference/grand-plan.md` | MODIFY (close-out) | Horizons 1–3 Delivered; deferred-decision rows |
| `docs/reference/user-stories.md` | MODIFY (close-out) | Mark resolved gap-analysis items |
| `README.md` | MODIFY | Replace "Getting Started" placeholder |
| `docs/plans/active/mvp/development-plan.md` | MODIFY | Final progress table; all phases Complete |
| `docs/plans/active/mvp/work-notes.md` | MODIFY | Phase-7 close-out block |
| `docs/plans/active/mvp/` | MOVE | → `docs/plans/completed/mvp/` |

---

## Verification

```bash
# 1. Stage the real run (see Step 7.1)
genomeclaw pipeline run --vcf $NEBULA_VCF --reference-root $REFS --run-dir $DERIVED/<run-id>
genomeclaw pipeline cyp2d6-call --bam $NEBULA_CRAM --run-dir $DERIVED/<run-id>
genomeclaw pipeline pgs-compute --pgs PGS000018 --vcf $NEBULA_VCF --reference-root $REFS \
    --run-dir $DERIVED/<run-id> --rationale '<rationale>' --question '<question>'

# 2. Full invariant sweep against the real derived store
cd packages/toolkit
GENOMECLAW_DERIVED_DIR=$DERIVED/CURRENT \
  uv run pytest tests/invariants tests/privacy tests/provenance tests/determinism -v

# 3. Live agent transcripts
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:<current-tag> OPENAI_API_KEY=... \
  uv run pytest tests/live_llm -v -m "story1 or story4 or story9"

# 4. SSRF runtime probe
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:<current-tag> \
  uv run pytest tests/invariants/test_invP002_ssrf_runtime_probe.py -v

# 5. Determinism (INV-R002): re-run the pipeline + diff the derived stores
genomeclaw pipeline run --vcf $NEBULA_VCF --reference-root $REFS --run-dir $DERIVED/<run-id-2>
duckdb $DERIVED/<run-id>/variants.duckdb 'EXPORT DATABASE'"'$EXPORT_1'"
duckdb $DERIVED/<run-id-2>/variants.duckdb 'EXPORT DATABASE'"'$EXPORT_2'"
diff -r $EXPORT_1 $EXPORT_2  # expect empty modulo declared non-determinism
```

---

## Completion Criteria

- [ ] Real-data end-to-end run completes in ≤4h30m (ingest + normalize + annotate + materialize + cyp2d6-call + pgs-compute).
- [ ] `pytest tests/invariants tests/privacy tests/provenance tests/determinism` green against the real derived store.
- [ ] All seven AC items from `spec.md` check off — AC1 through AC14 (numbering jumps where ACs were revised + retired).
- [ ] Three live agent transcripts captured + snapshot tests green (Stories 1, 4, 9).
- [ ] SSRF runtime probe green under full Landlock + seccomp + netns + OpenShell L7 proxy.
- [ ] `docs/reference/architecture.md`, `docs/reference/INVARIANTS.md`, `docs/reference/grand-plan.md`, `docs/reference/user-stories.md`, `README.md` reconciled with shipped code.
- [ ] No outbound calls observed in the SSRF + privacy-default tests except to the configured agent endpoint + host service.
- [ ] `docs/plans/active/mvp/development-plan.md` shows all 7 phases at Complete.
- [ ] `docs/plans/active/mvp/work-notes.md` carries a phase-7 close-out block.
- [ ] Plan moved from `docs/plans/active/mvp/` to `docs/plans/completed/mvp/`.

### Carry-forward follow-ups (out of scope for Phase 7; tracked as post-MVP)

- Slice E.4 (PRS validation study + pre-compute consent) — deferred per the methodological-review pass.
- Cyrius F4 (sex-info handling for chrX scoring) + F5 (`refs materialize` CLI) + F6 (CI gate on pgsc_calc pin bumps) — all per the 2026-05-22 EOD checkpoint's F-list.
- Story 10 (PRS) live re-stage against the post-Phase-6 PRS row — optional polish.
- AC7 warm-cache reproducibility (≤15 min wall on re-run with caches present) — closes the last unchecked AC of `prs-bootstrap-meta`; not blocking Phase 7.
