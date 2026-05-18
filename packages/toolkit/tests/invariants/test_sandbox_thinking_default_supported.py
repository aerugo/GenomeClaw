"""`INV-A002` validation gate — baked `thinkingDefault` is a valid per-model level.

Slice 5 probe finding (2026-05-15): OpenClaw validates the `--thinking <level>`
parameter against the **configured model**, not against the union of all
documented levels. For openai/gpt-5.5 the supported set is
``{off, minimal, low, medium, high, xhigh}``; `adaptive` and `max` are
rejected at per-call dispatch time. Slices 1-4 baked
``thinkingDefault: max`` and the gateway silently coerced/rejected it —
which means the INV-A002 synthesis floor was never actually applied per
call.

This test asserts the baked sandbox image's `thinkingDefault` is a level
the configured default model actually accepts. A future Dockerfile edit
that flips back to `max` (or that switches the default model without
updating the floor) gets caught on the next image rebuild.

The valid-levels map is a snapshot of OpenClaw v2026.4.24's behaviour; if
OpenClaw extends support for `max` to gpt-5.5 in a future release, this
test's expected set updates rather than the image's bake.

Gated on `GENOMECLAW_SANDBOX_IMAGE` per the rest of the sandbox-image
invariant suite.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess

import pytest

# Snapshot of OpenClaw v2026.4.24's per-model supported thinking levels
# (extracted from probe runs in slice 5; see work-notes Phase 3 slice 5).
# Keys are model ids as they appear in `agents.defaults.model` (the value
# may be of the form `provider/model-id`, in which case we match by the
# trailing model id after the slash).
_VALID_THINKING_LEVELS_BY_MODEL: dict[str, frozenset[str]] = {
    "gpt-5.5": frozenset({"off", "minimal", "low", "medium", "high", "xhigh"}),
    # Extend here when other models become the default. o-series models
    # also support "max"; per-model probes confirm the exact set.
}


@pytest.fixture(scope="module")
def sandbox_image() -> str:
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
def test_invA002_baked_thinking_default_is_valid_for_configured_model(
    sandbox_image: str,
) -> None:
    """The baked `thinkingDefault` is in the supported set for `agents.defaults.model`.

    Implements the INV-A002 deployment gate: the synthesis floor doesn't
    silently downgrade because the baked value is one the configured model
    rejects.
    """
    config = _read_baked_config(sandbox_image)
    agents_defaults = config.get("agents", {}).get("defaults", {})

    thinking_default = agents_defaults.get("thinkingDefault")
    model = agents_defaults.get("model")

    assert thinking_default, (
        f"INV-A002 deployment: baked image {sandbox_image!r} has no "
        f"`agents.defaults.thinkingDefault` set; the synthesis-reasoning "
        f"floor falls through to whatever the model's API default is."
    )
    assert model, (
        f"INV-A002 deployment: baked image {sandbox_image!r} has no "
        f"`agents.defaults.model` set; cannot validate the thinking floor "
        f"against an unknown model."
    )

    # Extract the model id from the `provider/model-id` form if present.
    model_id = model.split("/", 1)[1] if "/" in model else model
    valid_levels = _VALID_THINKING_LEVELS_BY_MODEL.get(model_id)
    if valid_levels is None:
        pytest.skip(
            f"per-model supported-levels map has no entry for {model_id!r}; "
            f"extend `_VALID_THINKING_LEVELS_BY_MODEL` in this test after "
            f"probing the new model's accepted set via `openclaw agent "
            f"--thinking <level>`."
        )

    assert thinking_default in valid_levels, (
        f"INV-A002 deployment violation: baked thinkingDefault={thinking_default!r} "
        f"is NOT in the supported set for model {model_id!r}. "
        f"Valid levels: {sorted(valid_levels)}. "
        f"OpenClaw will silently coerce or reject this at per-call dispatch — "
        f"the synthesis floor will not actually be applied."
    )


@pytest.mark.needs_sandbox
def test_invA002_baked_thinking_default_is_at_model_ceiling(sandbox_image: str) -> None:
    """The baked `thinkingDefault` is the **highest** level the model supports.

    INV-A002's contract is *the maximum reasoning effort the configured
    model supports*. For gpt-5.5 that's `xhigh`. A baked value of `high`
    or below would technically be supported (the prior gate would pass)
    but would understate the floor and silently weaken health-interpretation
    reasoning quality.

    The "ceiling" is the lexicographically-last level in the supported set
    by the OpenClaw documented ordering (off < minimal < low < medium <
    high < xhigh). If a model gains a `max` level in the future, update
    `_VALID_THINKING_LEVELS_BY_MODEL` and the `_CEILING_BY_MODEL` here.
    """
    config = _read_baked_config(sandbox_image)
    agents_defaults = config.get("agents", {}).get("defaults", {})
    thinking_default = agents_defaults.get("thinkingDefault")
    model = agents_defaults.get("model", "")
    model_id = model.split("/", 1)[1] if "/" in model else model

    ceiling_by_model: dict[str, str] = {
        "gpt-5.5": "xhigh",
    }
    expected_ceiling = ceiling_by_model.get(model_id)
    if expected_ceiling is None:
        pytest.skip(
            f"per-model ceiling map has no entry for {model_id!r}; extend "
            f"`ceiling_by_model` after probing this model's supported set."
        )
    assert thinking_default == expected_ceiling, (
        f"INV-A002 deployment: baked thinkingDefault={thinking_default!r} for model "
        f"{model_id!r} is NOT the model's ceiling ({expected_ceiling!r}). The "
        f"floor must be set to the highest reasoning level the model supports."
    )
