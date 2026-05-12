"""Shared type definitions for the GenomeClaw CLI layer.

This sub-package centralises the data shapes that flow between the CLI's
command modules and its renderers. Keeping them here (rather than near
the commands) lets renderers and tests depend on the shapes without
pulling in command-side logic — critical for `mypy --strict` and for
keeping the cold-start `--help` path tight.

Modules:
    envelope: top-level JSON envelope + error envelope + the
        ``CLI_OUTPUT_SCHEMA_VERSION`` constant that stamps every
        ``--json`` payload (`INV-C-cli-output-stability`, provisional).
"""

from __future__ import annotations

from genomeclaw_toolkit._cli.types.envelope import (
    CLI_OUTPUT_SCHEMA_VERSION,
    CliEnvelope,
    ErrorDetail,
)

__all__ = [
    "CLI_OUTPUT_SCHEMA_VERSION",
    "CliEnvelope",
    "ErrorDetail",
]
