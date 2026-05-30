"""The plugin manifest must declare its tools as cold metadata.

Phase 3 of the nemoclaw-canonical-integration plan (Facet B). OpenClaw
2026.5.18 builds the gateway/agent tool catalog from COLD MANIFEST
METADATA — it reads ``openclaw.plugin.json`` -> ``contracts.tools``
WITHOUT importing the plugin runtime. A tool registered only at runtime
via ``api.registerTool(...)`` but absent from ``contracts.tools`` is
never surfaced to the agent (the gateway logs "0 plugins"; the agent
reports ``command not found``). See
docs/plans/active/nemoclaw-canonical-integration/initial_findings.md and
the OpenClaw docs: https://docs.openclaw.ai/plugins/building-plugins

This is the structural guard that keeps ``contracts.tools`` in sync with
the ``registerTool`` calls in ``src/index.ts`` so a newly-added tool
can't silently fail to surface. Per INV-V001 this is structural source
inspection (regex over TS source + JSON parse of the manifest), not a
gate over LLM output.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_DIR = REPO_ROOT / "packages" / "nemoclaw-plugin"
PLUGIN_SRC = PLUGIN_DIR / "src" / "index.ts"
PLUGIN_MANIFEST = PLUGIN_DIR / "openclaw.plugin.json"

# Test-only / env-gated tools that are NOT registered in the default
# runtime, and so are intentionally excluded from the baked cold-metadata
# contract. ``genomeclaw_ssrf_probe_batch`` is registered only when
# ``GENOMECLAW_SSRF_PROBE`` is set (see src/index.ts `if (ssrfProbeEnabled)`).
_ENV_GATED_TOOLS = frozenset({"genomeclaw_ssrf_probe_batch"})

# Matches `name: "genomeclaw_<...>"` — the `name` field of each
# `api.registerTool({ ... })` call.
_REGISTER_TOOL_NAME = re.compile(r'name:\s*"(genomeclaw_[a-z_]+)"')


def _registered_tool_names() -> set[str]:
    src = PLUGIN_SRC.read_text()
    return set(_REGISTER_TOOL_NAME.findall(src))


def _manifest() -> dict:
    return json.loads(PLUGIN_MANIFEST.read_text())


def test_manifest_declares_contracts_tools() -> None:
    """`openclaw.plugin.json` must carry a non-empty `contracts.tools` array."""
    manifest = _manifest()
    contracts = manifest.get("contracts")
    assert isinstance(contracts, dict), (
        "openclaw.plugin.json is missing the `contracts` block. OpenClaw "
        "2026.5.18 discovers tools from this cold metadata before importing "
        "the plugin runtime; without it the gateway surfaces 0 tools. See "
        "docs/plans/active/nemoclaw-canonical-integration/initial_findings.md."
    )
    tools = contracts.get("tools")
    assert isinstance(tools, list) and tools, (
        "`contracts.tools` must be a non-empty array of tool name strings."
    )


def test_manifest_activation_on_startup() -> None:
    """`activation.onStartup` must be true so the gateway loads the plugin."""
    manifest = _manifest()
    activation = manifest.get("activation", {})
    assert activation.get("onStartup") is True, (
        "openclaw.plugin.json must set `activation.onStartup: true` so the "
        "OpenClaw gateway loads the plugin at startup rather than lazily."
    )


def test_contracts_tools_covers_all_registered_tools() -> None:
    """Every non-gated `registerTool` name must appear in `contracts.tools`.

    Guards against the failure mode where a new tool is added in
    `src/index.ts` but the cold-metadata contract is not updated, so the
    tool registers at runtime yet never surfaces to the agent.
    """
    registered = _registered_tool_names()
    assert registered, (
        "no `registerTool` names found in src/index.ts — the regex or the "
        "source layout changed; update this test."
    )
    expected = registered - _ENV_GATED_TOOLS
    declared = set(_manifest().get("contracts", {}).get("tools", []))

    missing = expected - declared
    assert not missing, (
        f"`contracts.tools` is missing tools that src/index.ts registers: "
        f"{sorted(missing)}. Add them to openclaw.plugin.json `contracts.tools` "
        "(or run the OpenClaw manifest generator) so the gateway surfaces them."
    )

    # Anything declared must be a real, known tool name (no typos / stale entries).
    unknown = declared - registered
    assert not unknown, (
        f"`contracts.tools` declares tools not registered in src/index.ts: "
        f"{sorted(unknown)}. Remove stale entries or fix the name."
    )
