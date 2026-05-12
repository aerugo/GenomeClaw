"""Phase 2 — destructive setup runner: executor orchestration + invariants.

The executor runs a 12-step destructive sequence (see phases/phase-2.md).
Tests use a FakeDestructivePlatform that records every method call and
can inject failures, plus an actual ``tmp_path`` for the Python-only
operations (mkdir_layout, copy, hash verify, yaml write).
"""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

# ---------------------------------------------------------------------------
# Test platform
# ---------------------------------------------------------------------------


@dataclass
class _CallRecord:
    method: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class FakeDestructivePlatform:
    """Records every destructive call; can inject failures per-method.

    Real side effects only for ``partition_disk_apfs`` (creates a fake
    mount-point dir under ``tmp_path``) and ``copy_file_with_sha``
    (writes the real bytes through, hashing both ends). Everything else
    is recorded only.
    """

    def __init__(self, *, tmp_root: Path) -> None:
        self.tmp_root = tmp_root
        self.call_log: list[_CallRecord] = []
        self.failure_modes: dict[str, str] = {}
        # State the fakes track:
        self.colima_running = True
        self.partition_mount: Path | None = None
        self.copy_corrupts: bool = False  # if True, copy_nebula writes corrupt bytes
        # Phase 1 surface stays the same — pre-populated by fixtures:
        self.volumes: list = []
        self.identities: dict = {}
        self.bcftools_status: str = "ok"
        self.bcftools_stderr: str = ""

    # ---- Phase 1 surface (unchanged) -----------------------------------

    def list_volumes(self):
        from genomeclaw_toolkit.prep.setup._types import Volume

        return [Volume(**v) if isinstance(v, dict) else v for v in self.volumes]

    def read_drive_identity(self, volume):
        from genomeclaw_toolkit.prep.setup._types import DriveIdentity

        ident = self.identities.get(volume.parent_disk)
        return DriveIdentity(**ident) if isinstance(ident, dict) else ident

    def bcftools_view_header(self, vcf):
        return self.bcftools_status, self.bcftools_stderr

    # ---- Phase 2 surface (destructive) ----------------------------------

    def _record(self, method: str, *args, **kwargs) -> None:
        self.call_log.append(_CallRecord(method=method, args=args, kwargs=kwargs))

    def _maybe_fail(self, method: str) -> None:
        from genomeclaw_toolkit.prep.setup.execute import DestructiveStepError

        mode = self.failure_modes.get(method)
        if mode == "return_code_2":
            raise DestructiveStepError(
                step_name=method, return_code=2, stderr="injected failure: return_code_2"
            )
        if mode == "stderr_only":
            raise DestructiveStepError(
                step_name=method, return_code=1, stderr="injected failure: stderr_only"
            )

    def colima_status(self) -> str:
        self._record("colima_status")
        return "running" if self.colima_running else "stopped"

    def colima_stop(self) -> None:
        self._record("colima_stop")
        self._maybe_fail("colima_stop")
        self.colima_running = False

    def colima_start(self) -> None:
        self._record("colima_start")
        self._maybe_fail("colima_start")
        self.colima_running = True

    def unmount_disk(self, parent_disk: str) -> None:
        self._record("unmount_disk", parent_disk)
        self._maybe_fail("unmount_disk")

    def partition_disk_apfs(self, parent_disk: str, label: str) -> Path:
        self._record("partition_disk_apfs", parent_disk, label)
        self._maybe_fail("partition_disk_apfs")
        # Side effect: create the fake mount point under tmp_root.
        mount = self.tmp_root / label
        mount.mkdir(parents=True, exist_ok=True)
        self.partition_mount = mount
        return mount

    def verify_mounts_via_shim(self, target_root: Path) -> None:
        self._record("verify_mounts_via_shim", target_root)
        self._maybe_fail("verify_mounts_via_shim")

    def copy_file_with_sha(self, src: Path, dst: Path) -> tuple[str, str]:
        """Real(ish) copy that hashes both sides; if ``copy_corrupts`` is
        set, writes wrong bytes so the verify step trips."""
        self._record("copy_file_with_sha", src, dst)
        self._maybe_fail("copy_file_with_sha")
        dst.parent.mkdir(parents=True, exist_ok=True)
        if self.copy_corrupts:
            dst.write_bytes(b"corrupt")
        else:
            shutil.copyfile(src, dst)
        src_sha = hashlib.sha256(src.read_bytes()).hexdigest()
        dst_sha = hashlib.sha256(dst.read_bytes()).hexdigest()
        return src_sha, dst_sha


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_destructive_platform(tmp_path: Path) -> FakeDestructivePlatform:
    """A FakeDestructivePlatform pre-populated with two distinct fake disks
    (a system disk for the source, an external drive for the target)."""
    nebula = tmp_path / "internal_disk" / "data" / "raw" / "MPNRGLQ2K"
    nebula.mkdir(parents=True)
    # Tiny CRAM-shaped payload so the SHAs are deterministic.
    (nebula / "MPNRGLQ2K.cram").write_bytes(b"FAKECRAM" * 1024)
    (nebula / "MPNRGLQ2K.cram.crai").write_bytes(b"FAKECRAI")
    (nebula / "MPNRGLQ2K.vcf.gz").write_bytes(b"\x1f\x8b\x08\x04FAKEVCF")
    (nebula / "MPNRGLQ2K.vcf.gz.tbi").write_bytes(b"FAKETBI")

    plat = FakeDestructivePlatform(tmp_root=tmp_path)
    plat.volumes = [
        {
            "name": "Macintosh HD",
            "mount_point": str(tmp_path / "internal_disk"),
            "size_bytes": 500 * 1000**3,
            "parent_disk": "disk3",
            "filesystem": "apfs",
            "is_system_disk": True,
        },
        {
            "name": "Genome",
            "mount_point": str(tmp_path / "external_drive"),
            "size_bytes": 500 * 1000**3,
            "parent_disk": "disk4",
            "filesystem": "exfat",
            "is_system_disk": False,
        },
    ]
    (tmp_path / "external_drive").mkdir()
    plat.identities = {
        "disk3": {
            "model": "APPLE SSD",
            "firmware": "internal",
            "capacity_gb": 500,
            "parent_disk": "disk3",
            "bus_type": "Internal",
        },
        "disk4": {
            "model": "Samsung Portable SSD T7 Shield",
            "firmware": "GBD8M3",
            "capacity_gb": 500,
            "parent_disk": "disk4",
            "bus_type": "USB",
        },
    }
    return plat


@pytest.fixture
def synthetic_plan(fake_destructive_platform, tmp_path: Path):
    """Build a SetupPlan by invoking the Phase-1 build_plan against the fake."""
    from genomeclaw_toolkit.prep.setup.detect import build_plan

    nebula_dir = tmp_path / "internal_disk" / "data" / "raw" / "MPNRGLQ2K"
    return build_plan(
        nebula_dir=nebula_dir,
        target_mount="Genome",
        platform=fake_destructive_platform,
    )


# ---------------------------------------------------------------------------
# 1. Typed-confirmation gate
# ---------------------------------------------------------------------------


def test_executor_refuses_without_typed_confirmation(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """Wrong phrase → ConfirmationMismatchError; no destructive call happens."""
    from genomeclaw_toolkit.prep.setup.execute import (
        ConfirmationMismatchError,
        execute,
    )

    with pytest.raises(ConfirmationMismatchError):
        execute(
            synthetic_plan,
            fake_destructive_platform,
            confirmation_phrase="WIPE wrong-name",
            audit_log_dir=tmp_path / ".genomeclaw",
            colima_yaml_path=tmp_path / "fake_colima.yaml",
        )

    # No destructive method was called.
    destructive = {
        "colima_stop",
        "unmount_disk",
        "partition_disk_apfs",
        "colima_start",
        "verify_mounts_via_shim",
        "copy_file_with_sha",
    }
    called = {c.method for c in fake_destructive_platform.call_log}
    assert called.isdisjoint(destructive), f"unexpected destructive call(s): {called & destructive}"


# ---------------------------------------------------------------------------
# 2. Step ordering (the load-bearing test)
# ---------------------------------------------------------------------------


def test_executor_runs_steps_in_required_order(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """Correct phrase → 9 destructive steps complete in spec order."""
    from genomeclaw_toolkit.prep.setup.execute import execute

    audit_log = execute(
        synthetic_plan,
        fake_destructive_platform,
        confirmation_phrase=synthetic_plan.confirmation_phrase,
        audit_log_dir=tmp_path / ".genomeclaw",
        colima_yaml_path=tmp_path / "fake_colima.yaml",
    )

    # Audit log records `complete` events in spec order; setup_started /
    # setup_completed are bracket events around the destructive steps.
    events = [json.loads(line) for line in audit_log.read_text().splitlines() if line.strip()]
    completes = [
        e["step"]
        for e in events
        if e["phase"] == "complete" and e["step"] not in ("setup_started", "setup_completed")
    ]
    expected = [
        "colima_stop",
        "unmount_disk",
        "partition_disk_apfs",
        "mkdir_layout",
        "copy_nebula",
        "verify_target_hashes",
        "write_colima_yaml",
        "colima_start",
        "verify_mounts_via_shim",
    ]
    assert completes == expected, f"step order mismatch: {completes}"


# ---------------------------------------------------------------------------
# 3-4. INV-D001 — source integrity
# ---------------------------------------------------------------------------


def test_invD001_executor_captures_source_hashes_before_destruction(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """INV-D001: source SHAs are written to audit log before any destructive op.

    Even if a destructive step fails *after* hashing, the log carries
    the pre-state record.
    """
    from genomeclaw_toolkit.prep.setup.execute import DestructiveStepError, execute

    fake_destructive_platform.failure_modes["unmount_disk"] = "return_code_2"

    audit_log_dir = tmp_path / ".genomeclaw"
    with pytest.raises(DestructiveStepError):
        execute(
            synthetic_plan,
            fake_destructive_platform,
            confirmation_phrase=synthetic_plan.confirmation_phrase,
            audit_log_dir=audit_log_dir,
        )

    # Find the audit log under audit_log_dir (it never got promoted because partition didn't run).
    logs = list(audit_log_dir.glob("setup-*.log"))
    assert logs, "audit log not written"
    events = [json.loads(line) for line in logs[0].read_text().splitlines() if line.strip()]
    started = next(e for e in events if e["step"] == "setup_started")
    sources = started["payload"]["source_hashes"]
    # All four Nebula files have a SHA recorded:
    names = {entry["name"] for entry in sources}
    assert names == {
        "MPNRGLQ2K.cram",
        "MPNRGLQ2K.cram.crai",
        "MPNRGLQ2K.vcf.gz",
        "MPNRGLQ2K.vcf.gz.tbi",
    }
    for entry in sources:
        assert len(entry["sha256"]) == 64  # hex SHA256


def test_invD001_executor_aborts_on_post_copy_hash_mismatch(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """INV-D001: post-copy SHA mismatch → DataIntegrityError; source intact."""
    from genomeclaw_toolkit.prep.setup.execute import DataIntegrityError, execute

    fake_destructive_platform.copy_corrupts = True

    nebula_dir = synthetic_plan.nebula.source_path
    pre_sha = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in nebula_dir.iterdir()
        if p.is_file()
    }

    audit_log_dir = tmp_path / ".genomeclaw"
    with pytest.raises(DataIntegrityError):
        execute(
            synthetic_plan,
            fake_destructive_platform,
            confirmation_phrase=synthetic_plan.confirmation_phrase,
            audit_log_dir=audit_log_dir,
        )

    # Source files unchanged.
    post_sha = {
        p.name: hashlib.sha256(p.read_bytes()).hexdigest()
        for p in nebula_dir.iterdir()
        if p.is_file()
    }
    assert pre_sha == post_sha, "executor mutated the source on hash-mismatch path"


# ---------------------------------------------------------------------------
# 5. INV-R001 — audit-log fields
# ---------------------------------------------------------------------------


def test_invR001_audit_log_carries_required_fields(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """INV-R001: completion event has versions, timestamps, paths, hash table."""
    from genomeclaw_toolkit.prep.setup.execute import execute

    audit_log = execute(
        synthetic_plan,
        fake_destructive_platform,
        confirmation_phrase=synthetic_plan.confirmation_phrase,
        audit_log_dir=tmp_path / ".genomeclaw",
        colima_yaml_path=tmp_path / "fake_colima.yaml",
    )

    events = [json.loads(line) for line in audit_log.read_text().splitlines() if line.strip()]
    completed = next(e for e in events if e["step"] == "setup_completed")
    p = completed["payload"]
    for required in (
        "started_at",
        "completed_at",
        "toolkit_version",
        "source_path",
        "target_partition",
        "target_parent_disk",
    ):
        assert required in p, f"missing field: {required}"


# ---------------------------------------------------------------------------
# 6-7. Audit-log shape (temp-then-promote, per-step events)
# ---------------------------------------------------------------------------


def test_audit_log_writes_temp_then_promotes_to_scratch(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """Initial writes go to ``audit_log_dir/setup-*.log``; after partition+mkdir
    succeed, the file is promoted to ``<scratch_dir>/setup.log`` and the temp is gone.
    """
    from genomeclaw_toolkit.prep.setup.execute import execute

    audit_log_dir = tmp_path / ".genomeclaw"
    final_path = execute(
        synthetic_plan,
        fake_destructive_platform,
        confirmation_phrase=synthetic_plan.confirmation_phrase,
        audit_log_dir=audit_log_dir,
        colima_yaml_path=tmp_path / "fake_colima.yaml",
    )
    # Final path lives under the partition mount, not the temp dir.
    assert "setup.log" in final_path.name
    assert "_scratch" in str(final_path)
    # No temp leftovers.
    leftovers = list(audit_log_dir.glob("setup-*.log"))
    assert not leftovers, f"temp audit log not cleaned up: {leftovers}"


def test_audit_log_writes_event_per_step(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """A clean run emits start+complete events for every step plus
    setup_started / setup_completed brackets."""
    from genomeclaw_toolkit.prep.setup.execute import execute

    audit_log = execute(
        synthetic_plan,
        fake_destructive_platform,
        confirmation_phrase=synthetic_plan.confirmation_phrase,
        audit_log_dir=tmp_path / ".genomeclaw",
        colima_yaml_path=tmp_path / "fake_colima.yaml",
    )
    events = [json.loads(line) for line in audit_log.read_text().splitlines() if line.strip()]
    starts = [e["step"] for e in events if e["phase"] == "start"]
    completes = [e["step"] for e in events if e["phase"] == "complete"]
    # 9 destructive steps each with start+complete, plus setup_started/setup_completed:
    assert len(starts) >= 9
    assert len(completes) >= 9
    assert events[0]["step"] == "setup_started"
    assert events[-1]["step"] == "setup_completed"


# ---------------------------------------------------------------------------
# 8. Failure propagation
# ---------------------------------------------------------------------------


def test_executor_propagates_subprocess_failure_with_diagnostics(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """Non-zero from a destructive method → DestructiveStepError carrying
    captured stderr; audit log gets a `phase=fail` event; subsequent steps
    are not attempted."""
    from genomeclaw_toolkit.prep.setup.execute import DestructiveStepError, execute

    fake_destructive_platform.failure_modes["partition_disk_apfs"] = "stderr_only"

    audit_log_dir = tmp_path / ".genomeclaw"
    with pytest.raises(DestructiveStepError) as exc:
        execute(
            synthetic_plan,
            fake_destructive_platform,
            confirmation_phrase=synthetic_plan.confirmation_phrase,
            audit_log_dir=audit_log_dir,
        )
    assert exc.value.step_name == "partition_disk_apfs"
    assert "injected failure" in exc.value.stderr

    logs = list(audit_log_dir.glob("setup-*.log"))
    assert logs, "audit log not written before exception"
    events = [json.loads(line) for line in logs[0].read_text().splitlines() if line.strip()]
    assert any(e["step"] == "partition_disk_apfs" and e["phase"] == "fail" for e in events)
    # No copy_nebula event — execution stopped at the failure.
    assert not any(e["step"] == "copy_nebula" for e in events)


# ---------------------------------------------------------------------------
# 13. INV-D003 — post-state layout
# ---------------------------------------------------------------------------


def test_post_setup_layout_is_canonical(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """After a successful run: genomeclaw/{raw,reference,derived,_scratch}
    all exist; setup.log is in _scratch/. Block-attached scratch was
    deferred (Option A pivot), so scratch.raw is no longer provisioned."""
    from genomeclaw_toolkit.prep.setup.execute import execute

    execute(
        synthetic_plan,
        fake_destructive_platform,
        confirmation_phrase=synthetic_plan.confirmation_phrase,
        audit_log_dir=tmp_path / ".genomeclaw",
        colima_yaml_path=tmp_path / "fake_colima.yaml",
    )

    mount = fake_destructive_platform.partition_mount
    assert mount is not None
    base = mount / "genomeclaw"
    for sub in ("raw", "reference", "derived", "_scratch"):
        assert (base / sub).is_dir(), f"missing {sub}/"

    assert (base / "_scratch" / "setup.log").exists()

    # The Nebula deliverable was copied (not just empty dirs).
    sample_dir = base / "raw" / "MPNRGLQ2K"
    assert sample_dir.is_dir()
    copied = {p.name for p in sample_dir.iterdir() if p.is_file()}
    assert copied == {
        "MPNRGLQ2K.cram",
        "MPNRGLQ2K.cram.crai",
        "MPNRGLQ2K.vcf.gz",
        "MPNRGLQ2K.vcf.gz.tbi",
    }


# ---------------------------------------------------------------------------
# 14. colima_stop is a no-op when not running
# ---------------------------------------------------------------------------


def test_executor_skips_colima_stop_if_not_running(
    fake_destructive_platform, synthetic_plan, tmp_path: Path
) -> None:
    """If colima_status reports stopped, executor still records the call but
    doesn't error. Real-world: fresh user, first setup."""
    from genomeclaw_toolkit.prep.setup.execute import execute

    fake_destructive_platform.colima_running = False  # already stopped

    execute(
        synthetic_plan,
        fake_destructive_platform,
        confirmation_phrase=synthetic_plan.confirmation_phrase,
        audit_log_dir=tmp_path / ".genomeclaw",
        colima_yaml_path=tmp_path / "fake_colima.yaml",
    )
    methods = [c.method for c in fake_destructive_platform.call_log]
    # We still query status; we may or may not call colima_stop.
    assert "colima_status" in methods
