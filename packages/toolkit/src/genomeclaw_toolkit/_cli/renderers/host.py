"""Rich renderers for the ``host`` command group.

Currently covers ``host doctor`` (Phase 1). ``host setup`` and
``host eject`` are thin Typer wrappers in Phase 1; their rich
renderers land in Phase 4 when interactive flows + confirmation
prompts are wired.

The doctor renderer is the canonical pattern: take a Pydantic
``DoctorPayload``, build a sequence of ``rich.table.Table`` /
``rich.panel.Panel`` objects, write them to the shared console.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from genomeclaw_toolkit._cli.console import get_console

if TYPE_CHECKING:
    from genomeclaw_toolkit._cli.commands.host import (
        DoctorPayload,
        _ProfileCompletenessPayload,
        _ProfileShowPayload,
    )

# Completeness glyphs reuse the established CLI status vocabulary
# (✓ done / ✗ fail from the pipeline renderer) — no new visual language.
_COMPLETENESS_GLYPH: dict[str, tuple[str, str]] = {
    "complete": ("✓", "green"),
    "partial": ("~", "yellow"),
    "missing": ("✗", "red"),
}


_STATUS_STYLE = {
    "OK": "green",
    "partial": "yellow",
    "missing": "red",
    "FAIL": "red",
}


def render_doctor(payload: DoctorPayload) -> None:
    """Render a doctor report as a sequence of rich tables and panels.

    Args:
        payload: The structured report produced by the doctor
            orchestrator + adapted into the CLI's payload model.
    """
    console = get_console()
    console.print()
    console.print(
        Panel.fit(
            Text("genomeclaw doctor — environment diagnostic", style="bold cyan"),
            border_style="cyan",
        )
    )
    _render_host_layout(payload)
    _render_setup_log(payload)
    _render_colima(payload)
    _render_references(payload)
    _render_raw_sample(payload)
    _render_derived_runs(payload)
    console.print()


def _render_host_layout(payload: DoctorPayload) -> None:
    """Render the host-layout check table."""
    console = get_console()
    table = Table(
        title="Host layout",
        title_style="bold",
        title_justify="left",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("Check")
    table.add_column("Status")
    table.add_column("Detail", overflow="fold")
    for check in payload.checks:
        style = _STATUS_STYLE.get(check.status, "")
        table.add_row(check.name, Text(check.status, style=style), check.message or "")
    console.print(table)


def _render_setup_log(payload: DoctorPayload) -> None:
    """Render the setup-audit-log block."""
    console = get_console()
    log = payload.setup_log
    if not log.found:
        body = Text(
            "(none — run `genomeclaw host setup` to create the canonical layout)",
            style="dim",
        )
    elif log.incomplete:
        body = Text(
            f"WARN: last setup did not complete "
            f"(started {log.last_started_at!r}, toolkit_version={log.toolkit_version!r})",
            style="yellow",
        )
    elif log.no_events:
        body = Text("(file present but no recognisable events — corrupted?)", style="yellow")
    else:
        lines: list[str] = [f"last completed: {log.last_completed_at}"]
        if log.toolkit_version is not None:
            lines.append(f"toolkit version: {log.toolkit_version}")
        if log.target_partition is not None:
            lines.append(f"target partition: {log.target_partition}")
        body = Text("\n".join(lines))
    console.print(Panel(body, title="Setup audit log", title_align="left"))


def _render_colima(payload: DoctorPayload) -> None:
    """Render the colima status block."""
    console = get_console()
    colima = payload.colima
    rows: list[str] = [f"installed: {colima.installed}"]
    if colima.version is not None:
        rows.append(f"version:   {colima.version}")
    rows.append(f"status:    {colima.status or 'unknown'}")
    console.print(Panel(Text("\n".join(rows)), title="colima", title_align="left"))


def _render_references(payload: DoctorPayload) -> None:
    """Render the reference-datasets table."""
    console = get_console()
    refs = payload.references
    title = f"Reference datasets (release set '{refs.release_set or '<unknown>'}')"
    if not refs.sources:
        console.print(
            Panel(Text("(none configured)", style="dim"), title=title, title_align="left")
        )
        return
    table = Table(
        title=title,
        title_style="bold",
        title_justify="left",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("Source")
    table.add_column("Release")
    table.add_column("Status")
    table.add_column("Notes", overflow="fold")
    for source in refs.sources:
        style = _STATUS_STYLE.get(source.status, "")
        notes_bits: list[str] = []
        if source.missing_files:
            notes_bits.append(f"missing {len(source.missing_files)} file(s)")
        if source.on_disk_release and source.on_disk_release != source.expected_release:
            notes_bits.append(f"on disk: {source.on_disk_release}")
        table.add_row(
            source.source,
            source.expected_release,
            Text(source.status, style=style),
            ", ".join(notes_bits),
        )
    console.print(table)


def _render_raw_sample(payload: DoctorPayload) -> None:
    """Render the raw-sample summary panel."""
    console = get_console()
    sample = payload.raw_sample
    if not sample.staged:
        body = Text("(no sample staged — drop your Nebula deliverable into raw/)", style="dim")
    else:
        files_block = "\n".join(f"  • {f}" for f in sample.files)
        body = Text(f"sample_id: {sample.sample_id or '<unknown>'}\nfiles:\n{files_block}")
    console.print(Panel(body, title="Raw sample", title_align="left"))


def _render_derived_runs(payload: DoctorPayload) -> None:
    """Render the derived-runs table."""
    console = get_console()
    runs = payload.derived_runs
    if not runs:
        console.print(
            Panel(
                Text("(none — run `genomeclaw pipeline ingest` to create one)", style="dim"),
                title="Derived runs",
                title_align="left",
            )
        )
        return
    table = Table(
        title="Derived runs",
        title_style="bold",
        title_justify="left",
        show_header=True,
        header_style="bold",
        expand=False,
    )
    table.add_column("Run ID")
    table.add_column("Sample")
    table.add_column("Started")
    table.add_column("Stage")
    for run in runs:
        table.add_row(
            run.run_id,
            run.sample_id or "—",
            run.started_at or "—",
            run.stage,
        )
    console.print(table)


def render_profile(payload: _ProfileShowPayload) -> None:
    """Render the host personal-context profile (or the missing-signal panel)."""
    console = get_console()
    console.print()
    if payload.profile is None:
        console.print(
            Panel.fit(
                Text(
                    "No host profile yet.\n"
                    f"Run `{payload.init_command or 'genomeclaw host profile init'}` "
                    "to record your personal context\n"
                    "(identity, biometrics, lifestyle, medical + family history).",
                    style="yellow",
                ),
                title="host profile",
                border_style="yellow",
            )
        )
        console.print()
        return

    profile = payload.profile
    console.print(
        Panel.fit(
            Text("host profile — self-reported personal context", style="bold cyan"),
            border_style="cyan",
        )
    )

    identity = Table(title="Identity", title_style="bold", title_justify="left", expand=False)
    identity.add_column("Field")
    identity.add_column("Value", overflow="fold")
    identity.add_row("display_name", profile.identity.display_name or "—")
    identity.add_row(
        "date_of_birth",
        profile.identity.date_of_birth.isoformat() if profile.identity.date_of_birth else "—",
    )
    identity.add_row("sex_assigned_at_birth", str(profile.identity.sex_assigned_at_birth))
    identity.add_row("gender_identity", profile.identity.gender_identity or "—")
    identity.add_row("ancestry (self-reported)", profile.identity.ancestry.self_reported or "—")
    identity.add_row(
        "ancestry groups",
        ", ".join(str(g) for g in profile.identity.ancestry.groups) or "—",
    )
    identity.add_row(
        "population codes (derived)",
        ", ".join(str(c) for c in profile.identity.ancestry.population_codes) or "—",
    )
    console.print(identity)

    bio = Table(title="Biometrics", title_style="bold", title_justify="left", expand=False)
    bio.add_column("Field")
    bio.add_column("Value")
    bio.add_row("height_cm", str(profile.biometrics.height_cm or "—"))
    bio.add_row("weight_kg", str(profile.biometrics.weight_kg or "—"))
    bio.add_row(
        "blood_type",
        str(profile.biometrics.blood_type) if profile.biometrics.blood_type else "—",
    )
    console.print(bio)

    life = Table(title="Lifestyle", title_style="bold", title_justify="left", expand=False)
    life.add_column("Field")
    life.add_column("Value", overflow="fold")
    life.add_row("smoking_status", str(profile.lifestyle.smoking_status))
    life.add_row("alcohol_use", str(profile.lifestyle.alcohol_use))
    life.add_row("exercise_frequency", str(profile.lifestyle.exercise_frequency))
    life.add_row("dietary_pattern", profile.lifestyle.dietary_pattern or "—")
    life.add_row("sleep_pattern", profile.lifestyle.sleep_pattern or "—")
    console.print(life)

    med = Table(title="Medical history", title_style="bold", title_justify="left", expand=False)
    med.add_column("Section")
    med.add_column("Count")
    med.add_row("conditions", str(len(profile.medical_history.conditions)))
    med.add_row("medications", str(len(profile.medical_history.medications)))
    med.add_row("allergies", str(len(profile.medical_history.allergies)))
    med.add_row("procedures", str(len(profile.medical_history.procedures)))
    console.print(med)

    # Family history is self-report — surfaced as a length / opt-out summary,
    # never the verbatim narrative in the at-a-glance view.
    if profile.family_history.opted_out:
        fam_summary = Text("opted out", style="dim")
    elif profile.family_history.notes:
        fam_summary = Text(f"recorded ({len(profile.family_history.notes)} chars)")
    else:
        fam_summary = Text("—", style="dim")
    console.print(Panel.fit(fam_summary, title="Family history", border_style="cyan"))

    if payload.completeness is not None:
        _render_completeness_table(payload.completeness)
    console.print()


def render_profile_completeness(payload: _ProfileCompletenessPayload) -> None:
    """Render the per-section completeness map (or the missing-signal panel)."""
    console = get_console()
    console.print()
    if payload.sections is None:
        console.print(
            Panel.fit(
                Text(
                    "No host profile yet — run `genomeclaw host profile init`.",
                    style="yellow",
                ),
                title="host profile completeness",
                border_style="yellow",
            )
        )
        console.print()
        return
    _render_completeness_table(payload.sections)
    console.print()


def _render_completeness_table(sections: dict[str, str]) -> None:
    """Render a section → completeness table with the established status glyphs."""
    console = get_console()
    table = Table(
        title="Completeness", title_style="bold", title_justify="left", expand=False
    )
    table.add_column("Section")
    table.add_column("Status")
    for section, status in sections.items():
        glyph, style = _COMPLETENESS_GLYPH.get(status, ("?", ""))
        table.add_row(section, Text(f"{glyph} {status}", style=style))
    console.print(table)


__all__ = ["render_doctor", "render_profile", "render_profile_completeness"]
