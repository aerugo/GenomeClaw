"""INV-P002 explicit-runtime-negative-case probe (Path Y).

Spawns the sandbox container with the nemoclaw-plugin's optional
TEST-ONLY ``genomeclaw_ssrf_probe_batch`` tool active
(via the ``/etc/genomeclaw/ssrf-probe-enabled`` marker file the test
touches before gateway boot), invokes the agent ONCE with no
arguments, and asserts the returned per-probe rejection_class matches
expectations.

The probe sweep is HARDCODED inside the plugin (see
``packages/nemoclaw-plugin/src/index.ts`` near the
``HARDCODED_PROBES`` constant) — five tuples matching spec AC2:

1. ``host.openshell.internal:<port> /v1/health`` → ALLOW (HTTP 200). The
   ``<port>`` matches whatever the sandbox image was built with (default
   8645; configurable via ``--build-arg GENOMECLAW_HOST_PORT=<n>`` on the
   sandbox image build). Defined inside the plugin via
   ``HARDCODED_PROBES[0].port``.
2. ``host.openshell.internal:<port+1> /v1/health`` → DENY (off-port).
3. ``192.168.99.99:80 /`` → DENY (RFC 1918 non-gateway).
4. ``example.com:443 /`` → DENY (public, non-allowlisted host).
5. ``1.1.1.1:53 /`` → DENY (public IP + non-standard port).

Three layers of INV-P002 coverage are now in place:

1. Static shape (``test_invP002_policy_preset_shape.py``, 6 tests).
2. Implicit runtime (the 4 live LLM tests exercise the policy on
   every allowed call but never assert a denial happens).
3. **Explicit runtime negative case** (this file): asserts the policy
   actually denies un-allowlisted destinations at runtime.

Phase 1 GREEN finding (docker-exec'd Node bypasses OpenShell —
the same mechanism as docker-exec'd curl) ruled out the original
plan's Node-script probe; this Path Y implementation routes through
the openclaw-loaded plugin's enforcement context instead.

Path Y also surfaced two openclaw runtime bugs:

- TypeBox ``Type.Array(Type.Object(...))`` params get stripped between
  raw_params and execute() args. Workaround: hardcode the probe set.
- Q-001 (agent-quirks.md): the openai-responses code path
  intermittently mangles string args to the literal ``"undefined"``.
  Workaround: zero-arg tool surface (no string to corrupt).

Plan: ``docs/plans/active/ssrf-runtime-probe/``
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import uuid
from pathlib import Path

import pytest

from tests._live_smoke.run import (
    DEFAULT_HOST_PORT,
    _build_openclaw_config_batch,
    host_service_running,
)


# Plugin dist relative to repo root. The test skips with a clear
# reason if it's missing — the operator must run `npm run build` in
# packages/nemoclaw-plugin/ to refresh it after editing the TS source.
# tests/invariants/<this> → tests → toolkit → packages → REPO_ROOT
_REPO_ROOT = Path(__file__).resolve().parents[4]
PLUGIN_DIST = _REPO_ROOT / "packages/nemoclaw-plugin/dist/index.js"


# Each entry pins the expected rejection_class for one tuple.
# The probe set itself is hardcoded inside the plugin (see
# `HARDCODED_PROBES` in nemoclaw-plugin/src/index.ts) — these
# entries must stay in lockstep with the IDs the plugin emits.
EXPECTED: dict[str, set[str]] = {
    "allow_host_service_health": {"allow_ok"},
    "deny_host_service_off_port": {
        "deny_port_not_allowlisted",
        "deny_host_not_allowlisted",
        "deny_other",
    },
    "deny_rfc1918_non_gateway": {
        "deny_host_not_allowlisted",
        "deny_internal_address",
        "deny_other",
    },
    "deny_public_example_com": {
        "deny_host_not_allowlisted",
        "deny_other",
    },
    "deny_public_cloudflare_dns": {
        "deny_host_not_allowlisted",
        "deny_internal_address",
        "deny_other",
    },
}


def _build_agent_message() -> str:
    # Zero-arg tool call — both array and string params get mangled by
    # openclaw's openai-responses path. The probe set is baked into the
    # plugin, so no args are needed.
    return (
        "Call the genomeclaw_ssrf_probe_batch tool ONCE with no arguments "
        "(empty object {}). Echo the entire results array back to me as "
        "raw JSON in a fenced code block. Do not call any other tools. "
        "Do not interpret the results."
    )


@pytest.mark.live_ssrf_probe
@pytest.mark.live_llm  # also needs OPENAI_API_KEY (one paid call per run)
def test_invP002_runtime_probe_sweep(tmp_path: Path) -> None:
    """INV-P002 (explicit runtime): allow-vs-deny pattern holds for all 5 tuples.

    Costs ~1 OpenAI Responses call (~$0.10–0.50) per execution. Use sparingly.
    """
    if not PLUGIN_DIST.exists():
        pytest.skip(
            f"plugin dist not built at {PLUGIN_DIST}. "
            "Run `cd packages/nemoclaw-plugin && npm run build` first."
        )

    api_key = os.environ["OPENAI_API_KEY"]  # gated by live_llm marker
    sandbox_image = os.environ["GENOMECLAW_SANDBOX_IMAGE"]  # gated by live_ssrf_probe
    derived_root = Path(os.environ.get("GENOMECLAW_DERIVED_ROOT", "/Volumes/Genome_Work/genomeclaw/derived"))
    if not derived_root.exists():
        pytest.skip(f"derived_root not present at {derived_root}")

    host_port = DEFAULT_HOST_PORT
    container_name = f"genomeclaw-ssrf-y-{uuid.uuid4().hex[:8]}"
    config_batch = _build_openclaw_config_batch(host_port)
    message = _build_agent_message()
    timeout_s = 600

    with host_service_running(derived_root, port=host_port):
        spawn = subprocess.run(
            ["docker", "run", "-d", "--rm",
             "--name", container_name,
             "--add-host=host.openshell.internal:host-gateway",
             "-e", f"OPENAI_API_KEY={api_key}",
             sandbox_image,
             "sleep", "infinity"],
            capture_output=True, text=True, check=False,
        )
        assert spawn.returncode == 0, f"docker run failed: {spawn.stderr!r}"
        try:
            # Touch the SSRF-probe marker file. The plugin checks for this
            # at registration time (see src/index.ts marker-file gate); a
            # filesystem marker is used instead of an env var because the
            # latter triggers openclaw's plugin-loader static-analysis
            # credential-harvesting heuristic.
            mark = subprocess.run(
                ["docker", "exec", "-u", "0", container_name,
                 "bash", "-c",
                 "mkdir -p /etc/genomeclaw && touch /etc/genomeclaw/ssrf-probe-enabled"],
                capture_output=True, text=True, check=False,
            )
            assert mark.returncode == 0, f"marker creation failed: {mark.stderr!r}"
            # docker cp the freshly built plugin in + chown root:root.
            # The cp preserves host UID (501) and openclaw refuses to
            # load plugins not owned by sandbox UID or root.
            cp = subprocess.run(
                ["docker", "cp", str(PLUGIN_DIST),
                 f"{container_name}:/opt/genomeclaw/dist/index.js"],
                capture_output=True, text=True, check=False,
            )
            assert cp.returncode == 0, f"docker cp failed: {cp.stderr!r}"
            chown = subprocess.run(
                ["docker", "exec", "-u", "0", container_name,
                 "chown", "root:root", "/opt/genomeclaw/dist/index.js"],
                capture_output=True, text=True, check=False,
            )
            assert chown.returncode == 0, f"chown failed: {chown.stderr!r}"

            script = (
                "set -uo pipefail\n"
                f'curl -sf "http://host.openshell.internal:{host_port}/v1/health" > /dev/null || {{ echo "host service unreachable" ; exit 11 ; }}\n'
                "cat > /tmp/batch.json <<'B'\n" + config_batch + "\nB\n"
                "openclaw config set --batch-file /tmp/batch.json > /dev/null 2>&1\n"
                "openclaw config set models.providers.openai.apiKey --ref-provider default --ref-source env --ref-id OPENAI_API_KEY > /dev/null 2>&1\n"
                "openclaw gateway run > /tmp/gateway.log 2>&1 &\n"
                "GW=$!\n"
                "for i in $(seq 1 60); do\n"
                "  if ss -lntp 2>/dev/null | grep -q openclaw-gatew; then break; fi\n"
                "  sleep 1\n"
                "done\n"
                "openclaw agent --agent genomeclaw "
                f"--message {json.dumps(message)} "
                "--json "
                f"--timeout {timeout_s} > /tmp/agent-out.json 2>&1\n"
                "RC=$?\n"
                "kill $GW 2>/dev/null || true\n"
                "wait $GW 2>/dev/null || true\n"
                "echo '===AGENT-JSON-BEGIN==='\n"
                "cat /tmp/agent-out.json\n"
                "echo\n"
                "echo '===AGENT-JSON-END==='\n"
                "exit $RC\n"
            )
            t0 = time.monotonic()
            proc = subprocess.run(
                ["docker", "exec", "-i", container_name, "bash", "-c",
                 "cat > /tmp/run.sh && bash /tmp/run.sh"],
                input=script, text=True, capture_output=True,
                timeout=timeout_s + 120, check=False,
            )
            elapsed = time.monotonic() - t0
        finally:
            subprocess.run(
                ["docker", "rm", "-f", container_name],
                capture_output=True, text=True, check=False,
            )

    (tmp_path / "stdout.txt").write_text(proc.stdout)
    m = re.search(r"===AGENT-JSON-BEGIN===\s*(.*?)\s*===AGENT-JSON-END===", proc.stdout, re.DOTALL)
    assert m is not None, f"missing sentinels in agent stdout (tail): {proc.stdout[-2000:]!r}"
    mm = re.search(r"\{[\s\S]*\}", m.group(1))
    assert mm is not None, f"no JSON object in sentinelled block: {m.group(1)[:500]!r}"
    trace = json.loads(mm.group(0))
    (tmp_path / "trace.json").write_text(json.dumps(trace, indent=2))

    payloads = trace.get("result", trace).get("payloads", [])
    reply = payloads[0].get("text", "") if payloads else ""
    cb = re.search(r"```(?:json)?\s*(\[[\s\S]*?\])\s*```", reply)
    assert cb is not None, (
        f"agent reply does not contain a fenced JSON array (tool may have failed): "
        f"reply (first 500 chars): {reply[:500]!r}; "
        f"elapsed={elapsed:.1f}s"
    )
    results = json.loads(cb.group(1))
    assert isinstance(results, list), f"expected list, got {type(results).__name__}"
    assert len(results) == 5, f"expected 5 probes, got {len(results)}: {results}"

    by_id = {r["id"]: r for r in results}
    failures: list[str] = []
    for probe_id, allowed_classes in EXPECTED.items():
        if probe_id not in by_id:
            failures.append(f"missing probe {probe_id!r} in results")
            continue
        rc = by_id[probe_id].get("rejection_class")
        if rc not in allowed_classes:
            failures.append(
                f"{probe_id}: got {rc!r}, expected one of {sorted(allowed_classes)} "
                f"(body excerpt: {by_id[probe_id].get('body_excerpt', '')[:200]!r})"
            )
    assert not failures, "INV-P002 runtime probe failures:\n  " + "\n  ".join(failures)

    # Sanity: the ALLOW probe must return HTTP 200 with a real
    # /v1/health body (proves the host service IS reachable from the
    # plugin's enforcement context, not just classified as allow_ok
    # by accident).
    allow_result = by_id["allow_host_service_health"]
    assert allow_result.get("status") == 200, (
        f"allow probe didn't return HTTP 200: {allow_result!r}"
    )
    body = allow_result.get("body_excerpt", "")
    assert '"status":"ok"' in body, (
        f"allow probe body doesn't look like /v1/health response: {body!r}"
    )
