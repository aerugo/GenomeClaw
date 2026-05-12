"""Curated reference dataset bundles (`genomeclaw refs fetch --all`).

A *release set* is a TOML manifest pinning one release per fetchable
source (ClinVar, GRCh38, dbSNP, gnomAD-exomes, …). The manifest is
shipped inside the toolkit package so two users on the same toolkit
version always fetch the same data — this is what makes `INV-R001`
(rebuildability) survive across machines without a network-lookup step
that would also widen the privacy egress surface (`INV-P001`).

Maintainers bump the curated set by adding a new TOML alongside
``default.toml`` (or editing ``default.toml`` for a minor refresh) and
shipping a new toolkit release. Users opt into the new pinned versions
by upgrading the toolkit; the on-disk path layout
``reference/<source>/<release>/`` makes coexisting releases a no-op
(adding ``clinvar/2026-06-13/`` next to ``clinvar/2026-05-09/``
doesn't disturb anything).
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from importlib import resources
from pathlib import Path

DEFAULT_RELEASE_SET = "default"


class ReleaseSetNotFound(LookupError):
    """The requested release-set name does not exist in the toolkit bundle."""


class ReleaseSetMalformed(ValueError):
    """The release-set TOML is missing required fields or has wrong types."""


@dataclass(frozen=True)
class ReleaseSetEntry:
    """One fetchable source pinned to one release inside a release set."""

    source: str
    release: str
    chroms: tuple[str, ...] | None = None
    """``None`` for single-file sources; concrete tuple for per-chrom
    sources (gnomad-exomes). The fetcher rejects ``chroms`` for
    single-file sources, so the manifest must not set it there."""


@dataclass(frozen=True)
class ReleaseSet:
    """A curated bundle of (source, release) pins."""

    name: str
    description: str
    sources: tuple[ReleaseSetEntry, ...]


def _manifest_dir() -> Path:
    """Filesystem path to the bundled ``release_sets/`` data directory.

    ``importlib.resources`` keeps this working when the toolkit is
    installed as a wheel (no source layout assumptions).
    """
    return Path(str(resources.files(__name__)))


def list_release_sets() -> list[str]:
    """Names of every release-set TOML bundled with the toolkit, sorted."""
    return sorted(p.stem for p in _manifest_dir().glob("*.toml"))


def load_release_set(name: str = DEFAULT_RELEASE_SET) -> ReleaseSet:
    """Parse and return the named release-set manifest.

    Raises ``ReleaseSetNotFound`` if no ``<name>.toml`` ships with this
    toolkit version; ``ReleaseSetMalformed`` if the file is present but
    structurally broken.
    """
    path = _manifest_dir() / f"{name}.toml"
    if not path.is_file():
        available = ", ".join(list_release_sets()) or "<none>"
        raise ReleaseSetNotFound(f"release set {name!r} not found; available: {available}")
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as exc:
        raise ReleaseSetMalformed(f"{path.name}: {exc}") from exc

    if not isinstance(data, dict):
        raise ReleaseSetMalformed(f"{path.name}: top level must be a table")

    manifest_name = data.get("name") or name
    description = data.get("description", "")
    raw_sources = data.get("sources")
    if not isinstance(raw_sources, list) or not raw_sources:
        raise ReleaseSetMalformed(f"{path.name}: 'sources' must be a non-empty array of tables")

    entries: list[ReleaseSetEntry] = []
    for idx, entry in enumerate(raw_sources):
        if not isinstance(entry, dict):
            raise ReleaseSetMalformed(f"{path.name}: sources[{idx}] must be a table")
        source = entry.get("source")
        release = entry.get("release")
        if not isinstance(source, str) or not source:
            raise ReleaseSetMalformed(
                f"{path.name}: sources[{idx}].source must be a non-empty string"
            )
        if not isinstance(release, str) or not release:
            raise ReleaseSetMalformed(
                f"{path.name}: sources[{idx}].release must be a non-empty string"
            )
        chroms_raw = entry.get("chroms")
        chroms: tuple[str, ...] | None
        if chroms_raw is None:
            chroms = None
        elif isinstance(chroms_raw, list) and all(isinstance(c, str) for c in chroms_raw):
            chroms = tuple(chroms_raw)
        else:
            raise ReleaseSetMalformed(
                f"{path.name}: sources[{idx}].chroms must be an array of strings"
            )
        entries.append(ReleaseSetEntry(source=source, release=release, chroms=chroms))

    return ReleaseSet(
        name=str(manifest_name),
        description=str(description),
        sources=tuple(entries),
    )


__all__ = [
    "DEFAULT_RELEASE_SET",
    "ReleaseSet",
    "ReleaseSetEntry",
    "ReleaseSetMalformed",
    "ReleaseSetNotFound",
    "list_release_sets",
    "load_release_set",
]
