"""Phase 2 — destructive setup runner.

Given a :class:`SetupPlan` (built by Phase 1's ``build_plan``) and the
typed-confirmation phrase the user actually entered, execute the
12-step destructive sequence: stop colima, repartition the target,
copy + verify the Nebula deliverable, provision the scratch image,
rewrite ``colima.yaml``, restart colima, format + mount the block
device, verify mounts.

Every step writes an audit-log event before and after. A failure at
any step raises a typed exception and stops; the audit log carries
enough state for manual recovery.

Source files are NEVER deleted. The executor copies + verifies; the
user purges the source manually after confirming.
"""

from __future__ import annotations

import hashlib
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from genomeclaw_toolkit import __version__ as TOOLKIT_VERSION
from genomeclaw_toolkit.prep.setup._types import SetupPlan
from genomeclaw_toolkit.prep.setup._yaml_writer import write_colima_yaml
from genomeclaw_toolkit.prep.setup.audit import AuditLog
from genomeclaw_toolkit.prep.setup.detect import SetupError
from genomeclaw_toolkit.prep.setup.platform import Platform

_TOTAL_STEPS = 9


def _say(msg: str, *, verbose: bool) -> None:
    """Print + flush so the user sees progress in real time during long steps."""
    if verbose:
        print(msg, flush=True)


def _human_bytes(n: int) -> str:
    """Render byte count as ``"55.2 GB"`` etc. (decimal units; matches the dry-run preview)."""
    if n < 1000:
        return f"{n} B"
    units = ("KB", "MB", "GB", "TB")
    value = float(n)
    for unit in units:
        value /= 1000
        if value < 1000 or unit == "TB":
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


def _human_duration(seconds: float) -> str:
    """Render elapsed seconds as ``"3m 24s"`` / ``"12s"`` / ``"0.4s"``."""
    if seconds < 1:
        return f"{seconds:.1f}s"
    secs = int(seconds)
    if secs < 60:
        return f"{secs}s"
    mins, rem = divmod(secs, 60)
    if mins < 60:
        return f"{mins}m {rem:02d}s"
    hours, rem_min = divmod(mins, 60)
    return f"{hours}h {rem_min:02d}m"


def _render_completion_summary(
    *,
    plan: SetupPlan,
    partition_mount: Path,
    target_root: Path,
    log_path: Path,
    colima_yaml_path: Path,
    total_bytes_copied: int,
    file_count: int,
    total_seconds: float,
) -> str:
    """Build the post-success summary printed at the end of a destructive run.

    Lays out: what was done, where everything landed, and the next commands
    the user is expected to invoke. Designed to leave the user with zero
    "what now?" ambiguity — every paragraph maps to a concrete on-disk
    artifact or a copy-pasteable command.
    """
    bar = "=" * 64
    sample_id = plan.nebula.sample_id
    src_path = plan.nebula.source_path
    sample_vcf = next(
        (f for f, _ in plan.nebula.files if f.endswith(".vcf.gz") and "hc" in f.lower()),
        None,
    )
    sample_bam = next(
        (f for f, _ in plan.nebula.files if f.endswith((".cram", ".bam"))),
        None,
    )

    lines = [
        "",
        bar,
        f"  setup: complete  (total wall time {_human_duration(total_seconds)})",
        bar,
        "",
        "What just happened:",
        f"  ✓ Partitioned the target as APFS named "
        f"{plan.target_volume.name!r} ({_human_bytes(plan.target_volume.size_bytes)})",
        f"  ✓ Mounted at {partition_mount}",
        f"  ✓ Copied {file_count} Nebula file(s) ({_human_bytes(total_bytes_copied)}) "
        f"with per-file SHA256 verification",
        "  ✓ Rewrote ~/.colima/default/colima.yaml to share the partition with the engine VM",
        "  ✓ Restarted colima; verified the four bind-mounts come up RO/RO/RW/RW",
        "",
        "Canonical on-disk layout (host paths):",
        f"  {target_root}/",
        f"    raw/{sample_id}/      ← {file_count} file(s), {_human_bytes(total_bytes_copied)} "
        f"(read-only at runtime; INV-D001)",
        "    reference/            ← annotation datasets (currently empty; populate via `fetch`)",
        "    derived/              ← per-run output dirs accumulate here (CURRENT symlink)",
        "    _scratch/             ← ephemeral; INV-D003. Safe to `rm -rf` between runs.",
        "",
        "Inside the toolkit container these are bind-mounted at",
        "/mnt/genomeclaw/{raw,reference,derived,scratch}.",
        "",
        "Records on disk:",
        f"  audit log:   {log_path}",
        f"  colima.yaml: {colima_yaml_path}  (backed up to <path>.bak.<ts>)",
        "",
        "Source data on Kingston is unchanged:",
        f"  {src_path}",
        "  Delete manually after confirming the T7 copy is intact "
        "(setup never deletes source files; INV-D001).",
        "",
        bar,
        "  Next steps",
        bar,
        "",
        "1. Verify the install is green:",
        "     bin/genomeclaw host doctor",
        "",
        "2. Populate reference data (deliberate, opt-in egress per INV-P001):",
        "     bin/genomeclaw refs fetch --source grch38   --release ncbi-2014",
        "     bin/genomeclaw refs fetch --source clinvar  --release <YYYY-MM-DD>",
        "     bin/genomeclaw refs fetch --source dbsnp    --release <build>",
        "     bin/genomeclaw refs fetch --source gnomad-exomes --release v4.1",
        "",
        "3. Run the pipeline against your Nebula deliverable. Note these are",
        "   in-container paths; the shim translates them to the host paths above:",
        "     bin/genomeclaw pipeline ingest \\",
        f"       --sample-id {sample_id} \\",
        "       --reference /mnt/genomeclaw/reference/grch38/<release>/ \\",
        f"       --vcf       /mnt/genomeclaw/raw/{sample_id}/{sample_vcf or '<sample>.vcf.gz'} \\",
        f"       --bam       /mnt/genomeclaw/raw/{sample_id}/{sample_bam or '<sample>.cram'} \\",
        "       --reference-fasta /mnt/genomeclaw/reference/grch38/<release>/grch38.fa.gz",
        "",
        "4. Before disconnecting the external drive (and ONLY then):",
        "     bin/genomeclaw host eject",
        "",
        "If anything feels off later, re-run `bin/genomeclaw host setup` — it's",
        "idempotent and auto-heals colima drift (no destructive re-run needed",
        "when the partition is intact).",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class ConfirmationMismatchError(SetupError):
    """The phrase the user typed didn't match the plan's confirmation phrase."""


class DestructiveStepError(SetupError):
    """A destructive step (subprocess shellout) returned non-zero."""

    def __init__(self, *, step_name: str, return_code: int, stderr: str) -> None:
        super().__init__(f"step {step_name!r} failed (rc={return_code}): {stderr}")
        self.step_name = step_name
        self.return_code = return_code
        self.stderr = stderr


class DataIntegrityError(SetupError):
    """Post-copy SHA256 mismatch between source and target."""

    def __init__(self, *, file_name: str, src_sha256: str, dst_sha256: str) -> None:
        super().__init__(
            f"hash mismatch on {file_name}: src={src_sha256[:12]}…  dst={dst_sha256[:12]}…"
        )
        self.file_name = file_name
        self.src_sha256 = src_sha256
        self.dst_sha256 = dst_sha256


class MountFlagError(SetupError):
    """Post-restart mount flags don't match the canonical layout."""


__all__ = [
    "ConfirmationMismatchError",
    "DataIntegrityError",
    "DestructiveStepError",
    "MountFlagError",
    "execute",
]


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _hash_source_files(plan: SetupPlan) -> list[dict[str, Any]]:
    """SHA256 every source file before any destructive op runs.

    The result lands verbatim in the ``setup_started`` event payload so
    INV-D001's "source state captured before mutation" promise has a
    concrete on-disk record.
    """
    out = []
    for fname, fsize in plan.nebula.files:
        path = plan.nebula.source_path / fname
        h = hashlib.sha256()
        with path.open("rb") as fh:
            for chunk in iter(lambda: fh.read(1 << 20), b""):
                h.update(chunk)
        out.append({"name": fname, "sha256": h.hexdigest(), "bytes": fsize})
    return out


def execute(
    plan: SetupPlan,
    platform: Platform,
    *,
    confirmation_phrase: str,
    audit_log_dir: Path,
    colima_yaml_path: Path | None = None,
    verbose: bool = True,
) -> Path:
    """Run the 12-step destructive setup sequence.

    Args:
        plan: A :class:`SetupPlan` built by ``build_plan``.
        platform: A :class:`Platform` (production = ``MacOSPlatform``;
            tests = ``FakeDestructivePlatform``).
        confirmation_phrase: The phrase the user actually typed at the
            prompt. Must equal ``plan.confirmation_phrase`` exactly
            (after stripping whitespace).
        audit_log_dir: Where to open the temp audit log; typically
            ``~/.genomeclaw``. Promoted to ``<scratch>/setup.log`` once
            the partition exists.
        colima_yaml_path: Path to ``colima.yaml`` to rewrite with the
            new mounts + ``additionalDisks`` block. Defaults to
            ``~/.colima/default/colima.yaml``. Tests **must** pass an
            explicit path under ``tmp_path`` so they never touch the
            user's real config.

    Returns:
        Path to the final audit log (post-promote).
    """
    if confirmation_phrase.strip() != plan.confirmation_phrase.strip():
        raise ConfirmationMismatchError(
            f"confirmation phrase did not match — expected "
            f"{plan.confirmation_phrase!r}, got {confirmation_phrase!r}"
        )

    started_at = _now_iso()
    log = AuditLog.open(audit_log_dir, prefix="setup")
    target_volume = plan.target_volume
    nebula = plan.nebula
    parent_disk = target_volume.parent_disk

    overall_start = time.monotonic()
    _say("", verbose=verbose)
    _say(
        f"Running destructive setup against {target_volume.name} "
        f"({_human_bytes(target_volume.size_bytes)} via {target_volume.parent_disk}).",
        verbose=verbose,
    )
    _say(f"Audit log: {log.path}", verbose=verbose)
    _say("", verbose=verbose)

    try:
        # 0. Capture pre-state hashes before any destructive op.
        t0 = time.monotonic()
        total_bytes = sum(fsize for _, fsize in plan.nebula.files)
        _say(
            f"[0/{_TOTAL_STEPS}] hashing source files ({_human_bytes(total_bytes)})…",
            verbose=verbose,
        )
        source_hashes = _hash_source_files(plan)
        _say(f"          ✓ done in {_human_duration(time.monotonic() - t0)}", verbose=verbose)
        log.event(
            "setup_started",
            "start",
            {
                "started_at": started_at,
                "toolkit_version": TOOLKIT_VERSION,
                "source_path": str(nebula.source_path),
                "target_partition": target_volume.name,
                "target_parent_disk": parent_disk,
                "target_filesystem_before": target_volume.filesystem,
                "source_hashes": source_hashes,
            },
        )

        # 1. colima_stop (best-effort — only if running).
        t0 = time.monotonic()
        _say(f"[1/{_TOTAL_STEPS}] stopping colima (if running)…", verbose=verbose)
        _step_start(log, "colima_stop", {"parent_disk": parent_disk})
        status = platform.colima_status()
        if status == "running":
            platform.colima_stop()
        _step_complete(log, "colima_stop", {"prior_status": status})
        _say(
            f"          ✓ {status} → stopped in {_human_duration(time.monotonic() - t0)}",
            verbose=verbose,
        )

        # 2. unmount_disk.
        t0 = time.monotonic()
        _say(
            f"[2/{_TOTAL_STEPS}] unmounting {parent_disk}…",
            verbose=verbose,
        )
        _step_start(log, "unmount_disk", {"parent_disk": parent_disk})
        platform.unmount_disk(parent_disk)
        _step_complete(log, "unmount_disk", {})
        _say(f"          ✓ done in {_human_duration(time.monotonic() - t0)}", verbose=verbose)

        # 3. partition_disk_apfs.
        new_label = "Genome_Work"
        t0 = time.monotonic()
        _say(
            f"[3/{_TOTAL_STEPS}] repartitioning {parent_disk} as APFS named "
            f"{new_label!r}… (typically 10–30s)",
            verbose=verbose,
        )
        _step_start(log, "partition_disk_apfs", {"label": new_label})
        partition_mount = platform.partition_disk_apfs(parent_disk, new_label)
        _step_complete(
            log,
            "partition_disk_apfs",
            {"label": new_label, "mount_point": str(partition_mount)},
        )
        _say(
            f"          ✓ mounted at {partition_mount} in {_human_duration(time.monotonic() - t0)}",
            verbose=verbose,
        )

        # 4. mkdir_layout (Python).
        target_root = partition_mount / "genomeclaw"
        scratch_dir = target_root / "_scratch"
        t0 = time.monotonic()
        _say(
            f"[4/{_TOTAL_STEPS}] creating canonical subdirs under {target_root}…",
            verbose=verbose,
        )
        _step_start(log, "mkdir_layout", {"target_root": str(target_root)})
        for sub in ("raw", "reference", "derived", "_scratch"):
            (target_root / sub).mkdir(parents=True, exist_ok=True)
        _step_complete(log, "mkdir_layout", {})
        _say(f"          ✓ done in {_human_duration(time.monotonic() - t0)}", verbose=verbose)

        # The layout exists; promote the audit log onto the target.
        log.promote(scratch_dir)
        _say(f"          (audit log promoted to {log.path})", verbose=verbose)

        # 5. copy_nebula (Python loop, Platform per-file copy).
        target_raw = target_root / "raw" / nebula.sample_id
        target_raw.mkdir(parents=True, exist_ok=True)
        copy_records: list[dict[str, Any]] = []
        copy_start = time.monotonic()
        _say(
            f"[5/{_TOTAL_STEPS}] copying {len(nebula.files)} Nebula file(s) "
            f"({_human_bytes(total_bytes)}) → {target_raw}/ (longest step — ~3–8 min for CRAM)",
            verbose=verbose,
        )
        _step_start(log, "copy_nebula", {"sample_id": nebula.sample_id})
        for fname, fsize in nebula.files:
            t_file = time.monotonic()
            _say(
                f"          → {fname} ({_human_bytes(fsize)})…",
                verbose=verbose,
            )
            src = nebula.source_path / fname
            dst = target_raw / fname
            src_sha, dst_sha = platform.copy_file_with_sha(src, dst)
            copy_records.append(
                {
                    "name": fname,
                    "src_sha256": src_sha,
                    "dst_sha256": dst_sha,
                    "bytes": fsize,
                }
            )
            _say(
                f"            ✓ ok in {_human_duration(time.monotonic() - t_file)}",
                verbose=verbose,
            )
        _step_complete(log, "copy_nebula", {"records": copy_records})
        _say(
            f"          ✓ all files copied in {_human_duration(time.monotonic() - copy_start)}",
            verbose=verbose,
        )

        # 6. verify_target_hashes (Python).
        t0 = time.monotonic()
        _say(
            f"[6/{_TOTAL_STEPS}] verifying per-file SHA256 src vs dst…",
            verbose=verbose,
        )
        _step_start(log, "verify_target_hashes", {})
        for rec in copy_records:
            if rec["src_sha256"] != rec["dst_sha256"]:
                _step_fail(
                    log,
                    "verify_target_hashes",
                    {
                        "file_name": rec["name"],
                        "expected": rec["src_sha256"],
                        "got": rec["dst_sha256"],
                    },
                )
                raise DataIntegrityError(
                    file_name=rec["name"],
                    src_sha256=rec["src_sha256"],
                    dst_sha256=rec["dst_sha256"],
                )
        _step_complete(log, "verify_target_hashes", {"files_verified": len(copy_records)})
        _say(
            f"          ✓ {len(copy_records)} file(s) verified in "
            f"{_human_duration(time.monotonic() - t0)}",
            verbose=verbose,
        )

        # 7. write_colima_yaml.
        # Block-attached scratch (additionalDisks) is unsupported on
        # colima 0.9.1 — it silently strips the field on start. The
        # mount we declare here is the partition root; per-subdir RO/RW
        # is enforced by the host shim's docker --mount flags.
        colima_yaml = colima_yaml_path or (Path.home() / ".colima" / "default" / "colima.yaml")
        t0 = time.monotonic()
        _say(
            f"[7/{_TOTAL_STEPS}] rewriting colima.yaml mounts ({colima_yaml})…",
            verbose=verbose,
        )
        _step_start(log, "write_colima_yaml", {"path": str(colima_yaml)})
        write_colima_yaml(
            colima_yaml,
            partition_mount=partition_mount,
            backup=True,
        )
        _step_complete(log, "write_colima_yaml", {})
        _say(f"          ✓ done in {_human_duration(time.monotonic() - t0)}", verbose=verbose)

        # 8. colima_start.
        t0 = time.monotonic()
        _say(
            f"[8/{_TOTAL_STEPS}] starting colima with new mounts… (typically 10–20s)",
            verbose=verbose,
        )
        _step_start(log, "colima_start", {})
        platform.colima_start()
        _step_complete(log, "colima_start", {})
        _say(f"          ✓ running in {_human_duration(time.monotonic() - t0)}", verbose=verbose)

        # 9. verify_mounts_via_shim.
        # Confirms the four canonical mounts come up correctly when the
        # shim's docker bind-mount discipline is applied. raw + reference
        # ro, derived + scratch rw. The platform's verifier shells out a
        # one-shot container with the same --mount flags the production
        # shim uses.
        expected_mounts = {
            f"{target_root}/raw": "ro",
            f"{target_root}/reference": "ro",
            f"{target_root}/derived": "rw",
            f"{target_root}/_scratch": "rw",
        }
        t0 = time.monotonic()
        _say(
            f"[9/{_TOTAL_STEPS}] verifying mount flags inside a one-shot container…",
            verbose=verbose,
        )
        _step_start(log, "verify_mounts_via_shim", {"expected": expected_mounts})
        platform.verify_mounts_via_shim(target_root)
        _step_complete(log, "verify_mounts_via_shim", {})
        _say(
            f"          ✓ raw RO, reference RO, derived RW, _scratch RW "
            f"({_human_duration(time.monotonic() - t0)})",
            verbose=verbose,
        )

        # Final bracket event.
        log.event(
            "setup_completed",
            "complete",
            {
                "started_at": started_at,
                "completed_at": _now_iso(),
                "toolkit_version": TOOLKIT_VERSION,
                "source_path": str(nebula.source_path),
                "target_partition": new_label,
                "target_parent_disk": parent_disk,
                "partition_mount": str(partition_mount),
                "target_root": str(target_root),
            },
        )
        if verbose:
            print(
                _render_completion_summary(
                    plan=plan,
                    partition_mount=partition_mount,
                    target_root=target_root,
                    log_path=log.path,
                    colima_yaml_path=colima_yaml,
                    total_bytes_copied=sum(r["bytes"] for r in copy_records),
                    file_count=len(copy_records),
                    total_seconds=time.monotonic() - overall_start,
                ),
                flush=True,
            )
        return log.path
    except DestructiveStepError as exc:
        log.event(
            exc.step_name,
            "fail",
            {"return_code": exc.return_code, "stderr": exc.stderr},
        )
        raise
    finally:
        log.close()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _step_start(log: AuditLog, step: str, payload: dict[str, Any]) -> None:
    log.event(step, "start", payload)


def _step_complete(log: AuditLog, step: str, payload: dict[str, Any]) -> None:
    log.event(step, "complete", payload)


def _step_fail(log: AuditLog, step: str, payload: dict[str, Any]) -> None:
    log.event(step, "fail", payload)
