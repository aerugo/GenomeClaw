"""Phase 4 — recovery-wrapper / onboard-script shape (nemoclaw-canonical-integration).

Static, no-docker checks on `scripts/sandbox-up.sh` + `scripts/onboard-sandbox.sh`.
These pin the Phase 4 cleanups:

- No non-comment reference to the legacy `/opt/genomeclaw` path (the plugin
  moved to `/sandbox/build/genomeclaw` in Phase 2; `sandbox-up.sh` Step 2 used
  to grep `/opt/genomeclaw` for EACCES).
- Gateway liveness is detected by PORT (`:18789`), not the fragile
  `ss … | grep openclaw-gatew` process-name match (the process is named
  `openclaw`; the truncated grep is version-dependent).
- `sandbox-up.sh` keeps the keyed `docker exec -e OPENAI_API_KEY` restart as the
  working local-Docker recovery, and makes a best-effort `nemoclaw … recover`
  / `connect --probe-only` attempt first (the supervised path when available).
- The keyed restart passes the secret via env (`-e`), never argv (INV-P003).

Per INV-V001 this is structural shell inspection (regex over shell source),
which is explicitly allowed (target is shell, not LLM output).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SANDBOX_UP = REPO_ROOT / "scripts" / "sandbox-up.sh"
ONBOARD = REPO_ROOT / "scripts" / "onboard-sandbox.sh"


def _noncomment(text: str) -> list[tuple[int, str]]:
    out = []
    for i, line in enumerate(text.splitlines(), start=1):
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        out.append((i, line))
    return out


def test_sandbox_up_no_legacy_opt_path() -> None:
    """`sandbox-up.sh` has no non-comment `/opt/genomeclaw` reference."""
    offenders = [
        (i, line.strip())
        for i, line in _noncomment(SANDBOX_UP.read_text())
        if "/opt/genomeclaw" in line
    ]
    assert not offenders, (
        "Phase 4: sandbox-up.sh still references the legacy /opt/genomeclaw path "
        f"in non-comment code (plugin is now at /sandbox/build/genomeclaw). "
        f"Offenders: {offenders}"
    )


def test_onboard_no_legacy_opt_path() -> None:
    """`onboard-sandbox.sh` has no non-comment `/opt/genomeclaw` reference."""
    offenders = [
        (i, line.strip())
        for i, line in _noncomment(ONBOARD.read_text())
        if "/opt/genomeclaw" in line
    ]
    assert not offenders, (
        "Phase 4: onboard-sandbox.sh still references the legacy /opt/genomeclaw "
        f"path in non-comment code. Offenders: {offenders}"
    )


def test_gateway_detection_is_port_based_not_process_name() -> None:
    """Neither script detects the gateway via the fragile `openclaw-gatew` grep."""
    for script in (SANDBOX_UP, ONBOARD):
        bad = [
            (i, line.strip())
            for i, line in _noncomment(script.read_text())
            if "openclaw-gatew" in line
        ]
        assert not bad, (
            f"Phase 4: {script.name} detects the gateway via the fragile "
            f"`openclaw-gatew` process-name grep. Use a port-based check "
            f"(`:18789`). Offenders: {bad}"
        )
    # Positive: a port-based liveness check must be present in sandbox-up.sh.
    up = SANDBOX_UP.read_text()
    assert re.search(r"ss\s+-lntp[^\n]*18789", up) or re.search(r"grep[^\n]*18789", up), (
        "Phase 4: sandbox-up.sh must detect the gateway by port (:18789)."
    )


def test_sandbox_up_keeps_keyed_restart_env_not_argv() -> None:
    """The keyed gateway restart passes OPENAI_API_KEY via `-e`, never argv (INV-P003)."""
    up = SANDBOX_UP.read_text()
    # Must still (re)start the gateway with the key in env.
    assert re.search(r"-e\s+OPENAI_API_KEY=", up), (
        "Phase 4: sandbox-up.sh must restart the gateway with `-e OPENAI_API_KEY=` "
        "(the INV-P003-clean local-Docker recovery)."
    )
    # The key VALUE must never expand outside a `-e` flag (no argv/file payloads).
    key_expand = re.compile(r"(?<!\\)\$\{?OPENAI_API_KEY\}?")
    env_flag = re.compile(r'-e\s+OPENAI_API_KEY="?\$\{?OPENAI_API_KEY\}?"?')
    for i, line in _noncomment(up):
        if key_expand.search(line):
            assert env_flag.search(line), (
                f"INV-P003: sandbox-up.sh:L{i} expands OPENAI_API_KEY outside a "
                f"`-e OPENAI_API_KEY=` env flag: {line.strip()[:120]}"
            )


def test_sandbox_up_best_effort_nemoclaw_recover() -> None:
    """`sandbox-up.sh` attempts the supervised recover path before the docker-exec restart.

    On local Docker `nemoclaw recover` fails (no credential injection — Phase 3),
    so it is a best-effort attempt, not the sole path; the keyed docker-exec
    restart remains. We just assert the supervised attempt is wired in (so the
    supervised path is used whenever it works, e.g. remote deployments).
    """
    up = SANDBOX_UP.read_text()
    assert re.search(r"nemoclaw\s+\S+\s+(recover|connect)", up), (
        "Phase 4: sandbox-up.sh should make a best-effort `nemoclaw <name> recover` "
        "or `connect --probe-only` attempt before the docker-exec keyed restart."
    )
