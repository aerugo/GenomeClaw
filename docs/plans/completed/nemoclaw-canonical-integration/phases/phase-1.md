# Phase 1: Upstream Docs Audit + Path Target Confirmation

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Confirm — with upstream docs + a small in-container probe — the exact path NemoClaw expects for plugin install, whether `openclaw plugins install` needs to run after a file-drop, and whether `policy-preset.yaml` needs filesystem allowances added. Resolve spec open questions Q1 and Q2 before touching the Dockerfile.

## Scope Boundaries

- **In scope**: reading upstream NemoClaw + OpenShell docs; running a one-off probe container to observe `openclaw plugins list` behavior; recording the chosen target path in `work-notes.md`.
- **Out of scope**: Dockerfile rewrite (Phase 2); script changes (Phases 3–4); documentation cleanup (Phase 6).

## Invariants Enforced in This Phase

- **INV-V001** Verification Methodology — the probe verifies plugin discovery via `openclaw plugins list` (structured CLI output) and `ls -la /sandbox/.openclaw/extensions/` (structural), not via log-grepping.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases**:

1. `test_canonical_plugin_path_documented` — assert that `docs/plans/active/nemoclaw-canonical-integration/work-notes.md` § Decision-1 records the chosen target path + cites the upstream doc URL. This is a documentation-as-test discipline borrowed from how `docs/plans/CLAUDE.md` § G enforces decision recording. Fail-state: section absent or empty.
2. `test_phase1_probe_findings_recorded` — assert that `work-notes.md` § Phase 1 § Test Results contains the actual output of the probe commands (a) `docker run --rm <base-image-sha> openclaw plugins list` against a clean container, (b) `ls -la /sandbox/.openclaw/extensions/` after the test drop. Fail-state: results placeholder still says "(pending)".

(These are documentation-completeness tests, not Pytest. They're checks on the work product of this audit phase. Mechanically they're `grep -q` over `work-notes.md` for required headers + non-placeholder content.)

**Sketch** (shell-based; runs in `scripts/check-phase1-audit.sh` if we land it, otherwise manual):

```bash
# Test 1
grep -q "## Key Decisions" docs/plans/active/nemoclaw-canonical-integration/work-notes.md
grep -A 20 "### Decision 1: Plan target path" docs/plans/active/nemoclaw-canonical-integration/work-notes.md \
  | grep -q "/sandbox/.openclaw"

# Test 2
grep -A 5 "### Phase 1.*Test Results" docs/plans/active/nemoclaw-canonical-integration/work-notes.md \
  | grep -v "pending" | grep -q "openclaw plugins"
```

After writing the checks, run them and confirm they fail because the work-notes Phase 1 § Test Results block still says "(pending)". Paste the failing output into `work-notes.md` Step 1.1 RED output.

### Step 1.2 — GREEN: Minimal Implementation

The "implementation" for an audit phase is the audit itself:

1. Pull a clean copy of the pinned base image candidate:
   ```bash
   docker pull ghcr.io/nvidia/nemoclaw/sandbox-base@sha256:<digest-from-current-nemoclaw-CLI>
   ```
2. Probe what's already inside the base image:
   ```bash
   docker run --rm <image> ls -la /sandbox/.openclaw/extensions/
   docker run --rm <image> ls -la /sandbox/.openclaw-data/extensions/
   docker run --rm <image> openclaw plugins list
   ```
3. Probe what happens if you drop a minimal plugin via `cp` into `/sandbox/.openclaw-data/extensions/test-plugin/`:
   ```bash
   docker run --rm -v <test-plugin-dir>:/sandbox/.openclaw-data/extensions/test-plugin <image> openclaw plugins list
   ```
4. Probe what happens if you instead run `openclaw plugins install <path> --link` against a plugin baked at `/sandbox/.openclaw-data/extensions/test-plugin/`:
   ```bash
   docker run --rm <image> bash -c "openclaw plugins install /sandbox/.openclaw-data/extensions/test-plugin --link && openclaw plugins list"
   ```
5. Inspect `policy-preset.yaml` to determine whether `filesystem_policy` needs to mention the canonical path or whether the Landlock baseline already covers it.
6. Record findings + decision in `work-notes.md` § Phase 1 § Test Results and § Phase 1 § Notes.

**Files affected**:
- [docs/plans/active/nemoclaw-canonical-integration/work-notes.md](../work-notes.md): § Phase 1 § Test Results filled; § Decision 1 updated with concrete path + doc URL.

### Step 1.3 — REFACTOR

- Trim the work-notes entry to essentials. Move long log paste into a fenced code block.
- If the audit produced an obvious additional question worth tracking, append it to § Open Risks & Follow-ups.

---

## Implementation Details

### Edge Cases to Handle

- Base image SHA candidate doesn't exist on GHCR (404). → Fall back to inspecting the current `:latest` digest with `docker buildx imagetools inspect`; document mismatch.
- `openclaw plugins list` requires the gateway to be running. → Use `--local` flag or boot the gateway inside the probe container first.
- Probe needs `--user sandbox` or similar to match the runtime Landlock policy. → Reproduce the exact `nemoclaw connect` runtime context using `docker exec --user sandbox <name> ...` on an existing onboarded sandbox if a fresh-image probe is unrepresentative.

### Error Handling

- If `openclaw plugins list` returns empty after a clean file-drop, that confirms `openclaw plugins install` is still required → Phase 2 retains the install step.
- If `openclaw plugins list` shows `test-plugin` after a file-drop alone, file-drop is sufficient → Phase 2 drops the install step.

### Privacy / Egress Notes (if applicable)

- The probe container pulls from GHCR; that's the same egress already used by the existing build. No new egress.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [docs/plans/active/nemoclaw-canonical-integration/work-notes.md](../work-notes.md) | MODIFY | Record probe findings + finalized Decision 1 path |
| (optional) `scripts/check-phase1-audit.sh` | CREATE | Re-runnable audit verification script |

---

## Verification

```bash
# Run probe (one-off; paste output into work-notes.md)
docker pull ghcr.io/nvidia/nemoclaw/sandbox-base@sha256:<digest>
docker run --rm <image> ls -la /sandbox/.openclaw/extensions/ /sandbox/.openclaw-data/extensions/
docker run --rm <image> openclaw plugins list

# Verify audit completeness (Step 1.1 tests)
bash scripts/check-phase1-audit.sh    # if created
# OR manually:
grep -A 20 "### Decision 1: Plan target path" docs/plans/active/nemoclaw-canonical-integration/work-notes.md
grep -A 40 "### Phase 1.*Test Results" docs/plans/active/nemoclaw-canonical-integration/work-notes.md
```

---

## Completion Criteria

- [ ] Target plugin path confirmed (`/sandbox/.openclaw-data/extensions/genomeclaw/` or upstream-documented alternative)
- [ ] Q1 resolved: file-drop suffices, OR `openclaw plugins install` still required
- [ ] Q2 resolved: NemoClaw credential system has a non-interactive mode (or escalate)
- [ ] Probe output pasted into work-notes Phase 1 § Test Results
- [ ] Decision 1 in work-notes updated with concrete path + upstream doc URL
- [ ] No new files committed without a purpose (`scripts/check-phase1-audit.sh` only if it's worth keeping)
