"""``vcfanno`` subprocess wrapper.

vcfanno is the tabix-indexed overlay annotator we use in Phase 4C to
join ClinVar / gnomAD-exomes / dbSNP INFO fields onto the user's
normalized VCF. It consumes a TOML config describing one ``[[annotation]]``
block per overlay source and writes the annotated VCF to stdout.

The wrapper isolates three concerns:

1. **TOML config rendering** — ``build_vcfanno_toml(configs)`` produces
   the inline TOML string vcfanno consumes. Pure-Python (no subprocess);
   exercised host-runnable.
2. **Subprocess execution** — ``run_vcfanno(input_vcf, config_toml, ...)``
   shells out, captures stderr, raises ``VcfannoError`` on non-zero exit.
3. **Version capture** — ``vcfanno_version()`` parses ``vcfanno`` stderr
   (the binary prints its banner on first invocation; the version is
   the only stable field we extract for the manifest).

`INV-R001`: the manifest's ``tools`` block records the version vcfanno
emits; the orchestrator's ``vcfanno`` provenance step captures the full
inline TOML config so a rerun against the same overlay-source SHAs
reproduces the same annotation columns.
"""

from __future__ import annotations

import re
import subprocess
import sys
from collections import deque
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class VcfannoConfig:
    """One vcfanno ``[[annotation]]`` block — one overlay source.

    Each block names: one tabix-indexed overlay file, the INFO fields
    to pull from it, the new column names (after renaming, since the
    canonical gnomAD field names like ``AF_grpmax_joint`` are renamed
    to project-canonical names like ``gnomad_af_popmax``), and the
    per-field operation (``self`` for direct copy; vcfanno also
    supports ``min``/``max``/``concat``/``first`` etc. — not used in v0).
    """

    file: Path
    fields: tuple[str, ...]
    names: tuple[str, ...]
    ops: tuple[str, ...]

    def __post_init__(self) -> None:
        if not (len(self.fields) == len(self.names) == len(self.ops)):
            raise ValueError(
                f"fields/names/ops must have the same length; "
                f"got {len(self.fields)} / {len(self.names)} / {len(self.ops)}"
            )


class VcfannoError(RuntimeError):
    """A ``vcfanno`` invocation exited non-zero. Stderr is captured."""


def _quote_toml_string(s: str) -> str:
    """Escape backslashes + double quotes; wrap in double quotes.

    Sufficient for paths + INFO field names (the values vcfanno actually
    consumes). Not a full TOML serialiser — vcfanno's config is
    structurally simple enough that we don't pull in a TOML library.
    """
    escaped = s.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


def _toml_string_array(items: tuple[str, ...]) -> str:
    return "[" + ", ".join(_quote_toml_string(x) for x in items) + "]"


def build_vcfanno_toml(configs: tuple[VcfannoConfig, ...]) -> str:
    """Render a vcfanno TOML config from a tuple of annotation blocks.

    The output is a single string with one ``[[annotation]]`` block per
    config, in the order given. vcfanno reads this directly via its
    ``-config`` arg.
    """
    blocks: list[str] = []
    for c in configs:
        blocks.append(
            "[[annotation]]\n"
            f"file = {_quote_toml_string(str(c.file))}\n"
            f"fields = {_toml_string_array(c.fields)}\n"
            f"names = {_toml_string_array(c.names)}\n"
            f"ops = {_toml_string_array(c.ops)}\n"
        )
    return "\n".join(blocks)


def run_vcfanno(
    *,
    input_vcf: Path,
    output_vcf: Path,
    config_toml: str,
    work_dir: Path,
) -> None:
    """Run ``vcfanno -p 1 <config> <input_vcf>`` and bgzip the result to ``output_vcf``.

    The config TOML is written to ``work_dir/vcfanno.conf`` (vcfanno
    reads from a file, not stdin). The annotated output is bgzipped
    + tabix-indexed by the caller; this wrapper writes plain VCF to
    stdout-via-pipe then bgzips it inside ``work_dir`` before the
    caller atomic-promotes it.

    Args:
        input_vcf: bgzipped + tabix-indexed input VCF.
        output_vcf: target bgzipped output VCF; parent dir created if missing.
        config_toml: TOML config string from ``build_vcfanno_toml(...)``.
        work_dir: scratch dir for the intermediate config + uncompressed VCF.

    Raises:
        VcfannoError: vcfanno exited non-zero. Stderr captured.
    """
    output_vcf.parent.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    config_path = work_dir / "vcfanno.conf"
    config_path.write_text(config_toml)

    # Run vcfanno, piping its plain-VCF stdout through bgzip into the
    # output path. Stderr is streamed line-by-line to ``sys.stderr`` so
    # the user sees vcfanno's own progress markers ("annotated N variants
    # in Ts (R/second)") in real time — without this, a multi-minute
    # vcfanno run against ~5M variants × N overlay sources looks like a
    # silent stall. We keep a bounded tail of recent stderr for the
    # error message on non-zero exit.
    plain_intermediate = work_dir / "annotated.vcf"
    stderr_tail: deque[str] = deque(maxlen=200)
    with plain_intermediate.open("wb") as out:
        proc = subprocess.Popen(
            ["vcfanno", "-p", "1", str(config_path), str(input_vcf)],
            stdout=out,
            stderr=subprocess.PIPE,
        )
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
        raise VcfannoError(f"vcfanno failed (rc={proc.returncode}):\n{tail}")

    # bgzip the plain VCF into the canonical output path.
    with output_vcf.open("wb") as out:
        subprocess.run(
            ["bgzip", "--stdout", str(plain_intermediate)],
            stdout=out,
            stderr=subprocess.PIPE,
            check=True,
        )


_VERSION_RE = re.compile(r"version\s+(\S+)", re.IGNORECASE)


def vcfanno_version() -> str:
    """Capture ``vcfanno``'s version. The binary has no ``--version`` flag;
    invoking with no args prints a banner to stderr that includes the
    version (e.g. ``vcfanno version 0.3.5``). We parse that.
    """
    proc = subprocess.run(["vcfanno"], capture_output=True, check=False)
    # vcfanno's banner is on stderr; some builds emit it on stdout.
    combined = proc.stdout.decode("utf-8", errors="replace") + proc.stderr.decode(
        "utf-8", errors="replace"
    )
    m = _VERSION_RE.search(combined)
    if m is None:
        return "unknown"
    return m.group(1)


__all__ = [
    "VcfannoConfig",
    "VcfannoError",
    "build_vcfanno_toml",
    "run_vcfanno",
    "vcfanno_version",
]
