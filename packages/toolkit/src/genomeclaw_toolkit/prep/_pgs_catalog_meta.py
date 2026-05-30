"""Parse PGS Catalog evaluation metrics from local sources (Plan 7 Phase 3).

Per `prs-calibration-phase3b` Phase 3 + INV-P001 (no network calls): two
local metadata sources can carry the AUC + top-decile-CI evaluation
metrics this module surfaces to ``classify_calibration``:

1. ``<work_dir>/log_scorefiles.json`` — pgsc_calc's per-run JSON that
   passes through PGS Catalog metadata. Searched first via ``rglob`` so
   files inside Nextflow hash directories are found without knowing the
   hash ahead of time.
2. ``<reference_root>/pgs_catalog/<pgs_id>.json`` — a pre-downloaded
   per-PGS metadata file (the existing
   ``genomeclaw refs fetch --source pgs_catalog`` post-hook is the
   canonical writer). Used as fallback.

The return value is an :class:`EvalMetricsResult` with the AUC delta,
the top-decile CI lower bound, the source label, and (when abstaining)
a structured ``abstain_reason``. The classifier consumes the two
numeric fields; the source label + abstain reason land in
``params_json`` for INV-A003 provenance.

This module does **not** issue any network calls. The
:func:`parse_pgs_catalog_eval_metrics` contract is local-files-only;
the test suite asserts this by monkeypatching ``urllib.request.urlopen``
to raise.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EvalMetricsResult:
    """PGS Catalog evaluation metrics extracted for one PGS ID.

    `source` is the structural record of which metadata file the values
    came from (``log_scorefiles`` / ``reference_json`` / ``abstain``).
    `abstain_reason` is non-None whenever the metrics couldn't be
    extracted; the orchestrator surfaces it in ``params_json`` so the
    audit trail records WHY the AUC gate didn't fire.
    """

    source: str
    auc_delta: float | None
    top_decile_ci_lower: float | None
    abstain_reason: str | None


# The PGS Catalog evaluation-metrics shape pgsc_calc passes through in
# ``log_scorefiles.json`` (verified empirically against pgsc_calc
# v2.2.0 outputs — the Phase 4 real-data smoke is the canonical reference
# for a known-good JSON shape).
_AUC_KEY = "auc"
_BASELINE_AUC_KEY = "clinical_baseline_auc"
_TOP_DECILE_CI_LOWER_KEY = "top_decile_or_ci_lower"


def _extract_eval_metrics_block(
    metadata: dict | None,
) -> tuple[float | None, float | None, str | None]:
    """Pull (auc_delta, top_decile_ci_lower, abstain_reason) from a metadata block.

    Returns a tuple where (a) ``auc_delta`` is ``None`` when either the AUC
    or the clinical baseline is missing, (b) ``top_decile_ci_lower`` is
    ``None`` when the key is absent, (c) ``abstain_reason`` is structural —
    the caller surfaces it in ``params_json``.
    """
    if metadata is None:
        return (None, None, "metrics_unavailable")
    eval_metrics = metadata.get("evaluation_metrics")
    if not isinstance(eval_metrics, dict):
        return (None, None, "metrics_unavailable")

    auc = eval_metrics.get(_AUC_KEY)
    baseline = eval_metrics.get(_BASELINE_AUC_KEY)
    top_decile_ci = eval_metrics.get(_TOP_DECILE_CI_LOWER_KEY)

    if not isinstance(auc, (int, float)):
        # No AUC ⇒ can't compute delta. But top-decile-CI alone is not
        # enough to fire the tier decline (BOTH conditions must hold),
        # so we still abstain on the AUC delta.
        return (None, top_decile_ci if isinstance(top_decile_ci, (int, float)) else None, "auc_unavailable")
    if not isinstance(baseline, (int, float)):
        # AUC present but clinical baseline is the floor we compare
        # against. PGS Catalog often omits this; abstain per the plan's
        # Q3 policy.
        return (None, top_decile_ci if isinstance(top_decile_ci, (int, float)) else None, "baseline_model_unspecified")

    auc_delta = float(auc) - float(baseline)
    ci_lower = float(top_decile_ci) if isinstance(top_decile_ci, (int, float)) else None
    return (auc_delta, ci_lower, None)


def _read_log_scorefiles(
    work_dir: Path, *, pgs_id: str
) -> tuple[dict | None, str | None]:
    """Locate + parse ``log_scorefiles.json`` under ``work_dir``.

    Two empirically-observed shapes are supported:

    1. **pgsc_calc v2.2.0** (the production shape, confirmed against
       2026-05-21 real-data smoke): a JSON **array** of
       ``{"header": {"pgs_id": ..., ...}, "evaluation_metrics": {...}?}``
       entries. The header carries trait/scorefile metadata;
       ``evaluation_metrics`` is absent in v2.2.0 (pgsc_calc does not
       pass through PGS Catalog AUC / top-decile-CI fields), so the
       parser typically returns ``"metrics_unavailable"`` for this shape.
    2. **Dict keyed by pgs_id** (the originally-assumed shape): a JSON
       dict where each top-level key is a PGS ID and the value carries
       ``evaluation_metrics``. Kept for forward compatibility if a
       future pgsc_calc version flips the shape.

    Returns ``(metadata_for_pgs_id, abstain_reason)``. The metadata dict
    contains a structured ``evaluation_metrics`` sub-block when present;
    ``abstain_reason`` is non-None when the file is malformed, the
    matching pgs_id entry has no metrics (``metrics_unavailable``), or
    no matching entry exists.
    """
    matches = sorted(work_dir.rglob("log_scorefiles.json"))
    if not matches:
        return (None, None)
    log_path = matches[0]
    try:
        payload = json.loads(log_path.read_text())
    except (OSError, json.JSONDecodeError):
        return (None, "malformed_metadata")

    metadata: dict | None = None
    if isinstance(payload, list):
        # pgsc_calc v2.2.0 array-of-entries shape: each entry's header.pgs_id
        # is the match key. The evaluation_metrics block (if present) is a
        # sibling of the header.
        for entry in payload:
            if not isinstance(entry, dict):
                continue
            header = entry.get("header")
            if not isinstance(header, dict):
                continue
            if header.get("pgs_id") == pgs_id:
                metadata = entry
                break
    elif isinstance(payload, dict):
        candidate = payload.get(pgs_id)
        if isinstance(candidate, dict):
            metadata = candidate
    else:
        return (None, "malformed_metadata")

    if metadata is None:
        # File present but no entry for this pgs_id; abstain on the
        # missing-data axis with a structural reason rather than declining.
        return (None, "metrics_unavailable")
    return (metadata, None)


def _read_reference_json(
    reference_root: Path, *, pgs_id: str
) -> tuple[dict | None, str | None]:
    """Read ``<reference_root>/pgs_catalog/<pgs_id>.json`` if it exists."""
    ref_path = reference_root / "pgs_catalog" / f"{pgs_id}.json"
    if not ref_path.exists():
        return (None, None)
    try:
        payload = json.loads(ref_path.read_text())
    except (OSError, json.JSONDecodeError):
        return (None, "malformed_metadata")
    if not isinstance(payload, dict):
        return (None, "malformed_metadata")
    return (payload, None)


def parse_pgs_catalog_eval_metrics(
    *,
    work_dir: Path,
    reference_root: Path,
    pgs_id: str,
) -> EvalMetricsResult:
    """Return PGS Catalog evaluation metrics for one PGS ID from local files.

    Source priority (per INV-P001 — no network calls):

    1. ``<work_dir>/**/log_scorefiles.json`` (pgsc_calc pass-through)
    2. ``<reference_root>/pgs_catalog/<pgs_id>.json`` (pre-downloaded)
    3. Abstain with ``abstain_reason='metrics_unavailable'``.

    A malformed JSON in either source yields
    ``source='abstain'`` + ``abstain_reason='malformed_metadata'`` rather
    than raising — the AUC gate is a secondary axis (the primary gate is
    overlap), so a metadata failure must not block the classifier.

    Args:
        work_dir: pgsc_calc Nextflow work-dir (parent of the hash
            directories).
        reference_root: GenomeClaw reference-data root (typically
            ``<repo>/data/reference``).
        pgs_id: PGS Catalog accession (e.g. ``"PGS000018"``).

    Returns:
        :class:`EvalMetricsResult`. When ``source != 'abstain'``,
        ``auc_delta`` and ``top_decile_ci_lower`` carry the parsed
        values (either may still be ``None`` if the underlying field
        was missing in the metadata). When ``source == 'abstain'``,
        ``abstain_reason`` names the cause.
    """
    metadata, abstain_reason = _read_log_scorefiles(work_dir, pgs_id=pgs_id)
    if abstain_reason == "malformed_metadata":
        return EvalMetricsResult(
            source="abstain",
            auc_delta=None,
            top_decile_ci_lower=None,
            abstain_reason="malformed_metadata",
        )
    if metadata is not None:
        auc_delta, ci_lower, reason = _extract_eval_metrics_block(metadata)
        return EvalMetricsResult(
            source="log_scorefiles",
            auc_delta=auc_delta,
            top_decile_ci_lower=ci_lower,
            abstain_reason=reason,
        )

    metadata, abstain_reason = _read_reference_json(reference_root, pgs_id=pgs_id)
    if abstain_reason == "malformed_metadata":
        return EvalMetricsResult(
            source="abstain",
            auc_delta=None,
            top_decile_ci_lower=None,
            abstain_reason="malformed_metadata",
        )
    if metadata is not None:
        auc_delta, ci_lower, reason = _extract_eval_metrics_block(metadata)
        return EvalMetricsResult(
            source="reference_json",
            auc_delta=auc_delta,
            top_decile_ci_lower=ci_lower,
            abstain_reason=reason,
        )

    return EvalMetricsResult(
        source="abstain",
        auc_delta=None,
        top_decile_ci_lower=None,
        abstain_reason="metrics_unavailable",
    )


__all__ = [
    "EvalMetricsResult",
    "parse_pgs_catalog_eval_metrics",
]
