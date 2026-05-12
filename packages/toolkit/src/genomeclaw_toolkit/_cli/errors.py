"""Structured error envelope + exit-code contract.

Every error path through the CLI converges on a ``CliError`` instance.
The top-level Typer callback catches ``CliError`` once, renders it in
the active output mode (rich panel or JSON ``ErrorDetail``), and exits
with the documented code.

Exit-code contract (per [spec § AC4](../../../../docs/plans/active/rich-cli/spec.md)):

* ``0`` — success
* ``1`` — runtime error (the operation tried and failed)
* ``2`` — usage error (invalid args; Typer surfaces these before the handler)
* ``3`` — precondition error (missing reference data, missing tool, missing run dir)
* ``4`` — data integrity error (truncated file, schema mismatch, contig mismatch)
* ``130`` — interrupted by ``SIGINT``

The classes are deliberately small Pydantic-friendly Python exceptions
— not Pydantic models — because ``raise`` needs a real exception type
and Pydantic doesn't subclass ``Exception``. The conversion to
``ErrorDetail`` (which IS a Pydantic model) happens at the CLI
boundary.
"""

from __future__ import annotations

from typing import Final

from genomeclaw_toolkit._cli.types.envelope import ErrorDetail

EXIT_SUCCESS: Final[int] = 0
EXIT_RUNTIME_ERROR: Final[int] = 1
EXIT_USAGE_ERROR: Final[int] = 2
EXIT_PRECONDITION_ERROR: Final[int] = 3
EXIT_DATA_INTEGRITY_ERROR: Final[int] = 4
EXIT_INTERRUPTED: Final[int] = 130


class CliError(Exception):
    """Base class for all CLI-boundary errors with a structured envelope.

    Subclasses pin a specific ``exit_code`` + ``error_type``. Command
    handlers raise these directly; the top-level boundary catches them
    and renders an envelope without ever exposing a Python traceback
    unless ``--debug`` is set.

    Attributes:
        message: One-line summary of what went wrong.
        details: Command-specific structured context (paths, IDs).
        suggested_actions: Ordered remediation steps.
        exit_code: Process exit status (per the contract above).
        error_type: Stable machine identifier for routing.
    """

    exit_code: int = EXIT_RUNTIME_ERROR
    error_type: str = "runtime_error"

    def __init__(
        self,
        message: str,
        *,
        details: dict[str, object] | None = None,
        suggested_actions: list[str] | None = None,
    ) -> None:
        """Initialise the error with its rendered context.

        Args:
            message: One-line user-facing summary.
            details: Optional structured context (paths, IDs, counts).
            suggested_actions: Optional ordered remediation steps.
        """
        super().__init__(message)
        self.message = message
        self.details: dict[str, object] = details or {}
        self.suggested_actions: list[str] = suggested_actions or []

    def to_envelope(self, *, traceback: list[str] | None = None) -> ErrorDetail:
        """Convert to the JSON-friendly ``ErrorDetail`` envelope.

        Args:
            traceback: Optional Python traceback frames; included only
                when ``--debug`` was set on the CLI invocation.

        Returns:
            A Pydantic ``ErrorDetail`` ready to embed in a ``CliEnvelope``.
        """
        return ErrorDetail(
            error_type=self.error_type,
            message=self.message,
            details=dict(self.details),
            suggested_actions=list(self.suggested_actions),
            traceback=traceback,
        )


class RuntimeFailure(CliError):  # noqa: N818 — semantic name; not all errors end in "Error"
    """Exit ``1`` — the operation tried to run and failed.

    Use for "ran the tool, the tool returned non-zero" or "wrote half
    the output then the destination went away." Distinguishes from
    precondition errors (``3``) where we never got far enough to try.
    """

    exit_code = EXIT_RUNTIME_ERROR
    error_type = "runtime_error"


class UsageError(CliError):
    """Exit ``2`` — invalid CLI arguments or flag combination.

    Typer raises its own ``UsageError`` for arg-validation failures;
    this class is for command-level usage problems that pass arg
    parsing but combine flags illegally (e.g. ``--bam`` without
    ``--bed``).
    """

    exit_code = EXIT_USAGE_ERROR
    error_type = "usage_error"


class PreconditionError(CliError):
    """Exit ``3`` — a required input or environment piece is missing.

    Examples: no canonical layout (run setup first), no derived run
    (run ingest first), required reference release absent on disk.
    The user fixes the precondition and retries.
    """

    exit_code = EXIT_PRECONDITION_ERROR
    error_type = "precondition_error"


class DataIntegrityError(CliError):
    """Exit ``4`` — a file's contents failed validation.

    Examples: truncated bgzip (no EOF marker), contig naming mismatch
    against the configured rename map, schema-version disagreement.
    The user fixes the data (often by re-fetching) and retries.
    """

    exit_code = EXIT_DATA_INTEGRITY_ERROR
    error_type = "data_integrity_error"


__all__ = [
    "EXIT_DATA_INTEGRITY_ERROR",
    "EXIT_INTERRUPTED",
    "EXIT_PRECONDITION_ERROR",
    "EXIT_RUNTIME_ERROR",
    "EXIT_SUCCESS",
    "EXIT_USAGE_ERROR",
    "CliError",
    "DataIntegrityError",
    "PreconditionError",
    "RuntimeFailure",
    "UsageError",
]
