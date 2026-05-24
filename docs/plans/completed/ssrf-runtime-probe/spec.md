# Spec — SSRF runtime probe (post-MVP)

**Status**: Active — development plan drafted 2026-05-23 ([development-plan.md](development-plan.md))
**Created**: 2026-05-23 during MVP Phase 7 close session 2
**Trigger**: Phase 7 close-out deferred the runtime SSRF probe after empirical findings (see Background).

---

## Goal

Verify at runtime that OpenShell's L7 proxy + the GenomeClaw policy preset together reject un-allowlisted egress destinations from inside the sandbox. The static policy-preset shape is already covered by `tests/invariants/test_invP002_policy_preset_shape.py` (6 tests); the runtime enforcement is implicitly verified by the 4 live LLM tests but not asserted negatively.

## Background

Phase 7 close session 2 (2026-05-23) empirically established:

- The bare sandbox image (`genomeclaw/sandbox:slice-d-prime`) has working public-internet network (`curl https://1.1.1.1` returns 301 from inside `docker run`). **The OpenShell L7 enforcement only fires when OpenClaw routes a request through its gateway** — bare `docker exec curl` bypasses the policy entirely.
- A meaningful runtime SSRF probe therefore needs OpenClaw running with the policy preset active inside the sandbox container, AND a way to exec curl-equivalent calls through OpenClaw's gateway path.
- The existing `tests/_live_smoke/run.py` orchestrator already spins up the full sandbox + openclaw + policy stack, but it tears down after a single agent turn. The SSRF probe needs the harness to stay open across multiple curl-equivalent attempts.

This is non-trivial harness work — a meaningful piece of work in its own right that doesn't fit inside a Phase-7 close session's budget. Phase 7 ships with the static + implicit-runtime coverage; this plan picks up the explicit runtime negative-case probe.

## Acceptance Criteria

- [ ] **AC1**: A new long-running sandbox harness function (likely an extension of `tests/_live_smoke/run.py`) that starts the sandbox container with OpenShell + the policy preset active + holds it open for multiple sequential probes.
- [ ] **AC2**: A parameterized runtime probe test that enumerates `(host, port, expected-outcome)` tuples + invokes a curl-via-OpenShell-gateway path against each. Initial tuple set:
  - `host.openshell.internal:8643` (the host service) → ALLOW
  - `host.openshell.internal:8644` (un-allowlisted port) → REJECT
  - `192.168.99.99:80` (un-allowlisted RFC 1918) → REJECT
  - `example.com:443` (public internet, non-allowlisted) → REJECT
  - `1.1.1.1:53` (public internet, non-allowlisted) → REJECT
- [ ] **AC3**: The probe surfaces OpenShell's actual rejection signal (whether that's a 403 from the L7 proxy, a connection-refused at the netns layer, or a different rejection class). Document the observed shape.
- [ ] **AC4**: Document that the full Landlock + seccomp + netns kernel-isolation probe remains a separate further-out follow-up. This plan scope's the OpenShell L7 + policy-preset surface, not the kernel surface.

## Applicable Invariants

- **INV-P002** (Sandbox Egress Surface) — extends the enforcement evidence from "static shape" + "implicit runtime" to "explicit runtime negative case".

## Proposed New Invariants

None.

## Open Questions

**Resolved during plan-authoring (2026-05-23).** Detailed answers in [work-notes.md § 2026-05-23 Plan authored](work-notes.md).

1. ~~**How does OpenShell expose a programmatic curl-via-gateway**?~~ → No `openshell` CLI exists; L7 enforcement is built into the OpenClaw gateway. Probe via a Node script (Node is in the policy's binary allowlist alongside openclaw) `docker exec`d into the running container. Curl is NOT in the allowlist so a curl-based probe would get blocked at the binary layer before the host/port matrix ever fires.
2. ~~**How does the existing live-smoke harness's container stay alive between turns?**~~ → It doesn't (it's strictly one-shot). Phase 1 of the development plan adds a `running_sandbox_container()` context manager that spawns with `sleep infinity` and starts the gateway via `docker exec`.
3. ~~**OpenShell version pinning**?~~ → Yes, the rejection-message FORMAT (not just the openclaw binary version) needs pinning. Phase 2 of the plan introduces `tools/openshell/probe-output.txt` golden baseline + an `OpenShellConventions` dataclass with `verified_against_version="2026.4.24"`. Phase 1 doesn't need it; Phase 2 closes the drift-detection loop.

## Out of Scope

- Full Landlock + seccomp + netns kernel-isolation probing (separate further-out plan).
- Extending the policy preset itself — this plan verifies the current preset enforces correctly; it doesn't add new allow/deny entries.
- Verifying the host service's own behavior under SSRF-class requests (e.g. malicious URL params); that's a host-service hardening concern, not a runtime-probe concern.

## Files Likely Touched

- `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` — NEW (the probe itself)
- `packages/toolkit/tests/_live_smoke/run.py` — extended for the long-running harness mode (or a sibling helper)
- Possibly a new `tools/openshell/` directory for OpenShell version pinning if AC4's question lands on "yes pin it"
- `docs/reference/INVARIANTS.md` — v1.15 → v1.16 with the runtime-probe coverage note (no new IDs)
