"""Phase 3 — ``SiblingMountablePath`` + ``as_sibling_mountable`` factory.

Captures the "host paths that flow into DooD-spawned siblings must be visible
on the host filesystem" rule as a typed boundary. The Phase-5 smoke v3
surfaced this: the orchestrator staged a merged VCF at
``/tmp/genomeclaw-scratch/...`` (container-local); pgsc_calc's siblings
couldn't see it; nextflow failed with a confusing ``No such file`` against
a path that DID exist inside the parent container.

Phase 3 promotes ``INV-D006`` (DooD-Safe Path Annotation). The factory
rejects ephemeral-scratch + non-host-visible paths BEFORE any subprocess
runs; the type makes the wrapper's contract explicit to mypy.

Phase plan: [phases/phase-3.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-3.md)
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Test 1–4 — factory accepts every canonical mount root
# ---------------------------------------------------------------------------


@pytest.fixture
def canonical_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A fake canonical root staged under ``tmp_path``.

    Exposes ``raw/``, ``derived/``, ``_scratch/``, ``reference/`` under
    ``tmp_path/canonical_root/`` and sets ``GENOMECLAW_HOST_ROOTS`` so the
    factory recognises this root as host-visible. Mirrors the Phase-1
    shim's identical-path overlay surface.
    """
    root = tmp_path / "canonical_root"
    for subdir in ("raw", "derived", "_scratch", "reference"):
        (root / subdir).mkdir(parents=True)
    monkeypatch.setenv("GENOMECLAW_HOST_ROOTS", str(root))
    return root


def test_factory_accepts_canonical_raw_path(canonical_root: Path) -> None:
    """A path under ``<host_roots>/raw/`` is accepted; the result is a
    :class:`SiblingMountablePath` AND still a :class:`Path` (subclass)."""
    from genomeclaw_toolkit.prep._paths import (
        SiblingMountablePath,
        as_sibling_mountable,
    )

    target = canonical_root / "raw" / "user.cram"
    target.touch()
    result = as_sibling_mountable(target)

    assert isinstance(result, SiblingMountablePath)
    assert isinstance(result, Path)
    assert Path(result) == target.resolve()


def test_factory_accepts_canonical_derived_path(canonical_root: Path) -> None:
    """A path under ``<host_roots>/derived/`` is accepted."""
    from genomeclaw_toolkit.prep._paths import (
        SiblingMountablePath,
        as_sibling_mountable,
    )

    target = canonical_root / "derived" / "run-1" / "out.vcf.gz"
    target.parent.mkdir(parents=True)
    target.touch()
    assert isinstance(as_sibling_mountable(target), SiblingMountablePath)


def test_factory_accepts_canonical_scratch_path(canonical_root: Path) -> None:
    """A path under ``<host_roots>/_scratch/`` is accepted."""
    from genomeclaw_toolkit.prep._paths import (
        SiblingMountablePath,
        as_sibling_mountable,
    )

    target = canonical_root / "_scratch" / "shard-1" / "merged.vcf.gz"
    target.parent.mkdir(parents=True)
    target.touch()
    assert isinstance(as_sibling_mountable(target), SiblingMountablePath)


def test_factory_accepts_canonical_reference_path(canonical_root: Path) -> None:
    """A path under ``<host_roots>/reference/`` is accepted."""
    from genomeclaw_toolkit.prep._paths import (
        SiblingMountablePath,
        as_sibling_mountable,
    )

    target = canonical_root / "reference" / "GRCh38.fa"
    target.touch()
    assert isinstance(as_sibling_mountable(target), SiblingMountablePath)


# ---------------------------------------------------------------------------
# Test 5 — smoke v3 reproducer (ephemeral scratch rejection)
# ---------------------------------------------------------------------------


def test_factory_rejects_ephemeral_scratch_path(canonical_root: Path) -> None:
    """The smoke v3 reproducer: ``ephemeral_scratch_base()`` produces paths
    under ``/tmp/genomeclaw-scratch/...`` which are container-local and not
    visible to DooD siblings. The factory rejects these with a fixable hint."""
    from genomeclaw_toolkit.prep._paths import (
        DooDPathError,
        as_sibling_mountable,
    )

    ephemeral_path = Path("/tmp/genomeclaw-scratch/prs_coverage_tier1-run-1/merged.vcf.gz")
    with pytest.raises(DooDPathError) as exc_info:
        as_sibling_mountable(ephemeral_path)
    # The hint must name a fixable alternative.
    msg = str(exc_info.value)
    assert "ephemeral_scratch_base" in msg, msg
    assert any(hint in msg for hint in ("shard_scratch", "work_dir", "canonical")), msg


# ---------------------------------------------------------------------------
# Test 6 — generic container-local path rejection
# ---------------------------------------------------------------------------


def test_factory_rejects_container_local_path(canonical_root: Path) -> None:
    """A path not under any sibling-mountable prefix raises ``DooDPathError``.

    Catches the generic case beyond ephemeral scratch — anywhere the
    parent container has a writable but non-overlayed FS would surface
    this. ``/var/lib/something/...`` is the placeholder used here."""
    from genomeclaw_toolkit.prep._paths import (
        DooDPathError,
        as_sibling_mountable,
    )

    with pytest.raises(DooDPathError):
        as_sibling_mountable(Path("/var/lib/notvisible/x.vcf.gz"))


# ---------------------------------------------------------------------------
# Test 7 — DooDPathError carries a fix hint
# ---------------------------------------------------------------------------


def test_dood_path_error_carries_fix_hint(canonical_root: Path) -> None:
    """The exception message must reference how to fix the path, not just
    say "rejected". Either name ``shard_scratch``, ``work_dir``, or the
    canonical-mount-roots list — at least one of these surface area phrases."""
    from genomeclaw_toolkit.prep._paths import (
        DooDPathError,
        as_sibling_mountable,
    )

    with pytest.raises(DooDPathError) as exc_info:
        as_sibling_mountable(Path("/var/lib/notvisible/x.vcf.gz"))
    msg = str(exc_info.value)
    assert any(
        hint in msg for hint in ("shard_scratch", "work_dir", "canonical", "GENOMECLAW_HOST_ROOTS")
    ), f"DooDPathError must name a fixable hint; got: {msg!r}"


# ---------------------------------------------------------------------------
# Test 8 — factory honours ``/mnt/genomeclaw`` even without GENOMECLAW_HOST_ROOTS
# ---------------------------------------------------------------------------


def test_factory_rejects_canonical_mnt_genomeclaw_in_phase6(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Phase 6 tightening: ``/mnt/genomeclaw/...`` is REJECTED, not accepted.

    The Phase 3 contract accepted the canonical mount unconditionally. Phase
    5 smoke v6 surfaced this as silently broken: pgsc_calc spawned DooD
    siblings against the host daemon, which couldn't resolve the canonical-
    container path. Phase 6 tightens the factory to reject canonical-mount
    paths with a translated hint naming the host-form equivalent.

    The previous test (pre-Phase-6) asserted acceptance — kept here as a
    rejection assertion documenting the tightening."""
    from genomeclaw_toolkit.prep._paths import (
        DooDPathError,
        as_sibling_mountable,
    )

    monkeypatch.delenv("GENOMECLAW_HOST_ROOTS", raising=False)
    target = Path("/mnt/genomeclaw/raw/user.cram")
    with pytest.raises(DooDPathError, match="canonical-mount"):
        as_sibling_mountable(target)


# ---------------------------------------------------------------------------
# Test 9 — ``_write_pgsc_calc_samplesheet`` parameter type is SiblingMountablePath
# ---------------------------------------------------------------------------


def test_write_pgsc_calc_samplesheet_vcf_param_is_sibling_mountable() -> None:
    """The wrapper's ``vcf`` parameter MUST be annotated as
    :class:`SiblingMountablePath` (the canonical INV-D006 surface).

    ``get_type_hints`` resolves the forward-reference string produced by
    ``from __future__ import annotations`` into the actual class object.
    """
    from typing import get_type_hints

    from genomeclaw_toolkit.prep._paths import SiblingMountablePath
    from genomeclaw_toolkit.prep.pgs import _write_pgsc_calc_samplesheet

    hints = get_type_hints(_write_pgsc_calc_samplesheet)
    assert hints["vcf"] is SiblingMountablePath, (
        f"_write_pgsc_calc_samplesheet.vcf must annotate SiblingMountablePath; got {hints['vcf']!r}"
    )


# ---------------------------------------------------------------------------
# Test 10 — ``ephemeral_scratch_base`` returns bare Path + docstring is explicit
# ---------------------------------------------------------------------------


def test_ephemeral_scratch_base_returns_bare_path_documented_as_dood_unsafe() -> None:
    """``ephemeral_scratch_base()`` MUST return bare ``Path`` (not
    :class:`SiblingMountablePath`); the docstring MUST name the negative case
    explicitly. The function exists for non-DooD steps; DooD callers must
    pick ``shard_scratch`` or ``work_dir`` instead."""
    from inspect import signature

    from genomeclaw_toolkit.prep._paths import SiblingMountablePath
    from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base

    sig = signature(ephemeral_scratch_base)
    assert sig.return_annotation is not SiblingMountablePath, (
        "ephemeral_scratch_base must NOT promise SiblingMountablePath — "
        "container-local paths are NOT visible to DooD siblings."
    )
    # Return annotation is just `Path` (or implicit).
    assert sig.return_annotation in (Path, "Path") or sig.return_annotation is Path

    # The docstring must explicitly warn callers.
    doc = ephemeral_scratch_base.__doc__ or ""
    assert any(
        marker in doc for marker in ("NOT sibling-mountable", "NOT visible", "DooD-unsafe")
    ), f"ephemeral_scratch_base docstring must flag DooD-unsafety; got: {doc!r}"


# ---------------------------------------------------------------------------
# Test 11 — Path subclass behaviour preserved
# ---------------------------------------------------------------------------


def test_sibling_mountable_path_preserves_path_api(canonical_root: Path) -> None:
    """The subclass must keep the Path API working: ``.parent``, ``.name``,
    ``.exists()``, division (``/``)."""
    from genomeclaw_toolkit.prep._paths import as_sibling_mountable

    target = canonical_root / "derived" / "out.vcf.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    smp = as_sibling_mountable(target)
    assert smp.name == "out.vcf.gz"
    assert smp.exists()
    assert smp.parent == target.parent
    # Division returns a regular Path (the resulting path may or may not be
    # sibling-mountable; the type must be re-validated at the boundary).
    child = smp / "sub"
    assert isinstance(child, Path)


# ---------------------------------------------------------------------------
# Test 12 — Factory is idempotent: wrap-of-wrap is harmless
# ---------------------------------------------------------------------------


def test_factory_is_idempotent(canonical_root: Path) -> None:
    """Calling ``as_sibling_mountable`` on an already-wrapped path returns a
    valid :class:`SiblingMountablePath`. Prevents accidental double-wrapping
    from raising spuriously."""
    from genomeclaw_toolkit.prep._paths import (
        SiblingMountablePath,
        as_sibling_mountable,
    )

    target = canonical_root / "derived" / "out.vcf.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()
    once = as_sibling_mountable(target)
    twice = as_sibling_mountable(once)
    assert isinstance(twice, SiblingMountablePath)
    assert Path(twice) == Path(once)
