"""Pipeline primitives for scratch-staging + atomic promotion.

Two functions, both small, both load-bearing:

- :func:`shard_scratch` is a context manager. It yields a per-step
  (and optionally per-shard) directory under ``/mnt/genomeclaw/scratch``.
  The directory is purged on exit, including on exception.

- :func:`atomic_promote` copies ``src`` to ``<dst>.tmp``, ``fsync``s the
  file and the parent directory, then renames ``<dst>.tmp`` → ``dst``.
  Within a single filesystem the rename is atomic on POSIX, so a reader
  observing ``dst`` mid-promote sees either nothing or the full file —
  never a partial.

Both primitives accept a ``base`` / explicit destination path so tests
can drive them under ``tmp_path``. Production calls pass the canonical
``/mnt/genomeclaw/scratch`` and ``/mnt/genomeclaw/derived/<run-id>/``
paths from the orchestrator.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

# Canonical container path; orchestrators pass this implicitly.
_SCRATCH_BASE = Path("/mnt/genomeclaw/scratch")

# Canonical container path for ephemeral per-step scratch. Per Phase A
# of the [annotate-shard-resilience plan](../../../../docs/plans/active/annotate-shard-resilience/development-plan.md),
# every ``shard_scratch(...)`` call uses this base by default instead of
# the bind-mounted persistent scratch. The default path is **inside the
# container** so writes don't traverse the virtiofs layer that backs
# ``/mnt/genomeclaw/scratch`` from the host — that's where the
# concurrent-FD pressure surfaced the 2026-05-14 EBADF tripwire.
# Override via ``GENOMECLAW_EPHEMERAL_SCRATCH_DIR`` for tests + advanced
# deployments.
_EPHEMERAL_SCRATCH_BASE_DEFAULT = Path("/tmp/genomeclaw-scratch")


def ephemeral_scratch_base() -> Path:
    """Return the configured ephemeral scratch base.

    Reads ``GENOMECLAW_EPHEMERAL_SCRATCH_DIR`` from the environment at
    call time (not import time) so tests can override per-fixture via
    ``monkeypatch.setenv``. Falls back to
    :data:`_EPHEMERAL_SCRATCH_BASE_DEFAULT` (``/tmp/genomeclaw-scratch``)
    when unset.

    The orchestrators (``annotate_vcfanno``, ``annotate_vep``,
    ``materialize``) pass this as ``base=`` to ``shard_scratch(...)``.
    Persistent caches under ``_cache/`` keep using the bind-mounted
    ``_SCRATCH_BASE`` — they're read sequentially across runs and don't
    suffer the concurrent-FD pressure that surfaced EBADF on virtiofs.
    """
    override = os.environ.get("GENOMECLAW_EPHEMERAL_SCRATCH_DIR")
    if override is not None:
        return Path(override)
    return _EPHEMERAL_SCRATCH_BASE_DEFAULT


class ScratchError(Exception):
    """Base for scratch-primitive errors."""


# ---------------------------------------------------------------------------
# shard_scratch
# ---------------------------------------------------------------------------


@contextmanager
def shard_scratch(
    *,
    step: str,
    run_id: str,
    shard: str | None = None,
    base: Path = _SCRATCH_BASE,
) -> Iterator[Path]:
    """Yield a per-step scratch directory; purge on exit.

    The directory is named ``<step>-<run_id>`` (or ``<step>-<run_id>-<shard>``
    when a ``shard`` arg is supplied — Phase-5+ scatter-gather uses this).
    Two simultaneous calls with different steps get different directories;
    same-step same-run-id calls would collide, but the orchestrator runs
    serially per run-id, so that doesn't surface in practice.

    Cleanup on context exit is unconditional (success or exception). A
    ``SIGKILL`` won't trigger the cleanup — leftover dirs after a hard
    crash are documented as user-purgable via
    ``rm -rf /mnt/genomeclaw/scratch/{step}-*/``.
    """
    parts = [step, run_id]
    if shard is not None:
        parts.append(shard)
    name = "-".join(parts)
    base.mkdir(parents=True, exist_ok=True)
    scratch = base / name
    scratch.mkdir(parents=True, exist_ok=False)
    try:
        yield scratch
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


# ---------------------------------------------------------------------------
# atomic_promote
# ---------------------------------------------------------------------------


def _copy_with_fsync(src: Path, tmp: Path) -> None:
    """Copy ``src`` to ``tmp``; ``fsync`` the file before close.

    Extracted as a module-level helper so tests can monkey-patch the
    failure path without touching the public API.
    """
    shutil.copyfile(src, tmp)
    fd = os.open(tmp, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def atomic_promote(src: Path, dst: Path) -> None:
    """Atomically promote ``src`` to ``dst``.

    Copies ``src`` to ``<dst>.tmp``, fsyncs the file and the parent
    directory, then renames ``<dst>.tmp`` → ``dst``. Within a single
    POSIX filesystem the rename is atomic, so a concurrent reader of
    ``dst`` observes either nothing or the full file — never a partial.

    On failure (mid-copy crash, source disappears, etc.), the ``.tmp``
    is unlinked before the exception propagates. ``dst`` is never
    partially overwritten.

    Both ``src`` and ``dst`` should be on the same filesystem. In the
    canonical Genome_Work layout they're both under
    ``/Volumes/Genome_Work/genomeclaw/...`` (APFS), so the rename is
    a within-FS rename and atomic.
    """
    if not src.exists():
        raise FileNotFoundError(f"atomic_promote: source not found: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    tmp = dst.with_name(dst.name + ".tmp")
    try:
        _copy_with_fsync(src, tmp)
        os.rename(tmp, dst)
        # fsync parent dir to commit the rename to disk.
        dirfd = os.open(dst.parent, os.O_RDONLY)
        try:
            os.fsync(dirfd)
        finally:
            os.close(dirfd)
    except BaseException:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass
        raise


__all__ = [
    "ScratchError",
    "atomic_promote",
    "shard_scratch",
]
