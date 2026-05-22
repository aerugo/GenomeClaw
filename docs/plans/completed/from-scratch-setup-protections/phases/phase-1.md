# Phase 1 — All five protections

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

## Invariants enforced in this phase

- **INV-D006** (DooD-Safe Path Annotation) — extended from wrapper-side annotation to shim-side propagation. New test `test_invD006_shim_dood_scan_exhaustive.py` enforces.
- **INV-T001** (External-Tool Conventions Captured as Typed Wrappers) — extended from argv pinning to plugin-load pinning. Extended `test_vep_loftee_plugin.py` enforces.

## TDD Steps

### Step 1.1 — RED

**Test cases**:

1. `test_invD006_shim_dood_scan_exhaustive` — walks every wrapper module under `prep/` that imports `as_sibling_mountable`; for each, traces the CLI subcommand bound to it via `@app.command(...)` in `_cli/commands/pipeline.py`; asserts each derived subcommand appears in `bin/genomeclaw`'s `_dood_scan_args()` regex list. Discovery loop:
   - AST-parse `pipeline.py` to enumerate `@app.command("<name>")` decorators + the wrapper they call.
   - For each wrapper, check whether it imports `as_sibling_mountable` from `prep._paths`.
   - If yes, the `<name>` must appear in the shim's `_dood_scan_args` body (parsed via regex against the bin/genomeclaw file).
   - Fail with a diff if any wrapper-using-as_sibling_mountable subcommand is missing from the shim's list.

2. `test_loftee_lof_plugin_instantiates_inside_image` — extension to the existing [test_vep_loftee_plugin.py](../../../../packages/toolkit/tests/integration/test_vep_loftee_plugin.py). Gated on `GENOMECLAW_SANDBOX_IMAGE` (or `GENOMECLAW_HAS_BIO=1`). Runs `vep --plugin LoF,/opt/vep/.vep/Plugins/LoF.pm --help` inside the toolkit image (or equivalent invocation that exercises LoF.pm's runtime `do '...'`-loaded modules). Asserts:
   - subprocess exits 0
   - stderr contains no "Failed to instantiate plugin LoF" line
   - stderr contains no "Can't locate DBD/SQLite.pm" line

3. **Pre-existing tests stay green**: full toolkit suite (`tests/unit tests/integration tests/invariants`) + plugin vitest. The protections must not regress anything.

**Expected RED**:
- Test 1 fails on current main: "_dood_scan_args missing subcommand: 'pgs-compute' (uses as_sibling_mountable via prep.pgs.compute_pgs)".
- Test 2 fails on current `genomeclaw/toolkit:slice-d-prime` image with the "Can't locate DBD/SQLite.pm" assertion failure.
- (Skipped on hosts without the env-var gates → tests still collect cleanly.)

### Step 1.2 — GREEN

**Files affected**:

1. `bin/genomeclaw` — add `pgs-compute` to the `_dood_scan_args()` regex list.

2. `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py` — extend the `DooDPathError` raised when no allowlist matches. Distinguish the empty-allowlist case (`GENOMECLAW_HOST_ROOTS=[]`, shim ran in non-DooD mode) from the un-allowlisted-prefix case. Empty-allowlist error message includes a fix hint that names the shim's scan function.

3. `packages/toolkit/Dockerfile` — add `perl-dbd-sqlite` to the `vep` stage's `micromamba install`. One-line addition next to the existing `perl-bioperl` + `perl-bio-bigfile` lines.

4. **Rebuild toolkit image** with the Dockerfile change: `docker build -t genomeclaw/toolkit:contract-drift-protected packages/toolkit/`. (Or re-tag as `slice-d-prime` to keep continuity with the rest of Phase 7's artifacts.)

5. Re-run the two new tests + the full suite → expect GREEN.

### Step 1.3 — REFACTOR

1. Tighten `test_invD006_shim_dood_scan_exhaustive`:
   - Cache the AST parse for clarity.
   - Sort outputs for stable diff reporting.
   - Add a short docstring naming the bug class + which Phase 7 session surfaced it.

2. Update [INVARIANTS.md](../../../../docs/reference/INVARIANTS.md) v1.14 → v1.15:
   - INV-D006 "Where it applies" + "How to verify" sections gain a bullet on shim-side propagation + cross-reference to the new test.
   - INV-T001 "How to verify" gains a bullet on plugin-load coverage + cross-reference to the extended `test_vep_loftee_plugin.py`.
   - Version stamp + Invariant Index unchanged (no new IDs).

3. Update [phase-7.md](../../../mvp/phases/phase-7.md) close-session-2 carry-forward list — mark these protections as landed.

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/invariants/test_invD006_shim_dood_scan_exhaustive.py` | CREATE | Meta-invariant for shim-side INV-D006 propagation |
| `packages/toolkit/tests/integration/test_vep_loftee_plugin.py` | MODIFY | Add the plugin-instantiation test (gated) |
| `bin/genomeclaw` | MODIFY | Add `pgs-compute` to `_dood_scan_args` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py` | MODIFY | Sharper `DooDPathError` for empty-allowlist case |
| `packages/toolkit/Dockerfile` | MODIFY | Add `perl-dbd-sqlite` to vep stage |
| `docs/reference/INVARIANTS.md` | MODIFY | v1.14 → v1.15 scope clarifications |
| `docs/plans/active/mvp/phases/phase-7.md` | MODIFY | Note protections landed |

## Verification

```bash
cd packages/toolkit

# 1. Confirm RED on current main (before any code changes):
uv run pytest tests/invariants/test_invD006_shim_dood_scan_exhaustive.py -v
# Expect: FAIL (pgs-compute missing from shim's scan list)

GENOMECLAW_SANDBOX_IMAGE=genomeclaw/toolkit:slice-d-prime \
  uv run pytest tests/integration/test_vep_loftee_plugin.py::test_loftee_lof_plugin_instantiates_inside_image -v
# Expect: FAIL (DBD::SQLite missing)

# 2. Apply the four GREEN fixes (shim + paths + Dockerfile + rebuild image).
docker build -t genomeclaw/toolkit:slice-d-prime packages/toolkit/

# 3. Re-run both new tests:
uv run pytest tests/invariants/test_invD006_shim_dood_scan_exhaustive.py -v
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/toolkit:slice-d-prime \
  uv run pytest tests/integration/test_vep_loftee_plugin.py -v
# Expect: PASS

# 4. Full suite stays green:
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/toolkit:slice-d-prime \
  uv run pytest tests/unit tests/integration tests/invariants --no-header -q

# 5. ruff
uv run ruff check tests/invariants/test_invD006_shim_dood_scan_exhaustive.py \
                  src/genomeclaw_toolkit/prep/_paths.py
```

## Completion Criteria

- [ ] `test_invD006_shim_dood_scan_exhaustive` passes (after shim fix).
- [ ] `test_loftee_lof_plugin_instantiates_inside_image` passes (after Dockerfile fix + image rebuild).
- [ ] Full toolkit suite remains green.
- [ ] ruff clean on touched files.
- [ ] `bin/genomeclaw` shim's `_dood_scan_args` includes `pgs-compute`.
- [ ] `DooDPathError` for the empty-allowlist case distinguishes the cause + names the shim's `_dood_scan_args` function in the fix hint.
- [ ] `packages/toolkit/Dockerfile` carries `perl-dbd-sqlite` in the vep stage.
- [ ] INVARIANTS.md v1.15 published.
- [ ] phase-7.md close-session-2 carry-forward list updated.
