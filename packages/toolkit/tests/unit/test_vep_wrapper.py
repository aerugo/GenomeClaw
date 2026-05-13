"""Unit tests for ``prep._vep`` flag construction + plugin config.

These tests don't invoke the ``vep`` binary — they exercise the pure-
Python flag-builder + dataclass shape. Real-binary integration tests
live in ``tests/integration/test_annotate_vep.py`` (Phase 4D needs_bio
suite, gated on the VEP cache + plugin-data fetches).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from genomeclaw_toolkit.prep._vep import (
    VepConfig,
    VepPluginConfig,
    build_vep_flags,
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
