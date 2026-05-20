# Phase 6: Close the four gaps surfaced by Phase 5 smoke

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Why this phase exists

The Phase 5 smoke against `MPNRGLQ2K.cram` was meant to be a final validation gate. Instead it surfaced **four distinct gaps** the discipline didn't catch. Each is honest evidence that the original three-layer model (shim overlay / wrapper boundary / tool conventions) was incomplete:

| # | Gap | Why the discipline missed it | Where it surfaced |
|---|-----|-----------------------------|-------------------|
| 1 | Smoke driver had a bespoke `docker run` that bypassed the shim with its own overlay + socket mount + `--user 0:0`. Pre-Phase-1 workaround, never migrated. | The plan's scope listed wrappers as migration targets, not scripts/drivers. | First failed smoke; the bypass had grown stale. |
| 2 | `SiblingMountablePath(Path)` works on Python 3.12+ natively but fails on 3.11 with `AttributeError: ... '_flavour'`. Tests ran on host venv (3.13); toolkit image runs 3.11. | Phase 3 completion was declared from host-venv green tests; production-Python execution was never gated. | Smoke v2 failed in 30s with the AttributeError. |
| 3 | Phase 1 added the path overlay but didn't mount `/var/run/docker.sock`, didn't adjust `--user` for socket access, and only scanned `$1 $2` for the auto-DooD case (missed `--json pipeline prs-compute …`). | Phase 1's scope was "identical-path bind mounts." DooD needs more than mounts. | Smoke v3/v4/v5 all failed in 30–90s with nextflow rc=1 + empty stderr. |
| 4 | `SiblingMountablePath` accepts `/mnt/genomeclaw/…` paths even though those exist only inside the toolkit container. The wrapper forwards them to Nextflow; siblings spawned by the host daemon receive a path that isn't on the host fs. | The factory matches on prefixes; both canonical-mount and host-form prefixes are accepted equivalently. The contract should be tighter. | Smoke v6 hit `EXTRACT_DATABASE` exit 127: `/bin/bash: /mnt/genomeclaw/.../...command.run: No such file`. |

Phase 6 closes all four. The discipline's three-layer model becomes **four layers**: the fourth is the "sibling-bound arguments MUST be host-form" rule, and the seam-singularity rule (shim is the only canonical invocation path) is promoted alongside it.

---

## Scope Boundaries

### In scope

1. **Factory tightening** (`as_sibling_mountable`):
   - Rejects canonical-mount paths (`/mnt/genomeclaw/…`). Raises `DooDPathError` with a message naming the host-form equivalent (computed from the shim-published mapping).
   - Accepts host-form paths under any prefix listed in the shim's structured env vars.
2. **Shim publishes a structured mapping** to the toolkit container:
   - `GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`, `GENOMECLAW_SCRATCH_DIR` are threaded through as `--env` flags (alongside the existing `GENOMECLAW_HOST_ROOTS` colon-list). The factory uses these to translate canonical-mount paths in the error message ("`/mnt/genomeclaw/scratch/foo` → use `${GENOMECLAW_SCRATCH_DIR}/foo` instead").
3. **Smoke driver fully migrated**:
   - Remove the bespoke `docker run` block (already partially done in Phase 5; ratify it).
   - Remove the host-form-path workaround variables added during Phase 5 debugging; the driver now passes the CANONICAL CLI argv (no special handling).
   - All paths it passes to the CLI are HOST-FORM only.
   - The driver is the canonical regression target for INV-D007.
4. **Production-python gate**:
   - New pytest marker `needs_prod_python`. Tests so marked are auto-skipped unless `GENOMECLAW_TOOLKIT_PRS_IMAGE` is set + `docker` is on PATH.
   - When set, the test runs the probe via `subprocess.run(["docker", "run", "--rm", image, "python", "-c", PROBE])` and asserts rc=0.
   - At least one such test per Phase that touches `prep/` source going forward; for Phase 6 specifically, one test per new factory/wrapper code path.
5. **Invariant texts**:
   - **INV-D006 tightened** (Phase 3 invariant): the "DooD-bound paths annotate `SiblingMountablePath`" rule stays, but the factory's acceptance criteria narrows to host-form paths only. Canonical-mount paths are rejected with a fixable hint.
   - **INV-D007 (NEW)**: "the host shim is the canonical seam for invoking the toolkit's DooD-spawning subcommands. Scripts that need to invoke such a subcommand MUST go through the shim; bespoke `docker run` invocations are prohibited." Verified by a discovery test that walks `bin/` + `scripts/` for `docker run` strings.

### Out of scope (explicit follow-up plans, not this phase)

- Auditing other CI workflows / dev scripts for bespoke `docker run` calls beyond `bin/genomeclaw-prs-smoke`. Separate one-shot grep audit.
- Increasing the colima VM resources to handle pgsc_calc's default resource request. The Phase 5 "resources exceed availability" warning is a Colima sizing concern, not a discipline issue.
- Translating canonical-mount paths to host-form silently (the option-B alternative the user rejected in favor of strict rejection). If user feedback later asks for translation, a follow-up plan reopens this.

### Invariants Affected

- **INV-D006** (tightened): see above.
- **INV-D007** (NEW): see above.
- The other Phase 3 invariants (INV-D005, INV-T001) are unaffected.

---

## TDD Steps

### Step 6.1 — RED

**Tests added (all expected to fail until Step 6.2):**

**A. Factory contract:**

1. `test_factory_rejects_canonical_mount_path`
   - `as_sibling_mountable(Path("/mnt/genomeclaw/scratch/foo"))` raises `DooDPathError`.
   - Message contains "/mnt/genomeclaw" + names the host-form equivalent (e.g., "use `${GENOMECLAW_SCRATCH_DIR}/foo` instead", which the test asserts when `GENOMECLAW_SCRATCH_DIR=/Volumes/.../foo`).

2. `test_factory_rejects_each_canonical_mount_subdir`
   - Parametrized over `raw`, `reference`, `derived`, `scratch`. Each `/mnt/genomeclaw/<sub>/x` raises `DooDPathError` whose message references the corresponding `GENOMECLAW_<SUB>_DIR` env var.

3. `test_factory_accepts_host_form_path` (regression cover)
   - `as_sibling_mountable(<host_form_path>)` accepts (paths under `GENOMECLAW_HOST_ROOTS`).

**B. Shim structured env-var publication:**

4. `test_shim_publishes_per_subdir_env_vars_for_dood`
   - Argv for `pipeline prs-compute` contains `--env GENOMECLAW_RAW_DIR=<raw_dir>` plus the three siblings.
   - Non-DooD subcommands don't carry these `--env` flags (minimal surface).

**C. Production-python gate:**

5. `test_prod_python_path_subclass_constructs_inside_image` (marked `needs_prod_python`)
   - Runs `docker run --rm "$IMAGE" python -c "from genomeclaw_toolkit.prep._paths import SiblingMountablePath; SiblingMountablePath('/tmp/x'); print('OK')"`.
   - Asserts rc=0 + stdout=="OK". This is the regression that would have caught the `Path`-subclass `_flavour` issue at Phase 3 completion.

6. `test_prod_python_factory_rejects_canonical_mount_inside_image` (marked `needs_prod_python`)
   - Same `docker run` shape, exercising the new rejection. Catches Python-version-skew in the factory itself.

**D. Smoke driver canonical:**

7. `test_smoke_driver_has_no_bespoke_docker_run`
   - `grep` for `docker run` in `bin/genomeclaw-prs-smoke` returns 0 matches.
   - The Phase 5 fallback (host-form variables, identical-path overlay bypass) is gone.

8. `test_smoke_driver_passes_host_form_paths_to_cli`
   - Static parse of the driver: every `--work-dir`, `--output-root`, `--reference-root` argument resolves to a path NOT prefixed with `/mnt/genomeclaw/…`.

**E. INV-D007 discovery:**

9. `test_invD007_no_bespoke_docker_run_in_repo_scripts`
   - Walks `bin/`. For every executable that's not `bin/genomeclaw` itself: `docker run` strings are forbidden unless the script is on a known-allowed-list. The allowed list starts empty.
   - The smoke driver is the first regression case. Future additions need to add themselves to the allow-list with a justification comment.

### Step 6.2 — GREEN: minimal implementation

**Files created:**
- `packages/toolkit/tests/unit/test_factory_rejects_canonical_mount.py` (tests 1–3)
- `packages/toolkit/tests/integration/test_shim_publishes_per_subdir_env.py` (test 4)
- `packages/toolkit/tests/integration/test_prod_python_smoke.py` (tests 5–6)
- `packages/toolkit/tests/integration/test_smoke_driver_canonical.py` (tests 7–8)
- `packages/toolkit/tests/invariants/test_invD007_seam_singularity.py` (test 9)

**Files modified:**
- `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py`:
  - Add `_CANONICAL_MOUNT_SUBDIRS = ("raw", "reference", "derived", "scratch")`.
  - Add `_host_root_for_canonical_subdir(sub: str) -> Path | None` that reads `GENOMECLAW_<SUB>_DIR`.
  - In `as_sibling_mountable`: detect canonical-mount paths first; raise `DooDPathError` with translated equivalent.
- `bin/genomeclaw`:
  - In the `dood_env_args` block, append `--env GENOMECLAW_RAW_DIR=$raw_dir`, etc.
- `bin/genomeclaw-prs-smoke`:
  - Delete the bespoke `docker run` block (already done in Phase 5).
  - Delete the `REF_ROOT_DOOD` / `OUTPUT_ROOT_DOOD` / `WORK_DIR_DOOD` host-form workaround vars; rename to the canonical `*_IN_CONTAINER` form OR leave the host-form vars but use them everywhere.
  - Decision: drop the `*_IN_CONTAINER` form entirely. Driver passes host paths to the CLI (which it always could, given Phase 1's overlay). Comment explains why.
- `packages/toolkit/tests/conftest.py`:
  - Add `pytest_collection_modifyitems` clause for `needs_prod_python` (skip unless `GENOMECLAW_TOOLKIT_PRS_IMAGE` set + `docker` on PATH).

### Step 6.3 — REFACTOR

- Verify the factory's error message is genuinely actionable. Sample wording: `"/mnt/genomeclaw/scratch/foo is a canonical-mount path; it exists only inside the toolkit container. DooD-spawned siblings cannot resolve it. Use the host-form equivalent: /Volumes/Genome_Work/genomeclaw/_scratch/foo (from GENOMECLAW_SCRATCH_DIR)."`
- Run ruff + mypy.
- Run the full suite. Expect 684 + 9 new tests ≈ 693 passed.
- Run `needs_prod_python` tests once with the image set (build the new image first; verifies the prod-python gate works against a real image).

---

## Files

| Action | Path | Purpose |
| --- | --- | --- |
| CREATE | `tests/unit/test_factory_rejects_canonical_mount.py` | Factory tests 1–3 |
| CREATE | `tests/integration/test_shim_publishes_per_subdir_env.py` | Test 4 |
| CREATE | `tests/integration/test_prod_python_smoke.py` | Tests 5–6 |
| CREATE | `tests/integration/test_smoke_driver_canonical.py` | Tests 7–8 |
| CREATE | `tests/invariants/test_invD007_seam_singularity.py` | Test 9 |
| MODIFY | `src/genomeclaw_toolkit/prep/_paths.py` | Factory tightening + canonical-mount rejection |
| MODIFY | `bin/genomeclaw` | Append per-subdir `--env` for DooD |
| MODIFY | `bin/genomeclaw-prs-smoke` | Remove bespoke `docker run` + host-form workaround |
| MODIFY | `tests/conftest.py` | `needs_prod_python` collection hook |

## Verification

```bash
# Unit + invariant suite:
uv run pytest tests/unit tests/integration tests/invariants --no-header
# Expected: ~693 passed (was 684 at end of Phase 5 shim fixes).

# Production-python gate, with image:
docker build -t genomeclaw/toolkit:phase6 -f packages/toolkit/Dockerfile packages/toolkit
GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:phase6 uv run pytest -m needs_prod_python
# Expected: 2 passed.
```

## Completion criteria

- [ ] All 9 new tests green; full suite still green; ruff clean; mypy clean on `_paths.py`.
- [ ] `needs_prod_python` gate exercised against a built image (proves the marker works end-to-end).
- [ ] `bin/genomeclaw-prs-smoke` contains zero `docker run` strings (INV-D007 first regression case).
- [ ] `work-notes.md` Phase 6 entry written, explicitly enumerating the four gaps + how each test prevents recurrence.
- [ ] `development-plan.md` Progress Tracking + Phase 6 row updated.
- [ ] `phase-7.md` scaffold drafted for the actual real-data smoke + final close-out.

---

## Open Questions for the Implementer

1. **What about pre-existing `_IN_CONTAINER` paths the smoke driver uses for non-DooD stages?**
   The driver's `prepare_coverage_tier1` stage (lines 273–280 in the smoke driver) passes `$CRAM_IN_CONTAINER` etc. to the shim. These never reach a DooD sibling — bcftools runs inside the toolkit container. They CAN stay in canonical-mount form. The decision: leave them as-is; only the DooD-bound stage is migrated. The driver's complexity stays minimal.

2. **Should the factory recognise the canonical mount via `os.path.realpath` resolution?**
   On colima, `/mnt/genomeclaw/scratch/foo` might `realpath` to `/Volumes/Genome_Work/genomeclaw/_scratch/foo` via the bind-mount layer. If the factory `realpath`s every input, it could rewrite canonical-mount paths to host-form automatically.

   Decision: NO. The whole point of (A) is to be loud + explicit. Silent rewriting is option (B), already rejected. Plus realpath behaviour on bind mounts is OS-dependent and would surprise readers later.

3. **How does the prod-python gate handle host venv mypy/ruff?**
   It doesn't — those keep running on the host venv as today. The gate is purely for runtime-Python-version verification of the prep/ source. Mypy and ruff are language-tooling, not runtime.

4. **Are there other DooD-spawning subcommands beyond `pipeline prs-compute` and `pipeline prs-prepare-coverage`?**
   Today, no. Future: `pipeline annotate` if it ever DooD-spawns VEP siblings (it doesn't today). The auto-DooD scan in the shim already enumerates explicitly; adding new ones is a one-line case-block edit.

5. **Should INV-D007's discovery test scan `tests/` too?**
   No — test fixtures often need to `docker run` arbitrary images (the `fake_docker` fixture in Phase 1 tests stubs the docker binary, doesn't itself run `docker run`). The discipline applies to runtime invocation scripts (`bin/`), not test infrastructure.
