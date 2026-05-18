"""Unit tests for ``prep._vep`` flag construction + plugin config.

These tests don't invoke the ``vep`` binary — they exercise the pure-
Python flag-builder + dataclass shape. Real-binary integration tests
live in ``tests/integration/test_annotate_vep.py`` (Phase 4D needs_bio
suite, gated on the VEP cache + plugin-data fetches).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genomeclaw_toolkit.prep import _vep as vep_module
from genomeclaw_toolkit.prep._vep import (
    _VEP_SKIPPED_VARIANT_RE,
    VepConfig,
    VepPluginConfig,
    VepRunStats,
    build_vep_flags,
    vep_run,
)


def _minimal_config(**overrides: object) -> VepConfig:
    defaults: dict[str, object] = {
        "input_vcf": Path("/fake/in.vcf.gz"),
        "output_vcf": Path("/fake/out.vcf.gz"),
        "cache_dir": Path("/fake/cache"),
        "plugin_dir": Path("/fake/plugins"),
    }
    defaults.update(overrides)
    return VepConfig(**defaults)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# VepPluginConfig.to_flag
# ---------------------------------------------------------------------------


def test_plugin_config_renders_bare_name_when_no_args() -> None:
    """Plugins without args render as just the plugin name."""
    p = VepPluginConfig(name="Conservation")
    assert p.to_flag() == "Conservation"


def test_plugin_config_renders_comma_joined_args() -> None:
    """Args are comma-joined after the name."""
    p = VepPluginConfig(
        name="LoF",
        args=(
            "loftee_path:/opt/vep/.vep/Plugins",
            "human_ancestor_fa:/ref/human_ancestor.fa.gz",
        ),
    )
    assert p.to_flag() == (
        "LoF,loftee_path:/opt/vep/.vep/Plugins,human_ancestor_fa:/ref/human_ancestor.fa.gz"
    )


def test_plugin_config_supports_key_equals_value_args() -> None:
    """AlphaMissense uses ``file=...`` key=value arg shape."""
    p = VepPluginConfig(name="AlphaMissense", args=("file=/ref/am.tsv.gz",))
    assert p.to_flag() == "AlphaMissense,file=/ref/am.tsv.gz"


# ---------------------------------------------------------------------------
# build_vep_flags — required flags + path threading
# ---------------------------------------------------------------------------


def test_build_vep_flags_emits_vep_binary_first() -> None:
    """argv[0] is always ``vep`` so subprocess can resolve the binary on PATH."""
    flags = build_vep_flags(_minimal_config())
    assert flags[0] == "vep"


def test_build_vep_flags_threads_cache_and_plugin_dirs() -> None:
    """``--dir_cache`` and ``--dir_plugins`` get the config paths verbatim."""
    flags = build_vep_flags(
        _minimal_config(
            cache_dir=Path("/ref/vep_cache/ensembl-114"),
            plugin_dir=Path("/opt/vep/.vep/Plugins"),
        )
    )
    assert "--dir_cache" in flags
    assert flags[flags.index("--dir_cache") + 1] == "/ref/vep_cache/ensembl-114"
    assert "--dir_plugins" in flags
    assert flags[flags.index("--dir_plugins") + 1] == "/opt/vep/.vep/Plugins"


def test_build_vep_flags_includes_phase_4d_required_flags() -> None:
    """Phase 4D pins MANE Select + HGVS + canonical + symbol + VCF output.

    These are the flags that drive the v0.2 schema columns: MANE Select
    transcript, HGVSc / HGVSp, consequence terms, gene symbol. Dropping
    any would silently break a downstream column — pin them.
    """
    flags = build_vep_flags(_minimal_config())
    for required in (
        "--cache",
        "--offline",
        "--mane_select",
        "--hgvs",
        "--symbol",
        "--canonical",
        "--vcf",
        "--no_stats",
    ):
        assert required in flags, f"missing required Phase 4D flag {required!r}"
    # Output is bgzip-compressed VCF; downstream concat / tabix expect this.
    assert flags[flags.index("--compress_output") + 1] == "bgzip"


def test_build_vep_flags_input_and_output_paths_threaded() -> None:
    """``-i`` and ``-o`` carry the config paths verbatim."""
    flags = build_vep_flags(
        _minimal_config(
            input_vcf=Path("/run/normalized.vcf.gz"),
            output_vcf=Path("/run/vep.vcf.gz"),
        )
    )
    assert flags[flags.index("-i") + 1] == "/run/normalized.vcf.gz"
    assert flags[flags.index("-o") + 1] == "/run/vep.vcf.gz"


def test_build_vep_flags_assembly_defaults_to_grch38() -> None:
    """v0 ships GRCh38 only — the default carries through to argv."""
    flags = build_vep_flags(_minimal_config())
    assert flags[flags.index("--assembly") + 1] == "GRCh38"


def test_build_vep_flags_emits_fasta_when_reference_fasta_set() -> None:
    """``--fasta <path>`` lands in argv when ``reference_fasta`` is set.

    VEP's ``--hgvs`` flag requires a reference FASTA in offline mode
    (``ERROR: Cannot generate HGVS coordinates (--hgvs and --hgvsg) in
    offline mode without a FASTA file``) — discovered the hard way during
    the 2026-05-14 real-data smoke. Phase 4D unconditionally passes
    ``--hgvs``, so the FASTA must always thread through.
    """
    flags = build_vep_flags(
        _minimal_config(reference_fasta=Path("/ref/grch38/ncbi-2014/grch38.fa.gz"))
    )
    assert "--fasta" in flags, f"--fasta missing from flags: {flags}"
    assert flags[flags.index("--fasta") + 1] == "/ref/grch38/ncbi-2014/grch38.fa.gz"


def test_build_vep_flags_omits_fasta_when_reference_fasta_none() -> None:
    """``--fasta`` is absent when no reference FASTA is configured.

    Defends the "partial reference layouts still annotate everything
    they can" contract: a user without a staged FASTA gets a flag set
    that's still well-formed (will fail at VEP-time on ``--hgvs`` —
    that's the upstream contract, not ours to mask).
    """
    flags = build_vep_flags(_minimal_config())
    assert "--fasta" not in flags


# ---------------------------------------------------------------------------
# build_vep_flags — plugin expansion
# ---------------------------------------------------------------------------


def test_build_vep_flags_emits_one_plugin_pair_per_plugin() -> None:
    """Each ``VepPluginConfig`` produces ``--plugin <to_flag()>`` in argv."""
    flags = build_vep_flags(
        _minimal_config(
            plugins=(
                VepPluginConfig("LoF", ("loftee_path:/p",)),
                VepPluginConfig("AlphaMissense", ("file=/ref/am.tsv.gz",)),
                VepPluginConfig("Downstream", ("length=200",)),
            )
        )
    )
    plugin_indices = [i for i, f in enumerate(flags) if f == "--plugin"]
    assert len(plugin_indices) == 3
    rendered = [flags[i + 1] for i in plugin_indices]
    assert rendered == [
        "LoF,loftee_path:/p",
        "AlphaMissense,file=/ref/am.tsv.gz",
        "Downstream,length=200",
    ]


def test_build_vep_flags_preserves_plugin_order() -> None:
    """LOFTEE typically runs first so AlphaMissense sees its
    consequence-filtered set. Plugin order in argv must match config
    order — VEP processes them sequentially.
    """
    flags = build_vep_flags(
        _minimal_config(
            plugins=(
                VepPluginConfig("LoF"),
                VepPluginConfig("AlphaMissense"),
                VepPluginConfig("Downstream"),
            )
        )
    )
    plugin_args = [flags[i + 1] for i, f in enumerate(flags) if f == "--plugin"]
    assert plugin_args == ["LoF", "AlphaMissense", "Downstream"]


# ---------------------------------------------------------------------------
# build_vep_flags — optional --fork
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fork", [0, 1, 4, 8])
def test_build_vep_flags_fork_zero_omits_fork_flag(fork: int) -> None:
    """``--fork`` is omitted when fork==0 (VEP defaults to 1 worker)."""
    flags = build_vep_flags(_minimal_config(fork=fork))
    if fork == 0:
        assert "--fork" not in flags
    else:
        assert flags[flags.index("--fork") + 1] == str(fork)


# ---------------------------------------------------------------------------
# build_vep_flags — extra_flags passthrough
# ---------------------------------------------------------------------------


def test_build_vep_flags_extra_flags_appended_before_io_pair() -> None:
    """``extra_flags`` lands after plugins, before ``-i``/``-o`` so dev tweaks
    don't accidentally override the input/output paths.
    """
    flags = build_vep_flags(_minimal_config(extra_flags=("--verbose", "--buffer_size", "1000")))
    verbose_idx = flags.index("--verbose")
    i_idx = flags.index("-i")
    assert verbose_idx < i_idx
    assert flags[flags.index("--buffer_size") + 1] == "1000"


# ---------------------------------------------------------------------------
# Skipped-variant accounting (decoy-variant-provenance plan)
# ---------------------------------------------------------------------------


def test_skipped_variant_regex_matches_canonical_vep_warning() -> None:
    """The regex captures the contig name from a real VEP skip warning.

    VEP emits one ``WARNING: line N skipped (<contig> <pos> ... )`` line per
    variant it can't annotate (chromosome absent from the cache — typical
    for GRCh38 decoy / random / alt contigs). Capturing the contig name
    powers the per-chrom skip breakdown that the orchestrator surfaces in
    provenance for an audit trail of dropped variants.
    """
    line = (
        "WARNING: line 12345 skipped (chrUn_JTFH01001998v1_decoy 1234 . A G): "
        "Chromosome chrUn_JTFH01001998v1_decoy not found in annotation sources or synonyms"
    )
    match = _VEP_SKIPPED_VARIANT_RE.match(line)
    assert match is not None
    assert match.group(1) == "chrUn_JTFH01001998v1_decoy"


def test_skipped_variant_regex_ignores_other_warnings() -> None:
    """Non-skip ``WARNING:`` lines must not match — defends against false
    positives that would inflate the recorded skip count.

    LOFTEE's compile-time warnings, VEP's plugin-loading warnings, and
    bgzip's stderr noise all start with ``WARNING:`` but aren't variant
    skips; only the ``line N skipped (...)`` shape counts.
    """
    non_skip_lines = [
        "WARNING: Plugin LoF compile failed",
        "WARNING: 2026-05-15 something happened",
        "INFO: line 1 skipped (foo bar)",  # different prefix
        "WARNING: line skipped (chr1 1)",  # missing line number
        "",
        "Some random log line",
    ]
    for line in non_skip_lines:
        assert _VEP_SKIPPED_VARIANT_RE.match(line) is None, (
            f"regex unexpectedly matched non-skip line: {line!r}"
        )


def test_vep_run_stats_counts_skipped_variants_from_stderr(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """``vep_run`` returns a :class:`VepRunStats` summing skips per chrom.

    Monkeypatches ``subprocess.Popen`` to a fake that yields a stream of
    canned stderr lines (mix of skips on three contigs + unrelated noise)
    and asserts the returned stats match the input counts. The regex is
    exercised end-to-end with the wrapper's parsing loop.
    """
    stderr_lines = [
        b"2026-05-15 12:00:00 - Read 100 variants from stdin\n",
        b"WARNING: line 1 skipped (chrUn_KI270742v1 1 . A T): not in cache\n",
        b"WARNING: line 2 skipped (chrUn_KI270742v1 2 . A T): not in cache\n",
        b"WARNING: line 3 skipped (chr1_KI270706v1_random 3 . C G): not in cache\n",
        b"WARNING: line 4 skipped (chrUn_JTFH01001998v1_decoy 4 . T A): not in cache\n",
        b"WARNING: line 5 skipped (chrUn_KI270742v1 5 . G A): not in cache\n",
        b"WARNING: Plugin LoF compile noise - should not count\n",
        b"2026-05-15 12:01:00 - Done\n",
    ]

    class _FakeProc:
        def __init__(self, lines: list[bytes]) -> None:
            self._lines = iter(lines)
            self.returncode: int | None = None
            self.stderr = self  # so proc.stderr.readline works

        def readline(self) -> bytes:
            return next(self._lines, b"")

        def wait(self) -> int:
            self.returncode = 0
            return 0

    def _fake_popen(*_args: object, **_kwargs: object) -> _FakeProc:
        return _FakeProc(stderr_lines)

    monkeypatch.setattr(vep_module.subprocess, "Popen", _fake_popen)

    config = VepConfig(
        input_vcf=tmp_path / "in.vcf.gz",
        output_vcf=tmp_path / "out.vcf.gz",
        cache_dir=tmp_path / "cache",
        plugin_dir=tmp_path / "plugins",
    )
    stats = vep_run(config)

    assert isinstance(stats, VepRunStats)
    assert stats.skipped_variants == 5
    assert stats.skipped_chroms == {
        "chrUn_KI270742v1": 3,
        "chr1_KI270706v1_random": 1,
        "chrUn_JTFH01001998v1_decoy": 1,
    }
