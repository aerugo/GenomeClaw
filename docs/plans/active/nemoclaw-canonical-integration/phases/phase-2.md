# Phase 2: Dockerfile Rewrite + Base-Image SHA Pin

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Rewrite [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) to (a) bake the plugin inside the OpenShell Landlock RW baseline and (b) pin the base image to eliminate version skew between the host `nemoclaw` CLI and the sandbox runtime.

> **Path / pin revised after Phase 1 probe** (this scaffold predates it):
> - **Canonical path** is `/sandbox/build/genomeclaw/`, NOT `/sandbox/.openclaw-data/extensions/genomeclaw/`. The `.openclaw-data` symlink layout referenced below does not exist in `sandbox-base:v0.0.50`. `/sandbox/build/` is chosen over `/sandbox/.openclaw/extensions/` because `openclaw plugins install --link` refuses a source path already inside the auto-scanned extensions tree. The plugin is registered via `openclaw plugins install --link` and the loader reads `dist/` from the linked path directly. Both paths are inside the Landlock RW baseline (`/sandbox/`), which is the property `INV-D011` actually requires.
> - **Pin is `:v0.0.50`** (version tag matching the host `nemoclaw --version`), NOT a `@sha256:` digest. Version-tagged GHCR digests are stable per-arch-index and keep the multi-arch pull portable; the resolved digest is recorded in a Dockerfile comment as the structural breadcrumb. See work-notes Decision 2.

## Scope Boundaries

- **In scope**: Dockerfile rewrite; image build; container-start verification that the plugin is at the canonical path and discoverable by `openclaw plugins list`.
- **Out of scope**: gateway lifecycle (Phase 3); credential system migration (Phase 3); script changes (Phase 4); documentation (Phase 6).

## Invariants Enforced in This Phase

- **NEW INV-D011 (provisional)** Plugin Install Path Follows NemoClaw's Canonical Pattern — enforced structurally by a post-build container probe that asserts `/sandbox/build/genomeclaw/package.json` exists and `/opt/genomeclaw/` does not, plus a Dockerfile-grep discovery test that requires the `openclaw plugins install` source path to start with a Landlock RW prefix (`/sandbox/` or `/tmp/`).
- **INV-V001** Verification Methodology — image probe uses `docker exec` + structured filesystem assertions, not log-grep.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Tests

**Test cases** (as implemented — paths/pin reflect the Phase 1 revision above):

In `packages/toolkit/tests/integration/test_sandbox_image_canonical_plugin_path.py` (docker-gated on `GENOMECLAW_SANDBOX_IMAGE`):

1. `test_plugin_lives_at_canonical_path` — boot the built image; assert `/sandbox/build/genomeclaw/package.json` exists and is readable as user `sandbox`.
2. `test_plugin_dist_index_at_canonical_path` — assert the compiled entrypoint `/sandbox/build/genomeclaw/dist/index.js` exists.
3. `test_plugin_absent_from_legacy_opt_path` — assert `/opt/genomeclaw/` does NOT exist.
4. `test_plugin_discoverable_by_openclaw_plugins_list` — run `openclaw plugins list`; assert a `genomeclaw` row is present and shows `enabled` status. (`plugins list` renders the source as `~/…`, so we assert on the enabled-status row, not a literal `/sandbox/` substring.)

In `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` (no docker; Dockerfile-grep):

5. `test_invD011_dockerfile_uses_landlock_baseline_path_for_plugin` — the `openclaw plugins install` source path starts with a Landlock RW prefix (`/sandbox/` or `/tmp/`).
6. `test_invD011_dockerfile_does_not_reference_legacy_opt_path` — no non-comment line references `/opt/genomeclaw`.
7. `test_invD011_base_image_pinned_by_version_tag` — `FROM`/`ARG SANDBOX_BASE=` resolves to `:vX.Y.Z` (or a `@sha256:` digest), never `:latest`.
8. `test_invD011_no_other_sandbox_dockerfiles_use_opt_install_path` — discovery sweep across `packages/*/sandbox/Dockerfile`.

Plus the **end-to-end smoke gate** (manual / scripted, captured in work-notes rather than a docker-in-pytest test, since onboarding the sandbox is not driveable from inside the toolkit pytest container): boot the sandbox from the newly-built image via `./scripts/onboard-sandbox.sh` (gateway still started via the Step 7b path — this phase doesn't fix that; Phase 3 does), then run `./scripts/ask.sh --capture "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."`. Assert: (a) the `.trace.json` parses; (b) `meta.finalAssistantVisibleText` is a non-empty string > 200 chars; (c) the sibling trajectory file shows at least one successful `genomeclaw_*` tool call. If `GENOMECLAW_REPLAY_LLM=1` is set, also pipe `(trajectory_summary, reply)` to the LLM-judge from [packages/toolkit/tests/agent_replay/_judge.py](../../../../packages/toolkit/tests/agent_replay/_judge.py) and assert `faithful=true` AND `understandable=true`. Per `INV-A006` / `INV-V001`: no substring-list enumeration.

RED state: the docker-gated tests (1–4) fail until the new image is built; the invD011 tests (5–8) fail while the Dockerfile still bakes under `/opt/genomeclaw/` and pins `:latest`.

### Step 2.2 — GREEN: Minimal Implementation

1. Resolve the pin: `nemoclaw --version` → `v0.0.50`; the matching base tag `ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.50` is already locally cached and contains OpenClaw 2026.5.18 (Phase 1). Record the resolved multi-arch index digest in a Dockerfile comment.
2. Rewrite the Dockerfile:
   - `ARG SANDBOX_BASE=ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.50` + `FROM ${SANDBOX_BASE}`.
   - `COPY` the plugin source (package.json, tsconfig, src/, types/, openclaw.plugin.json, policy-preset.yaml) into `/sandbox/build/genomeclaw/`.
   - Build there (`npm ci && npm run build`), then `chown -R sandbox:sandbox /sandbox/build/genomeclaw`.
   - Register with `openclaw plugins install /sandbox/build/genomeclaw --link` as user `sandbox` (file-drop alone is not auto-discovered in v0.0.50 — Phase 1 Q1). The source path is deliberately under `/sandbox/build/`, NOT `/sandbox/.openclaw/extensions/`, because `install --link` rejects a source already in the auto-scan tree.
   - Keep the existing baked config layers (gateway.mode, plugins.allow, hostService.baseUrl, OpenAI provider, agent prompt, workspace bootstrap).
3. Build via the onboard script's pre-build (`docker build --build-arg GENOMECLAW_HOST_PORT=8645 -t genomeclaw/sandbox:port-8645 -f packages/nemoclaw-plugin/sandbox/Dockerfile packages/nemoclaw-plugin/`), or directly to a throwaway tag (`genomeclaw/sandbox:phase2`) for test isolation.
4. Run the tests. Confirm all 8 structural tests turn green; then run the smoke gate.

**Files affected**:
- [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile): rewrite
- `packages/toolkit/tests/integration/test_sandbox_image_canonical_plugin_path.py`: CREATE
- `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` (provisional, promoted in Phase 6): CREATE

### Step 2.3 — REFACTOR

- Add a top-of-file comment in the Dockerfile noting the SHA-pin bump cadence (rebump whenever the host `nemoclaw` CLI version changes).
- Consolidate any duplicated COPY layers.
- If the build is now multi-stage, name stages (`AS build`, `AS runtime`) for clarity.

---

## Implementation Details

### Edge Cases to Handle

- **No symlink needed**: `/sandbox/build/genomeclaw/` is registered via `install --link`; the `.openclaw/extensions` symlink the original scaffold imagined does not apply (and would collide with the auto-scan-tree rejection).
- **`npm ci` runs as root** during build, but the resulting tree must be `sandbox`-owned. A final `chown -R sandbox:sandbox /sandbox/build/genomeclaw` after `npm ci` handles it.
- **`install --link` source-path collision**: a source under `/sandbox/.openclaw/extensions/` errors with "plugin already exists … (delete it first)" because that tree is auto-scanned. `/sandbox/build/` avoids this.
- **Pin availability**: `:v0.0.50` matches the host CLI exactly and is locally cached, so no gap. Bump the pin in the same change whenever the host `nemoclaw` is upgraded.

### Error Handling

- Build failure on the pin: the `:v0.0.50` tag must be pullable / cached. Re-pull with `docker pull ghcr.io/nvidia/nemoclaw/sandbox-base:v0.0.50` and confirm it matches `nemoclaw --version`.
- Plugin not found by `openclaw plugins list` after build: probable cause is `install --link` failing silently (source path inside the auto-scan tree → "plugin already exists") OR the `chown` not running before `USER sandbox`. Re-inspect inside the container.

### Privacy / Egress Notes (if applicable)

- No new egress destinations. Build still pulls from `ghcr.io/nvidia/...`, same as before.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| [packages/nemoclaw-plugin/sandbox/Dockerfile](../../../../packages/nemoclaw-plugin/sandbox/Dockerfile) | MODIFY | Plugin path migration to `/sandbox/build/genomeclaw/` + `:v0.0.50` pin |
| `packages/toolkit/tests/integration/test_sandbox_image_canonical_plugin_path.py` | CREATE | Tests 1–4 (canonical path, dist entrypoint, absence from /opt, plugin discovery) |
| `packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py` | CREATE | Tests 5–8 (Landlock-baseline install path, no /opt ref, version-tag pin, cross-Dockerfile discovery) |
| [docs/plans/active/nemoclaw-canonical-integration/work-notes.md](../work-notes.md) | MODIFY | Phase 2 progress + decisions |

---

## Verification

```bash
# Build the image (with the canonical host port baked in)
docker build --build-arg GENOMECLAW_HOST_PORT=8645 \
  -t genomeclaw/sandbox:phase2 \
  -f packages/nemoclaw-plugin/sandbox/Dockerfile packages/nemoclaw-plugin/

# Run the docker-gated path tests against the built image
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase2 \
uv --project packages/toolkit run pytest \
  packages/toolkit/tests/integration/test_sandbox_image_canonical_plugin_path.py -v -m needs_sandbox

# Run the (no-docker) invD011 discovery tests
uv --project packages/toolkit run pytest \
  packages/toolkit/tests/invariants/test_invD011_plugin_install_path.py -v

# Confirm no other tests broken
uv --project packages/toolkit run pytest packages/toolkit/tests/ -x

# Smoke: plugin really discoverable (table output, no --json — see test note)
CID=$(docker run -d --rm --user sandbox -e HOME=/sandbox genomeclaw/sandbox:phase2 sleep 600)
docker exec --user sandbox -e HOME=/sandbox "$CID" openclaw plugins list | grep genomeclaw
docker stop "$CID"

# End-to-end smoke gate: muscle question via ask.sh (onboard rebuilds from the
# canonical-path Dockerfile + recreates the sandbox; gateway still via Step 7b)
./scripts/onboard-sandbox.sh
bin/genomeclaw host service   # in a separate shell, against an active derived run
GENOMECLAW_REPLAY_LLM=1 ./scripts/ask.sh --capture \
  "Give personalized recommendations based on genome on how I should train to build muscle for general fitness and give personalized recommendations for diet."
# Inspect: docs/reports/demo-<today>-logs/give-personalized-recommendations-*.trace.json
#         docs/reports/demo-<today>-logs/give-personalized-recommendations-*.trajectory.jsonl
# Paste the LLM-judge verdict + trace excerpt into work-notes.md Phase 2 § Test Results.
```

---

## Completion Criteria

- [ ] Dockerfile updated; base image pinned by `:v0.0.50` version tag (digest recorded in comment)
- [ ] Plugin tree at `/sandbox/build/genomeclaw/` (inside the Landlock RW baseline)
- [ ] `/opt/genomeclaw/` does NOT exist in the image
- [ ] `openclaw plugins list` returns an enabled `genomeclaw` row from within a fresh container
- [ ] All 8 structural Phase 2 tests pass (4 docker-gated path + 4 invD011 discovery)
- [ ] Muscle-question smoke gate passes; verdict captured in work-notes (with LLM-judge result if `GENOMECLAW_REPLAY_LLM=1` set)
- [ ] No other previously-passing tests fail
- [ ] `work-notes.md` Phase 2 § Test Results contains pytest output + manual probe output
- [ ] Phase status updated in `development-plan.md`
