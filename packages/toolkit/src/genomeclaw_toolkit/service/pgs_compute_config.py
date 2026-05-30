"""Read the ``prs_compute_config.json`` sidecar at host-service startup.

The E.3 worker needs the sample's CRAM path, reference root, scorefile
root, coverage TSVs, and reference fasta to invoke
:func:`compute_prs_with_coverage_fill`. ``bin/genomeclaw-prs-smoke`` and
the ``pipeline pgs-compute`` CLI take these as flags; the host service
reads them once from a sidecar at the active run-dir.

The sidecar is **one-time-per-deployment** configuration. Missing or
malformed → the host service logs a clear warning + skips spawning the
worker. The non-compute read routes (``/v1/variants``, ``/v1/findings``,
etc.) keep working so the agent's non-compute capability is unaffected.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, fields
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path


_SIDECAR_FILENAME = "prs_compute_config.json"


@dataclass(frozen=True)
class PrsComputeConfig:
    """Typed projection of the ``prs_compute_config.json`` sidecar.

    Per-deployment configuration: the worker reads this once at startup
    and threads the values into every :func:`compute_prs_with_coverage_fill`
    invocation. Paths are host-form (per from-scratch-setup-protections
    INV-D006 discipline) — pgsc_calc's DooD sibling containers resolve
    them against the host filesystem.
    """

    sample_id: str
    cram_path: Path
    reference_root: Path
    scorefile_root: Path
    work_dir_root: Path
    panel_version: str
    sites_tsv: Path
    alleles_tsv: Path
    fasta: Path


class PrsComputeConfigMissingError(FileNotFoundError):
    """The sidecar isn't at ``<run_dir>/prs_compute_config.json``."""


class PrsComputeConfigMalformedError(ValueError):
    """The sidecar exists but is invalid JSON or missing a required field."""


def load_prs_compute_config(run_dir: Path) -> PrsComputeConfig:
    """Read + validate the sidecar; return a typed :class:`PrsComputeConfig`.

    Raises:
        PrsComputeConfigMissingError: when the sidecar doesn't exist; the
            message names the expected path so the operator can fix it
            without spelunking the source.
        PrsComputeConfigMalformedError: when the JSON is invalid OR when
            a required field is missing.
    """
    sidecar_path = run_dir / _SIDECAR_FILENAME
    if not sidecar_path.exists():
        raise PrsComputeConfigMissingError(
            f"{_SIDECAR_FILENAME} not found at {sidecar_path}; "
            "stage it before starting the host service."
        )
    try:
        raw = json.loads(sidecar_path.read_text())
    except json.JSONDecodeError as exc:
        raise PrsComputeConfigMalformedError(
            f"{_SIDECAR_FILENAME} at {sidecar_path} is not valid JSON: {exc}"
        ) from exc

    expected_fields = {f.name for f in fields(PrsComputeConfig)}
    missing = expected_fields - set(raw)
    if missing:
        raise PrsComputeConfigMalformedError(
            f"{_SIDECAR_FILENAME} at {sidecar_path} is missing required "
            f"field(s): {sorted(missing)!r}"
        )

    path_fields = {
        "cram_path",
        "reference_root",
        "scorefile_root",
        "work_dir_root",
        "sites_tsv",
        "alleles_tsv",
        "fasta",
    }
    # Late import — Path is in stdlib but TYPE_CHECKING gated above.
    from pathlib import Path as _Path

    typed: dict[str, object] = {}
    for name in expected_fields:
        value = raw[name]
        typed[name] = _Path(value) if name in path_fields else value
    return PrsComputeConfig(**typed)  # type: ignore[arg-type]


def derive_prs_compute_config_from_manifest(
    manifest: dict[object, object],
    *,
    reference_root: "Path",
    scratch_root: "Path",
    panel_version: str = "v1",
) -> dict[str, str]:
    """Derive a ``prs_compute_config.json``-compatible dict from a run manifest.

    Pure function: no I/O, no side-effects. The caller is responsible for
    writing the result to ``<run_dir>/prs_compute_config.json``.

    Paths are host-form (INV-D006): they must be visible to sibling pgsc_calc
    containers, not container-local.  The derivation uses well-known
    subdirectory conventions that the GenomeClaw reference layout defines:

    - ``<reference_root>/prs_pca_sites/<panel_version>/pca_sites.tsv``
    - ``<reference_root>/prs_pca_sites/<panel_version>/pca_alleles.tsv``
    - ``<reference_root>/pgs_scorefile/``
    - The FASTA is read directly from ``manifest["input"]["reference_path"]``,
      which ``ingest`` records as the host-form path to the reference FASTA
      used during the run.

    Args:
        manifest: parsed ``manifest.json`` dict from the run dir.
        reference_root: host-form path to the ``reference/`` directory (e.g.
            ``/Volumes/Genome_Work/genomeclaw/reference``).
        scratch_root: host-form path to the scratch directory (e.g.
            ``/Volumes/Genome_Work/genomeclaw/_scratch``).
        panel_version: PCA ancestry panel version tag.  Defaults to ``"v1"``
            (the first shipped panel).

    Returns:
        A dict with every field required by :class:`PrsComputeConfig`,
        with all path values as strings (host-form).

    Raises:
        KeyError: when a required manifest field is absent (``sample_id``,
            ``input.bam_path``, ``input.reference_path``).
        ValueError: when the manifest's ``input.reference_path`` looks
            container-local (starts with ``/mnt/``).
    """
    # Late import — Path is in stdlib but gated by TYPE_CHECKING above.
    from pathlib import Path as _Path

    sample_id = str(manifest["sample_id"])

    input_block = manifest["input"]  # type: ignore[index]
    cram_path = str(input_block["bam_path"])  # type: ignore[index]
    reference_path = str(input_block["reference_path"])  # type: ignore[index]

    # Sanity-check: reference_path must be host-form (not container-local).
    if reference_path.startswith("/mnt/"):
        raise ValueError(
            f"manifest.input.reference_path looks container-local ({reference_path!r}); "
            "the manifest must record the host-form path (INV-D006). "
            "Re-ingest with a host-form --reference flag."
        )

    reference_root_str = str(reference_root)
    sites_tsv = str(_Path(reference_root_str) / "prs_pca_sites" / panel_version / "pca_sites.tsv")
    alleles_tsv = str(
        _Path(reference_root_str) / "prs_pca_sites" / panel_version / "pca_alleles.tsv"
    )
    scorefile_root = str(_Path(reference_root_str) / "pgs_scorefile")
    work_dir_root = str(_Path(str(scratch_root)) / "pgs-work")

    return {
        "sample_id": sample_id,
        "cram_path": cram_path,
        "reference_root": reference_root_str,
        "scorefile_root": scorefile_root,
        "work_dir_root": work_dir_root,
        "panel_version": panel_version,
        "sites_tsv": sites_tsv,
        "alleles_tsv": alleles_tsv,
        "fasta": reference_path,
    }


def write_prs_compute_config(
    run_dir: "Path",
    manifest: dict[object, object],
    *,
    reference_root: "Path",
    scratch_root: "Path",
    panel_version: str = "v1",
) -> "Path":
    """Derive + write ``prs_compute_config.json`` into ``run_dir``.

    Idempotent: overwrites any existing sidecar. Call this at the end of
    ``pipeline ingest`` (or ``pipeline materialize`` as a hook) so every
    fresh run-dir is complete without operator manual action.

    Returns the path of the written sidecar.

    Raises:
        Same as :func:`derive_prs_compute_config_from_manifest`.
    """
    import json as _json
    from pathlib import Path as _Path

    config_dict = derive_prs_compute_config_from_manifest(
        manifest,
        reference_root=reference_root,
        scratch_root=scratch_root,
        panel_version=panel_version,
    )
    sidecar_path = _Path(str(run_dir)) / _SIDECAR_FILENAME
    sidecar_path.write_text(_json.dumps(config_dict, indent=2, sort_keys=True) + "\n")
    return sidecar_path


__all__ = [
    "PrsComputeConfig",
    "PrsComputeConfigMalformedError",
    "PrsComputeConfigMissingError",
    "derive_prs_compute_config_from_manifest",
    "load_prs_compute_config",
    "write_prs_compute_config",
]
