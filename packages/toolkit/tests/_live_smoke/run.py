"""Run an `openclaw agent` turn inside the sandbox image, return parsed trace.

The orchestrator handles the four-part dance Phase 2b's manual smoke
script did:

1. Stand up the host service against the supplied derived store on a
   loopback port (default 8645; configurable via
   ``GENOMECLAW_HOST_SERVICE_PORT``) as a child process.
2. Pre-stage `IDENTITY.md` + `USER.md` into a tmp workspace dir; bind-
   mount it into the sandbox at `/sandbox/.openclaw/workspace/` so the
   `pi`-harness's BOOTSTRAP.md flow doesn't intercept the first turn
   (the bypass pattern that worked end-to-end in the Phase 2b smoke).
3. `docker run` against the sandbox image with `--add-host=host.openshell.
   internal:host-gateway -e OPENAI_API_KEY` and pipe a shell script that
   configures the OpenAI provider + `agents.defaults.thinkingDefault: max`,
   reconfigures the genomeclaw plugin's `hostService.baseUrl` to the
   chosen port, starts the gateway, runs `openclaw agent --json`, and
   emits the raw JSON to a host-mounted volume.
4. Tear the host service down; return the parsed trace dict.

The orchestrator is INTENTIONALLY synchronous + serial: live LLM calls
cost real money and we want predictable, easy-to-debug behaviour.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import signal
import socket
import subprocess
import sys
import time
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Any

# GenomeClaw's canonical host-service port. Operator-configurable via the
# GENOMECLAW_HOST_SERVICE_PORT env var (matches the convention used by the
# `bin/genomeclaw` shim + the in-sandbox plugin baseUrl). 8645 is the
# default — DevRelClaw uses 8643, so distinct defaults let both projects
# coexist on one host. See
# docs/reports/genomeclaw-devrelclaw-coexistence-2026-05-24.md.
DEFAULT_HOST_PORT = int(os.environ.get("GENOMECLAW_HOST_SERVICE_PORT", "8645"))


def _port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """Return True iff binding `host:port` succeeds (port is currently free)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((host, port))
            return True
        except OSError:
            return False


@contextmanager
def host_service_running(derived_root: Path, *, port: int = DEFAULT_HOST_PORT) -> Iterator[int]:
    """Start `genomeclaw host service` against `derived_root`; tear down on exit.

    Raises RuntimeError if the port is already in use OR the service
    fails to come up within ~10 s. The contextmanager yields the bound
    port so the caller can reconfigure the plugin's `hostService.baseUrl`.
    """
    if not _port_is_free(port):
        raise RuntimeError(
            f"port {port} already in use; "
            "set GENOMECLAW_LIVE_SMOKE_HOST_PORT to override or stop the existing process"
        )

    # Use the same Python that's running pytest so we hit the in-tree
    # genomeclaw_toolkit package. The CLI's `main()` is exposed as a
    # console script (`genomeclaw`); calling it via `python -c` keeps us
    # inside the test's venv without depending on the script being on
    # PATH.
    cmd = [
        sys.executable,
        "-c",
        (
            "from genomeclaw_toolkit._cli import main; "
            f"main(['host', 'service', '--derived-root', {str(derived_root)!r}, "
            f"'--port', {str(port)!r}])"
        ),
    ]
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Wait for /v1/health to respond. The service binds within a few
        # hundred ms; 10 s is generous so a slow CI doesn't false-fail.
        deadline = time.monotonic() + 10.0
        while time.monotonic() < deadline:
            if not _port_is_free(port):
                # Port is taken → the service has bound. Verify health.
                health = _curl_health(port)
                if health is not None and health.get("status") == "ok":
                    yield port
                    return
            if proc.poll() is not None:
                # Service died before binding; surface its log.
                stdout = proc.stdout.read() if proc.stdout else "<no stdout>"
                raise RuntimeError(
                    f"host service exited before binding {port}: rc={proc.returncode}\n{stdout}"
                )
            time.sleep(0.2)
        raise RuntimeError(f"host service failed to bind {port} within 10 s")
    finally:
        # Send SIGINT to let uvicorn shut down cleanly; then SIGKILL after grace.
        try:
            proc.send_signal(signal.SIGINT)
            try:
                proc.wait(timeout=3)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait(timeout=3)
        except ProcessLookupError:
            pass


def _curl_health(port: int) -> dict[str, Any] | None:
    """One-shot GET /v1/health; returns parsed JSON or None on any failure."""
    try:
        proc = subprocess.run(
            ["curl", "-sf", "--max-time", "2", f"http://127.0.0.1:{port}/v1/health"],
            check=False,
            capture_output=True,
            text=True,
        )
        if proc.returncode != 0:
            return None
        return json.loads(proc.stdout)
    except (json.JSONDecodeError, OSError):
        return None


def _render_extra_workspace_block(files: dict[str, str]) -> str:
    """Render the bash block that writes pre-staged workspace files via heredocs.

    Each key is a workspace-relative path (e.g. `"MEMORY.md"` or
    `"daily/2026-04-01.md"`). The value is the file content. We pick a
    per-file heredoc terminator derived from the path so multiple files
    don't collide; the path's non-alnum chars get squashed to keep the
    terminator a single bash word.
    """
    if not files:
        return ""
    chunks = ["\n# 0b. Pre-staged workspace files (slice 3+: weak memory notes etc.).\n"]
    for relpath, content in files.items():
        sanitised = re.sub(r"[^A-Za-z0-9]", "_", relpath).upper()
        terminator = f"WORKSPACE_FILE_{sanitised}"
        # Defensive: if the content somehow contains the chosen terminator
        # on a line of its own, the heredoc would close early. Fail loudly
        # rather than silently corrupt the file.
        if re.search(rf"(?m)^{re.escape(terminator)}$", content):
            raise ValueError(
                f"extra_workspace_files content for {relpath!r} contains the heredoc "
                f"terminator {terminator!r} on a line; pick a different path."
            )
        # Use a sub-shell `( cd && ... )` so we don't need to track CWD.
        target = f"/sandbox/.openclaw/workspace/{relpath}"
        chunks.append(f"mkdir -p {os.path.dirname(target) or '/'}\n")
        chunks.append(f"cat > {target} <<'{terminator}'\n")
        chunks.append(content if content.endswith("\n") else content + "\n")
        chunks.append(f"{terminator}\n")
    return "".join(chunks)


def _build_in_container_script(
    *,
    message: str,
    host_port: int,
    timeout_s: int,
    extra_workspace_files: dict[str, str] | None = None,
) -> str:
    """The bash script executed inside the sandbox container.

    Configures the OpenAI provider + the genomeclaw plugin's
    `hostService.baseUrl`, starts the gateway, invokes the agent, then
    emits the raw agent JSON to stdout bracketed by sentinel lines so
    the host can extract it past the plugin-loader log line + any
    gateway-fallback log lines.

    `extra_workspace_files` is a mapping from workspace-relative path
    (e.g. `"MEMORY.md"` or `"daily/2026-04-01.md"`) to file content.
    Slice 3 uses this to pre-stage a deliberately-weak prior memory note
    so the agent's INV-C001 v1.6 validation step can fire against a
    known-bad input. Each file is written via a per-file heredoc, so
    callers don't need to worry about quoting.

    The Phase 3 slice 4 (2026-05-15) Dockerfile bake of `IDENTITY.md`
    + `USER.md` (with `BOOTSTRAP.md` removed) makes the inline bootstrap
    workaround the previous slices needed unnecessary — the image's
    workspace is bootstrap-complete on first run. A regression in that
    bake gets caught by `tests/invariants/test_sandbox_workspace_bootstrap_baked.py`.

    The script is assembled by concatenation (not f-string + dedent) so
    bash heredoc terminators land at column 0 — `dedent` can't strip
    indent from interpolated multi-line strings (which start at col 0
    because the constants are unindented), which leaves the rest of the
    script indented and bash then fails to recognise the heredoc closer.
    """
    escaped_message = json.dumps(message)
    # Shared with running_sandbox_container() so the two harness modes
    # don't drift on provider config / model id / thinking depth.
    openclaw_batch = _build_openclaw_config_batch(host_port)
    extra_workspace_block = _render_extra_workspace_block(extra_workspace_files or {})
    return (
        "set -uo pipefail\n"
        "\n"
        "# 0. Workspace pre-staging (slice 3+: weak memory notes etc.).\n"
        "#    Bootstrap files (IDENTITY.md / USER.md / no BOOTSTRAP.md) are baked\n"
        "#    into the image at build time per slice 4 — no inline write needed.\n"
        + extra_workspace_block
        + "\n"
        f'curl -sf "http://host.openshell.internal:{host_port}/v1/health" > /dev/null '
        '|| { echo "host service unreachable" ; exit 11 ; }\n'
        "\n"
        "# 2. Configure OpenAI gpt-5.5 + max thinking + plugin host port.\n"
        "cat > /tmp/openclaw-batch.json <<'OPENCLAW_BATCH'\n" + openclaw_batch + "\n"
        "OPENCLAW_BATCH\n"
        "openclaw config set --batch-file /tmp/openclaw-batch.json > /dev/null 2>&1\n"
        "openclaw config set models.providers.openai.apiKey "
        "--ref-provider default --ref-source env --ref-id OPENAI_API_KEY > /dev/null 2>&1\n"
        "\n"
        "# 3. Start gateway (stderr -> /tmp/gateway.log).\n"
        "openclaw gateway run > /tmp/gateway.log 2>&1 &\n"
        "GATEWAY_PID=$!\n"
        "for i in $(seq 1 30); do\n"
        '  if openclaw gateway status 2>&1 | grep -qiE "ready|healthy|listening|connected"; then\n'
        "    break\n"
        "  fi\n"
        "  sleep 1\n"
        "done\n"
        "\n"
        "# 4. One-shot agent turn — JSON output to /tmp; capture rc.\n"
        "#    NOTE: openclaw `agent --json` may emit the envelope on stderr\n"
        "#    in the embedded-fallback path; combine both streams so the\n"
        "#    extractor downstream can find the {...} block regardless.\n"
        "openclaw agent \\\n"
        "  --agent genomeclaw \\\n"
        f"  --message {escaped_message} \\\n"
        "  --json \\\n"
        f"  --timeout {timeout_s} \\\n"
        "  > /tmp/agent-out.json 2>&1\n"
        "AGENT_RC=$?\n"
        "\n"
        "# 5. Cleanup\n"
        'kill "$GATEWAY_PID" 2>/dev/null || true\n'
        'wait "$GATEWAY_PID" 2>/dev/null || true\n'
        "\n"
        "# 6. Emit JSON (+ any prefix log noise) bracketed by sentinels.\n"
        'echo "===AGENT-JSON-BEGIN==="\n'
        "if [ -s /tmp/agent-out.json ]; then\n"
        "  cat /tmp/agent-out.json\n"
        "else\n"
        '  echo "<empty /tmp/agent-out.json; agent rc=$AGENT_RC>"\n'
        '  echo "===GATEWAY-LOG-BEGIN==="\n'
        "  tail -c 4000 /tmp/gateway.log 2>/dev/null || true\n"
        '  echo "===GATEWAY-LOG-END==="\n'
        "fi\n"
        "echo\n"
        'echo "===AGENT-JSON-END==="\n'
        'echo "rc=$AGENT_RC"\n'
        "exit $AGENT_RC\n"
    )


def run_agent_in_sandbox(
    message: str,
    *,
    derived_root: Path,
    sandbox_image: str,
    openai_api_key: str,
    host_port: int = DEFAULT_HOST_PORT,
    timeout_s: int = 240,
    extra_workspace_files: dict[str, str] | None = None,
) -> dict[str, Any]:
    """Run one agent turn against `sandbox_image` + return the parsed JSON trace.

    Args:
        message: The user-facing message to send to the agent.
        derived_root: Path the host service serves from (must already
            carry a `derived/<run-id>/` staged via `staging.py`).
        sandbox_image: A docker image tag (e.g. `genomeclaw/sandbox:ars-phase-2c`).
            The image must carry the slice-4 workspace bake
            (`IDENTITY.md` + `USER.md` baked, no `BOOTSTRAP.md`); a
            stripped-down image will fall back into the pi-harness
            bootstrap intercept flow.
        openai_api_key: The OpenAI API key (passed via `-e OPENAI_API_KEY`).
        host_port: Port the host service binds + the plugin reads from.
        timeout_s: Hard timeout for the entire docker invocation.
        extra_workspace_files: Optional mapping from workspace-relative
            path (e.g. ``"MEMORY.md"``) to file content. Pre-staged
            inside the container before the agent runs. Slice 3 uses
            this to seed a deliberately-weak prior memory note for the
            INV-C001 v1.6 validation-driven supersession test. The
            slice-4 bake means callers no longer need to pre-stage the
            bootstrap files themselves.

    Returns:
        A dict with the parsed agent JSON. The agent CLI's stdout is
        prefixed by a one-line `[plugins] GenomeClaw plugin registered ...`
        log + may carry gateway-fallback log lines; this function strips
        leading non-JSON content before parsing.

    Raises:
        RuntimeError: when docker fails to invoke OR the JSON cannot be
            extracted OR the host service didn't come up.
    """
    if shutil.which("docker") is None:
        raise RuntimeError("docker CLI not on PATH; cannot run live smoke")

    script = _build_in_container_script(
        message=message,
        host_port=host_port,
        timeout_s=timeout_s,
        extra_workspace_files=extra_workspace_files,
    )

    with host_service_running(derived_root, port=host_port):
        # Hand the script to the container via stdin. The container
        # reads it, writes it to /tmp/run.sh, executes it. The agent's
        # JSON envelope is emitted on stdout bracketed by
        # `===AGENT-JSON-{BEGIN,END}===` sentinels.
        docker_cmd = [
            "docker",
            "run",
            "--rm",
            "-i",
            "--add-host=host.openshell.internal:host-gateway",
            "-e",
            "OPENAI_API_KEY",
            sandbox_image,
            "bash",
            "-c",
            "cat > /tmp/run.sh && bash /tmp/run.sh",
        ]
        env = {**os.environ, "OPENAI_API_KEY": openai_api_key}
        proc = subprocess.run(
            docker_cmd,
            input=script,
            text=True,
            capture_output=True,
            timeout=timeout_s + 60,
            check=False,
            env=env,
        )

    json_blob = _extract_sentinelled_json(proc.stdout)
    if json_blob is None:
        raise RuntimeError(
            f"docker invocation produced no parseable agent JSON between sentinels. "
            f"docker rc={proc.returncode}\n"
            f"stdout (first 2k):\n{proc.stdout[:2000]}\n"
            f"stderr (first 1k):\n{proc.stderr[:1000]}"
        )
    trace = _parse_agent_output(json_blob)
    if trace is None:
        raise RuntimeError(
            f"could not parse agent JSON. docker rc={proc.returncode}\n"
            f"json blob (first 2k):\n{json_blob[:2000]}"
        )
    return trace


def _extract_sentinelled_json(stdout: str) -> str | None:
    """Pull the text between `===AGENT-JSON-BEGIN===` and `===AGENT-JSON-END===`.

    The in-container script brackets the JSON with these sentinels so
    the host can find it past the plugin-loader log line + any gateway
    fallback log lines that openclaw emits to stdout. Returns None if
    the sentinels are absent or empty.
    """
    m = re.search(
        r"===AGENT-JSON-BEGIN===\s*(.*?)\s*===AGENT-JSON-END===",
        stdout,
        re.DOTALL,
    )
    if m is None:
        return None
    blob = m.group(1).strip()
    return blob or None


def _parse_agent_output(raw: str) -> dict[str, Any] | None:
    """Strip leading log lines + parse the JSON envelope + normalise the shape.

    `openclaw agent --json` writes the JSON envelope to stdout, but the
    plugin loader emits a one-line `[plugins] GenomeClaw plugin registered
    ...` first. The gateway-fallback path may also emit several log lines
    before the JSON. Search for the first `{` and try to parse from there.

    Shape normalisation: openclaw returns one of two shapes depending on
    whether the gateway succeeded or fell back to embedded execution:

    - Gateway-wrapped (full envelope):
      ``{status, runId, summary, result: {payloads, meta}}``
    - Embedded direct (the inner result, unwrapped):
      ``{payloads, meta}``

    Tests should not have to handle both. We normalise to the
    gateway-wrapped form by wrapping the embedded direct shape with a
    synthetic `status: "ok"` + the original blob under `result`.
    """
    m = re.search(r"\{[\s\S]*\}", raw)
    if m is None:
        return None
    candidate = m.group(0)
    try:
        parsed = json.loads(candidate)
    except json.JSONDecodeError:
        return None
    if isinstance(parsed, dict) and "status" not in parsed and "payloads" in parsed:
        return {
            "status": "ok",
            "summary": "completed-embedded",
            "result": parsed,
        }
    return parsed


def _build_openclaw_config_batch(host_port: int) -> str:
    """Render the openclaw `config set --batch-file` payload as JSON.

    Shared by the one-shot in-container script (agent turns) and the
    long-running container fixture (ssrf-probe). The OpenAI provider
    entry is included even when no agent call follows because the
    plugin's hostService.baseUrl + plugin-allow + gateway.mode entries
    must land together as one batch; omitting the provider produces a
    half-configured gateway that refuses to bind cleanly.
    """
    return json.dumps(
        [
            {"path": "models.providers.openai.baseUrl", "value": "https://api.openai.com/v1"},
            {
                "path": "models.providers.openai.models",
                "value": [
                    {
                        "id": "gpt-5.5",
                        "name": "GPT 5.5",
                        "api": "openai-responses",
                        "contextWindow": 200000,
                        "maxTokens": 16384,
                    }
                ],
            },
            {"path": "auth.profiles.openai_default.provider", "value": "openai"},
            {"path": "auth.profiles.openai_default.mode", "value": "api_key"},
            {"path": "plugins.allow", "value": ["genomeclaw"]},
            {"path": "gateway.mode", "value": "local"},
            {"path": "agents.defaults.model", "value": "openai/gpt-5.5"},
            {"path": "agents.defaults.thinkingDefault", "value": "xhigh"},
            {
                "path": "plugins.entries.genomeclaw.config.hostService.baseUrl",
                "value": f"http://host.openshell.internal:{host_port}",
            },
        ]
    )


# Path to the Node probe script shipped alongside this module. Copied into
# the running sandbox container at /opt/probe_script.js by
# running_sandbox_container().
_PROBE_SCRIPT_HOST_PATH = Path(__file__).parent / "probe_script.js"
_PROBE_SCRIPT_CONTAINER_PATH = "/opt/probe_script.js"


@contextmanager
def running_sandbox_container(
    *,
    sandbox_image: str,
    host_port: int = DEFAULT_HOST_PORT,
    gateway_boot_timeout_s: float = 60.0,
) -> Iterator[str]:
    """Spawn the sandbox container + start the gateway; yield container ID.

    The container is created with `sleep infinity` as its entrypoint so it
    stays alive across multiple ``docker exec``-issued probes. The openclaw
    gateway is configured + started inside via docker exec; readiness is
    polled via ``openclaw gateway status``. The Node probe script
    (``probe_script.js`` in this directory) is copied into the container
    at ``/opt/probe_script.js`` so subsequent ``run_probe`` calls can exec
    it directly.

    Cleanup runs unconditionally on context exit via ``docker rm -f`` —
    no zombie containers even when the ``with`` block raises.

    Raises ``RuntimeError`` if:

    - ``docker run`` fails to spawn the container.
    - The gateway fails to report ready within ``gateway_boot_timeout_s``.
      The container's ``/tmp/gateway.log`` is included in the error message
      for debugging.
    """
    import uuid

    container_name = f"genomeclaw-ssrf-probe-{uuid.uuid4().hex[:8]}"
    config_batch = _build_openclaw_config_batch(host_port)

    # 1. Spawn the container. `--add-host` matches the one-shot path so
    # `host.openshell.internal` resolves to the host-gateway bridge.
    spawn_cmd = [
        "docker", "run", "-d", "--rm",
        "--name", container_name,
        "--add-host=host.openshell.internal:host-gateway",
        sandbox_image,
        "sleep", "infinity",
    ]
    spawn = subprocess.run(spawn_cmd, capture_output=True, text=True, check=False)
    if spawn.returncode != 0:
        raise RuntimeError(
            f"docker run failed (rc={spawn.returncode}): "
            f"stdout={spawn.stdout[:500]!r} stderr={spawn.stderr[:500]!r}"
        )
    container_id = spawn.stdout.strip() or container_name

    try:
        # 2. Copy the Node probe script into the container.
        if _PROBE_SCRIPT_HOST_PATH.exists():
            cp_proc = subprocess.run(
                ["docker", "cp", str(_PROBE_SCRIPT_HOST_PATH),
                 f"{container_name}:{_PROBE_SCRIPT_CONTAINER_PATH}"],
                capture_output=True, text=True, check=False,
            )
            if cp_proc.returncode != 0:
                raise RuntimeError(
                    f"docker cp probe_script.js failed: {cp_proc.stderr[:500]}"
                )

        # 3. Write the openclaw config batch + start the gateway.
        config_exec = subprocess.run(
            ["docker", "exec", "-i", container_name,
             "bash", "-c",
             "cat > /tmp/openclaw-batch.json && "
             "openclaw config set --batch-file /tmp/openclaw-batch.json > /dev/null 2>&1"],
            input=config_batch, capture_output=True, text=True, check=False,
        )
        if config_exec.returncode != 0:
            raise RuntimeError(
                f"openclaw config set failed: {config_exec.stderr[:500]}"
            )

        gateway_start = subprocess.run(
            ["docker", "exec", "-d", container_name,
             "bash", "-c", "openclaw gateway run > /tmp/gateway.log 2>&1"],
            capture_output=True, text=True, check=False,
        )
        if gateway_start.returncode != 0:
            raise RuntimeError(
                f"docker exec gateway-start failed: {gateway_start.stderr[:500]}"
            )

        # 4. Poll readiness. `openclaw gateway status` blocks ~5 s per call
        # doing a WebSocket probe; instead poll the gateway's listening
        # socket inside the container (instant). The default gateway port
        # is 18789 (from `openclaw config get gateway.port`). `ss` truncates
        # process names to 15 chars, so the comm field is `openclaw-gatewa`
        # (no trailing y). We grep for that prefix on any LISTEN row.
        deadline = time.monotonic() + gateway_boot_timeout_s
        ready = False
        while time.monotonic() < deadline:
            port_probe = subprocess.run(
                ["docker", "exec", container_name,
                 "bash", "-c",
                 "ss -lntp 2>/dev/null | grep -q openclaw-gatew && echo UP"],
                capture_output=True, text=True, check=False,
            )
            if "UP" in port_probe.stdout:
                ready = True
                break
            time.sleep(1.0)
        if not ready:
            log = subprocess.run(
                ["docker", "exec", container_name,
                 "bash", "-c", "cat /tmp/gateway.log 2>/dev/null || true"],
                capture_output=True, text=True, check=False,
            )
            raise RuntimeError(
                f"openclaw gateway didn't report ready within "
                f"{gateway_boot_timeout_s}s. Gateway log tail:\n{log.stdout[-2000:]}"
            )

        yield container_id
    finally:
        subprocess.run(
            ["docker", "rm", "-f", container_name],
            capture_output=True, text=True, check=False,
        )


def run_probe(
    container_id: str,
    *,
    host: str,
    port: int,
    method: str = "GET",
    path: str = "/",
    docker_exec_timeout_s: int = 15,
) -> dict[str, Any]:
    """Issue one SSRF probe via ``docker exec node /opt/probe_script.js``.

    Returns the parsed JSON dict the Node script writes on stdout — one
    line with keys ``status``, ``body_excerpt``, ``rejection_class``,
    ``openclaw_version_line``, ``elapsed_ms``, ``tuple``.

    Raises ``RuntimeError`` if ``docker exec`` fails outright OR the
    script's stdout isn't parseable JSON. A "probe ran but got rejected"
    outcome is signalled by the JSON's ``rejection_class``, not by the
    exec rc — the Node script always exits 0 and reports classification
    in-band.
    """
    proc = subprocess.run(
        ["docker", "exec", container_id,
         "node", _PROBE_SCRIPT_CONTAINER_PATH,
         "--host", host, "--port", str(port),
         "--method", method, "--path", path],
        capture_output=True, text=True, check=False, timeout=docker_exec_timeout_s,
    )
    if proc.returncode != 0:
        raise RuntimeError(
            f"docker exec probe failed (rc={proc.returncode}): "
            f"stdout={proc.stdout[:500]!r} stderr={proc.stderr[:500]!r}"
        )
    stdout = proc.stdout.strip()
    if not stdout:
        raise RuntimeError("probe script produced empty stdout")
    try:
        return json.loads(stdout.splitlines()[-1])
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"probe script stdout was not parseable JSON: {e}; raw: {stdout[:500]!r}"
        ) from e


__all__ = [
    "DEFAULT_HOST_PORT",
    "host_service_running",
    "run_agent_in_sandbox",
    "running_sandbox_container",
    "run_probe",
]
