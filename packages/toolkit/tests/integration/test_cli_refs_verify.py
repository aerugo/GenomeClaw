"""Phase 2 — ``refs verify`` command tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomeclaw_toolkit.prep._bgzip import BGZF_EOF_MARKER
from genomeclaw_toolkit.prep.release_sets import ReleaseSet, ReleaseSetEntry


@pytest.fixture
def synthetic_release_set(monkeypatch: pytest.MonkeyPatch) -> ReleaseSet:
    """A tiny release set with one bgzipped source for verify-mode tests."""
    rs = ReleaseSet(
        name="test-set",
        description="Synthetic release set for tests.",
        sources=(ReleaseSetEntry(source="clinvar", release="2026-01", chroms=None),),
    )

    def fake_load(name: str = "default") -> ReleaseSet:
        return rs

    monkeypatch.setattr(
        "genomeclaw_toolkit.prep.release_sets.load_release_set",
        fake_load,
    )
    return rs


def _stage_clean_bgzip(ref: Path, source: str, release: str) -> Path:
    """Stage a syntactically valid bgzipped file under the release dir."""
    release_dir = ref / source / release
    release_dir.mkdir(parents=True)
    target = release_dir / f"{source}.vcf.gz"
    target.write_bytes(BGZF_EOF_MARKER + BGZF_EOF_MARKER)
    return target


def _stage_truncated_bgzip(ref: Path, source: str, release: str) -> Path:
    """Stage a file with valid bgzip framing but a truncated tail."""
    release_dir = ref / source / release
    release_dir.mkdir(parents=True)
    target = release_dir / f"{source}.vcf.gz"
    target.write_bytes(BGZF_EOF_MARKER + b"junk-data-no-eof-marker-at-end")
    return target


def test_refs_verify_succeeds_on_clean_layout(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """All files intact → exit 0 + empty failure list."""
    ref = tmp_path / "reference"
    _stage_clean_bgzip(ref, "clinvar", "2026-01")

    result = invoke_cli(["--json", "refs", "verify", "--reference-root", str(ref)])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["payload"]["failures"] == []
    assert payload["payload"]["files_checked"] >= 1


def test_refs_verify_returns_exit_4_for_truncated_file(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """A truncated bgzip → exit 4 (DataIntegrityError) + failure row."""
    ref = tmp_path / "reference"
    _stage_truncated_bgzip(ref, "clinvar", "2026-01")

    result = invoke_cli(["refs", "verify", "--reference-root", str(ref)])
    assert result.exit_code == 4, result.stderr
    assert "truncated" in result.stderr or "integrity" in result.stderr.lower()


def test_refs_verify_marks_missing_files_explicitly(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """A missing file is reported as ``reason: missing`` (distinct from truncated)."""
    ref = tmp_path / "reference"
    # Create the release dir but NOT the canonical file.
    (ref / "clinvar" / "2026-01").mkdir(parents=True)

    result = invoke_cli(["refs", "verify", "--reference-root", str(ref)])
    assert result.exit_code == 4
    assert "missing" in result.stderr.lower()


def test_invD001_refs_verify_does_not_mutate_sources(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """`INV-D001`: the verifier reads reference files but never writes them."""
    ref = tmp_path / "reference"
    target = _stage_clean_bgzip(ref, "clinvar", "2026-01")
    before_bytes = target.read_bytes()
    before_mtime = target.stat().st_mtime

    result = invoke_cli(["refs", "verify", "--reference-root", str(ref)])
    assert result.exit_code == 0

    assert target.read_bytes() == before_bytes
    assert target.stat().st_mtime == before_mtime


def test_refs_verify_schema_version_present(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """`INV-C-cli-output-stability`: schema version stamped on the payload."""
    ref = tmp_path / "reference"
    _stage_clean_bgzip(ref, "clinvar", "2026-01")
    result = invoke_cli(["--json", "refs", "verify", "--reference-root", str(ref)])
    assert json.loads(result.stdout)["cli_output_schema_version"] == "1.0"
