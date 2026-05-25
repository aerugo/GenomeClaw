# Feature: Onboard Persistent Agent Fix

**Status**: Draft
**Created**: 2026-05-24
**Owner**: aerugo / claude
**Related Plans**: completed [agent-research-and-synthesis](../../completed/agent-research-and-synthesis/) (bakes the sandbox image; this plan extends what it bakes)
**Source report**: [docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md)

---

## Goal

Make `scripts/onboard-sandbox.sh` succeed end-to-end on a fresh macOS-Sequoia + colima host so that `nemoclaw list` shows a usable `genomeclaw` sandbox the operator can immediately talk to via the documented `nemoclaw genomeclaw exec ... openclaw agent ...` path — and do it without ever putting the OpenAI API key on a command-line argv.

## Background

The 2026-05-24 demo session ([docs/reports/genomeclaw-demo-questions-2026-05-24.md](../../../reports/genomeclaw-demo-questions-2026-05-24.md)) tried to onboard the persistent `nemoclaw genomeclaw` sandbox using the documented `./scripts/onboard-sandbox.sh` path and hit three distinct failures, only the first of which has been patched:

1. **Patched in 2026-05-24** — `nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile` aborted at `COPY policy-preset.yaml` because nemoclaw stages only the Dockerfile's directory into the build context. The script now pre-builds the image with the correct context and hands `nemoclaw onboard` a one-line shim Dockerfile (`FROM <pre-built-tag>`). This part works.

2. **Still broken** — after step 1 succeeds, the deployed sandbox's gateway refuses to start (`Gateway start blocked: existing config is missing gateway.mode`), and every follow-up `nemoclaw genomeclaw exec --no-tty -- bash -c "openclaw config set ..."` step emits `EACCES: permission denied, scandir '/opt/genomeclaw'`. Root cause has two parts:

   - **`HOME` is unset / defaults to `/root`** when commands run as `sandbox` (uid 998) without an explicit `HOME=/sandbox`. `openclaw config` then tries to write under `/root/.openclaw/` and EACCESes.
   - **`nemoclaw genomeclaw exec` wraps every command in openshell's filesystem-restriction layer** (landlock or equivalent — confirmed by `mountinfo` parity vs `docker exec` while still EACCESing on `/opt`). So even with `HOME=/sandbox`, the post-install `openclaw config set …` steps run through a sandboxed shim that can't read the plugin dir, fail to register the plugin's `source`, and the gateway then refuses to load it. None of the script's `nemoclaw genomeclaw exec` steps in the section after `nemoclaw onboard` complete cleanly.

3. **Auth-profile write leaked the operator's OpenAI API key into the log**. The script passes a base64 blob (containing the key) as a `python3 -c "import base64; ...base64.b64decode('<blob>')..."` argv. When that command crashed because the target directory didn't yet exist, the Python traceback echoed the full source — including the blob — to stdout, which `tee` captured to `docs/reports/demo-2026-05-24-logs/03-onboard-v2.log`. The log was redacted in-place but the pattern will leak on every future failure that touches an argv-interpolated secret.

The demo session worked around all three by:
- doing the gateway/config setup via `docker exec --user sandbox -e HOME=/sandbox` (bypassing `nemoclaw exec`),
- starting the gateway with `docker exec -d -e OPENAI_API_KEY=...` (env var, not argv-interpolated config),
- pointing `models.providers.openai.apiKey` at `--ref-source env --ref-id OPENAI_API_KEY` so the key is read at runtime from the gateway process's env.

This plan promotes those workarounds into the canonical onboarding path.

Out of scope for this plan but flagged in the demo report:
- `genomeclaw_pgs_compute` reports `done` while `genomeclaw_pgs_get` returns no row (reproduced on PGS000014 + PGS000334). Belongs in its own plan against the host service's PRS-task lifecycle.
- `genomeclaw_gene` argument-serialization bug surfaces on at least CYP1A2/ADORA2A/AHR/POR/BRCA1/BRCA2/TP53 panels. Belongs in its own plan against the plugin's TypeBox parameter shapes.

## Acceptance Criteria

Each criterion is one test or one human-verifiable assertion.

- [ ] **AC1**: After `./scripts/onboard-sandbox.sh` completes on a fresh `nemoclaw onboard --fresh`, `nemoclaw list` shows a `genomeclaw` sandbox alongside any existing sandboxes, with status `(healthy)` and image `openshell/sandbox-from:<tag-from-shim>`.
- [ ] **AC2**: After onboarding, `nemoclaw genomeclaw exec --no-tty -- bash -c 'openclaw agent --local --json --agent genomeclaw --message "Smoke test. Call genomeclaw_status and report the active run id in one sentence."'` returns a JSON envelope with `status=ok`, ≥1 tool call (`genomeclaw_status`), and reply text that names the active run id. (Smoke test path; the script's final step.)
- [ ] **AC3**: The freshly-built sandbox image's baked `/sandbox/.openclaw/openclaw.json` contains, before any `nemoclaw exec` interaction:
  - `gateway.mode = "local"`
  - `plugins.allow` includes `"genomeclaw"`
  - `plugins.entries.genomeclaw.config.hostService.baseUrl = "http://host.openshell.internal:${GENOMECLAW_HOST_PORT}"` (build-arg substituted)
  - `plugins.entries.genomeclaw.config.hostService.timeoutMs = 30000`
  - `models.providers.openai.apiKey` is configured via `--ref-source env --ref-id OPENAI_API_KEY` (runtime-resolved reference, not a literal value).

  All four assertions live in a single `test_invP001_sandbox_baked_config_persistent_path` invariant test that loads the JSON out of the built image and walks the paths.
- [ ] **AC4**: The freshly-built sandbox image has `ENV HOME=/sandbox` (assertable via `docker inspect --format '{{json .Config.Env}}' genomeclaw/sandbox:port-${GENOMECLAW_HOST_PORT} | jq 'index("HOME=/sandbox")'`).
- [ ] **AC5**: `scripts/onboard-sandbox.sh` contains zero argv-interpolated secret patterns. Verified by a discovery test that greps the script for the rendered-shape pattern `python3 -c.*\$[A-Z_]*B64` and `--key.*\$[A-Z_]*KEY` and asserts no match. Auth-profile write must use stdin (`docker exec -i ... bash -c 'cat > .../auth-profiles.json' <<< "$json"`).
- [ ] **AC6**: `bin/genomeclaw host doctor` reports a *warning-level* finding when `~/.colima/default/colima.yaml` has `mounts: []` (or no `mounts:` block) AND `$GENOMECLAW_DERIVED_DIR` resolves to a path that is not a child of any colima-mounted host directory. The warning text names the failure mode ("the docker-wrapped host service will not see your derived directory") and the two fixes ("re-run `genomeclaw host setup`" OR "start the host service natively via `GENOMECLAW_NATIVE=1 bin/genomeclaw host service`"). Test fixture: monkeypatch `~/.colima/default/colima.yaml` to one of three shapes (empty mounts / populated-and-covers / populated-but-doesn't-cover) + assert the doctor's exit code and emitted JSON shape.
- [ ] **AC7**: The auth-profile written by the script is reachable from inside the deployed container at `/sandbox/.openclaw/agents/genomeclaw/agent/auth-profiles.json` AND its content parses as JSON with the expected shape (`profiles.openai/gpt-5.5.key` non-empty). Verified by a post-onboard `docker exec` test.

## Applicable Invariants

- **INV-P001** Privacy Is the Default Operating Mode — the script handles the operator's OpenAI API key (a credential that gates the agent's egress to OpenAI). Any onboarding code that mishandles secrets violates the requirement *"Secrets, tokens, and credentials live outside `data/` and are never committed."* The 2026-05-24 leak of the key into `docs/reports/demo-2026-05-24-logs/03-onboard-v2.log` was *technically* under `docs/` not `data/`, but the spirit of the rule is "credentials don't land in committable artifacts" — the report directory IS committed. This plan tightens the argv-vs-stdin discipline so the leak path closes structurally.
- **INV-P002** Agent Egress Is a Named, Minimal-Sufficient Boundary — onboarding configures the named egress destination (OpenAI provider). This plan does not widen the egress surface; it just makes the configuration step safer.
- **INV-D006** DooD-Safe Path Annotation — the host service / shim handling is shaped by colima mounts being correctly configured. AC6's host doctor check is the operator-side detection layer for the failure mode where colima mounts are missing and `bin/genomeclaw host service` silently can't see the derived dir.

## Proposed New Invariants

**NEW INV-P003 — Secrets Pass via stdin or env, Never via argv**

**Rule**: Any code that handles operator-supplied secrets (API keys, OAuth tokens, signed URLs containing credentials) must transport them into a subprocess via stdin (`cat > ... <<EOF`, heredoc, file descriptor) or via the subprocess's environment (`docker exec -e KEY=...`, `subprocess.run(..., env=...)`) — **never** as a positional or `--flag value` argv argument and **never** via shell interpolation into a string argument (`bash -c "cmd $SECRET ..."`).

**Rationale**: argv entries land in `ps`, in error tracebacks (Python's default traceback prints the entire `-c` source string), in container audit logs, and in any `tee` capture of stdout/stderr. The 2026-05-24 onboard-sandbox.sh leak (which leaked an OpenAI key into a committed report log via a Python `b64decode('<blob>')` traceback) is the canonical example. stdin and env-passed secrets are not visible in `ps` or in tracebacks of unrelated failures.

**Where it will apply**:
- `scripts/onboard-sandbox.sh` and any future onboarding/credential-rotation script.
- `packages/toolkit/src/` — any `subprocess.run` invocation that passes secrets to a child.
- `packages/nemoclaw-plugin/src/` — any spawned process or HTTP call that includes a secret.

**How to verify**:
- Static grep test against shell scripts in `scripts/` looking for `python3 -c.*\$.*B64`, `--key.*\$.*KEY`, `bash -c.*\$.*TOKEN`-style patterns. Discovery test runs against the whole repo; new violations fail loudly.
- For Python: a unit test that wraps `subprocess.Popen` and asserts no secret-shaped string (regex: `sk-(proj|live|test)-[A-Za-z0-9_-]{20,}`, `ghp_[A-Za-z0-9]{36}`, etc.) appears in the rendered argv.

This invariant could land in the appropriate section of `docs/reference/INVARIANTS.md` (category `INV-P`, next available number) after Phase 2's tests are green.

## Technical Requirements

### Source Data Inputs
- None. This plan touches build-time and host-side scripts only; no genomic data flows.

### Derived Outputs
- None for the pipeline layer. Outputs are: a built `genomeclaw/sandbox:port-${GENOMECLAW_HOST_PORT}` image, a registered `nemoclaw genomeclaw` sandbox, and updated doctor JSON.

### Schema / Migration Impact
- None.

### Pipeline / Workflow Impact
- `scripts/onboard-sandbox.sh` flow changes:
  - Pre-build step (already landed 2026-05-24) stays as-is.
  - All `nemoclaw genomeclaw exec --no-tty -- bash -c "openclaw config set ..."` steps for config that is now baked at image-build time (Phase 1) are deleted; the baked config makes them no-ops at best, and they fail under the openshell filesystem-restriction wrapper at worst.
  - Auth-profile write rewrites from `nemoclaw exec ... python3 -c "...$PROFILE_B64..."` to `docker exec -i --user sandbox <CID> bash -c 'mkdir -p ... && cat > .../auth-profiles.json'` reading the JSON from stdin.
  - Smoke test stays via `nemoclaw genomeclaw exec` (that path works for `openclaw agent --local` because agent calls don't read `/opt/genomeclaw` — they go over the gateway WebSocket which is already running).
- `bin/genomeclaw host doctor` adds one new check (colima-mounts-cover-derived-dir).

### Agent / UX Impact
- Operator sees `nemoclaw list` showing `genomeclaw` after one `./scripts/onboard-sandbox.sh` run, not after manual recovery steps.
- `bin/genomeclaw host doctor` now warns the operator if their colima setup will silently break the docker-wrapped host service.

### External Dependencies
- `nemoclaw onboard` (version that ships at the date of writing; the openshell sandbox wrapper's filesystem restriction is an upstream behavior we're working around, not changing).
- `docker exec` (already on PATH for every supported host).

## Privacy & Safety Considerations

- **Boundary scan**: the operator's OpenAI API key is the only secret touched by this work. It enters via `.env` (already on the operator's host), is read by the script via `source .env`, is written into the built container as the value of `auth-profiles.json :: profiles.openai/gpt-5.5.key`, and is passed at gateway-start time via `docker exec -e OPENAI_API_KEY=...`. Once the gateway is up, runtime `openclaw agent` calls do *not* re-pass the key — the gateway reads it once at startup and holds it in process memory.
- **Default-off remote calls**: no new remote calls introduced. The only egress this plan touches is the operator's existing opt-in to OpenAI for the agent.
- **Redaction surface**: the script must never emit the key value to stdout/stderr/logs. Phase 2's argv-elimination is the structural fix; Phase 2 also adds a `set +x` guard around any block that touches the key, in case `set -x` was enabled upstream.
- **Clinical escalation**: n/a — no findings or interpretations flow through this code.

## Out of Scope

- The two agent-side bugs surfaced in the 2026-05-24 demo:
  - `genomeclaw_pgs_compute` ack-without-row. Belongs in its own plan against the host service's PRS-task lifecycle (likely the `pgs_compute_tasks.sqlite` ↔ `pgs_scores` write race).
  - `genomeclaw_gene` argument-serialization bug on certain gene panels. Belongs in its own plan against the plugin's TypeBox parameter shapes.
- Re-staging a full Phase-6 annotated run as `derived/CURRENT`. Operator-side action.
- Changing `nemoclaw onboard` upstream to expose `--context`. Out of our control; the shim Dockerfile workaround (already landed) is sufficient.
- Changing openshell's sandboxing-wrapper behavior. Upstream-controlled; the workaround (use `docker exec` for config steps) is sufficient.
- Making `bin/genomeclaw host service` itself detect missing colima mounts and auto-fall-back to native uvicorn. Phase 3 of this plan only adds the *detection* in `host doctor`; the *automatic fallback* is a heavier lift (the shim's path-resolution logic would need to change), and a doctor warning is sufficient for the immediate need.

## Dependencies

- Existing `scripts/onboard-sandbox.sh` (already has the shim-Dockerfile fix from 2026-05-24).
- Existing `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` (`host doctor` lives here).
- Existing `packages/toolkit/tests/invariants/test_invP001_sandbox_web_egress_contract.py` as the template shape for AC3's baked-config gate test.

## Open Questions

- [ ] **Q1**: Should the auth-profile write happen in `scripts/onboard-sandbox.sh` (operator runs once, key lands in container's filesystem) or be deferred to a separate `scripts/configure-openai.sh` step the operator runs after onboard? The current spec assumes the former (matches DevRelClaw's pattern). The latter would make `onboard-sandbox.sh` secret-free which is a defense-in-depth win. **Lean: keep in `onboard-sandbox.sh` for ergonomic parity with DevRelClaw + because Phase 2's stdin-based write is structurally safe; revisit if the upstream `nemoclaw inference set --provider openai-api` path becomes usable on local Docker (currently broken — that's why the script writes the file directly).**
- [ ] **Q2**: Should `INV-P003` cover positive cases (test_xxx_uses_stdin) as well as negative cases (test_xxx_argv_has_no_secret_pattern)? Negative-only is easier to write but easier to silently regress (someone adds a new script, forgets the test). Discovery test that walks `scripts/` + asserts the no-argv-secret pattern across all matches gives positive coverage. **Lean: discovery + per-script negative test; the discovery test is the structural floor, per-script tests give better failure attribution.**
- [ ] **Q3**: Phase 3's host-doctor check needs a portable YAML parser. The toolkit already has `pyyaml` via transitive deps? Or should it pattern-match `mounts: \[\]` / `mounts:\s*$` with regex? **Lean: regex for the doctor (zero new deps; the failure-mode signatures are narrow enough), with the proviso that if colima ever changes the file format we revisit.**
