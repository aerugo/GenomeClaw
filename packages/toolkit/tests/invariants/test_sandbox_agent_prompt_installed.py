"""Sandbox-image gate: the agent system prompt is installed in the openclaw config.

Pairs with [test_agent_system_prompt_contract.py](
test_agent_system_prompt_contract.py) which gates the prompt's content. This
test gates the **deployment**: the prompt must actually be baked into the
sandbox image's openclaw.json as the default agent's `systemPromptOverride`.

A future Dockerfile change that drops the install-agent-prompt.py step (or
breaks it) would leave the sandbox running with no agent system prompt —
the research-and-synthesis protocol would silently not apply. This gate
catches that.

Gated on `GENOMECLAW_SANDBOX_IMAGE` per the rest of the sandbox-image
invariant suite.
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


def _read_baked_config(image: str) -> dict:
    """Read /sandbox/.openclaw/openclaw.json out of the image as JSON."""
    proc = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "--entrypoint",
            "cat",
            image,
            "/sandbox/.openclaw/openclaw.json",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        pytest.fail(
            f"could not read /sandbox/.openclaw/openclaw.json from image {image!r}: "
            f"rc={proc.returncode}; stderr={proc.stderr!r}"
        )
    return json.loads(proc.stdout)


@pytest.mark.needs_sandbox
def test_genomeclaw_agent_registered_in_config(sandbox_image: str) -> None:
    """The baked openclaw.json carries a `genomeclaw` named agent as default."""
    config = _read_baked_config(sandbox_image)
    agents = config.get("agents", {}).get("list", [])
    assert agents, (
        "INV-A001 deployment: no agents registered in the baked sandbox config; "
        "the install-agent-prompt.py Dockerfile step is missing or broken."
    )
    genomeclaw_agents = [a for a in agents if a.get("id") == "genomeclaw"]
    assert genomeclaw_agents, (
        f"INV-A001 deployment: no agent with id='genomeclaw' in baked config; "
        f"got agent ids {[a.get('id') for a in agents]}"
    )
    assert genomeclaw_agents[0].get("default") is True, (
        "INV-A001 deployment: the genomeclaw agent must be the default agent"
    )


@pytest.mark.needs_sandbox
def test_system_prompt_installed_with_protocol_content(sandbox_image: str) -> None:
    """The systemPromptOverride is non-empty + contains the protocol's load-bearing terms.

    Pins the deployment-level contract that what landed in the config is
    actually the prompt the agent-system-prompt-contract tests validated.
    The agent's research-and-synthesis behaviour depends on this prompt
    being live in the gateway.
    """
    config = _read_baked_config(sandbox_image)
    agents = config.get("agents", {}).get("list", [])
    genomeclaw_agent = next((a for a in agents if a.get("id") == "genomeclaw"), None)
    assert genomeclaw_agent is not None
    prompt = genomeclaw_agent.get("systemPromptOverride", "")
    # The prompt is multi-thousand-character; anything below 5000 chars is
    # almost certainly truncation or a regression.
    assert len(prompt) >= 5000, (
        f"INV-A001 deployment: systemPromptOverride is suspiciously short "
        f"({len(prompt)} chars); expected the full agent-system-prompt.md "
        "(currently ~14K chars). Possible truncation in the install step."
    )
    # Load-bearing terms — if any of these are absent, the protocol the
    # tests-in-the-repo gated is not what the sandbox is running.
    for term in (
        "research-and-synthesis",
        "health-interpretation turn",
        "memory_search",
        "INV-A002",
        "Supersedes",
    ):
        assert term in prompt, (
            f"INV-A001 deployment: installed system prompt missing "
            f"load-bearing term {term!r}; the install step may have transformed "
            "the prompt text in a way that broke the protocol contract."
        )
