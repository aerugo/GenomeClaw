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
is grepped for the forbidden argv-interpolation patterns. Positive
tests on `scripts/onboard-sandbox.sh` assert the OpenAI key reaches the
container only via env (`docker exec -e OPENAI_API_KEY=...`) and that no
literal key is written into `auth-profiles.json` (deleted in
nemoclaw-canonical-integration Phase 3, Facet A2 — see that plan's
work-notes for the privacy-review finding that motivated removing it).

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

# INV-V001-allow:
#
# The regex patterns below detect **shell-argv anti-pattern shapes** for the
# INV-P003 secret-leak rule. This is structural detection of the forbidden
# *form* of a shell invocation (python -c with b64decode of a $VAR; bash -c
# interpolating a secret-named env var; --key/--secret/--token flags with $VAR
# values), NOT enumeration of paraphrases that a language model might use.
# The target language here is shell, not LLM output.
#
# Different class than INV-V001's banned methodology (forbidden-phrase
# enumeration over agent reply text). The structural-regex-over-source-code
# pattern is explicitly allowed.

# INV-V001-allow: structural shell-argv anti-pattern detection (see annotation above for full rationale)
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


def _noncomment_lines(text: str) -> list[tuple[int, str]]:
    """(line_no, line) for lines that aren't blank or shell comments."""
    out: list[tuple[int, str]] = []
    for i, line in enumerate(text.splitlines(), start=1):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        out.append((i, line))
    return out


def test_invP003_onboard_writes_no_literal_key_to_authprofiles() -> None:
    """No literal OpenAI key is written into `auth-profiles.json` (Facet A2).

    The 2026-05-30 privacy review flagged the prior stdin write of a
    `"key": "<literal>"` field into the container's auth-profiles.json as
    HIGH severity (durable plaintext secret in the writable layer / any
    `docker commit`). It was deleted because the gateway's env-ref provider
    (key supplied via `docker exec -e OPENAI_API_KEY`, INV-P003-clean) already
    covers the agent — verified empirically that the agent completes an LLM
    turn with no auth-profiles.json present. This test keeps that write from
    silently returning.
    """
    text = ONBOARD_SCRIPT.read_text()
    # A non-comment line that writes (cat-redirect or tee) into auth-profiles.json
    # is the regression. Comments referencing it (explaining the deletion) are fine.
    for line_no, line in _noncomment_lines(text):
        if "auth-profiles.json" not in line:
            continue
        assert not re.search(r"(cat\s*>|tee)\s*[^|\n]*auth-profiles\.json", line), (
            f"INV-P003: {ONBOARD_SCRIPT.relative_to(REPO_ROOT)}:L{line_no} writes "
            "auth-profiles.json. The literal-key write was deleted in Facet A2 "
            "(the gateway env-ref covers the agent); do not reintroduce a "
            f"plaintext-secret file. Offending line: {line.strip()[:120]}"
        )


def test_invP003_openai_key_only_in_env_positions() -> None:
    """The OpenAI key VALUE expands only inside a `docker exec -e` env flag.

    Reviewer guard (2026-05-30): the key value must reach the container via
    `docker exec -e OPENAI_API_KEY="${OPENAI_API_KEY}"` (env, not argv) — never
    inside a `-c "..."` payload, a file write, or a CLI flag value. We look for
    actual value-expansions (`$OPENAI_API_KEY` / `${OPENAI_API_KEY}`); a bare
    mention of the string (e.g. in a log `echo`) or the shell assignment that
    DEFINES the var (`export OPENAI_API_KEY="$OPEN_AI_API_KEY"`, which expands
    `$OPEN_AI_API_KEY`, not the key) are not value-leaks. Structural shell
    inspection (INV-V001-allow).
    """
    text = ONBOARD_SCRIPT.read_text()
    # A real value-expansion: `$OPENAI_API_KEY` / `${OPENAI_API_KEY}` NOT preceded
    # by a backslash. Escaped `\$OPENAI_API_KEY` (printed literally inside a help
    # `echo`, e.g. the "Next steps" block) does not expand and is not a leak.
    key_value_expansion = re.compile(r"(?<!\\)\$\{?OPENAI_API_KEY\}?")
    env_flag = re.compile(r'-e\s+OPENAI_API_KEY="?\$\{?OPENAI_API_KEY\}?"?')
    for line_no, line in _noncomment_lines(text):
        if not key_value_expansion.search(line):
            continue
        assert env_flag.search(line), (
            f"INV-P003: {ONBOARD_SCRIPT.relative_to(REPO_ROOT)}:L{line_no} expands the "
            "OPENAI_API_KEY value outside a `docker exec -e OPENAI_API_KEY=...` env "
            "flag. The key value must travel via env, never argv or a file payload. "
            f"Offending line: {line.strip()[:120]}"
        )
