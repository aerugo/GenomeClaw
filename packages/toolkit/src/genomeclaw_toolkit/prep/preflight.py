"""Pre-flight assertions for orchestrators.

Each orchestrator (``ingest``, ``normalize``, ``annotate``, ``materialize``,
``fetch``) calls the assertions appropriate to its data flow at the top
of its main entry. Failure raises a typed ``PreflightError`` with a
fixable message — typically pointing the user at ``genomeclaw
setup`` to restore the canonical layout.

The assertions probe each canonical mount by attempting a write (RW
checks) or by attempting a write and expecting it to fail (RO checks).
Probe files are unlinked immediately on success.

Mount-point parameters default to the canonical container paths
(``/mnt/genomeclaw/{raw,reference,derived,scratch}``); tests inject
``tmp_path`` subdirs to avoid touching the real container mounts.
"""

from __future__ import annotations

import os
from pathlib import Path

# Canonical in-container mount points. The host shim binds host paths
# under each of these. Tests pass overriding paths.
_RAW = Path("/mnt/genomeclaw/raw")
_REFERENCE = Path("/mnt/genomeclaw/reference")
_DERIVED = Path("/mnt/genomeclaw/derived")
_SCRATCH = Path("/mnt/genomeclaw/scratch")


def _should_skip() -> bool:
    """``GENOMECLAW_SKIP_PREFLIGHT=1`` short-circuits every assertion.

    Test-only escape hatch — set in ``tests/conftest.py`` so existing
    Phase-4A integration tests that use ``tmp_path``-based paths (rather
    than the canonical ``/mnt/genomeclaw/...`` mounts) can still drive
    the orchestrators end-to-end. Phase-3 preflight tests pass explicit
    ``path=`` kwargs that bypass the canonical defaults entirely; they
    don't need this gate. Production never sets the env var.
    """
    return os.environ.get("GENOMECLAW_SKIP_PREFLIGHT") == "1"


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class PreflightError(Exception):
    """Base for every pre-flight assertion failure."""


class RawNotMountedError(PreflightError):
    """``/mnt/genomeclaw/raw`` is missing — user must run ``setup``."""


class RawNotReadOnlyError(PreflightError):
    """``/mnt/genomeclaw/raw`` is writable — INV-D001 enforcement is broken."""


class ReferenceNotMountedError(PreflightError):
    """``/mnt/genomeclaw/reference`` is missing — user must run ``setup``."""


class ReferenceNotReadOnlyError(PreflightError):
    """``/mnt/genomeclaw/reference`` is writable during a non-fetch step."""


class ReferenceNotWritableError(PreflightError):
    """``/mnt/genomeclaw/reference`` is read-only during ``fetch``."""


class DerivedNotMountedError(PreflightError):
    """``/mnt/genomeclaw/derived`` is missing — user must run ``setup``."""


class DerivedNotWritableError(PreflightError):
    """``/mnt/genomeclaw/derived`` is read-only — pipeline outputs blocked."""


class ScratchNotMountedError(PreflightError):
    """``/mnt/genomeclaw/scratch`` is missing — user must run ``setup``."""


class ScratchNotWritableError(PreflightError):
    """``/mnt/genomeclaw/scratch`` is read-only — orchestrators can't run."""


# ---------------------------------------------------------------------------
# Internal probes
# ---------------------------------------------------------------------------


def _probe_writable(path: Path) -> bool:
    """Attempt to create + delete a probe file; return True iff it succeeded."""
    probe = path / ".genomeclaw_preflight_probe"
    try:
        probe.touch()
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def _setup_hint() -> str:
    return "run `genomeclaw host setup` to restore the canonical layout"


# ---------------------------------------------------------------------------
# Public assertions
# ---------------------------------------------------------------------------


def assert_raw_readonly(*, path: Path = _RAW) -> None:
    if _should_skip():
        return
    if not path.exists():
        raise RawNotMountedError(f"{path} not found — {_setup_hint()}")
    if _probe_writable(path):
        raise RawNotReadOnlyError(
            f"INV-D001 violation: {path} is writable; the source-of-truth "
            "bind-mount must be read-only. Re-run `genomeclaw host setup` "
            "to restore the read-only bind-mount discipline."
        )


def assert_reference_readonly(*, path: Path = _REFERENCE) -> None:
    if _should_skip():
        return
    if not path.exists():
        raise ReferenceNotMountedError(f"{path} not found — {_setup_hint()}")
    if _probe_writable(path):
        raise ReferenceNotReadOnlyError(
            f"INV-D001 violation: {path} is writable; non-fetch orchestrators "
            "must see reference data as read-only. Re-run "
            "`genomeclaw host setup` to restore the read-only bind-mount."
        )


def assert_reference_writable(*, path: Path = _REFERENCE) -> None:
    """Used only by ``fetch`` (the one orchestrator that writes to reference)."""
    if _should_skip():
        return
    if not path.exists():
        raise ReferenceNotMountedError(f"{path} not found — {_setup_hint()}")
    if not _probe_writable(path):
        raise ReferenceNotWritableError(
            f"{path} is read-only; `genomeclaw refs fetch` needs the "
            "reference mount writable for the duration of the fetch. "
            "The shim should mount it RW for fetch only — check "
            "`bin/genomeclaw`."
        )


def assert_derived_writable(*, path: Path = _DERIVED) -> None:
    if _should_skip():
        return
    if not path.exists():
        raise DerivedNotMountedError(f"{path} not found — {_setup_hint()}")
    if not _probe_writable(path):
        raise DerivedNotWritableError(
            f"{path} is read-only; pipeline outputs need this mount "
            f"writable. {_setup_hint().capitalize()}."
        )


def assert_scratch_writable(*, path: Path = _SCRATCH) -> None:
    if _should_skip():
        return
    if not path.exists():
        raise ScratchNotMountedError(f"{path} not found — {_setup_hint()}")
    if not _probe_writable(path):
        raise ScratchNotWritableError(
            f"{path} is read-only; orchestrators stage intermediate "
            f"work here. {_setup_hint().capitalize()}."
        )


__all__ = [
    "DerivedNotMountedError",
    "DerivedNotWritableError",
    "PreflightError",
    "RawNotMountedError",
    "RawNotReadOnlyError",
    "ReferenceNotMountedError",
    "ReferenceNotReadOnlyError",
    "ReferenceNotWritableError",
    "ScratchNotMountedError",
    "ScratchNotWritableError",
    "assert_derived_writable",
    "assert_raw_readonly",
    "assert_reference_readonly",
    "assert_reference_writable",
    "assert_scratch_writable",
]
