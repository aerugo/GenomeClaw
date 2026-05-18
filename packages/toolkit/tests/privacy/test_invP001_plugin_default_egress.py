"""`INV-P001` — the plugin reaches nothing but the configured host service by default.

Per [INVARIANTS.md § INV-P001](../../../../docs/reference/INVARIANTS.md), the
default operating mode constrains outbound destinations to:

- The user-configured NemoClaw agent provider (managed by OpenShell —
  not by this plugin).
- The host-side `genomeclaw-service` (single endpoint, single port).

Phase 5 Slice E adds defense-in-depth at the manifest + source-code
layers: a regression that introduces a second `fetch` call site, or
that ships a default `baseUrl` pointing at anything other than
`host.openshell.internal:8643`, surfaces here in milliseconds.

The runtime sandbox-level enforcement of the same rule lives at the
[OpenShell policy preset](../../../../nemoclaw-plugin/policy-preset.yaml)
+ INV-P002's test under [test_invP002_policy_preset_shape.py](
../invariants/test_invP002_policy_preset_shape.py).
"""

from __future__ import annotations

import json
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PLUGIN_DIR = _REPO_ROOT / "packages" / "nemoclaw-plugin"
_MANIFEST_PATH = _PLUGIN_DIR / "openclaw.plugin.json"
_PLUGIN_SOURCE_PATH = _PLUGIN_DIR / "src" / "index.ts"

# The documented default destination. Anything else as the manifest's
# default is a regression that ships a publicly-installable plugin
# pre-pointed at a destination other than the user's host service.
_EXPECTED_DEFAULT_BASE_URL = "http://host.openshell.internal:8643"

# URLs allowed to appear in source comments / docstrings. These are
# documentation pointers — never fetched at runtime, never embedded in
# code paths that reach the network. A reviewer adding a new URL here
# must record the rationale.
_DOCUMENTATION_URL_ALLOWLIST: frozenset[str] = frozenset(
    {
        # Rationale: 2026-05-15 live sweep — surfaced the deprecation of
        # the `openclaw/plugin-sdk` compat layer; this URL points at the
        # SDK-migration guide referenced in the import comment.
        "https://docs.openclaw.ai/plugins/sdk-migration",
        "https://docs.openclaw.ai/plugins/sdk-migration.",  # trailing period swallowed by the regex
    }
)


def _load_manifest() -> dict[str, object]:
    return json.loads(_MANIFEST_PATH.read_text())


def test_invP001_manifest_default_base_url_is_host_openshell_internal() -> None:
    """The manifest's `configSchema.properties.hostService.baseUrl.default` is the documented value.

    A user installing the plugin without overriding config gets this
    URL — it must be the one OpenShell's policy preset allows, and
    nothing else.
    """
    manifest = _load_manifest()
    config_schema = manifest["configSchema"]
    assert isinstance(config_schema, dict)
    properties = config_schema["properties"]
    assert isinstance(properties, dict)
    host_service = properties["hostService"]
    assert isinstance(host_service, dict)
    base_url = host_service["properties"]["baseUrl"]
    assert isinstance(base_url, dict)
    assert base_url["default"] == _EXPECTED_DEFAULT_BASE_URL, (
        f"INV-P001: manifest defaults hostService.baseUrl to "
        f"{base_url['default']!r}; expected {_EXPECTED_DEFAULT_BASE_URL!r}"
    )


def test_invP001_plugin_source_has_no_hardcoded_remote_destinations() -> None:
    """The plugin source contains no hardcoded http(s) URLs other than the documented default.

    Defense-in-depth: the runtime config can override the host service
    URL, but the SOURCE-LEVEL default + any literal URL constant must
    only ever name `host.openshell.internal`. A reviewer who scans the
    file shouldn't find a literal pointing at telemetry / npm /
    error-reporting / anything else.

    The check is intentionally simple: ripgrep for `http://` or
    `https://` literals + filter to the documented default. Any other
    literal fails the test with a pointer at the offending line.
    """
    source = _PLUGIN_SOURCE_PATH.read_text()
    url_literal = re.compile(r"https?://[a-zA-Z0-9._:/\-]+")
    matches = url_literal.findall(source)
    # All matches must be either the documented runtime default or a
    # documentation URL in the allowlist (with rationale). Anything else
    # is a regression. Markdown comments + JSDoc are part of the source so
    # documentation URLs surface here too — by design.
    allowlist = {_EXPECTED_DEFAULT_BASE_URL} | _DOCUMENTATION_URL_ALLOWLIST
    unexpected = [m for m in matches if m not in allowlist]
    assert not unexpected, (
        f"INV-P001: plugin source contains URL literals other than the documented default "
        f"or allowlisted documentation URLs: {unexpected}. Either remove them or extend "
        "_DOCUMENTATION_URL_ALLOWLIST in this test with the rationale."
    )


def test_invP001_plugin_source_uses_single_http_client_function() -> None:
    """All HTTP calls in the plugin source route through one `callHostService` function.

    Defense-in-depth: a regression that adds a second `fetch(...)` call
    site bypasses the centralised URL construction + timeout +
    auth-style discipline. The rule is: exactly one `fetch(...)` call
    site in the source, inside `callHostService`.

    A future refactor may rename `callHostService`; the test extracts
    the function containing the lone `fetch(` and asserts only one
    such call site exists.
    """
    source = _PLUGIN_SOURCE_PATH.read_text()
    # Strip docstring / comment occurrences of `fetch(`. The matcher
    # was a tightened up after the v1.6 plugin doctring introduced
    # the phrase `one `fetch(...)` call site` in a JSDoc block. The
    # rule remains: exactly one actual fetch invocation in the source.
    fetch_call_sites = [
        i
        for i, line in enumerate(source.splitlines(), start=1)
        if "fetch(" in line and not line.lstrip().startswith(("*", "//"))
    ]
    assert len(fetch_call_sites) == 1, (
        f"INV-P001: plugin source contains {len(fetch_call_sites)} `fetch(` call sites "
        f"on lines {fetch_call_sites}; expected exactly one (inside `callHostService`)."
    )


def test_invP001_manifest_output_class_defaults_to_summary() -> None:
    """The manifest's `outputClass` default is `summary` (INV-P002 alignment).

    `INV-P002` requires every plugin tool to declare `output_class:
    summary` unless explicitly opted into `bulk`. The manifest carries
    this default at the package level too so a user installing the
    plugin can never accidentally start in `bulk` mode by omitting
    config — they have to explicitly set `outputClass: bulk` AND have
    a separate policy preset to authorise it (no such preset exists
    in v0).
    """
    manifest = _load_manifest()
    output_class = manifest["configSchema"]["properties"]["outputClass"]
    assert isinstance(output_class, dict)
    assert output_class["default"] == "summary"
    # Enum must include the two documented values + nothing else.
    assert set(output_class["enum"]) == {"summary", "bulk"}, (
        f"INV-P001/P002: outputClass enum {output_class['enum']} drifted from "
        "the documented {summary, bulk} set"
    )
