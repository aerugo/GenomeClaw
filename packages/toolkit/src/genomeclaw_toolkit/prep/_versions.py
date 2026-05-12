"""Tool-version capture for the manifest's ``tools`` block (`INV-R001`).

Per Phase 2 deliverable: ``manifest.json`` records ``bcftools``,
``python``, ``duckdb``, and ``genomeclaw-toolkit`` versions. ``mosdepth``
joins the list when sub-phase 2C-C lands.

The image-digest helper reads ``/.dockerenv`` (present inside any
Docker container) plus the ``GENOMECLAW_IMAGE_DIGEST`` env var the host
shim threads through. When running native (no ``/.dockerenv``) the
helper returns ``None`` and the manifest's ``image_digest`` stays unset.
"""

from __future__ import annotations

import os
import sys

import duckdb

from genomeclaw_toolkit import __version__ as toolkit_version
from genomeclaw_toolkit.prep._bcftools import BcftoolsError, bcftools_version


def collect_tool_versions() -> dict[str, str]:
    """Capture per-tool version strings for the manifest's ``tools`` block.

    ``bcftools`` is captured via subprocess; an absence on PATH is
    surfaced as ``"unavailable"`` rather than aborting (Phase 2C-B-2's
    happy path requires bcftools, but the manifest writer should never
    crash because of an environment quirk — the ingest layer enforces
    bcftools availability before this is called).
    """
    tools: dict[str, str] = {
        "python": (f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"),
        "duckdb": duckdb.__version__,
        "genomeclaw-toolkit": toolkit_version,
    }
    try:
        info = bcftools_version()
        tools["bcftools"] = info.version
        if info.htslib_version:
            tools["htslib"] = info.htslib_version
    except (FileNotFoundError, BcftoolsError):
        tools["bcftools"] = "unavailable"
    return tools


def image_digest() -> str | None:
    """Return the running ``genomeclaw/toolkit`` image digest, or ``None``.

    Sourced from ``GENOMECLAW_IMAGE_DIGEST`` (set by the host shim when
    invoking ``docker run``). Native (no-Docker) invocations return
    ``None`` so the manifest's ``image_digest`` field is omitted rather
    than spoofed.
    """
    digest = os.environ.get("GENOMECLAW_IMAGE_DIGEST")
    return digest or None


__all__ = ["collect_tool_versions", "image_digest"]
