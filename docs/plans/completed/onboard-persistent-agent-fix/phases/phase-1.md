# Phase 1: Bake the Persistent-Path Config Into the Sandbox Dockerfile

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Make the freshly-built `genomeclaw/sandbox:port-${GENOMECLAW_HOST_PORT}` image self-sufficient enough that `openclaw gateway run` succeeds on first start, the GenomeClaw plugin loads with 9 tools, and the OpenAI provider resolves its API key from the gateway process's env — without any post-install `openclaw config set` having to succeed first. Phase 2 will rip out the now-redundant post-install config calls in `scripts/onboard-sandbox.sh`; this phase lays the foundation.

## Scope Boundaries

- **In scope**: edits to `packages/nemoclaw-plugin/sandbox/Dockerfile`; one new baked-config invariant test file.
- **Out of scope**: any change to `scripts/onboard-sandbox.sh` (Phase 2); the colima-mounts doctor check (Phase 3); promoting `INV-P003` (Phase 2). Also: the `auth-profiles.json` file — that holds a per-operator secret and must NOT be baked into the image (would land in a Docker layer, accessible to anyone who pulls the image). Auth-profile placement stays in Phase 2 via stdin-based `docker exec`.

## Invariants Enforced in This Phase

- **INV-P001** Privacy Is the Default Operating Mode — the new baked-config gate (extending the existing `test_invP001_sandbox_web_egress_contract.py`) asserts the persistent-path config is baked correctly; the apiKey-via-env-ref bake is part of the same gate because misconfiguring it (e.g., baking a literal key) would put a secret in the image. The test pins both the presence-of-correct-shape AND the absence-of-literal-key-in-config.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases** (all in `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py`):

1. `test_invP001_baked_gateway_mode_is_local` — load `/sandbox/.openclaw/openclaw.json` from the built image; assert `gateway.mode == "local"`.
2. `test_invP001_baked_plugins_allow_contains_genomeclaw` — assert `"genomeclaw" in openclaw_json["plugins"]["allow"]`.
3. `test_invP001_baked_hostservice_baseurl_uses_build_arg_port` — assert `plugins.entries.genomeclaw.config.hostService.baseUrl == f"http://host.openshell.internal:{GENOMECLAW_HOST_PORT}"` where `GENOMECLAW_HOST_PORT` is read from the test's env (default 8645 matching the Dockerfile ARG default).
4. `test_invP001_baked_hostservice_timeoutms_is_30000` — assert `plugins.entries.genomeclaw.config.hostService.timeoutMs == 30000`.
5. `test_invP001_baked_openai_apikey_is_env_ref_not_literal` — assert `models.providers.openai.apiKey` has shape `{"$ref": {"provider": "default", "source": "env", "id": "OPENAI_API_KEY"}}` (or whatever the actual ref-shape is — confirm via `openclaw config get` on a manually-set config first). Crucially: assert the value is NOT a literal `sk-…` string. Use a regex (`^sk-[a-z]+-[A-Za-z0-9_-]{20,}$`) to assert absence of any value that looks like an OpenAI key anywhere in the config blob (defensive: catches the case where someone misconfigures the bake and accidentally hard-codes their dev key).
6. `test_invP001_baked_env_home_is_sandbox` — `docker inspect --format '{{json .Config.Env}}'` the built image; assert `"HOME=/sandbox"` is in the env list.

**Test sketch**:

```python
"""INV-P001: persistent-path config is baked into the sandbox image so
the gateway starts cleanly on first run, without needing any post-install
`openclaw config set` (which is broken under nemoclaw's exec wrapper).

Pairs with test_invP001_sandbox_web_egress_contract.py which covers the
web-search / web-fetch portion of the bake. Same image, different keys.
"""
from __future__ import annotations

import json
import os
import re
import subprocess

import pytest

from tests.support.sandbox_image import sandbox_image_tag  # existing helper used by the web-egress test

OPENAI_KEY_PATTERN = re.compile(r"sk-[a-z]+-[A-Za-z0-9_-]{20,}")


@pytest.fixture(scope="module")
def baked_openclaw_json(sandbox_image_tag: str) -> dict:
    """Cat /sandbox/.openclaw/openclaw.json out of the built image."""
    proc = subprocess.run(
        ["docker", "run", "--rm", "--entrypoint", "cat", sandbox_image_tag,
         "/sandbox/.openclaw/openclaw.json"],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


@pytest.fixture(scope="module")
def baked_image_env(sandbox_image_tag: str) -> list[str]:
    proc = subprocess.run(
        ["docker", "inspect", "--format", "{{json .Config.Env}}", sandbox_image_tag],
        capture_output=True, text=True, check=True,
    )
    return json.loads(proc.stdout)


def test_invP001_baked_gateway_mode_is_local(baked_openclaw_json: dict) -> None:
    assert baked_openclaw_json.get("gateway", {}).get("mode") == "local"


def test_invP001_baked_plugins_allow_contains_genomeclaw(baked_openclaw_json: dict) -> None:
    allow = baked_openclaw_json.get("plugins", {}).get("allow") or []
    assert "genomeclaw" in allow


def test_invP001_baked_hostservice_baseurl_uses_build_arg_port(baked_openclaw_json: dict) -> None:
    port = os.environ.get("GENOMECLAW_HOST_PORT", "8645")
    entry = baked_openclaw_json["plugins"]["entries"]["genomeclaw"]["config"]["hostService"]
    assert entry["baseUrl"] == f"http://host.openshell.internal:{port}"


def test_invP001_baked_hostservice_timeoutms_is_30000(baked_openclaw_json: dict) -> None:
    entry = baked_openclaw_json["plugins"]["entries"]["genomeclaw"]["config"]["hostService"]
    assert entry["timeoutMs"] == 30000


def test_invP001_baked_openai_apikey_is_env_ref_not_literal(baked_openclaw_json: dict) -> None:
    apikey = baked_openclaw_json["models"]["providers"]["openai"]["apiKey"]
    # The exact ref shape needs to be confirmed empirically — see Phase 1
    # implementation notes. The test asserts ref-shape AND no literal key.
    assert isinstance(apikey, dict), f"apiKey must be a ref dict, got {type(apikey).__name__}"
    assert apikey.get("source") == "env" or apikey.get("ref", {}).get("source") == "env", (
        f"apiKey must be env-ref, got {apikey!r}"
    )
    # Defensive: the entire serialised config must not contain a literal openai key.
    full_blob = json.dumps(baked_openclaw_json)
    assert not OPENAI_KEY_PATTERN.search(full_blob), (
        "INV-P001: a literal OpenAI API key was found in the baked image's openclaw.json"
    )


def test_invP001_baked_env_home_is_sandbox(baked_image_env: list[str]) -> None:
    assert "HOME=/sandbox" in baked_image_env, (
        "ENV HOME=/sandbox missing from sandbox image — openclaw config will "
        "default to /root/.openclaw and EACCES on the unprivileged sandbox user."
    )
```

After writing the tests, run them and **confirm they fail for the intended reason**. Paste the failing output into `work-notes.md`.

### Step 1.2 — GREEN: Minimal Implementation

Edit `packages/nemoclaw-plugin/sandbox/Dockerfile`:

```dockerfile
# After the existing `USER sandbox` + `RUN openclaw plugins install /opt/genomeclaw --link` step,
# and after the existing `RUN openclaw config set tools.web.search.enabled true && ...` step:

# Set HOME explicitly so openclaw config defaults to /sandbox/.openclaw
# (the unprivileged sandbox user's writeable home) rather than /root/.openclaw
# (which EACCESes for uid 998). Without this, every `openclaw config set`
# issued by docker exec or nemoclaw exec lands in /root and fails.
ENV HOME=/sandbox

# Bake the persistent-path runtime config so the gateway starts cleanly on
# first run and the GenomeClaw plugin loads without any post-install
# `openclaw config set` (which is broken under nemoclaw's exec wrapper —
# see docs/plans/active/onboard-persistent-agent-fix/spec.md for context).
RUN openclaw config set gateway.mode local \
 && openclaw config set plugins.allow '["genomeclaw"]' \
 && openclaw config set plugins.entries.genomeclaw.config.hostService.baseUrl \
      "http://host.openshell.internal:${GENOMECLAW_HOST_PORT}" \
 && openclaw config set plugins.entries.genomeclaw.config.hostService.timeoutMs 30000

# Bind the OpenAI provider's API key to the OPENAI_API_KEY env var at runtime.
# The gateway process needs the key in its env at startup time; the operator
# supplies it via `docker exec -e OPENAI_API_KEY=...` at gateway-start time
# (see scripts/onboard-sandbox.sh Phase 2). The key NEVER lands in this image
# layer — only the ref to an env var name lands.
RUN openclaw config set models.providers.openai.apiKey \
      --ref-provider default --ref-source env --ref-id OPENAI_API_KEY
```

**Files affected**:
- `packages/nemoclaw-plugin/sandbox/Dockerfile`: 3 new `RUN` blocks + 1 `ENV` line (~12 lines of additions).

### Step 1.3 — REFACTOR

With tests green:

- Confirm the new `RUN` blocks live in the right place (after `openclaw plugins install` so the plugin entry exists when `plugins.allow` is set; after `USER sandbox` so the config writes land in the sandbox user's home).
- Confirm `ENV HOME=/sandbox` lands BEFORE the first `RUN openclaw config set` that follows the `USER sandbox` switch (otherwise that first config-set lands in /root and the subsequent ones land in /sandbox, splitting the config across two homes).
- Tighten the test fixtures: if the existing `tests/support/sandbox_image` helper doesn't expose the right tag, extract a `sandbox_image_tag` fixture in `tests/conftest.py` so both this new test file and the existing `test_invP001_sandbox_web_egress_contract.py` share it.
- Re-run tests after each refactor.

---

## Implementation Details

### Confirming the apiKey ref-shape

The exact JSON shape produced by `openclaw config set models.providers.openai.apiKey --ref-provider default --ref-source env --ref-id OPENAI_API_KEY` needs to be verified empirically before writing the AC5 assertion. Likely candidates:

```json
{ "$ref": { "provider": "default", "source": "env", "id": "OPENAI_API_KEY" } }
```

or

```json
{ "provider": "default", "source": "env", "id": "OPENAI_API_KEY" }
```

The test's `assert apikey.get("source") == "env" or apikey.get("ref", {}).get("source") == "env"` covers both shapes; tighten to whichever turns out to be the truth.

### Edge Cases to Handle

- **`GENOMECLAW_HOST_PORT` default**: the Dockerfile's existing `ARG GENOMECLAW_HOST_PORT=8645` makes the env-substitution work for the canonical case. If a non-default port is supplied via `--build-arg`, the substitution propagates (verified by the existing port-templated `sed` on `policy-preset.yaml`).
- **Bake ordering**: the Dockerfile already has multiple `RUN openclaw config set` blocks. Adding new ones doesn't conflict because each `openclaw config set` is an additive merge into `openclaw.json`. The new `gateway.mode local` block must run as `USER sandbox` (already in scope at the right point in the file).
- **Cache invalidation**: any change to the new `RUN openclaw config set ...` block invalidates layer cache from that point forward. Acceptable — the bake is cheap (~1 second per `openclaw config set`).

### Error Handling

- If `openclaw config set` fails at build time, the build fails. Acceptable — that's a Dockerfile-correctness issue we want to surface early, not silently paper over.

### Privacy / Egress Notes

- The apiKey-via-env-ref bake is a structural privacy improvement: the image carries only the *name* of the env var that holds the secret, not the secret itself. Anyone who pulls the built image gets the ref shape but no key. This makes the persistent path's image safe to push to a private registry, which the previous arrangement (where the script writes the key into `auth-profiles.json` post-onboard) didn't compromise (the key landed in the running container, not the image) but the new arrangement makes more explicit.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/nemoclaw-plugin/sandbox/Dockerfile` | MODIFY | Add `ENV HOME=/sandbox` + 3 new `RUN openclaw config set` blocks. |
| `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py` | CREATE | 6 invariant tests covering AC3 + AC4 + the apiKey-not-literal defensive check. |
| `packages/toolkit/tests/conftest.py` | MODIFY (maybe) | Extract `sandbox_image_tag` fixture if not already shared. |

---

## Verification

```bash
# Build the sandbox image with the new bakes
docker build \
  --build-arg GENOMECLAW_HOST_PORT=8645 \
  -t genomeclaw/sandbox:port-8645 \
  -f packages/nemoclaw-plugin/sandbox/Dockerfile \
  packages/nemoclaw-plugin/

# Manual sanity check
docker run --rm --entrypoint cat genomeclaw/sandbox:port-8645 /sandbox/.openclaw/openclaw.json \
  | jq '.gateway.mode, .plugins.allow, .plugins.entries.genomeclaw.config.hostService, .models.providers.openai.apiKey'
docker inspect --format '{{json .Config.Env}}' genomeclaw/sandbox:port-8645 | jq '.[] | select(startswith("HOME"))'

# Run Phase 1 tests
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py -v

# Run the full invariant suite to confirm no regression
.venv/bin/pytest tests/invariants/ -v

# Static checks
.venv/bin/ruff check tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py
.venv/bin/mypy --strict tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py
```

---

## Completion Criteria

- [ ] All 6 new test cases pass against the freshly-built image.
- [ ] Existing `test_invP001_sandbox_web_egress_contract.py` still passes.
- [ ] Static checks pass (mypy strict, ruff clean).
- [ ] At least one test references `INV-P001` in its name or docstring (5 do via `test_invP001_*` naming).
- [ ] No raw genomic data, secrets, or sample IDs added to fixtures.
- [ ] `work-notes.md` updated with the RED output (paste the actual `pytest` failure), GREEN minimal-diff summary, and any REFACTOR notes.
- [ ] Phase status updated to "Complete" in `development-plan.md`.
- [ ] Manual sanity check at the verification command above returns the expected JSON shape.
