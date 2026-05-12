"""CLI coverage for the curated multi-source fetch path.

Three surfaces:

- ``genomeclaw refs fetch --all`` — iterate the release set and call the
  underlying ``fetch`` impl once per source. Mocks the impl directly so
  these tests never touch the network (the real download path is
  covered by ``test_fetch_*`` against a pytest-httpserver).
- ``genomeclaw refs fetch --list-release-sets`` — print the bundled
  sets + their pins; exit 0.
- ``genomeclaw host setup --fetch-all`` — after a NO_OP smart-setup
  resolves, exec the shim to fetch the default release set.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _stub_fetch_returns_path(monkeypatch: pytest.MonkeyPatch, calls: list[dict]) -> None:
    """Replace ``refs.fetch_impl`` with a recorder that returns a fake path."""
    import genomeclaw_toolkit._cli.commands.refs as refs_cmd

    def fake_fetch(**kwargs):
        calls.append(kwargs)
        return Path(f"/fake/{kwargs['source']}/{kwargs['release']}")

    monkeypatch.setattr(refs_cmd, "fetch_impl", fake_fetch)


def test_fetch_all_iterates_default_release_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``refs fetch --all`` calls the fetch impl once per source in 'default'."""
    calls: list[dict] = []
    _stub_fetch_returns_path(monkeypatch, calls)

    result = invoke_cli(["refs", "fetch", "--all", "--reference-root", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    # Default set ships four sources; the call sequence must be the same
    # order the TOML lays out (grch38 first because normalize depends on
    # its index).
    sources_called = [c["source"] for c in calls]
    assert sources_called == ["grch38", "clinvar", "dbsnp", "gnomad-exomes"]
    # gnomAD must propagate its chroms tuple from the manifest; the others
    # must not (single-file sources reject ``chroms``).
    by_source = {c["source"]: c for c in calls}
    assert by_source["clinvar"]["chroms"] is None
    assert by_source["dbsnp"]["chroms"] is None
    assert by_source["grch38"]["chroms"] is None
    assert by_source["gnomad-exomes"]["chroms"] is not None
    assert "1" in by_source["gnomad-exomes"]["chroms"]
    assert "fetching release set 'default'" in result.stderr


def test_fetch_all_rejects_mixed_with_source(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """``--all`` + ``--source`` should fail loudly, not silently dispatch one or the other."""
    calls: list[dict] = []
    _stub_fetch_returns_path(monkeypatch, calls)

    result = invoke_cli(
        [
            "refs",
            "fetch",
            "--all",
            "--source",
            "clinvar",
            "--release",
            "2026-04",
            "--reference-root",
            str(tmp_path),
        ]
    )

    assert result.exit_code == 2  # usage error
    assert calls == []
    assert "mutually exclusive" in result.stderr


def test_fetch_all_skips_already_present_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, invoke_cli
) -> None:
    """A ``VersionAlreadyExists`` from one source must not abort the rest of the set.

    Single-source mode keeps the loud refusal (a typo shouldn't no-op),
    but in --all mode we treat already-present as a resume-friendly skip.
    """
    import genomeclaw_toolkit._cli.commands.refs as refs_cmd
    from genomeclaw_toolkit.prep.fetch import VersionAlreadyExists

    calls: list[str] = []

    def fake_fetch(**kwargs):
        calls.append(kwargs["source"])
        if kwargs["source"] == "clinvar":
            raise VersionAlreadyExists("clinvar already on disk")
        return Path(f"/fake/{kwargs['source']}/{kwargs['release']}")

    monkeypatch.setattr(refs_cmd, "fetch_impl", fake_fetch)

    result = invoke_cli(["refs", "fetch", "--all", "--reference-root", str(tmp_path)])

    assert result.exit_code == 0, result.stderr
    assert calls == ["grch38", "clinvar", "dbsnp", "gnomad-exomes"]
    assert "[skip]" in result.stderr and "clinvar" in result.stderr


def test_fetch_list_release_sets_prints_default(invoke_cli) -> None:
    """``--list-release-sets`` enumerates bundled set names."""
    result = invoke_cli(["refs", "fetch", "--list-release-sets"])

    assert result.exit_code == 0, result.stderr
    combined = result.stdout + result.stderr
    assert "default" in combined
    assert "grch38" in combined
    assert "clinvar" in combined
    assert "gnomad-exomes" in combined


def test_fetch_without_source_or_all_errors(invoke_cli) -> None:
    """The single-source surface requires --source + --release (or --all)."""
    result = invoke_cli(["refs", "fetch"])

    assert result.exit_code == 2  # usage error
    assert "--source" in result.stderr and "--release" in result.stderr


def test_fetch_unknown_release_set_errors(tmp_path: Path, invoke_cli) -> None:
    """An unknown ``--release-set`` is a usage error."""
    result = invoke_cli(
        [
            "refs",
            "fetch",
            "--all",
            "--release-set",
            "no-such-set",
            "--reference-root",
            str(tmp_path),
        ]
    )

    assert result.exit_code == 2
    assert "no-such-set" in result.stderr
