"""Phase 6 Slice D' — ``PharmCATConventions`` frozen dataclass.

Captures PharmCAT v3.2.0's argv + outside-call TSV + output JSON
conventions in a typed dataclass mirroring ``CyriusConventions`` and
``PgscCalcConventions``. Wrapper tests assert against the dataclass
rather than against hardcoded strings; a future pin bump that changes a
flag produces a clear typed-test failure rather than a silent rc=1.

Promotes ``INV-T001`` — third entry in the strict-tools roster
alongside ``PgscCalcConventions`` + ``CyriusConventions``.

Slice plan: [phases/phase-6-slice-d-prime.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d-prime.md)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass

import pytest


def test_pharmcat_conventions_dataclass_exists_and_is_frozen() -> None:
    """The dataclass imports, is recognised as a dataclass, and is frozen."""
    from genomeclaw_toolkit.prep._pharmcat_conventions import PharmCATConventions

    assert is_dataclass(PharmCATConventions)
    conv = PharmCATConventions()
    with pytest.raises(FrozenInstanceError):
        conv.outside_call_flag = "--something-else"  # type: ignore[misc]


def test_pharmcat_conventions_verified_against_version_matches_pin() -> None:
    """``verified_against_version`` matches ``PGX_RUNTIME_VERSIONS['pharmcat']``."""
    from genomeclaw_toolkit.prep._pharmcat_conventions import PharmCATConventions
    from genomeclaw_toolkit.prep._versions import PGX_RUNTIME_VERSIONS

    assert PharmCATConventions().verified_against_version == PGX_RUNTIME_VERSIONS["pharmcat"]


def test_pharmcat_conventions_argv_fields_are_non_empty_strings() -> None:
    """Every argv-related conventions field is a non-empty string."""
    from genomeclaw_toolkit.prep._pharmcat_conventions import PharmCATConventions

    conv = PharmCATConventions()
    for field_name in (
        "entrypoint",
        "vcf_flag",
        "outside_call_flag",
        "output_dir_flag",
    ):
        value = getattr(conv, field_name)
        assert isinstance(value, str) and value, (
            f"PharmCATConventions.{field_name} must be a non-empty string; got {value!r}"
        )
