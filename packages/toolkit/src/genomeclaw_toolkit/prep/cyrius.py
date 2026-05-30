"""Cyrius CYP2D6 star-allele caller wrapper (Phase 6 Slice D).

Wraps Illumina's Cyrius (github.com/Illumina/Cyrius) — a single-purpose
Python tool that resolves CYP2D6 star-alleles from short-read BAM/CRAM
input. The output diplotype (e.g. ``*1/*4``) feeds PharmCAT's outside-
call interface for the ``*1/*4``-class PGx finding the project owner's
run actually depends on.

This wrapper subprocess-invokes ``star_caller.py``; tests stub
``subprocess.run`` and provide fixture output files. Real-data
verification runs as a manual smoke against the project owner's CRAM
after the toolkit image is rebuilt with ``bioconda::cyrius`` (deferred
per Slice D's scope decision).

The wrapper emits ``cyp2d6_diplotype.json`` under the run directory
with a self-describing envelope:

    {
      "sample_id": "...",
      "diplotype": "*1/*4",
      "filter_status": "PASS",
      "raw_cyrius_output": { ... full Cyrius JSON ... },
      "provenance": {
        "source_path": "...",
        "source_sha256": "...",
        "tool": "cyrius",
        "tool_version": "1.1.1",
        "params_json": "{...}",
        "schema_version": "v0.2",
        "created_at": "..."
      }
    }

The seven canonical INV-R001 provenance columns live inside the
``provenance`` block; the CLI subcommand stamps them at write time
rather than baking them into the wrapper signature.

Slice plan: [phases/phase-6-slice-d.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d.md)
"""

from __future__ import annotations

import hashlib
import json
import subprocess
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genomeclaw_toolkit.prep._cyrius_conventions import CyriusConventions
from genomeclaw_toolkit.schemas import SCHEMA_VERSION

_SUPPORTED_GENOME_BUILDS = ("GRCh38",)


class CyriusNoGenotypeError(RuntimeError):
    """Cyrius emitted no ``Genotype`` entry for the requested sample.

    Typically caused by a header SM-tag mismatch between the BAM and
    the requested ``sample_id``; surfaces as a clean error rather than
    a silently-empty diplotype envelope.
    """


@dataclass(frozen=True)
class CyriusDiplotypeRow:
    """The parsed Cyrius output for one sample, ready for downstream consumption.

    Frozen; the CLI subcommand stamps the seven canonical INV-R001
    provenance columns alongside this row at write time.
    """

    sample_id: str
    diplotype: str
    filter_status: str
    raw_cyrius_output: dict[str, Any]


def _sha256_of(path: Path, *, chunk_size: int = 1 << 20) -> str:
    """Return the SHA256 hexdigest of ``path``."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while True:
            chunk = fh.read(chunk_size)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _build_cyrius_argv(
    *,
    manifest_path: Path,
    output_dir: Path,
    prefix: str,
    conventions: CyriusConventions,
    threads: int | None = None,
    reference_fasta: Path | None = None,
) -> list[str]:
    """Build the Cyrius invocation argv from conventions.

    Every flag string comes from :class:`CyriusConventions` — the
    wrapper reads ``conv.manifest_flag`` rather than hardcoding
    ``"--manifest"`` so a future pin bump that flips the flag produces
    a typed-test failure (in :mod:`tests.unit.test_cyrius_conventions`)
    rather than a silent rc=1 against the real tool.

    ``reference_fasta`` is required when the input is a CRAM (pysam
    needs the reference to decompress); optional for BAM input. The
    wrapper threads it through if provided.
    """
    argv = [
        conventions.entrypoint,
        conventions.manifest_flag,
        str(manifest_path),
        conventions.genome_flag,
        conventions.genome_build_grch38,
        conventions.prefix_flag,
        prefix,
        conventions.output_dir_flag,
        str(output_dir),
    ]
    if threads is not None:
        argv += [conventions.threads_flag, str(threads)]
    if reference_fasta is not None:
        argv += [conventions.reference_flag, str(reference_fasta)]
    return argv


def _parse_cyrius_json(
    cyrius_output: Path,
    *,
    sample_id: str,
    conventions: CyriusConventions,
) -> tuple[str, str, dict[str, Any]]:
    """Parse Cyrius's per-sample JSON output. Returns ``(diplotype, filter, raw)``.

    Cyrius v1.1.1 emits a top-level dict keyed by **the BAM file's
    basename stem** (NOT by a sample-id arg — Cyrius has no
    ``--sample-id`` flag). The wrapper's contract is "one BAM per
    invocation," so the output always has exactly one entry; we pick
    it regardless of how it's keyed. The ``sample_id`` arg is the
    wrapper's *audit identity* (carried into the envelope's
    ``sample_id`` field), not Cyrius's internal key.

    If Cyrius's output also happens to carry ``sample_id`` as a direct
    key (e.g. when the BAM filename matches), that takes precedence —
    keeps the test fixtures' simpler shape working.
    """
    raw = json.loads(cyrius_output.read_text())

    # Empirical Cyrius v1.1.1 behavior (smoke 2026-05-22): the output is
    # keyed by the BAM file's basename stem. With a single-BAM manifest
    # the JSON has exactly one entry. Prefer ``sample_id`` if present
    # (test-fixture path); otherwise pick the single entry.
    if sample_id in raw:
        sample_block = raw[sample_id]
    elif len(raw) == 1:
        sample_block = next(iter(raw.values()))
    else:
        raise CyriusNoGenotypeError(
            f"Cyrius emitted no entry for sample_id={sample_id!r}; "
            f"available keys: {sorted(raw.keys())!r}. With a multi-BAM manifest "
            "the wrapper cannot disambiguate; use one BAM per invocation."
        )

    # Cyrius v1.1.1 emits ``Genotype`` and ``Filter`` as STRINGS, not lists
    # (empirical 2026-05-22 against the MPNRGLQ2K CRAM — initial README-based
    # assumption was wrong). The parser accepts either shape so test
    # fixtures that pre-date the empirical discovery still work.
    genotype_value = sample_block.get(conventions.output_genotype_key)
    filter_value = sample_block.get(conventions.output_filter_key)

    if isinstance(genotype_value, list):
        diplotype = genotype_value[0] if genotype_value else None
    else:
        diplotype = genotype_value

    if isinstance(filter_value, list):
        filter_status = filter_value[0] if filter_value else "UNKNOWN"
    else:
        filter_status = filter_value or "UNKNOWN"

    if not diplotype:
        raise CyriusNoGenotypeError(
            f"Cyrius emitted an empty Genotype for sample_id={sample_id!r}; "
            f"raw block: {sample_block!r}"
        )

    return diplotype, filter_status, raw


def call_cyp2d6(
    *,
    bam: Path,
    genome_build: str,
    run_dir: Path,
    sample_id: str,
    threads: int | None = None,
    reference_fasta: Path | None = None,
    conventions: CyriusConventions | None = None,
) -> CyriusDiplotypeRow | None:
    """Invoke Cyrius against ``bam``; return the parsed diplotype or ``None`` on no-call.

    Two return paths:

    - **Successful call**: returns :class:`CyriusDiplotypeRow`; writes
      ``cyp2d6_diplotype.json`` to ``run_dir`` with ``cyp2d6_status='called'``.
    - **No-call** (Cyrius emitted an empty Genotype — typically low coverage at
      the CYP2D6/CYP2D7 locus or structural variants interfering): returns
      ``None``; writes ``cyp2d6_no_call_envelope.json`` to ``run_dir`` with
      ``cyp2d6_status='no_call'``. The CLI handler reads the sentinel and
      inserts an indeterminate ``findings`` row so the agent surface never
      lacks a CYP2D6 signal (per the cyp2d6-no-call-finding plan).

    Args:
        bam: source BAM/CRAM (read-only; Cyrius opens it host-side; no
            mutation per INV-D001).
        genome_build: reference build. GRCh38 only in v0; other builds
            raise ``ValueError`` pre-subprocess.
        run_dir: derived run directory. Cyrius's output files
            (``cyp2d6.json``, ``cyp2d6.tsv``) land here alongside a
            one-line manifest (``cyrius_manifest.txt``).
        sample_id: the sample identifier Cyrius will key its output
            JSON sub-dict under. Typically the BAM's SM tag value.
        threads: optional worker-thread count.
        reference_fasta: reference fasta path. **Required when the
            input is a CRAM** (pysam needs the reference to decompress);
            ignored for BAM input. The wrapper passes it through via
            Cyrius's ``--reference`` flag.
        conventions: optional :class:`CyriusConventions`. Defaults to
            ``CyriusConventions()`` (canonical pinned defaults). Tests
            stub via :func:`dataclasses.replace`.

    Returns:
        :class:`CyriusDiplotypeRow` on a successful call, ``None`` on a no-call.

    Raises:
        ValueError: when ``genome_build`` is not in
            ``_SUPPORTED_GENOME_BUILDS`` OR when ``bam.suffix == '.cram'``
            but ``reference_fasta`` is None.
        RuntimeError: when Cyrius's ``subprocess.run`` exits non-zero.
        CyriusNoGenotypeError: when Cyrius emits no entry for ``sample_id``
            on a **multi-sample** manifest (the wrapper's contract is
            one-BAM-per-invocation; this is a programmer-error path, not
            the empty-Genotype no-call path which now returns ``None``).
    """
    if genome_build not in _SUPPORTED_GENOME_BUILDS:
        raise ValueError(
            f"GenomeClaw ships GRCh38 only; got genome_build={genome_build!r}. "
            "Cyrius supports GRCh37 + GRCh38, but the rest of the toolkit is "
            "GRCh38-only — re-export your BAM to GRCh38 or extend the wrapper."
        )

    if bam.suffix == ".cram" and reference_fasta is None:
        raise ValueError(
            f"CRAM input ({bam!s}) requires reference_fasta to be set — "
            "Cyrius's pysam handle cannot decompress CRAM blocks without it. "
            "Pass --reference-fasta <path> at the CLI or reference_fasta=<path> "
            "to call_cyp2d6()."
        )

    conv = conventions or CyriusConventions()

    # NOTE: Cyrius runs in-process via pysam — it does NOT spawn DooD
    # sibling containers the way pgsc_calc / Nextflow do. So the
    # path-crossing-discipline `as_sibling_mountable(...)` check used in
    # `prep/pgs.py` is unnecessary here; container-mount paths (under
    # `/mnt/genomeclaw/...`) resolve correctly inside the toolkit image
    # where Cyrius runs. INV-D006 applies to wrappers that spawn DooD
    # siblings; this wrapper is a sibling-free contract.
    run_dir.mkdir(parents=True, exist_ok=True)

    # One-BAM-per-line manifest: Cyrius's --manifest contract.
    manifest_path = run_dir / "cyrius_manifest.txt"
    manifest_path.write_text(f"{bam}\n")

    output_prefix = "cyp2d6"
    argv = _build_cyrius_argv(
        manifest_path=manifest_path,
        output_dir=run_dir,
        prefix=output_prefix,
        conventions=conv,
        threads=threads,
        reference_fasta=reference_fasta,
    )

    proc = subprocess.run(argv, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        stdout_tail = "\n".join(
            proc.stdout.decode("utf-8", errors="replace").splitlines()[-20:]
        )
        raise RuntimeError(
            f"cyrius failed (rc={proc.returncode}):\n"
            f"--- stderr ---\n{stderr_text}\n"
            f"--- stdout (last 20 lines) ---\n{stdout_tail}"
        )

    cyrius_output = run_dir / conv.output_filename_template.format(prefix=output_prefix)
    params = {
        "genome_build": genome_build,
        "threads": threads,
        "reference_fasta": str(reference_fasta) if reference_fasta is not None else None,
    }
    try:
        diplotype, filter_status, raw = _parse_cyrius_json(
            cyrius_output, sample_id=sample_id, conventions=conv
        )
    except CyriusNoGenotypeError:
        # The empty-Genotype no-call path. Cyrius ran successfully but
        # could not call CYP2D6 — typically low coverage at the
        # CYP2D6/CYP2D7 locus or a structural variant. We don't want to
        # halt the pipeline (the user still needs the rest of their
        # findings); instead, write a sentinel envelope so the CLI
        # handler can INSERT an indeterminate `findings` row. Returning
        # `None` is the contract that lets the caller branch on the
        # no-call vs. success path.
        #
        # The multi-sample-manifest path also raises CyriusNoGenotypeError
        # but with a different message; distinguish by inspecting the
        # raw cyrius JSON. If the file has exactly one sample block with
        # an empty/missing Genotype field, treat it as no-call. Otherwise
        # re-raise (the multi-sample case is a programmer error, not a
        # data outcome).
        raw_payload = json.loads(cyrius_output.read_text())
        if len(raw_payload) == 1:
            sample_block = next(iter(raw_payload.values()))
            filter_value = sample_block.get(conv.output_filter_key)
            if isinstance(filter_value, list):
                filter_status_str = filter_value[0] if filter_value else "NO_CALL"
            else:
                filter_status_str = filter_value or "NO_CALL"
            _write_no_call_envelope(
                run_dir=run_dir,
                bam=bam,
                sample_id=sample_id,
                filter_status=filter_status_str,
                raw_cyrius_output=raw_payload,
                params=params,
            )
            return None
        raise

    row = CyriusDiplotypeRow(
        sample_id=sample_id,
        diplotype=diplotype,
        filter_status=filter_status,
        raw_cyrius_output=raw,
    )

    # Write the wrapper envelope to <run_dir>/cyp2d6_diplotype.json with
    # the seven canonical INV-R001 provenance fields stamped at write
    # time. The bam SHA256 + tool version live in the provenance block;
    # callers (CLI / future annotate-step consumer) read this envelope
    # rather than the raw cyp2d6.json.
    _write_diplotype_envelope(
        run_dir=run_dir,
        bam=bam,
        row=row,
        params=params,
    )

    return row


def _build_provenance_block(bam: Path, params: dict[str, Any]) -> dict[str, str]:
    """Build the seven-field INV-R001 provenance block shared by both envelopes."""
    from genomeclaw_toolkit.prep._versions import PGX_RUNTIME_VERSIONS

    return {
        "source_path": str(bam),
        "source_sha256": _sha256_of(bam) if bam.exists() else "",
        "tool": "cyrius",
        "tool_version": PGX_RUNTIME_VERSIONS["cyrius"],
        "params_json": json.dumps(params, sort_keys=True),
        "schema_version": SCHEMA_VERSION,
        "created_at": datetime.now(tz=UTC).isoformat(),
    }


def _write_diplotype_envelope(
    *,
    run_dir: Path,
    bam: Path,
    row: CyriusDiplotypeRow,
    params: dict[str, Any],
) -> Path:
    """Write the wrapper-emitted ``cyp2d6_diplotype.json`` envelope.

    Stamps the seven canonical INV-R001 provenance fields inside the
    ``provenance`` block. The CLI subcommand can pass through this
    helper directly when it owns the full provenance trail at invocation
    time; the wrapper calls it inline so a direct
    :func:`call_cyp2d6` invocation (outside the CLI) still produces the
    envelope downstream consumers expect.

    Includes ``cyp2d6_status='called'`` so downstream consumers can
    distinguish a successful diplotype from the no-call sentinel emitted
    by :func:`_write_no_call_envelope`.
    """
    envelope = {
        "cyp2d6_status": "called",
        "sample_id": row.sample_id,
        "diplotype": row.diplotype,
        "filter_status": row.filter_status,
        "raw_cyrius_output": row.raw_cyrius_output,
        "provenance": _build_provenance_block(bam, params),
    }
    envelope_path = run_dir / "cyp2d6_diplotype.json"
    envelope_path.write_text(json.dumps(envelope, indent=2, sort_keys=True))
    return envelope_path


def _write_no_call_envelope(
    *,
    run_dir: Path,
    bam: Path,
    sample_id: str,
    filter_status: str,
    raw_cyrius_output: dict[str, Any],
    params: dict[str, Any],
) -> Path:
    """Write the ``cyp2d6_no_call_envelope.json`` sentinel for the no-call path.

    Structurally identical to :func:`_write_diplotype_envelope` but uses a
    distinct filename + ``cyp2d6_status='no_call'`` + ``diplotype=None``
    so downstream consumers (the CLI handler, the PharmCAT skip-detect,
    the agent's findings reader) can distinguish the two states. The raw
    Cyrius output is preserved verbatim — it IS the evidence per INV-E001.
    """
    envelope = {
        "cyp2d6_status": "no_call",
        "sample_id": sample_id,
        "diplotype": None,
        "filter_status": filter_status,
        "raw_cyrius_output": raw_cyrius_output,
        "provenance": _build_provenance_block(bam, params),
    }
    envelope_path = run_dir / "cyp2d6_no_call_envelope.json"
    envelope_path.write_text(json.dumps(envelope, indent=2, sort_keys=True))
    return envelope_path


__all__ = [
    "CyriusDiplotypeRow",
    "CyriusNoGenotypeError",
    "call_cyp2d6",
]
