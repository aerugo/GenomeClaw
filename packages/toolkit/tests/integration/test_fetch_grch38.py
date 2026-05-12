"""Phase 4B — ``genomeclaw refs fetch --source grch38`` against a mocked HTTP backend.

Covers cases 1–4 from
``docs/plans/active/mvp/phases/phase-4.md`` Step 4B.1.

The real GRCh38 fetch is a deliberate user-initiated HTTPS download from
NCBI's `genomes/all/GCA/...` tree (~3 GB). For tests we redirect via
``base_url`` to a ``pytest-httpserver`` instance so CI never reaches
outside the runner.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

import pytest
from pytest_httpserver import HTTPServer

# Tiny synthetic "FASTA" payload — the fetcher never parses it (the
# parsing is samtools' job during the post-fetch ``samtools faidx``
# step). The MD5 below is deterministic from the bytes.
_TINY_FASTA_TEXT = (
    ">chr1\n"
    "ACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGTACGT\n"
    ">chr17\n"
    "GCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCATGCAT\n"
)


def _bgzip_bytes(text: str) -> bytes:
    """Return BGZF-compressed bytes via ``bgzip`` so the output is
    indistinguishable from a real ``GRCh38_no_alt_analysis_set.fna.gz``.

    Tests that need only the bytes-level checksum gates (cases 1, 3, 4)
    can use this; tests that need ``samtools faidx`` to actually index
    the result (case 2) need bgzipped output, not gzipped, because
    ``faidx`` requires a BGZF-formatted block-gzip.
    """
    proc = subprocess.run(
        ["bgzip", "--stdout"],
        input=text.encode(),
        check=True,
        capture_output=True,
    )
    return proc.stdout


def _have_bgzip() -> bool:
    return os.environ.get("GENOMECLAW_HAS_BIO") == "1" and (
        subprocess.run(["which", "bgzip"], capture_output=True).returncode == 0
    )


def _stage_grch38_response(
    httpserver: HTTPServer,
    *,
    payload: bytes,
    md5_override: str | None = None,
) -> str:
    """Wire a mocked NCBI-style endpoint pair: fasta + directory checksums.

    NCBI's grch38 assembly tree publishes ``md5checksums.txt`` (one
    entry per file in the directory) rather than per-file ``.md5``
    sidecars — so the mock serves the directory-level file with the
    real upstream line shape, and the fetcher's ``md5_checksums_relpath``
    mode hits it. ``md5_override`` injects a divergent hash so the
    ChecksumMismatch test fires.
    """
    md5_to_serve = md5_override or hashlib.md5(payload).hexdigest()
    fasta_relpath = (
        "/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38"
        "/seqs_for_alignment_pipelines.ucsc_ids"
        "/GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz"
    )
    checksums_relpath = (
        "/genomes/all/GCA/000/001/405/GCA_000001405.15_GRCh38"
        "/seqs_for_alignment_pipelines.ucsc_ids/md5checksums.txt"
    )
    httpserver.expect_request(fasta_relpath).respond_with_data(
        payload, content_type="application/gzip"
    )
    # Multi-line checksums file: include a few decoy entries so the
    # parser must actually match by filename, not just take the first
    # line. Format mirrors NCBI's: `<hex>  ./<fname>\n`.
    body = (
        "deadbeef00000000000000000000dead  ./GCA_000001405.15_GRCh38_GRC_exclusions.bed\n"
        f"{md5_to_serve}  ./GCA_000001405.15_GRCh38_no_alt_analysis_set.fna.gz\n"
        "1111111111111111111111111111aaaa  ./GCA_000001405.15_GRCh38_full_analysis_set.fna.gz\n"
    )
    httpserver.expect_request(checksums_relpath).respond_with_data(
        body.encode(),
        content_type="text/plain",
    )
    return httpserver.url_for("").rstrip("/")


# ---------------------------------------------------------------------------
# Cases 3, 4: host-runnable (raise before post-fetch hook fires).
#
# Case 1 needs the post-fetch hook to run end-to-end (gunzip → bgzip →
# samtools faidx). The on-disk file after the hook is a re-bgzipped
# copy of the upstream content, so byte-for-byte equality vs. the
# served payload no longer holds; the test asserts content equality
# instead (decompress + compare to the original FASTA text). Cases 3 + 4
# raise early and never reach the hook, so opaque bytes are fine for
# them and they stay host-runnable. The host-side soft-fail in
# ``_samtools_faidx_in_target_dir`` when bgzip/samtools is missing is
# exercised by the existing dispatch tests; in-image is where the hook
# actually fires.
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_fetch_grch38_writes_versioned_path_mocked(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Case 1: fetch writes ``grch38.fa.gz`` (bgzip), builds ``.fai``/``.gzi``,
    and stashes the upstream MD5 sidecar.
    """
    import gzip

    from genomeclaw_toolkit.prep.fetch import fetch

    if not _have_bgzip():
        pytest.skip("test payload requires bgzip on PATH")

    payload = _bgzip_bytes(_TINY_FASTA_TEXT)
    base_url = _stage_grch38_response(httpserver, payload=payload)

    written = fetch(
        source="grch38",
        reference_root=tmp_path,
        release="ncbi-2014",
        base_url=base_url,
    )

    expected = tmp_path / "grch38" / "ncbi-2014" / "grch38.fa.gz"
    assert written == expected
    assert expected.exists()
    # The on-disk file went through gunzip | bgzip in the post-fetch hook,
    # so the bytes differ from the served payload (different bgzip
    # framing). Content equivalence is what matters — decompressing the
    # on-disk file yields the same FASTA text we started with.
    assert gzip.decompress(expected.read_bytes()) == _TINY_FASTA_TEXT.encode()

    # Post-fetch hook also writes .fai + .gzi sidecars so downstream
    # tools can do random-access reads without a separate index pass.
    assert (expected.parent / "grch38.fa.gz.fai").exists()
    assert (expected.parent / "grch38.fa.gz.gzi").exists()

    # MD5 sidecar records the **upstream** NCBI hash (what was on the
    # wire), not the recompressed on-disk file. Documentation-only.
    md5_sidecar = tmp_path / "grch38" / "ncbi-2014" / "grch38.fa.gz.md5"
    assert md5_sidecar.exists()
    assert hashlib.md5(payload).hexdigest() in md5_sidecar.read_text()


def test_fetch_grch38_rejects_checksum_mismatch_mocked(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Case 3: wrong-checksum server response → ChecksumMismatch; no canonical file written."""
    from genomeclaw_toolkit.prep.fetch import ChecksumMismatch, fetch

    base_url = _stage_grch38_response(
        httpserver,
        payload=b"opaque-fasta-bytes",
        md5_override="0" * 32,
    )

    with pytest.raises(ChecksumMismatch):
        fetch(
            source="grch38",
            reference_root=tmp_path,
            release="ncbi-2014",
            base_url=base_url,
        )

    canonical = tmp_path / "grch38" / "ncbi-2014" / "grch38.fa.gz"
    assert not canonical.exists()


def test_fetch_grch38_refuses_to_overwrite_existing_release(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    """Case 4 (`INV-D001`): a previously-fetched release is **not** overwritten by a re-run."""
    from genomeclaw_toolkit.prep.fetch import VersionAlreadyExists, fetch

    base_url = _stage_grch38_response(httpserver, payload=b"new-fasta-bytes")

    prior = tmp_path / "grch38" / "ncbi-2014" / "grch38.fa.gz"
    prior.parent.mkdir(parents=True)
    prior.write_bytes(b"PRIOR-FETCH-CONTENTS")
    prior_sha256 = hashlib.sha256(prior.read_bytes()).hexdigest()

    with pytest.raises(VersionAlreadyExists):
        fetch(
            source="grch38",
            reference_root=tmp_path,
            release="ncbi-2014",
            base_url=base_url,
        )

    # The previous version's bytes are unchanged.
    assert prior.exists()
    assert hashlib.sha256(prior.read_bytes()).hexdigest() == prior_sha256


# ---------------------------------------------------------------------------
# Case 2: needs bgzip + samtools (the post-fetch hook builds the .fai)
# ---------------------------------------------------------------------------


@pytest.mark.needs_bio
def test_fetch_grch38_builds_fai_index(httpserver: HTTPServer, tmp_path: Path) -> None:
    """Case 2: after fetch, the ``.fai`` index exists and ``samtools faidx`` is satisfied.

    The fetcher's GRCh38 layout includes a post-fetch hook that runs
    ``samtools faidx <out>`` to build the index in the same directory.
    Without this, downstream consumers (``bcftools norm -f``,
    ``mosdepth --fasta``, VEP) would each have to build it on first
    use — duplicated work and a race condition between concurrent
    pipeline runs.
    """
    from genomeclaw_toolkit.prep.fetch import fetch

    if not _have_bgzip():
        pytest.skip("samtools faidx requires a bgzipped fasta; needs bgzip on PATH")

    payload = _bgzip_bytes(_TINY_FASTA_TEXT)
    base_url = _stage_grch38_response(httpserver, payload=payload)

    written = fetch(
        source="grch38",
        reference_root=tmp_path,
        release="ncbi-2014",
        base_url=base_url,
    )

    fai = written.with_suffix(".gz.fai")
    gzi = written.with_suffix(".gz.gzi")
    assert fai.exists(), f"expected .fai sidecar at {fai}"
    # bgzipped fastas use a .gzi index too; both should be present.
    assert gzi.exists(), f"expected .gzi sidecar at {gzi}"

    # Round-trip: ``samtools faidx <fa> chr1`` returns bytes (not an error).
    proc = subprocess.run(
        ["samtools", "faidx", str(written), "chr1"],
        capture_output=True,
        check=True,
    )
    assert proc.stdout.startswith(b">chr1")
