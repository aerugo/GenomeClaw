"""``SiblingMountablePath`` + factory + ``DooDPathError``.

A typed boundary for the "host paths that flow into DooD-spawned siblings
must be visible on the host filesystem" rule. Constructed via
:func:`as_sibling_mountable`. Wrappers that build sibling-container mount
arguments (``-v <host>:<container>`` for pgsc_calc's nextflow tasks,
bcftools shards, etc.) declare this type for their path parameters; the
factory call at the orchestrator boundary rejects container-local paths
BEFORE any subprocess fires.

Failure mode this prevents: the Phase-5 smoke v3 lived here. The
orchestrator staged a merged VCF under
:func:`ephemeral_scratch_base` (``/tmp/genomeclaw-scratch/...`` — container-
local). pgsc_calc's siblings couldn't see it; nextflow returned rc=1 with
``No such file`` against a path that DID exist inside the parent
container.

This is the canonical implementation of ``INV-D006`` (DooD-Safe Path
Annotation). See
[docs/plans/active/path-crossing-discipline/](../../../../docs/plans/active/path-crossing-discipline/)
for the plan that introduced it.

Mount prefix discovery:

- The canonical ``/mnt/genomeclaw`` prefix is always accepted (the
  toolkit container ships with this mount in production).
- ``GENOMECLAW_HOST_ROOTS`` is a colon-separated list of additional
  prefixes the shim populates with the deployment's actual host roots
  (e.g., ``/Volumes/Genome_Work/genomeclaw``). The Phase-1 identical-path
  overlay establishes those mounts; the factory verifies the wrapper
  consumes them.

Negative case: ``/tmp/genomeclaw-scratch`` (the default of
:func:`ephemeral_scratch_base`) is explicitly rejected even when listed
in ``GENOMECLAW_HOST_ROOTS`` — the path is container-local by design.
"""

from __future__ import annotations

import os
from pathlib import Path


class DooDPathError(ValueError):
    """A path bound for a DooD-spawned sibling is not host-visible.

    Raised at the wrapper boundary so a non-sibling-mountable path fails
    BEFORE bcftools / pgsc_calc / nextflow run. The message names a
    fixable alternative (``shard_scratch``, ``work_dir``, or the canonical
    mount roots) rather than just "rejected".
    """


# Subclass the platform-specific concrete ``Path`` class (``PosixPath`` on
# darwin/linux; ``WindowsPath`` on win) rather than the abstract ``Path``
# itself. Python 3.11 raises ``AttributeError: type object
# 'SiblingMountablePath' has no attribute '_flavour'`` when subclassing
# ``Path`` directly — the abstract class delegates flavour to its concrete
# subclass at instantiation. Python 3.12+ supports the direct ``Path``
# subclass natively; this idiom is the cross-version-compatible one. The
# toolkit image ships Python 3.11; the host dev venv may be 3.13.
class SiblingMountablePath(type(Path())):  # type: ignore[misc]
    """A ``Path`` validated as visible on the host filesystem.

    Constructed via :func:`as_sibling_mountable`. Carrying this type
    signals that the path is rooted under a sibling-mountable prefix —
    either the canonical ``/mnt/genomeclaw/...`` mount or a deployment
    root advertised via ``GENOMECLAW_HOST_ROOTS`` — and is safe to write
    into a DooD sibling's ``-v <host>:<container>`` invocation.

    Wrappers that build sibling-container argv (``_write_pgsc_calc_samplesheet``,
    ``_build_pgsc_calc_argv``, ``compute_prs_with_coverage_fill``) annotate
    their path parameters with this type. mypy + the INV-D006 invariant test
    enforce the annotation; the factory enforces the runtime check.
    """


# Canonical-mount paths inside the toolkit container. These exist ONLY
# inside the container (Phase 1's shim bind-mounts the host roots here).
# DooD siblings spawned by the host daemon cannot resolve them. Phase 6
# tightens the factory: callers must pass host-form paths (under one of
# the four ``GENOMECLAW_<SUB>_DIR`` prefixes the shim publishes).
_CANONICAL_MOUNT_ROOT = "/mnt/genomeclaw"

# Per-subdir translation table. The canonical mount subdir maps to the
# env var the shim publishes for the corresponding host-form prefix.
# ``/mnt/genomeclaw/<sub>/x`` → ``$GENOMECLAW_<ENV>_DIR/x``.
_CANONICAL_MOUNT_TRANSLATION: dict[str, str] = {
    "raw": "GENOMECLAW_RAW_DIR",
    "reference": "GENOMECLAW_REF_DIR",
    "derived": "GENOMECLAW_DERIVED_DIR",
    "scratch": "GENOMECLAW_SCRATCH_DIR",
}

# The container-local prefix produced by :func:`ephemeral_scratch_base`.
# Explicitly rejected because it's not visible to DooD siblings — even when
# the deployment lists ``/tmp`` in ``GENOMECLAW_HOST_ROOTS``, ephemeral
# scratch must surface as a typed error pointing at ``shard_scratch``.
_EPHEMERAL_SCRATCH_PREFIX = "/tmp/genomeclaw-scratch"


def _host_roots_from_env() -> list[Path]:
    """Parse ``GENOMECLAW_HOST_ROOTS`` (colon-separated) into Paths.

    The shim populates this when it sets up the Phase-1 identical-path
    overlay. Empty / unset returns an empty list — only the canonical
    ``/mnt/genomeclaw`` prefix applies.
    """
    raw = os.environ.get("GENOMECLAW_HOST_ROOTS", "")
    if not raw:
        return []
    return [Path(part) for part in raw.split(":") if part]


def _is_relative_to(child: Path, parent: Path) -> bool:
    """Path.is_relative_to backport-safe wrapper.

    The python 3.9 ``is_relative_to`` exists on 3.13 too; this indirection
    keeps the call site readable.
    """
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        return False


def _translate_canonical_mount_to_host_form(p: Path) -> tuple[str, str] | None:
    """If ``p`` is under ``/mnt/genomeclaw/<sub>/...``, return ``(env_var,
    translated_path_string)`` where ``env_var`` names the host-form env var
    and ``translated_path_string`` is the equivalent host-form path.

    Returns ``None`` when ``p`` is not under the canonical mount.

    The translation is a *hint* for the error message; the factory still
    raises. Callers fix their code to use the host-form path directly.
    """
    s = str(p)
    if not s.startswith(_CANONICAL_MOUNT_ROOT + "/"):
        return None
    relative = s[len(_CANONICAL_MOUNT_ROOT) + 1 :]
    if "/" in relative:
        subdir, _, tail = relative.partition("/")
    else:
        subdir, tail = relative, ""
    env_var = _CANONICAL_MOUNT_TRANSLATION.get(subdir)
    if env_var is None:
        return None
    host_root = os.environ.get(env_var, f"${env_var}")
    translated = f"{host_root}/{tail}" if tail else host_root
    return env_var, translated


def as_sibling_mountable(p: Path) -> SiblingMountablePath:
    """Validate ``p`` is host-visible; return a :class:`SiblingMountablePath`.

    The factory MUST be called at the orchestrator boundary before any
    wrapper that passes ``p`` into a DooD sibling's mount argument runs.
    A path that fails the check produces :class:`DooDPathError` with a
    fixable hint.

    Idempotent: passing in an already-wrapped :class:`SiblingMountablePath`
    returns a valid instance (no re-validation needed; the prefix-match
    re-check is cheap so we run it anyway for safety).

    Accepts:

    * Anything under a prefix in ``GENOMECLAW_HOST_ROOTS`` (host-form
      paths, populated by the shim from the deployment's canonical roots).

    Rejects (with translated hint):

    * Anything under ``/mnt/genomeclaw/<sub>/...`` (canonical-mount paths
      that exist ONLY inside the toolkit container). Phase 6 (INV-D006
      tightening): DooD siblings spawned by the host daemon cannot
      resolve container-only paths. Use the host-form equivalent named
      in the error message.
    * Anything under ``/tmp/genomeclaw-scratch`` (ephemeral scratch is
      container-local by INV-D003 design).
    * Anything not matching the host-form prefixes.
    """
    p_resolved = p.resolve() if p.exists() else Path(os.path.abspath(str(p)))
    s_resolved = str(p_resolved)

    # Reject canonical-mount paths first — they're the most common mistake
    # post-Phase-1 (the toolkit container has the canonical mount; callers
    # naturally type paths in that form). Phase 5 smoke v6 surfaced the
    # silent failure: pgsc_calc spawned siblings via DooD, siblings tried
    # to bind-mount /mnt/genomeclaw/... from the host fs (where it doesn't
    # exist) → ``.command.run: No such file`` and exit 127.
    if s_resolved.startswith(_CANONICAL_MOUNT_ROOT + "/") or s_resolved == _CANONICAL_MOUNT_ROOT:
        translation = _translate_canonical_mount_to_host_form(p_resolved)
        if translation is not None:
            env_var, host_form = translation
            raise DooDPathError(
                f"{p_resolved} is a canonical-mount path (exists only inside "
                f"the toolkit container). DooD-spawned siblings cannot resolve "
                f"it against the host filesystem. Use the host-form equivalent: "
                f"{host_form} (from {env_var})."
            )
        raise DooDPathError(
            f"{p_resolved} is under the canonical-mount root {_CANONICAL_MOUNT_ROOT} "
            "but doesn't map to a known subdir (raw/reference/derived/scratch). "
            "Canonical-mount paths exist only inside the toolkit container and "
            "are not sibling-mountable. Use a host-form path under GENOMECLAW_HOST_ROOTS."
        )

    # Explicit rejection of ephemeral scratch (Phase 3 — INV-D003 negative case).
    if s_resolved.startswith(_EPHEMERAL_SCRATCH_PREFIX):
        raise DooDPathError(
            f"{p_resolved} is rooted under ephemeral_scratch_base() (container-"
            "local) and is NOT visible to DooD siblings. Use shard_scratch(...) "
            "or work_dir (host-visible canonical mount) for paths that must "
            "flow into pgsc_calc / nextflow / bcftools-shard siblings."
        )

    prefixes: list[Path] = list(_host_roots_from_env())
    if not any(_is_relative_to(p_resolved, prefix) for prefix in prefixes):
        raise DooDPathError(
            f"{p_resolved} is not under any sibling-mountable prefix "
            f"(GENOMECLAW_HOST_ROOTS={[str(x) for x in prefixes]}). "
            "Either relocate the file to a host-form canonical root, or "
            "extend GENOMECLAW_HOST_ROOTS via the shim's identical-path "
            "overlay (INV-D005)."
        )
    return SiblingMountablePath(p_resolved)


__all__ = [
    "DooDPathError",
    "SiblingMountablePath",
    "as_sibling_mountable",
]
