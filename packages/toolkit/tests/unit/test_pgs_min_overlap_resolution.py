"""prs-non-imputed-wgs Phase 1 — `_resolve_min_overlap()` precedence helper.

The wrapper's pgsc_calc argv now sources ``--min_overlap`` from a typed
helper, not from a hardcoded literal. The helper's contract:

1. Env var ``GENOMECLAW_PGSC_CALC_MIN_OVERLAP`` overrides the conventions
   dataclass default.
2. When the env var is unset, the value falls through to
   ``PgscCalcConventions.min_overlap_default_for_non_imputed_wgs`` (0.5
   per the prs-non-imputed-wgs spec).
3. Invalid env values (unparseable as float, out of [0.0, 1.0]) raise
   ``ValueError`` BEFORE pgsc_calc spawns. The typed error surface beats
   a silent fall-through to a wrong-by-default value, and a clean
   pre-flight error beats a confusing pgsc_calc rc=1.

Centralising the precedence here means the wrapper (for argv emission)
and the CLI (for ``params_json`` provenance) read the same value via the
same helper — no risk of the persisted ``min_overlap_used`` diverging
from what was actually passed to pgsc_calc.
"""

from __future__ import annotations

import pytest


def test_resolve_min_overlap_returns_conventions_default_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env var → conventions default (0.5 for non-imputed single-sample WGS)."""
    monkeypatch.delenv("GENOMECLAW_PGSC_CALC_MIN_OVERLAP", raising=False)

    from genomeclaw_toolkit.prep.pgs import _resolve_min_overlap

    assert _resolve_min_overlap() == 0.5


def test_resolve_min_overlap_env_var_overrides_conventions_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Env var ``GENOMECLAW_PGSC_CALC_MIN_OVERLAP`` takes precedence."""
    monkeypatch.setenv("GENOMECLAW_PGSC_CALC_MIN_OVERLAP", "0.6")

    from genomeclaw_toolkit.prep.pgs import _resolve_min_overlap

    assert _resolve_min_overlap() == 0.6


def test_resolve_min_overlap_returns_float_not_string(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The env-var path parses the string to float (not stringy fall-through).

    A regression where the helper returned ``"0.6"`` (string) would silently
    poison ``params_json`` provenance (JSON would write ``"min_overlap_used":
    "0.6"`` instead of ``0.6``) AND would coerce-format the argv value
    differently. Pinning the return type at the unit level catches this.
    """
    monkeypatch.setenv("GENOMECLAW_PGSC_CALC_MIN_OVERLAP", "0.42")

    from genomeclaw_toolkit.prep.pgs import _resolve_min_overlap

    value = _resolve_min_overlap()
    assert isinstance(value, float), (
        f"helper must return float; got {type(value).__name__} = {value!r}"
    )
    assert value == 0.42


def test_resolve_min_overlap_raises_on_unparseable_env_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An env var that can't parse as float surfaces as ``ValueError``.

    Silent fall-through to a wrong default would let a user-typed
    ``GENOMECLAW_PGSC_CALC_MIN_OVERLAP=O.5`` (capital-O typo) reach
    pgsc_calc and produce a confusing rc=1 hours later. The typed pre-
    flight error catches it before the 90-minute smoke starts.
    """
    monkeypatch.setenv("GENOMECLAW_PGSC_CALC_MIN_OVERLAP", "not-a-float")

    from genomeclaw_toolkit.prep.pgs import _resolve_min_overlap

    with pytest.raises(ValueError, match="GENOMECLAW_PGSC_CALC_MIN_OVERLAP"):
        _resolve_min_overlap()


def test_resolve_min_overlap_raises_on_out_of_range_env_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``--min_overlap`` is a proportion; values outside [0.0, 1.0] are invalid.

    pgsc_calc would reject ``--min_overlap 1.5`` downstream, but the
    failure mode would be a deep Nextflow log. Same pre-flight discipline:
    surface the bad value at the helper boundary.
    """
    monkeypatch.setenv("GENOMECLAW_PGSC_CALC_MIN_OVERLAP", "1.5")

    from genomeclaw_toolkit.prep.pgs import _resolve_min_overlap

    with pytest.raises(ValueError, match=r"\[0\.0, 1\.0\]"):
        _resolve_min_overlap()
