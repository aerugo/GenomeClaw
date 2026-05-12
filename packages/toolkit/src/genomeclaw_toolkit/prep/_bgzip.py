"""Bgzip integrity helpers.

The BGZF (block gzip) format used by bcftools / htslib / vcfanno ends
every well-formed file with a 28-byte empty BGZF block. Truncation by
the fetcher (interrupted HTTP download, fileysystem write that lost
its tail, etc.) leaves a file whose body is valid bgzip framing but
whose trailing bytes are arbitrary data. Such files pass shallow
``htsfile`` / ``bcftools view -h`` checks (which only touch the
header) but fail mid-stream when a consumer reaches the truncation
point.

The check here is cheap (28-byte tail read) and definitive (the EOF
marker is invariant across BGZF versions). Run it post-fetch and
during ``genomeclaw refs verify``.

`INV-D-fetch-integrity` (provisional, from the rich-cli plan's
absorbed 4C.4 work): every bgzipped reference file passes this check
before the fetcher reports success.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from pathlib import Path


# File suffixes that are bgzip-framed and therefore eligible for the
# EOF-marker integrity check. Kept here so callers (fetcher + refs
# verify + future ingest pre-flight) share one source of truth.
BGZIP_SUFFIXES: Final[frozenset[str]] = frozenset({".vcf.gz", ".vcf.bgz", ".bcf"})


class IncompleteBgzip(RuntimeError):
    """A bgzipped file lacks the canonical 28-byte BGZF EOF marker.

    Raised by the fetcher's post-download integrity check when the
    payload's tail doesn't match :data:`BGZF_EOF_MARKER`. The partial
    file is removed before this exception propagates.
    """


# The 28-byte empty-block trailer that every well-formed BGZF file
# ends with. Defined in the BAM/SAM specification, section 4.1.2:
# https://samtools.github.io/hts-specs/SAMv1.pdf — the "BGZF EOF
# marker". Reading these 28 bytes from any valid bgzipped file
# (``.vcf.gz`` / ``.vcf.bgz`` / ``.bcf`` / ``.bam``) yields exactly
# this byte sequence.
BGZF_EOF_MARKER: Final[bytes] = bytes.fromhex(
    "1f8b08040000000000ff0600424302001b0003000000000000000000"
)


def verify_bgzip_eof_marker(path: Path) -> bool:
    """Return ``True`` iff the file ends with the canonical BGZF EOF marker.

    Args:
        path: Filesystem path to a bgzipped file. The path must exist;
            the function does not silently treat a missing file as a
            failed check (that would mask layout bugs).

    Returns:
        ``True`` when the trailing 28 bytes match :data:`BGZF_EOF_MARKER`;
        ``False`` for any other tail (truncated bgzip, plain gzip without
        the trailer, empty file, etc.).

    Raises:
        FileNotFoundError: When ``path`` does not exist.
        OSError: When the file cannot be opened for reading.
    """
    if not path.is_file():
        raise FileNotFoundError(f"bgzip verify target not found: {path}")
    marker_len = len(BGZF_EOF_MARKER)
    with path.open("rb") as fh:
        # Seek from end so we don't read the whole file for a tail check.
        fh.seek(-marker_len, 2)
        tail = fh.read(marker_len)
    return tail == BGZF_EOF_MARKER


def is_bgzip_target(relpath: str) -> bool:
    """Return True iff ``relpath`` has a bgzip suffix worth EOF-checking."""
    return any(relpath.endswith(suf) for suf in BGZIP_SUFFIXES)


__all__ = [
    "BGZF_EOF_MARKER",
    "BGZIP_SUFFIXES",
    "IncompleteBgzip",
    "is_bgzip_target",
    "verify_bgzip_eof_marker",
]
