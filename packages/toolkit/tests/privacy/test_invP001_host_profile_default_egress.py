"""Phase 1 (host-profile-personal-context) — INV-P001 default-egress test.

``INV-P001`` (privacy is the default operating mode): hitting the two new
host-profile endpoints in default configuration must produce zero
outbound network connections to a non-loopback address. The profile is
the single most identifying host-side dataset after the raw genome; the
read path must never phone home.

The test installs a spy on ``socket.socket.connect`` for the duration of
the two requests and asserts no non-loopback destination was contacted.
"""

from __future__ import annotations

import socket
from pathlib import Path

from fastapi.testclient import TestClient

from genomeclaw_toolkit.host_profile.store import write_profile_atomic
from genomeclaw_toolkit.schemas.host_profile import HostProfile
from genomeclaw_toolkit.service.app import build_app

_LOOPBACK_PREFIXES = ("127.", "::1", "localhost")


def _is_loopback(address) -> bool:
    if not isinstance(address, tuple) or not address:
        return True  # AF_UNIX / non-inet sockets are local by construction.
    host = str(address[0])
    return any(host == "::1" or host.startswith(p) for p in _LOOPBACK_PREFIXES)


def test_invP001_host_profile_endpoint_default_no_outbound(
    tmp_path: Path, monkeypatch
) -> None:
    """INV-P001: the two host-profile endpoints make zero non-loopback connections."""
    derived_root = tmp_path / "derived"
    derived_root.mkdir()
    write_profile_atomic(
        derived_root,
        HostProfile.model_validate(
            {
                "schema_version": "host_profile/1.0",
                "meta": {
                    "created_at": "2026-05-31T00:00:00Z",
                    "updated_at": "2026-05-31T00:00:00Z",
                },
                "identity": {"sex_assigned_at_birth": "male"},
            }
        ),
    )

    non_loopback: list = []
    real_connect = socket.socket.connect

    def _spy_connect(self, address):  # noqa: ANN001
        if not _is_loopback(address):
            non_loopback.append(address)
        return real_connect(self, address)

    monkeypatch.setattr(socket.socket, "connect", _spy_connect)

    app = build_app(derived_root=derived_root)
    with TestClient(app) as client:
        client.get("/v1/host/profile")
        client.get("/v1/host/profile/completeness")

    assert non_loopback == [], (
        f"INV-P001 violation: host-profile endpoints attempted non-loopback "
        f"connections to {non_loopback!r}"
    )
