# Feature: PRS smoke iteration resilience

**Status**: Draft
**Created**: 2026-05-21
**Owner**: GenomeClaw engineering
**Related Plans**:
- Parent: [prs-bootstrap-meta](../prs-bootstrap-meta.md) Stage 3 cascade
- In-flight sibling: [prs-non-imputed-wgs](../prs-non-imputed-wgs/) (Phase 4 smoke v22 is the GREEN gate)
- Failure ledger source: [docs/plans/active/prs-non-imputed-wgs/work-notes.md](../prs-non-imputed-wgs/work-notes.md) (v22 through v22i)

---

## Goal

Close the four classes of brittleness that drove 8+ iterative failures in smoke v22's pre-success ledger (sampleset-naming regressions, NXF_SCRATCH-vs-bind-mount races, transient pgsc_calc bugs, external-drive/Colima/Docker infrastructure disconnects) so future PRS smokes complete or fail-fast with actionable diagnostics rather than burning multi-hour wall-clock on transient infra glitches.

## Background

Smoke v22 took **9 attempts** (v22, v22b, v22c, v22d, v22e, v22f, v22g, v22h ×2, v22i) before reaching matchmerge with a clean pipeline. Each attempt revealed a distinct gap; the gaps fall into four layers:

| Layer | Smokes | Cause |
|-------|--------|-------|
| **L1 — Tool-contract bugs** (wrapper code) | v22, v22b, v22f | Sampleset-naming (`.`, `_`), `process.scratch` directive not honored |
| **L2 — Tool-environment interaction** (config) | v22c, v22e | NXF_SCRATCH escapes bind-mount; match-rate threshold mis-calibrated |
| **L3 — Transient flakiness** (nondeterministic) | v22d | pgsc_calc heapq.merge KeyError (same code, different temp file ordering) |
| **L4 — Infrastructure / hardware** | v22g, v22h ×2 | External drive disconnect mid-run; Colima virtiofs stale FD; mount config lost on `colima restart` |

L1+L2 are already addressed by `prs-non-imputed-wgs` Phases 1.B, 2.B–E + their regression tests. **This plan closes L3 + L4** plus an L5 ("smoke-driver fragility" — the wrapper itself loses partial-progress state when SIGTERM cascades).

## Acceptance Criteria

- [ ] AC1: `genomeclaw host doctor --json` reports three new structural fields for smoke pre-flight: `colima_mount_visible: bool` (DooD-bound paths visible inside the daemon's VM), `external_drive_readable: bool` (test-read a known file from the bind-mount), `leftover_genomeclaw_containers: list[str]` (any container with label `genomeclaw-smoke=<...>` from a prior run).
- [ ] AC2: `bin/genomeclaw-prs-smoke` exits with rc=2 + actionable error if any pre-flight readiness field fails — BEFORE invoking the expensive Tier 1 / Tier 2 path. Smoke driver pre-flight should complete in ≤30 seconds.
- [ ] AC3: Smoke driver labels every docker run it issues with `genomeclaw-smoke=<utc-iso>`; cleanup pass at smoke completion (success OR failure) stops all containers with that label.
- [ ] AC4: Nextflow config (`_TMPDIR_REDIRECT_CONFIG` in `pgs.py`) gains `errorStrategy = 'retry'` + `maxRetries = 2` for known-transient pgsc_calc tasks (INTERSECT_VARIANTS at minimum); regression test asserts the directive is present.
- [ ] AC5: `compute_pgs`'s `RuntimeError` message on pgsc_calc rc != 0 includes BOTH stdout + stderr (today it surfaces only stderr's last line — the Nextflow update banner — burying the actual error in Nextflow's task .command.err files).
- [ ] AC6: Smoke driver traps SIGTERM/SIGINT to flush partial-progress state to `smoke.log` before exit (closes the v22g gap where a 1h22m run died with no record of which pgsc_calc tasks had completed).
- [ ] AC7: A short read-only watchdog probe re-runs every ~60s inside a long pgsc_calc run; mount-loss detection in ≤60s. The probe reads a canary file (e.g. `<raw_dir>/.canary`) staged at smoke start; failure flags a recovery cycle (AC9).
- [ ] AC8: `compute_pgs`'s pgsc_calc invocation includes `-resume` so a re-invocation against the same `work_dir` picks up from the last completed Nextflow task (skips work already done).
- [ ] AC9: The smoke driver runs a bounded recovery loop on mid-run mount loss: (a) cascade-kill the toolkit container; (b) wait until the host-side drive becomes stably readable for ≥30s (don't recover into a still-bouncing drive); (c) `colima stop` + `colima start --mount /Volumes/Genome_Work:w` (or whatever canonical args were persisted at install time); (d) re-invoke pgsc_calc with `-resume`. Recovery is bounded to `--max-recovery-attempts` (default 3); past that the smoke fails with a documented "drive too unstable" diagnostic.
- [ ] AC10: Recovery cycles are recorded as structured events in `<smoke-dir>/recovery.log` (one JSON line per cycle: timestamp, last-completed task, recovery duration). After smoke completion, the total recovery count is surfaced in `cli_envelope.json`.

## Applicable Invariants

- **INV-D003** Heavy scratch separated — the smoke pre-flight read-test stays in the scratch dir; no derived-store writes.
- **INV-D005 / D006 / D007** — the pre-flight checks exercise the canonical mount + shim seam; they're the same checks our path-crossing discipline already enforces, surfaced as doctor probes.
- **INV-P001** Privacy default — pre-flight checks read ONE small file from the bind-mount; no egress, no large reads.
- **INV-R001** Rebuildability — Nextflow's retry strategy MUST NOT mask determinism breakage. Retries are bounded (`maxRetries = 2`) + logged; if a task succeeds on retry, the row's `params_json` records `retry_count`.
- **INV-C002** CLI Output Contract — the new doctor fields are additive (no schema bump); the smoke driver's rc=2 pre-flight-failure path uses the existing typed error envelope.

## Proposed New Invariants

**None.** Each phase strengthens an existing invariant (mostly INV-R001 around rebuildability + INV-D003 around scratch placement) rather than introducing a new project-wide rule.

## Technical Requirements

### Source Data Inputs

- Test fixture for AC1: a known-readable file under `/Volumes/Genome_Work/genomeclaw/raw/` — the existing `MPNRGLQ2K.mm2.sortdup.bqsr.cram.crai` (small .crai sidecar; quick read) is suitable.
- Test fixture for AC4: a flaky-intersect synthetic input that triggers the `CHR:POS:A0:A1` KeyError reproducibly *(out of scope if a deterministic reproducer can't be found; document as "retry strategy verified empirically against v22d real-data smoke")*.

### Derived Outputs

- Smoke driver writes `<smoke-dir>/preflight.json` with the structural readiness check results.
- Smoke driver writes `<smoke-dir>/cleanup.log` recording every container it stops at smoke-completion time.

### Schema / Migration Impact

- `host doctor`'s output schema (`cli_output_schema_version`) gains the three new fields additively. No version bump per INV-C002.
- `pgs_scores.params_json` (already a free-form JSON column) gains optional `retry_count: int` when Nextflow retried a task.

### Pipeline / Workflow Impact

```
Existing smoke flow:
  smoke driver → INV-D001 pre-snapshot → Tier 1 → prs_compute_PGS000018 (~30-90 min)

New smoke flow:
  smoke driver
    → preflight (≤30s):
       - colima_mount_visible
       - external_drive_readable
       - leftover_genomeclaw_containers (auto-cleanup if any)
    → INV-D001 pre-snapshot
    → Tier 1
    → prs_compute_PGS000018 (with Nextflow retry strategy for transient tasks)
    → on-exit cleanup (label-based docker stop)
```

### Agent / UX Impact

- No agent-facing changes. PRS computation user-experience is unchanged on the happy path; the difference is failure-mode UX (faster, more diagnostic).
- `genomeclaw doctor`'s output gains three new informational fields; agent doesn't consume these directly.

### External Dependencies

- Docker labels API (existing).
- Nextflow `errorStrategy` directive (existing).
- macOS / Colima behavior around virtiofs stale FDs (the operational reality the plan documents but cannot fix at the framework layer).

## Privacy & Safety Considerations

- **Boundary scan**: pre-flight checks read ONE known sidecar file from the existing bind-mount. No new egress; no new path crosses any trust boundary.
- **Default-off remote calls**: unchanged.
- **Redaction surface**: unchanged.
- **Clinical escalation**: unchanged. The smoke driver is a development tool; doesn't surface in user-facing reports.

## Out of Scope

- **Internal-SSD staging for long pgsc_calc runs**: post-v22-ledger reality check (work_dir peaks at ~58 GB during a run vs ~30 GB free internal SSD on the project owner's setup) makes the originally-sketched F9 design infeasible. Bundle-only staging (16 GB) is feasible but doesn't remove mid-run external-drive write I/O. Phase 4 (mid-run recovery + Nextflow resume) is the more targeted L4 fix; F9 stays open for future hardware setups with bigger internal SSDs.
- **Singularity profile for pgsc_calc**: would avoid the DooD-related complications altogether. Bigger change (image build path, conventions dataclass). Tracked as "F10: pgsc_calc Singularity profile."
- **CI integration for the real-data smoke**: per the meta-plan's open follow-ups list ("CI pipeline"); separate effort.
- **PG-decline classifier wiring against the empirical match rate**: pgsc_calc-matchmerge's 0.45 threshold is enforced at the wrapper layer; the agent-facing decline rendering is already in `prs-input-coverage-fill` Phase 3b.
- **Auto-recovery from Colima itself crashing** (vs. a stale mount): Colima crash is distinct from a virtiofs glitch. The recovery loop in AC9 assumes Colima is restartable from the host; if Colima itself is dead (e.g. VZ.framework fault), the recovery still triggers `colima start` which handles the full bring-up. But debugging WHY Colima crashed is out of scope.

## Dependencies

- `prs-non-imputed-wgs` Phase 4 smoke v22 must reach matchmerge (validates that all L1+L2 fixes are stable). v22i (in flight 2026-05-21) is the canonical run to verify before this plan starts.
- Colima with `--mount /Volumes/Genome_Work:w` is the canonical development setup; pre-flight checks assume that mount pattern.

## Open Questions

- [ ] Q1: Should the preflight read-test exercise EVERY canonical bind-mount path (raw, reference, derived, scratch) or just one representative? *Working assumption*: one representative (`raw/` since that's what INV-D001 needs first); if it's broken, the others are likely broken too.
- [x] Q2: Should the periodic re-check (AC7) be a separate process or a heartbeat from the smoke driver? *(Resolved 2026-05-21)*: heartbeat from the smoke driver itself — a background bash loop that probes a canary file every 60s. Simpler than a separate process; runs only for the lifetime of the smoke; touches no new IPC surface.
- [ ] Q3: What's the right behavior when `leftover_genomeclaw_containers` is non-empty: auto-stop, or warn-and-abort? *Working assumption*: auto-stop with a printed list (smoke driver is a development tool; warn-and-abort would just add a manual step).
- [ ] Q4: Where does the smoke driver get the canonical `colima start` args? *(Open; AC9 design decision)*: the user's incantation is `colima start --cpu 2 --memory 12 --disk 40 --mount /Volumes/Genome_Work:w` — these aren't reliably persisted in `~/.colima/default/colima.yaml` (we've observed it get reset to `mounts: []` between sessions). *Working assumption*: `genomeclaw host setup` persists the canonical args to `~/.config/genomeclaw/colima.json` (a new file); the smoke driver's recovery cycle sources from there. If the file is missing, recovery falls back to "manual remediation required" (smoke fails with the canonical incantation printed as a hint).
- [ ] Q5: How does `-resume` interact with our `params_json` provenance? *(Open; AC8/INV-R001 design decision)*: a Nextflow run with `-resume` that skips N cached tasks plus runs M fresh tasks should record `retry_count` per task AND a top-level `resume_count` for how many invocations were needed. *Working assumption*: surface `resume_count` in `pgs_scores.params_json`; Phase 3's existing `retry_count` parser extends to track this.
