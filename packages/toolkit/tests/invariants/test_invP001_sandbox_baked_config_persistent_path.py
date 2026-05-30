"""`INV-P001` — persistent-path baked config in the sandbox image.

Companion to `test_invP001_sandbox_web_egress_contract.py` (same image,
different config keys). This module covers the bakes that make the
persistent `nemoclaw genomeclaw` sandbox come up usable on first run
without any post-install `openclaw config set` having to succeed —
which is load-bearing because `nemoclaw genomeclaw exec` runs every
command inside openshell's filesystem-restriction wrapper that EACCESes
on `/opt/genomeclaw`, so post-install config-set commands fail in
practice (see docs/reports/genomeclaw-demo-questions-2026-05-24.md).

The bakes asserted here:

- `gateway.mode = "local"` — without this, the gateway refuses to start
  with `Gateway start blocked: existing config is missing gateway.mode`.
- `"genomeclaw" in plugins.allow` — without this, the plugin is loaded
  but disabled, and the gateway reports `0 tools` from genomeclaw.
- `plugins.entries.genomeclaw.config.hostService.baseUrl` is the
  `host.openshell.internal:${GENOMECLAW_HOST_PORT}` URL the plugin
  uses to reach the host service.
- `plugins.entries.genomeclaw.config.hostService.timeoutMs == 30000`.
- `models.providers.openai.apiKey` is an env-ref to `OPENAI_API_KEY`,
  NOT a literal key value (a literal would leak into the image layer).
- `ENV HOME=/sandbox` is set in the image so `openclaw config` defaults
  to `/sandbox/.openclaw/` (the sandbox user's writeable home) rather
  than `/root/.openclaw` (which EACCESes for uid 998).

Historical note: prior to the nemoclaw-canonical-integration plan
(2026-05-29) the plugin lived at `/opt/genomeclaw/` — outside the
OpenShell Landlock RW baseline — so any post-install
`openclaw config set` issued via `nemoclaw genomeclaw exec` failed
with EACCES. The persistent-path bakes here were the primary mitigation.
The plugin now lives at `/sandbox/.openclaw/extensions/genomeclaw/`
(inside the Landlock baseline), so post-install `openclaw config set`
also works in principle — but the build-time bakes remain because the
first-run experience must not depend on the operator re-running
`openclaw config set`.

Gated on `GENOMECLAW_SANDBOX_IMAGE` per the rest of the sandbox-image
invariant suite — skips cleanly without a built image.

Tracks the onboard-persistent-agent-fix plan
(docs/plans/completed/onboard-persistent-agent-fix/) + the
nemoclaw-canonical-integration plan
(docs/plans/active/nemoclaw-canonical-integration/).
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess

import pytest

# Matches OpenAI API keys (the prefix family used by the platform: sk-proj-,
# sk-live-, sk-test-, sk-…). If any value matching this pattern shows up
# anywhere in the baked openclaw.json, the bake leaked a literal credential
# into the image — which is the failure mode this test catches.
_OPENAI_KEY_PATTERN = re.compile(r"sk-[a-z]+-[A-Za-z0-9_-]{20,}")


@pytest.fixture(scope="module")
def sandbox_image() -> str:
    """Resolve the sandbox image tag from env + verify it's locally available."""
    tag = os.environ.get("GENOMECLAW_SANDBOX_IMAGE")
    if not tag:
        pytest.skip(
            "GENOMECLAW_SANDBOX_IMAGE not set; "
            "build packages/nemoclaw-plugin/sandbox/Dockerfile and set the env var."
        )
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not on PATH.")
    proc = subprocess.run(
        ["docker", "image", "inspect", tag],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.skip(f"sandbox image {tag!r} not available locally.")
    return tag


@pytest.fixture(scope="module")
def baked_openclaw_json(sandbox_image: str) -> dict:
    """Read `/sandbox/.openclaw/openclaw.json` out of the built image."""
    proc = subprocess.run(
        [
            "docker", "run", "--rm",
            "--entrypoint", "cat",
            sandbox_image,
            "/sandbox/.openclaw/openclaw.json",
        ],
        capture_output=True, text=True, check=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"could not read /sandbox/.openclaw/openclaw.json from image {sandbox_image!r}: "
            f"rc={proc.returncode}; stderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def baked_image_env(sandbox_image: str) -> list[str]:
    """Read the image's `Config.Env` list via `docker inspect`."""
    proc = subprocess.run(
        ["docker", "inspect", "--format", "{{json .Config.Env}}", sandbox_image],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


@pytest.mark.needs_sandbox
def test_invP001_baked_gateway_mode_is_local(baked_openclaw_json: dict) -> None:
    """`gateway.mode == "local"` so the gateway starts cleanly on first run."""
    mode = baked_openclaw_json.get("gateway", {}).get("mode")
    assert mode == "local", (
        f"INV-P001: sandbox image's baked gateway.mode={mode!r}; expected 'local'. "
        "Without this, the gateway refuses to start with 'Gateway start blocked: "
        "existing config is missing gateway.mode' and the persistent agent path "
        "is dead in the water — see onboard-persistent-agent-fix plan."
    )


@pytest.mark.needs_sandbox
def test_invP001_baked_plugins_allow_contains_genomeclaw(baked_openclaw_json: dict) -> None:
    """`"genomeclaw" in plugins.allow` so the plugin is allowed to load."""
    allow = baked_openclaw_json.get("plugins", {}).get("allow") or []
    assert "genomeclaw" in allow, (
        f"INV-P001: sandbox image's baked plugins.allow={allow!r}; "
        "expected to include 'genomeclaw'. Without this, the gateway loads the "
        "plugin entry but the plugin's tools aren't surfaced to the agent."
    )


@pytest.mark.needs_sandbox
def test_invP001_baked_hostservice_baseurl_uses_build_arg_port(
    baked_openclaw_json: dict,
) -> None:
    """`hostService.baseUrl` points at `host.openshell.internal:${GENOMECLAW_HOST_PORT}`."""
    port = os.environ.get("GENOMECLAW_HOST_PORT", "8645")
    entries = baked_openclaw_json.get("plugins", {}).get("entries", {})
    genomeclaw_entry = entries.get("genomeclaw") or {}
    host_service = (genomeclaw_entry.get("config") or {}).get("hostService") or {}
    base_url = host_service.get("baseUrl")
    expected = f"http://host.openshell.internal:{port}"
    assert base_url == expected, (
        f"INV-P001: baked plugins.entries.genomeclaw.config.hostService.baseUrl="
        f"{base_url!r}; expected {expected!r}. The plugin uses this URL to "
        "reach the host service; if it's wrong, every tool call returns "
        "ECONNREFUSED."
    )


@pytest.mark.needs_sandbox
def test_invP001_baked_hostservice_timeoutms_is_30000(
    baked_openclaw_json: dict,
) -> None:
    """`hostService.timeoutMs == 30000`."""
    entries = baked_openclaw_json.get("plugins", {}).get("entries", {})
    genomeclaw_entry = entries.get("genomeclaw") or {}
    host_service = (genomeclaw_entry.get("config") or {}).get("hostService") or {}
    assert host_service.get("timeoutMs") == 30000, (
        f"INV-P001: baked plugins.entries.genomeclaw.config.hostService.timeoutMs="
        f"{host_service.get('timeoutMs')!r}; expected 30000."
    )


@pytest.mark.needs_sandbox
def test_invP001_baked_openai_apikey_is_env_ref_not_literal(
    baked_openclaw_json: dict,
) -> None:
    """`models.providers.openai.apiKey` is an env-ref, never a literal key.

    The ref shape is the flat dict `{"source": "env", "provider": "default",
    "id": "OPENAI_API_KEY"}` (verified empirically against the running
    container). A literal `sk-…` value here would mean the image carries
    the operator's API key in a layer — that's the failure mode this test
    catches.
    """
    providers = baked_openclaw_json.get("models", {}).get("providers", {})
    apikey = (providers.get("openai") or {}).get("apiKey")
    assert isinstance(apikey, dict), (
        f"INV-P001: models.providers.openai.apiKey is {type(apikey).__name__}, "
        f"value={apikey!r}; expected an env-ref dict. A literal string here "
        "means the operator's credential leaked into the image layer."
    )
    assert apikey.get("source") == "env", (
        f"INV-P001: models.providers.openai.apiKey.source={apikey.get('source')!r}; "
        "expected 'env' so the key is resolved from the gateway process's env "
        "at startup, not baked into the image."
    )
    assert apikey.get("id") == "OPENAI_API_KEY", (
        f"INV-P001: models.providers.openai.apiKey.id={apikey.get('id')!r}; "
        "expected 'OPENAI_API_KEY' so the gateway reads from the canonical env var."
    )
    # Defensive: walk the entire baked config and assert no literal openai
    # key value appears anywhere. Catches the case where the bake correctly
    # sets apiKey to an env-ref but accidentally also puts the literal in
    # auth.profiles or anywhere else.
    full_blob = json.dumps(baked_openclaw_json)
    match = _OPENAI_KEY_PATTERN.search(full_blob)
    assert not match, (
        f"INV-P001: a literal OpenAI API key was found in the baked "
        f"openclaw.json at offset {match.start() if match else '?'}; the "
        "image must never carry the operator's credential in a layer. "
        f"Matched substring (redacted): {match.group(0)[:8]}...{match.group(0)[-4:]}"
    )


@pytest.mark.needs_sandbox
def test_invP001_baked_gateway_bind_is_loopback(baked_openclaw_json: dict) -> None:
    """`gateway.bind == "loopback"` (nemoclaw-canonical-integration Phase 3, Facet A1).

    On sandbox-base:v0.0.50 the gateway defaults to `bind=auto` (0.0.0.0) in a
    container and refuses to start without auth. nemoclaw launches the
    supervised gateway flag-lessly, so baking `bind=loopback` is what lets it
    start (127.0.0.1, where auth=none is valid) without baking a gateway-access
    secret. See the Dockerfile gateway-config bake + work-notes Phase 3.
    """
    bind = baked_openclaw_json.get("gateway", {}).get("bind")
    assert bind == "loopback", (
        f"INV-P001 / Facet A1: baked gateway.bind={bind!r}; expected 'loopback'. "
        "Without it the supervised gateway (`openclaw gateway run --port`) hits "
        "the container bind=auto auth guard and refuses to start, breaking onboard, "
        "`nemoclaw recover`, and the dashboard/TUI."
    )


@pytest.mark.needs_sandbox
def test_invP001_no_static_gateway_token_baked(baked_openclaw_json: dict) -> None:
    """No static gateway-access token is baked into the image config.

    Per the 2026-05-30 privacy-safety review: a static `gateway.auth.token`
    baked into a Dockerfile layer persists in image history and is identical
    across every deployment — the same INV-P003 class of risk a baked API key
    would be. The loopback-bind posture needs no token; if a token is ever
    required for a bind=auto dashboard path it MUST be generated at runtime and
    passed via env, never baked. This guards against that regression.
    """
    gateway = baked_openclaw_json.get("gateway", {})
    auth = gateway.get("auth") or {}
    token = auth.get("token")
    # Absent / empty / OpenClaw's redaction sentinel are all fine. A real
    # non-empty literal is the regression this test catches.
    redaction_sentinels = {"__OPENCLAW_REDACTED__", "", None}
    assert token in redaction_sentinels, (
        f"INV-P003 / Facet A1: a static gateway.auth.token is baked into the "
        f"image config (value redacted). Remove it — the loopback gateway needs "
        "no token, and a bind=auto token must be runtime-generated + env-injected, "
        "never baked into an image layer."
    )
    assert auth.get("mode") != "token", (
        f"INV-P003 / Facet A1: baked gateway.auth.mode='token' implies a baked "
        "static token. The loopback posture uses auth=none (or unset); a token "
        "mode belongs only to a runtime-generated, env-injected dashboard path."
    )


@pytest.mark.needs_sandbox
def test_invP001_baked_gateway_auth_mode_is_none(baked_openclaw_json: dict) -> None:
    """`gateway.auth.mode == "none"` completes the loopback-tokenless posture.

    With `bind=loopback` alone the gateway auto-generates a per-startup token
    that loopback clients (agent / dashboard / TUI) don't have → "unauthorized:
    gateway token missing". Baking `auth.mode=none` lets gateway-routed clients
    connect token-free on loopback. Safe per the 2026-05-30 privacy review
    (loopback bind + NemoClaw's authenticated port-forward).
    """
    mode = baked_openclaw_json.get("gateway", {}).get("auth", {}).get("mode")
    assert mode == "none", (
        f"Facet A1: baked gateway.auth.mode={mode!r}; expected 'none' so the "
        "loopback gateway accepts token-free connections from the agent/dashboard/TUI."
    )


@pytest.mark.needs_sandbox
def test_invP001_baked_env_home_is_sandbox(baked_image_env: list[str]) -> None:
    """`ENV HOME=/sandbox` is set in the image.

    Without this, `openclaw config` defaults to `/root/.openclaw` which the
    unprivileged sandbox user (uid 998) cannot write. Every post-install
    `openclaw config set` then EACCESes — surfaced 2026-05-24 during the
    demo-questions onboard attempt.
    """
    assert "HOME=/sandbox" in baked_image_env, (
        f"INV-P001: sandbox image's ENV does not include HOME=/sandbox. "
        f"Got Config.Env={baked_image_env!r}. "
        "Without ENV HOME=/sandbox, openclaw config defaults to /root/.openclaw "
        "and EACCESes for the unprivileged sandbox user."
    )
