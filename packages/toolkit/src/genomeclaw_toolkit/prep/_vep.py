"""``vep`` subprocess wrapper.

VEP (Ensembl Variant Effect Predictor) annotates the post-vcfanno VCF
with transcript-level consequence predictions, MANE Select canonical-
transcript HGVS strings, and plugin-derived columns:

- **LOFTEE** — high-confidence loss-of-function flag + filter reason.
- **AlphaMissense** — DeepMind's pathogenicity score + class for
  missense variants.
Phase 4D chains VEP after :mod:`annotate_vcfanno` in the parent
:mod:`annotate` orchestrator. VEP's plugin **code** lives in the
toolkit image at ``/opt/vep/.vep/Plugins/``; plugin **data** (the
AlphaMissense scores TSV, LOFTEE's ``human_ancestor.fa``) ships on
the bind-mounted ``reference/vep_cache/Plugins/`` volume.

The wrapper isolates three concerns:

1. **Flag construction** — :func:`build_vep_flags` produces the argv
   list from a :class:`VepConfig` dataclass. Pure Python — unit-
   testable without the bio image.
2. **Subprocess execution** — :func:`vep_run` shells out, streams
   stderr to the parent so the user sees VEP's progress markers in
   real time, raises :class:`VepError` on non-zero exit.
3. **Version capture** — :func:`vep_version` parses the ``ensembl-vep``
   line out of ``vep --help`` (VEP has no ``--version`` flag) for
   the manifest's ``tools`` block.

`INV-R001`: the version + the exact flag list emitted here are what
``annotate_vep.py`` records in ``provenance.json``'s ``vep`` step, so
a rerun against the same cache + plugin data + flag set reproduces
byte-equivalent annotation columns.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class VepPluginConfig:
    """One ``--plugin`` invocation.

    VEP's plugin flag is ``--plugin <name>[,<arg1>,<arg2>,...]`` where
    each plugin defines its own positional / key=value args. This
    dataclass renders both shapes via :meth:`to_flag` so the orchestrator
    doesn't have to special-case string interpolation per plugin.

    Examples:
        ``VepPluginConfig("LoF", ("loftee_path:/opt/vep/.vep/Plugins",
        "human_ancestor_fa:/ref/human_ancestor.fa.gz"))``

        ``VepPluginConfig("AlphaMissense", ("file=/ref/AlphaMissense.tsv.gz",))``
    """

    name: str
    args: tuple[str, ...] = ()

    def to_flag(self) -> str:
        """Render the comma-joined value passed to ``--plugin``."""
        if not self.args:
            return self.name
        return self.name + "," + ",".join(self.args)


@dataclass(frozen=True)
class VepConfig:
    """All inputs needed for one ``vep_run`` invocation.

    Attributes:
        input_vcf: bgzipped + tabix-indexed VCF (typically the
            ``vcfanno.vcf.gz`` output from the prior pipeline step).
        output_vcf: target bgzipped VCF path. Parent dir is created.
        cache_dir: VEP cache root — e.g.
            ``reference/vep_cache/ensembl-114/`` containing
            ``homo_sapiens/114_GRCh38/`` underneath.
        plugin_dir: directory containing the .pm files for every
            plugin in ``plugins``. The toolkit image's plugins live at
            ``/opt/vep/.vep/Plugins/``.
        assembly: ``GRCh38`` or ``GRCh37``. v0 ships GRCh38 only
            (Q5 of phase-4.md).
        plugins: ordered tuple of plugins to enable; each rendered as
            its own ``--plugin <flag>`` pair.
        fork: ``--fork N`` parallel workers. 0 = VEP default (1).
        extra_flags: trailing argv tokens, for one-off tuning during
            development (the orchestrator does not use this in
            production paths).
    """

    input_vcf: Path
    output_vcf: Path
    cache_dir: Path
    plugin_dir: Path
    assembly: str = "GRCh38"
    plugins: tuple[VepPluginConfig, ...] = ()
    fork: int = 0
    extra_flags: tuple[str, ...] = field(default_factory=tuple)


class VepError(RuntimeError):
    """A ``vep`` invocation exited non-zero. Stderr tail is captured in the message."""


# CLI flags always present in the production invocation. The orchestrator
# layers plugins + per-run flags on top via :class:`VepConfig`.
_STATIC_FLAGS: tuple[str, ...] = (
    "--cache",
    "--offline",
    "--mane_select",
    "--hgvs",
    "--symbol",
    "--canonical",
    "--vcf",
    "--compress_output",
    "bgzip",
    # ``--no_stats`` skips the auxiliary HTML/text stats report VEP
    # emits next to the output VCF. Phase 4D ships the VCF only;
    # downstream tooling reads it via tabix, not via the report.
    "--no_stats",
)


def build_vep_flags(config: VepConfig) -> list[str]:
    """Render the full ``vep <flags>`` argv for ``config``.

    Pure function: takes no I/O. The orchestrator wraps this in
    :func:`vep_run` to actually execute, but tests assert flag shape
    directly against this output without needing the VEP binary.
    """
    args: list[str] = [
        "vep",
        "--dir_cache",
        str(config.cache_dir),
        "--dir_plugins",
        str(config.plugin_dir),
        "--assembly",
        config.assembly,
    ]
    args.extend(_STATIC_FLAGS)
    if config.fork > 0:
        args.extend(["--fork", str(config.fork)])
    for plugin in config.plugins:
        args.extend(["--plugin", plugin.to_flag()])
    args.extend(config.extra_flags)
    args.extend(["-i", str(config.input_vcf), "-o", str(config.output_vcf)])
    return args


def vep_run(config: VepConfig) -> None:
    """Run ``vep`` with ``config``; stream stderr; raise :class:`VepError` on failure.

    Stderr is captured incrementally + forwarded to the parent process's
    own stderr so the user sees VEP's "processed N variants" progress
    lines in real time on long runs. A bounded tail of recent stderr is
    preserved for the :class:`VepError` message if the subprocess
    exits non-zero.
    """
    config.output_vcf.parent.mkdir(parents=True, exist_ok=True)
    flags = build_vep_flags(config)

    stderr_tail: deque[str] = deque(maxlen=200)
    proc = subprocess.Popen(flags, stderr=subprocess.PIPE)
    assert proc.stderr is not None
    for raw_line in iter(proc.stderr.readline, b""):
        decoded = raw_line.decode("utf-8", errors="replace").rstrip()
        if not decoded:
            continue
        stderr_tail.append(decoded)
        sys.stderr.write(decoded + "\n")
        sys.stderr.flush()
    proc.wait()
    if proc.returncode != 0:
        tail = "\n".join(stderr_tail)
        raise VepError(f"vep failed (rc={proc.returncode}):\n{tail}")


# VEP's ``--help`` output (versions block) looks like:
#
#   Versions:
#     ensembl              : 114.1117691
#     ensembl-compara      : 114.0efa758
#     ensembl-funcgen      : 114.dc9dfbc
#     ensembl-io           : 114.ec3b610
#     ensembl-variation    : 114.ca00935
#     ensembl-vep          : 114.1
#
# ``ensembl-vep`` is the line we want — it identifies the VEP release
# branch the rest of the Ensembl stack was compiled against.
_VERSION_RE = re.compile(r"^\s*ensembl-vep\s*:\s*(\S+)\s*$", re.MULTILINE)


def vep_version() -> str:
    """Return the ``ensembl-vep`` version string parsed from ``vep --help``.

    VEP has no ``--version`` flag — the version lives in the help
    banner. We invoke ``vep --help``, scan stdout for the
    ``ensembl-vep`` line, and return its value (e.g. ``"114.1"``).
    Falls back to ``"unknown"`` if parsing fails (e.g. VEP not on PATH;
    surfaced as a manifest-time signal that the install is broken
    rather than crashing the orchestrator).
    """
    try:
        proc = subprocess.run(["vep", "--help"], capture_output=True, check=False)
    except (FileNotFoundError, OSError):
        return "unknown"
    combined = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode(
        "utf-8", errors="replace"
    )
    match = _VERSION_RE.search(combined)
    return match.group(1) if match else "unknown"


__all__: Sequence[str] = (
    "VepConfig",
    "VepError",
    "VepPluginConfig",
    "build_vep_flags",
    "vep_run",
    "vep_version",
)
