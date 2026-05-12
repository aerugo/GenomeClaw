"""Shared input-resolution helpers for the command thin wrappers.

The ingest / normalize / annotate / materialize / pipeline commands
all share the same autodetect contracts for ``--vcf``, ``--reference``,
``--run-dir``. These helpers centralise the resolution + exception
mapping so each command's Typer handler stays small and consistent.

Module-private: ``_cli/commands/`` consumers only. Not re-exported
from ``_cli``.
"""

from __future__ import annotations

from pathlib import Path

from genomeclaw_toolkit._cli.errors import PreconditionError, UsageError
from genomeclaw_toolkit.prep.ingest import autodetect_sample_inputs
from genomeclaw_toolkit.prep.reference_build import autodetect_reference_dir
from genomeclaw_toolkit.prep.run_id import resolve_current_run_dir

# Sentinel value used by Typer's ``nargs='?'`` equivalents to signal
# "the user passed the flag without an argument; please autodetect."
AUTODETECT_SENTINEL = "<autodetect>"


def resolve_ingest_inputs(
    *,
    vcf: str | None,
    reference: str | None,
    sample_id: str | None,
    raw_root: Path,
    reference_root: Path,
) -> tuple[str, Path, Path]:
    """Resolve sample/VCF/reference triple from the user's flag values.

    Three forms supported per flag:

    * Explicit path (``--vcf /path/to/x.vcf.gz``) — used as-is.
    * Bare sentinel (``--vcf`` with no value) — autodetect from the
      matching root directory.
    * Omitted entirely — autodetect, same as the bare form.

    Args:
        vcf: User-supplied ``--vcf`` value (or sentinel / ``None``).
        reference: User-supplied ``--reference`` value (or sentinel / ``None``).
        sample_id: Optional ``--sample-id``; inferred from the
            autodetected sample dir if not given.
        raw_root: ``--raw-root`` for VCF autodetect.
        reference_root: ``--reference-root`` for reference autodetect.

    Returns:
        ``(sample_id, vcf_path, reference_dir)``.

    Raises:
        UsageError: ``--vcf`` given an explicit path without ``--sample-id``.
        PreconditionError: Autodetect couldn't resolve (zero or many
            candidates).
    """
    resolved_sample_id = sample_id
    if vcf is None or vcf == AUTODETECT_SENTINEL:
        try:
            detected_sample_id, vcf_path = autodetect_sample_inputs(raw_root)
        except ValueError as exc:
            raise PreconditionError(str(exc)) from exc
        if resolved_sample_id is None:
            resolved_sample_id = detected_sample_id
    else:
        vcf_path = Path(vcf)
        if resolved_sample_id is None:
            raise UsageError(
                "--sample-id is required when --vcf is given a path "
                "(omit --vcf to autodetect both from raw/)."
            )

    if reference is None or reference == AUTODETECT_SENTINEL:
        try:
            reference_dir = autodetect_reference_dir(reference_root)
        except ValueError as exc:
            raise PreconditionError(str(exc)) from exc
    else:
        reference_dir = Path(reference)

    return resolved_sample_id, vcf_path, reference_dir


def resolve_run_dir(*, run_dir: str | None, derived_root: Path) -> Path:
    """Resolve ``--run-dir`` to a concrete derived-run directory.

    Args:
        run_dir: User-supplied ``--run-dir`` value (or sentinel / ``None``).
        derived_root: ``--derived-root`` for CURRENT-symlink autodetect.

    Returns:
        The resolved run directory.

    Raises:
        PreconditionError: ``CURRENT`` symlink is missing or broken.
    """
    if run_dir is None or run_dir == AUTODETECT_SENTINEL:
        try:
            return resolve_current_run_dir(derived_root)
        except ValueError as exc:
            raise PreconditionError(str(exc)) from exc
    return Path(run_dir)


__all__ = ["AUTODETECT_SENTINEL", "resolve_ingest_inputs", "resolve_run_dir"]
