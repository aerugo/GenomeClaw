"""Unit coverage for the bundled release-set loader.

The toolkit ships ``release_sets/default.toml`` (and may ship more
later). Tests target both the bundled default and synthetic malformed
manifests written to ``tmp_path`` to exercise the parser's failure
branches without committing intentionally-broken TOML to the repo.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def test_default_release_set_loads_and_pins_phase4_sources() -> None:
    """The shipped ``default.toml`` parses cleanly and includes every
    Phase-4 source ``annotate`` + ``materialize`` rely on.

    Originally the set covered just the vcfanno-overlay quartet (4C);
    Phase 4D added vep_cache + the two plugin-data sources (LOFTEE,
    AlphaMissense) so a single ``refs fetch --all`` populates everything
    the pipeline needs to run the full VEP chain.
    """
    from genomeclaw_toolkit.prep.release_sets import (
        DEFAULT_RELEASE_SET,
        load_release_set,
    )

    rs = load_release_set(DEFAULT_RELEASE_SET)

    assert rs.name == "default"
    assert rs.description
    sources = {e.source for e in rs.sources}
    assert sources == {
        "grch38",
        "clinvar",
        "dbsnp",
        "gnomad-exomes",
        "gnomad-constraint",
        "vep_cache",
        "alphamissense",
        "loftee",
        # PRS Reference Bootstrap Phase 1 — ancestry-calibration reference
        # for `pgsc_calc --run_ancestry` (INV-C001 v1.7).
        "pgs_catalog_ancestry",
        # PRS Input Coverage Fill Phase 5a — PGS Catalog scoring file
        # (PGS000018 smoke baseline). Parameterised by PGS ID via the
        # release column.
        "pgs_scorefile",
    }
    # Every entry pins a non-empty release label (`INV-R001` rebuildability).
    for e in rs.sources:
        assert e.release
    # gnomAD-exomes must carry an explicit chroms list — empty default
    # would skip every chromosome silently.
    gnomad = next(e for e in rs.sources if e.source == "gnomad-exomes")
    assert gnomad.chroms is not None
    assert "1" in gnomad.chroms and "X" in gnomad.chroms and "Y" in gnomad.chroms


def test_list_release_sets_includes_default() -> None:
    from genomeclaw_toolkit.prep.release_sets import list_release_sets

    names = list_release_sets()
    assert "default" in names


def test_load_release_set_raises_for_unknown_name() -> None:
    from genomeclaw_toolkit.prep.release_sets import (
        ReleaseSetNotFound,
        load_release_set,
    )

    with pytest.raises(ReleaseSetNotFound, match="not found"):
        load_release_set("nonexistent-set")


def _write_manifest(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, body: str) -> None:
    """Point the loader at ``tmp_path`` and drop ``synthetic.toml`` in it."""
    from genomeclaw_toolkit.prep import release_sets

    monkeypatch.setattr(release_sets, "_manifest_dir", lambda: tmp_path)
    (tmp_path / "synthetic.toml").write_text(body)


def test_load_release_set_rejects_missing_sources_array(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genomeclaw_toolkit.prep.release_sets import ReleaseSetMalformed, load_release_set

    _write_manifest(monkeypatch, tmp_path, 'name = "synthetic"\n')
    with pytest.raises(ReleaseSetMalformed, match="sources"):
        load_release_set("synthetic")


def test_load_release_set_rejects_entry_missing_release(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genomeclaw_toolkit.prep.release_sets import ReleaseSetMalformed, load_release_set

    _write_manifest(
        monkeypatch,
        tmp_path,
        'name = "synthetic"\n[[sources]]\nsource = "clinvar"\n',
    )
    with pytest.raises(ReleaseSetMalformed, match="release"):
        load_release_set("synthetic")


def test_load_release_set_rejects_chroms_wrong_type(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from genomeclaw_toolkit.prep.release_sets import ReleaseSetMalformed, load_release_set

    _write_manifest(
        monkeypatch,
        tmp_path,
        (
            'name = "synthetic"\n'
            "[[sources]]\n"
            'source = "gnomad-exomes"\n'
            'release = "v4.1"\n'
            "chroms = [1, 2, 3]\n"  # ints, not strings
        ),
    )
    with pytest.raises(ReleaseSetMalformed, match="chroms"):
        load_release_set("synthetic")
