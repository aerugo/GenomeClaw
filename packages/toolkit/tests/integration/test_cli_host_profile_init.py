"""Phase 2 (host-profile-personal-context) — interactive ``init`` / ``edit``.

The interactive walk is exercised through a :class:`ScriptedPrompter`
injected by monkeypatching ``interactive.default_prompter`` — no TTY, no
Questionary event loop. Each prompt carries a stable key, so the scripted
answers address fields by name rather than by call order.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from genomeclaw_toolkit.host_profile import interactive
from genomeclaw_toolkit.host_profile.store import host_profile_path, read_profile, write_profile_atomic
from genomeclaw_toolkit.schemas.host_profile import HostProfile


@pytest.fixture
def scripted(monkeypatch):
    """Install a ScriptedPrompter with the given answers as the default prompter."""

    def _install(answers: dict | None = None):
        monkeypatch.setattr(
            interactive, "default_prompter", lambda: interactive.ScriptedPrompter(answers or {})
        )

    return _install


def _derived(tmp_path: Path) -> Path:
    root = tmp_path / "derived"
    root.mkdir()
    return root


def test_invC002_host_profile_init_quick_json_envelope(tmp_path, invoke_cli, scripted) -> None:
    """`init --quick --json` writes the profile and emits the canonical envelope."""
    root = _derived(tmp_path)
    scripted({"identity.sex_assigned_at_birth": "male"})
    result = invoke_cli(["--json", "host", "profile", "init", "--quick", "--derived-root", str(root)])

    assert result.exit_code == 0, result.stderr
    envelope = json.loads(result.stdout.strip())
    assert envelope["cli_output_schema_version"] == "1.0"
    assert envelope["command"] == "host.profile.init"
    assert envelope["payload"]["profile"]["identity"]["sex_assigned_at_birth"] == "male"
    assert read_profile(root) is not None


def test_host_profile_init_interactive_walks_all_sections(tmp_path, invoke_cli, scripted) -> None:
    """A full interactive walk writes a profile covering every section."""
    root = _derived(tmp_path)
    scripted(
        {
            "identity.sex_assigned_at_birth": "male",
            "lifestyle.smoking_status": "never",
        }
    )
    result = invoke_cli(["host", "profile", "init", "--derived-root", str(root)])

    assert result.exit_code == 0, result.stderr
    profile = read_profile(root)
    assert profile is not None
    assert profile.identity.sex_assigned_at_birth == "male"
    assert profile.lifestyle.smoking_status == "never"


def test_host_profile_init_skip_records_meta_skipped_init_at(tmp_path, invoke_cli) -> None:
    """`init --skip` records meta.skipped_init_at without prompting."""
    root = _derived(tmp_path)
    result = invoke_cli(["--json", "host", "profile", "init", "--skip", "--derived-root", str(root)])

    assert result.exit_code == 0, result.stderr
    assert json.loads(result.stdout.strip())["payload"]["skipped"] is True
    profile = read_profile(root)
    assert profile is not None
    assert profile.meta.skipped_init_at is not None


def test_host_profile_init_ancestry_multiselect_persists_friendly_and_pop1000g(
    tmp_path, invoke_cli, scripted
) -> None:
    """Ancestry groups persist verbatim and derive their 1000G codes."""
    root = _derived(tmp_path)
    scripted({"identity.ancestry.groups": ["european", "east_asian"]})
    result = invoke_cli(["host", "profile", "init", "--quick", "--derived-root", str(root)])

    assert result.exit_code == 0, result.stderr
    profile = read_profile(root)
    assert [str(g) for g in profile.identity.ancestry.groups] == ["european", "east_asian"]
    assert [str(c) for c in profile.identity.ancestry.population_codes] == ["EUR", "EAS"]


def test_host_profile_init_ancestry_self_reported_freetext_accepts_mixed(
    tmp_path, invoke_cli, scripted
) -> None:
    """Mixed-ancestry free text is persisted verbatim."""
    root = _derived(tmp_path)
    narrative = "50% Icelandic, 25% Czech, 25% Kazakh"
    scripted({"identity.ancestry.self_reported": narrative})
    invoke_cli(["host", "profile", "init", "--quick", "--derived-root", str(root)])

    assert read_profile(root).identity.ancestry.self_reported == narrative


def test_host_profile_init_family_history_editor_path_strips_scaffold_comments(
    tmp_path, invoke_cli, scripted
) -> None:
    """The $EDITOR family-history path strips `#` scaffold comments before saving."""
    root = _derived(tmp_path)
    edited = "# scaffold comment to drop\nDad: heart attack at 52.\n# another comment\n"
    scripted({"family.entry_mode": "editor", "family.notes": edited})
    invoke_cli(["host", "profile", "init", "--derived-root", str(root)])

    notes = read_profile(root).family_history.notes
    assert notes == "Dad: heart attack at 52."
    assert "scaffold comment" not in (notes or "")


def test_host_profile_init_family_history_opt_out_sets_flag(tmp_path, invoke_cli, scripted) -> None:
    """Opting out sets opted_out=true and leaves notes null."""
    root = _derived(tmp_path)
    scripted({"family.entry_mode": "opt_out"})
    invoke_cli(["host", "profile", "init", "--derived-root", str(root)])

    fam = read_profile(root).family_history
    assert fam.opted_out is True
    assert fam.notes is None


def test_host_profile_init_no_goals_section_walked(tmp_path, invoke_cli, scripted) -> None:
    """The written profile carries no `goals` key (considered + dropped, Decision 11)."""
    root = _derived(tmp_path)
    scripted({})
    invoke_cli(["host", "profile", "init", "--derived-root", str(root)])

    raw = json.loads(host_profile_path(root).read_text())
    assert "goals" not in raw


def test_host_profile_edit_field_drop_requires_confirmation(tmp_path, invoke_cli, monkeypatch) -> None:
    """Editing to remove a set value fails without --yes, succeeds with it (INV-D004)."""
    root = _derived(tmp_path)
    write_profile_atomic(
        root,
        HostProfile.model_validate(
            {
                "schema_version": "host_profile/1.0",
                "meta": {"created_at": "2026-05-31T00:00:00Z", "updated_at": "2026-05-31T00:00:00Z"},
                "identity": {"display_name": "Jane Doe", "sex_assigned_at_birth": "female"},
            }
        ),
    )
    # The editor returns a profile with display_name removed (a field drop).
    dropped = {
        "schema_version": "host_profile/1.0",
        "meta": {"created_at": "2026-05-31T00:00:00Z", "updated_at": "2026-05-31T00:00:00Z"},
        "identity": {"sex_assigned_at_birth": "female"},
    }
    edited_text = json.dumps(dropped)
    monkeypatch.setattr(
        interactive,
        "default_prompter",
        lambda: interactive.ScriptedPrompter({"profile.edit": edited_text}),
    )

    # Without --yes: refused.
    refused = invoke_cli(["host", "profile", "edit", "--derived-root", str(root)])
    assert refused.exit_code != 0
    assert read_profile(root).identity.display_name == "Jane Doe"  # unchanged

    # With --yes: the drop is confirmed and applied.
    ok = invoke_cli(["host", "profile", "edit", "--yes", "--derived-root", str(root)])
    assert ok.exit_code == 0, ok.stderr
    assert read_profile(root).identity.display_name is None
