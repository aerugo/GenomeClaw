"""`VepConventions` + AlphaMissense/VEP release alignment helper.

Per `bioreview-small-fixes` Fix 2:

1. `VepConventions` exists as a frozen dataclass with
   `verified_against_version` (matching `INV-T001` strict-tools test).
2. The `_discover_enabled_plugins` AlphaMissense entry includes
   `transcript_match=1` (so AM aligns scores to the user's transcript
   when MANE Select is active).
3. `check_alphamissense_vep_release_alignment` reads the AM header +
   VEP cache `info.txt`, emits a warning string list on mismatch,
   empty list on match or when either source is absent.
"""

from __future__ import annotations

import gzip
from pathlib import Path


def test_vep_conventions_dataclass_frozen() -> None:
    """`VepConventions` is a frozen dataclass with the documented version."""
    import dataclasses

    import pytest

    from genomeclaw_toolkit.prep._vep_conventions import VepConventions

    conv = VepConventions()
    assert conv.verified_against_version == "114.1"
    assert "transcript_match=1" in conv.alphamissense_plugin_args
    # Frozen → mutation raises.
    with pytest.raises(dataclasses.FrozenInstanceError):
        conv.verified_against_version = "x"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# vep-mane-plus-clinical Phase 1 extensions
# ---------------------------------------------------------------------------


def test_vep_conventions_mane_flag_is_mane_not_mane_select() -> None:
    """`mane_flag` pins `--mane` (NOT `--mane_select`).

    Per vep-mane-plus-clinical: `--mane` activates both MANE_SELECT AND
    MANE_PLUS_CLINICAL CSQ fields; `--mane_select` activates only the
    Select subset. The 73 MANE Plus Clinical genes (MANE v1.5) carry
    pathogenic variants in alternative transcripts that the Select-only
    flag silently drops from the canonical row.
    """
    from genomeclaw_toolkit.prep._vep_conventions import VepConventions

    assert VepConventions().mane_flag == "--mane"


def test_vep_conventions_pick_order_flag() -> None:
    """`pick_order_flag` is `--pick_order`."""
    from genomeclaw_toolkit.prep._vep_conventions import VepConventions

    assert VepConventions().pick_order_flag == "--pick_order"


def test_vep_conventions_pick_order_value_includes_mane_plus_clinical() -> None:
    """`pick_order_value` contains `mane_plus_clinical` in the rank list."""
    from genomeclaw_toolkit.prep._vep_conventions import VepConventions

    assert "mane_plus_clinical" in VepConventions().pick_order_value


def test_vep_conventions_pick_order_value_starts_with_rank() -> None:
    """The canonical pVACtools/GDC pick_order starts with `rank,`.

    Standard ordering: `rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length`.
    """
    from genomeclaw_toolkit.prep._vep_conventions import VepConventions

    assert VepConventions().pick_order_value.startswith("rank,")


def test_vep_conventions_mane_select_csq_field() -> None:
    """CSQ-field name for MANE Select is the upstream-pinned `MANE_SELECT`."""
    from genomeclaw_toolkit.prep._vep_conventions import VepConventions

    assert VepConventions().mane_select_csq_field == "MANE_SELECT"


def test_vep_conventions_mane_plus_clinical_csq_field() -> None:
    """CSQ-field name for MANE Plus Clinical is the upstream `MANE_PLUS_CLINICAL`."""
    from genomeclaw_toolkit.prep._vep_conventions import VepConventions

    assert VepConventions().mane_plus_clinical_csq_field == "MANE_PLUS_CLINICAL"


def test_alphamissense_plugin_args_include_transcript_match(tmp_path: Path) -> None:
    """`_discover_enabled_plugins` propagates `transcript_match=1` to the AM entry.

    Without `transcript_match=1`, AlphaMissense falls back to gene-level
    aggregation and silently emits one score per gene rather than per
    transcript. Per `bioreview-small-fixes` Fix 2 — the canonical AM arg
    tuple lives in `VepConventions.alphamissense_plugin_args`.
    """
    from genomeclaw_toolkit.prep.annotate_vep import _resolve_plugins as _discover_enabled_plugins

    # Materialise the minimum AM file layout
    # (`<reference_dir>/alphamissense/<release>/AlphaMissense/AlphaMissense_hg38.tsv.gz`).
    am_release_dir = tmp_path / "alphamissense" / "2024-10-01"
    am_subdir = am_release_dir / "AlphaMissense"
    am_subdir.mkdir(parents=True)
    am_file = am_subdir / "AlphaMissense_hg38.tsv.gz"
    am_file.write_bytes(b"fake-am-data")

    plugins = _discover_enabled_plugins(tmp_path)

    am_plugins = [p for p in plugins if p.name == "AlphaMissense"]
    assert len(am_plugins) == 1, f"expected one AlphaMissense plugin entry; got {am_plugins!r}"
    am_args = am_plugins[0].args
    assert any(arg.startswith("file=") for arg in am_args), f"missing file= arg: {am_args!r}"
    assert "transcript_match=1" in am_args, (
        f"AlphaMissense plugin args must include `transcript_match=1`; got {am_args!r}"
    )


def _write_am_with_release(am_dir: Path, release: str) -> Path:
    """Stage an AlphaMissense bundle that advertises the given Ensembl release."""
    am_subdir = am_dir / "AlphaMissense"
    am_subdir.mkdir(parents=True, exist_ok=True)
    am_file = am_subdir / "AlphaMissense_hg38.tsv.gz"
    with gzip.open(am_file, "wt") as fh:
        fh.write(
            f"#AlphaMissense_hg38 (synthetic test fixture)\n"
            f"#ensembl_release={release}\n"
            "#columns: CHROM POS REF ALT genome uniprot_id transcript_id\n"
        )
    return am_file


def _write_vep_cache_with_release(vep_cache_dir: Path, release: str) -> Path:
    """Stage a VEP cache layout that advertises the given Ensembl release."""
    species_dir = vep_cache_dir / "homo_sapiens" / f"{release}_GRCh38"
    species_dir.mkdir(parents=True)
    (species_dir / "info.txt").write_text(f"release\t{release}\nassembly\tGRCh38\n")
    return species_dir


def test_release_alignment_match_returns_empty(tmp_path: Path) -> None:
    """AM + VEP cache on the same release → no warnings."""
    from genomeclaw_toolkit.prep._vep_conventions import (
        check_alphamissense_vep_release_alignment,
    )

    reference_root = tmp_path / "reference"
    _write_am_with_release(reference_root / "alphamissense" / "2024-10-01", "111")
    _write_vep_cache_with_release(reference_root / "vep_cache" / "release-111", "111")

    warnings = check_alphamissense_vep_release_alignment(reference_root)
    assert warnings == []


def test_release_alignment_mismatch_emits_warning(tmp_path: Path) -> None:
    """AM + VEP cache on different releases → one warning naming both."""
    from genomeclaw_toolkit.prep._vep_conventions import (
        check_alphamissense_vep_release_alignment,
    )

    reference_root = tmp_path / "reference"
    _write_am_with_release(reference_root / "alphamissense" / "2024-10-01", "111")
    _write_vep_cache_with_release(reference_root / "vep_cache" / "release-114", "114")

    warnings = check_alphamissense_vep_release_alignment(reference_root)
    assert len(warnings) == 1
    msg = warnings[0]
    assert "AlphaMissense" in msg and "VEP cache" in msg
    assert "111" in msg and "114" in msg


def test_release_alignment_missing_am_returns_empty(tmp_path: Path) -> None:
    """No AM bundle staged → graceful skip; no warning."""
    from genomeclaw_toolkit.prep._vep_conventions import (
        check_alphamissense_vep_release_alignment,
    )

    reference_root = tmp_path / "reference"
    _write_vep_cache_with_release(reference_root / "vep_cache" / "release-111", "111")

    warnings = check_alphamissense_vep_release_alignment(reference_root)
    assert warnings == []


def test_release_alignment_missing_vep_cache_returns_empty(tmp_path: Path) -> None:
    """No VEP cache staged → graceful skip; no warning."""
    from genomeclaw_toolkit.prep._vep_conventions import (
        check_alphamissense_vep_release_alignment,
    )

    reference_root = tmp_path / "reference"
    _write_am_with_release(reference_root / "alphamissense" / "2024-10-01", "111")

    warnings = check_alphamissense_vep_release_alignment(reference_root)
    assert warnings == []
