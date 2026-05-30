# Phase 6: Documentation Cleanup + Optional Invariant Promotion

**Status**: Reconciled — premise largely invalidated by Phase 5; doc edits + INV-D011 registry entry SPECIFIED and deferred (in-flight doc-file WIP). INV-D011 enforced by the committed discovery test.
**Started**: 2026-05-30
**Completed**: spec + handoff 2026-05-30; doc-file commits deferred to the maintainer
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## ⚠️ Reconciliation (2026-05-30) — premise invalidated by Phase 5, and a clean-commit blocker

Two findings reshaped this phase:

1. **Phase 6's original premise is wrong for local Docker.** It assumed "the dashboard / `nemoclaw connect` / TUI now work, so remove the docker-exec guidance and make them primary." Phase 5 proved the opposite on local Docker: **`docker exec` / `scripts/ask.sh` REMAINS the canonical working path** (the embedded agent + the keyed gateway), while the dashboard/TUI are plumbing-fixed (canonical plugin path + loopback-tokenless gateway) but **data-blocked** (no v0.4 derived store → host 503) and require manual interaction. So the "remove docker-exec, dashboard-primary" rewrite must NOT be made. The current in-flight `CLAUDE.md` "Running the Agent Locally" section is already accurate for local Docker and needs no change.

2. **The doc files are entangled with substantial uncommitted in-flight WIP** that is NOT this plan's: `docs/reference/INVARIANTS.md` (+224 lines of other invariants), `README.md`/`CLAUDE.md`/`.claude/agents/test-engineer.md` (the workaround-docs additions, partly overlapping the exact troubleshooting sections this phase would edit — the in-flight README diff even *adds* a stale `/opt/genomeclaw` reference). Editing + committing these would bundle the maintainer's WIP. **Therefore the doc edits below are SPECIFIED and handed off; this plan does not edit those files.** INV-D011 is enforced by its committed discovery test; the INVARIANTS.md registry entry is deferred for the same reason.

## Objective (reconciled)

Specify the (small, residual) doc edits + the `INV-D011` registry entry as a maintainer handoff, to be applied alongside the in-flight doc-file WIP. Keep `INV-D011` enforced via the already-committed `test_invD011_plugin_install_path.py` (green through Phases 2–5). The original sweeping "remove docker-exec / dashboard-primary" rewrite is withdrawn (Phase 5 showed docker-exec/ask.sh stays canonical on local Docker).

### Deferred doc edits (handoff — apply with the in-flight doc WIP)
- **README.md § Troubleshooting**: the `/opt/genomeclaw` EACCES entries (≈ lines 392, 411, 502–506) describe a problem the canonical-path migration FIXED — the plugin is now at `/sandbox/build/genomeclaw` (inside the Landlock RW baseline). Update/remove those entries; update the `sandbox-up.sh` description (its plugin check now targets `/sandbox/build/genomeclaw/dist/index.js` and gateway detection is port-based, not the `/opt` EACCES probe). The in-flight README diff that *adds* an `EACCES-on-/opt/genomeclaw` probe line should be reconciled away.
- **CLAUDE.md § Running the Agent Locally**: already accurate for local Docker (docker-exec/ask.sh canonical, `sandbox-up.sh` recovery). No change needed beyond optionally noting the gateway is now loopback + auth=none (token-free) and the plugin path is `/sandbox/build/genomeclaw`.
- **.claude/agents/test-engineer.md**: the in-flight content (live-agent gates via `docker exec`, INV-V001 rule) is accurate; no canonical-path change needed.

### `INV-D011` registry entry (handoff — paste into INVARIANTS.md when its WIP settles)
> **INV-D011 — Plugin Install Path Follows NemoClaw's Canonical (Landlock-RW) Pattern.** Any plugin baked into a GenomeClaw sandbox image MUST live inside the OpenShell Landlock RW baseline (`/sandbox/…` or `/tmp/…`), registered with the OpenClaw runtime via `openclaw plugins install … --link`, and MUST declare its agent tools as cold metadata in `openclaw.plugin.json` (`contracts.tools` + `activation.onStartup`) so the gateway surfaces them without importing the runtime. Plugins MUST NOT live under `/opt/<plugin-id>/` or any path outside the baseline. **Where it applies**: `packages/*/sandbox/Dockerfile`. **How to verify**: `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` (path + version-tag pin) and `test_plugin_manifest_tool_contract.py` (cold-metadata tool contract). Bump INVARIANTS.md Version + add to the Invariant Index.

## Objective (original — superseded, retained for context)

Update README, CLAUDE.md, and `.claude/agents/test-engineer.md` to reflect the canonical NemoClaw-managed paths now that they actually work. Remove the *"nemoclaw exec is broken upstream"* warnings and the *"docker exec is the working path"* guidance. If Phases 1–5 validated the canonical-path discipline cleanly, promote `INV-D011` into [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) with a discovery test.

## Scope Boundaries

- **In scope**: README sandbox setup + troubleshooting sections; CLAUDE.md § Running the Agent Locally; test-engineer agent guidance; conditional `INV-D011` promotion.
- **Out of scope**: any code changes (those landed in Phases 2–4); user-facing report copy (no agent-output changes in this plan).

## Invariants Enforced in This Phase

- **NEW INV-D011** Plugin Install Path Follows NemoClaw's Canonical Pattern — promoted here (conditional). Promotion criteria: Phase 2's `INV-D011` provisional discovery test has been green for an entire phase cycle (Phases 2–5) without exception, and the upstream-canonical-path rationale survived Phase 1 audit.

---

## TDD Steps

### Step 6.1 — RED: Write Failing Tests

**Test cases**:

1. `test_readme_does_not_recommend_docker_exec_as_canonical_path` — read [README.md](../../../../README.md); assert the *"Running the Agent Locally"* or *"Sandbox setup"* sections do NOT contain *"docker exec ... openclaw agent"* presented as the primary path; the primary path must be the dashboard / `nemoclaw connect`. `scripts/ask.sh` is documented as the scripted alternative.
2. `test_readme_documents_canonical_plugin_path` — assert README mentions `/sandbox/.openclaw-data/extensions/genomeclaw/` as the install location.
3. `test_claude_md_running_agent_section_updated` — read [CLAUDE.md](../../../../CLAUDE.md); assert the § *Running the Agent Locally* (if it exists; or wherever the canonical-path guidance is) reflects the post-Phase-3 reality — no warnings about `nemoclaw exec` being broken.
4. `test_test_engineer_agent_no_workaround_references` — read [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md); assert no reference to the docker-exec-as-canonical pattern.
5. `test_invD011_discovery` (conditional) — if `INV-D011` promoted: walk all Dockerfiles under `packages/*/sandbox/`; fail if any of them install a plugin at a path outside `/sandbox/.openclaw-data/extensions/<plugin-id>/`. Walk all test files; fail if any reference `/opt/<plugin-id>/`.
6. `test_invariants_md_lists_invD011` (conditional, same gate) — read INVARIANTS.md; assert `INV-D011` is present in the Invariant Index and has a Rule / Requirements / Where it applies / How to verify section.
7. `test_phase6_muscle_question_regression_smoke` — **end-to-end regression smoke after doc edits**. Re-run `./scripts/ask.sh --capture "<muscle question>"`. Catches the case where a README env-var rename, an example credential path, or a CLAUDE.md edit accidentally regresses runtime behavior. Pass criteria: same as Phase 5 Test 3 — synthesized reply > 200 chars, ≥1 successful `genomeclaw_*` tool call, LLM-judge `faithful=true` AND `understandable=true` with `GENOMECLAW_REPLAY_LLM=1`.

**Sketch**:

```python
def test_readme_does_not_recommend_docker_exec_as_canonical_path():
    text = Path("README.md").read_text()
    # Primary path section should mention dashboard or connect
    assert re.search(r"### Running the Agent.*?\n(.*?\n){0,30}.*?nemoclaw (genomeclaw )?(connect|dashboard)", text, re.DOTALL)
    # No "docker exec is the working path" anti-guidance
    assert "docker exec is the working path" not in text

def test_readme_documents_canonical_plugin_path():
    text = Path("README.md").read_text()
    assert "/sandbox/.openclaw-data/extensions/genomeclaw" in text or \
           "/sandbox/.openclaw/extensions/genomeclaw" in text

def test_invD011_discovery():
    if not Path("docs/reference/INVARIANTS.md").read_text().count("INV-D011"):
        pytest.skip("INV-D011 not promoted yet")
    for dockerfile in Path("packages").rglob("sandbox/Dockerfile"):
        content = dockerfile.read_text()
        assert not re.search(r"COPY .*\s/opt/[a-z][a-z0-9-]+", content), \
            f"INV-D011: plugin path under /opt/ in {dockerfile}"
```

Run; confirm RED. Paste output into work-notes.

### Step 6.2 — GREEN: Minimal Implementation

1. **README.md** updates:
   - § Sandbox setup: lead with `nemoclaw onboard` flow (via `./scripts/onboard-sandbox.sh`). Document `/sandbox/.openclaw-data/extensions/genomeclaw/` as the plugin location.
   - § Running the Agent Locally: lead with the dashboard URL + `nemoclaw connect`; document `./scripts/ask.sh` as the scripted alternative.
   - § Troubleshooting: keep a note about base-image SHA bump cadence + the `nemoclaw <name> recover` path.
   - Remove the *"docker exec is the working path"* + *"nemoclaw exec is broken upstream"* warnings.
2. **CLAUDE.md** updates:
   - § Running the Agent Locally (or equivalent): same canonical-path documentation as the README.
   - Remove workaround guidance.
3. **.claude/agents/test-engineer.md** updates:
   - Update any test-runner / smoke-test guidance referencing `docker exec`-as-canonical to reflect the new reality.
4. **Conditional `INV-D011` promotion** (only if gate criteria met):
   - Add `INV-D011` to [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md):
     - Category: `INV-D` (Data).
     - Rule + Requirements + Where it applies + How to verify (cite the discovery test).
     - Increment INVARIANTS.md Version + Last Updated.
     - Add Invariant Index entry.
   - Move `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` from "provisional" to permanent (rename if it was named provisionally).
5. Re-run all six tests. Confirm green.

**Files affected**:
- [README.md](../../../../README.md): MODIFY
- [CLAUDE.md](../../../../CLAUDE.md): MODIFY
- [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md): MODIFY
- [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md): MODIFY (conditional)
- `packages/toolkit/tests/invariants/test_invD011_*.py`: MODIFY (conditional)
- `packages/toolkit/tests/docs/test_phase6_docs_updated.py`: CREATE (Tests 1–4)

### Step 6.3 — REFACTOR

- Cross-check that any internal links between README, CLAUDE.md, and the plan docs still resolve.
- Move this plan from `docs/plans/active/nemoclaw-canonical-integration/` to `docs/plans/completed/nemoclaw-canonical-integration/` as the final step (per `docs/plans/CLAUDE.md` § Completing the Implementation).

---

## Implementation Details

### Edge Cases to Handle

- **`INV-D011` promotion declined**: if Phase 5 surfaced any case where a plugin legitimately needs a non-canonical path (e.g. a system-level integration), document the rejection in work-notes and remove the provisional `test_invD011_*` test rather than promoting.
- **README contains pre-existing examples** that grep matches incidentally: tune the test regex to target the canonical-path *recommendation* sections, not every mention.

### Error Handling

- If documentation tests pass but actual surface check from Phase 5 silently regressed (e.g. dashboard URL stopped resolving between Phase 5 and Phase 6), back out the doc changes and re-investigate. Don't claim a working setup in docs that doesn't work.

### Privacy / Egress Notes

- Documentation updates don't introduce new egress. The README's troubleshooting section MAY add a note about NemoClaw credential storage (file path + permissions) so users know where their key lives. That's informative, not action-triggering.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [README.md](../../../../README.md) | MODIFY | § Sandbox setup, § Running the Agent Locally, § Troubleshooting |
| [CLAUDE.md](../../../../CLAUDE.md) | MODIFY | § Running the Agent Locally |
| [.claude/agents/test-engineer.md](../../../../.claude/agents/test-engineer.md) | MODIFY | Remove docker-exec workaround references |
| [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) | MODIFY (conditional) | Add `INV-D011` |
| `packages/toolkit/tests/docs/test_phase6_docs_updated.py` | CREATE | Tests 1–4 (doc content gates) |
| `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` | MODIFY (conditional) | Promote provisional to permanent |
| Plan directory | MOVE | `active/` → `completed/` |

---

## Verification

```bash
# Phase 6 doc tests
uv --project packages/toolkit run pytest packages/toolkit/tests/docs/test_phase6_docs_updated.py -v

# Conditional INV-D011 tests
uv --project packages/toolkit run pytest packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py -v

# Full suite final pass
uv --project packages/toolkit run pytest packages/toolkit/tests/ -v

# Muscle-question regression smoke (catch doc-driven runtime regressions)
GENOMECLAW_REPLAY_LLM=1 ./scripts/ask.sh --capture \
  "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."

# Final plan move (only after all above green)
git mv docs/plans/active/nemoclaw-canonical-integration docs/plans/completed/nemoclaw-canonical-integration
```

---

## Completion Criteria

- [ ] README § Sandbox setup + § Running the Agent Locally + § Troubleshooting updated
- [ ] CLAUDE.md § Running the Agent Locally updated
- [ ] `.claude/agents/test-engineer.md` updated
- [ ] All four doc tests pass
- [ ] If `INV-D011` promoted: INVARIANTS.md updated; discovery test green; Version bumped
- [ ] Muscle-question regression smoke after doc edits: synthesized reply + LLM-judge clean
- [ ] Full test suite green
- [ ] `work-notes.md` final Phase 6 entry written
- [ ] `development-plan.md` Status set to **Complete** + Progress Tracking table all green
- [ ] Plan directory moved from `active/` to `completed/`
