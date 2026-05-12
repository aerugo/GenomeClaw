"""Reference-data introspection — public helpers for the ``refs`` CLI group.

Three surfaces:

* :func:`describe_release_set` returns one :class:`ReferenceSourceStatus`
  per source pinned by the active release set, with on-disk
  classification (``OK`` / ``partial`` / ``missing``).
* :func:`verify_release_set_integrity` runs the bgzip-EOF check across
  every expected bgzipped file and returns per-file pass/fail.
* :func:`describe_source` returns the same classification as
  :func:`describe_release_set` for one named source, with file sizes
  added for the ``refs info`` view.

All three are read-only (`INV-D001`): they inspect the reference tree;
they never mutate it.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final, Literal

from pydantic import BaseModel, ConfigDict, Field

from genomeclaw_toolkit.prep._bgzip import verify_bgzip_eof_marker
from genomeclaw_toolkit.prep.release_sets import (
    DEFAULT_RELEASE_SET,
    ReleaseSet,
    load_release_set,
)

if TYPE_CHECKING:
    from pathlib import Path


# File suffixes that are bgzip-formatted and therefore eligible for the
# EOF-marker integrity check. ``.tbi`` / ``.fai`` / ``.gzi`` / ``.md5``
# are sidecars and not bgzipped.
_BGZIP_SUFFIXES: Final[frozenset[str]] = frozenset({".vcf.gz", ".vcf.bgz", ".bcf"})


SourceStatus = Literal["OK", "partial", "missing"]


class ReferenceFileStatus(BaseModel):
    """One reference file's on-disk + integrity classification."""

    model_config = ConfigDict(extra="forbid")

    relpath: str = Field(description="Path relative to the release dir.")
    present: bool
    size_bytes: int | None = Field(
        default=None,
        description="File size in bytes; None when the file is missing.",
    )
    bgzip_ok: bool | None = Field(
        default=None,
        description=(
            "BGZF EOF marker present (True), absent (False), or not "
            "applicable (None) for non-bgzipped sidecars."
        ),
    )


class ReferenceSourceStatus(BaseModel):
    """One source's classification under the active release set."""

    model_config = ConfigDict(extra="forbid")

    source: str
    expected_release: str
    on_disk_release: str | None = None
    status: SourceStatus
    present_files: tuple[str, ...] = ()
    missing_files: tuple[str, ...] = ()


class ReferenceSourceDetail(ReferenceSourceStatus):
    """Source classification + per-file integrity for ``refs info``."""

    files: tuple[ReferenceFileStatus, ...] = ()


def _expected_files(source: str, layout: object, chroms: tuple[str, ...] | None) -> list[str]:
    """Filenames (relative to the release dir) a complete fetch produces.

    Mirrors :func:`genomeclaw_toolkit.prep.doctor._expected_files_under_release_dir`.
    Kept inline rather than imported because the doctor's version is
    private + we'd grow more reasons to diverge as Phase 3 lands.
    """
    files: list[str] = []
    # Avoid attribute typing on the layout protocol — release_sets's
    # ``_LAYOUTS`` table is a private structure inside the fetch module
    # that we treat as opaque here.
    subdir = (
        f"{layout.output_subdir}/"  # type: ignore[attr-defined]
        if getattr(layout, "output_subdir", None)
        else ""
    )

    def _add(file_obj: object) -> None:
        filename = file_obj.output_filename  # type: ignore[attr-defined]
        files.append(subdir + filename)
        if getattr(file_obj, "md5_relpath", None) or getattr(
            file_obj, "md5_checksums_relpath", None
        ):
            files.append(subdir + filename + ".md5")

    for f in layout.files:  # type: ignore[attr-defined]
        _add(f)
    if getattr(layout, "is_multi_file", False) and chroms:
        for c in chroms:
            for tmpl in layout.chrom_files:  # type: ignore[attr-defined]
                _add(tmpl.for_chrom(c))
    # Source-specific post-fetch extras (grch38's faidx + gzi sidecars).
    if source == "grch38":
        files.append("grch38.fa.gz.fai")
        files.append("grch38.fa.gz.gzi")
    return files


def _classify_source(
    *,
    source: str,
    expected_release: str,
    chroms: tuple[str, ...] | None,
    reference_root: Path,
) -> ReferenceSourceStatus:
    """Walk one source's expected files and emit a status row."""
    # Lazy-import the layouts table — it pulls in the fetcher graph
    # which we don't want to load at CLI cold-start time.
    from genomeclaw_toolkit.prep.fetch import _LAYOUTS

    layout = _LAYOUTS.get(source)
    if layout is None:
        return ReferenceSourceStatus(
            source=source,
            expected_release=expected_release,
            on_disk_release=None,
            status="missing",
        )

    release_dir = reference_root / source / expected_release
    if not release_dir.is_dir():
        return ReferenceSourceStatus(
            source=source,
            expected_release=expected_release,
            on_disk_release=None,
            status="missing",
        )

    expected = _expected_files(source, layout, chroms)
    present: list[str] = []
    missing: list[str] = []
    for rel in expected:
        if (release_dir / rel).exists():
            present.append(rel)
        else:
            missing.append(rel)

    status: SourceStatus = "OK" if not missing else "partial"
    return ReferenceSourceStatus(
        source=source,
        expected_release=expected_release,
        on_disk_release=expected_release,
        status=status,
        present_files=tuple(present),
        missing_files=tuple(missing),
    )


def describe_release_set(
    *,
    reference_root: Path,
    release_set: ReleaseSet | None = None,
) -> tuple[str, list[ReferenceSourceStatus]]:
    """Classify every source in the active release set against the reference tree.

    Args:
        reference_root: The ``reference/`` directory.
        release_set: Optional explicit release set; defaults to the
            bundled ``default``.

    Returns:
        Tuple of ``(release_set_name, [ReferenceSourceStatus, ...])``.
    """
    rs = release_set if release_set is not None else load_release_set(DEFAULT_RELEASE_SET)
    sources = [
        _classify_source(
            source=entry.source,
            expected_release=entry.release,
            chroms=entry.chroms,
            reference_root=reference_root,
        )
        for entry in rs.sources
    ]
    return rs.name, sources


def _is_bgzip_target(relpath: str) -> bool:
    """Return True iff a relative path is a bgzipped file we should check."""
    return any(relpath.endswith(suf) for suf in _BGZIP_SUFFIXES)


def describe_source(
    *,
    reference_root: Path,
    source: str,
    release_set: ReleaseSet | None = None,
) -> ReferenceSourceDetail:
    """Return the per-file detail view for a single source.

    Args:
        reference_root: The ``reference/`` directory.
        source: Source name (``"clinvar"`` / ``"grch38"`` / etc.).
        release_set: Optional explicit release set; defaults to bundled
            ``default``.

    Returns:
        A :class:`ReferenceSourceDetail` with file-level integrity.

    Raises:
        ValueError: ``source`` is not in the active release set.
    """
    rs = release_set if release_set is not None else load_release_set(DEFAULT_RELEASE_SET)
    matching = [e for e in rs.sources if e.source == source]
    if not matching:
        raise ValueError(
            f"Unknown source {source!r}; release set {rs.name!r} pins "
            f"{[e.source for e in rs.sources]!r}."
        )
    entry = matching[0]
    base_status = _classify_source(
        source=source,
        expected_release=entry.release,
        chroms=entry.chroms,
        reference_root=reference_root,
    )

    release_dir = reference_root / source / entry.release
    file_rows: list[ReferenceFileStatus] = []
    for relpath in [*base_status.present_files, *base_status.missing_files]:
        absolute = release_dir / relpath
        if not absolute.exists():
            file_rows.append(
                ReferenceFileStatus(relpath=relpath, present=False, size_bytes=None, bgzip_ok=None)
            )
            continue
        size = absolute.stat().st_size
        bgzip_ok: bool | None = None
        if _is_bgzip_target(relpath):
            try:
                bgzip_ok = verify_bgzip_eof_marker(absolute)
            except OSError:
                bgzip_ok = False
        file_rows.append(
            ReferenceFileStatus(relpath=relpath, present=True, size_bytes=size, bgzip_ok=bgzip_ok)
        )

    file_rows.sort(key=lambda f: f.relpath)
    return ReferenceSourceDetail(
        source=base_status.source,
        expected_release=base_status.expected_release,
        on_disk_release=base_status.on_disk_release,
        status=base_status.status,
        present_files=base_status.present_files,
        missing_files=base_status.missing_files,
        files=tuple(file_rows),
    )


class IntegrityFailure(BaseModel):
    """One file that failed the bgzip-EOF integrity check."""

    model_config = ConfigDict(extra="forbid")

    source: str
    relpath: str
    reason: Literal["truncated", "missing", "unreadable"]


def verify_release_set_integrity(
    *,
    reference_root: Path,
    release_set: ReleaseSet | None = None,
) -> tuple[str, list[IntegrityFailure]]:
    """Run the bgzip-EOF check across every expected file in the release set.

    Args:
        reference_root: The ``reference/`` directory.
        release_set: Optional explicit release set; defaults to bundled
            ``default``.

    Returns:
        Tuple of ``(release_set_name, [IntegrityFailure, ...])`` —
        empty failure list means every checked file is intact. Files
        without a bgzip extension (``.md5``, ``.tbi``, ``.fai``,
        ``.gzi``) are skipped silently — their integrity is checked
        elsewhere (sha256 sidecars + tabix's own framing).
    """
    rs = release_set if release_set is not None else load_release_set(DEFAULT_RELEASE_SET)
    failures: list[IntegrityFailure] = []
    for entry in rs.sources:
        status = _classify_source(
            source=entry.source,
            expected_release=entry.release,
            chroms=entry.chroms,
            reference_root=reference_root,
        )
        release_dir = reference_root / entry.source / entry.release
        for relpath in [*status.present_files, *status.missing_files]:
            if not _is_bgzip_target(relpath):
                continue
            absolute = release_dir / relpath
            if not absolute.is_file():
                failures.append(
                    IntegrityFailure(source=entry.source, relpath=relpath, reason="missing")
                )
                continue
            try:
                ok = verify_bgzip_eof_marker(absolute)
            except OSError:
                failures.append(
                    IntegrityFailure(source=entry.source, relpath=relpath, reason="unreadable")
                )
                continue
            if not ok:
                failures.append(
                    IntegrityFailure(source=entry.source, relpath=relpath, reason="truncated")
                )
    return rs.name, failures


__all__ = [
    "IntegrityFailure",
    "ReferenceFileStatus",
    "ReferenceSourceDetail",
    "ReferenceSourceStatus",
    "SourceStatus",
    "describe_release_set",
    "describe_source",
    "verify_release_set_integrity",
]
