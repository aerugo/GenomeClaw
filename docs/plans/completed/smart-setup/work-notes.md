# Smart setup — work notes

**Feature**: state-detection-driven `genomeclaw-prep setup`
**Started**: 2026-05-11
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## Session log

> Append-only. Newest entries at the bottom.

### 2026-05-11 — Plan authored

**Context review completed**:
- Read [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) v1.6 — confirmed applicable invariants are `INV-D001`, `INV-D003`, `INV-R001`. No new invariants needed.
- Re-read [prep/setup/](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/) modules — confirmed the existing structure has clean seams for a state-driven dispatcher (`Platform` protocol, `_yaml_writer.py` round-tripper, `SetupPlan` dataclass).
- Re-read the [cram-scratch-strategy post-close recovery recipe](../../completed/cram-scratch-strategy/work-notes.md#post-close-colima-recovery-recipe-added-2026-05-11) — confirmed every symptom 1–5 is either a state this plan auto-heals or an environmental quirk this plan documents away.

**Key insights**:
- The colima.yaml `mounts:` drift is the most common failure mode. After `colima delete && colima start` (the standard recovery from a wide class of colima issues), the mounts block is empty and every pipeline run fails at docker bind-mount. Smart-setup makes "after colima delete, just run setup again" a one-line recovery.
- The destructive flow already has the right shape (validation → preview → typed-confirm → execute). The new code is mostly the *dispatcher* that decides whether to invoke it.
- The new action handlers (`reconfigure_colima`, `recreate_layout`, `start_colima`) are small (~30 lines each) because the underlying machinery (`Platform` protocol, audit-log helpers) is already in place.

**Completed today**:
- [x] [spec.md](spec.md) — goal + 7 defined states + acceptance criteria + open questions resolved
- [x] [development-plan.md](development-plan.md) — solution design + single-phase plan + testing strategy
- [x] [work-notes.md](work-notes.md) — this file
- [ ] [phases/phase-1.md](phases/phase-1.md) — next

**Decisions made**:
- **One-phase plan, not multi-phase**: the work is structurally one slice (state inspection + dispatcher + new action handlers). Splitting into multiple phases would just slow review. ~18 tests, ~1.5–2 hours active.
- **`setup` entry point unchanged**: `bin/genomeclaw-prep setup` still invokes the same CLI; the smart-dispatch is internal. No new flag mode (rejected `--reconfigure-only` in favor of state-driven).
- **"Nebula missing" fails fast** if `--source` not provided, rather than auto-prompting. The fresh-install path already handles the interactive prompt; reusing it in the recovery path conflates two scenarios.
- **`colima.yaml canonical` check is presence-not-equality**: as long as the canonical four mounts are present + memory ≥ 4 GB, drift detection passes. The user may have added their own mounts; the toolkit doesn't strip them.
- **Doctor extension deferred**: a doctor that surfaces colima drift before pipeline runs is complementary but out of scope. Smart-setup auto-heals; doctor would proactively warn. ~30 min when filed.

**Blockers / issues**: none yet.

**Next steps**:
1. Author [phases/phase-1.md](phases/phase-1.md) with the TDD scaffold (RED test list, GREEN steps, files table, completion criteria).
2. Implement state inspection + dispatcher + handlers per Phase 1.
3. Gate: host venv full suite + in-image gate (the existing setup_execute tests + the new smart-setup tests).
4. Resume MVP Phase 4C completion (W4 onward) after this plan ships.

### 2026-05-11 — Phase 1 RED → GREEN → smoke; plan close

**Step 1.1 — RED**: wrote 18 tests across three files (6 inspect + 7 dispatch + 5 integration). Confirmed RED state: 18/18 failed with `ImportError` / `AttributeError` for the not-yet-implemented `inspect_system`, `decide_action`, `SetupAction`, `SystemState`, `run_smart`.

**Step 1.2 — GREEN**: implemented in ~2 hours active.

- [`inspect.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/inspect.py): `SystemState` dataclass + `inspect_system(*, platform)`. Pure read-only function: stats the filesystem; `platform.list_volumes()` + `colima_status()`; parses `~/.colima/default/colima.yaml` via `yaml.safe_load`. Skips layout / nebula / colima inspection when partition is missing or wrong-format (those states already dispatch FULL_DESTRUCTIVE; further inspection is wasted work).
- [`dispatch.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/dispatch.py): `SetupAction` StrEnum + `decide_action(state) → (action, rationale)`. Pure function; decision tree of 7 cascading if-checks in order. Rationale strings are short + human-readable.
- [`_recreate_layout.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/_recreate_layout.py): `mkdir -p` the missing subdirs; append a `recreate_layout` audit event. Doesn't touch `raw/` (`INV-D001`).
- [`_start_colima.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/_start_colima.py): single `platform.colima_start()` + audit event.
- [`_reconfigure_colima.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/_reconfigure_colima.py): reuses [`_yaml_writer.write_colima_yaml`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/_yaml_writer.py) for the mounts portion (preserves user's other mounts); new `_bump_memory_if_needed(min_gb=8)` helper for the memory bump (production threshold = 8 GB, higher than the 4 GB inspection threshold to give margin); `colima_stop → colima_start` to apply; audit event records `{drift_detected, memory_before, memory_after}`.
- [`run.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/run.py): `run_smart(platform=None)` entry point. Prints chosen action + rationale; dispatches; returns rc. Returns 2 for FULL_DESTRUCTIVE / RESTAGE_NEBULA (the CLI falls through).
- [`cli.py`](../../../packages/toolkit/src/genomeclaw_toolkit/cli.py): `_run_setup` now calls `run_smart` first; falls through to `run_interactive` only when smart returns 2 (FULL_DESTRUCTIVE state). Single `bin/genomeclaw-prep setup` entry point handles all states.
- [`__init__.py`](../../../packages/toolkit/src/genomeclaw_toolkit/prep/setup/__init__.py): exports `inspect_system`, `decide_action`, `SetupAction`, `SystemState`, `run_smart`.

All 18 RED tests turned GREEN on the first pass — no implementation bugs surfaced. (`ruff` flagged 3 minor format/import-sort issues; `--fix` cleaned them up.)

**Step 1.3 — REFACTOR**: no structural changes needed. The code is straightforward state-machine logic. One inline cleanup: removed the "Run setup interactively" stderr pointer from `run_smart`'s FULL_DESTRUCTIVE / RESTAGE_NEBULA branches when the CLI is the caller — the pointer was misleading post-CLI-wiring (the user IS running setup). The rationale on stdout still contains "first-time" / "partition" keywords the test asserts against.

**Gates**:
- **Host venv full suite**: 175 passed, 61 skipped (was 157; +18 net = smart-setup's 6 inspect + 7 dispatch + 5 integration).
- **In-image full suite**: 236 passed, 0 failed (was 218 at session start; +18 net). No regressions.
- **Ruff + format**: clean.

**Real-environment smoke**: `cd /Users/hugi/GitRepos/GenomeClaw && bin/genomeclaw-prep setup --dry-run` against the current state (Kingston renamed to `Genome_Work_Kingston`, T7 with factory contents, no canonical `Genome_Work` partition):

```
Detected action: full_destructive
Rationale: No Genome_Work partition detected — first-time onboarding required.
Detected external volumes:
  - T7 Shield  (/Volumes/T7 Shield, 2000 GB, exfat)
  - Genome_Work_Kingston  (/Volumes/Genome_Work_Kingston, 512 GB, apfs)
Path to Nebula deliverable directory: ...
```

The smart-dispatch correctly identifies the no-partition state and falls through to the interactive flow. The output is clean (no misleading pointer messages); the transition is seamless.

**Documentation updates landed**:
- [README.md § Storage planning](../../../README.md#storage-planning): new paragraph documenting `setup`'s idempotent + self-healing behavior; cross-links to this plan's spec.
- [docs/reference/user-stories.md § Story 1 Step 0](../../reference/user-stories.md): new "Self-healing setup" paragraph alongside the existing "Diagnostics" paragraph.
- [docs/plans/completed/cram-scratch-strategy/work-notes.md § Cumulative recovery procedure](../../completed/cram-scratch-strategy/work-notes.md#cumulative-recovery-procedure): the manual `sed memory: 2 → 8` + `colima stop && colima start` dance is now superseded by `bin/genomeclaw-prep setup`; updated the recovery script + added an explicit "Update 2026-05-11" note.

**Decisions Made (during implementation)**:

1. **`inspect_system` skips layout / nebula / colima checks when partition is absent or wrong-format.** Cleaner code path; the dispatcher trips on partition-state first anyway. The skipped fields default to False/None/empty-tuple in `SystemState`.
2. **Production memory threshold = 8 GB (`_PRODUCTION_MEMORY_GB`); inspection threshold = 4 GB (`_MIN_COLIMA_MEMORY_GB`).** Setup flags drift at < 4 GB; when fixing the drift, it bumps to 8 GB so there's margin before another bump is needed. Two thresholds for two concerns (drift detection vs. production sizing).
3. **`run_smart`'s standalone pointer messages removed.** The CLI is the only caller in production; the pointer would only be useful if someone imported `run_smart` directly — they can read the action enum themselves. Trade-off: one fewer line of stderr for standalone callers; cleaner CLI output for everyone else.
4. **`write_colima_yaml` is reused as-is.** The existing helper already handles mount-list de-dup + preserves user's other mounts. No new yaml-writer code; only the memory-bump helper is new in `_reconfigure_colima.py`. Net change: ~40 lines of new yaml manipulation.
5. **The audit-log goes under `_scratch/setup.log` for non-destructive actions too.** The original destructive flow already used `_scratch/setup.log` (after promoting from `~/.genomeclaw/setup-<ts>.log`). For non-destructive actions, `_scratch/` is guaranteed to exist (we just created it via `recreate_layout`, or it was already there), so we can write directly. Avoids the temp-then-promote dance.

**Phase 1 status: Complete.** All 18 tests green; both gates green; lint clean; real-environment smoke confirms the dispatch works. The smart-setup feature is live as the default behavior of `bin/genomeclaw-prep setup`.

**Plan close**: moving `docs/plans/active/smart-setup/` → `docs/plans/completed/smart-setup/`. The doctor-extension follow-up flagged in the development-plan is filed but not landed; smart-setup auto-heals at the entry point, doctor would add a proactive heads-up. Worth ~30 min when filed as its own plan.

**Next step**: resume MVP Phase 4 — W4 (ClinVar match-count parity check on the project owner's real Nebula VCF). Pre-requisite: actually run the destructive setup against T7 Shield. Now `bin/genomeclaw-prep setup` is the single command for that — no manual bootstrap needed.