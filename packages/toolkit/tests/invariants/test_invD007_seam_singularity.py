"""INV-D007 discovery — the shim is the canonical seam for DooD subcommands.

Walks ``bin/`` for executable scripts (other than ``bin/genomeclaw`` itself).
For each, asserts that no ``docker run`` string appears outside the allow-
list. The seam-singularity rule prevents bespoke ``docker run`` invocations
that duplicate shim logic — the Phase 5 smoke surfaced this as the
``bin/genomeclaw-prs-smoke`` bypass that survived Phases 1–3 and started
silently failing once the shim's behaviour drifted from the driver's
reimplementation.

Adding a new script that needs a bespoke ``docker run`` requires:
1. A justification comment on the line.
2. Adding the script to ``_ALLOWED_BESPOKE_DOCKER_RUN`` below + a code review.

Phase 6 starts the allow-list empty; the smoke driver migration in
the same phase keeps it empty.

Phase plan: [phases/phase-6.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-6.md)
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_BIN_DIR = _REPO_ROOT / "bin"

# Scripts allowed to invoke ``docker run`` directly. Empty by design — every
# DooD subcommand goes through ``bin/genomeclaw`` (the shim). If you need to
# add an entry, justify it in the PR and accept the review burden.
_ALLOWED_BESPOKE_DOCKER_RUN: set[str] = set()

# ``bin/genomeclaw`` itself IS the shim, so it builds the canonical ``docker
# run`` command. Exempt by name.
_SHIM_NAME = "genomeclaw"


def _executable_scripts(bin_dir: Path) -> list[Path]:
    """All regular files under ``bin/`` that are exec-bit set."""
    if not bin_dir.is_dir():
        return []
    return [p for p in bin_dir.iterdir() if p.is_file() and (p.stat().st_mode & 0o111)]


def test_invD007_no_bespoke_docker_run_in_repo_scripts() -> None:
    """Scripts under ``bin/`` must not invoke ``docker run`` directly.

    The seam-singularity rule: ``bin/genomeclaw`` is the only sanctioned
    entry-point that constructs ``docker run`` argv. Other scripts go
    through the shim so the path-crossing-discipline invariants apply
    uniformly.
    """
    scripts = _executable_scripts(_BIN_DIR)
    assert scripts, f"no executable scripts under {_BIN_DIR} — wrong path?"

    violations: list[tuple[str, int, str]] = []
    for script in scripts:
        if script.name == _SHIM_NAME or script.name in _ALLOWED_BESPOKE_DOCKER_RUN:
            continue
        text = script.read_text(errors="replace")
        for i, line in enumerate(text.splitlines(), start=1):
            stripped = line.lstrip()
            if stripped.startswith("#"):
                continue
            if "docker run" in line:
                violations.append((script.name, i, line.strip()))

    assert not violations, (
        "INV-D007 violation: bespoke `docker run` found in scripts that aren't on "
        "the allow-list. Use bin/genomeclaw (the shim) instead. Violations: "
        f"{violations}"
    )
