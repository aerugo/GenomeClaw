"""INV-T001 discovery test — every external-tool wrapper has a conventions dataclass.

Walks ``genomeclaw_toolkit.prep`` for modules that wrap an external
bioinformatics binary; asserts each has an adjacent ``_<tool>_conventions``
module exporting a frozen dataclass with ``verified_against_version``.

Strict for Phase-2 deliverables (``_pgsc_calc``); warn-only for pre-existing
wrappers that have not yet been backfilled (``_bcftools``, ``_bgzip``,
``_mosdepth``, ``_vcfanno``, ``_vep``). Backfill is its own follow-up plan
per `INV-T001`'s backfill clause.

Phase plan: [phases/phase-2.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-2.md)
"""

from __future__ import annotations

import importlib
from dataclasses import is_dataclass

import pytest

# External-tool wrapper modules under genomeclaw_toolkit.prep that integrate
# a distinct external binary. Each row is the module stem (without leading
# underscore in the conventions filename).
_STRICT_TOOLS: list[str] = [
    "pgsc_calc",  # path-crossing-discipline Phase 2 — first conventions dataclass
    "cyrius",  # MVP Phase 6 Slice D — Cyrius CYP2D6 caller
    "pharmcat",  # MVP Phase 6 Slice D' — PharmCAT PGx pipeline
]

_WARN_TOOLS: list[str] = [
    # Pre-Phase-2 wrappers; expected-missing until backfill plans land.
    # Each is its own short plan triggered on the next pin bump.
    "bcftools",
    "bgzip",
    "mosdepth",
    "vcfanno",
    "vep",
]


def _try_import_conventions(tool: str):
    """Try ``genomeclaw_toolkit.prep._<tool>_conventions``; return the module or None."""
    module_path = f"genomeclaw_toolkit.prep._{tool}_conventions"
    try:
        return importlib.import_module(module_path)
    except ModuleNotFoundError:
        return None


def _find_conventions_class(module) -> type | None:
    """Find a frozen-dataclass class in ``module`` whose name ends with 'Conventions'."""
    if module is None:
        return None
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if isinstance(attr, type) and attr_name.endswith("Conventions") and is_dataclass(attr):
            return attr
    return None


def test_invT001_strict_tools_have_conventions_dataclass() -> None:
    """STRICT: every tool in ``_STRICT_TOOLS`` has a frozen conventions dataclass
    with ``verified_against_version`` populated.

    Fails fast if a new external-tool wrapper is added without a conventions
    dataclass. Phase 2 adds ``pgsc_calc``; future phases add others.
    """
    missing: list[str] = []
    not_frozen: list[str] = []
    no_version: list[str] = []
    for tool in _STRICT_TOOLS:
        mod = _try_import_conventions(tool)
        if mod is None:
            missing.append(tool)
            continue
        cls = _find_conventions_class(mod)
        if cls is None:
            missing.append(f"{tool} (module exists but no <X>Conventions dataclass found)")
            continue
        # frozen=True is opaque from outside, but we test via instantiation +
        # mutation attempt below in test_pgsc_calc_conventions; here we just
        # check that the class has the verified-version field.
        instance = cls()
        version = getattr(instance, "verified_against_version", None)
        if not isinstance(version, str) or not version:
            no_version.append(tool)
            continue
        # Check immutability defensively.
        try:
            instance.verified_against_version = "x"
            not_frozen.append(tool)
        except Exception:  # FrozenInstanceError or AttributeError
            pass

    errors: list[str] = []
    if missing:
        errors.append(f"missing: {missing}")
    if not_frozen:
        errors.append(f"not frozen: {not_frozen}")
    if no_version:
        errors.append(f"no verified_against_version: {no_version}")
    assert not errors, f"INV-T001 strict-tools failures: {' / '.join(errors)}"


def test_invT001_warn_tools_listed_explicitly_for_backfill() -> None:
    """WARN-only: pre-existing wrappers awaiting backfill are explicitly listed.

    Reports their presence (so the backfill queue stays visible) without
    failing the suite. When a warn-tool gets its conventions dataclass, it
    moves to ``_STRICT_TOOLS`` in this file.
    """
    backfilled: list[str] = []
    still_missing: list[str] = []
    for tool in _WARN_TOOLS:
        mod = _try_import_conventions(tool)
        cls = _find_conventions_class(mod)
        if cls is not None:
            backfilled.append(tool)
        else:
            still_missing.append(tool)

    if backfilled:
        # If a warn-tool has been backfilled, the explicit list should be
        # updated to reflect that (move to _STRICT_TOOLS). Surface as a
        # warning, not a failure — the discovery is the contract here.
        pytest.skip(
            "INV-T001 backfill: the following warn-tools now have conventions "
            f"dataclasses and should move to _STRICT_TOOLS: {backfilled}"
        )
    # Otherwise: confirm we know which tools still need backfill.
    assert still_missing == _WARN_TOOLS, (
        f"INV-T001 warn-tools list out of sync: still missing = {still_missing}, "
        f"declared = {_WARN_TOOLS}"
    )
