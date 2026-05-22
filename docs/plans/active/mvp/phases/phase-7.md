# Phase 7: End-to-end MVP demo + invariant sweep + plan close

**Status**: Pending — close sessions 1 + 2 scoped 2026-05-22
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)
**Spec**: [spec.md § AC1–AC14](../spec.md)

---

## Objective

Drive the full ingest → normalize → annotate → materialize → CYP2D6 → PharmCAT → PRS → live-agent loop against the project owner's real Nebula VCF + CRAM into **one canonical run-dir**, sweep every `INV-xxx` against that run-dir, verify the SSRF policy preset holds under sandbox-runtime L7 probing, reconcile any reference-doc drift, and move the MVP plan to `completed/`.

Phase 7 is **not** about writing new pipeline code — Phases 1–6 are responsible for that. It's about driving the assembled system end-to-end in one consolidated run, confirming the invariant tests pass together rather than only in isolated test files, and closing the plan paperwork.

Three sub-decisions pinned 2026-05-22 (see [development-plan.md § Open Risks](../development-plan.md#open-risks--follow-ups)):

1. **Step 7.1 — full re-run** (not augment-existing). One canonical run-dir simplifies every downstream test + INV-R002 (rebuildability / determinism) is meaningful only against a fresh run.
2. **Step 7.4 — static + sandbox L7 SSRF probe** (not full Landlock+seccomp+netns). The MVP's promise is the OpenShell L7 + policy-preset shape, both of which are testable in the sandbox image. Full kernel-level isolation probing (Landlock+seccomp+netns) is a real research project tied to OpenShell version specifics; capture as a post-MVP follow-up.
3. **Step 7.3 — reuse the 4 Slice F live tests** (skip Story 1 authoring). Stories 2 / 4 / 9 / 10 already pass against gpt-5.5 + the sandbox image; Story 1 ("any actionable findings?") is substantially covered by Story 4's PGx path. Re-run them against the consolidated run-dir for integration coverage.

## Two-session structure

| Session | Steps | Wall | Foreground | Goal |
|---------|-------|------|------------|------|
| **Close 1** | 7.1 (full re-run, backgroundable) + 7.2 (invariant sweep against run-dir) + 7.3 (re-run live tests against canonical run-dir) | ~5-6 hr wall, ~1-2 hr foreground | Kick off long run, do reconciliation work while it runs | Canonical run-dir + all invariants green against real data |
| **Close 2** | 7.4 (static + sandbox L7 SSRF probe authored + run) + 7.5 (final doc drift + plan move-to-completed + final commit + push) | ~2-3 hr | Author the probe test, run it, doc sweep, plan move, final commit/push | MVP plan in completed/; project enters post-MVP state |

Two sessions is the cleanest split — close session 1's long run isn't worth interleaving with close session 2's authoring work.

## Scope Boundaries

- **In scope**:
  - One end-to-end pipeline run against the project owner's real Nebula VCF + CRAM landing in **one canonical run-dir** at `/Volumes/Genome_Work/genomeclaw/derived/<run-id>/`. Sequence: `pipeline run` → `pipeline cyp2d6-call` → `pipeline pharmcat` → `pipeline pgs-compute`.
  - Full invariant sweep against the canonical run-dir + INV-R002 (determinism diff via a second run).
  - Re-run of the 4 Slice F live tests (Stories 2 / 4 / 9 / 10) against the canonical run-dir's findings + variants + coverage_qc + pgs_scores rows.
  - **Sandbox-L7 SSRF probe** authored as `tests/invariants/test_invP002_ssrf_runtime_probe.py`: parameterised attempts to reach un-allowlisted hosts/ports from inside the sandbox; expect rejection at the OpenShell L7 proxy or the netns barrier (whichever fires first). Does NOT require full Landlock+seccomp setup — verifies what the MVP actually promised.
  - **Doc drift sweep**: reconcile any reference-doc drift surfaced by the canonical run + final paperwork (development-plan.md / work-notes.md / spec.md / phase-7.md status closures).
  - **Plan close-out**: move `docs/plans/active/mvp/` → `docs/plans/completed/mvp/`. Final commit + push.
- **Out of scope**:
  - **Full Landlock+seccomp+netns SSRF probe**. Captured as a post-MVP follow-up (depends on OpenShell version specifics; warrants its own short plan).
  - **Story 1 live test authoring** — substantially covered by Story 4. Captured as a post-MVP follow-up if a discrete Story 1 contract surfaces value.
  - Any new pipeline subcommand, schema column, evidence kind, or invariant.
  - Validation studies, eval harnesses, additional PRS traits, additional PharmCAT guideline branches (DPWG / FDA).
  - Cyrius / PharmCAT outside-call code — Slice D / D' deliverables. Phase 7 consumes them.

## Invariants Enforced in This Phase

This phase **re-exercises** every canonical invariant in a single sweep against the canonical run-dir rather than introducing new tests. The list below is the live-sweep checklist; each invariant must have at least one passing test that touched the real run's derived store.

- **INV-D001** Raw genomic files source-of-truth — VCF + CRAM SHA256 unchanged after the full run (compare digests pre / post).
- **INV-D002** Sandbox image has no bioinformatics binaries — re-run sandbox image inspection.
- **INV-D003** Heavy scratch separated from authoritative outputs — preflight assertion at each orchestrator entry; verify `_scratch/` and `derived/` are non-nested on the project owner's drive.
- **INV-D005 / INV-D006 / INV-D007 / INV-D008** Path-crossing discipline — `test_invD00*` files green against the real run's argv emissions.
- **INV-E001** Every emitted finding carries `evidence_ref` — assert against `findings` rows in the canonical derived store (~9 PGx findings + the PRS finding + whatever Phase 4 emitted).
- **INV-P001** Privacy default — sandbox flow with default config produces no outbound calls beyond `host.openshell.internal` + `inference.local` (re-run `test_invP001_*.py`).
- **INV-P002** Minimal-sufficient JSON + policy preset shape — `test_invP002_*.py` green; **sandbox L7 SSRF probe** confirms runtime enforcement, not just static config.
- **INV-R001** Provenance columns on every derived row — assert against the real `variants` / `pgs_scores` / `findings` / `coverage_qc` tables.
- **INV-R002** Rebuildability — re-run the pipeline against the same VCF + same reference + same tool versions; diff the derived stores; expect byte-equivalent output modulo declared non-determinism.
- **INV-C001** v1.7 — clinical-actionable findings carry `clinical_escalation`; PRS findings are `clinical-non-actionable`; PRS decline pattern fires on an immature-trait question; snapshot tests over the 4 Slice F live transcripts pass.
- **INV-T001** Tool-conventions dataclasses match pinned versions — `test_invT001_tool_conventions_exist.py` green; the post-Phase-6 dataclass set (PgscCalc + Cyrius + PharmCAT) all show `verified_against_version` matching `_versions.py` pins.
- **INV-A001 / INV-A002 / INV-A003** Agent memory provenance + reasoning floor + PRS compute provenance — re-run `live_llm` tests against the canonical run-dir's findings; assert `executionTrace.thinking` populated on the Story 9 + Story 4 turns and a memory note landed before each reply.

---

## Close Session 1

### Step 7.1 — Stage the canonical real-data run

**Pre-flight checks** (10 min):

1. Confirm `/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/` carries the canonical VCF + CRAM + indexes.
2. Confirm the reference layout under `/Volumes/Genome_Work/genomeclaw/reference/` is current — VEP cache + LOFTEE + AlphaMissense + gnomAD-exomes + dbSNP + gnomAD-constraint + pgs_catalog_ancestry + GRCh38 fasta (for PharmCAT's preprocessor).
3. Confirm both Docker images are current: `genomeclaw/toolkit:slice-d-prime` (6.35 GB) + `genomeclaw/sandbox:slice-d-prime` (2.61 GB).
4. Capture SHA256 of the input VCF + CRAM into a pre-run log for the post-run INV-D001 check.

**Run sequence** (~4h45m – 5h30m wall, mostly background):

```bash
export GENOMECLAW_IMAGE=genomeclaw/toolkit:slice-d-prime
RUN_ID="$(date -u +%Y-%m-%dT%H-%M-%SZ)-phase7"
RUN_DIR="/mnt/genomeclaw/derived/${RUN_ID}"

# 1. ingest + normalize + annotate + materialize (~4h09m per Phase 4 close)
bin/genomeclaw pipeline run \
  --vcf /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz \
  --reference-root /mnt/genomeclaw/reference \
  --run-dir "${RUN_DIR}"

# 2. Cyrius CYP2D6 (~170s)
bin/genomeclaw pipeline cyp2d6-call \
  --bam /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram \
  --sample-id MPNRGLQ2K \
  --reference-fasta /mnt/genomeclaw/reference/grch38/ncbi-2014/grch38.fa.gz \
  --run-dir "${RUN_DIR}"

# 3. PharmCAT PGx (~135s)
bin/genomeclaw pipeline pharmcat \
  --vcf /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz \
  --cyp2d6-diplotype-json "${RUN_DIR}/cyp2d6_diplotype.json" \
  --reference-fasta /mnt/genomeclaw/reference/grch38/ncbi-2014/grch38.fa.gz \
  --run-dir "${RUN_DIR}"

# 4. PGS Catalog PRS — agent-curated rationale (e.g. PGS000018 for CAD)
bin/genomeclaw pipeline pgs-compute \
  --pgs PGS000018 \
  --vcf /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz \
  --reference-root /mnt/genomeclaw/reference \
  --rationale '<rationale per INV-A003 — see prior smoke v23 for canonical form>' \
  --question 'phase-7 end-to-end smoke against the canonical run-dir' \
  --work-dir /mnt/genomeclaw/_scratch/pgs-work-phase7 \
  --run-dir "${RUN_DIR}"

# 5. Update CURRENT symlink atomically
bin/genomeclaw runs activate "${RUN_ID}"
```

**Post-run sanity checks** (5 min):

- Confirm input VCF + CRAM SHA256 unchanged (INV-D001).
- `duckdb ${DERIVED}/CURRENT/variants.duckdb 'SELECT COUNT(*) FROM variants'` — expect 4.87M rows.
- `SELECT COUNT(*) FROM findings WHERE tool = 'pharmcat'` — expect ~9 rows.
- `SELECT * FROM pgs_scores` — expect 1 row (PGS000018).
- `SELECT * FROM coverage_qc LIMIT 5` — expect ~20,000 gene-level rows.

### Step 7.2 — Run the invariant sweep against the canonical run-dir

```bash
cd packages/toolkit
GENOMECLAW_DERIVED_DIR=/Volumes/Genome_Work/genomeclaw/derived/CURRENT \
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:slice-d-prime \
  uv run pytest tests/invariants tests/privacy tests/provenance tests/determinism -v
```

Reconcile any failures: a stale fixture (most likely — the canonical run-dir carries shapes the synthetic fixtures don't cover) gets widened to admit both. A real bug gets a one-line fix or a follow-up plan, not a phase-7 commit.

### Step 7.3 — Re-run the 4 Slice F live tests against the canonical run-dir

The 4 live tests currently stage their own synthetic findings via `tests/_live_smoke/staging.py`. For Phase 7's integration coverage, stage them against the **canonical run-dir's actual findings** instead — verifies the agent's prose against real data.

**Option A** (recommended): Add a `--against-run-dir <path>` opt-in to the staging helper that, if set, points the host service at the canonical run-dir instead of staging synthetic fixtures. Re-run the 4 tests.

**Option B** (simpler): Keep the synthetic staging + just re-run as-is to confirm no regressions post-sandbox-rebuild.

```bash
export OPENAI_API_KEY=$(grep '^OPEN_AI_API_KEY=' .env | cut -d= -f2-)
export GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:slice-d-prime

uv run pytest \
  tests/integration/test_live_story2_introspection_snapshot.py \
  tests/integration/test_live_story4_clopidogrel_snapshot.py \
  tests/integration/test_live_story9_caffeine_snapshot.py \
  tests/integration/test_live_story10_cad_prs_snapshot.py \
  -v
```

Cost: ~$1-2 + ~15 min wall (4 turns × ~3-4 min each). Capture the transcripts into `docs/reference/transcripts/phase-7/` for the close-out narrative.

### Step 7.2 — INV-R002 determinism check (close session 1 finale)

Re-run the full pipeline (steps 1-4 of Step 7.1) into a **second** run-dir. Diff the two stores:

```bash
RUN_ID_2="$(date -u +%Y-%m-%dT%H-%M-%SZ)-phase7-rerun"
# Re-run all 4 commands above against RUN_DIR_2 = /mnt/genomeclaw/derived/${RUN_ID_2}

# Diff via duckdb's EXPORT DATABASE
duckdb $RUN_DIR/variants.duckdb 'EXPORT DATABASE '"'$EXPORT_1'"
duckdb $RUN_DIR_2/variants.duckdb 'EXPORT DATABASE '"'$EXPORT_2'"
diff -r $EXPORT_1 $EXPORT_2  # expect empty modulo declared non-determinism (timestamps)
```

Document any non-determinism in `work-notes.md` (expected: `created_at` timestamps differ on every row; the actual data values must match byte-for-byte).

**Close session 1 done when**: canonical run-dir exists at `derived/CURRENT/`, all invariant tests green against it, 4 live tests pass, INV-R002 diff is empty modulo timestamps.

---

## Close Session 2

### Step 7.4 — Sandbox-L7 SSRF probe (Phase-5-deferred work, scoped down)

**Author** `tests/invariants/test_invP002_ssrf_runtime_probe.py`:

The probe enumerates (host, port, expected-outcome) tuples and attempts a connection from inside the running sandbox container against each. Expected outcomes:

| Target | Expected |
|--------|----------|
| `host.openshell.internal:8643` (the host service) | ALLOW |
| `host.openshell.internal:8644` (un-allowlisted port on the same host) | REJECT |
| `192.168.1.1:80` (un-allowlisted RFC 1918 host) | REJECT |
| `example.com:443` (public internet, non-allowlisted) | REJECT |
| `1.1.1.1:53` (public internet, non-allowlisted) | REJECT |

The probe uses `curl --max-time 2` from inside the sandbox; expected REJECTs return non-zero with a clear connection-refused / timeout / proxy-blocked signal. Expected ALLOW returns 200 (or the actual host-service response).

**Run**:

```bash
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:slice-d-prime \
  uv run pytest tests/invariants/test_invP002_ssrf_runtime_probe.py -v
```

**Scope**: this is the sandbox-L7 + policy-preset enforcement check, NOT full kernel-level isolation (Landlock+seccomp+netns). The latter is captured as a post-MVP follow-up plan.

### Step 7.5 — Documentation drift sweep + plan close

1. **architecture.md drift recon** — verify the diagrams + endpoint sketches match the canonical run-dir's shape; any Phase-7-discovered drift lands here. Most drift was reconciled during the 2026-05-22 Phase-6 close sweep; expect minor reconciliation only.
2. **INVARIANTS.md** — verify version stamp + Invariant Index match the latest invariants; no new invariants expected (Phase 7 is exercise, not introduction).
3. **grand-plan.md** — mark Horizons 4 (Cautious reporting) + 5 (Pharmacogenomics) as Delivered if they aren't already; advance deferred-decision rows.
4. **user-stories.md** — mark resolved gap-analysis items in the canonical run-dir's findings shape.
5. **README.md** — verify the Getting Started flow matches the actual subcommand surface; reconcile any drift.
6. **development-plan.md** — final progress table; all 7 phases at Complete; final 2026-XX-XX close date on each row.
7. **work-notes.md** — phase-7 close-out block (close session 1 + close session 2 narratives, the canonical run-dir's path, final test counts, the INV-R002 determinism-diff outcome).
8. **phase-7.md** (this file) — Status → Complete, Completed → close-session-2 date.
9. **Move** `docs/plans/active/mvp/` → `docs/plans/completed/mvp/`.
10. **Final commit** capturing the move + the final paperwork.
11. **Push** to origin/main.

---

## Implementation Details

### Tracing what actually runs in close session 1

Phase 7 is the first place every `INV-xxx` test has the canonical run-dir available. Expect 1–3 invariant tests to fail-then-widen on first pass: the real data carries shapes synthetic fixtures don't cover (e.g., the `coverage_qc` table has ~20,000 gene-level rows vs. the fixture's 7; the `findings` table has the 9 Cyrius+PharmCAT rows plus the PRS row plus Phase-4's findings rather than the fixture's 1-3 rows). Widening means admitting the real shape, not regressing on the invariant.

### Wall-clock budget refinements

Phase 4 closed at 4h08m58s end-to-end (ingest + normalize + annotate + materialize). Slice D (cyp2d6-call) added 170s. Slice D' (PharmCAT) added 135s. Slice E (pgs-compute) adds ~25-30 min including the ancestry-projection step. Total close-session-1 budget:

- Pipeline run: ~4h09m
- cyp2d6-call: ~3 min
- pharmcat: ~3 min
- pgs-compute: ~25-30 min
- **End-to-end: ~4h40m – 4h50m**

Add ~30 min for invariant-sweep reconciliation + ~15 min for the 4 live-test runs + ~30 min for the INV-R002 second run = **~5h45m total close-session-1 wall**, ~1-2 hr foreground attention.

### SSRF probe — scoped trade-offs

The Phase-5-deferred original was "Landlock+seccomp+netns + OpenShell L7 proxy" — full kernel-level isolation verification. The MVP's actual contract is the OpenShell L7 proxy + the policy-preset shape; both are testable in the sandbox image without kernel-level setup.

What the scoped probe DOES verify:
- The sandbox's network namespace is constrained
- The OpenShell L7 proxy rejects non-allowlisted hosts
- The policy preset's enumeration matches the runtime behavior

What the scoped probe DOES NOT verify:
- Landlock filesystem isolation (out of scope; deferred)
- seccomp syscall filtering (out of scope; deferred)
- Cross-process namespace escape (out of scope; deferred)

These deferrals are explicit + intentional. The post-MVP plan that takes on the full Landlock/seccomp probing should also tie OpenShell version pinning into INV-T001 (treat the OpenShell runtime as another externally-pinned tool).

### Privacy / egress notes

Phase 7 introduces **no new egress surfaces**. The four documented surfaces (agent → OpenAI managed by OpenShell L7 proxy; plugin → host service; `genomeclaw refs fetch` → annotation sources; `pgsc_calc` → PGS Catalog) are exercised here for the last time as part of the MVP close-out. Story 9 re-stage may trigger `web_search` if the agent's memory has aged out — that is the AC13 path (a fresh `web_search` call when memory is past freshness date), expected, and recorded in the transcript.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/mvp/phases/phase-7.md` | THIS FILE | Authoring + tracking the close-out phase |
| `docs/reference/transcripts/phase-7/story-2.md` | CREATE | Story 2 introspection transcript |
| `docs/reference/transcripts/phase-7/story-4.md` | CREATE | Story 4 clopidogrel/CYP2C19 PGx transcript |
| `docs/reference/transcripts/phase-7/story-9.md` | CREATE | Story 9 caffeine lifestyle transcript |
| `docs/reference/transcripts/phase-7/story-10.md` | CREATE | Story 10 CAD PRS transcript |
| `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` | CREATE | Phase-5-deferred SSRF probe (scoped to sandbox-L7) |
| `packages/toolkit/tests/_live_smoke/staging.py` | MODIFY (option A) | Add `--against-run-dir` opt-in to point at canonical run-dir |
| `docs/reference/architecture.md` | MODIFY (drift) | Reconcile any post-canonical-run drift |
| `docs/reference/INVARIANTS.md` | MODIFY (close-out) | Version stamp + Invariant Index sweep |
| `docs/reference/grand-plan.md` | MODIFY (close-out) | Horizons 4 + 5 Delivered; deferred-decision rows |
| `docs/reference/user-stories.md` | MODIFY (close-out) | Final gap-analysis reconciliation |
| `README.md` | MODIFY | Final flow reconciliation |
| `docs/plans/active/mvp/development-plan.md` | MODIFY | Final progress table; all phases Complete |
| `docs/plans/active/mvp/work-notes.md` | MODIFY | Phase-7 close-session-1 + close-session-2 blocks |
| `docs/plans/active/mvp/` | MOVE | → `docs/plans/completed/mvp/` |

---

## Verification

Close session 1:

```bash
# 1. Stage the canonical real-data run (Step 7.1)
bin/genomeclaw pipeline run --vcf $NEBULA_VCF --reference-root $REFS --run-dir $DERIVED/<run-id>
bin/genomeclaw pipeline cyp2d6-call --bam $NEBULA_CRAM --sample-id MPNRGLQ2K \
    --reference-fasta $REF_FASTA --run-dir $DERIVED/<run-id>
bin/genomeclaw pipeline pharmcat --vcf $NEBULA_VCF \
    --cyp2d6-diplotype-json $DERIVED/<run-id>/cyp2d6_diplotype.json \
    --reference-fasta $REF_FASTA --run-dir $DERIVED/<run-id>
bin/genomeclaw pipeline pgs-compute --pgs PGS000018 --vcf $NEBULA_VCF --reference-root $REFS \
    --run-dir $DERIVED/<run-id> --rationale '<rationale>' --question '<question>' \
    --work-dir $SCRATCH/pgs-work-phase7

# 2. Invariant sweep
cd packages/toolkit
GENOMECLAW_DERIVED_DIR=$DERIVED/CURRENT GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:slice-d-prime \
  uv run pytest tests/invariants tests/privacy tests/provenance tests/determinism -v

# 3. 4 Slice F live tests
export OPENAI_API_KEY=$(grep '^OPEN_AI_API_KEY=' /Users/hugi/GitRepos/GenomeClaw/.env | cut -d= -f2-)
uv run pytest \
  tests/integration/test_live_story2_introspection_snapshot.py \
  tests/integration/test_live_story4_clopidogrel_snapshot.py \
  tests/integration/test_live_story9_caffeine_snapshot.py \
  tests/integration/test_live_story10_cad_prs_snapshot.py -v

# 4. INV-R002 determinism diff: re-run + diff stores
# (full pipeline run sequence again into RUN_DIR_2)
duckdb $DERIVED/<run-id>/variants.duckdb 'EXPORT DATABASE '"'$EXPORT_1'"
duckdb $DERIVED/<run-id-2>/variants.duckdb 'EXPORT DATABASE '"'$EXPORT_2'"
diff -r $EXPORT_1 $EXPORT_2  # expect empty modulo timestamps
```

Close session 2:

```bash
# 5. SSRF probe (sandbox-L7 scope)
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:slice-d-prime \
  uv run pytest tests/invariants/test_invP002_ssrf_runtime_probe.py -v

# 6. Final paperwork + plan move
git mv docs/plans/active/mvp docs/plans/completed/mvp
git commit -m 'docs(mvp): close Phase 7 + move plan to completed/'
git push origin main
```

---

## Completion Criteria

### Close session 1 done when

- [ ] Canonical run-dir at `/Volumes/Genome_Work/genomeclaw/derived/<run-id>/` carries: 4.87M-row `variants` table, ~20,000-row `coverage_qc` table, ~9-row `pharmcat`-tool `findings`, 1-row `pgs_scores`, `cyp2d6_diplotype.json`, `manifest.json`, `provenance.json`, plus the Phase 4 v0.2 annotation columns.
- [ ] `CURRENT` symlink atomically updated.
- [ ] Input VCF + CRAM SHA256 unchanged after the full run (INV-D001).
- [ ] `pytest tests/invariants tests/privacy tests/provenance tests/determinism` green against the canonical run-dir.
- [ ] 4 Slice F live tests pass (Stories 2 / 4 / 9 / 10) against the canonical run-dir's findings.
- [ ] INV-R002 second-run diff is empty modulo timestamps.
- [ ] 4 transcripts captured in `docs/reference/transcripts/phase-7/`.

### Close session 2 done when

- [ ] SSRF runtime probe authored + green (sandbox-L7 scope).
- [ ] `docs/reference/architecture.md`, `docs/reference/INVARIANTS.md`, `docs/reference/grand-plan.md`, `docs/reference/user-stories.md`, `README.md` reconciled with canonical-run-dir shape.
- [ ] All 14 AC items from `spec.md` check off (AC1–AC14; numbering jumps where ACs were revised + retired).
- [ ] No outbound calls observed in the SSRF + privacy-default tests except to the configured agent endpoint + host service.
- [ ] `docs/plans/active/mvp/development-plan.md` shows all 7 phases at Complete with close dates.
- [ ] `docs/plans/active/mvp/work-notes.md` carries close-session-1 + close-session-2 blocks.
- [ ] `docs/plans/active/mvp/phases/phase-7.md` Status → Complete with Completed date.
- [ ] Plan moved from `docs/plans/active/mvp/` to `docs/plans/completed/mvp/`.
- [ ] Final commit + push to `origin/main`.

### Phase-7-companion plans landed in close session 1

- **[from-scratch-setup-protections](../../from-scratch-setup-protections/)** *(2026-05-23)* — closes two regressions the canonical real-data run surfaced: (a) `bin/genomeclaw`'s `_dood_scan_args` was missing `pgs-compute` → bare invocation fails the path-crossing pre-flight (fixed + meta-invariant test landed); (b) toolkit image was missing `perl-dbd-sqlite` → LOFTEE plugin silently NULL-ed every `loftee_lof` row (Dockerfile fix + `perl -M`-probe test landed). INVARIANTS.md → v1.15 with scope clarifications on INV-D006 + INV-T001.

### Carry-forward follow-ups (out of scope for Phase 7; tracked as post-MVP)

- **Full Landlock+seccomp+netns SSRF probe** — author a dedicated post-MVP plan that ties OpenShell version pinning into INV-T001 + verifies kernel-level isolation primitives. The MVP's scoped probe verifies the L7 + policy-preset surface; the full probe verifies the syscall + filesystem isolation surface.
- **Story 1 live test** — discrete "any actionable findings?" test if a contract gap surfaces beyond what Story 4 already covers.
- Slice E.4 (PRS validation study + pre-compute consent) — deferred per the methodological-review pass.
- Cyrius F4 (sex-info handling for chrX scoring) + F5 (`refs materialize` CLI) + F6 (CI gate on pgsc_calc pin bumps) — all per the 2026-05-22 EOD checkpoint's F-list.
- PharmCAT DPWG + FDA guideline branches — currently CPIC-only; expand if user-actionable recommendations surface downstream.
- AC7 warm-cache reproducibility (≤15 min wall on re-run with caches present) — closes the last unchecked AC of `prs-bootstrap-meta`; not blocking Phase 7.
