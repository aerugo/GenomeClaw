# Phase 6: Destructive commands

**Status**: Complete
**Started**: 2026-05-12
**Completed**: 2026-05-12
**Parent Plan**: [development-plan.md](../development-plan.md)
**Predecessor**: [phase-5.md](phase-5.md) — pipeline UX + per-orchestrator callbacks + strict-typing graduation complete.
**Successor**: [phase-7.md](phase-7.md) — polish + agent ergonomics (tab completion, "did you mean", cold-start audit).

---

## Objective

Replace the Phase-1 thin wrappers for `host setup` and `host eject` with confirmation-aware implementations. Establish the **typed-confirmation prompt** pattern for destructive operations and the **non-TTY safety semantics** (`--force-reset` / `--force` without `--yes` on a non-TTY → exit 2).

This is the smallest remaining UX phase but the one with the highest blast-radius for user mistakes — wiping a drive that wasn't supposed to be wiped is unrecoverable. The Phase 1 + Phase 4 typed-error envelopes already pin the failure-mode shape; Phase 6 adds the pre-emptive "are you really sure?" gate that prevents getting there in the first place.

## Scope Boundaries

**In scope**:

- `host setup --force-reset` requires either an interactive TTY confirmation (the user types a specific phrase) or `--yes` on the command line. Without one of the two, the command refuses with exit 2 and a clear message naming both ways forward.
- `host setup` (non-force-reset paths): the existing smart-dispatch behaviour is preserved; no new prompt because the smart-dispatch resolver already refuses to reformat without explicit opt-in.
- `host eject` adds a confirmation prompt (the drive name typed back) when running in interactive TTY mode without `--force` AND without `--yes`. The existing `--force` flag (bypasses the in-flight-pipeline safety check) is preserved as a separate gate.
- The typed-confirmation phrase for `host setup --force-reset`: **`REFORMAT GENOMECLAW DRIVE`** (uppercase; the user must type it verbatim).
- The typed-confirmation phrase for `host eject`: the **drive's mount-point basename** (e.g. `Genome_Work` for `/Volumes/Genome_Work`) — a much shorter prompt but still specific enough to prevent muscle-memory ejection.
- JSON-mode behavior:
  - `host setup --json` emits a planned-actions payload before executing + a final result payload after. Non-TTY without `--yes` → still refuses (exit 2) with a structured error envelope.
  - `host eject --json` emits a single final-result envelope with `{drive, force_used, exit_code}`.
- `--yes` global flag is already wired (Phase 1) — Phase 6 just consumes it on the destructive paths.
- Tests: ~10 covering: typed-confirmation accept/reject paths, `--yes` bypass, non-TTY-refuses, JSON-mode behavior, eject prompt accept/reject, existing `PipelineRunningError` precondition path preserved.
- `cli-output-schemas.md`: add `host.setup` + `host.eject` payload schemas.
- Privacy-default test extended with one `host setup --dry-run --yes` case + one `host eject --force` case (both should make zero outbound HTTP calls).

**Out of scope** (deferred to later phases):

- Tab completion + "did you mean" + `--version` enrichment — Phase 7.
- Repo grep-clean + `INV-Cxxx` promotion — Phase 8.
- Rewriting the underlying `setup_run_smart` / `setup_run_interactive` / `eject_impl` orchestrators. Phase 6 only changes the CLI wrapper; the orchestrators stay unchanged.

## Invariants Enforced in This Phase

- **INV-P001** Privacy default — extending the no-egress test with `host setup --dry-run --yes` + `host eject --force` keeps the assertion that these commands never touch the network.
- **NEW provisional safety invariant `INV-S-confirmation-required`**: any CLI command that mutates host state outside `derived/` (i.e. reformats a disk, ejects a drive, modifies colima/lima state) requires either an interactive typed-confirmation OR an explicit `--yes` flag. Enforced by tests in this phase; promoted alongside `INV-C-cli-output-stability` in Phase 8 if it holds.

---

## TDD Steps

### Step 6.1 — RED

`tests/integration/test_cli_host_setup_confirmation.py` (CREATE):

1. `test_host_setup_force_reset_refuses_non_tty_without_yes` — invoke `host setup --force-reset --dry-run` under a non-TTY stdin; assert exit 2 + the error envelope's `suggested_actions` mentions both `--yes` and the typed phrase.
2. `test_host_setup_force_reset_accepts_yes_flag_on_non_tty` — same invocation + `--yes`; assert the orchestrator gets called with `auto_confirm=True`.
3. `test_host_setup_force_reset_accepts_typed_phrase_on_tty` — simulate TTY stdin returning `REFORMAT GENOMECLAW DRIVE\n`; assert orchestrator called with `auto_confirm=True`.
4. `test_host_setup_force_reset_rejects_wrong_phrase_on_tty` — TTY stdin returns `nope\n`; assert exit 2 + orchestrator never called.
5. `test_host_setup_json_emits_plan_and_result_envelopes` — `--json host setup --dry-run --yes`; assert exactly two stdout envelopes (plan + result), both schema-versioned.
6. `test_host_setup_non_destructive_path_skips_confirmation` — `host setup` without `--force-reset` invokes smart-dispatch; no prompt, no `--yes` required.

`tests/integration/test_cli_host_eject_confirmation.py` (CREATE):

7. `test_host_eject_refuses_non_tty_without_yes_or_force` — non-TTY stdin, no flags; exit 2.
8. `test_host_eject_accepts_yes_flag` — `--yes` skips prompt + invokes orchestrator.
9. `test_host_eject_accepts_typed_drive_basename_on_tty` — TTY stdin returns `Genome_Work\n`; orchestrator called with `drive=/Volumes/Genome_Work`.
10. `test_host_eject_preserves_force_flag_for_pipeline_running` — `--force` is independent of `--yes`; bypasses only the in-flight-pipeline check.
11. `test_host_eject_json_emits_result_envelope` — `--json host eject --yes`; assert single envelope with `{drive, force_used, exit_code}` payload shape.

Privacy extension in `test_invP001_cli_no_egress.py`:

12. `test_invP001_no_egress_during_host_setup_dry_run_yes`.
13. `test_invP001_no_egress_during_host_eject_yes`.

### Step 6.2 — GREEN

Add a small helper module `_cli/confirm.py` exporting:

```python
def require_destructive_confirmation(
    *,
    ctx: AppContext,
    operation: str,                  # "REFORMAT GENOMECLAW DRIVE" / drive basename
    suggested_actions: list[str],
) -> None
```

The helper:
- Returns silently if `ctx.assume_yes` is `True`.
- Refuses with `UsageError` (exit 2) when stdin isn't a TTY.
- Prompts the user; checks the typed string against `operation` (exact-match, case-sensitive).
- Refuses with `UsageError` (exit 2) on mismatch.

`_cli/commands/host.py` wires `require_destructive_confirmation()` into `host_setup`'s `--force-reset` branch + `host_eject`'s entry. JSON-mode `host setup` writes a "plan" envelope before the orchestrator call + a "result" envelope after.

### Step 6.3 — REFACTOR

- Confirm Google-style docstrings on every new public symbol.
- If the test suite shows the `require_destructive_confirmation()` API gets called the same way from both commands, leave it as the single helper. Otherwise split into `confirm_typed_phrase()` + `confirm_drive_eject()`.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `src/genomeclaw_toolkit/_cli/confirm.py` | CREATE | `require_destructive_confirmation()` helper |
| `src/genomeclaw_toolkit/_cli/commands/host.py` | MODIFY | Wire confirmation into setup --force-reset + eject; add JSON-mode plan/result envelopes |
| `docs/reference/cli-output-schemas.md` | MODIFY | Document `host.setup` + `host.eject` schemas |
| `tests/integration/test_cli_host_setup_confirmation.py` | CREATE | 6 tests for setup confirmation flow |
| `tests/integration/test_cli_host_eject_confirmation.py` | CREATE | 5 tests for eject confirmation flow |
| `tests/privacy/test_invP001_cli_no_egress.py` | MODIFY | 2 new no-egress cases |

---

## Verification

```bash
cd packages/toolkit

# Phase's tests
uv run pytest tests/integration/test_cli_host_setup_confirmation.py \
              tests/integration/test_cli_host_eject_confirmation.py \
              tests/privacy/test_invP001_cli_no_egress.py -v

# Full suite
uv run pytest -q

# Quality gates
uv run ruff check .
uv run ruff format --check .
uv run mypy src/genomeclaw_toolkit/_cli

# Smoke (against an external drive — user-discretion)
uv run genomeclaw host eject --drive /Volumes/Genome_Work --yes --dry-run    # if --dry-run lands
uv run genomeclaw --json host setup --dry-run --yes                          # validates plan + result envelopes
```

---

## Completion Criteria

- [x] All listed tests pass (13 new in setup + eject confirmation files + 2 privacy = 15 net; **375 passed, 61 skipped** — +15 over Phase 5).
- [x] Static checks pass: `ruff check` + `ruff format --check` + `mypy --strict` on `_cli/`.
- [x] `host setup --force-reset` without `--yes` and on a non-TTY exits with code 2 + an error envelope naming both ways forward — confirmed via real-CLI smoke (`uv run genomeclaw host setup --force-reset --dry-run < /dev/null` → exit 2).
- [x] `host eject` without `--yes` / `--force` and on a non-TTY exits with code 2.
- [x] `host setup --json --dry-run --yes` emits exactly two stdout envelopes (plan + result) — pinned by `test_host_setup_json_emits_plan_and_result_envelopes`.
- [x] Each enforced `INV-xxx` is verified by at least one test: INV-P001 covered by two new privacy cases (`test_invP001_no_egress_during_host_setup_dry_run_yes` + `test_invP001_no_egress_during_host_eject_yes`).
- [x] `docs/reference/cli-output-schemas.md` documents the new payload schemas with worked examples.
- [x] No raw genomic data committed.
- [x] `work-notes.md` updated.
- [x] Phase status updated in `development-plan.md` (Phase 6 → Complete).
- [ ] `phases/phase-7.md` drafted — covered by the existing development-plan narrative (`§ Phase 7: Polish + agent ergonomics`); standalone file will be authored at the start of Phase 7 work.

## Contract change (deliberate)

Phase 1's thin wrapper treated `--force-reset` ALONE as the deliberate confirmation: passing the flag was equivalent to typing the phrase. Phase 6 **changes** that contract: `--force-reset` no longer counts as confirmation by itself; the user must additionally pass `--yes` (scripted) or type the phrase (interactive TTY). This change broke 4 existing tests (`test_setup_force_reset_skips_smart_dispatch`, `test_setup_force_reset_dry_run_skips_destructive`, `test_setup_force_reset_propagates_run_interactive_failure`, `test_setup_cli_force_reset_with_source_and_target_runs_unattended`). All 4 updated to add `--yes` to their invocation. Documented in [work-notes.md](../work-notes.md#phase-6).
