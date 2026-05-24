"""INV-P002 explicit-runtime-negative-case probe.

**Status (2026-05-24): Phase 1 design flaw discovered — see work-notes.md.**

The original plan was to issue outbound HTTP from inside the sandbox via
the policy-allowlisted Node runtime (Node is in the policy's
``binaries:`` allowlist alongside openclaw) and assert OpenShell L7
denies un-allowlisted ``(host, port, method, path)`` tuples.

Empirical finding during Phase 1 GREEN: **docker-exec'd processes
bypass OpenShell enforcement entirely** — same mechanism the spec's
Background already documented for ``docker exec curl``. The policy
only activates when openclaw routes the request through its proxy
infrastructure (plugin tool calls during an agent turn). A direct
``docker exec node`` is outside the OpenShell enforcement context, so
no policy fires and the probe just sees plain network behaviour
(unreachable destinations look identical to policy-denied ones).

The probe code + harness extension (``running_sandbox_container`` +
``probe_script.js``) shipped because the harness is reusable
infrastructure independent of the probe-design pivot. The five tuple
tests are marked ``@pytest.mark.skip`` with the design-flaw reason
until the plan is revised. Two candidate paths are documented in
``work-notes.md``:

- **Path X (paid)**: pivot to an agent-turn-based probe; each tuple
  becomes one ``openclaw agent`` invocation that calls an
  ``egress_probe`` tool, classified from the trace.
- **Path Y (heavier)**: ship a custom probe plugin + a non-agent
  invocation surface (likely ``openclaw gateway call`` with a new
  method) so probes route through the policy without an LLM in the
  loop.

Plan: ``docs/plans/active/ssrf-runtime-probe/``
Phase: ``phases/phase-1.md``
"""
from __future__ import annotations

from dataclasses import dataclass

import pytest

from tests._live_smoke.run import (
    DEFAULT_HOST_PORT,
    run_probe,
    running_sandbox_container,
)


@dataclass(frozen=True)
class ProbeTuple:
    """One row of the probe matrix."""

    id: str
    host: str
    port: int
    method: str
    path: str
    expected_class: str
    why: str  # short note for the test docstring


PROBE_TUPLES: list[ProbeTuple] = [
    ProbeTuple(
        id="allow_host_service_health",
        host="host.openshell.internal",
        port=DEFAULT_HOST_PORT,
        method="GET",
        path="/v1/health",
        expected_class="allow_ok",
        why="positive baseline — confirms the probe can distinguish ALLOW from DENY",
    ),
    ProbeTuple(
        id="deny_host_service_off_port",
        host="host.openshell.internal",
        port=DEFAULT_HOST_PORT + 1,
        method="GET",
        path="/v1/health",
        expected_class="deny_port_not_allowlisted",
        why="off-port on the allowlisted host; only :8643 is allowed",
    ),
    ProbeTuple(
        id="deny_rfc1918_non_gateway",
        host="192.168.99.99",
        port=80,
        method="GET",
        path="/",
        expected_class="deny_host_not_allowlisted",
        why="RFC 1918 dummy IP that is NOT the configured gateway",
    ),
    ProbeTuple(
        id="deny_public_example_com",
        host="example.com",
        port=443,
        method="GET",
        path="/",
        expected_class="deny_host_not_allowlisted",
        why="IANA-reserved public hostname not in the allowlist",
    ),
    ProbeTuple(
        id="deny_public_cloudflare_dns",
        host="1.1.1.1",
        port=53,
        method="GET",
        path="/",
        expected_class="deny_host_not_allowlisted",
        why="public IP + non-standard port not in the allowlist",
    ),
]


@pytest.fixture(scope="module")
def sandbox_with_gateway():
    """Spawn the sandbox once + start gateway + yield container id."""
    import os

    image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]  # KeyError surfaces if missing despite skip
    with running_sandbox_container(
        sandbox_image=image,
        host_port=DEFAULT_HOST_PORT,
    ) as cid:
        yield cid


@pytest.mark.live_ssrf_probe
@pytest.mark.skip(
    reason=(
        "Phase 1 design flaw: docker-exec'd Node bypasses OpenShell enforcement "
        "entirely (same as docker-exec'd curl). See work-notes.md § 2026-05-24 "
        "Phase 1 GREEN finding; the probe path needs to route through openclaw's "
        "proxy infrastructure (Path X = agent turn, Path Y = custom probe plugin)."
    )
)
@pytest.mark.parametrize(
    "probe",
    PROBE_TUPLES,
    ids=[t.id for t in PROBE_TUPLES],
)
def test_invP002_runtime_probe(sandbox_with_gateway: str, probe: ProbeTuple) -> None:
    """INV-P002: runtime probe — {probe.why}."""
    result = run_probe(
        sandbox_with_gateway,
        host=probe.host,
        port=probe.port,
        method=probe.method,
        path=probe.path,
    )
    assert result["rejection_class"] == probe.expected_class, (
        f"tuple {probe.id}: expected {probe.expected_class!r}, "
        f"got {result.get('rejection_class')!r}. "
        f"status={result.get('status')!r} "
        f"body_excerpt={result.get('body_excerpt', '')[:300]!r}"
    )
