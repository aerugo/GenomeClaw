"""Provisional `INV-D011` discovery: plugin install path follows the NemoClaw
canonical pattern.

Per Phase 2 of docs/plans/active/nemoclaw-canonical-integration/: any plugin
baked into a GenomeClaw sandbox image MUST live inside the OpenShell
Landlock RW baseline — i.e., under `/sandbox/<some-subdir>/<plugin-id>/`
or `/tmp/<some-subdir>/<plugin-id>/`. The current plan settles on
`/sandbox/build/<plugin-id>/`: inside `/sandbox/` (Landlock RW) and
OUTSIDE `/sandbox/.openclaw/extensions/` (which `openclaw plugins install
--link` refuses to accept as a source path because the directory tree is
auto-scanned by the runtime). Plugins MUST NOT live under `/opt/<plugin-id>/`,
`/usr/local/lib/<plugin-id>/`, or any other path outside the Landlock RW
baseline.

This discovery test greps the actual sandbox Dockerfile rather than
running a container, so it fails fast in any environment (no docker
required).

This invariant is provisional through Phase 5. Phase 6 promotes it to
`docs/reference/INVARIANTS.md` if the discipline holds.

Also asserts the base image is pinned by a version tag (`:v<version>`),
not the mutable `:latest`. `:latest` drift was the root cause behind the
2026-05-29 outage that motivated this plan — see spec.md root cause 2.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[4]
SANDBOX_DOCKERFILE = REPO_ROOT / "packages" / "nemoclaw-plugin" / "sandbox" / "Dockerfile"


def _read_dockerfile() -> str:
    assert SANDBOX_DOCKERFILE.exists(), (
        f"Sandbox Dockerfile missing at {SANDBOX_DOCKERFILE}. "
        "INV-D011 discovery cannot run."
    )
    return SANDBOX_DOCKERFILE.read_text()


_LANDLOCK_RW_PREFIXES = ("/sandbox/", "/tmp/")


def _non_comment_lines(text: str) -> list[str]:
    return [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def test_invD011_dockerfile_uses_landlock_baseline_path_for_plugin() -> None:
    """Plugin source must be staged inside the OpenShell Landlock RW baseline.

    The current plan stages at `/sandbox/build/genomeclaw/` (inside `/sandbox/`,
    outside `/sandbox/.openclaw/extensions/`). This test accepts any path
    inside the Landlock RW baseline (`/sandbox/*` or `/tmp/*`) so a future
    refactor that picks a different in-baseline location doesn't break the
    invariant; the structural rule is "must be readable by processes started
    via the OpenShell runtime", not "must be at one specific path".
    """
    text = _read_dockerfile()
    install_lines = [
        line for line in _non_comment_lines(text)
        if "openclaw plugins install" in line
    ]
    assert install_lines, (
        "INV-D011: sandbox Dockerfile does not invoke "
        "`openclaw plugins install`. The plugin must be registered with the "
        "OpenClaw runtime; file-drop alone is not auto-discovered in nemoclaw "
        "v0.0.50 — see work-notes Phase 1."
    )
    for line in install_lines:
        # Extract the source path argument (first non-flag token after `install`).
        tokens = re.findall(r"\S+", line)
        path_arg: str | None = None
        seen_install = False
        for tok in tokens:
            if tok == "install":
                seen_install = True
                continue
            if seen_install and not tok.startswith("-"):
                path_arg = tok
                break
        assert path_arg is not None, (
            f"INV-D011: could not parse the source path argument from "
            f"`openclaw plugins install` line: {line!r}"
        )
        assert path_arg.startswith(_LANDLOCK_RW_PREFIXES), (
            f"INV-D011: `openclaw plugins install` source path {path_arg!r} is "
            f"not under the Landlock RW baseline (must start with one of "
            f"{_LANDLOCK_RW_PREFIXES!r}). The plugin must live inside the "
            "baseline so `nemoclaw connect`, the dashboard, and the TUI can "
            f"read it. Offending line: {line!r}"
        )


def test_invD011_dockerfile_does_not_reference_legacy_opt_path() -> None:
    """No non-comment line in the Dockerfile may reference `/opt/genomeclaw/`.

    Comments are allowed (they preserve hard-won historical context about
    why the canonical-path migration happened). The structural concern is
    that no `COPY` / `RUN` / `WORKDIR` / `ENV` directive lands the plugin
    or its assets under the legacy Landlock-blocked path.
    """
    text = _read_dockerfile()
    code_lines = [
        line for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    legacy_refs = [line for line in code_lines if "/opt/genomeclaw" in line]
    assert not legacy_refs, (
        "INV-D011: sandbox Dockerfile still references the legacy `/opt/genomeclaw` "
        f"path in non-comment code (offending lines: {legacy_refs!r}). That path is "
        "outside the OpenShell Landlock baseline; processes started via NemoClaw's "
        "runtime (dashboard / connect / TUI) fail with EACCES when trying to load "
        "the plugin from there."
    )


def test_invD011_base_image_pinned_by_version_tag() -> None:
    """`FROM ghcr.io/nvidia/nemoclaw/sandbox-base:vX.Y.Z` (not `:latest`)."""
    text = _read_dockerfile()
    # Allow ARG default for the base image. Match either an explicit FROM line
    # or the ARG that supplies the default. Both must point at a versioned tag.
    for line in text.splitlines():
        m = re.match(
            r"^\s*(?:FROM|ARG\s+SANDBOX_BASE=)\s*ghcr\.io/nvidia/nemoclaw/sandbox-base[:@](\S+)",
            line,
        )
        if not m:
            continue
        pin = m.group(1)
        if pin == "latest":
            pytest.fail(
                "INV-D011: sandbox base image is pinned to `:latest`, which "
                "drifts silently against the local docker image cache. Pin to "
                "`:v<nemoclaw-version>` (or a `@sha256:` digest) matching the "
                f"host `nemoclaw --version`. Offending line: {line!r}"
            )
        # Acceptable: `:v0.0.50`, `:v0.1.0`, `@sha256:<64-hex>`.
        if pin.startswith("v") and re.match(r"^v\d+\.\d+\.\d+", pin):
            return
        if pin.startswith("sha256:") and re.match(r"^sha256:[0-9a-f]{64}$", pin):
            return
        pytest.fail(
            f"INV-D011: base image pin {pin!r} is not a recognized stable form "
            "(expected `:vX.Y.Z` or `@sha256:<64-hex>`). Offending line: {line!r}"
        )
    pytest.fail(
        "INV-D011: could not find a `FROM ghcr.io/nvidia/nemoclaw/sandbox-base` "
        "line or `ARG SANDBOX_BASE=` default in the sandbox Dockerfile."
    )


def test_invD011_no_other_sandbox_dockerfiles_use_opt_install_path() -> None:
    """Discovery: any sandbox Dockerfile under `packages/*/sandbox/` must not
    install plugins under `/opt/<plugin-id>/`. Provisional until Phase 6.

    The toolkit image (`packages/toolkit/Dockerfile`) is intentionally OUT of
    scope — it is a host-side bioinformatics container, not a NemoClaw plugin
    sandbox, and its `/opt/genomeclaw/toolkit/` path is unrelated to the
    Landlock baseline."""
    sandbox_dockerfiles = list((REPO_ROOT / "packages").glob("*/sandbox/Dockerfile"))
    assert sandbox_dockerfiles, "no sandbox Dockerfiles found under packages/*/sandbox/"
    offenders: list[tuple[Path, list[str]]] = []
    for df in sandbox_dockerfiles:
        text = df.read_text()
        bad = [
            line for line in text.splitlines()
            if re.search(r"(?:COPY|RUN .*install).*\s/opt/[a-z0-9_-]+(?:/|$|\s)", line)
        ]
        if bad:
            offenders.append((df, bad))
    assert not offenders, (
        "INV-D011: sandbox Dockerfile(s) install/copy into `/opt/<plugin-id>/`, "
        "which is outside the OpenShell Landlock baseline. Move to "
        f"`/sandbox/.openclaw/extensions/<plugin-id>/`. Offenders: {offenders!r}"
    )
