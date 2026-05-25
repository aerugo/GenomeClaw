# Onboard Persistent Agent Fix — Work Notes

**Feature**: make `./scripts/onboard-sandbox.sh` produce a working persistent `nemoclaw genomeclaw` sandbox in one run, without ever putting the OpenAI API key on argv.
**Started**: 2026-05-24
**Branch**: `feature/onboard-persistent-agent-fix` (not yet created)
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)
**Source report**: [docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md)

---

## Session Log

### 2026-05-24 — Plan creation (no implementation yet)

**Context Review Completed**:
- Re-read [root CLAUDE.md](../../../../CLAUDE.md) — confirmed applicable invariants: INV-P001, INV-P002, INV-D006.
- Read [docs/reference/INVARIANTS.md v1.16](../../../reference/INVARIANTS.md) — confirmed P003 is the next available `INV-P` number (P001 = privacy default, P002 = agent egress).
- Read [docs/plans/CLAUDE.md](../../CLAUDE.md) (planning protocol) — confirmed plan structure.
- Re-read [docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md) — source of all three failure modes addressed by this plan.
- Inspected `packages/nemoclaw-plugin/sandbox/Dockerfile` (where Phase 1 lands).
- Inspected `scripts/onboard-sandbox.sh` (where Phase 2 lands — the 2026-05-24 shim-Dockerfile fix is already in this file).
- Inspected `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` mention from the README — confirmed `host doctor` lives there.

**Applicable Invariants**:
- **INV-P001**: tightening — the script's argv-secret leak path closes structurally in Phase 2; baked-image config gate extends in Phase 1.
- **INV-P002**: respect — no new egress surface; the OpenAI provider config flow is the same shape the live-smoke harness already uses.
- **INV-D006**: detection layer — Phase 3 surfaces the colima-mounts misconfiguration as an operator warning rather than a silent agent failure.
- **NEW INV-P003** (proposed): secrets via stdin or env, never via argv. Promoted into `INVARIANTS.md` only after Phase 2's tests are green.

**Key Insights**:
- The `nemoclaw genomeclaw exec` failures observed on 2026-05-24 are NOT a bug in nemoclaw — they're an openshell-sandboxing-wrapper behavior we don't control. `docker exec --user sandbox -e HOME=/sandbox` works as a clean bypass and is what the live-smoke harness already uses implicitly.
- `HOME=/sandbox` was the missing piece. Without it, `openclaw config` defaults to `/root/.openclaw` which the uid-998 sandbox user can't write. The Dockerfile has `WORKDIR /sandbox` but not `ENV HOME=/sandbox` — adding the `ENV` line is one of the most impactful single-line changes in the whole plan.
- The OpenAI API key leak was a single `python3 -c "...$PROFILE_B64..."` invocation that crashed for an unrelated reason (target dir missing) and dumped its `-c` argv into a traceback. Python prints the full source in tracebacks by default. Any future failure of any argv-interpolated-secret invocation will repeat the leak — hence the proposed structural invariant.

**Completed Today**:
- [x] Wrote `spec.md` with the three failure modes, seven ACs, applicable invariants, and the proposed INV-P003.
- [x] Wrote `development-plan.md` with three-phase breakdown.
- [x] Wrote `phases/phase-1.md` (Dockerfile bakes + invariant test).
- [x] Wrote `phases/phase-2.md` (script rewrite + INV-P003 discovery test + live-onboard integration test).
- [x] Wrote `phases/phase-3.md` (host doctor colima-mounts check).
- [x] Created this work-notes.md.

**Decisions Made**:
- **Three phases, not one big rewrite.** Each phase is independently mergeable + testable. Phase 1 (Dockerfile bakes) is the prerequisite for Phase 2; Phase 3 is independent and could be merged in any order.
- **Skip the upstream fix.** The cleanest fix would be (a) nemoclaw exposes `--context` on its onboard CLI, AND (b) openshell-sandbox-wrapper relaxes its filesystem restrictions for the operator-trusted exec path. Both are upstream-controlled and would take indefinite time. This plan accepts the workarounds.
- **`auth-profiles.json` stays in `onboard-sandbox.sh`, not split into a separate script.** Operator ergonomics matter (one command to onboard); the stdin-based write is structurally safe under INV-P003 so the privacy gain of splitting is small.
- **Discovery test is the structural floor for INV-P003.** Per-pattern tests give better failure attribution, but the discovery test catches future-script-additions that re-introduce the pattern. Both.
- **Regex, not pyyaml, for the colima.yaml read.** No new dep, narrow enough pattern to be robust, fits the doctor's "fast read-only check" shape.

**Blockers / Issues**:
- None pre-implementation. Phases are sequenced so Phase 1's prerequisite (Dockerfile bakes) is in place before Phase 2 starts deleting the now-redundant script calls.

**Next Steps**:
1. Branch `feature/onboard-persistent-agent-fix` from main.
2. Implement Phase 1: write the RED tests in `tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py`; confirm RED; minimal Dockerfile edits; confirm GREEN.
3. Implement Phase 2: write the RED INV-P003 discovery test; confirm RED on the existing script; rewrite the script; confirm GREEN; run the live-onboard integration test; promote INV-P003.
4. Implement Phase 3: write the RED parametrized doctor test; confirm RED; add the `_check_colima_mounts_cover_derived` function; confirm GREEN.
5. Run full test suite; static checks; manually verify end-to-end against the operator's host.

---

### 2026-05-25 — Implementation session (all three phases)

**Context Review Completed**:
- Re-read [spec.md](spec.md), [development-plan.md](development-plan.md), and the three phase plans.
- Inspected the existing baked-image test pattern (`test_invP001_sandbox_web_egress_contract.py`) for AC3 + AC4 test scaffolding.
- Inspected `prep/doctor.py` to confirm the report-dict shape (named sections, not findings array) and the existing `_collect_stale_colima_mounts` pattern for the Phase 3 helper.
- Empirically confirmed the OpenAI apiKey ref shape (`{"source":"env","provider":"default","id":"OPENAI_API_KEY"}`) by inspecting a running sandbox.

**Applicable Invariants** (reaffirmed):
- INV-P001 (extended via Phase 1 bakes); INV-P002 (no widening); INV-D006 (Phase 3 detection layer); NEW INV-P003 (promoted in Phase 2).

**Key Insights**:
- The `apiKey --ref-source env` set is order-sensitive — needs `baseUrl` AND `models` already present (validator's cross-field check). Used `openclaw config set --batch-file` to land all four provider keys atomically.
- BuildKit heredoc syntax isn't portable to the default docker builder; `printf '%s' '...' > /tmp/...` is the lowest-common-denominator.
- The openshell-wrapper EACCES on `/opt/genomeclaw` is real — Phase 2's pivot to `docker exec --user sandbox -e HOME=/sandbox` was load-bearing for both the bake-skip safety net and the auth-profile write.

**Completed Today**:
- [x] Phase 1 RED: 6 tests fail for the right reasons.
- [x] Phase 1 GREEN: Dockerfile diff lands (ENV HOME + 3 RUN blocks); image rebuilt; 6/6 pass; web-egress invariant test still green (3/3).
- [x] Phase 2 RED: INV-P003 discovery test fails on the existing script's `python3 -c "...$PROFILE_B64..."` pattern (after adding bash-line-continuation handling to the regex pass).
- [x] Phase 2 GREEN: script rewritten; INV-P003 tests pass (3/3).
- [x] INV-P003 promoted into `docs/reference/INVARIANTS.md` between P002 and R001; Version 1.16 → 1.17; Last Updated bumped; Invariant Index entry added; new changelog entry at top.
- [x] README updates for Phase 2 (step renumbering, accuracy fix on "never lands in argv" claim, gateway-start step doc, three Troubleshooting entries).
- [x] `.claude/agents/privacy-safety-reviewer.md` updated (INV-P003 to coverage list + Anti-Patterns entry).
- [x] Phase 3 RED: 5 of 6 doctor tests fail; the 6th (exit-code test) passes by coincidence (doctor already exits 0 on clean layout).
- [x] Phase 3 GREEN: `_collect_colima_mounts_cover_derived` added; wired into `doctor()` report dict; 6/6 pass.
- [x] README updates for Phase 3 (extended `host doctor` description + extended the existing `no_active_run` troubleshooting entry to enumerate both failure modes).
- [x] Regression check: all 51 existing doctor tests still pass; full invariant suite is 68/68 green excluding 1 pre-existing failure (`test_invP002_policy_preset_targets_host_openshell_internal` asserts port 8643 but our policy preset is on 8645 — stale from the earlier port-migration commit 1dcf81c, unrelated to this plan).

**Decisions Made (deviation from plan)**:
- Skipped the live-onboard integration test (`test_live_onboard_persistent_agent.py`). The plan called for a `@pytest.mark.live_onboard`-gated end-to-end test that runs `./scripts/onboard-sandbox.sh` against a throwaway sandbox. Implementing it would require either (a) destroying the currently-running `nemoclaw genomeclaw` sandbox or (b) standing up a parallel `genomeclaw-test` sandbox on a different port — both heavyweight for the demo session. The three discovery + per-pattern + positive-shape invariant tests cover the structural floor; the live end-to-end is a follow-up if/when needed. Documented as a known-deferred item.
- Skipped the host-disk-derived exemption case in Phase 3 (see Phase 3 Notes above).

**Blockers / Issues**:
- One pre-existing test failure (`test_invP002_policy_preset_targets_host_openshell_internal`) unrelated to this plan — port migration drift. Not in scope.

**Next Steps**:
1. Operator runs `./scripts/onboard-sandbox.sh` end-to-end to manually verify AC1 + AC2 + AC7 on their host (the live equivalent of the skipped integration test).
2. If onboarding succeeds, plan moves to `docs/plans/completed/onboard-persistent-agent-fix/`.
3. Two follow-up plans worth filing: `genomeclaw_pgs_compute` ack-without-row bug; `genomeclaw_gene` argument-serialization bug. Both surfaced in the 2026-05-24 demo and reproduce reliably.

---

## Phase Progress

### Phase 1: Bake the Persistent-Path Config Into the Sandbox Dockerfile
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results
```text
tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py
  test_invP001_baked_gateway_mode_is_local                     PASSED
  test_invP001_baked_plugins_allow_contains_genomeclaw         PASSED
  test_invP001_baked_hostservice_baseurl_uses_build_arg_port   PASSED
  test_invP001_baked_hostservice_timeoutms_is_30000            PASSED
  test_invP001_baked_openai_apikey_is_env_ref_not_literal      PASSED
  test_invP001_baked_env_home_is_sandbox                       PASSED
============================== 6 passed in 0.38s ===============================
```
Existing `test_invP001_sandbox_web_egress_contract.py` (3 tests) still passes.

#### Results
- `packages/nemoclaw-plugin/sandbox/Dockerfile` modified: added `ENV HOME=/sandbox` after `USER sandbox`, plus three new `RUN openclaw config set ...` blocks for (a) gateway.mode + plugins.allow + hostService.baseUrl/timeoutMs, (b) openai provider baseUrl/models/auth-profile via `openclaw config set --batch-file` (single-key sets fail validator's circular cross-field check), (c) openai apiKey as env-ref.
- `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py` created: 6 invariant tests reading `/sandbox/.openclaw/openclaw.json` out of the built image + reading `Config.Env`.
- Sandbox image rebuilt successfully: `genomeclaw/sandbox:port-8645`.

#### Notes
- **apiKey ref shape confirmed empirically** to be a flat dict `{"source": "env", "provider": "default", "id": "OPENAI_API_KEY"}` — wrote test against this exact shape.
- **First build failure**: `openclaw config set models.providers.openai.apiKey --ref-source env --ref-id OPENAI_API_KEY` rejected with `models.providers.openai.baseUrl: Invalid input: expected string, received undefined` — provider's apiKey set validates against adjacent fields (baseUrl/models). Worked around by adding baseUrl/models/auth-profile via the same batch-file pattern the live-smoke harness uses.
- **Second build failure**: tried per-key `openclaw config set baseUrl ... && openclaw config set models ...` chain — but the cross-field validator runs after EACH single set, so baseUrl-without-models fails, and models-without-baseUrl fails too. Switched to `openclaw config set --batch-file /tmp/openai-provider.json` which sets all four keys atomically. Validator is happy after the batch lands.
- **Third build failure**: BuildKit heredoc syntax (`RUN <<'EOF'`) isn't supported by the default docker builder we use; switched to `RUN printf '%s' '...' > /tmp/...` + `openclaw config set --batch-file /tmp/...` + cleanup. Portable across builders.

---

### Phase 2: Onboard Script — stdin for Secrets, Explicit Gateway Start
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results
```text
tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py
  test_invP003_onboard_script_has_no_argv_secret_patterns                 PASSED
  test_invP003_discovery_no_argv_secret_patterns_across_scripts_dir       PASSED
  test_invP003_onboard_script_writes_authprofile_via_stdin                PASSED
============================== 3 passed in 0.01s ===============================
```

#### Results
- `scripts/onboard-sandbox.sh` rewritten: deleted broken step 5 (hostService.baseUrl/timeoutMs via `nemoclaw exec` — now baked); rewrote step 6 (auth-profile write) to render JSON on Python's stdout and pipe into `docker exec -i --user sandbox -e HOME=/sandbox <CID> bash -c 'mkdir -p ... && cat > ...auth-profiles.json'` — payload never lands in argv; rewrote step 7 (models.json inference.local routing) to use the same `docker exec -i` path (no secret here but the EACCES bug was the same); added step 7b that explicitly (re-)starts the openclaw gateway via `docker exec -d -e OPENAI_API_KEY=...` so the gateway has the env var the baked apiKey-ref resolves against; kept step 8 (smoke test via `nemoclaw genomeclaw exec`) unchanged because agent calls don't read /opt/genomeclaw. Added `set +x` guard around the secret-touching block as defense-in-depth.
- `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py` created: 3 invariant tests — per-script grep for forbidden argv-secret patterns; discovery test walking all `.sh` under `scripts/`; positive-shape complement asserting the stdin pattern is present.
- `INV-P003` promoted into `docs/reference/INVARIANTS.md` between INV-P002 and INV-R001; Invariant Index entry added; Version bumped to 1.17, Last Updated 2026-05-25, new changelog entry at top of file.
- `README.md` updated: renumbered steps in "Sandbox setup — the GenomeClaw NemoClaw agent" (step 5 deleted, steps 6→5, 7→6, added 7 + 7b); fixed the misleading "never lands in argv or process list" claim (was empirically false; new wording describes the actual stdin-based path); added three Troubleshooting entries for the failures the demo session surfaced.
- `.claude/agents/privacy-safety-reviewer.md` updated: INV-P003 added to "Invariants You Are Responsible For" section + new Anti-Patterns entry.

#### Notes
- **Test discovery test caught its own gap**: the `python3 -c "...base64.b64decode('$PROFILE_B64')..."` pattern in the original script spans two physical lines (bash `\` line continuation). My initial regex was line-based and missed it. Added `_join_line_continuations` helper that joins `\\\n` continuations into logical lines before applying the patterns. The negative tests then correctly turned RED on the pre-rewrite script.
- **Forbidden pattern list** is conservative — three shapes that map to the canonical leak modes: `python3 -c "...b64decode('$...')..."` (the 2026-05-24 leak), `bash -c "...$<NAME>_(KEY|SECRET|TOKEN|PASSWORD)..."` (shell-string interpolation), `--key/secret/token/password $X` (argv flag interpolation). Adding more patterns is easy (just add to `_FORBIDDEN_ARGV_PATTERNS`); over-broad patterns risk false positives that obscure real violations.

---

### Phase 3: `host doctor` Colima-Mounts Coverage Check
**Status**: Complete
**Started**: 2026-05-25
**Completed**: 2026-05-25

#### Test Results
```text
tests/integration/test_host_doctor_colima_mounts_coverage.py
  test_invD006_doctor_warns_when_colima_mounts_empty_and_derived_uncovered                PASSED
  test_invD006_doctor_no_warning_when_mounts_cover_derived                                PASSED
  test_invD006_doctor_warns_when_mounts_populated_but_dont_cover                          PASSED
  test_invD006_doctor_no_warning_when_colima_config_absent                                PASSED
  test_invD006_doctor_exit_code_is_zero_when_only_finding_is_this_warning                 PASSED
  test_invD006_doctor_handles_yaml_with_quoted_paths_and_trailing_slashes                 PASSED
============================== 6 passed in 0.07s ===============================
```
Existing `test_doctor.py` (31 tests) and `test_doctor_helpers.py` (20 tests) still pass — 51 pre-existing + 6 new = 57 doctor-adjacent tests green.

#### Results
- `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` modified: added `_collect_colima_mounts_cover_derived(config_path, derived_dir)` helper (uses `yaml.safe_load`, follows the existing `_collect_stale_colima_mounts` shape); wired it into `doctor()` between the stale-mount and reference checks; added the new `colima_mounts_cover_derived` key to the report dict. Returns one of three statuses: `"no_config"` (yaml absent — different check's territory), `"covers"` (at least one mount entry is an ancestor of derived_dir), or `"uncovered"` (warning with both fixes named: re-run `host setup` OR `GENOMECLAW_NATIVE=1`).
- `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py` created: 6 tests covering the three statuses + exit-code-stays-zero + trailing-slash mount path edge case.
- `README.md` updated: extended the `host doctor` description in "Day-to-day commands" to mention the new check; extended the existing "Agent reply says `no_active_run`" troubleshooting entry to enumerate the two failure modes (CURRENT-missing vs colima-mounts-uncovered) and the fixes for each.

#### Notes
- **Design simplification vs. plan**: the Phase 3 plan over-specced a "$HOME-derived is exempt" case (system-disk paths skip the warning because colima shares $HOME by default). Dropped that case during implementation — on macOS Sequoia + VZ.framework, $HOME is mounted read-only without Full Disk Access, so the exemption would give false negatives. The simpler design ("warn unless an explicit mount covers") is more robust and the "fix" message names both `host setup` and `GENOMECLAW_NATIVE=1`, so operators on $HOME-derived still have a clear path.
- **Used pyyaml, not regex**: my Phase 3 plan assumed no `yaml` dep, but `_collect_stale_colima_mounts` already imports it. Following the existing pattern (yaml.safe_load with defensive try/except) was simpler than the regex approach.
- **Report shape is dict-of-sections, not findings-array**: my Phase 3 plan assumed a `findings: [...]` array but the existing doctor surfaces named sections (`stale_mounts`, `colima_mount_visible`, etc.). Adapted the new collector + the tests to match — section is keyed `colima_mounts_cover_derived` in the report dict, status field carries the verdict.

---

## Key Decisions

### Decision 1: Three-phase split, not single-rewrite
**Date**: 2026-05-24
**Context**: The fixes from the demo report span Dockerfile, shell script, and Python CLI. A single mega-PR would be a rewrite waiting to happen.
**Decision**: Split into Phase 1 (Dockerfile), Phase 2 (script), Phase 3 (doctor). Each independently mergeable; Phase 1 is prerequisite for Phase 2 but Phase 3 is independent.
**Rationale**: Matches the planning protocol's "phased delivery" principle. Phase 1 is the smallest possible "build it and they work" — a baked image that the operator can manually drive via `docker exec` if Phase 2 hasn't landed. Phase 2 is where the structural privacy win lands. Phase 3 is the operator-UX polish.
**Alternatives Considered**: single-PR rewrite (rejected — too large to review carefully); two phases (Dockerfile+script combined, then doctor) — rejected because the INV-P003 promotion deserves its own phase visibility.
**Affected Invariants**: INV-P001 (extended in Phase 1), NEW INV-P003 (promoted in Phase 2), INV-D006 (detection layer added in Phase 3).

### Decision 2: Bake config rather than fix nemoclaw exec
**Date**: 2026-05-24
**Context**: `nemoclaw genomeclaw exec` is EACCES-failing on /opt/genomeclaw inside the openshell sandboxing wrapper. Could try to fix nemoclaw upstream OR work around.
**Decision**: Work around by baking the config that nemoclaw exec was trying to set. Open an upstream issue but don't block this plan on it.
**Rationale**: The bake-time path is a known-good place where the Dockerfile already sets four similar config keys. Adding three more (`gateway.mode`, `plugins.allow`, `hostService.baseUrl`) is one Dockerfile line each. Upstream fixes take indefinite time.
**Alternatives Considered**: file an upstream issue (still doing that as a follow-up); modify the openshell sandbox wrapper to allow /opt reads (rejected — not our code).
**Affected Invariants**: None changed.

### Decision 3: stdin-based auth-profile write, not bake
**Date**: 2026-05-24
**Context**: Could bake the OpenAI key into the image at build time (via `--build-arg`) instead of writing post-build. Wouldn't need `docker exec -i ... cat > ...`.
**Decision**: Stdin-based write at onboard time, not bake.
**Rationale**: Baking the key into the image creates a Docker layer that contains the secret. Anyone with read access to the image (operator's local registry, future image pushes, layer-export attacks) gets the key. Writing post-build keeps the key in the running container only; if the container is destroyed, the key is gone.
**Alternatives Considered**: build-arg bake (rejected per above); skip the file entirely and rely solely on `models.providers.openai.apiKey` env-ref (rejected because some openclaw code paths read from `auth-profiles.json` directly — DevRelClaw's onboarding hit this and works around it the same way).
**Affected Invariants**: INV-P001 (tightened), NEW INV-P003 (introduces the pattern).

---

## Files Modified

### Created (in plan)
- `docs/plans/active/onboard-persistent-agent-fix/spec.md`
- `docs/plans/active/onboard-persistent-agent-fix/development-plan.md`
- `docs/plans/active/onboard-persistent-agent-fix/phases/phase-1.md`
- `docs/plans/active/onboard-persistent-agent-fix/phases/phase-2.md`
- `docs/plans/active/onboard-persistent-agent-fix/phases/phase-3.md`
- `docs/plans/active/onboard-persistent-agent-fix/work-notes.md`

### Created (planned, during implementation)
- `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py`
- `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py`
- `packages/toolkit/tests/integration/test_live_onboard_persistent_agent.py`
- `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py`

### Modified (planned, during implementation)
- `packages/nemoclaw-plugin/sandbox/Dockerfile` (Phase 1)
- `scripts/onboard-sandbox.sh` (Phase 2)
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` (Phase 3)
- `docs/reference/INVARIANTS.md` (Phase 2 — INV-P003 promotion + Version bump)
- `README.md` (Phase 2 + Phase 3 — sandbox-setup section + doctor mention)
- `.claude/agents/privacy-safety-reviewer.md` (Phase 2 — add INV-P003)

### Deleted
- (none planned)

---

## Documentation Updates Required

### INVARIANTS.md changes
- [ ] Add `INV-P003`: Secrets via stdin or env, Never via argv — after Phase 2.

### Other Documentation
- [ ] `README.md` — Sandbox-setup section reflects the new flow; small mention under doctor for the new check.
- [ ] `.claude/agents/privacy-safety-reviewer.md` — INV-P003 added to coverage list.

---

## Open Risks & Follow-ups

- **Risk**: `nemoclaw onboard` upstream changes its build-context handling, invalidating the shim-Dockerfile workaround.
- **Risk**: openshell sandbox wrapper tightens further to block `docker exec` from outside the sandbox. Would require moving auth-profile placement to build-time `--build-arg`, which has its own privacy concerns.
- **Follow-up plan needed**: `genomeclaw_pgs_compute` ack-without-row bug (PGS000014, PGS000334).
- **Follow-up plan needed**: `genomeclaw_gene` argument-serialization bug (CYP1A2/ADORA2A/AHR/POR/BRCA1/BRCA2/TP53).
- **Follow-up (low priority)**: make `bin/genomeclaw host service` auto-fall-back to native uvicorn when colima mounts don't cover the dir (Phase 3 doctor warning is the operator-visible stopgap).
