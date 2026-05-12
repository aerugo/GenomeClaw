"""GenomeClaw host-side toolkit.

This package owns the host CLI (``genomeclaw``), the FastAPI host
service, and the schemas / Pydantic models the two share.
"""

from __future__ import annotations

from importlib import metadata

try:
    __version__ = metadata.version("genomeclaw-toolkit")
except metadata.PackageNotFoundError:
    __version__ = "0.0.0+dev"

__all__ = ["__version__"]
