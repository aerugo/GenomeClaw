# Phase 1: Identical-Path Bind Mounts in the Shim

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Make the toolkit container see every host path that may flow into a DooD sibling at its identical absolute path. This is the report's §6 priority-1 recommendation: lowest friction (one shim edit), biggest immediate win (unblocks Phase 5 + any future Nextflow-based subcommand). The change is additive — non-DooD subcommands keep today's mount shape and pay no cost.

Phase 1 promotes **INV-D005** (Identical-Path Bind Mounts for Sibling Containers).

## Scope Boundaries

- **In scope**:
  - `bin/genomeclaw` modifications: `GENOMECLAW_DOOD=1` env var, auto-set for DooD-spawning subcommands, additive identical-path overlay mount.
  - Longest-common-prefix detection logic over the four `*_DIR` paths.
  - Four-separate-overlays fallback for split-tree deployments.
  - Tests: shim integration test (both modes) + invariant test (walks the docker invocation).
- **Out of scope**:
  - `DooDPathError` typed exception (Phase 3 owns it).
  - `SiblingMountablePath` type (Phase 3 owns it).
  - Per-wrapper migration to the new types (Phase 3).
  - `PgscCalcConventions` dataclass (Phase 2).
  - INVARIANTS.md edits (Phase 4 lifts the proposed text from `development-plan.md` once Phase 1's test is green).

## Invariants Enforced in This Phase

- **INV-D005** (NEW) — every host path that may flow to a sibling is mounted at its identical absolute path in the parent container when `GENOMECLAW_DOOD=1`. The new tests are the verification surface; the rule's text is in `development-plan.md` §"Proposed Invariant Texts" and lands in INVARIANTS.md in Phase 4.

The phase also keeps **INV-D001** intact: the overlay mount of `raw/` (or the common-prefix overlay that covers it) is `:ro`, byte-equivalent to the canonical `/mnt/genomeclaw/raw,readonly` mount.

---

## TDD Steps

### Step 1.1 — RED: Write failing tests

**Test cases**:

1. `test_shim_no_overlay_when_dood_env_unset` — without `GENOMECLAW_DOOD=1` (and without a DooD-auto-set subcommand), the shim's docker invocation contains only the canonical four mounts. Byte-for-byte same as today.
2. `test_shim_adds_identical_path_overlay_when_dood_env_set` — with `GENOMECLAW_DOOD=1`, the docker invocation contains an additional `--mount type=bind,source=${canonical_root},target=${canonical_root}` entry where `${canonical_root}` is the longest common prefix of the four `*_DIR` paths.
3. `test_shim_auto_sets_dood_env_for_pipeline_prs_compute` — invoking the shim as `bin/genomeclaw pipeline prs-compute ...` causes the overlay to appear, even without the env var explicitly set.
4. `test_shim_keeps_today_shape_for_pipeline_ingest` — invoking the shim as `bin/genomeclaw pipeline ingest ...` (a non-DooD subcommand) does NOT add the overlay, matching the negative case in `test_1`.
5. `test_shim_falls_back_to_four_overlays_when_no_common_prefix` — with four `*_DIR` env vars set to paths with no common prefix above `/`, the shim adds four separate identical-path overlay mounts instead of one. Asserts none is `/` itself.
6. `test_shim_overlay_raw_remains_readonly` — the overlay mount that covers `${raw_dir}` is `:ro`; passes the docker daemon's mount-consistency check (no RO/RW conflict with the canonical `/mnt/genomeclaw/raw,readonly` mount).
7. `test_invD005_dood_subcommand_sibling_host_paths_visible` (invariant test) — for the `pipeline prs-compute` subcommand, walks the shim's docker invocation, collects every host path that downstream code may pass to a DooD sibling (i.e., the four canonical roots + their common prefix), and asserts each is bind-mounted at its identical absolute path.
8. `test_shim_smoke_v5_reproducer` — the exact failure shape from smoke v5 (sibling container told to mount `/mnt/genomeclaw/scratch/pgsc_calc_work/...`; host daemon resolves against host FS where `/mnt/genomeclaw/` doesn't exist). With Phase 1 in place, the sibling sees the path via the identical-path overlay route. (This is the load-bearing regression test — if it passes, smoke v5 cannot recur in this shape.)

**Sketch** (Python; the shim tests run the shim under a stubbed `docker` binary that records argv):

```python
# tests/integration/test_shim_identical_path_mounts.py

def test_shim_no_overlay_when_dood_env_unset(tmp_path, fake_docker, canonical_layout):
    """Without GENOMECLAW_DOOD=1 and non-DooD subcommand: today-shape mounts."""
    # Arrange: canonical_layout fixture sets up /tmp/.../genomeclaw/{raw,reference,derived,_scratch}/
    env = dict(os.environ, GENOMECLAW_RAW_DIR=str(canonical_layout / "raw"), ...)
    # Act:
    subprocess.run(["bin/genomeclaw", "pipeline", "ingest", "--help"], env=env)
    # Assert: fake_docker.recorded_argv contains exactly the four canonical mounts
    mounts = parse_mount_args(fake_docker.recorded_argv)
    assert len(mounts) == 4
    assert not any(m.target == m.source for m in mounts)

def test_shim_adds_identical_path_overlay_when_dood_env_set(tmp_path, fake_docker, canonical_layout):
    """With GENOMECLAW_DOOD=1: canonical four + one common-prefix overlay."""
    env = dict(os.environ, GENOMECLAW_DOOD="1", GENOMECLAW_RAW_DIR=...)
    subprocess.run(["bin/genomeclaw", "pipeline", "ingest", "--help"], env=env)
    mounts = parse_mount_args(fake_docker.recorded_argv)
    overlay = [m for m in mounts if m.source == m.target]
    assert len(overlay) == 1
    assert str(overlay[0].source) == str(canonical_layout)

def test_invD005_dood_subcommand_sibling_host_paths_visible(canonical_layout, fake_docker):
    """INV-D005: every host path that may flow to a DooD sibling has an identical-path mount."""
    subprocess.run(["bin/genomeclaw", "pipeline", "prs-compute", "--help"], env={"GENOMECLAW_RAW_DIR": ...})
    mounts = parse_mount_args(fake_docker.recorded_argv)
    # Every canonical *_DIR must be reachable at its host absolute path:
    for path_dir in [canonical_layout / d for d in ("raw", "reference", "derived", "_scratch")]:
        assert any(
            m.source == path_dir and (m.target == path_dir or (canonical_layout in m.source.parents and m.source == m.target))
            for m in mounts
        ), f"INV-D005: no identical-path mount covering {path_dir}"
```

**Confirm failure**: each test asserts a behaviour the current shim does not implement. The RED step is complete when:
- Tests 1, 4 PASS (today-shape still holds for non-DooD)
- Tests 2, 3, 5, 6, 7, 8 FAIL with diagnostic messages that name the missing overlay

Paste the failing output verbatim into `work-notes.md` under a "Phase 1 RED" section.

### Step 1.2 — GREEN: Minimal Implementation

**Implementation strategy**:

1. **Detect DooD subcommands in the shim**. Today the shim has a `case "${1:-}" in host) ...` block that auto-sets `GENOMECLAW_NATIVE=1`. Add a parallel block for DooD:
   ```bash
   case "${1:-}${2:+ }${2:-}" in
     "pipeline prs-compute"|"pipeline prs-prepare-coverage")
       : "${GENOMECLAW_DOOD:=1}"
       ;;
   esac
   ```
   (Names exact subcommands rather than a wildcard so a future contributor adding a new DooD subcommand explicitly opts in.)

2. **Compute the longest common prefix of the four `*_DIR` paths**. Pure bash:
   ```bash
   compute_common_prefix() {
     local first="$1"; shift
     local common="$first"
     for p in "$@"; do
       while [[ "$p" != "$common"* ]]; do
         common="${common%/*}"
         [[ "$common" == "" ]] && { echo ""; return; }
       done
     done
     echo "$common"
   }
   ```
   Refuse to mount `/` itself (the empty/single-slash result triggers the four-overlay fallback).

3. **Build the overlay mounts**:
   ```bash
   if [[ "${GENOMECLAW_DOOD:-0}" == "1" ]]; then
     common_root="$(compute_common_prefix "$raw_dir" "$ref_dir" "$derived_dir" "$scratch_dir")"
     if [[ -n "$common_root" && "$common_root" != "/" ]]; then
       # Single overlay covers all four. RO required because raw/ is inside it.
       mounts+=("--mount" "type=bind,source=${common_root},target=${common_root},readonly")
       # Plus a writable nested overlay for derived/ and scratch/ within the common root.
       # Docker resolves nested mounts source-first, so the inner RW overlays take precedence.
       mounts+=("--mount" "type=bind,source=${derived_dir},target=${derived_dir}")
       mounts+=("--mount" "type=bind,source=${scratch_dir},target=${scratch_dir}")
       # NOTE: ref_dir stays RO via the outer overlay; raw_dir is RO via both layers.
     else
       # No common prefix — four separate identical-path mounts.
       mounts+=("--mount" "type=bind,source=${raw_dir},target=${raw_dir},readonly")
       mounts+=("--mount" "type=bind,source=${ref_dir},target=${ref_dir},readonly")
       mounts+=("--mount" "type=bind,source=${derived_dir},target=${derived_dir}")
       mounts+=("--mount" "type=bind,source=${scratch_dir},target=${scratch_dir}")
     fi
   fi
   ```

4. **Verify mount-flag consistency**. Add a sanity-check pass that asserts no two mount entries with the same source path have conflicting readonly flags. (Docker would reject otherwise; better to fail fast with a clear message.)

**Files affected**:
- `bin/genomeclaw` — additive changes only. The today-shape mount block stays in place.

### Step 1.3 — REFACTOR

With tests green:

- Extract `compute_common_prefix` into a documented helper function with a leading comment block citing INV-D005 by ID.
- Extract the overlay-construction logic into a `build_dood_overlay_mounts` helper that takes the four `*_DIR` paths and emits the mount-arg lines.
- Add a one-line `genomeclaw: DOOD=1 → adding identical-path overlay for $common_root` debug message gated on `GENOMECLAW_DEBUG=1` (the existing debug hook).
- Re-run all phase tests after each refactor step. Re-run shellcheck.

---

## Implementation Details

### Edge Cases to Handle

- **`$HOME`-rooted canonical paths**. The user's `~/.colima/default/colima.yaml` must list every overlay source under `mounts:` (per architecture.md §"Engine VM file-sharing"). The shim does not validate colima's config; that's `genomeclaw host doctor`'s job. The overlay mount itself doesn't fail if colima isn't configured — docker simply binds whatever path the engine VM exposes (which may be empty). Phase 3's `as_sibling_mountable` factory is the surface that catches this — until Phase 3 lands, users on a misconfigured colima see Phase-5-style failures.
- **Symlinks**. The shim already calls `pwd -P` on `$derived_dir` and `$scratch_dir` for the INV-D003 nested-check. Same canonicalization applies to the overlay sources; otherwise a symlinked `~/derived` and a real-path `/Users/.../derived` look like different mount sources.
- **`reference/` write window during `refs fetch`**. Today the shim drops the `readonly` flag on the `reference/` canonical mount when `$1 $2 == "refs fetch"`. The Phase 1 overlay does NOT add an overlay for `refs fetch` (which is not a DooD subcommand). No conflict.
- **`GENOMECLAW_OFFLINE=1`**. Today's `--network none` flag stays as-is; Phase 1 does not touch the network surface.

### Error Handling

- **Docker mount-source duplication with conflicting flags**: the sanity-check pass above raises `genomeclaw: overlay mount RO/RW conflict on source ${path}` and exits 2. Tested by `test_shim_overlay_raw_remains_readonly`.
- **`compute_common_prefix` returns `/` or empty**: fall back to four separate overlays. Logged at debug level: `genomeclaw: DOOD=1 → no common prefix, using four overlays`. Tested by `test_shim_falls_back_to_four_overlays_when_no_common_prefix`.
- **`GENOMECLAW_DOOD=1` set explicitly by the user for a non-DooD subcommand**: respected. The user's explicit setting wins; the shim's auto-set is a default, not a clamp.

### Privacy / Egress Notes

- No new egress. The overlay is local mount machinery, fully within the host docker daemon. The OpenShell sandbox does not get DooD or any of these mounts (INV-D002).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [bin/genomeclaw](../../../../../bin/genomeclaw) | MODIFY | Add `GENOMECLAW_DOOD=1` auto-set + overlay mount construction |
| `packages/toolkit/tests/integration/test_shim_identical_path_mounts.py` | CREATE | Test cases 1–6, 8 |
| `packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py` | CREATE | Test case 7 (the INV-D005 invariant test) |
| `packages/toolkit/tests/conftest.py` | MODIFY | Add `fake_docker` fixture (stubbed `docker` binary that records argv); add `canonical_layout` fixture (creates a temp dir with the four canonical subdirs) |

---

## Verification

```bash
# Run this phase's tests
cd packages/toolkit
uv run pytest tests/integration/test_shim_identical_path_mounts.py -v
uv run pytest tests/invariants/test_invD005_identical_path_mounts.py -v

# Run all toolkit tests (regression check)
uv run pytest -v

# Shellcheck the shim
shellcheck bin/genomeclaw

# Manual smoke (non-blocking; for confidence, not for CI):
GENOMECLAW_DEBUG=1 GENOMECLAW_DOOD=1 \
  bin/genomeclaw pipeline ingest --help 2>&1 | grep -E '^genomeclaw:'
# Expected: debug line shows the additional --mount type=bind entries
```

For the Phase 5 smoke-equivalent re-run (validation, not phase-completion):

```bash
# Real-tool smoke against the project owner's CRAM (requires the canonical layout populated)
GENOMECLAW_DEBUG=1 \
  bin/genomeclaw pipeline prs-compute \
    --sample MPNRGLQ2K --pgs PGS000018 \
    --vcf /Volumes/Genome_Work/genomeclaw/derived/.../tier1_plus_tier2.vcf.gz
# Expected: no v5-shape failure; the merged-VCF path resolves on the sibling daemon
```

---

## Completion Criteria

- [ ] All eight test cases pass (1, 4 PASS at RED time; the remaining six PASS post-GREEN)
- [ ] Existing shim tests still green (no regressions)
- [ ] Shellcheck clean on `bin/genomeclaw`
- [ ] Each enforced invariant (INV-D005) is verified by `test_invD005_identical_path_mounts.py`
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures or repo
- [ ] `work-notes.md` updated with: (a) RED output verbatim, (b) any Q1–Q3 confirmations from the plan-review pass, (c) any deviations from this phase plan, (d) the manual-smoke output if run
- [ ] Phase status updated in [development-plan.md](../development-plan.md) Progress Tracking table
- [ ] `phases/phase-2.md` created from [templates/phase-template.md](../../../templates/phase-template.md)
