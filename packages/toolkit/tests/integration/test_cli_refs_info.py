"""Phase 2 — ``refs info <source>`` command tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER
from genomeclaw_toolkit.prep.release_sets import ReleaseSet, ReleaseSetEntry


@pytest.fixture
def synthetic_release_set(monkeypatch: pytest.MonkeyPatch) -> ReleaseSet:
    """Tiny release set with one source for info-mode tests."""
    rs = ReleaseSet(
        name="test-set",
        description="Synthetic.",
        sources=(ReleaseSetEntry(source="clinvar", release="2026-01", chroms=None),),
    )

    def fake_load(name: str = "default") -> ReleaseSet:
        return rs

    monkeypatch.setattr(
        "genomeclaw_toolkit.prep.release_sets.load_release_set",
        fake_load,
    )
    return rs


def test_refs_info_emits_per_file_detail(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """`refs info` populates payload.detail with per-file presence + bgzip status."""
    ref = tmp_path / "reference"
    release_dir = ref / "clinvar" / "2026-01"
    release_dir.mkdir(parents=True)
    # Stage all 3 expected clinvar artifacts so status == "OK".
    (release_dir / "clinvar.vcf.gz").write_bytes(BGZF_EOF_MARKER + BGZF_EOF_MARKER)
    (release_dir / "clinvar.vcf.gz.md5").write_bytes(b"")
    (release_dir / "clinvar.vcf.gz.tbi").write_bytes(b"")

    result = invoke_cli(["--json", "refs", "info", "clinvar", "--reference-root", str(ref)])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "refs.info"
    detail = payload["payload"]["detail"]
    assert detail["source"] == "clinvar"
    assert detail["expected_release"] == "2026-01"
    assert detail["status"] == "OK"
    file_rows = {f["relpath"]: f for f in detail["files"]}
    assert "clinvar.vcf.gz" in file_rows
    assert file_rows["clinvar.vcf.gz"]["present"] is True
    assert file_rows["clinvar.vcf.gz"]["bgzip_ok"] is True
    assert file_rows["clinvar.vcf.gz"]["size_bytes"] > 0


def test_refs_info_marks_truncated_file_bgzip_false(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """A truncated bgzip surfaces as ``bgzip_ok: false`` in the detail rows."""
    ref = tmp_path / "reference"
    release_dir = ref / "clinvar" / "2026-01"
    release_dir.mkdir(parents=True)
    (release_dir / "clinvar.vcf.gz").write_bytes(BGZF_EOF_MARKER + b"truncated-tail")

    result = invoke_cli(["--json", "refs", "info", "clinvar", "--reference-root", str(ref)])
    assert result.exit_code == 0
    detail = json.loads(result.stdout)["payload"]["detail"]
    file_rows = {f["relpath"]: f for f in detail["files"]}
    assert file_rows["clinvar.vcf.gz"]["bgzip_ok"] is False


def test_refs_info_refuses_unknown_source_with_usage_error(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """Unknown source (not in the release set) → exit 2 (usage)."""
    ref = tmp_path / "reference"
    ref.mkdir()
    result = invoke_cli(["refs", "info", "no-such-source", "--reference-root", str(ref)])
    assert result.exit_code == 2
    assert "no-such-source" in result.stderr.lower() or "unknown source" in result.stderr.lower()


def test_refs_info_rich_renders_summary_panel(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """Rich mode produces summary panel + file table."""
    ref = tmp_path / "reference"
    release_dir = ref / "clinvar" / "2026-01"
    release_dir.mkdir(parents=True)
    (release_dir / "clinvar.vcf.gz").write_bytes(BGZF_EOF_MARKER + BGZF_EOF_MARKER)

    result = invoke_cli(["refs", "info", "clinvar", "--reference-root", str(ref)])
    assert result.exit_code == 0, result.stderr
    assert "clinvar" in result.stderr
    assert "2026-01" in result.stderr
