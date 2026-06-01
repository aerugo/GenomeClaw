"""README accuracy gate — the canonical README must match the shipped surface.

`README.md` is the project's entry-point document; a contributor or agent
reads it to learn the CLI, the host service, and the agent tools. This gate
derives ground truth **from the code** (the Typer command tree, the plugin
manifest's tool list, the host-service routes) and asserts the README's
*enumerable* facts match — so the doc cannot silently drift again as the
toolkit evolves.

It pins enumerable facts (tool names, command names, port, endpoint paths,
the invariants link), NOT prose/wording — routine README copy edits must not
break it (see readme-accuracy-refresh plan, Q2: curated subset).

INV-V001: this is *structural inspection over a source document + code* (the
sanctioned alternative to phrase-enumeration over agent output). The handful
of retired-string-absence checks target the static README and are annotated
`# INV-V001-allow:` — the target is a doc the project controls, not LLM output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from genomeclaw_toolkit._cli import _registered_subcommand_names

_REPO_ROOT = Path(__file__).resolve().parents[4]
_README = _REPO_ROOT / "README.md"
_PLUGIN_MANIFEST = _REPO_ROOT / "packages" / "nemoclaw-plugin" / "openclaw.plugin.json"
_SERVICE_APP = (
    _REPO_ROOT / "packages" / "toolkit" / "src" / "genomeclaw_toolkit" / "service" / "app.py"
)


# --- ground-truth extractors (read from code, never hardcoded) -------------


def _readme() -> str:
    return _README.read_text()


def _manifest_tools() -> list[str]:
    """The agent-callable tool names from the plugin manifest's contract."""
    manifest = json.loads(_PLUGIN_MANIFEST.read_text())
    return list(manifest.get("contracts", {}).get("tools", []))


def _command_paths() -> list[str]:
    """Space-joined CLI command paths from the live Typer app (e.g. 'host profile init')."""
    return _registered_subcommand_names()


def _host_service_route_paths() -> set[str]:
    """The `/v1/...` route paths declared in service/app.py."""
    src = _SERVICE_APP.read_text()
    return set(re.findall(r'@app\.(?:get|post)\(\s*"([^"]+)"', src))


# --- gates ------------------------------------------------------------------


def test_readme_lists_every_plugin_tool() -> None:
    """Every agent tool in the plugin manifest is named in the README."""
    readme = _readme()
    missing = [t for t in _manifest_tools() if t not in readme]
    assert not missing, f"README omits agent tools that the plugin registers: {missing}"


def test_readme_does_not_undercount_tools() -> None:
    """The README must not carry the stale 'six ... tools' count (now ten)."""
    # INV-V001-allow: retired-string check over the static README (the project
    # controls this doc; target is not LLM output). Guards the specific stale
    # claim "six agent-callable tools" / "six ... tools".
    assert not re.search(r"\bsix\b[^.\n]{0,40}\btools\b", _readme(), re.IGNORECASE), (
        "README still claims 'six ... tools'; the plugin now registers "
        f"{len(_manifest_tools())} ({', '.join(_manifest_tools())})."
    )


def test_readme_host_service_port_is_8645() -> None:
    """The GenomeClaw host-service port is 8645; no GenomeClaw line says 8643."""
    readme = _readme()
    assert "8645" in readme, "README must document the host-service port 8645"
    # INV-V001-allow: retired-string check (static doc). An 8643 mention is fine
    # when it (a) names DevRelClaw (the coexistence section) or (b) sits beside
    # the correct 8645 on the same line (an explanatory "8645, not 8643" line).
    # Flag only a line that presents 8643 as THE GenomeClaw service port — i.e.
    # 8643 with neither DevRelClaw nor 8645 alongside.
    offenders = [
        ln
        for ln in readme.splitlines()
        if "8643" in ln and "devrelclaw" not in ln.lower() and "8645" not in ln
    ]
    assert not offenders, (
        "README has non-DevRelClaw line(s) referencing 8643 (GenomeClaw service "
        f"is 8645): {offenders}"
    )


def test_readme_documents_host_profile_endpoint_and_drops_retired_pgs_trait() -> None:
    """The README's endpoint surface includes /v1/host/profile and not the retired /v1/pgs/{trait}."""
    readme = _readme()
    assert "/v1/host/profile" in _host_service_route_paths(), (
        "precondition: /v1/host/profile must be a real host-service route"
    )
    assert "/v1/host/profile" in readme, (
        "README endpoint list must include /v1/host/profile"
    )
    # INV-V001-allow: retired-string check (static doc).
    assert "/v1/pgs/{trait}" not in readme, (
        "README still lists the retired /v1/pgs/{trait} endpoint; the agent-driven "
        "PRS layer uses /v1/pgs/computed, /v1/pgs/compute, etc."
    )


def test_readme_documents_cli_groups_and_host_profile_subcommands() -> None:
    """The README documents the CLI groups + every `host profile` subcommand."""
    readme = _readme()
    groups = sorted({p.split()[0] for p in _command_paths()} - {"completion"})
    missing_groups = [g for g in groups if g not in readme]
    assert not missing_groups, f"README omits CLI groups: {missing_groups}"

    assert "host profile" in readme, "README must document the `host profile` subgroup"
    # Each host-profile subcommand name must appear somewhere in the README.
    sub = [p.split()[2] for p in _command_paths() if p.startswith("host profile ")]
    missing_sub = [s for s in sub if s not in readme]
    assert not missing_sub, f"README omits `host profile` subcommands: {missing_sub}"


def test_readme_places_fetch_under_refs_and_documents_pipeline_core() -> None:
    """`fetch` is a `refs` command (not pipeline); core pipeline stages are documented."""
    readme = _readme()
    assert "refs fetch" in _command_paths(), "precondition: refs fetch exists"
    assert re.search(r"refs\s+fetch", readme) or "`refs`" in readme and "fetch" in readme, (
        "README must document `fetch` under the `refs` group"
    )
    # Core pipeline stages (curated subset — not every leaf, per plan Q2).
    for stage in ("ingest", "normalize", "annotate", "materialize"):
        assert stage in readme, f"README must document the pipeline `{stage}` stage"


def test_readme_links_invariants_doc() -> None:
    """The README links the canonical invariants doc (version-less per plan Q1)."""
    assert "docs/reference/INVARIANTS.md" in _readme(), (
        "README must link docs/reference/INVARIANTS.md"
    )


def test_readme_no_retired_curated_notes_calibration_citation() -> None:
    """The retired `INV-C001 v1.5` curated-notes calibration fossil must not return."""
    readme = _readme()
    # INV-V001-allow: retired-string checks over the static README. The
    # curated_notes lifestyle-calibration mechanism was retired in INV-C001 v1.6
    # (superseded by agent research-and-synthesis); `curated_notes` may still be
    # named in a *retired* context, but these specific stale claims must not.
    assert "curated-notes recognition" not in readme, (
        "README cites the retired 'curated-notes recognition' (INV-C001 v1.5)"
    )
    assert "v1.5 (with curated-notes" not in readme, (
        "README carries the stale INV-C001 v1.5 curated-notes citation"
    )
