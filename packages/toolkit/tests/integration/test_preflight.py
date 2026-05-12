"""Phase 3 — pre-flight assertion library.

Each assertion writes a probe file to test the canonical mount property
(RO refuses, RW accepts) and raises a typed exception with a fixable
message on failure. Tests run via temp-dir fakes that simulate the four
canonical mounts at arbitrary paths injected into each assertion.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def _disable_skip_preflight(monkeypatch: pytest.MonkeyPatch) -> None:
    """Conftest sets ``GENOMECLAW_SKIP_PREFLIGHT=1`` for the suite; this
    file exercises the assertions directly, so we have to unset it."""
    monkeypatch.delenv("GENOMECLAW_SKIP_PREFLIGHT", raising=False)


def _make_ro_dir(tmp_path: Path, name: str) -> Path:
    """Create a directory and chmod it to deny writes to the current user."""
    path = tmp_path / name
    path.mkdir()
    # 0o555 — owner+group+other read+execute, no write anywhere
    os.chmod(path, 0o555)
    yield_path = path
    return yield_path


def _make_rw_dir(tmp_path: Path, name: str) -> Path:
    path = tmp_path / name
    path.mkdir()
    return path


# ---------------------------------------------------------------------------
# assert_raw_readonly
# ---------------------------------------------------------------------------


def test_assert_raw_readonly_passes_when_ro(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import assert_raw_readonly

    ro = _make_ro_dir(tmp_path, "raw")
    try:
        assert_raw_readonly(path=ro)
    finally:
        os.chmod(ro, 0o755)


def test_assert_raw_readonly_rejects_when_writable(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        RawNotReadOnlyError,
        assert_raw_readonly,
    )

    rw = _make_rw_dir(tmp_path, "raw")
    with pytest.raises(RawNotReadOnlyError, match="INV-D001"):
        assert_raw_readonly(path=rw)


def test_assert_raw_readonly_rejects_when_missing(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        RawNotMountedError,
        assert_raw_readonly,
    )

    missing = tmp_path / "raw"
    with pytest.raises(RawNotMountedError, match="genomeclaw host setup"):
        assert_raw_readonly(path=missing)


# ---------------------------------------------------------------------------
# assert_reference_readonly
# ---------------------------------------------------------------------------


def test_assert_reference_readonly_passes_when_ro(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import assert_reference_readonly

    ro = _make_ro_dir(tmp_path, "reference")
    try:
        assert_reference_readonly(path=ro)
    finally:
        os.chmod(ro, 0o755)


def test_assert_reference_readonly_rejects_when_writable(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        ReferenceNotReadOnlyError,
        assert_reference_readonly,
    )

    rw = _make_rw_dir(tmp_path, "reference")
    with pytest.raises(ReferenceNotReadOnlyError, match="INV-D001"):
        assert_reference_readonly(path=rw)


# ---------------------------------------------------------------------------
# assert_derived_writable
# ---------------------------------------------------------------------------


def test_assert_derived_writable_passes_when_rw(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import assert_derived_writable

    rw = _make_rw_dir(tmp_path, "derived")
    assert_derived_writable(path=rw)


def test_assert_derived_writable_rejects_when_ro(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        DerivedNotWritableError,
        assert_derived_writable,
    )

    ro = _make_ro_dir(tmp_path, "derived")
    try:
        with pytest.raises(DerivedNotWritableError):
            assert_derived_writable(path=ro)
    finally:
        os.chmod(ro, 0o755)


def test_assert_derived_writable_rejects_when_missing(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        DerivedNotMountedError,
        assert_derived_writable,
    )

    missing = tmp_path / "derived"
    with pytest.raises(DerivedNotMountedError, match="genomeclaw host setup"):
        assert_derived_writable(path=missing)


# ---------------------------------------------------------------------------
# assert_scratch_writable
# ---------------------------------------------------------------------------


def test_assert_scratch_writable_passes_when_rw(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import assert_scratch_writable

    rw = _make_rw_dir(tmp_path, "scratch")
    assert_scratch_writable(path=rw)


def test_assert_scratch_writable_rejects_when_ro(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        ScratchNotWritableError,
        assert_scratch_writable,
    )

    ro = _make_ro_dir(tmp_path, "scratch")
    try:
        with pytest.raises(ScratchNotWritableError):
            assert_scratch_writable(path=ro)
    finally:
        os.chmod(ro, 0o755)


def test_assert_scratch_writable_rejects_when_missing(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        ScratchNotMountedError,
        assert_scratch_writable,
    )

    missing = tmp_path / "scratch"
    with pytest.raises(ScratchNotMountedError, match="genomeclaw host setup"):
        assert_scratch_writable(path=missing)


# ---------------------------------------------------------------------------
# assert_reference_writable (only fetch uses this)
# ---------------------------------------------------------------------------


def test_assert_reference_writable_passes_when_rw(tmp_path: Path) -> None:
    """``fetch`` writes to reference/; its pre-flight asserts the inverse polarity."""
    from genomeclaw_toolkit.prep.preflight import assert_reference_writable

    rw = _make_rw_dir(tmp_path, "reference")
    assert_reference_writable(path=rw)


def test_assert_reference_writable_rejects_when_ro(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.preflight import (
        ReferenceNotWritableError,
        assert_reference_writable,
    )

    ro = _make_ro_dir(tmp_path, "reference")
    try:
        with pytest.raises(ReferenceNotWritableError, match="fetch"):
            assert_reference_writable(path=ro)
    finally:
        os.chmod(ro, 0o755)
