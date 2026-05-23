# Phase 3 — Decide + execute (Path U / D / L)

**Status**: Pending (gated on Phase 1 + 2 producing classification + outcome)
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Based on the Phase 1 classification + Phase 2 cross-model outcome, execute exactly one resolution path:

- **Path U (upstream)**: file an openclaw GitHub issue / PR with the reproducer + classification.
- **Path D (document quirk)**: write a project-wide `docs/reference/agent-quirks.md` capturing the failure mode + workaround + trigger conditions.
- **Path L (local fix)**: ship a local plugin-side or sysprompt-side fix that recovers the agent's intent better than the current arg-guard.

Pick exactly one. Land it. Close the plan.

## Scope Boundaries

- **In scope**: the one path picked.
- **Out of scope**: parallel execution of multiple paths. If two paths look attractive, pick the one with the highest signal-to-effort ratio and defer the other to a follow-up plan.

## Invariants enforced in this phase

- **INV-P001** — if Path L modifies the plugin, no new egress surface.
- **No regression to `b8b7954`**'s runtime arg-guard — its 23 vitest pass throughout this phase.

---

## Path U — Upstream openclaw issue / PR

### When this path

Phase 2 Outcome A: alternative model exhibits same corruption → runtime-side bug.

### Steps

1. Distill `findings.md` into a focused openclaw issue body. The maintainers shouldn't need to re-investigate; the issue includes:
   - Minimal reproducer (script + sandbox image steps).
   - Classification + raw-payload diff.
   - Cross-model bisect data.
   - Suggested fix surface (if Phase 1 identified the parser line).
2. File the issue at `github.com/<openclaw repo>`.
3. If we can write the patch ourselves, submit a PR alongside the issue.
4. Update GenomeClaw's `findings.md` + work-notes with the issue URL.
5. The existing `b8b7954` arg-guard stays as the workaround.

### Acceptance

- Upstream issue (or PR) URL recorded in `findings.md`.
- Workaround stays in place — no GenomeClaw code change.

---

## Path D — Document the quirk

### When this path

Phase 2 Outcome B: alternative model has 0% corruption → gpt-5.5-specific.

### Steps

1. Create `docs/reference/agent-quirks.md` (NEW project-wide doc) with structure:

   ```markdown
   # Agent Quirks Reference

   ## gpt-5.5 tool-arg serialization (2026-05-23)

   **Symptom**: gpt-5.5 occasionally emits tool-call arguments as either:
   - the literal JS string `"undefined"` for required string fields, or
   - the OpenAI tool-call ID format (`call_xxx|fc_yyy`) as the entire args body
   ...

   **Trigger conditions**: <from Phase 1's classification>
   **Workaround**: see `nemoclaw-plugin/src/index.ts`'s `rejectIfPlaceholder` (commit b8b7954).
   **Status**: model-side quirk; no upstream openclaw fix expected.
   ```

2. Update `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`'s failure-mapping table to reference the quirks doc.

3. Optionally tighten the `rejectIfPlaceholder` error message to hint at the quirk + suggest the agent retry with explicit args structure.

### Acceptance

- `docs/reference/agent-quirks.md` exists + documents the quirk.
- Sysprompt references the quirks doc.
- No code change beyond the optional error-message tightening.

---

## Path L — Local fix

### When this path

Either Phase 2 surfaced a workaround openclaw exposes (e.g. a tool-arg recovery callback) OR the investigation identified a non-trivial plugin-side mitigation that recovers the agent's intent.

### Steps

1. Implement the local fix in the plugin (most likely) OR the sysprompt.
2. Add focused tests (vitest + at least one integration test that exercises the recovery path).
3. Update the sysprompt if the fix changes the agent's contract.
4. Rebuild sandbox image; verify the eyesight question's corruption-rate drops to near-zero.

### Acceptance

- Tests for the new fix path pass.
- Existing 23 vitest pass.
- Empirical verification: eyesight question reproducer's corruption rate drops by ≥80% vs Phase 1 baseline.

---

## Common close-out (any path)

- Update `findings.md` with the executed path + outcome.
- Update plan's `work-notes.md` with the final state.
- Update [agent-prs-compute-fix's completed work-notes](../../completed/agent-prs-compute-fix/work-notes.md) "Open follow-ups" section to mark `openclaw-toolcall-serialization` as resolved (Path U/D/L).
- Move this plan from `active/` to `completed/`.

---

## Files

Path-conditional. Common:

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/openclaw-toolcall-serialization-investigation/findings.md` | MODIFY | Final outcome recorded |
| `docs/plans/active/openclaw-toolcall-serialization-investigation/work-notes.md` | MODIFY | Phase 3 close block |
| `docs/plans/completed/agent-prs-compute-fix/work-notes.md` | MODIFY (light) | Mark openclaw follow-up resolved |
| Path D: `docs/reference/agent-quirks.md` | CREATE | The quirks doc |
| Path D: `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY (light) | Reference quirks doc |
| Path L: plugin / sysprompt diffs | MODIFY | The local fix |

---

## Verification

Path-conditional:

- **Path U**: link to upstream issue + reproducer in `findings.md`.
- **Path D**: `docs/reference/agent-quirks.md` exists; sysprompt references it.
- **Path L**: tests pass + empirical reproducer corruption rate dropped ≥80%.

---

## Completion Criteria

- [ ] Exactly one path executed.
- [ ] `findings.md` finalised.
- [ ] `work-notes.md` Phase 3 close block written.
- [ ] `agent-prs-compute-fix`'s open-follow-up list updated to mark this plan resolved.
- [ ] Plan moved from `active/` to `completed/`.

## Next

Plan closes after Phase 3. No further phases.
