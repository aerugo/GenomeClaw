# Phase 3: `SiblingMountablePath` + factory + `compute_prs_with_coverage_fill` migration

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Introduce a validated `Path` subclass `SiblingMountablePath` constructed by an `as_sibling_mountable(path)` factory; migrate the DooD-bound wrappers (`_write_pgsc_calc_samplesheet`, `compute_prs_with_coverage_fill`, anything that hands a path to a sibling-container's `-v <host>:<container>` arg) to consume it; surface `DooDPathError` at the boundary so a container-local `/tmp/...` path is rejected typed + at runtime BEFORE bcftools or pgsc_calc runs.

The Phase-5 smoke v3 surfaced this class of bug: the orchestrator staged the merged VCF at `/tmp/genomeclaw-scratch/...` (container-local) and pgsc_calc's siblings couldn't see it. The bug class is "passing a non-host-visible path into a DooD-spawned tool"; after Phase 3, the same class of mistake fails fast with a typed exception naming a fix (move the path to a sibling-mountable location).

Phase 3 promotes **INV-D006** (DooD-Safe Path Annotation).

## Scope Boundaries

- **In scope**:
  - `_paths.py` module exposing `SiblingMountablePath` (Path subclass), `as_sibling_mountable(path)` factory, `DooDPathError` exception.
  - Migration of `_write_pgsc_calc_samplesheet`: the `vcf` parameter typed as `SiblingMountablePath`.
  - Migration of `compute_prs_with_coverage_fill` (in `coverage_fill.py`): `vcf`, `work_dir`, `reference_root` typed as `SiblingMountablePath`.
  - Migration of `shard_scratch(...)` (in `scratch.py`): return type `SiblingMountablePath` (the `_scratch/` canonical mount is host-visible).
  - `ephemeral_scratch_base()` docstring + `# DooD-unsafe` marker (negative case; stays `Path`).
  - Unit + integration + invariant tests.
- **Out of scope**:
  - Migrating other wrappers (`_bcftools`, `_vep`, etc.) until they need DooD; today only pgsc_calc-bound paths matter for the orchestrator.
  - `compute_pgs` itself (already passes `vcf` to `_write_pgsc_calc_samplesheet`; the type tightening propagates one level up — typed-checked from the orchestrator down).
  - Doc rollup — Phase 4 lifts INV-D006 into INVARIANTS.md.
  - Real-tool smoke re-run — Phase 5.

## Invariants Enforced in This Phase

- **INV-D006** (NEW) — DooD-bound wrappers' path-typed parameters annotate `SiblingMountablePath`; factory rejects ephemeral-scratch and container-local paths; runtime guard raises `DooDPathError` with a fixable message.

Existing invariants preserved:
- **INV-D001** (raw RO) — factory does not bypass; `SiblingMountablePath` over a raw path inherits the read-only-mount semantics from the shim.
- **INV-D003** (scratch separated) — `ephemeral_scratch_base()` stays the negative case (container-local, NOT sibling-mountable); the factory rejects it.
- **INV-D005** — Phase 1's identical-path overlay is what makes a `SiblingMountablePath` host-visible in the first place. INV-D006 enforces wrappers consume them; INV-D005 enforces the mounts are wired.

---

## TDD Steps

### Step 3.1 — RED: Write failing tests

**Test cases**:

1. `test_sibling_mountable_path_factory_accepts_canonical_raw_path` — `as_sibling_mountable(canonical_root / "raw" / "x.cram")` returns a `SiblingMountablePath`; the resulting object IS a `Path` (subclass invariant); `isinstance(x, SiblingMountablePath) is True`.
2. `test_sibling_mountable_path_factory_accepts_canonical_derived_path` — same but for `derived/`.
3. `test_sibling_mountable_path_factory_accepts_canonical_scratch_path` — same but for `_scratch/`.
4. `test_sibling_mountable_path_factory_accepts_canonical_reference_path` — same but for `reference/`.
5. `test_sibling_mountable_path_factory_rejects_ephemeral_scratch_path` — `as_sibling_mountable(Path("/tmp/genomeclaw-scratch/x"))` raises `DooDPathError` mentioning "ephemeral_scratch_base" and "not visible to sibling containers". The smoke v3 reproducer.
6. `test_sibling_mountable_path_factory_rejects_container_local_path` — `as_sibling_mountable(Path("/var/lib/something/x"))` raises `DooDPathError`. Generic container-local case.
7. `test_sibling_mountable_path_dood_path_error_carries_fix_hint` — the raised exception's `args[0]` references how to fix (`shard_scratch(...)`, `work_dir`, or the canonical mount roots).
8. `test_write_pgsc_calc_samplesheet_rejects_bare_path_for_vcf` — passing `Path(...)` (not `SiblingMountablePath`) to `_write_pgsc_calc_samplesheet(vcf=...)` raises `DooDPathError` (the factory is called at the boundary so a runtime-wrapped check fires).
9. `test_compute_prs_with_coverage_fill_rejects_non_sibling_vcf` — `compute_prs_with_coverage_fill(vcf=tmp_path / "tmp" / "merged.vcf.gz", ...)` raises `DooDPathError` BEFORE any bcftools / pgsc_calc subprocess fires (assert via `subprocess.run` patch's `call_count == 0`).
10. `test_shard_scratch_returns_sibling_mountable_path` — `shard_scratch(...)` return value `isinstance(result, SiblingMountablePath) is True`.
11. `test_ephemeral_scratch_base_returns_bare_path_documented_as_dood_unsafe` — `ephemeral_scratch_base()` returns `Path` (not `SiblingMountablePath`); the docstring contains "NOT sibling-mountable" or similar (regex check).
12. `test_invD006_dood_safe_path_annotation_walks_wrappers` — the invariant test. Uses `inspect.signature` to walk `_write_pgsc_calc_samplesheet`, `compute_prs_with_coverage_fill`, asserts the `vcf` / `work_dir` / `reference_root` parameter annotations are `SiblingMountablePath`. Fails if a future contributor downgrades a parameter to bare `Path`.
13. `test_mypy_rejects_bare_path_where_sibling_mountable_required` — a fixture `.py` file at `tests/fixtures/mypy_red/bare_path_to_write_pgsc_calc_samplesheet.py` is run through `subprocess.run(["mypy", "--strict", path])` + asserts rc=1 + error message. Marked `@pytest.mark.needs_mypy` since mypy must be installed. (Optional — see Decision 3 below.)

**Sketch**:

```python
# tests/unit/test_sibling_mountable_path.py
import pytest
from pathlib import Path

from genomeclaw_toolkit.prep._paths import (
    SiblingMountablePath,
    as_sibling_mountable,
    DooDPathError,
)

def test_factory_accepts_canonical_raw_path(canonical_root: Path) -> None:
    target = canonical_root / "raw" / "x.cram"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    result = as_sibling_mountable(target)
    assert isinstance(result, SiblingMountablePath)
    assert isinstance(result, Path)
    assert result == target

def test_factory_rejects_ephemeral_scratch_path() -> None:
    with pytest.raises(DooDPathError, match="ephemeral_scratch_base"):
        as_sibling_mountable(Path("/tmp/genomeclaw-scratch/foo"))
```

**Confirm failure**: tests fail with `ModuleNotFoundError: No module named 'genomeclaw_toolkit.prep._paths'`. Paste output into [work-notes.md](../work-notes.md) under a "Phase 3 RED" section.

### Step 3.2 — GREEN: Minimal Implementation

**Files created**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py` — the type + factory + exception.

**Module shape** (illustrative):

```python
# _paths.py
from __future__ import annotations
from pathlib import Path

class DooDPathError(ValueError):
    """A path bound for a DooD-spawned sibling cannot be sibling-mountable.

    Surfaces at the wrapper boundary so a non-host-visible path fails BEFORE
    bcftools / pgsc_calc / nextflow runs.
    """


class SiblingMountablePath(Path):
    """A ``Path`` validated as visible on the host filesystem.

    Constructed via :func:`as_sibling_mountable`. Carrying this type signals
    that the path is rooted under a canonical (or identical-path-overlayed)
    mount and is safe to write into a DooD sibling's ``-v <host>:<container>``
    invocation.
    """


# Canonical sibling-mountable prefixes. Each one is either:
#  - A canonical mount root the shim establishes (``/mnt/genomeclaw/raw``, etc.), OR
#  - A host-visible deployment root (e.g., ``/Volumes/Genome_Work/genomeclaw``)
#    surfaced via the INV-D005 identical-path overlay.
_SIBLING_MOUNTABLE_PREFIXES: tuple[Path, ...] = (
    Path("/mnt/genomeclaw"),
    # Deployment-specific roots from the shim are appended at call time via
    # an environment variable populated by the shim (GENOMECLAW_HOST_ROOTS).
)


def as_sibling_mountable(p: Path) -> SiblingMountablePath:
    """Validate ``p`` is host-visible; return a :class:`SiblingMountablePath`.

    Raises:
        DooDPathError: when ``p`` is rooted under ephemeral scratch
            (``/tmp/genomeclaw-scratch``) or a non-host-visible location.
    """
    p = p.resolve()
    if str(p).startswith("/tmp/genomeclaw-scratch"):
        raise DooDPathError(
            f"{p} is rooted under ephemeral_scratch_base() (container-local) "
            "and is NOT visible to sibling containers spawned via DooD. "
            "Use shard_scratch(...) for paths that must flow to pgsc_calc / "
            "bcftools siblings."
        )
    prefixes = list(_SIBLING_MOUNTABLE_PREFIXES)
    for env_root in (os.environ.get("GENOMECLAW_HOST_ROOTS") or "").split(":"):
        if env_root:
            prefixes.append(Path(env_root))
    if not any(_is_relative_to(p, prefix) for prefix in prefixes):
        raise DooDPathError(
            f"{p} is not under any sibling-mountable prefix "
            f"({[str(x) for x in prefixes]}). Either mount it via the shim's "
            "identical-path overlay or relocate to a canonical mount."
        )
    return SiblingMountablePath(p)
```

**Migrations**:
- `pgs.py:_write_pgsc_calc_samplesheet(vcf: SiblingMountablePath, ...)` — `vcf` parameter retype.
- `coverage_fill.py:compute_prs_with_coverage_fill(vcf: SiblingMountablePath, work_dir: SiblingMountablePath, reference_root: SiblingMountablePath, ...)` — three retypes.
- `scratch.py:shard_scratch(...) -> SiblingMountablePath` — return retype + add `as_sibling_mountable()` wrap at return site.
- `scratch.py:ephemeral_scratch_base()` — docstring update with explicit "NOT sibling-mountable" marker.

**Pattern**: the factory is called at the orchestrator (boundary) before the wrappers run; wrappers just declare the type. CLI subcommand wrap inputs via `as_sibling_mountable(vcf)` and pass the result down.

### Step 3.3 — REFACTOR: Clean Up

- Co-locate `_paths.py` alongside `_pgsc_calc_conventions.py` under `prep/`.
- Ensure `DooDPathError` inherits `ValueError` (subclass of the existing exception hierarchy — caller code that catches `ValueError` still works).
- Ruff + mypy clean.
- Add the `GENOMECLAW_HOST_ROOTS` env var to the shim (one-line `--env` add); document in [bin/genomeclaw](../../../../bin/genomeclaw).

---

## Files

| Action | Path | Purpose |
| --- | --- | --- |
| CREATE | `packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py` | `SiblingMountablePath`, `as_sibling_mountable`, `DooDPathError` |
| CREATE | `packages/toolkit/tests/unit/test_sibling_mountable_path.py` | Factory accept/reject + DooDPathError surface (tests 1–7) |
| CREATE | `packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py` | End-to-end rejection (test 9) |
| CREATE | `packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py` | Walks wrappers asserting annotations (test 12) |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | `_write_pgsc_calc_samplesheet(vcf: SiblingMountablePath, ...)` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py` | `compute_prs_with_coverage_fill` parameter retype |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py` | `shard_scratch` return retype + `ephemeral_scratch_base` docstring |
| MODIFY | `bin/genomeclaw` | Append `--env GENOMECLAW_HOST_ROOTS=<canonical_root>` |

## Verification

Run from `packages/toolkit/`:

```bash
uv run pytest tests/unit/test_sibling_mountable_path.py \
              tests/integration/test_compute_prs_rejects_non_sibling_path.py \
              tests/invariants/test_invD006_dood_safe_path_annotation.py -v
uv run pytest tests/unit tests/integration tests/invariants -x       # full suite
uv run ruff check src/genomeclaw_toolkit/prep tests
uv run mypy src/genomeclaw_toolkit/prep/_paths.py src/genomeclaw_toolkit/prep/pgs.py
```

## Completion Criteria

- [ ] Tests 1–12 (the 13th is optional, see Decision 3) green.
- [ ] Existing `test_pgsc_calc_wrapper.py` + `test_prs_coverage_fill_*.py` still green (the factory boundary may surface in their fixtures).
- [ ] Smoke v3 reproducer (orchestrator stages VCF at `/tmp/genomeclaw-scratch/...`) raises `DooDPathError` BEFORE any subprocess fires.
- [ ] Full toolkit suite green; ruff clean; mypy clean on `_paths.py` + `pgs.py`.
- [ ] [work-notes.md](../work-notes.md) Phase 3 entry written.
- [ ] `development-plan.md` Progress Tracking table updated.
- [ ] `phases/phase-4.md` scaffold created (Phase 4 = doc rollup).

## Open Decisions for the Implementer

1. **Should `SiblingMountablePath` inherit from `Path` or be a `NewType`?** Recommendation: subclass. `NewType` loses the runtime Path API (`.parent`, `.exists()`, etc.); callers would need to wrap/unwrap constantly. Subclassing keeps the Path API while adding the type marker.
2. **Where does `GENOMECLAW_HOST_ROOTS` come from?** The shim already knows the canonical_root from the DooD overlay logic (Phase 1); pass it through as an env var. Inside the container, the factory reads it. If unset (native mode, tests), the factory falls back to `_SIBLING_MOUNTABLE_PREFIXES` only.
3. **Test 13 (mypy strict check) — keep or drop?** Recommendation: drop from initial Phase-3 deliverable. The discovery test (test 12) walks runtime signatures and catches downgrades; an `.mypy_red/` fixture file run through subprocess adds CI complexity for marginal incremental coverage. Promote to a follow-up only if a CI bug slips through test 12.
4. **`as_sibling_mountable` recurses or only checks the immediate path?** Recommendation: only the immediate path. The factory's contract is "this specific path is mountable"; recursion is the caller's concern (orchestrator validates the inputs it constructs).
5. **What about colima virtiofs visibility quirks?** Recommendation: documented in the factory docstring, but not runtime-enforced. The shim's `INV-D005` overlay already establishes the mount; if the virtiofs layer drops the file later, that's an environment bug, not a wrapper bug. Add a smoke-trace note if it surfaces in Phase 5.
