# Smart setup — state-detection-driven `genomeclaw-prep setup`

**Feature**: `genomeclaw-prep setup` inspects current system state and dispatches the right action automatically, instead of always running the monolithic destructive flow.

---

## Goal

Replace `setup`'s single-purpose destructive behavior with a state-driven dispatcher so the same command works as both "first-time onboarding" *and* "recover from colima drift" without the user having to know which mode to invoke.

## Background

During MVP Phase 4C.2 wrap-up (2026-05-11), the toolkit team hit a recurring problem: every `colima delete` (the standard recovery from a wide class of VM-level failures) wipes `~/.colima/default/colima.yaml`'s `mounts:` block + resets `memory:` to lima's default. The on-disk `Genome_Work` partition survives, so `genomeclaw-prep doctor` reports green, but the engine VM can no longer see the bind-mounted paths — every subsequent pipeline run fails at the docker `--mount` step. The fix is "rewrite colima.yaml + restart colima," but there's no command for that today; the only path is to re-run full destructive `setup`, which overkills (reformats the drive + recopies Nebula) and isn't appropriate when the partition is fine.

The current symptom recurred at least three times in one session ([cram-scratch-strategy post-close work-notes](../../completed/cram-scratch-strategy/work-notes.md#post-close-colima-recovery-recipe-added-2026-05-11) symptoms 1–5). Each time the fix was manual bootstrap of colima.yaml + restart. The pattern won't stop until the toolkit has a non-destructive reconfigure path.

A flag-mode (`setup --reconfigure-only`) would solve the technical problem but force the user to learn another mode name. The better design — and the one this plan implements — is **`setup` inspects state and figures out which action to take itself**.

## Acceptance criteria

1. **`bin/genomeclaw-prep setup`** invoked against a system in any of seven defined states (below) picks the correct action without requiring a mode flag.
2. **Idempotent in steady state**: if everything's already configured, `setup` reports "already configured" + exit 0 + no side effects.
3. **Destructive actions still require typed confirmation** (the existing `WIPE /Volumes/<name>` prompt). Non-destructive actions don't.
4. **Pre-action preview** — for every action other than "no-op," setup prints a one-paragraph summary of detected state + chosen action *before* executing, so the user knows what's about to happen.
5. **Audit-log records the chosen action** in `_scratch/setup.log` so the history of state transitions is reconstructable post-fact.
6. **`--dry-run`** still works — surfaces detected state + chosen action + would-be diff, exits 0 without executing.
7. **A 13-test in-image needs_bio suite + ~10-test host suite** cover the state matrix (one test per state→action mapping; one test per destructive-confirmation path; one for the audit-log shape).

### Seven defined states

| # | State | Detection | Chosen action |
|---|-------|-----------|---------------|
| 1 | **Fresh** | no `/Volumes/Genome_Work` partition | full destructive setup (current behavior; requires source path + typed confirm) |
| 2 | **Wrong format** | `/Volumes/Genome_Work` exists but is not APFS | full destructive setup (with typed confirm) |
| 3 | **Layout missing** | partition + format OK, but ≥1 of `raw/reference/derived/_scratch` is absent | `mkdir -p` the missing subdirs (non-destructive; no confirm) |
| 4 | **Nebula missing** | layout OK but `raw/<sample-id>/` empty | re-copy from source path the user provides (or fail with clear pointer if `--source` not given) |
| 5 | **Colima drifted** | partition + layout + Nebula OK, but `~/.colima/default/colima.yaml` is missing the canonical `mounts:` entries OR `memory:` < 4 GB | rewrite colima.yaml + restart colima (non-destructive; no confirm) |
| 6 | **Colima stopped** | everything else OK, colima just isn't running | `colima start` |
| 7 | **Fully configured** | all of the above pass | no-op + report green |

## Applicable invariants

- **`INV-D001`** Raw Genomic Files Are Source-of-Truth Artifacts — state-inspection reads `raw/` but never mutates it; the "Nebula missing" recovery action copies *into* `raw/` from a user-provided source, with per-file SHA256 verification (same contract as the existing fresh-install path).
- **`INV-D003`** Heavy Scratch Is Separated From Authoritative Outputs — the "Layout missing" action recreates `_scratch/` as a sibling of `derived/`, preserving the structural separation. The "Colima drifted" action's rewritten `mounts:` block keeps the canonical four-mount layout intact.
- **`INV-R001`** Rebuildability — every dispatched action appends a structured event to `_scratch/setup.log` (`{ts, action, detected_state, params}`). The dispatcher is deterministic given a fixed `SystemState` so the chain "inspect → dispatch → execute" is reproducible.

## Proposed new invariants

None. Existing invariants cover the surface; this is a refactor of an existing orchestrator + a new dispatch layer.

## Out of scope

- **Doctor extension** to surface colima.yaml drift before a pipeline run. Filed as a companion follow-up; the smart-setup auto-heal handles the same drift at the setup entry point.
- **Cross-drive migration** between two configured drives (e.g., Kingston → T7 with both already containing Genome_Work partitions). Falls into the "wrong format" or "fresh" buckets depending on the target's state; explicit migration tooling is a separate plan if observed need surfaces.
- **Linux host support**. Setup's diskutil + colima invocations are macOS-specific; smart-setup inherits that limitation.
- **Concurrent `setup` invocations**. The orchestrator serializes per shim invocation; concurrent runs are out of scope (and not a real-world use case for a single-user CLI).

## Privacy & safety considerations

No new egress paths. State inspection reads local filesystem + colima.yaml + `diskutil`/`colima` shellouts; no network calls. The destructive paths inherit the existing typed-confirmation guard. Per `INV-P001`, no genomic data is ever transmitted; the only network-touching action (full destructive's Nebula copy) is host-side disk-to-disk.

The audit-log entries are local-only and contain only filesystem paths + state flags, never variant data.

## Open questions

| Q | Resolution candidate |
|---|---|
| **Q1: Should "Nebula missing" auto-prompt for source path, or fail-fast?** | Fail-fast with a clear pointer. The fresh-install path already handles "where's your Nebula" via the interactive volume detection; re-using that prompt in the recovery path is ergonomic but conflates two scenarios. Cleaner: "Nebula raw dir is empty; re-run setup with `--source /path/to/nebula-deliverable` or run `genomeclaw-prep ingest` directly." |
| **Q2: How do we detect "colima drifted"?** | Parse `~/.colima/default/colima.yaml` via the existing `_yaml_writer.py` helper (already round-trips colima's yaml shape). Compare `mounts:` entries against the canonical list (derived from the actual `Genome_Work` partition mount-point); flag drift if any canonical entry is missing OR memory < 4 GB. Don't require exact equality (the user may have added their own non-canonical mounts; setup shouldn't strip them — only ensure the canonical entries are present). |
| **Q3: What does the "Colima drifted" action's `setup.log` event look like?** | `{step: "reconfigure_colima", detected_state: {...}, mounts_added: [...], memory_before: 2, memory_after: 8}`. Diff is recorded so a `git log`-style replay is possible. |
| **Q4: When the user runs `setup` against a fully-configured system, what does the output look like?** | One-line "Already configured" + a `doctor`-style green summary (the four canonical paths + colima status). Exit 0. ~3 lines of output total. |
| **Q5: Should state inspection itself be idempotent? Could two consecutive `setup` calls produce different `SystemState`s?** | Yes, idempotent — the only side effects of inspection are read-only stat + subprocess capture (no mkdir, no shellout that mutates state). Two consecutive calls produce the same state unless something external changed. |
| **Q6: What's the test strategy for `colima_running` detection?** | Inject a fake `Platform` (same protocol the existing setup uses) that returns `colima_running=True/False` synthetically. Real colima behavior is exercised by the existing in-image needs_bio suite. State-inspection unit tests run on host venv. |

## Estimated effort

~1.5–2 hours active implementation:

- State-inspection module: ~150 lines, ~6 unit tests
- Dispatcher: ~50 lines, ~7 unit tests (one per state)
- Three new action handlers (reconfigure-colima, recreate-layout, start-colima): ~100 lines total + 6 tests
- Updated `run.py` orchestrator: ~50 lines of dispatch + UX
- CLI no-op (the entry point is unchanged; behavior is just smarter underneath)

Total: ~13 new tests on host venv + ~5 in-image needs_bio tests for the end-to-end paths.
