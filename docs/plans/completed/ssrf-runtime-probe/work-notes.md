# Work Notes — SSRF runtime probe

**Started**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## 2026-05-23 — Plan authored

**Context entry**: The spec landed during MVP Phase 7 close session 2 (2026-05-23) when the empirical finding emerged that the bare sandbox image has working public-internet network — the OpenShell L7 enforcement only fires when an allowlisted binary (openclaw or node) routes through the policy. A meaningful runtime probe therefore needs three things together: (1) the policy preset active, (2) an allowlisted-binary caller, (3) a way to issue multiple sequential probes without paying per-call container-boot overhead.

**Open questions answered before plan-authoring**:

- **Q1 — How does OpenShell expose a programmatic curl-via-gateway?**
  - **Probed**: `docker run --rm genomeclaw/sandbox:phase-6c openclaw --help` + `openclaw {proxy,gateway,exec-policy,security,sandbox,mcp,acp} --help`. No `openshell` CLI exists in the image (the L7 enforcement is built into openclaw's gateway path, not exposed as a standalone binary). `openclaw gateway call <method>` is an RPC surface against the WebSocket gateway — but its method set doesn't include a generic "egress probe" verb.
  - **Answer**: write a small Node script (Node is in the policy's `binaries:` allowlist alongside openclaw) that issues `fetch()` calls to each `(host, port, path)` tuple. The Node runtime exercises the policy's host/port/method/path matrix as the policy was designed to enforce — curl would get blocked at the binary-allowlist layer before the matrix ever fires.

- **Q2 — How does the existing live-smoke harness keep the container alive?**
  - **Probed**: read `packages/toolkit/tests/_live_smoke/run.py` end-to-end. The harness is strictly one-shot: `_build_in_container_script` starts gateway, runs `openclaw agent` once, kills gateway, exits. The container is `--rm` so it's gone after the script completes.
  - **Answer**: extend the harness with a `running_sandbox_container()` context manager that spawns the container with `sleep infinity`, starts the gateway via `docker exec`, holds the container open across multiple `docker exec`-issued probes, and tears down on context exit. Refactor the one-shot path to use the new context manager internally so the SHAPE is shared.

- **Q3 — OpenShell version pinning, INV-T001-style baseline?**
  - **Probed**: `openclaw --version` inside the sandbox image → `OpenClaw 2026.4.24 (cbcfdf6)`. The image tag already pins the binary version; what's NOT pinned is the rejection-message format the enforcer emits.
  - **Answer**: yes — Phase 2 introduces a thin `tools/openshell/probe-output.txt` golden baseline + an `OpenShellConventions.verified_against_version` dataclass. Phase 1 doesn't need it for the GREEN gate, but Phase 2 closes the drift-detection loop.

**Three-phase plan**:
1. Long-running sandbox harness + Node probe script + 5-tuple parameterized probe (no version pin yet).
2. OpenShell rejection-message golden baseline + version pin (INV-T001 style).
3. INVARIANTS.md v1.15 → v1.16 bump + reference doc updates.

**Applicable invariants**:
- INV-P001 (probe payloads are synthetic — no genomic content flows through the probe).
- INV-P002 (probe IS the explicit-runtime-negative-case evidence layer for the existing static-shape coverage).
- INV-T001 (Phase 2 baseline pins the rejection-message format against the OpenClaw version).

**Privacy posture**: probe payload bodies carry only the URL being tested. No genomic content. No secrets. The destinations exercised (`example.com`, `1.1.1.1`, `192.168.99.99`, off-allowlist ports on `host.openshell.internal`) MUST be rejected — if the test passes, no egress to those hosts actually happens. Privacy-safety-reviewer agent should review the Phase 1 diff before it lands.

**Expected wall-clock**: half-day for Phase 1 (harness extension + Node script + test fixture is the heaviest piece), ~1 hour for Phase 2, ~30 min for Phase 3.

### Sequencing relative to other active plans

- Independent of `coverage-qc-gene-list-bed` (different surface).
- Independent of `openclaw-toolcall-serialization-investigation` (that one is operator-blocked on Phase 2's cross-model bisect; this one is unblocked).

### Next step

Surface this plan to the user for sign-off. Phase 1 starts after sign-off — the harness extension touches a critical path (`run.py` is used by all 4 live LLM tests + the Phase 4 worker-self-sufficient-compute verification flow), so the user should weigh in on the refactor shape before code lands. Specifically the question of whether `run_agent_in_sandbox()` should be a thin wrapper around `running_sandbox_container()` (default: yes, per Decision 2 in development-plan.md) or whether the new context manager should sit alongside the existing one-shot path.

### Phase status

| Phase | Status |
|-------|--------|
| 1 — Long-running harness + 5-tuple probe | PARTIAL — harness GREEN, probe approach pivoted (design flaw discovered) |
| 2 — Version pin + golden baseline | Awaiting Phase 1 probe-approach pivot |
| 3 — Docs | Awaiting Phases 1+2 |

---

## 2026-05-24 — Phase 1 GREEN: harness works, probe design flaw discovered

Implemented Phase 1 per the plan: extracted `running_sandbox_container()` from the one-shot harness, shipped `probe_script.js` (Node), added `run_probe()`, registered `live_ssrf_probe` marker, wrote 5 parameterized probe tests + 4 harness unit tests.

**Harness pieces work end-to-end**:
- 4/4 harness unit tests PASS on bare host (no docker required): teardown-on-exception, readiness-timeout-raises, both-modes-coexist, module-exports.
- Live container lifecycle works: spawns sandbox in ~1s, openclaw gateway up + listening on `0.0.0.0:18789` in ~10s after a 5-iteration fix to the readiness probe (initial implementation polled `openclaw gateway status` which blocks ~5s per call doing a WebSocket connectivity probe; switched to `ss -lntp | grep openclaw-gatew` — note ss truncates process names to 15 chars, so the grep target is `openclaw-gatew` not `openclaw-gateway`).
- 5/5 probe tests fire correctly through the parameterized fixture, each `docker exec`s the Node script and gets a single-line JSON result back. The full 5-tuple sweep + container lifecycle is ~55s on a 2-CPU colima.

**Design flaw discovered during the live run**: the spec's Background already documented that "bare `docker exec curl` bypasses the policy entirely" — but I read this as a problem only for `curl` (not in the policy's binary allowlist), thinking that `node` (which IS in the allowlist) would be enforced. Empirically that assumption is wrong: **the OpenShell L7 policy only activates when openclaw routes the request through its proxy infrastructure**, regardless of which binary issues the request. A `docker exec <cid> node ...` runs under the container's PID namespace but outside the OpenShell enforcement context — the policy never fires.

Evidence:
- All 5 probe tuples returned `<fetch error: fetch failed>` with status=None. The probe classifier maps that to `deny_other`. None of the destinations was reachable, but none of the rejections carried an OpenShell-shaped body either — they were just plain network failures (DNS or connect-refused).
- Confirmed by probing `openclaw infer web fetch --url http://example.com/`: returns "Error: web.fetch is disabled or no provider is available." — no provider-mediated fetch path is wired in this image, ruling out an easy non-agent + non-docker-exec surface.
- `openclaw gateway call <method>` exposes only `health/status/system-presence/cron.*` — no built-in egress probe.

So the probe approach as designed cannot exercise the L7 enforcement. The harness extension itself is valuable infrastructure independent of the probe-design pivot — the long-running container fixture is reusable for other scenarios (e.g., the openclaw Phase 2 reproducer once an OpenAI key is back).

**What shipped**:
- `running_sandbox_container()` + `run_probe()` + `_build_openclaw_config_batch()` (shared with the one-shot path) in `tests/_live_smoke/run.py`.
- `probe_script.js` (Node) — kept; future paths X or Y can repurpose it.
- 4 harness unit tests in `tests/integration/test_live_smoke_harness.py` (all PASS on bare host).
- 5 probe tests in `tests/invariants/test_invP002_ssrf_runtime_probe.py` — marked `@pytest.mark.skip` with the design-flaw reason; the test file's module docstring explains the pivot.
- `live_ssrf_probe` marker registered; conftest auto-skip predicate added.

**Open question — pick the path forward**:

- **Path X (cheaper, paid)**: pivot to an agent-turn probe. Each tuple becomes one `openclaw agent --message "Try to fetch <url>; report the result verbatim."` invocation. The agent's tool-call layer routes egress through openclaw's proxy infrastructure, so the policy fires. Classify the rejection from the agent's tool-error trace. Cost: ~5 LLM calls per probe run ($1-5 depending on model). Risk: agent may not deterministically attempt the URL; reproducibility variance.

- **Path Y (heavier, free at runtime)**: build a custom probe plugin that registers an `egress_probe(url, method)` tool. Invoke via... actually, looking at the openclaw CLI surface there's no non-agent path to a plugin tool call. Even Path Y likely needs an agent turn — but the agent can call the tool 5 times in one turn deterministically, dropping the cost to 1 LLM call per probe run.

- **Path Z (give up the runtime probe)**: keep the static `INV-P002` shape tests + implicit-runtime coverage; document that the explicit-runtime layer requires harness work that exceeds its value. Lose the negative-case evidence but save the credit + time spend.

Recommendation: **Path Y with a single multi-call agent turn**. One LLM call per probe run × CI cost. Custom plugin is ~30 LOC TypeScript. Plan revision before implementation — surface the trade-offs to the user.

**Files changed**:
- `packages/toolkit/tests/_live_smoke/run.py` — MODIFIED (extracted `_build_openclaw_config_batch`, added `running_sandbox_container` + `run_probe`, refactored `_build_in_container_script` to share the config-batch helper).
- `packages/toolkit/tests/_live_smoke/probe_script.js` — CREATED (Node probe + classifier; kept for Phase 1 revision).
- `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` — CREATED (5 parameterized probe tests, skipped pending pivot).
- `packages/toolkit/tests/integration/test_live_smoke_harness.py` — CREATED (4 harness unit tests, all PASS).
- `packages/toolkit/tests/conftest.py` — MODIFIED (auto-skip predicate for `live_ssrf_probe` marker).
- `packages/toolkit/pyproject.toml` — MODIFIED (registered `live_ssrf_probe` marker).

---

## 2026-05-24 — Phase 1b: Path Y LANDED + GREEN

Implemented Path Y end-to-end. The probe-sweep pytest test passes against the real sandbox in ~98 s wall (1 OpenAI Responses call, ~$0.10-0.50 per run).

**Implementation arc** (five iterations through openclaw runtime bugs):

1. **v1 — TypeBox `Type.Array(Type.Object(...))` strip**: agent sent `{"probes":[{...},...]}` correctly (verified in `raw_params=...` gateway log), but `args.probes` arrived at `execute()` as `undefined`. OpenClaw's TypeBox validator silently drops array-of-object params between raw_params and the callback.
2. **v2 — defensive coercion**: `Array.from(Object.values(args.probes))` — but `args.probes` is `undefined`, so `Object.values(undefined)` throws. Same root issue, different symptom.
3. **v3 — `probesJson: string` workaround**: take the array as a JSON-encoded string and parse inside the tool. The string param arrived as the literal `"undefined"` — this is **Q-001** (agent-quirks.md) hitting the SSRF tool. OpenClaw's openai-responses path intermittently mangles tool-call args.
4. **v4 — `confirm: "run"` sentinel arg**: even a short string arg got corrupted to `undefined`. Q-001 isn't size-dependent.
5. **v6 — zero-arg tool** (`Type.Object({}, { additionalProperties: false })`, pattern from `genomeclaw_status`): immune to both bugs because there's no arg to corrupt. The probe set is **hardcoded** in the plugin TypeScript. ALL 5 PROBES PASSED.

**Empirical findings (worth their own openclaw issues)**:
- TypeBox `Type.Array(Type.Object(...))` is structurally broken in the openclaw runtime — probably the schema compiler doesn't handle nested object schemas in arrays. The other tools that use `Type.Array(Type.String(...))` work fine, so it's specific to array-of-object.
- Q-001 affects ANY string arg through the openai-responses path, not just long ones — even a 3-character `"run"` got mangled. Affects all openai-responses agent runs in a context-conditional way.

**Path Y final shape**:

- `packages/nemoclaw-plugin/src/index.ts`: optional `genomeclaw_ssrf_probe_batch` tool registered only when `GENOMECLAW_ENABLE_SSRF_PROBE=1`. Zero-arg surface. Hardcoded 5-tuple probe set inside the plugin TypeScript (must stay in lockstep with the pytest's `EXPECTED` dict). Each probe runs `fetch()` from inside the plugin's enforcement context, classifies the result, returns the array.
- `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py`: `@pytest.mark.live_ssrf_probe @pytest.mark.live_llm`-gated. Spawns sandbox with `sleep infinity`, `docker cp`s the freshly-built plugin (`packages/nemoclaw-plugin/dist/index.js`) over the baked-in one, chowns root:root (openclaw rejects non-sandbox-owned plugins), starts gateway via `docker exec`, invokes the agent with the zero-arg prompt, parses the fenced JSON code block from the agent's reply, asserts each `rejection_class` is in the per-tuple allow-set + the ALLOW probe actually returned HTTP 200 with a real `/v1/health` body.
- `packages/nemoclaw-plugin/dist/index.js`: rebuilt (`npm run build`).

**Test result (98 s wall, 1 LLM call)**:

```
PASSED [100%]
  allow_host_service_health: allow_ok  (HTTP 200, body status:ok schema_version:v0.2)
  deny_host_service_off_port: deny_other  (<fetch error: fetch failed>)
  deny_rfc1918_non_gateway: deny_other  (<fetch error: aborted>)
  deny_public_example_com: deny_other  (<fetch error: fetch failed>)
  deny_public_cloudflare_dns: deny_other  (<fetch error: fetch failed>)
```

**What this proves (and doesn't)**:

- **Proves**: the policy allows the configured host+port+path (HTTP 200 with real body proves the host service IS reachable from the plugin); un-allowlisted destinations are unreachable (all 4 deny probes fail at the network layer).
- **Does NOT prove**: which layer denies the un-allowlisted destinations. The body is `<fetch error: fetch failed>` for all deny probes — no OpenShell-shaped rejection message (e.g., `"blocked: internal address"`). The destination could be denied by OpenShell's L7 policy, OR by the sandbox container's DNS (which may not resolve `example.com`), OR by the lack of a route to `192.168.99.99`. The privacy invariant (un-allowlisted traffic doesn't escape) holds either way; the categorical evidence is weaker than spec AC3 wanted.

**Phase 2 scope** (still pending — recommend splitting into a follow-up plan):

- Sharpen the rejection-class classifier by capturing the actual OpenShell rejection body when one fires. Need to probe a destination that IS reachable AT NETWORK LAYER but BLOCKED BY POLICY (e.g., `host.openshell.internal:8643` with a non-allowlisted PATH like `/v1/raw-secrets` — the path matrix should fire and return a policy-shaped body).
- Pin OpenShell rejection-message format as `tools/openshell/probe-output.txt` golden baseline (INV-T001 style).
- Document the three coverage layers in INVARIANTS.md v1.16.

**Files changed (Phase 1b)**:
- `packages/nemoclaw-plugin/src/index.ts` — MODIFIED (added zero-arg `genomeclaw_ssrf_probe_batch` tool, env-gated)
- `packages/nemoclaw-plugin/dist/index.js` — REBUILT
- `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` — MODIFIED (replaced Phase 1 skipped tests with the Path Y live test)

### Phase status (updated)

| Phase | Status |
|-------|--------|
| 1 — Long-running harness + 5-tuple probe | COMPLETE (harness shipped 2026-05-24; probe approach pivoted to Path Y) |
| 1b — Path Y custom plugin + zero-arg sweep | COMPLETE (2026-05-24, 5/5 PASS) |
| 2 — Rejection-class classifier hardening + version pin + golden baseline | DEFERRED to follow-up plan (hardening, not on critical path) |
| 3 — INVARIANTS.md v1.16 docs | COMPLETE (2026-05-24) |

The core privacy-enforcement evidence is in place. Plan archived to `completed/`.

---

## 2026-05-24 — Plan closure

Per the user's review of the plan's stated purpose ("catch policy-enforcement regression at CI time so genomic data can't accidentally exfiltrate"), the Phase 1 + 1b 5/5 sweep already meets that bar:

- Policy stops enforcing entirely → ALLOW probe still works, DENY probes start succeeding (HTTP 200), test goes RED.
- Policy weakens to permit a previously-denied destination that IS network-reachable (`example.com:443`) → `rejection_class` flips `deny_other → allow_ok`, test goes RED.
- ALLOW path breaks → no HTTP 200 + body assertion fails, test goes RED.

Phase 2 (classifier sharpening + version pin + golden baseline) is defense-in-depth — it would catch regressions that LOOSEN the policy on destinations that remain network-unreachable (a narrow class). Not on the critical path. Deferred to a follow-up plan if/when desired.

Phase 3 closed by adding the three-layer coverage note to INVARIANTS.md v1.16 under INV-P002's "How to verify" section. The new test file is referenced under Layer 3.

Plan ready to archive to `completed/`.
