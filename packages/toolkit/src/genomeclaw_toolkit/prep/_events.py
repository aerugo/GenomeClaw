"""Long-running-operation progress events.

The event hierarchy is the canonical seam between long-running
orchestrators (fetch, pipeline stages) and the rich + JSON renderers.
Each subclass is a frozen dataclass — handlers can cache, dedup, or
buffer events freely. ``to_json_dict`` returns the line-oriented NDJSON
shape consumed by ``--json`` mode.

The event ``event`` discriminator names are part of the public
``cli_output_schema_version`` contract — adding new event types is
additive (minor bump); renaming an existing event requires a major
bump + deprecation cycle.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar


@dataclass(frozen=True, slots=True)
class _ProgressEvent:
    """Base type for every progress event emitted by an orchestrator.

    Subclasses set a ``_event_type`` class variable (the NDJSON
    discriminator) and add their own fields. The base intentionally has
    no fields so subclasses control field ordering for stable JSON
    output.
    """

    _event_type: ClassVar[str] = ""

    def to_json_dict(self) -> dict[str, Any]:
        """Return an NDJSON-ready dict with the ``event`` discriminator first.

        Subclasses inherit this implementation; the only requirement is
        that every field is JSON-serialisable as-is (strings, ints,
        floats — no nested dataclasses).
        """
        from dataclasses import asdict, fields

        # Skip private fields (the ClassVar isn't a field anyway, but
        # we filter for safety in case subclasses grow private state).
        payload: dict[str, Any] = {"event": type(self)._event_type}
        for f in fields(self):
            if f.name.startswith("_"):
                continue
            payload[f.name] = getattr(self, f.name)
        # ``asdict`` is unused here but imported for the side-effect
        # that ``fields()`` validates the dataclass shape at call time.
        _ = asdict
        return payload


@dataclass(frozen=True, slots=True)
class FileStart(_ProgressEvent):
    """A single file download is starting.

    Args:
        source: Source name (``"clinvar"``, ``"gnomad-exomes"``, …).
        relpath: File path relative to the release dir.
        total_bytes: Server-reported ``Content-Length``; ``None`` when
            the server omits the header.
    """

    source: str
    relpath: str
    total_bytes: int | None
    _event_type: ClassVar[str] = "file_start"


@dataclass(frozen=True, slots=True)
class FileProgress(_ProgressEvent):
    """An in-flight progress update for one file download.

    Emitted at coarse intervals (every few percent / few MB) to keep
    NDJSON streams from flooding the consumer.

    Args:
        source: Source name.
        relpath: Relative path being downloaded.
        bytes_so_far: Bytes written to disk so far this attempt.
        total_bytes: Server-reported total; ``None`` when unknown.
    """

    source: str
    relpath: str
    bytes_so_far: int
    total_bytes: int | None
    _event_type: ClassVar[str] = "file_progress"


@dataclass(frozen=True, slots=True)
class FileComplete(_ProgressEvent):
    """A single file download completed successfully.

    Args:
        source: Source name.
        relpath: Relative path that finished.
        bytes_written: Final on-disk byte count.
        md5: Hex MD5 of the downloaded bytes (lowercase, NCBI sidecar
            format). ``None`` when the source publishes no MD5 sidecar.
        duration_sec: Wall-clock duration of the download.
    """

    source: str
    relpath: str
    bytes_written: int
    md5: str | None
    duration_sec: float
    _event_type: ClassVar[str] = "file_complete"


@dataclass(frozen=True, slots=True)
class FileFailed(_ProgressEvent):
    """A single file download failed with an integrity error.

    Args:
        source: Source name.
        relpath: Relative path that failed.
        reason: Stable machine-readable failure code
            (``"truncated"`` / ``"incomplete_bgzip"`` / ``"stalled"`` /
            ``"checksum_mismatch"``).
        message: Human-readable error message.
    """

    source: str
    relpath: str
    reason: str
    message: str
    _event_type: ClassVar[str] = "file_failed"


@dataclass(frozen=True, slots=True)
class PhaseStart(_ProgressEvent):
    """A pipeline stage (ingest / normalize / annotate / materialize) is starting.

    Args:
        phase: Stage name (``"ingest"`` / ``"normalize"`` / …).
    """

    phase: str
    _event_type: ClassVar[str] = "phase_start"


@dataclass(frozen=True, slots=True)
class PhaseComplete(_ProgressEvent):
    """A pipeline stage finished successfully.

    Args:
        phase: Stage name.
        duration_sec: Wall-clock duration of the stage.
        run_dir: Path to the run directory the stage wrote to.
    """

    phase: str
    duration_sec: float
    run_dir: str
    _event_type: ClassVar[str] = "phase_complete"


@dataclass(frozen=True, slots=True)
class PhaseMessage(_ProgressEvent):
    """A beat-by-beat status update emitted from inside a running phase.

    Emitted by long-running orchestrators between :class:`PhaseStart`
    and :class:`PhaseComplete` so the user (rich mode) or NDJSON
    consumer sees what the phase is doing right now — "staging dbsnp",
    "[3/24] chr3 vcfanno running", "concatenating shards". Cosmetic:
    phase semantics don't depend on whether or how many of these the
    orchestrator emits.

    Args:
        phase: Parent phase name (``"ingest"`` / ``"annotate"`` / …).
            Must match the ``phase`` of the surrounding
            :class:`PhaseStart` / :class:`PhaseComplete` pair so the
            renderer can attribute the message to the right task row.
        message: Short user-facing description of the current beat.
            Phase prefix should NOT be included — the renderer adds
            it.
    """

    phase: str
    message: str
    _event_type: ClassVar[str] = "phase_message"


@dataclass(frozen=True, slots=True)
class PhaseFailed(_ProgressEvent):
    """A pipeline stage failed.

    Args:
        phase: Stage name that failed.
        error_type: Stable error-type identifier matching the
            ``CliError`` envelope's ``error_type`` field.
        message: Human-readable failure message.
    """

    phase: str
    error_type: str
    message: str
    _event_type: ClassVar[str] = "phase_failed"


@dataclass(frozen=True, slots=True)
class PipelineComplete(_ProgressEvent):
    """The chained ``pipeline run`` finished successfully.

    Args:
        run_dir: Final run directory.
        duration_sec: Total wall-clock duration across every stage.
    """

    run_dir: str
    duration_sec: float
    _event_type: ClassVar[str] = "pipeline_complete"


def emit_beat(
    callback: Any,
    *,
    phase: str,
    message: str,
    logger: Any = None,
) -> None:
    """Log + emit a :class:`PhaseMessage` beat in one call.

    Long-running orchestrators sprinkle this between heavy steps so the
    rich-mode user gets sub-phase visibility (printed above the live
    progress region) and the NDJSON consumer gets per-beat events.
    The same string also lands in the structured log via ``logger.info``
    when one is provided — that path is what populates the forensic log
    file the operator inspects when something goes wrong.

    Args:
        callback: The orchestrator's ``progress_callback`` (or
            ``None``). Tolerates ``None`` so the helper is safe to call
            from code paths that have no callback wired (tests, library
            consumers).
        phase: Parent phase name; passed into the :class:`PhaseMessage`.
        message: Beat description (without a phase prefix).
        logger: Optional :class:`logging.Logger`; when given, the beat
            is also written to it at INFO level.
    """
    if logger is not None:
        logger.info("%s: %s", phase, message)
    if callback is not None:
        callback(PhaseMessage(phase=phase, message=message))


__all__ = [
    "FileComplete",
    "FileFailed",
    "FileProgress",
    "FileStart",
    "PhaseComplete",
    "PhaseFailed",
    "PhaseMessage",
    "PhaseStart",
    "PipelineComplete",
    "emit_beat",
]
