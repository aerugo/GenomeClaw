"""`INV-P003` (proposed) — secrets pass via stdin or env, never via argv.

Background: on 2026-05-24 the onboard script's
`nemoclaw genomeclaw exec -- python3 -c "import base64; ...base64.b64decode('$PROFILE_B64')..."`
invocation crashed because the target directory `/sandbox/.openclaw/agents/
genomeclaw/agent/` didn't yet exist. Python's default traceback prints
the entire `-c` source string verbatim — including the base64 blob that
encoded the operator's OpenAI API key. That traceback landed in a
`tee`-captured log file (`docs/reports/demo-2026-05-24-logs/03-onboard-v2.log`),
which is a committed report directory. The key was redacted in-place but
the leak path is structural: ANY future failure of ANY argv-interpolated
secret command will repeat the leak.

This file enforces the structural floor: every `.sh` under `scripts/`
is grepped for the forbidden argv-interpolation patterns. Per-script
positive tests on `scripts/onboard-sandbox.sh` assert the stdin-based
write pattern is present.

The proposed invariant is INV-P003; promoted into docs/reference/INVARIANTS.md
once this file's tests are green.

Tracks the onboard-persistent-agent-fix plan
(docs/plans/active/onboard-persistent-agent-fix/).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPTS_DIR = REPO_ROOT / "scripts"
ONBOARD_SCRIPT = SCRIPTS_DIR / "onboard-sandbox.sh"

# Patterns that historically (or canonically) ship a secret through argv.
# Each is a positive-match for a forbidden shape — finding any of these
# means the script puts a secret-bearing value on a command line.
_FORBIDDEN_ARGV_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    # python3 -c "...base64.b64decode('$<NAME>_B64')..." — the canonical leak shape
    # surfaced 2026-05-24.
    (
        "python -c with b64decode($NAME_B64)",
        re.compile(r"python3?\s+-c\s+.*b64decode\(['\"]\$"),
    ),
    # bash -c "...$<NAME>_KEY..." / SECRET / TOKEN / PASSWORD — shell interpolation
    # of a secret-named env var into a bash -c argv string.
    (
        "bash -c with interpolated $NAME_(KEY|SECRET|TOKEN|PASSWORD)",
        re.compile(r"bash\s+-c\s+['\"][^'\"]*\$[A-Z_]*(?:KEY|SECRET|TOKEN|PASSWORD)"),
    ),
    # --key $X, --secret $X, --token $X, --password $X — argv flag with
    # interpolated value. Catches CLIs that take credentials as flag args.
    (
        "--(key|secret|token|password) $X argv flag",
        re.compile(r"--(?:key|secret|token|password)[=\s]+\$"),
    ),
)


def _join_line_continuations(text: str) -> list[tuple[int, str]]:
    """Join bash line-continuations (trailing `\\\\` + newline) into logical lines.

    Returns (start_line_no, joined_text) tuples so a logical line that spans
    physical lines 209-210 reports as line 209. Bash scripts routinely break
    long invocations across multiple physical lines with `\\\\` — including
    the canonical leak pattern from 2026-05-24
    (`nemoclaw genomeclaw exec --no-tty -- python3 -c \\\\\\n  "...$PROFILE_B64..."`).
    """
    logical: list[tuple[int, str]] = []
    physical = text.splitlines()
    i = 0
    while i < len(physical):
        start = i + 1  # 1-indexed
        joined = physical[i]
        # While the current line ends in an unescaped trailing backslash,
        # consume the next physical line.
        while joined.endswith("\\") and (i + 1) < len(physical):
            joined = joined[:-1] + " " + physical[i + 1]
            i += 1
        logical.append((start, joined))
        i += 1
    return logical


def _gather_offenders(text: str) -> list[tuple[int, str, str]]:
    """Return (line_no, pattern_name, line_text) for every match in `text`."""
    offenders: list[tuple[int, str, str]] = []
    for line_no, joined in _join_line_continuations(text):
        for name, pattern in _FORBIDDEN_ARGV_PATTERNS:
            if pattern.search(joined):
                offenders.append((line_no, name, joined.strip()))
    return offenders


def test_invP003_onboard_script_has_no_argv_secret_patterns() -> None:
    """The auth-profile-write step that leaked the API key in 2026-05-24 must stay closed.

    Direct grep on `scripts/onboard-sandbox.sh` for the three canonical
    forbidden shapes. Pre-Phase-2 this fails on the
    `nemoclaw exec ... python3 -c "...$PROFILE_B64..."` line.
    """
    text = ONBOARD_SCRIPT.read_text()
    offenders = _gather_offenders(text)
    rendered = "\n".join(
        f"  L{i:3d} ({name}): {line[:120]}" for i, name, line in offenders
    )
    assert not offenders, (
        f"INV-P003: {ONBOARD_SCRIPT.relative_to(REPO_ROOT)} has argv-interpolated "
        f"secret patterns. Secrets must transit via stdin (`docker exec -i ... cat > ...`) "
        f"or env (`docker exec -e NAME=...`), never as argv arguments — see the "
        f"2026-05-24 demo-questions report for the leak that motivated this invariant.\n"
        f"Offenders:\n{rendered}"
    )


def test_invP003_discovery_no_argv_secret_patterns_across_scripts_dir() -> None:
    """Structural floor: every .sh under scripts/ is clean of argv-secret patterns.

    Catches future-script-additions that re-introduce the pattern. The
    per-script test above gives better failure attribution for the canonical
    onboard-sandbox.sh case; this test guarantees nothing new sneaks in.
    """
    offenders: list[tuple[Path, int, str, str]] = []
    for script in sorted(SCRIPTS_DIR.rglob("*.sh")):
        text = script.read_text()
        for i, name, line in _gather_offenders(text):
            offenders.append((script.relative_to(REPO_ROOT), i, name, line))
    rendered = "\n".join(
        f"  {p}:L{i:3d} ({name}): {line[:120]}" for p, i, name, line in offenders
    )
    assert not offenders, (
        f"INV-P003 violations across scripts/:\n{rendered}\n\n"
        "Move the secret-bearing payload to stdin (`docker exec -i ... cat > ...`) "
        "or to env (`docker exec -e NAME=...`); never put it on argv."
    )


def test_invP003_onboard_script_writes_authprofile_via_stdin() -> None:
    """Positive complement: the auth-profile must be written via docker exec stdin.

    Greps for the stdin-write shape. This is the structural opposite of the
    argv-interpolation patterns above — Phase 2 introduces this pattern
    when it removes the `nemoclaw exec ... python3 -c "..."` line.
    """
    text = ONBOARD_SCRIPT.read_text()
    # docker exec -i (interactive, takes stdin) anywhere followed by a
    # reference to auth-profiles.json.
    has_docker_exec_i_authprofile = bool(re.search(
        r"docker\s+exec[^|\n]*\s-i[^|\n]*auth-profiles\.json",
        text, re.DOTALL,
    ))
    has_cat_redirect_to_authprofile = bool(re.search(
        r"cat\s*>\s*[^|\n]*auth-profiles\.json", text,
    ))
    assert has_docker_exec_i_authprofile, (
        "INV-P003: expected `docker exec -i ... auth-profiles.json` pattern in "
        f"{ONBOARD_SCRIPT.relative_to(REPO_ROOT)}. The auth-profile write must "
        "use docker exec with stdin (-i) so the JSON payload never lands in "
        "argv. Phase 2 of onboard-persistent-agent-fix introduces this pattern."
    )
    assert has_cat_redirect_to_authprofile, (
        "INV-P003: expected `cat > ... auth-profiles.json` redirect pattern in "
        f"{ONBOARD_SCRIPT.relative_to(REPO_ROOT)}. The auth-profile write should "
        "redirect stdin into the target file inside the container."
    )
