# SSRF runtime probe — Development Plan

**Status**: Draft (authored 2026-05-23; awaiting sign-off)
**Created**: 2026-05-23
**Branch**: `feature/ssrf-runtime-probe`
**Spec**: [spec.md](spec.md)

---

## Summary

Add a runtime negative-case probe that issues outbound HTTP requests from inside the running sandbox via the OpenShell-allowlisted Node runtime, asserting the policy preset rejects every un-allowlisted `(host, port, method, path)` tuple. Closes the gap between the static policy-preset shape (already covered by `INV-P002` shape tests) and the implicit "no agent test ever tried to go off-policy" coverage.

## Critical Invariants to Respect

- **INV-P001** Privacy Is the Default Operating Mode — the probe's purpose IS to verify privacy enforcement. The probe itself uses synthetic destinations (`example.com`, `1.1.1.1`, RFC 1918 dummies); no genomic payload ever leaves the host.
- **INV-P002** Sandbox Egress Surface — this plan promotes the empirical evidence for INV-P002 from "static shape" + "implicit runtime via 4 live LLM tests" to "explicit runtime negative-case probe per ALLOW/REJECT tuple". The probe is gated `@pytest.mark.live_ssrf_probe` (a new marker) and runs in CI only when the sandbox image + docker are available.
- **INV-T001** Tool-Contract Conventions — OpenShell's rejection-message shape (HTTP code + body fragment) is a contract surface. If the policy enforcer's rejection shape changes (e.g. body string `"blocked: internal address"` becomes `"denied: rfc1918"`), the probe should fail with a typed assertion, not pass silently. Phase 2 introduces a thin OpenShell version pin + golden rejection-message baseline.

## Proposed New Invariants

**None.** The plan strengthens the empirical surface for `INV-P002`; it does not introduce a new project-wide rule.

## Current State Analysis

### What exists today
- `packages/nemoclaw-plugin/policy-preset.yaml` declares the policy: one allowed `(host, port)` = `(host.openshell.internal, 8643)`, six allowed GET paths + one POST (`/v1/pgs/compute`), binary allowlist = `openclaw` + `node`, allowed-IPs covers RFC 1918.
- `packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py` (6 tests) verifies the YAML shape — no IP outside RFC 1918 + the single endpoint host/port + the six read paths + the one POST.
- `packages/toolkit/tests/_live_smoke/run.py` orchestrates one-shot agent turns: start host service → `docker run --rm` sandbox → in-container script starts gateway, runs agent, tears down → extract sentinelled JSON. **The container exits after every turn.**
- The 4 live LLM tests under `tests/_live_smoke/` exercise the agent through the gateway against the host service, so the policy is implicitly enforced on every call — but no test issues an un-allowlisted call to confirm a denial happens.

### What's missing
- An explicit assertion that a `(host=example.com, port=443, ...)` call from a binary IN the allowlist (node) gets denied. The current 4-test surface only ever calls allowed paths.
- A long-running harness so multiple probes share one container/gateway lifetime (each `docker run` is 10–15 s of openclaw boot + gateway start).
- A pinned OpenShell rejection-message baseline so the probe surfaces drift as a typed failure, not as a silent pass when the rejection string changes.

### Files to Modify

| File | Current State | Planned Changes |
|------|---------------|-----------------|
| `packages/toolkit/tests/_live_smoke/run.py` | One-shot `run_agent_in_sandbox()` orchestrator | Add `running_sandbox_container()` context manager: spawn container with `sleep infinity`, start gateway via `docker exec`, hold open, tear down on exit. The existing one-shot path stays as a thin wrapper around the new context manager. |
| `pyproject.toml` (toolkit) | Has `needs_bio`, `live_llm`, `needs_phase5_smoke_artifacts`, etc. markers | Add `live_ssrf_probe` marker (gated on `GENOMECLAW_HAS_DOCKER=1` + sandbox image env var). |
| `docs/reference/INVARIANTS.md` v1.15 | INV-P002 lists static + implicit-runtime coverage | Bump to v1.16; add the runtime probe as the third evidence layer under "How to verify". No new IDs. |

### Files to Create

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` | The probe itself. Parameterized over 5 `(host, port, method, path, expected)` tuples per AC2. |
| `packages/toolkit/tests/_live_smoke/probe_script.js` (or inlined) | Node script that issues `fetch()` against `(host, port, path)` and prints a JSON result blob (`{status, body_excerpt, rejection_class}`). Node is in the binary allowlist; the script is `docker exec`d. |
| `tools/openshell/probe-output.txt` (Phase 2) | Golden baseline for OpenShell's rejection shape: HTTP status + body fragment for `(internal address blocked)`, `(host not allowlisted)`, `(path not allowlisted)`. Pinned against `OpenClaw 2026.4.24 (cbcfdf6)`. |

## Solution Design

The probe issues outbound HTTP from inside the sandbox using the Node runtime (which IS allowlisted at the binary layer), exercising the host/port/method/path matrix of the policy. The probe is run via a `docker exec` against a long-running container that the test fixture spawns once and reuses for all 5 tuples.

```text
                                Host (pytest)
                                       │
                                       │ ① docker run --rm -d ... sleep infinity
                                       │    (container starts; gateway not yet)
                                       ▼
                              ┌─────────────────────┐
                              │  Sandbox container  │
                              │  (policy enforced)  │
                              │                     │
       ② docker exec ─────────│  openclaw gateway   │  ◄── stays alive
          openclaw config set │  run &              │      across all 5
          + gateway run       │                     │      probes
                              │                     │
       ③ for each (h,p,m,P,E):│                     │
         docker exec ─────────│  node probe_script  │
                              │       .js h:p m P   │
                              │           │         │
                              │           ▼         │
                              │  OpenShell policy   │
                              │  enforces ALLOW/    │
                              │  REJECT             │
                              │           │         │
                              │           ▼         │
                              │  Returns JSON       │
                              │  {status, body,     │
                              │   rejection_class}  │
                              │                     │
       ④ docker rm -f ────────│                     │
                              └─────────────────────┘
```

The `run.py` extension exposes:

```python
@contextmanager
def running_sandbox_container(
    *,
    sandbox_image: str,
    host_port: int = DEFAULT_HOST_PORT,
    openclaw_extra_config: list[dict] | None = None,
) -> Iterator[str]:
    """Spawn the sandbox container + start the gateway inside it; yield
    the container ID. Caller can `docker exec <id> ...` to issue probes.
    Cleanup runs unconditionally on context exit."""
```

The one-shot `run_agent_in_sandbox()` is refactored to use this context manager internally (one container/gateway boot per turn, but the SHAPE is shared with the new probe surface).

### Key Design Decisions

1. **Probe via Node, not curl**: `curl` is NOT in the policy's binary allowlist, so a probe via curl would get blocked at the binary layer — never reaching the host/port/method/path enforcement. Using Node (which IS allowlisted) exercises the matrix the policy is designed to enforce. Tests the right surface.

2. **Long-running container with `sleep infinity` + `docker exec`**: 10–15 s of gateway boot per `docker run` × 5 probes = ~75 s pure overhead. One container shared across probes = ~15 s overhead + ~1 s per probe. Big test-runtime savings. The container lifetime is bounded by the pytest fixture's context manager so leaks can't happen.

3. **Probe is `@pytest.mark.live_ssrf_probe`-gated** (new marker), gated on `GENOMECLAW_HAS_DOCKER=1` + a sandbox image env var. Mirrors the existing `live_llm` / `needs_bio` pattern; auto-skips on bare hosts. Toolkit-image CI job opts in by setting the env var.

4. **Rejection-class classification, not just `status_code != 200`**: each probe result is classified into one of `{allow_ok, deny_internal_address, deny_host_not_allowlisted, deny_port_not_allowlisted, deny_path_not_allowlisted, deny_other}`. The classification logic lives in the probe script (Node) — not in pytest — so the classification stays close to the rejection-source format. Tests assert classification matches the tuple's expected outcome.

5. **Golden rejection-message baseline pinned to OpenClaw version** (Phase 2): an INV-T001-style `tools/openshell/probe-output.txt` baseline file captures the body fragment for each rejection class (e.g., `"ssrf_denied: blocked: internal address"`). A test asserts `OpenClawConventions.verified_against_version == "2026.4.24"` matches the actual openclaw `--version` output captured at probe time. Drift in either direction = typed failure.

6. **No agent involvement**: the probe avoids any agent turn. Agent runs cost LLM credits; this probe runs the gateway + Node only. Reproducible, fast, cheap.

### Schema / Provenance Impact

- No schema changes. No derived-store changes. The probe is read-only from outside the sandbox.

### Privacy & Egress Impact

- The probe explicitly attempts un-allowlisted egress destinations (`example.com:443`, `1.1.1.1:53`). These attempts MUST be rejected by the policy under test; if the test passes, no egress to those hosts actually happened. If the test fails (i.e. an attempt succeeds), the policy is broken and the probe surfaces it loudly.
- The probe payload bodies carry only the URL being tested — no genomic content, no secrets. Synthetic prompt = synthetic egress attempt.
- New marker `live_ssrf_probe` is gated; bare-host runs auto-skip.
- The `privacy-safety-reviewer` agent should review the diff before Phase 2 ships — the plan is directly INV-P002-adjacent.

## Phase Overview

| Phase | Description | TDD Focus | Est. Tests |
|-------|-------------|-----------|------------|
| 1 | Long-running sandbox harness + probe script + 5-tuple parameterized probe (no version pin yet) | RED: 5-tuple probe + harness; GREEN: minimal implementation; REFACTOR: extract `running_sandbox_container` shape | 5 probe assertions + ~3 harness unit tests |
| 2 | OpenShell rejection-message golden baseline + version pin (INV-T001 style) | RED: probe-output.txt baseline + version-pin assertion; GREEN: write the baseline; REFACTOR: extract `OpenClawConventions` dataclass | +2 (baseline-match + version-pin) |
| 3 | INVARIANTS.md v1.15 → v1.16 bump + docs | None (docs only) | 0 |

## Phase 1: Long-running harness + 5-tuple probe

**Goal**: A `@pytest.mark.live_ssrf_probe`-gated test that spawns the sandbox once, exercises 5 `(host, port, method, path, expected)` tuples through OpenShell's enforcement layer, and asserts each result's `rejection_class` matches its expected outcome.

**Detailed Plan**: [phases/phase-1.md](phases/phase-1.md)

### Deliverables
1. `packages/toolkit/tests/_live_smoke/run.py` extended with `running_sandbox_container()` context manager.
2. `packages/toolkit/tests/_live_smoke/probe_script.js` Node script that issues fetch + reports classified result.
3. `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` — 5-tuple parameterized probe.
4. `pyproject.toml` updated with `live_ssrf_probe` marker.

### Invariants Enforced Here
- **INV-P002**: each tuple asserts the policy's enforcement at runtime; the test as a whole is the explicit-runtime-negative-case layer the spec calls for.

### Success Criteria
- [ ] All 5 tuples pass when run inside the toolkit image with sandbox image env var set.
- [ ] Test auto-skips on bare hosts without docker / sandbox image.
- [ ] Harness teardown runs even when probes fail (no zombie containers).
- [ ] Test runtime ≤ 60 s for the full 5-tuple sweep.

## Phase 2: OpenShell version pin + golden baseline

**Goal**: Pin OpenClaw version + capture rejection-message shape so silent enforcement drift surfaces as a typed test failure.

### Deliverables
1. `tools/openshell/probe-output.txt` — golden baseline of the 3 rejection classes' body fragments + the openclaw `--version` line.
2. `packages/toolkit/src/genomeclaw_toolkit/_versions.py` — add `OPENCLAW_VERSION = "2026.4.24"` (or equivalent surface). Alternatively, a small `OpenShellConventions` dataclass in `tests/_live_smoke/` if we don't want to promote it to `_versions`.
3. `tests/invariants/test_invT001_openclaw_conventions.py` — pins `OpenShellConventions.verified_against_version` against `_versions.OPENCLAW_VERSION` and re-runs the probe-output classification against `probe-output.txt`.

### Invariants Enforced Here
- **INV-T001**: extends the tool-contract discipline to OpenShell. New entry in the INV-T001 wrapper table.

### Success Criteria
- [ ] Version-pin assertion + probe-output match.
- [ ] Bumping the OpenClaw image tag without bumping `_versions.OPENCLAW_VERSION` produces a typed failure with a clear pointer to the baseline file.

## Phase 3: Docs

**Goal**: Document the new runtime-probe coverage layer in `INVARIANTS.md` + add a section to `docs/reference/architecture.md` (or similar) noting the three coverage layers (static / implicit / explicit-runtime).

### Deliverables
1. `docs/reference/INVARIANTS.md` v1.15 → v1.16 with the runtime-probe coverage note under INV-P002 + INV-T001.
2. Architecture-reference doc update (1 short paragraph).

### Success Criteria
- [ ] INV-P002's "How to verify" section lists all three layers.
- [ ] INV-T001's wrapper table includes OpenShell.

---

## Testing Strategy

### Invariant Tests
- `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py`: 5-tuple parameterized runtime probe. Each tuple's `rejection_class` must match its expected outcome.
- `packages/toolkit/tests/invariants/test_invT001_openclaw_conventions.py` (Phase 2): version-pin + probe-output match.

### Privacy-Default Tests
- The whole probe is one giant privacy-default test: assert un-allowlisted destinations remain unreachable from inside the sandbox.

### No New Unit / Integration / Provenance / Determinism / Report / Evidence Tests
- The plan is pure runtime verification of policy enforcement — no schemas, no derived stores, no user-facing outputs change.

---

## Documentation Updates

After implementation is complete:

- [ ] [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) — bump to v1.16 with the runtime probe noted under INV-P002 + INV-T001 wrapper-table entry for OpenShell.
- [ ] `docs/reference/architecture.md` — add a short note on the three-layer sandbox-egress coverage (static / implicit / explicit-runtime).
- [ ] `packages/nemoclaw-plugin/policy-preset.yaml` — header comment updated to point at the new runtime probe.

---

## Progress Tracking

| Phase | Status | Started | Completed | Notes |
|-------|--------|---------|-----------|-------|
| 1 — Long-running harness + 5-tuple probe | Pending | | | ~half-day. Hardest part is the Node probe-script classifier. |
| 2 — Version pin + golden baseline | Pending | | | ~1 hour. Trivial after Phase 1 is green. |
| 3 — Docs | Pending | | | ~30 min. |

---

## Open Risks & Follow-ups

- **OpenShell rejection-shape drift across image rebuilds**: mitigated by Phase 2's golden baseline + version pin.
- **`docker exec` from the test running inside the toolkit image (CI scenario)**: requires docker-out-of-docker. The `host service` shim path already uses DooD, so this is solved at infrastructure layer — but the probe test needs to inherit the same env var (`GENOMECLAW_HOST_ROOTS`) for path consistency. Phase 1's harness work should mirror the shim's DooD setup.
- **Future expansion**: a kernel-isolation probe (Landlock + seccomp + netns) is explicitly out of scope per spec AC4 — that's a separate later plan.
- **policy-preset evolution**: if `policy-preset.yaml` grows (e.g. bulk-mode endpoints added per spec note on INV-P002), the probe's 5-tuple set MUST be updated in lockstep — otherwise the probe goes stale and silently passes against weakened enforcement. Add a test to `test_invP002_policy_preset_shape.py` that asserts the probe's tuple set covers every allowed (host, port) combo in the YAML.
