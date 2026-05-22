"""Phase 6 Slice D — ``CyriusConventions`` frozen dataclass.

Captures Cyrius v1.1.1's argv + output JSON schema in a typed dataclass
mirroring the ``PgscCalcConventions`` pattern. Each field's value
matches the upstream Illumina/Cyrius README; the wrapper tests assert
against the dataclass rather than against hardcoded strings so a future
pin bump that changes a flag name produces a clear typed-test failure
rather than a silent rc=1.

Promotes ``INV-T001`` (External-Tool Conventions Captured as Typed
Wrappers) — second entry alongside ``PgscCalcConventions``.

Slice plan: [phases/phase-6-slice-d.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d.md)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass

import pytest


def test_cyrius_conventions_dataclass_exists_and_is_frozen() -> None:
    """The dataclass imports, is recognised as a dataclass, and is frozen."""
    from genomeclaw_toolkit.prep._cyrius_conventions import CyriusConventions

    assert is_dataclass(CyriusConventions)
    conv = CyriusConventions()
    with pytest.raises(FrozenInstanceError):
        conv.manifest_flag = "--something-else"  # type: ignore[misc]


def test_cyrius_conventions_verified_against_version_matches_pin() -> None:
    """If a future pin bump moves ``PGX_RUNTIME_VERSIONS["cyrius"]`` without
    updating the conventions, this test fails loudly — the contract belongs
    to the version it was verified against."""
    from genomeclaw_toolkit.prep._cyrius_conventions import CyriusConventions
    from genomeclaw_toolkit.prep._versions import PGX_RUNTIME_VERSIONS

    assert CyriusConventions().verified_against_version == PGX_RUNTIME_VERSIONS["cyrius"]


def test_cyrius_conventions_argv_fields_are_non_empty_strings() -> None:
    """Every argv-related conventions field is a non-empty string."""
    from genomeclaw_toolkit.prep._cyrius_conventions import CyriusConventions

    conv = CyriusConventions()
    for field_name in (
        "entrypoint",
        "manifest_flag",
        "genome_flag",
        "prefix_flag",
        "output_dir_flag",
        "threads_flag",
        "output_genotype_key",
        "output_filter_key",
    ):
        value = getattr(conv, field_name)
        assert isinstance(value, str) and value, (
            f"CyriusConventions.{field_name} must be a non-empty string; got {value!r}"
        )
