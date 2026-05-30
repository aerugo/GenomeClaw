"""PGS Catalog evaluation-metrics gate (Plan 7 Phase 3).

Per `prs-calibration-phase3b` Phase 3: parse PGS Catalog evaluation
metrics from pgsc_calc's local pass-through (``log_scorefiles.json``) or
from a pre-downloaded ``reference_root/pgs_catalog/<pgs_id>.json``.
Extract:

- ``auc_delta = pgs_auc - clinical_baseline_auc``,
- ``top_decile_ci_lower``: lower bound of the top-decile OR/HR
  confidence interval.

Triggers the ``PGS_CATALOG_TIER_INSUFFICIENT`` decline when BOTH
``auc_delta < 0.02`` AND ``top_decile_ci_lower < 1.5``.

INV-P001: no network calls. INV-A003: provenance source is recorded
in the result (``log_scorefiles`` / ``reference_json`` / ``abstain``).
"""

from __future__ import annotations

import json
from pathlib import Path


def test_parse_pgs_catalog_eval_metrics_returns_none_when_no_source(tmp_path: Path) -> None:
    """Neither metadata file present → result.source == 'abstain'."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.source == "abstain"
    assert result.auc_delta is None
    assert result.top_decile_ci_lower is None
    assert result.abstain_reason == "metrics_unavailable"


def test_parse_pgs_catalog_eval_metrics_from_log_scorefiles(tmp_path: Path) -> None:
    """`log_scorefiles.json` carries evaluation metrics → parsed values returned."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    log_json = tmp_path / "log_scorefiles.json"
    log_json.write_text(
        json.dumps(
            {
                "PGS000018": {
                    "evaluation_metrics": {
                        "auc": 0.71,
                        "clinical_baseline_auc": 0.70,
                        "top_decile_or_ci_lower": 1.3,
                    }
                }
            }
        )
    )
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.source == "log_scorefiles"
    assert result.auc_delta is not None
    assert abs(result.auc_delta - 0.01) < 1e-9
    assert result.top_decile_ci_lower == 1.3
    assert result.abstain_reason is None


def test_parse_pgs_catalog_eval_metrics_log_scorefiles_in_subdir(tmp_path: Path) -> None:
    """`log_scorefiles.json` lives under a Nextflow hash dir; the parser finds it via rglob."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    deep = tmp_path / "ab" / "cdef1234"
    deep.mkdir(parents=True)
    (deep / "log_scorefiles.json").write_text(
        json.dumps(
            {
                "PGS000018": {
                    "evaluation_metrics": {
                        "auc": 0.75,
                        "clinical_baseline_auc": 0.70,
                        "top_decile_or_ci_lower": 1.8,
                    }
                }
            }
        )
    )
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.source == "log_scorefiles"
    assert result.auc_delta is not None
    assert abs(result.auc_delta - 0.05) < 1e-9


def test_parse_pgs_catalog_eval_metrics_falls_back_to_reference_json(tmp_path: Path) -> None:
    """No log_scorefiles → falls back to `reference_root/pgs_catalog/<pgs_id>.json`."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    ref = tmp_path / "reference" / "pgs_catalog"
    ref.mkdir(parents=True)
    (ref / "PGS000018.json").write_text(
        json.dumps(
            {
                "evaluation_metrics": {
                    "auc": 0.72,
                    "clinical_baseline_auc": 0.70,
                    "top_decile_or_ci_lower": 1.4,
                }
            }
        )
    )
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.source == "reference_json"
    assert result.auc_delta is not None
    assert abs(result.auc_delta - 0.02) < 1e-9
    assert result.top_decile_ci_lower == 1.4


def test_parse_pgs_catalog_eval_metrics_abstains_when_baseline_missing(tmp_path: Path) -> None:
    """No clinical_baseline_auc → abstain with reason `baseline_model_unspecified`."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    log_json = tmp_path / "log_scorefiles.json"
    log_json.write_text(
        json.dumps(
            {
                "PGS000018": {
                    "evaluation_metrics": {
                        "auc": 0.71,
                        "top_decile_or_ci_lower": 1.3,
                    }
                }
            }
        )
    )
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.source == "log_scorefiles"
    assert result.auc_delta is None
    assert result.abstain_reason == "baseline_model_unspecified"


def test_parse_pgs_catalog_eval_metrics_abstains_when_auc_missing(tmp_path: Path) -> None:
    """No AUC → abstain with reason `auc_unavailable`."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    log_json = tmp_path / "log_scorefiles.json"
    log_json.write_text(
        json.dumps(
            {
                "PGS000018": {
                    "evaluation_metrics": {
                        "clinical_baseline_auc": 0.70,
                    }
                }
            }
        )
    )
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.auc_delta is None
    assert result.abstain_reason == "auc_unavailable"


def test_parse_pgs_catalog_eval_metrics_handles_malformed_json(tmp_path: Path) -> None:
    """Malformed JSON → abstain with reason `malformed_metadata`. No exception."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    log_json = tmp_path / "log_scorefiles.json"
    log_json.write_text("{not valid json")
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.source == "abstain"
    assert result.abstain_reason == "malformed_metadata"


def test_parse_pgs_catalog_eval_metrics_real_pgsc_calc_v2_2_0_array_shape(tmp_path: Path) -> None:
    """Real pgsc_calc v2.2.0 emits `log_scorefiles.json` as a JSON array of
    ``{"header": {"pgs_id": ..., ...}}`` entries — NOT the dict-keyed-by-pgs_id
    shape the original synthetic tests assumed. The parser must recognise
    the array shape, find the matching pgs_id, and treat
    "evaluation_metrics absent" as `metrics_unavailable` (file shape is fine,
    fields we need just aren't there) rather than `malformed_metadata`.

    Captured from the 2026-05-21 real-data smoke at
    ``_scratch/prs_phase5_smoke/2026-05-21T18-18-47Z/pgsc_calc_work/0b/.../log_scorefiles.json``.
    """
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    log_json = tmp_path / "log_scorefiles.json"
    log_json.write_text(
        json.dumps(
            [
                {
                    "header": {
                        "pgs_id": "PGS000018",
                        "pgs_name": "metaGRS_CAD",
                        "trait_reported": "Coronary artery disease",
                        "variants_number": 1_745_180,
                        "weight_type": None,
                    }
                }
            ]
        )
    )
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    # Real pgsc_calc v2.2.0 doesn't pass through evaluation metrics — the
    # parser correctly finds the entry but abstains with metrics_unavailable,
    # NOT malformed_metadata (the JSON is perfectly well-formed).
    assert result.source == "log_scorefiles"
    assert result.auc_delta is None
    assert result.top_decile_ci_lower is None
    assert result.abstain_reason == "metrics_unavailable"


def test_parse_pgs_catalog_eval_metrics_array_shape_with_metrics(tmp_path: Path) -> None:
    """If a future pgsc_calc version augments the array entry with evaluation_metrics,
    the parser extracts them from the matched header entry."""
    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    log_json = tmp_path / "log_scorefiles.json"
    log_json.write_text(
        json.dumps(
            [
                {
                    "header": {"pgs_id": "PGS000019"},
                    "evaluation_metrics": {
                        "auc": 0.65,
                        "clinical_baseline_auc": 0.60,
                        "top_decile_or_ci_lower": 1.2,
                    },
                },
                {
                    "header": {"pgs_id": "PGS000018"},
                    "evaluation_metrics": {
                        "auc": 0.74,
                        "clinical_baseline_auc": 0.70,
                        "top_decile_or_ci_lower": 1.8,
                    },
                },
            ]
        )
    )
    result = parse_pgs_catalog_eval_metrics(
        work_dir=tmp_path,
        reference_root=tmp_path / "reference",
        pgs_id="PGS000018",
    )
    assert result.source == "log_scorefiles"
    assert result.auc_delta is not None
    assert abs(result.auc_delta - 0.04) < 1e-9
    assert result.top_decile_ci_lower == 1.8


def test_invP001_parse_pgs_catalog_eval_metrics_no_network_required(tmp_path: Path) -> None:
    """INV-P001: the parser opens only local files. Smoke-test the contract.

    A monkeypatch on `urllib.request.urlopen` (the obvious back-door) makes
    any accidental network call raise so the test fails loudly.
    """
    import urllib.request

    from genomeclaw_toolkit.prep._pgs_catalog_meta import parse_pgs_catalog_eval_metrics

    original = urllib.request.urlopen

    def _fail(*args, **kwargs):
        raise AssertionError("INV-P001: parse_pgs_catalog_eval_metrics issued a network call")

    try:
        urllib.request.urlopen = _fail  # type: ignore[assignment]
        result = parse_pgs_catalog_eval_metrics(
            work_dir=tmp_path,
            reference_root=tmp_path / "reference",
            pgs_id="PGS000018",
        )
        assert result.source == "abstain"  # no local files, no network → abstain
    finally:
        urllib.request.urlopen = original  # type: ignore[assignment]
