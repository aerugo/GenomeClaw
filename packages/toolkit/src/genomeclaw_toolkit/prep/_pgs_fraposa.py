"""Parse pgsc_calc's FRAPOSA `.pcs` outputs + compute superpop Mahalanobis distance.

Per `prs-calibration-phase3b` Phase 2 (INV-C001 v1.7 ancestry-calibration
branch): pgsc_calc's ``--run_ancestry`` step writes per-sample and
reference-panel top-10 principal-component coordinates into
``<work_dir>/ancestry/fraposa/``. This module:

1. parses the per-sample ``.pcs`` file into ``{sample_id: ndarray(10)}``;
2. parses the reference-panel ``.pcs`` into ``{superpop: ndarray(n, 10)}``
   using a caller-supplied ``IID → superpop`` label map;
3. computes the Mahalanobis distance from the per-sample vector to each
   superpopulation centroid; returns ``(min_distance, nearest_label)``;
4. parses PGS Catalog ``gwas_ancestry`` strings into the canonical
   superpopulation-code set that ``classify_calibration`` consults for
   the ``ANCESTRY_CALIBRATION_UNCERTAIN`` trigger.

INV-R002 guard: a header-only ``.pcs`` file raises :class:`FraposaPcsError`
rather than persisting a degenerate 0.0 distance. A superpop with fewer
samples than PCs (rank-deficient covariance) likewise raises.

INV-P001 hold: every input is a local path; no network call is issued.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np


# Mahalanobis distance computes against the top-10 PCs FRAPOSA emits.
# pgsc_calc v2.2.0 always writes PC1–PC10; if a future pin changes the
# count the parser will raise a clear error rather than silently truncating.
_PC_COUNT = 10


class FraposaPcsError(RuntimeError):
    """A FRAPOSA `.pcs` file is degenerate, malformed, or rank-deficient.

    Raised by the parser when the per-sample file has zero data rows
    (per INV-R002: never persist a 0-distance derived from a degenerate
    artifact) and by the distance helper when a superpopulation has
    fewer reference samples than principal components (rank-deficient
    covariance — :func:`numpy.linalg.inv` would silently produce noise).
    """


def parse_fraposa_sample_pcs(pcs_path: Path) -> dict[str, np.ndarray]:
    """Parse a per-sample FRAPOSA `.pcs` file → ``{sample_id: ndarray(10)}``.

    The file is tab-delimited with header ``FID\\tIID\\tPC1\\t…\\tPC10``.
    Most pgsc_calc runs land a single sample, but the parser handles
    multiple rows for fixture flexibility.

    Args:
        pcs_path: Absolute path to ``<work_dir>/ancestry/fraposa/project/<sampleset>.pcs``.

    Returns:
        Dict mapping IID → numpy array of length 10 (PC1 … PC10).

    Raises:
        FraposaPcsError: when the file contains zero data rows (INV-R002
            degenerate-artifact guard) or when the header cannot be
            parsed for PC1..PC10.
    """
    with pcs_path.open("r", encoding="utf-8") as fh:
        header_line = fh.readline().rstrip("\n")
        fields = header_line.split("\t")
        try:
            iid_idx = fields.index("IID")
        except ValueError as exc:
            raise FraposaPcsError(
                f"FRAPOSA .pcs file {pcs_path} is missing the IID column "
                f"(header={fields!r}); cannot parse sample PCs."
            ) from exc
        pc_indices: list[int] = []
        for i in range(1, _PC_COUNT + 1):
            name = f"PC{i}"
            try:
                pc_indices.append(fields.index(name))
            except ValueError as exc:
                raise FraposaPcsError(
                    f"FRAPOSA .pcs file {pcs_path} is missing column {name!r} "
                    f"(header={fields!r}); FRAPOSA emits PC1..PC{_PC_COUNT}."
                ) from exc

        samples: dict[str, np.ndarray] = {}
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            cells = line.split("\t")
            if len(cells) <= max(iid_idx, *pc_indices):
                continue
            iid = cells[iid_idx]
            try:
                vec = np.array([float(cells[i]) for i in pc_indices], dtype=np.float64)
            except ValueError:
                continue
            samples[iid] = vec

    if not samples:
        raise FraposaPcsError(
            f"FRAPOSA .pcs file {pcs_path} contained 0 sample rows; "
            "expected >= 1. NOT processing degenerate FRAPOSA output "
            "(INV-R002). Common causes: pgsc_calc did not run "
            "`--run_ancestry`, FRAPOSA failed silently, or the sampleset "
            "glob picked the wrong file."
        )
    return samples


def parse_fraposa_ref_pcs(
    pcs_path: Path,
    *,
    pop_label_map: dict[str, str],
) -> dict[str, np.ndarray]:
    """Parse the reference-panel `.pcs` file, bucketing rows by superpop label.

    The reference `.pcs` file contains only ``FID``/``IID``; the caller
    supplies a ``IID → superpop`` map (typically built from the 1kGP +
    HGDP sample-metadata TSVs under ``reference_root/ancestry/``).
    Samples whose IID has no mapping are silently skipped so a partial
    label map degrades gracefully.

    Args:
        pcs_path: Reference panel `.pcs` (typically
            ``<work_dir>/ancestry/fraposa/pca/GRCh38_reference_extracted.pcs``).
        pop_label_map: ``{IID: superpop_label}`` (e.g. ``{"HG00096": "EUR"}``).

    Returns:
        ``{superpop_label: ndarray(n_samples_in_superpop, 10)}``. Empty
        dict if no samples match the label map.

    Raises:
        FraposaPcsError: when the header is missing ``IID`` or ``PC1..PC10``.
    """
    with pcs_path.open("r", encoding="utf-8") as fh:
        header_line = fh.readline().rstrip("\n")
        fields = header_line.split("\t")
        try:
            iid_idx = fields.index("IID")
        except ValueError as exc:
            raise FraposaPcsError(
                f"FRAPOSA reference .pcs file {pcs_path} is missing the IID column."
            ) from exc
        pc_indices: list[int] = []
        for i in range(1, _PC_COUNT + 1):
            name = f"PC{i}"
            try:
                pc_indices.append(fields.index(name))
            except ValueError as exc:
                raise FraposaPcsError(
                    f"FRAPOSA reference .pcs file {pcs_path} missing {name!r}."
                ) from exc

        buckets: dict[str, list[np.ndarray]] = {}
        for line in fh:
            line = line.rstrip("\n")
            if not line:
                continue
            cells = line.split("\t")
            if len(cells) <= max(iid_idx, *pc_indices):
                continue
            iid = cells[iid_idx]
            label = pop_label_map.get(iid)
            if label is None:
                continue
            try:
                vec = np.array([float(cells[i]) for i in pc_indices], dtype=np.float64)
            except ValueError:
                continue
            buckets.setdefault(label, []).append(vec)

    return {label: np.vstack(rows) for label, rows in buckets.items()}


def compute_mahalanobis_distances(
    sample_vec: np.ndarray,
    ref_by_superpop: dict[str, np.ndarray],
) -> tuple[float | None, str | None]:
    """Return ``(min_distance, nearest_superpop)`` over all superpop centroids.

    For each superpopulation, computes a centroid (column mean) and a
    full-rank covariance matrix from its reference samples; then computes
    the Mahalanobis distance ``D = sqrt((x-μ)^T Σ⁻¹ (x-μ))``. The
    smallest distance + its label are returned.

    Args:
        sample_vec: Length-10 numpy array (per-sample PC vector).
        ref_by_superpop: ``{superpop: ndarray(n_samples, 10)}`` from
            :func:`parse_fraposa_ref_pcs`.

    Returns:
        ``(min_distance, nearest_label)`` — ``(None, None)`` when
        ``ref_by_superpop`` is empty (caller should abstain on the
        ancestry axis).

    Raises:
        FraposaPcsError: when any superpop has fewer reference samples
            than principal components (rank-deficient covariance). The
            message names the offending superpop so the operator can
            diagnose the reference bundle.
    """
    if not ref_by_superpop:
        return (None, None)

    distances: dict[str, float] = {}
    for label, ref_matrix in ref_by_superpop.items():
        n_samples = ref_matrix.shape[0]
        if n_samples <= _PC_COUNT:
            raise FraposaPcsError(
                f"Superpopulation {label!r} has only {n_samples} reference "
                f"samples (<= {_PC_COUNT} PCs); the covariance matrix is "
                "rank-deficient and the Mahalanobis inversion would produce "
                "garbage. Check the reference bundle's population label map."
            )
        centroid = ref_matrix.mean(axis=0)
        # rowvar=False: each row is one observation, each column one variable.
        cov = np.cov(ref_matrix, rowvar=False)
        try:
            cov_inv = np.linalg.inv(cov)
        except np.linalg.LinAlgError as exc:
            raise FraposaPcsError(
                f"Superpopulation {label!r} has a singular covariance matrix; "
                "two or more reference samples may be identical."
            ) from exc
        delta = sample_vec - centroid
        # D² = δᵀ Σ⁻¹ δ. Clamp to ≥ 0 before sqrt to avoid tiny float-noise
        # negatives.
        d_squared = float(delta @ cov_inv @ delta)
        distances[label] = float(np.sqrt(max(d_squared, 0.0)))

    nearest = min(distances, key=lambda k: distances[k])
    return (distances[nearest], nearest)


def find_fraposa_project_pcs(work_dir: Path, *, sampleset: str) -> Path | None:
    """Glob ``<work_dir>/ancestry/fraposa/project/*<sampleset>.pcs``.

    pgsc_calc emits the file with a build-prefixed name
    (e.g. ``GRCh38_norm_oriented_norm_splitfamaa.pcs``). The orchestrator
    knows the bare sampleset but not the build prefix, so glob-by-suffix.

    Returns:
        First match (alphabetically sorted) or ``None`` if no FRAPOSA
        output is present (caller abstains on the ancestry axis).
    """
    project_dir = work_dir / "ancestry" / "fraposa" / "project"
    if not project_dir.is_dir():
        return None
    candidates = sorted(project_dir.glob(f"*{sampleset}.pcs"))
    return candidates[0] if candidates else None


# Recognised PGS Catalog ancestry strings. Keys are normalised to
# lowercase before lookup so casing variants ("European", "european",
# "EUROPEAN") all resolve. The five canonical 1kGP superpopulations +
# the two pgsc_calc extended codes (CSA, MID) per the development plan.
_GWAS_ANCESTRY_ALIASES: dict[str, str] = {
    "eur": "EUR",
    "european": "EUR",
    "europeans": "EUR",
    "white": "EUR",
    "afr": "AFR",
    "african": "AFR",
    "african american or afro-caribbean": "AFR",
    "african unspecified": "AFR",
    "sub-saharan african": "AFR",
    "amr": "AMR",
    "ad mixed american": "AMR",
    "hispanic or latin american": "AMR",
    "latino": "AMR",
    "eas": "EAS",
    "east asian": "EAS",
    "sas": "SAS",
    "south asian": "SAS",
    "csa": "CSA",
    "central/south asian": "CSA",
    "central asian": "CSA",
    "mid": "MID",
    "middle eastern": "MID",
    "greater middle eastern": "MID",
}


def parse_gwas_ancestry_superpops(gwas_ancestry: str | None) -> set[str]:
    """Parse a PGS Catalog ``gwas_ancestry`` string → ``{superpop, …}``.

    PGS Catalog metadata occasionally writes plain three-letter codes
    (``"EUR"``) and occasionally full English names (``"European, South
    Asian"``); this helper normalises both. Supported separators:
    comma, semicolon, ``" + "``, ``" and "``. Unrecognised tokens are
    silently dropped — an empty result tells :func:`classify_calibration`
    to abstain on the ancestry axis rather than incorrectly fire the
    decline.

    Returns:
        Set of canonical three-letter superpop codes (``EUR``, ``AFR``,
        ``AMR``, ``EAS``, ``SAS``, plus the pgsc_calc-extended ``CSA``
        and ``MID``). Empty set for ``None``, empty string, or unparseable input.
    """
    if not gwas_ancestry:
        return set()
    raw = gwas_ancestry.strip()
    if not raw:
        return set()
    # Normalise common separators to commas before splitting.
    for sep in (";", " + ", " and "):
        raw = raw.replace(sep, ",")
    tokens = [t.strip().lower() for t in raw.split(",") if t.strip()]
    found: set[str] = set()
    for token in tokens:
        canonical = _GWAS_ANCESTRY_ALIASES.get(token)
        if canonical is not None:
            found.add(canonical)
    return found


__all__ = [
    "FraposaPcsError",
    "compute_mahalanobis_distances",
    "find_fraposa_project_pcs",
    "parse_fraposa_ref_pcs",
    "parse_fraposa_sample_pcs",
    "parse_gwas_ancestry_superpops",
]
