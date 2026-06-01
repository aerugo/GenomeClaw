"""Phase 2 (host-profile-personal-context) — ``host profile`` CLI subgroup.

Covers the non-interactive subcommands ``show`` / ``set`` / ``review``:
the INV-C002 ``--json`` envelope contract, the missing-profile signal,
dotted-path mutation + audit, the unknown-path rejection, and the
``review`` last-full-review stamp. The interactive ``init`` / ``edit``
flows are covered in ``test_cli_host_profile_init.py``.

Bare-host venv — in-process CLI via the ``invoke_cli`` fixture; no bio
binaries, no network.
"""

from __future__ import annotations

import json
from pathlib import Path

from genomeclaw_toolkit.host_profile.store import audit_log_path, read_profile, write_profile_atomic
from genomeclaw_toolkit.schemas.host_profile import HostProfile

_META = {"created_at": "2026-05-31T00:00:00Z", "updated_at": "2026-05-31T00:00:00Z"}


def _write_profile(derived_root: Path) -> None:
    write_profile_atomic(
        derived_root,
        HostProfile.model_validate(
            {
                "schema_version": "host_profile/1.0",
                "meta": dict(_META),
                "identity": {
                    "sex_assigned_at_birth": "male",
                    "date_of_birth": "1988-11-12",
                    "ancestry": {"groups": ["european"]},
                },
                "biometrics": {"height_cm": 195.0, "weight_kg": 104.0},
            }
        ),
    )


def _derived(tmp_path: Path) -> Path:
    root = tmp_path / "derived"
    root.mkdir()
    return root


def test_invC002_host_profile_show_json_envelope_shape(tmp_path, invoke_cli) -> None:
    """INV-C002: `host profile show --json` carries the canonical envelope."""
    root = _derived(tmp_path)
    _write_profile(root)
    result = invoke_cli(["--json", "host", "profile", "show", "--derived-root", str(root)])

    assert result.exit_code == 0, result.stderr
    envelope = json.loads(result.stdout.strip())
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "host.profile.show"
    assert envelope["payload"]["profile"]["schema_version"] == "host_profile/1.0"
    assert envelope["payload"]["missing"] is False
    assert envelope["payload"]["completeness"]["identity"] in {"complete", "partial"}


def test_host_profile_show_missing_profile_renders_init_hint(tmp_path, invoke_cli) -> None:
    """Human-mode `show` on a fresh root renders the init-command hint (on stderr)."""
    root = _derived(tmp_path)
    result = invoke_cli(["host", "profile", "show", "--derived-root", str(root)])

    assert result.exit_code == 0
    assert "host profile init" in result.stderr


def test_host_profile_show_missing_profile_json_envelope_carries_init_command(
    tmp_path, invoke_cli
) -> None:
    """JSON-mode `show` on a fresh root surfaces the structured missing signal."""
    root = _derived(tmp_path)
    result = invoke_cli(["--json", "host", "profile", "show", "--derived-root", str(root)])

    assert result.exit_code == 0
    payload = json.loads(result.stdout.strip())["payload"]
    # `exclude_none=True` drops the null `profile`/`completeness` keys — a
    # missing profile is signalled by `missing: true` + the init command.
    assert payload.get("profile") is None
    assert payload["missing"] is True
    assert payload["init_command"] == "genomeclaw host profile init"


def test_host_profile_set_dotted_path_writes_single_field(tmp_path, invoke_cli) -> None:
    """`set <list>.add` appends one element; the audit log records the write."""
    root = _derived(tmp_path)
    _write_profile(root)
    result = invoke_cli(
        [
            "--json", "host", "profile", "set",
            "medical_history.medications.add", '{"name": "clopidogrel"}',
            "--derived-root", str(root),
        ]
    )

    assert result.exit_code == 0, result.stdout + result.stderr
    profile = read_profile(root)
    assert profile is not None
    assert [m.name for m in profile.medical_history.medications] == ["clopidogrel"]
    # The audit log carries an entry for the mutation.
    log_lines = [ln for ln in audit_log_path(root).read_text().splitlines() if ln.strip()]
    assert log_lines  # at least the initial write + the set
    assert any("medical_history.medications" in ln for ln in log_lines)


def test_host_profile_set_rejects_unknown_section(tmp_path, invoke_cli) -> None:
    """`set` against an unknown path exits 2 with a structured usage error."""
    root = _derived(tmp_path)
    _write_profile(root)
    result = invoke_cli(
        [
            "--json", "host", "profile", "set",
            "medical_history.dragons", "x",
            "--derived-root", str(root),
        ]
    )

    assert result.exit_code == 2
    envelope = json.loads(result.stdout.strip())
    assert envelope["error"]["error_type"] == "usage_error"


def test_host_profile_review_marks_last_full_review_at(tmp_path, invoke_cli) -> None:
    """`review` stamps `meta.last_full_review_at` and reports it in the envelope."""
    root = _derived(tmp_path)
    _write_profile(root)
    assert read_profile(root).meta.last_full_review_at is None

    result = invoke_cli(["--json", "host", "profile", "review", "--derived-root", str(root)])

    assert result.exit_code == 0, result.stderr
    payload = json.loads(result.stdout.strip())["payload"]
    assert payload["last_full_review_at"] is not None
    assert read_profile(root).meta.last_full_review_at is not None
