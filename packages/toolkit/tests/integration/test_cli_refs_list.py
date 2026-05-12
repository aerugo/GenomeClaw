"""Phase 2 — ``refs list`` command tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomeclaw_toolkit.prep.release_sets import ReleaseSet, ReleaseSetEntry


@pytest.fixture
def synthetic_release_set(monkeypatch: pytest.MonkeyPatch) -> ReleaseSet:
    """A tiny release set used only by the refs-list tests.

    Patching ``load_release_set`` keeps the test out of the
    toolkit's bundled TOML manifest (24 gnomAD chroms is too much
    surface for a unit-level test).
    """
    rs = ReleaseSet(
        name="test-set",
        description="Synthetic release set for tests.",
        sources=(
            ReleaseSetEntry(source="clinvar", release="2026-01", chroms=None),
            ReleaseSetEntry(source="dbsnp", release="b157", chroms=None),
        ),
    )

    def fake_load(name: str = "default") -> ReleaseSet:
        return rs

    monkeypatch.setattr(
        "genomeclaw_toolkit.prep.release_sets.load_release_set",
        fake_load,
    )
    return rs


def _stage_clean_source(reference_root: Path, source: str, release: str) -> None:
    """Stage all expected files for a single-file source.

    The fetcher's layouts:

    * ``clinvar``: ``.vcf.gz`` + ``.vcf.gz.md5`` + ``.vcf.gz.tbi``  (3 files)
    * ``dbsnp``: ``.vcf.gz`` + ``.vcf.gz.md5`` + ``.vcf.gz.tbi`` + ``.vcf.gz.tbi.md5``  (4 files)

    Both sets must be staged completely for the source to classify ``OK``.
    """
    release_dir = reference_root / source / release
    release_dir.mkdir(parents=True)
    (release_dir / f"{source}.vcf.gz").write_bytes(b"")
    (release_dir / f"{source}.vcf.gz.md5").write_bytes(b"")
    (release_dir / f"{source}.vcf.gz.tbi").write_bytes(b"")
    if source == "dbsnp":
        # dbSNP also publishes a sidecar for the tabix index.
        (release_dir / f"{source}.vcf.gz.tbi.md5").write_bytes(b"")


def test_refs_list_reports_all_sources_when_release_set_complete(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """`refs list` enumerates the release set and classifies every source."""
    ref = tmp_path / "reference"
    _stage_clean_source(ref, "clinvar", "2026-01")
    _stage_clean_source(ref, "dbsnp", "b157")

    result = invoke_cli(["--json", "refs", "list", "--reference-root", str(ref)])
    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload["command"] == "refs.list"
    sources = {s["source"]: s for s in payload["payload"]["sources"]}
    assert sources["clinvar"]["status"] == "OK"
    assert sources["dbsnp"]["status"] == "OK"


def test_refs_list_flags_missing_release_dir(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """A source whose release-dir doesn't exist is classified ``missing``."""
    ref = tmp_path / "reference"
    ref.mkdir()
    # Stage only clinvar; leave dbsnp untouched.
    _stage_clean_source(ref, "clinvar", "2026-01")

    result = invoke_cli(["--json", "refs", "list", "--reference-root", str(ref)])
    assert result.exit_code == 0
    sources = {s["source"]: s for s in json.loads(result.stdout)["payload"]["sources"]}
    assert sources["dbsnp"]["status"] == "missing"
    assert sources["clinvar"]["status"] == "OK"


def test_refs_list_rich_renders_status_table(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """Rich mode emits the table to stderr."""
    ref = tmp_path / "reference"
    ref.mkdir()

    result = invoke_cli(["refs", "list", "--reference-root", str(ref)])
    assert result.exit_code == 0, result.stderr
    assert "clinvar" in result.stderr
    assert "dbsnp" in result.stderr
    # Both should be classified missing — the table should show that.
    assert "missing" in result.stderr


def test_refs_list_schema_version_present(
    invoke_cli, tmp_path: Path, synthetic_release_set: ReleaseSet
) -> None:
    """`INV-C-cli-output-stability`: every JSON payload carries the schema version."""
    ref = tmp_path / "reference"
    ref.mkdir()
    result = invoke_cli(["--json", "refs", "list", "--reference-root", str(ref)])
    assert json.loads(result.stdout)["cli_output_schema_version"] == "1.0"
