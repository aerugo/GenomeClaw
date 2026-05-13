"""``annotate-vep`` orchestration (Phase 4D).

Runs VEP against the post-vcfanno VCF, layering transcript-level
consequence predictions + MANE Select HGVS strings + LOFTEE /
AlphaMissense plugin outputs onto every variant.

Operates on an existing ``derived/<run-id>/`` from a prior
``annotate_vcfanno`` step:

1. Resolves the VEP cache under ``<reference_dir>/vep_cache/<release>/``.
   When no cache is staged, emits a "skipping VEP" beat and **returns
   without running** — the parent ``annotate`` chain still produces a
   working ``annotated.vcf.gz`` (a copy of ``vcfanno.vcf.gz``) so the
   downstream ``materialize`` contract is preserved while Phase 4D is
   being rolled out incrementally.
2. Reads ``run_dir/vcfanno.vcf.gz`` as input.
3. Builds the VEP flag set (MANE Select + HGVS + canonical + symbol +
   plugins where the corresponding plugin-data files exist on disk).
4. Runs VEP via the wrapper in :mod:`prep._vep`.
5. ``atomic_promote``s ``vep.vcf.gz`` + ``.tbi`` into the run dir.
6. Updates ``manifest.outputs.vep_vcf`` + sha256.
7. Appends a ``vep`` step to ``provenance.json`` capturing the VEP
   version, plugin set, cache release, input + output sha256, and the
   exact flag list used.

`INV-D001`: the VEP cache + plugin data under ``reference/vep_cache/``
are read-only — VEP never writes back. `INV-D003`: VEP's intermediate
plain VCF lives under ``_scratch/annotate-vep-<run-id>/`` via
``shard_scratch``; the final ``vep.vcf.gz`` is the only artifact that
crosses into ``derived/``, via ``atomic_promote(...)``. `INV-R001`:
provenance step records the exact CLI flag list so a rerun against the
same cache + plugin data SHAs reproduces byte-equivalent annotation
columns.

The orchestrator is intentionally idempotent on the "no cache present"
path: it logs a beat, leaves ``vep.vcf.gz`` absent, and returns the
caller's ``vcfanno.vcf.gz`` path. The parent ``annotate`` orchestrator
treats that return value as "VEP skipped" and copies the vcfanno
output forward.
"""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from genomeclaw_toolkit.prep import preflight
from genomeclaw_toolkit.prep._bcftools import bcftools_index_tbi
from genomeclaw_toolkit.prep._events import emit_beat
from genomeclaw_toolkit.prep._vep import (
    VepConfig,
    VepPluginConfig,
    build_vep_flags,
    vep_run,
    vep_version,
)
from genomeclaw_toolkit.prep.scratch import atomic_promote, shard_scratch

if TYPE_CHECKING:
    from collections.abc import Callable

    from genomeclaw_toolkit.prep._events import _ProgressEvent

log = logging.getLogger(__name__)


# The toolkit image's VEP plugin code lives at this path (set in
# Dockerfile via ``COPY --from=vep-plugins``). The orchestrator passes
# this to ``vep --dir_plugins``. Plugin *data* (AlphaMissense scores,
# LOFTEE's human_ancestor.fa) lives under
# ``reference/vep_cache/Plugins/`` — fetched separately at fetch time.
_IMAGE_PLUGIN_DIR = Path("/opt/vep/.vep/Plugins")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _serialise_for_json(value: object) -> object:
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%dT%H:%M:%SZ")
    if isinstance(value, Path):
        return str(value)
    raise TypeError(f"unserialisable: {value!r}")


def _resolve_vep_cache_dir(reference_dir: Path, release: str | None) -> Path | None:
    """Pick the VEP cache dir under ``reference_dir/vep_cache/``.

    Returns the resolved release dir on success; returns ``None`` when
    no VEP cache is staged on disk yet. The orchestrator interprets
    ``None`` as "skip VEP" so the rest of the pipeline keeps working
    on installs that haven't fetched the ~75 GB VEP cache.

    Per Q5 of phase-4.md the cache release tag (e.g. ``"ensembl-114"``)
    is the directory name under ``reference/vep_cache/``. With no
    explicit release, picks the lexicographically-largest dir (works
    for ``ensembl-114`` < ``ensembl-115`` ordering; if a release
    naming scheme changes, the caller passes an explicit ``release``).
    """
    cache_root = reference_dir / "vep_cache"
    if not cache_root.exists():
        return None
    if release is not None:
        candidate = cache_root / release
        return candidate if candidate.exists() else None
    releases = sorted(p.name for p in cache_root.iterdir() if p.is_dir())
    # Filter the trailing "Plugins" sibling — that's plugin data, not
    # a release dir.
    releases = [r for r in releases if r != "Plugins"]
    if not releases:
        return None
    return cache_root / releases[-1]


def _latest_release_dir(source_root: Path) -> Path | None:
    """Pick the lexicographically-largest release dir under ``source_root``.

    Mirrors the ``_resolve_newest_release`` pattern in
    :mod:`annotate_vcfanno` so per-plugin data lookups follow the same
    "newest release wins" convention as the vcfanno overlay sources.
    Returns ``None`` when the source root doesn't exist or has no
    release subdirs.
    """
    if not source_root.exists():
        return None
    releases = sorted(p for p in source_root.iterdir() if p.is_dir())
    return releases[-1] if releases else None


def _resolve_plugins(reference_dir: Path) -> tuple[VepPluginConfig, ...]:
    """Probe per-source reference dirs for plugin-data files; enable each
    plugin whose data is on disk.

    Phase 4D enables two plugins when their data is present:

    - **LoF (LOFTEE)** — requires
      ``reference/loftee/<release>/human_ancestor.fa.gz``.
    - **AlphaMissense** — requires
      ``reference/alphamissense/<release>/AlphaMissense/AlphaMissense_hg38.tsv.gz``.

    Each plugin's data lives under its own ``<source>/<release>/``
    directory (matching the layout produced by ``genomeclaw refs
    fetch``), so no cross-source symlinks are needed: the orchestrator
    picks the newest release of each source, probes for the expected
    files, and enables the plugin when they're present. A plugin
    whose data is missing is silently dropped from the config so
    partial fetches still annotate everything they can.
    """
    enabled: list[VepPluginConfig] = []

    loftee_release = _latest_release_dir(reference_dir / "loftee")
    if loftee_release is not None:
        loftee_anc = loftee_release / "human_ancestor.fa.gz"
        if loftee_anc.exists():
            # Base args are always required: where the plugin code
            # lives + the ancestral-allele reference. Conservation +
            # GERP add finer-grained ``loftee_filter`` distinctions
            # when present (the LoF plugin no-ops on the missing-arg
            # path, so partial fetches still produce LoF flags — just
            # without the optional filtering metadata).
            args: list[str] = [
                f"loftee_path:{_IMAGE_PLUGIN_DIR}",
                f"human_ancestor_fa:{loftee_anc}",
            ]
            conservation = loftee_release / "loftee.sql"
            if conservation.exists():
                args.append(f"conservation_file:{conservation}")
            gerp = loftee_release / "gerp_conservation_scores.homo_sapiens.GRCh38.bw"
            if gerp.exists():
                args.append(f"gerp_bigwig:{gerp}")
            enabled.append(VepPluginConfig(name="LoF", args=tuple(args)))

    am_release = _latest_release_dir(reference_dir / "alphamissense")
    if am_release is not None:
        am_file = am_release / "AlphaMissense" / "AlphaMissense_hg38.tsv.gz"
        if am_file.exists():
            enabled.append(VepPluginConfig(name="AlphaMissense", args=(f"file={am_file}",)))

    return tuple(enabled)


def annotate_vep(
    *,
    run_dir: Path,
    reference_dir: Path,
    vep_cache_release: str | None = None,
    fork: int = 0,
    started_at: datetime | None = None,
    progress_callback: Callable[[_ProgressEvent], None] | None = None,
) -> Path | None:
    """Run VEP on ``run_dir/vcfanno.vcf.gz``; promote to ``run_dir/vep.vcf.gz``.

    Returns the promoted output path on success, or ``None`` when no
    VEP cache is staged on the host (Phase 4D rollout-in-progress
    signal — the parent ``annotate`` chain treats ``None`` as "VEP
    skipped" and uses ``vcfanno.vcf.gz`` as ``annotated.vcf.gz``).

    Args:
        run_dir: an existing ``derived/<run-id>/`` from a prior
            ``annotate_vcfanno`` step. Must contain ``vcfanno.vcf.gz``.
        reference_dir: the toolkit's reference root.
        vep_cache_release: optional cache release tag (e.g.
            ``"ensembl-114"``). When ``None``, picks the lex-largest
            directory under ``<ref>/vep_cache/``.
        fork: ``--fork N`` parallelism for VEP. 0 = VEP default (1).
            On consumer-SSD hardware fork 4-8 reliably halves wall
            time without busting the 32 GB RAM envelope.
        started_at: optional fixed UTC timestamp; defaults to
            ``datetime.now(tz=UTC)``.
        progress_callback: optional event consumer.
    """
    preflight.assert_raw_readonly()
    preflight.assert_reference_readonly()
    preflight.assert_derived_writable()
    preflight.assert_scratch_writable()

    if not run_dir.exists():
        raise FileNotFoundError(f"run dir not found: {run_dir}")
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(f"manifest.json not found in run dir: {run_dir}")

    vcfanno_vcf = run_dir / "vcfanno.vcf.gz"
    if not vcfanno_vcf.exists():
        raise FileNotFoundError(
            f"vcfanno.vcf.gz not found in {run_dir}; "
            "run `genomeclaw pipeline annotate` (which runs vcfanno) first"
        )

    cache_dir = _resolve_vep_cache_dir(reference_dir, vep_cache_release)
    if cache_dir is None:
        emit_beat(
            progress_callback,
            phase="annotate",
            message=(
                "skipping VEP (no cache under reference/vep_cache/ — "
                "run `genomeclaw refs fetch --source vep_cache` to enable)"
            ),
            logger=log,
        )
        return None

    if started_at is None:
        started_at = datetime.now(tz=UTC)

    plugins = _resolve_plugins(reference_dir)
    plugin_names = ",".join(p.name for p in plugins) if plugins else "none"
    emit_beat(
        progress_callback,
        phase="annotate",
        message=(
            f"running VEP against cache {cache_dir.name} "
            f"(plugins: {plugin_names}; ~minutes-to-hours on real data)"
        ),
        logger=log,
    )

    vcfanno_sha = _sha256_file(vcfanno_vcf)
    output_vcf = run_dir / "vep.vcf.gz"

    scratch_base = run_dir.parent.parent / "scratch"
    with shard_scratch(step="annotate-vep", run_id=run_dir.name, base=scratch_base) as scratch:
        work_output = scratch / "vep.vcf.gz"
        config = VepConfig(
            input_vcf=vcfanno_vcf,
            output_vcf=work_output,
            cache_dir=cache_dir,
            plugin_dir=_IMAGE_PLUGIN_DIR,
            plugins=plugins,
            fork=fork,
        )
        flags = build_vep_flags(config)
        vep_run(config)
        emit_beat(progress_callback, phase="annotate", message="vep complete; indexing output", logger=log)
        work_output_tbi = bcftools_index_tbi(vcf=work_output, derived_dir=scratch)

        atomic_promote(src=work_output, dst=output_vcf)
        atomic_promote(src=work_output_tbi, dst=run_dir / "vep.vcf.gz.tbi")

    output_sha = _sha256_file(output_vcf)
    completed_at = datetime.now(tz=UTC)

    provenance_path = run_dir / "provenance.json"
    provenance = json.loads(provenance_path.read_text())
    inputs: list[dict[str, Any]] = [{"path": str(vcfanno_vcf), "sha256": vcfanno_sha}]
    # The VEP cache + plugin-data files are also reference inputs;
    # provenance records the cache release name so a rerun against the
    # same release reproduces the same annotation columns. Hashing the
    # 75 GB cache + plugin data is impractical per-run; instead we pin
    # the release-string identity, which is stable per-release upstream.
    provenance["steps"].append(
        {
            "step": "vep",
            "tool": "vep",
            "tool_version": vep_version(),
            "started_at": started_at,
            "completed_at": completed_at,
            "inputs": inputs,
            "outputs": [{"path": "vep.vcf.gz", "sha256": output_sha}],
            "params": {
                "cache_release": cache_dir.name,
                "plugins": [p.to_flag() for p in plugins],
                "flags": flags,
                "fork": fork,
            },
        }
    )
    provenance_path.write_text(json.dumps(provenance, indent=2, default=_serialise_for_json) + "\n")

    manifest = json.loads(manifest_path.read_text())
    manifest["outputs"]["vep_vcf"] = "vep.vcf.gz"
    manifest["outputs"]["vep_vcf_sha256"] = output_sha
    manifest_path.write_text(json.dumps(manifest, indent=2, default=_serialise_for_json) + "\n")

    emit_beat(
        progress_callback,
        phase="annotate",
        message=f"vep output promoted: {output_vcf.name}",
        logger=log,
    )
    return output_vcf


__all__ = ["annotate_vep"]
