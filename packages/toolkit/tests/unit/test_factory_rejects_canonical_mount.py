"""Phase 6 — factory rejects canonical-mount paths in DooD context.

The Phase 5 smoke v6 surfaced this gap: ``SiblingMountablePath`` accepted
``/mnt/genomeclaw/scratch/foo`` even though that path exists only inside
the toolkit container. When the wrapper forwarded it to pgsc_calc/Nextflow,
DooD-spawned siblings received a path that wasn't resolvable on the host
filesystem and `.command.run` not-found errors followed.

Phase 6 tightens the factory: canonical-mount paths are REJECTED with a
fixable hint naming the host-form equivalent. Callers must pass host-form
paths (under a ``GENOMECLAW_<SUB>_DIR`` prefix the shim publishes).

This is the canonical implementation of the INV-D006 tightening; see
[docs/plans/active/path-crossing-discipline/phases/phase-6.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-6.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Test 1 — canonical-mount path is rejected with a translated hint
# ---------------------------------------------------------------------------


def test_factory_rejects_canonical_mount_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """``/mnt/genomeclaw/scratch/foo`` raises ``DooDPathError`` whose message
    names the host-form alternative computed from ``GENOMECLAW_SCRATCH_DIR``."""
    from genomeclaw_toolkit.prep._paths import DooDPathError, as_sibling_mountable

    monkeypatch.setenv("GENOMECLAW_SCRATCH_DIR", "/Volumes/Genome_Work/genomeclaw/_scratch")
    # The host root must also be on the GENOMECLAW_HOST_ROOTS allowlist for the
    # error-translation logic to make sense (it's the same set of prefixes the
    # factory accepts when the caller uses the host-form). The test fixture
    # is loose here — the factory must reject the canonical-mount form
    # regardless of HOST_ROOTS state.
    monkeypatch.setenv("GENOMECLAW_HOST_ROOTS", "/Volumes/Genome_Work/genomeclaw/_scratch")

    with pytest.raises(DooDPathError) as exc_info:
        as_sibling_mountable(Path("/mnt/genomeclaw/scratch/foo"))

    msg = str(exc_info.value)
    assert "/mnt/genomeclaw" in msg, msg
    # The hint names the host-form path the caller should use instead.
    assert "/Volumes/Genome_Work/genomeclaw/_scratch/foo" in msg, msg
    # The hint references the env var the factory used for translation.
    assert "GENOMECLAW_SCRATCH_DIR" in msg, msg


# ---------------------------------------------------------------------------
# Test 2 — parametrized over every canonical mount subdir
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "subdir,env_var",
    [
        ("raw", "GENOMECLAW_RAW_DIR"),
        ("reference", "GENOMECLAW_REF_DIR"),
        ("derived", "GENOMECLAW_DERIVED_DIR"),
        ("scratch", "GENOMECLAW_SCRATCH_DIR"),
    ],
)
def test_factory_rejects_each_canonical_mount_subdir(
    subdir: str,
    env_var: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each ``/mnt/genomeclaw/<subdir>/x`` raises ``DooDPathError`` whose
    message references the matching ``GENOMECLAW_<SUB>_DIR`` env var.

    Verifies the factory's translation table is wired up for ALL four
    canonical subdirs, not just one."""
    from genomeclaw_toolkit.prep._paths import DooDPathError, as_sibling_mountable

    host_root = f"/Volumes/Genome_Work/genomeclaw/_{subdir}"
    monkeypatch.setenv(env_var, host_root)
    monkeypatch.setenv("GENOMECLAW_HOST_ROOTS", host_root)

    with pytest.raises(DooDPathError) as exc_info:
        as_sibling_mountable(Path(f"/mnt/genomeclaw/{subdir}/sample.vcf"))

    msg = str(exc_info.value)
    assert env_var in msg, (
        f"DooDPathError must reference {env_var} for the {subdir} subdir; got: {msg!r}"
    )
    assert f"{host_root}/sample.vcf" in msg, (
        f"DooDPathError must include the translated host-form path; got: {msg!r}"
    )


# ---------------------------------------------------------------------------
# Test 3 — host-form path is accepted (regression cover)
# ---------------------------------------------------------------------------


def test_factory_accepts_host_form_path(tmp_path: Path) -> None:
    """Host-form paths under a ``GENOMECLAW_HOST_ROOTS`` prefix are still
    accepted. The tightening targets canonical-mount paths only; the
    host-form path is the one true sibling-mountable shape.

    The autouse conftest fixture sets ``GENOMECLAW_HOST_ROOTS`` to include
    ``tmp_path`` + ``/private`` (the macOS ``tmp_path`` symlink target),
    so paths under tmp_path satisfy the factory's prefix check."""
    from genomeclaw_toolkit.prep._paths import SiblingMountablePath, as_sibling_mountable

    target = tmp_path / "_scratch" / "merged.vcf.gz"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.touch()

    result = as_sibling_mountable(target)
    assert isinstance(result, SiblingMountablePath)
