# Phase 1: Long-running harness + 5-tuple probe

**Status**: Pending (awaiting plan sign-off)
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Add an explicit-runtime-negative-case test for `INV-P002` that issues 5 `(host, port, method, path, expected)` probes from inside the running sandbox via the policy-allowlisted Node runtime, asserts each rejection_class matches its expected outcome, and runs in under 60 s total wall time (shares one container/gateway boot across all 5 probes).

## Scope Boundaries

- **In scope**:
  - Long-running sandbox harness (`running_sandbox_container()` context manager in `tests/_live_smoke/run.py`).
  - Node probe script + classifier (in-image, `docker exec`d for each tuple).
  - 5-tuple parameterized pytest test gated `@pytest.mark.live_ssrf_probe`.
  - Refactor the existing `run_agent_in_sandbox()` to use the new context manager internally — preserves all 4 live LLM tests' behavior.
  - 3 lightweight unit tests on the harness itself (context-exit teardown, gateway-readiness loop, docker-exec command shape).
- **Out of scope** (deferred to Phase 2):
  - OpenShell rejection-message golden baseline.
  - `OpenShellConventions` dataclass + version pin.
  - The cross-check assertion that the probe's 5-tuple set covers every endpoint in `policy-preset.yaml`.

## Invariants Enforced in This Phase

- **INV-P002** (Sandbox Egress Surface): each tuple asserts the policy denies (or allows) at runtime. The five tuples enumerated in spec AC2 cover the four denial classes: `deny_internal_address` (192.168.99.99), `deny_host_not_allowlisted` (example.com, 1.1.1.1), `deny_port_not_allowlisted` (host.openshell.internal:8644), plus one ALLOW positive (host.openshell.internal:8643 /v1/health) to confirm the probe distinguishes ALLOW from DENY rather than always-deny.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Probe test cases** (in `tests/invariants/test_invP002_ssrf_runtime_probe.py`, parameterized over the 5 tuples):

1. `test_invP002_runtime_probe_host_openshell_internal_8643_health_allowed` — ALLOW, must return `rejection_class="allow_ok"` + HTTP 200.
2. `test_invP002_runtime_probe_host_openshell_internal_8644_rejected` — DENY (port not in allowlist), must return `rejection_class="deny_port_not_allowlisted"` (or `deny_host_not_allowlisted` — see Implementation Notes).
3. `test_invP002_runtime_probe_rfc1918_192_168_99_99_rejected` — DENY (un-allowlisted RFC 1918 even though range is in `allowed_ips`; the host is not the configured endpoint), must classify as `deny_host_not_allowlisted`.
4. `test_invP002_runtime_probe_example_com_443_rejected` — DENY (public internet, non-allowlisted host), must classify as `deny_host_not_allowlisted`.
5. `test_invP002_runtime_probe_1_1_1_1_53_rejected` — DENY (public internet, non-allowlisted host + port), must classify as `deny_host_not_allowlisted` (or `deny_internal_address` depending on which guard fires first — empirically determined Phase 1.1).

**Harness unit-test cases** (in `tests/integration/test_live_smoke_harness.py`):

6. `test_running_sandbox_container_teardown_on_exception` — RAISE inside the context; container MUST be `docker rm -f`'d on exit.
7. `test_running_sandbox_container_gateway_readiness_loop_times_out` — patch `openclaw gateway status` to never report ready; the harness must raise `RuntimeError` after the configured deadline.
8. `test_run_agent_in_sandbox_uses_new_context_manager` — refactor regression: the one-shot path goes through the new context manager (mock + assert call sequence).

**Sketch — the probe-script call surface (Node)**:

```text
docker exec <cid> node /opt/probe_script.js \
  --host example.com --port 443 --method GET --path /
→ stdout: {"status": null, "body_excerpt": "ssrf_denied: blocked: host not in policy",
            "rejection_class": "deny_host_not_allowlisted",
            "openclaw_version": "2026.4.24 (cbcfdf6)"}
```

**Sketch — the pytest fixture**:

```python
@pytest.fixture(scope="module")
def sandbox_with_gateway(sandbox_image_env):
    with running_sandbox_container(
        sandbox_image=sandbox_image_env, host_port=DEFAULT_HOST_PORT,
    ) as cid:
        yield cid

@pytest.mark.live_ssrf_probe
@pytest.mark.parametrize(
    "host,port,method,path,expected_class",
    PROBE_TUPLES,
    ids=[t.id for t in PROBE_TUPLES],
)
def test_invP002_runtime_probe_tuple(
    sandbox_with_gateway, host, port, method, path, expected_class,
):
    """INV-P002: <tuple description>."""
    result = run_probe(
        sandbox_with_gateway, host=host, port=port, method=method, path=path,
    )
    assert result["rejection_class"] == expected_class, (
        f"Expected {expected_class}, got {result['rejection_class']}; "
        f"body excerpt: {result['body_excerpt'][:200]}"
    )
```

After writing these 8 tests, run them. Tests 1-5 will fail because the new code path doesn't exist yet (no `running_sandbox_container`, no `probe_script.js`, no `run_probe` helper, no `live_ssrf_probe` marker — pytest will emit `PytestUnknownMarkWarning` + collection errors). Tests 6-8 will fail because `running_sandbox_container` does not exist yet. Paste the RED output into `work-notes.md`.

### Step 1.2 — GREEN: Minimal Implementation

**Files affected**:
- `packages/toolkit/tests/_live_smoke/run.py` — MODIFY: extract a `running_sandbox_container()` context manager; refactor `run_agent_in_sandbox()` to call it.
- `packages/toolkit/tests/_live_smoke/probe_script.js` — CREATE: the Node script + classifier.
- `packages/toolkit/tests/_live_smoke/__init__.py` — MODIFY: export `running_sandbox_container` + `run_probe` helpers.
- `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` — CREATE: parameterized probe test.
- `packages/toolkit/tests/integration/test_live_smoke_harness.py` — CREATE: 3 harness unit tests.
- `packages/toolkit/pyproject.toml` — MODIFY: register `live_ssrf_probe` marker; add the env-var skip predicate to `conftest.py`.
- `packages/toolkit/tests/conftest.py` — MODIFY: auto-skip `live_ssrf_probe` tests when `GENOMECLAW_HAS_DOCKER != "1"` OR the sandbox-image env var is unset.

**Implementation notes**:

- The Node probe script's classifier reads the response (or the thrown error from `fetch()`) and maps it to one of: `allow_ok`, `deny_internal_address`, `deny_host_not_allowlisted`, `deny_port_not_allowlisted`, `deny_path_not_allowlisted`, `deny_other`. The mapping is body-fragment-based for now (e.g., `"blocked: internal address"` → `deny_internal_address`); Phase 2 promotes these fragments to the golden baseline.
- `running_sandbox_container()` spawns with `docker run -d --rm --add-host=host.openshell.internal:host-gateway --name <unique> <image> sleep infinity`, then `docker exec <name> bash -c "openclaw config set --batch-file ... && openclaw gateway run >/tmp/gateway.log 2>&1 &"`, then polls `openclaw gateway status` for readiness (10 s deadline; same loop as the one-shot path).
- `run_probe(cid, host, port, method, path)` is a thin wrapper: `docker exec <cid> node /opt/probe_script.js --host ... --port ... --method ... --path ...` + parse the single-line JSON stdout.

### Step 1.3 — REFACTOR

With tests green:

- Extract the gateway-config-batch construction (currently duplicated between one-shot script and new context manager) into a `_build_openclaw_config_batch(host_port)` helper. Confirmed duplication = rule-of-three trigger.
- Tighten types on `running_sandbox_container()` — `Iterator[str]` for the container ID; explicit `RuntimeError` for boot failures with clear messages.
- Add ONE comment to `probe_script.js` explaining the `rejection_class` mapping comes from empirical Phase 1.1 probes (since the OpenShell rejection-message format is undocumented).

---

## Implementation Details

### Edge Cases to Handle

- **Gateway boot timeout**: 10 s deadline matches the one-shot path. On timeout, dump `/tmp/gateway.log` from the container into the test error message so failures are debuggable.
- **`docker exec` exits non-zero before producing JSON**: probe-script wraps everything in try/catch, always emits one-line JSON to stdout (with `error` field), exits 0. The pytest helper distinguishes "probe ran but rejected" (rc=0, classified) from "probe failed to run" (rc≠0 OR JSON parse failure).
- **Container leak on test crash**: the `running_sandbox_container()` context manager always runs `docker rm -f <name>` in its `finally` block. Unit test 6 confirms this even on RAISE inside the `with` block.
- **Port collision**: the host service starts on `DEFAULT_HOST_PORT=8643`. If a stale container is bound to that port, fail early with a clear error pointing at `docker ps` + the `docker rm -f` resolution.

### Error Handling

- Probe script's `fetch()` throws on connection-refused / DNS-failure / 403 / etc. — caught + classified.
- If a tuple's actual `rejection_class` doesn't match any of the known mapping rules, classify as `deny_other` + include the raw body excerpt in the JSON output. Test fails with the excerpt visible so the operator can extend the classifier.

### Privacy / Egress Notes

- The probe payloads are URL-only (no body). No genomic content, no secrets.
- The 5 destinations probed are public/synthetic: `host.openshell.internal:8643/v1/health` (the host service, allowed), `host.openshell.internal:8644/*` (off-port), `192.168.99.99:80` (RFC 1918 dummy IP, not the gateway), `example.com:443`, `1.1.1.1:53`. None resolves to a real third-party service in a way the probe could leak data to — `example.com` is IANA-reserved; `1.1.1.1:53` is Cloudflare DNS but the probe issues a GET (not a DNS query) so the connection should be refused at HTTP layer if anything reached it.
- The whole point: assert these calls are REJECTED. If they ARE rejected, no egress happens. If the test ever flips to PASS-without-rejection (i.e., the destination IS reachable), that's a privacy-invariant violation and the test screams.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/_live_smoke/run.py` | MODIFY | Extract `running_sandbox_container()` context manager; refactor one-shot path to use it. |
| `packages/toolkit/tests/_live_smoke/probe_script.js` | CREATE | Node script issuing `fetch()` + classifying rejection_class. |
| `packages/toolkit/tests/_live_smoke/__init__.py` | MODIFY | Export new symbols. |
| `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` | CREATE | 5-tuple parameterized probe. |
| `packages/toolkit/tests/integration/test_live_smoke_harness.py` | CREATE | 3 harness unit tests (teardown, readiness timeout, refactor regression). |
| `packages/toolkit/pyproject.toml` | MODIFY | Register `live_ssrf_probe` marker. |
| `packages/toolkit/tests/conftest.py` | MODIFY | Auto-skip predicate for the new marker. |

---

## Verification

```bash
# Run just this phase's tests (host — should auto-skip; only the harness unit tests run)
packages/toolkit/.venv/bin/python -m pytest \
  packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py \
  packages/toolkit/tests/integration/test_live_smoke_harness.py -v

# Run them inside the toolkit image with docker + sandbox image available
docker run --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /Users/hugi/GitRepos/GenomeClaw:/repo \
  -w /repo/packages/toolkit \
  -e GENOMECLAW_HAS_DOCKER=1 \
  -e GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-6c \
  genomeclaw/toolkit:worker-self-sufficient \
  python -m pytest tests/invariants/test_invP002_ssrf_runtime_probe.py -v

# Run the full toolkit suite + confirm no regressions in the 4 live LLM tests
packages/toolkit/.venv/bin/python -m pytest packages/toolkit/tests/ --no-header -q

# Lint + type
packages/toolkit/.venv/bin/python -m ruff check packages/toolkit/tests/_live_smoke/
packages/toolkit/.venv/bin/python -m mypy packages/toolkit/tests/_live_smoke/
```

---

## Completion Criteria

- [ ] All 5 probe tests pass when run with `GENOMECLAW_HAS_DOCKER=1` + sandbox-image env var set.
- [ ] All 3 harness unit tests pass on bare host (no docker required).
- [ ] Auto-skip works on bare host (no docker / no sandbox image).
- [ ] Full toolkit suite: no regressions in the 4 live LLM tests after the `run_agent_in_sandbox()` refactor (run with `GENOMECLAW_HAS_DOCKER=1` + `OPENAI_API_KEY` set; or document why they were not run if budget-constrained).
- [ ] `ruff` + `mypy` clean on the new + modified files.
- [ ] `INV-P002` is the cited invariant in each probe test's docstring.
- [ ] No raw genomic data, secrets, or sample IDs added.
- [ ] `work-notes.md` updated with RED output (collection errors / failure messages), GREEN summary (which file made which test pass), REFACTOR notes (what was extracted, what was tightened).
- [ ] Phase 1 status updated in `development-plan.md`.
- [ ] **Privacy-safety-reviewer agent invoked** on the Phase 1 diff before commit — INV-P002 plan.
