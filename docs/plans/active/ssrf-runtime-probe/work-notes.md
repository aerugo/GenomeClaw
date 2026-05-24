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
| 1 — Long-running harness + 5-tuple probe | Awaiting sign-off |
| 2 — Version pin + golden baseline | Awaiting Phase 1 |
| 3 — Docs | Awaiting Phases 1+2 |
