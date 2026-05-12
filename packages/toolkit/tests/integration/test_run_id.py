"""Phase 2 — run-id format + CURRENT-symlink atomic update.

Covers test cases 16, 17, 18 from
``docs/plans/active/mvp/phases/phase-2.md`` Step 2.1.

Run-IDs are deterministic given the same input SHA256 + start timestamp;
uniqueness across simultaneous runs is preserved by the timestamp
component. The CURRENT symlink under ``derived/`` resolves the active run
for the host service (Phase 5) and is updated atomically by
``genomeclaw``.
"""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest

RUN_ID_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2}Z-[0-9a-f]{6}$")


def test_run_id_format_iso_plus_hash() -> None:
    """Case 16: run-id matches ``^\\d{4}-\\d{2}-\\d{2}T\\d{2}-\\d{2}-\\d{2}Z-[0-9a-f]{6}$``."""
    from genomeclaw_toolkit.prep.run_id import generate_run_id

    started_at = datetime(2026, 5, 6, 8, 12, 34, tzinfo=UTC)
    run_id = generate_run_id(input_sha256="a" * 64, started_at=started_at)
    assert RUN_ID_PATTERN.match(run_id), run_id


def test_run_id_deterministic_for_same_input_and_clock() -> None:
    """Two run-id generations with the same inputs produce identical IDs.

    This anchors INV-R001's determinism story for the run-id itself; the
    pipeline as a whole is exercised in case 8 (Phase 2C).
    """
    from genomeclaw_toolkit.prep.run_id import generate_run_id

    started_at = datetime(2026, 5, 6, 8, 12, 34, tzinfo=UTC)
    a = generate_run_id(input_sha256="b" * 64, started_at=started_at)
    b = generate_run_id(input_sha256="b" * 64, started_at=started_at)
    assert a == b


def test_run_id_differs_when_input_differs() -> None:
    from genomeclaw_toolkit.prep.run_id import generate_run_id

    started_at = datetime(2026, 5, 6, 8, 12, 34, tzinfo=UTC)
    a = generate_run_id(input_sha256="c" * 64, started_at=started_at)
    b = generate_run_id(input_sha256="d" * 64, started_at=started_at)
    # Same timestamp prefix, different hex suffix.
    assert a[:20] == b[:20]
    assert a[-6:] != b[-6:]


def test_current_symlink_initial_creation(tmp_path: Path) -> None:
    """Case 18: first ``ingest`` on an empty derived dir creates CURRENT correctly."""
    from genomeclaw_toolkit.prep.run_id import update_current_symlink

    derived_root = tmp_path
    run_id = "2026-05-06T08-12-34Z-abc123"
    (derived_root / run_id).mkdir()

    update_current_symlink(derived_root, run_id)

    current = derived_root / "CURRENT"
    assert current.is_symlink()
    assert os.readlink(current) == run_id  # relative target inside derived/
    assert (current / ".").resolve() == (derived_root / run_id).resolve()


def test_current_symlink_atomic_update_replaces_previous(tmp_path: Path) -> None:
    """Case 17 (happy path): a successful ingest swings CURRENT to the new run."""
    from genomeclaw_toolkit.prep.run_id import update_current_symlink

    derived_root = tmp_path
    old_run = "2026-05-06T08-12-34Z-abc123"
    new_run = "2026-05-07T11-22-33Z-def456"
    (derived_root / old_run).mkdir()
    (derived_root / new_run).mkdir()

    update_current_symlink(derived_root, old_run)
    update_current_symlink(derived_root, new_run)

    assert os.readlink(derived_root / "CURRENT") == new_run


def test_current_symlink_atomic_update_cleans_up_tmp(tmp_path: Path) -> None:
    """Case 17 (cleanup): no stray CURRENT.tmp survives a successful update."""
    from genomeclaw_toolkit.prep.run_id import update_current_symlink

    derived_root = tmp_path
    run_id = "2026-05-06T08-12-34Z-abc123"
    (derived_root / run_id).mkdir()

    update_current_symlink(derived_root, run_id)

    assert not (derived_root / "CURRENT.tmp").exists()


def test_current_symlink_uses_relative_target(tmp_path: Path) -> None:
    """The symlink target is relative so the symlink survives a moved derived/."""
    from genomeclaw_toolkit.prep.run_id import update_current_symlink

    derived_root = tmp_path
    run_id = "2026-05-06T08-12-34Z-abc123"
    (derived_root / run_id).mkdir()

    update_current_symlink(derived_root, run_id)

    target = os.readlink(derived_root / "CURRENT")
    assert not Path(target).is_absolute(), target


def test_resolve_current_run_dir_returns_symlink_target(tmp_path: Path) -> None:
    """``resolve_current_run_dir`` returns the absolute path the CURRENT symlink points at."""
    from genomeclaw_toolkit.prep.run_id import resolve_current_run_dir, update_current_symlink

    run_id = "2026-05-06T08-12-34Z-abc123"
    (tmp_path / run_id).mkdir()
    update_current_symlink(tmp_path, run_id)

    assert resolve_current_run_dir(tmp_path) == (tmp_path / run_id).resolve()


def test_resolve_current_run_dir_refuses_when_derived_missing(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.run_id import resolve_current_run_dir

    with pytest.raises(ValueError, match="derived root not found"):
        resolve_current_run_dir(tmp_path / "nope")


def test_resolve_current_run_dir_refuses_when_current_missing(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.run_id import resolve_current_run_dir

    with pytest.raises(ValueError, match="no CURRENT symlink"):
        resolve_current_run_dir(tmp_path)


def test_resolve_current_run_dir_refuses_when_symlink_broken(tmp_path: Path) -> None:
    """``CURRENT`` pointing at a non-existent target → clear error."""
    from genomeclaw_toolkit.prep.run_id import resolve_current_run_dir, update_current_symlink

    run_id = "2026-05-06T08-12-34Z-abc123"
    (tmp_path / run_id).mkdir()
    update_current_symlink(tmp_path, run_id)
    # Remove the target directory after the symlink was written.
    (tmp_path / run_id).rmdir()

    with pytest.raises(ValueError, match="not a directory|no CURRENT symlink"):
        resolve_current_run_dir(tmp_path)


def test_run_id_rejects_bad_sha256_length() -> None:
    """Refuses inputs that aren't 64-char lowercase hex (the format SHA256 emits)."""
    from genomeclaw_toolkit.prep.run_id import generate_run_id

    started_at = datetime(2026, 5, 6, 8, 12, 34, tzinfo=UTC)
    with pytest.raises(ValueError):
        generate_run_id(input_sha256="too-short", started_at=started_at)


def test_run_id_rejects_naive_datetime() -> None:
    """Naive datetimes are rejected — the timestamp must be unambiguously UTC."""
    from genomeclaw_toolkit.prep.run_id import generate_run_id

    naive = datetime(2026, 5, 6, 8, 12, 34)
    with pytest.raises(ValueError):
        generate_run_id(input_sha256="e" * 64, started_at=naive)
