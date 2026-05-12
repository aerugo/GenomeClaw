"""JSON-Lines audit log for ``genomeclaw host setup``.

Setup writes one event per destructive step (start / complete / fail).
The log lives at ``~/.genomeclaw/setup-{ts}.log`` until ``promote`` moves
it onto the freshly-partitioned target at ``<scratch>/setup.log``.
"""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


class AuditLog:
    """Append-only JSON-Lines log with a temp-then-promote lifecycle.

    Open under ``audit_log_dir`` with a ``setup-{ts}.log`` filename.
    After the partition + ``mkdir_layout`` steps succeed, call
    :meth:`promote` to move the file into ``<target>/_scratch/setup.log``;
    subsequent events append to the promoted file.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        # Open in append-binary mode so we can fsync each line.
        path.parent.mkdir(parents=True, exist_ok=True)
        self._fh = path.open("ab")

    @classmethod
    def open(cls, audit_log_dir: Path, *, prefix: str = "setup") -> AuditLog:
        ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
        path = audit_log_dir / f"{prefix}-{ts}.log"
        return cls(path)

    def event(self, step: str, phase: str, payload: dict[str, Any]) -> None:
        """Append one ``{ts, step, phase, payload}`` event line.

        Raises ``TypeError`` (from ``json.dumps``) if ``payload`` contains
        anything not JSON-serialisable — fail loud rather than swallow.
        """
        record = {
            "ts": datetime.now(tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "step": step,
            "phase": phase,
            "payload": payload,
        }
        line = json.dumps(record).encode("utf-8") + b"\n"
        self._fh.write(line)
        self._fh.flush()
        os.fsync(self._fh.fileno())

    def promote(self, scratch_dir: Path) -> Path:
        """Atomically move the log into ``scratch_dir/setup.log``.

        After return, ``self.path`` is updated; subsequent ``event`` calls
        append to the promoted file. The original temp file is unlinked.
        """
        scratch_dir.mkdir(parents=True, exist_ok=True)
        new_path = scratch_dir / "setup.log"
        # Close the current handle so the move is clean.
        self._fh.close()
        shutil.move(str(self.path), str(new_path))
        self.path = new_path
        self._fh = new_path.open("ab")
        return new_path

    def close(self) -> None:
        if not self._fh.closed:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()


__all__ = ["AuditLog"]
