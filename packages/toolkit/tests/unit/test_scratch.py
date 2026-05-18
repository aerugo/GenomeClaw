"""Phase 4 — pipeline primitives: ``shard_scratch`` + ``atomic_promote``.

Tests run against tmp_path-injected base/dst paths so they don't touch
the canonical ``/mnt/genomeclaw/scratch`` mount. Covers the
``INV-R001`` corner where a crashed promote leaves a partial file
visible at the destination.
"""

from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# ephemeral_scratch_base — Phase A of annotate-shard-resilience
# ---------------------------------------------------------------------------


def test_ephemeral_scratch_base_returns_default_when_env_var_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``GENOMECLAW_EPHEMERAL_SCRATCH_DIR`` unset → returns the canonical default.

    The default is intentionally **inside the container** (``/tmp/genomeclaw-scratch``)
    so the heavy per-step intermediates that vcfanno and VEP write don't traverse
    the virtiofs bind-mount that backs ``/mnt/genomeclaw/scratch`` on the host.
    The cram-scratch-strategy plan's documented tripwire (vcfanno EBADF under
    concurrent reads on virtiofs) fires when shard_scratch's writes go through
    that mount — keeping the default off-virtiofs is the architectural fix.
    """
    from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base

    monkeypatch.delenv("GENOMECLAW_EPHEMERAL_SCRATCH_DIR", raising=False)
    base = ephemeral_scratch_base()
    assert base == Path("/tmp/genomeclaw-scratch")


def test_ephemeral_scratch_base_reads_env_var_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """An explicit ``GENOMECLAW_EPHEMERAL_SCRATCH_DIR`` overrides the default.

    Tests + the user can route ephemeral scratch wherever they like — that's
    the seam for redirecting to ``tmp_path`` in pytest, or to a VM-internal
    ext4 partition in production.
    """
    from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base

    explicit = tmp_path / "my-ephemeral"
    monkeypatch.setenv("GENOMECLAW_EPHEMERAL_SCRATCH_DIR", str(explicit))
    base = ephemeral_scratch_base()
    assert base == explicit


def test_ephemeral_scratch_base_returns_path_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Returns ``pathlib.Path``, not ``str`` (caller can `/`-compose without `Path()` wrapping)."""
    from genomeclaw_toolkit.prep.scratch import ephemeral_scratch_base

    monkeypatch.setenv("GENOMECLAW_EPHEMERAL_SCRATCH_DIR", str(tmp_path))
    assert isinstance(ephemeral_scratch_base(), Path)


# ---------------------------------------------------------------------------
# shard_scratch
# ---------------------------------------------------------------------------


def test_shard_scratch_yields_dir_under_base(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import shard_scratch

    with shard_scratch(step="annotate", run_id="run-001", base=tmp_path) as scratch:
        assert scratch.is_dir()
        assert scratch.parent == tmp_path
        assert scratch.name == "annotate-run-001"


def test_shard_scratch_includes_shard_in_name(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import shard_scratch

    with shard_scratch(
        step="dv-make-examples", run_id="run-001", shard="chr1", base=tmp_path
    ) as scratch:
        assert scratch.name == "dv-make-examples-run-001-chr1"


def test_shard_scratch_cleans_up_on_normal_exit(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import shard_scratch

    captured: Path | None = None
    with shard_scratch(step="annotate", run_id="run-001", base=tmp_path) as scratch:
        captured = scratch
        (scratch / "marker").write_text("hello")
    assert captured is not None
    assert not captured.exists()


def test_shard_scratch_cleans_up_on_exception(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import shard_scratch

    captured: Path | None = None
    with pytest.raises(RuntimeError, match="boom"):
        with shard_scratch(step="annotate", run_id="run-001", base=tmp_path) as scratch:
            captured = scratch
            (scratch / "marker").write_text("hello")
            raise RuntimeError("boom")
    assert captured is not None
    assert not captured.exists()


def test_shard_scratch_does_not_collide_across_steps(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import shard_scratch

    with shard_scratch(step="annotate", run_id="run-001", base=tmp_path) as a:
        with shard_scratch(step="materialize", run_id="run-001", base=tmp_path) as b:
            assert a != b
            assert a.is_dir()
            assert b.is_dir()


def test_shard_scratch_creates_base_if_missing(tmp_path: Path) -> None:
    """If ``base`` doesn't exist (atypical but possible during tests), create it."""
    from genomeclaw_toolkit.prep.scratch import shard_scratch

    base = tmp_path / "newly-created"
    with shard_scratch(step="annotate", run_id="run-001", base=base) as scratch:
        assert scratch.is_dir()
        assert base.is_dir()


# ---------------------------------------------------------------------------
# atomic_promote
# ---------------------------------------------------------------------------


def test_atomic_promote_writes_dst(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import atomic_promote

    src = tmp_path / "scratch" / "annotated.vcf.gz"
    src.parent.mkdir()
    src.write_bytes(b"hello-world" * 1024)
    dst = tmp_path / "derived" / "annotated.vcf.gz"

    atomic_promote(src, dst)
    assert dst.read_bytes() == b"hello-world" * 1024


def test_atomic_promote_creates_parent_dir(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import atomic_promote

    src = tmp_path / "scratch" / "out.txt"
    src.parent.mkdir()
    src.write_text("payload")
    dst = tmp_path / "derived" / "deep" / "nested" / "out.txt"

    atomic_promote(src, dst)
    assert dst.read_text() == "payload"


def test_atomic_promote_cleans_up_tmp_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genomeclaw_toolkit.prep import scratch as scratch_mod
    from genomeclaw_toolkit.prep.scratch import atomic_promote

    src = tmp_path / "scratch" / "out.txt"
    src.parent.mkdir()
    src.write_text("payload")
    dst = tmp_path / "derived" / "out.txt"

    # Inject a copyfile that fails after partially writing the .tmp.
    def boom(*args, **kwargs):
        # Simulate a partial write before raising.
        tmp = dst.with_name(dst.name + ".tmp")
        tmp.write_bytes(b"PARTIAL")
        raise OSError("simulated mid-copy failure")

    monkeypatch.setattr(scratch_mod, "_copy_with_fsync", boom)

    with pytest.raises(OSError, match="simulated"):
        atomic_promote(src, dst)

    # Neither dst nor <dst>.tmp may be left behind.
    assert not dst.exists()
    assert not dst.with_name(dst.name + ".tmp").exists()


def test_atomic_promote_raises_when_src_missing(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import atomic_promote

    src = tmp_path / "missing.txt"
    dst = tmp_path / "derived" / "out.txt"

    with pytest.raises(FileNotFoundError, match="missing"):
        atomic_promote(src, dst)


def test_atomic_promote_overwrites_existing_dst(tmp_path: Path) -> None:
    from genomeclaw_toolkit.prep.scratch import atomic_promote

    src = tmp_path / "scratch" / "out.txt"
    src.parent.mkdir()
    src.write_text("new-content")
    dst = tmp_path / "derived" / "out.txt"
    dst.parent.mkdir()
    dst.write_text("old-content")

    atomic_promote(src, dst)
    assert dst.read_text() == "new-content"


# ---------------------------------------------------------------------------
# INV-R001: no partial state visible mid-promote
# ---------------------------------------------------------------------------


def _slow_writer(src: str, dst: str, ready_event_path: str) -> None:
    """Subprocess target: signal readiness, then run atomic_promote.

    The reader process polls the destination during this window. Atomic
    rename means the reader either sees a missing file or the full
    contents, never a partial.
    """
    from genomeclaw_toolkit.prep.scratch import atomic_promote

    # Make the source large enough that the copy takes a measurable
    # time slice — gives the reader its window.
    Path(ready_event_path).touch()
    atomic_promote(Path(src), Path(dst))


def test_invR001_atomic_promote_no_partial_state_visible(tmp_path: Path) -> None:
    """INV-R001: a reader observing ``dst`` mid-copy sees either the
    full file or no file — never a partial."""
    src = tmp_path / "src.bin"
    src.write_bytes(b"x" * (16 * 1024 * 1024))  # 16 MB — copy takes ~100 ms
    dst = tmp_path / "dst.bin"
    ready = tmp_path / "ready"

    proc = multiprocessing.Process(target=_slow_writer, args=(str(src), str(dst), str(ready)))
    proc.start()
    # Wait for the writer to start, then poll dst aggressively.
    deadline = time.time() + 5.0
    while not ready.exists() and time.time() < deadline:
        time.sleep(0.001)

    observations: list[int] = []
    while proc.is_alive():
        if dst.exists():
            try:
                observations.append(dst.stat().st_size)
            except OSError:
                pass
        time.sleep(0.001)

    proc.join(timeout=5.0)
    assert proc.exitcode == 0

    # Every observation must be the full size — never partial.
    full_size = src.stat().st_size
    bad = [size for size in observations if size != full_size]
    assert not bad, f"observed partial sizes: {bad[:5]} (expected {full_size} only)"
    # Final state: dst exists at full size; no .tmp leftover.
    assert dst.stat().st_size == full_size
    assert not dst.with_name(dst.name + ".tmp").exists()


# ---------------------------------------------------------------------------
# Sanity: fsync is actually called (cheap to verify with monkeypatch)
# ---------------------------------------------------------------------------


def test_atomic_promote_fsyncs_file_and_dir(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """``atomic_promote`` calls ``os.fsync`` on the file and on the
    parent directory — durability belt-and-suspenders."""
    from genomeclaw_toolkit.prep.scratch import atomic_promote

    fsync_calls: list[int] = []
    real_fsync = os.fsync

    def fake_fsync(fd: int) -> None:
        fsync_calls.append(fd)
        return real_fsync(fd)

    monkeypatch.setattr(os, "fsync", fake_fsync)

    src = tmp_path / "scratch" / "out.txt"
    src.parent.mkdir()
    src.write_text("payload")
    dst = tmp_path / "derived" / "out.txt"

    atomic_promote(src, dst)
    # At least 2 fsync calls: one for the file, one for the parent dir.
    assert len(fsync_calls) >= 2
