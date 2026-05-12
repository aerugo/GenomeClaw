"""Run-ID generation + ``CURRENT`` symlink atomic update.

Run-IDs follow ``{ISO 8601 UTC second}-{6-char hex}``, e.g.
``2026-05-06T08-12-34Z-abc123``. The hex is the first 6 chars of
SHA256(input_sha256 + start_timestamp_ns); deterministic given the same
input + clock, but uniqueness across simultaneous runs is preserved by
the timestamp.

The ``CURRENT`` symlink under ``derived/`` resolves the active run for
the host service (Phase 5). Updates use ``os.replace`` for POSIX-atomic
swap on the same filesystem.
"""

from __future__ import annotations

import hashlib
import os
import re
from datetime import datetime
from pathlib import Path

_HEX64 = re.compile(r"^[0-9a-f]{64}$")


def generate_run_id(*, input_sha256: str, started_at: datetime) -> str:
    """Generate a run-id from an input SHA256 + a UTC start timestamp.

    Args:
        input_sha256: 64-char lowercase hex; the SHA256 of the primary
            input artifact (typically the source VCF).
        started_at: timezone-aware UTC datetime; the moment ingest began.

    Raises:
        ValueError: if ``input_sha256`` is not 64-char lowercase hex, or
            ``started_at`` is naive (no timezone).
    """
    if not _HEX64.match(input_sha256):
        raise ValueError(f"input_sha256 must be 64-char lowercase hex, got {input_sha256!r}")
    if started_at.tzinfo is None:
        raise ValueError("started_at must be timezone-aware (UTC)")

    iso = started_at.strftime("%Y-%m-%dT%H-%M-%SZ")
    seed = f"{input_sha256}:{int(started_at.timestamp() * 1e9)}"
    digest = hashlib.sha256(seed.encode()).hexdigest()[:6]
    return f"{iso}-{digest}"


def resolve_current_run_dir(derived_root: Path) -> Path:
    """Resolve ``<derived_root>/CURRENT`` to the active run directory.

    Returns the symlink's target as an absolute path under ``derived_root``.
    Raises ``ValueError`` (with a message naming the missing or broken
    symlink) when ``CURRENT`` doesn't exist or doesn't resolve to a
    directory under ``derived_root`` — caller surfaces it as a CLI error.
    """
    if not derived_root.is_dir():
        raise ValueError(f"derived root not found: {derived_root}")
    current = derived_root / "CURRENT"
    if not current.is_symlink() and not current.exists():
        raise ValueError(
            f"no CURRENT symlink under {derived_root}; "
            "run `genomeclaw pipeline ingest` first or pass --run-dir <path>"
        )
    target = current.resolve()
    if not target.is_dir():
        raise ValueError(
            f"{current} resolves to {target} which is not a directory; "
            "rerun `genomeclaw pipeline ingest` or pass --run-dir <path>"
        )
    return target


def update_current_symlink(derived_root: Path, run_id: str) -> None:
    """Atomically point ``<derived_root>/CURRENT`` at ``<run_id>``.

    The target is **relative** (just ``run_id``) so the symlink survives
    a ``mv`` of ``derived_root`` to a different host path. The update
    uses a temporary symlink + ``os.replace`` to avoid a window in which
    ``CURRENT`` doesn't exist.
    """
    tmp = derived_root / "CURRENT.tmp"
    final = derived_root / "CURRENT"

    # Clean up any leftover from a crashed prior run; this is our own
    # scratch path and never the user's data.
    if tmp.is_symlink() or tmp.exists():
        tmp.unlink()

    # Use a relative target inside derived_root so the link survives
    # if derived_root itself is later moved.
    os.symlink(run_id, tmp)
    os.replace(tmp, final)  # POSIX-atomic on same filesystem


__all__ = ["generate_run_id", "resolve_current_run_dir", "update_current_symlink"]
