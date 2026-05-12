"""JSON envelope contracts for ``--json`` CLI output.

Every ``--json`` payload conforms to the same envelope shape — the
schema-version field at the top is the agent's contract anchor. Adding
new optional fields to a payload doesn't bump the version; renaming or
removing fields requires a major bump and a deprecation cycle.

Promotion of ``INV-C-cli-output-stability`` from provisional → canonical
is gated on this module's contracts being stable across two phases of
the [rich-cli plan](../../../../docs/plans/active/rich-cli/) without
breaking changes.
"""

from __future__ import annotations

from typing import Any, Final, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

# Bump major for breaking changes; minor for additive changes. Agents
# check this once at startup and refuse to consume payloads from a
# major version they don't recognise.
CLI_OUTPUT_SCHEMA_VERSION: Final[str] = "1.0"


_PayloadT = TypeVar("_PayloadT")


class ErrorDetail(BaseModel):
    """Structured error envelope embedded in ``CliEnvelope.error``.

    Agents read ``error_type`` for routing and ``suggested_actions`` for
    surfacing remediation steps to the user. ``traceback`` is populated
    only when the user invoked with ``--debug``; never by default.
    """

    model_config = ConfigDict(extra="forbid")

    error_type: str = Field(
        description="Stable machine-readable identifier (e.g. 'precondition_error')."
    )
    message: str = Field(description="One-line human-readable summary.")
    details: dict[str, Any] = Field(
        default_factory=dict,
        description="Command-specific structured context (paths, IDs, etc.).",
    )
    suggested_actions: list[str] = Field(
        default_factory=list,
        description="Ordered remediation steps the user (or agent) can take.",
    )
    traceback: list[str] | None = Field(
        default=None,
        description="Python traceback frames; populated only under --debug.",
    )


class CliEnvelope(BaseModel, Generic[_PayloadT]):
    """Top-level wrapper around every ``--json`` payload.

    The envelope provides a stable shape across all commands: agents
    learn it once and apply it everywhere. ``payload`` is the
    command-specific structured result; ``error`` is populated instead
    of ``payload`` on non-zero exit codes.

    Both ``payload`` and ``error`` are mutually exclusive in practice
    (one will be ``None``), but the schema doesn't enforce that —
    individual command handlers do.
    """

    model_config = ConfigDict(extra="forbid")

    cli_output_schema_version: str = Field(
        default=CLI_OUTPUT_SCHEMA_VERSION,
        description="Envelope schema version; bumped per the contract above.",
    )
    command: str = Field(description="Dotted-form command name (e.g. 'host.doctor', 'refs.fetch').")
    payload: _PayloadT | None = Field(
        default=None,
        description="Command-specific structured result on success.",
    )
    error: ErrorDetail | None = Field(
        default=None,
        description="Populated on non-zero exit; mutually exclusive with payload.",
    )


__all__ = [
    "CLI_OUTPUT_SCHEMA_VERSION",
    "CliEnvelope",
    "ErrorDetail",
]
