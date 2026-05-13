"""Unit tests for ``annotate_vcfanno._sha256_file_cached`` + parallel hasher.

The annotate phase hashes ~230 GB of overlay sources (clinvar + dbsnp
+ 24×gnomad-exomes + the just-normalised VCF) every run for
``INV-R001`` provenance. Single-threaded that's ~8 min on consumer SSD.
We (a) hash in parallel via :class:`ThreadPoolExecutor` (hashlib
releases the GIL inside ``update(...)``) and (b) persist a
``(size, mtime_ns) → sha256`` cache so subsequent runs against an
unmodified reference layout skip the recompute entirely.

These tests are pure-Python (no bcftools / vcfanno needed) — they
exercise the cache invariants directly without touching the bio image.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import pytest

from genomeclaw_toolkit.prep.annotate_vcfanno import (
    _hash_files_parallel,
    _sha256_file,
    _sha256_file_cached,
)


def _write_blob(path: Path, content: bytes) -> Path:
    path.write_bytes(content)
    return path


# ---------------------------------------------------------------------------
# _sha256_file_cached
# ---------------------------------------------------------------------------


def test_cache_miss_computes_sha_and_persists_entry(tmp_path: Path) -> None:
    """First call against a fresh cache_dir computes + writes the cache entry."""
    src = _write_blob(tmp_path / "blob.bin", b"hello world\n")
    cache_dir = tmp_path / "_cache"

    sha, hit = _sha256_file_cached(src, cache_dir=cache_dir)

    assert hit is False
    assert sha == _sha256_file(src)
    # Cache entry written + parseable.
    entries = list(cache_dir.glob("*.json"))
    assert len(entries) == 1
    payload = json.loads(entries[0].read_text())
    assert payload["sha256"] == sha
    assert payload["size"] == src.stat().st_size
    assert payload["mtime_ns"] == src.stat().st_mtime_ns


def test_cache_hit_returns_stored_sha_without_recomputing(tmp_path: Path) -> None:
    """Second call against an unmodified file returns ``cache_hit=True``.

    Crucially, the cache hit must trust the stored sha (the whole point
    of the cache is to skip the read). We seed the cache with a
    deliberately-wrong sha and assert the lookup returns it — proving
    the cache is consulted instead of recomputing.
    """
    src = _write_blob(tmp_path / "blob.bin", b"hello world\n")
    cache_dir = tmp_path / "_cache"

    # Prime the cache with a fake sha that wouldn't match the real bytes.
    _sha256_file_cached(src, cache_dir=cache_dir)
    entries = list(cache_dir.glob("*.json"))
    payload = json.loads(entries[0].read_text())
    payload["sha256"] = "f" * 64
    entries[0].write_text(json.dumps(payload))

    sha, hit = _sha256_file_cached(src, cache_dir=cache_dir)
    assert hit is True
    assert sha == "f" * 64, "cache hit must return the stored value, not recompute"


def test_cache_invalidates_when_file_size_changes(tmp_path: Path) -> None:
    """Appending bytes (different size + mtime) invalidates the cached sha."""
    src = _write_blob(tmp_path / "blob.bin", b"abc")
    cache_dir = tmp_path / "_cache"
    first_sha, _ = _sha256_file_cached(src, cache_dir=cache_dir)

    # Append → size changes.
    src.write_bytes(b"abcdef")
    second_sha, hit = _sha256_file_cached(src, cache_dir=cache_dir)

    assert hit is False, "size change must trigger a recompute"
    assert second_sha != first_sha
    assert second_sha == _sha256_file(src)


def test_cache_invalidates_when_mtime_ns_changes(tmp_path: Path) -> None:
    """Same-size content with a different mtime_ns invalidates the cache.

    Defensive against in-place edits that preserve file length but
    change content (rare; common enough on overwrite-with-different-bytes
    workflows that we trust mtime as the second invariant).
    """
    src = _write_blob(tmp_path / "blob.bin", b"abc")
    cache_dir = tmp_path / "_cache"
    _sha256_file_cached(src, cache_dir=cache_dir)

    # In-place rewrite of identical-length content — bump mtime forward
    # explicitly so the OS-level granularity doesn't elide the change.
    # ``os.utime`` with nanosecond precision lets us set mtime_ns past
    # the cached value regardless of filesystem mtime granularity.
    st = src.stat()
    src.write_bytes(b"xyz")
    os.utime(src, ns=(st.st_atime_ns, st.st_mtime_ns + 1_000_000_000))

    sha, hit = _sha256_file_cached(src, cache_dir=cache_dir)
    assert hit is False, "mtime_ns change must trigger a recompute"
    assert sha == _sha256_file(src)


def test_cache_recovers_from_malformed_entry(tmp_path: Path) -> None:
    """A corrupted JSON cache entry triggers a clean recompute, not a crash."""
    src = _write_blob(tmp_path / "blob.bin", b"abc")
    cache_dir = tmp_path / "_cache"
    _sha256_file_cached(src, cache_dir=cache_dir)
    # Corrupt the entry.
    entries = list(cache_dir.glob("*.json"))
    entries[0].write_text("not valid json {{{")

    sha, hit = _sha256_file_cached(src, cache_dir=cache_dir)
    assert hit is False
    assert sha == _sha256_file(src)
    # The malformed entry was overwritten by the recompute.
    payload = json.loads(entries[0].read_text())
    assert payload["sha256"] == sha


def test_cache_uses_per_path_keying_so_two_files_get_independent_entries(
    tmp_path: Path,
) -> None:
    """Two distinct paths get distinct cache files, even with identical content."""
    src_a = _write_blob(tmp_path / "a.bin", b"same content")
    src_b = _write_blob(tmp_path / "b.bin", b"same content")
    cache_dir = tmp_path / "_cache"

    sha_a, _ = _sha256_file_cached(src_a, cache_dir=cache_dir)
    sha_b, _ = _sha256_file_cached(src_b, cache_dir=cache_dir)

    assert sha_a == sha_b  # contents are identical
    entries = list(cache_dir.glob("*.json"))
    assert len(entries) == 2, "each path should get its own cache entry"


# ---------------------------------------------------------------------------
# _hash_files_parallel
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("worker_count", [1, 4])
def test_parallel_hasher_returns_one_sha_per_input_path(
    tmp_path: Path, worker_count: int
) -> None:
    """Result dict has one entry per input path with the correct sha."""
    sources = [_write_blob(tmp_path / f"f{i}.bin", f"contents {i}".encode()) for i in range(6)]
    cache_dir = tmp_path / "_cache"

    results = _hash_files_parallel(
        sources, cache_dir=cache_dir, worker_count=worker_count
    )

    assert set(results) == set(sources)
    for src in sources:
        assert results[src] == _sha256_file(src)


def test_parallel_hasher_second_call_pays_only_cache_hits(tmp_path: Path) -> None:
    """Second invocation against an unmodified set of files is essentially free.

    Measures wall-time as a behavioural proxy: cache hits stat() each
    file but never re-read its contents, so the second pass must be
    substantially faster than the first. The test uses 8 × 4 MiB blobs
    (~32 MiB) to make the first-pass SHA256 cost measurable while
    keeping the test runtime sane.
    """
    blob = b"x" * (4 * 1024 * 1024)
    sources = [_write_blob(tmp_path / f"f{i}.bin", blob) for i in range(8)]
    cache_dir = tmp_path / "_cache"

    t0 = time.monotonic()
    first = _hash_files_parallel(sources, cache_dir=cache_dir, worker_count=4)
    cold_elapsed = time.monotonic() - t0

    t1 = time.monotonic()
    second = _hash_files_parallel(sources, cache_dir=cache_dir, worker_count=4)
    hot_elapsed = time.monotonic() - t1

    assert first == second
    # Hot path must be meaningfully faster than cold. Threshold is
    # forgiving (3×) to ride out CI / dev-machine variance — the actual
    # ratio observed on hardware is typically 50-500×.
    assert hot_elapsed * 3 < cold_elapsed, (
        f"cache hit didn't measurably win: cold={cold_elapsed:.3f}s hot={hot_elapsed:.3f}s"
    )
