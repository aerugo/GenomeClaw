"""FRAPOSA `.pcs` parser + Mahalanobis distance (Plan 7 Phase 2).

Per `prs-calibration-phase3b` Phase 2: parse pgsc_calc's FRAPOSA output
files (per-sample + reference-panel PCs) and compute the minimum
Mahalanobis distance from the user's PC vector to each 1kGP+HGDP
superpopulation centroid. The minimum distance + the nearest
superpopulation label drive the `ANCESTRY_CALIBRATION_UNCERTAIN`
classifier branch (tested separately in
``test_pgs_qc_ancestry_branch.py``).

INV-R002 guard: a `.pcs` file with zero data rows is a degenerate
FRAPOSA artifact and must raise ``FraposaPcsError`` rather than persist
a 0.0 distance.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest


_HEADER = "FID\tIID\tPC1\tPC2\tPC3\tPC4\tPC5\tPC6\tPC7\tPC8\tPC9\tPC10\n"


def _write_pcs(path: Path, rows: list[tuple[str, str, list[float]]]) -> None:
    """Write a tab-delimited FRAPOSA-shaped .pcs file. Each row is (FID, IID, 10 PCs)."""
    lines = [_HEADER]
    for fid, iid, pcs in rows:
        cells = [fid, iid] + [f"{v:.6f}" for v in pcs]
        lines.append("\t".join(cells) + "\n")
    path.write_text("".join(lines))


def test_parse_fraposa_sample_pcs_returns_sample_vector(tmp_path: Path) -> None:
    """A 1-sample .pcs file parses to a single (sample_id, 10-vector) entry."""
    from genomeclaw_toolkit.prep._pgs_fraposa import parse_fraposa_sample_pcs

    pcs_path = tmp_path / "sample.pcs"
    real_pcs = [-10.5845, -41.0037, 1.0416, -17.7813, 15.0012, 1.6987, -0.1475, -0.7264, -0.1899, 2.2386]
    _write_pcs(pcs_path, [("MPNRGLQ2K", "MPNRGLQ2K", real_pcs)])

    samples = parse_fraposa_sample_pcs(pcs_path)
    assert list(samples.keys()) == ["MPNRGLQ2K"]
    vec = samples["MPNRGLQ2K"]
    assert isinstance(vec, np.ndarray)
    assert vec.shape == (10,)
    np.testing.assert_allclose(vec, np.array(real_pcs), atol=1e-6)


def test_INV_R002_parse_fraposa_sample_pcs_raises_on_zero_data_rows(tmp_path: Path) -> None:
    """INV-R002: header-only .pcs file → FraposaPcsError. No 0-distance cached."""
    from genomeclaw_toolkit.prep._pgs_fraposa import FraposaPcsError, parse_fraposa_sample_pcs

    pcs_path = tmp_path / "sample.pcs"
    pcs_path.write_text(_HEADER)  # header only, no data

    with pytest.raises(FraposaPcsError) as exc_info:
        parse_fraposa_sample_pcs(pcs_path)
    msg = str(exc_info.value)
    assert "0 sample rows" in msg or "zero data rows" in msg.lower()
    assert "degenerate" in msg.lower() or "fraposa" in msg.lower()


def test_parse_fraposa_ref_pcs_groups_by_superpopulation(tmp_path: Path) -> None:
    """Reference panel rows are bucketed by superpop label using the IID→superpop map."""
    from genomeclaw_toolkit.prep._pgs_fraposa import parse_fraposa_ref_pcs

    pcs_path = tmp_path / "ref.pcs"
    _write_pcs(
        pcs_path,
        [
            ("EUR1", "EUR1", [1.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("EUR2", "EUR2", [3.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("AFR1", "AFR1", [0.0, 5.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("AFR2", "AFR2", [0.0, 7.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("EAS1", "EAS1", [0.0, 0.0, 2.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
            ("EAS2", "EAS2", [0.0, 0.0, 4.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0]),
        ],
    )
    pop_map = {
        "EUR1": "EUR", "EUR2": "EUR",
        "AFR1": "AFR", "AFR2": "AFR",
        "EAS1": "EAS", "EAS2": "EAS",
    }
    by_pop = parse_fraposa_ref_pcs(pcs_path, pop_label_map=pop_map)
    assert set(by_pop.keys()) == {"EUR", "AFR", "EAS"}
    assert by_pop["EUR"].shape == (2, 10)
    assert by_pop["AFR"].shape == (2, 10)
    np.testing.assert_allclose(by_pop["EUR"][:, 0], np.array([1.0, 3.0]))
    np.testing.assert_allclose(by_pop["AFR"][:, 1], np.array([5.0, 7.0]))


def test_parse_fraposa_ref_pcs_skips_samples_missing_from_pop_map(tmp_path: Path) -> None:
    """A reference sample without a pop-map entry is silently skipped (defensive)."""
    from genomeclaw_toolkit.prep._pgs_fraposa import parse_fraposa_ref_pcs

    pcs_path = tmp_path / "ref.pcs"
    _write_pcs(
        pcs_path,
        [
            ("EUR1", "EUR1", [1.0] + [0.0] * 9),
            ("OOPS", "OOPS", [2.0] + [0.0] * 9),  # no pop-map entry
            ("EUR2", "EUR2", [3.0] + [0.0] * 9),
        ],
    )
    pop_map = {"EUR1": "EUR", "EUR2": "EUR"}
    by_pop = parse_fraposa_ref_pcs(pcs_path, pop_label_map=pop_map)
    assert set(by_pop.keys()) == {"EUR"}
    assert by_pop["EUR"].shape == (2, 10)


def test_compute_mahalanobis_distances_picks_nearest_superpop() -> None:
    """Query point closer to superpop B; min distance + nearest label point at B."""
    from genomeclaw_toolkit.prep._pgs_fraposa import compute_mahalanobis_distances

    # Two well-separated reference clouds with >> 10 samples so the
    # sample covariance is a good estimator of the underlying 1.0 sigma.
    rng = np.random.default_rng(seed=0)
    ref_eur_centroid = np.zeros(10)
    ref_eas_centroid = np.array([20.0] + [0.0] * 9)
    eur = ref_eur_centroid + rng.normal(0, 1, size=(200, 10))
    eas = ref_eas_centroid + rng.normal(0, 1, size=(200, 10))

    # Query: sample mean of EUR (so the residual to the EUR centroid is 0).
    query = eur.mean(axis=0)

    min_d, nearest = compute_mahalanobis_distances(query, {"EUR": eur, "EAS": eas})
    assert nearest == "EUR"
    assert min_d == 0.0 or min_d < 1.0  # near zero — query is the sample centroid


def test_compute_mahalanobis_distances_far_query_yields_large_distance() -> None:
    """Query 30 sigma away from every centroid yields a > 3.0 distance."""
    from genomeclaw_toolkit.prep._pgs_fraposa import compute_mahalanobis_distances

    rng = np.random.default_rng(seed=1)
    ref_eur_centroid = np.zeros(10)
    eur = ref_eur_centroid + rng.normal(0, 1, size=(12, 10))

    # Query 30 units away on PC1.
    query = ref_eur_centroid.copy()
    query[0] = 30.0

    min_d, nearest = compute_mahalanobis_distances(query, {"EUR": eur})
    assert nearest == "EUR"
    assert min_d > 3.0


def test_compute_mahalanobis_distances_raises_when_too_few_samples_per_superpop() -> None:
    """A superpop with fewer reference samples than PCs (< 11) is rank-deficient.

    The pre-check raises ``FraposaPcsError`` so the inversion never runs against
    a singular matrix; the message names the offending superpop.
    """
    from genomeclaw_toolkit.prep._pgs_fraposa import FraposaPcsError, compute_mahalanobis_distances

    rng = np.random.default_rng(seed=2)
    # 5 samples × 10 PCs ⇒ rank-deficient covariance.
    eur = rng.normal(0, 1, size=(5, 10))
    query = np.zeros(10)

    with pytest.raises(FraposaPcsError) as exc_info:
        compute_mahalanobis_distances(query, {"EUR": eur})
    msg = str(exc_info.value)
    assert "EUR" in msg
    assert "rank" in msg.lower() or "singular" in msg.lower() or "samples" in msg.lower()


def test_compute_mahalanobis_distances_empty_ref_map_returns_none() -> None:
    """No reference superpops → (None, None) — abstain on missing reference data."""
    from genomeclaw_toolkit.prep._pgs_fraposa import compute_mahalanobis_distances

    query = np.zeros(10)
    min_d, nearest = compute_mahalanobis_distances(query, {})
    assert min_d is None
    assert nearest is None


def test_find_fraposa_project_pcs_globs_by_sampleset(tmp_path: Path) -> None:
    """Find ``ancestry/fraposa/project/*<sampleset>.pcs`` under a work-dir."""
    from genomeclaw_toolkit.prep._pgs_fraposa import find_fraposa_project_pcs

    project_dir = tmp_path / "ancestry" / "fraposa" / "project"
    project_dir.mkdir(parents=True)
    pcs_path = project_dir / "GRCh38_norm_oriented_norm_splitfamaa.pcs"
    _write_pcs(pcs_path, [("S1", "S1", [0.0] * 10)])

    found = find_fraposa_project_pcs(tmp_path, sampleset="norm_oriented_norm_splitfamaa")
    assert found == pcs_path


def test_find_fraposa_project_pcs_returns_none_when_missing(tmp_path: Path) -> None:
    """No FRAPOSA outputs in the work-dir → None (caller abstains)."""
    from genomeclaw_toolkit.prep._pgs_fraposa import find_fraposa_project_pcs

    found = find_fraposa_project_pcs(tmp_path, sampleset="whatever")
    assert found is None


def test_parse_gwas_ancestry_superpops_canonical_codes() -> None:
    """Plain 3-letter codes round-trip into the expected set."""
    from genomeclaw_toolkit.prep._pgs_fraposa import parse_gwas_ancestry_superpops

    assert parse_gwas_ancestry_superpops("EUR") == {"EUR"}
    assert parse_gwas_ancestry_superpops("EAS") == {"EAS"}
    assert parse_gwas_ancestry_superpops("EUR,EAS") == {"EUR", "EAS"}
    assert parse_gwas_ancestry_superpops("EUR, AFR") == {"EUR", "AFR"}
    assert parse_gwas_ancestry_superpops("EUR;SAS") == {"EUR", "SAS"}


def test_parse_gwas_ancestry_superpops_english_names() -> None:
    """PGS Catalog often writes the English population name (e.g. 'European')."""
    from genomeclaw_toolkit.prep._pgs_fraposa import parse_gwas_ancestry_superpops

    assert parse_gwas_ancestry_superpops("European") == {"EUR"}
    assert parse_gwas_ancestry_superpops("East Asian") == {"EAS"}
    assert parse_gwas_ancestry_superpops("South Asian") == {"SAS"}
    assert parse_gwas_ancestry_superpops("African") == {"AFR"}
    assert parse_gwas_ancestry_superpops("European, South Asian") == {"EUR", "SAS"}


def test_parse_gwas_ancestry_superpops_empty_returns_empty_set() -> None:
    """Empty / None / unrecognised → empty set (caller abstains on the ancestry axis)."""
    from genomeclaw_toolkit.prep._pgs_fraposa import parse_gwas_ancestry_superpops

    assert parse_gwas_ancestry_superpops("") == set()
    assert parse_gwas_ancestry_superpops("   ") == set()
    assert parse_gwas_ancestry_superpops("FooBarBaz") == set()
