"""`INV-P001` v1.7 — sandbox web egress contract.

The sandbox image ships with an explicit two-part contract:

1. **`tools.web.search.enabled: true`** — native OpenAI `web_search` (the
   hosted `web_search` tool that OpenAI's Responses API exposes) IS available
   when the agent is talking to OpenAI. This is part of the **same egress
   destination** the user already opted into when they configured the OpenAI
   provider — not a new egress destination.

2. **`tools.web.search.provider` UNSET** — no managed `web_search` provider
   (Brave, Tavily, Perplexity, etc.) is pinned at the image layer. The
   managed `web_search` tool effectively no-ops without a provider; the user
   opts into a managed provider explicitly post-install by running
   `openclaw config set tools.web.search.provider <name>` + supplying the
   provider's API key. That action **is** the act of adding a new named
   egress destination per `INV-P001`.

3. **`tools.web.fetch.enabled: false`** — `web_fetch` does outbound HTTP from
   the sandbox to arbitrary URLs and is **not** part of the OpenAI Responses
   API contract; it remains a third named egress destination that requires
   explicit user opt-in.

Per `INV-P001` v1.7 (revised 2026-05-15 from v1.6's blanket-off default):
the threat model treats native OpenAI search as part of the agent provider's
egress envelope, while managed providers + `web_fetch` remain gated. The
user adds a managed provider or enables `web_fetch` per-operation.

Gated on `GENOMECLAW_SANDBOX_IMAGE` per the rest of the sandbox-image
invariant suite — skips cleanly without a built image.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest


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


def _read_baked_config(sandbox_image: str) -> dict:
    """Read `/sandbox/.openclaw/openclaw.json` out of the built image."""
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "cat",
            sandbox_image,
            "/sandbox/.openclaw/openclaw.json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"could not read /sandbox/.openclaw/openclaw.json from image {sandbox_image!r}: "
            f"rc={proc.returncode}; stderr={proc.stderr!r}. "
            "The image's Dockerfile must explicitly bake the web egress contract."
        )
    return json.loads(proc.stdout)


@pytest.mark.needs_sandbox
def test_invP001_web_search_enabled_in_default_config(sandbox_image: str) -> None:
    """`tools.web.search.enabled` is `true` in the baked config.

    Under `INV-P001` v1.7, native OpenAI `web_search` flows through the agent
    provider's egress envelope (not a new destination), so the search tool is
    structurally available. The privacy gate is on **managed providers** + on
    **`web_fetch`**, not on the `enabled` flag itself.
    """
    config = _read_baked_config(sandbox_image)
    web_search_enabled = config.get("tools", {}).get("web", {}).get("search", {}).get("enabled")
    assert web_search_enabled is True, (
        f"INV-P001 v1.7: sandbox image {sandbox_image!r} ships with "
        f"tools.web.search.enabled={web_search_enabled!r}; expected `true` so "
        "native OpenAI web_search activates for Responses-API agent calls "
        "without the user manually flipping a flag."
    )


@pytest.mark.needs_sandbox
def test_invP001_no_managed_search_provider_pinned(sandbox_image: str) -> None:
    """`tools.web.search.provider` is unset (or empty) in the baked config.

    Pinning a managed provider (Brave / Tavily / Perplexity / etc.) at the
    image layer would add a new named egress destination without the user's
    opt-in. The user adds a managed provider explicitly post-install per
    `INV-P001` v1.7.
    """
    config = _read_baked_config(sandbox_image)
    provider = config.get("tools", {}).get("web", {}).get("search", {}).get("provider")
    assert provider in (None, ""), (
        f"INV-P001 v1.7 violation: sandbox image {sandbox_image!r} ships with a "
        f"pinned managed web_search provider ({provider!r}); expected absent or empty. "
        "Managed providers are an opt-in egress destination — the user runs "
        "`openclaw config set tools.web.search.provider <name>` to add one."
    )


@pytest.mark.needs_sandbox
def test_invP001_web_fetch_disabled_in_default_config(sandbox_image: str) -> None:
    """`tools.web.fetch.enabled` is `false` in the baked config.

    `web_fetch` does outbound HTTP from the sandbox to arbitrary URLs and is
    not part of the OpenAI Responses API contract. It is a third named egress
    destination per `INV-P001` and must stay off by default. The user enables
    it explicitly when their workflow requires it.
    """
    config = _read_baked_config(sandbox_image)
    web_fetch_enabled = config.get("tools", {}).get("web", {}).get("fetch", {}).get("enabled")
    assert web_fetch_enabled is False, (
        f"INV-P001 v1.7: sandbox image {sandbox_image!r} ships with "
        f"tools.web.fetch.enabled={web_fetch_enabled!r}; expected `false`. "
        "web_fetch is opt-in; it issues outbound HTTP to arbitrary URLs and "
        "is not part of the OpenAI Responses API contract."
    )
