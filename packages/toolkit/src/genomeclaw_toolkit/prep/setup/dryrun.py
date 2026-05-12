"""Render a :class:`SetupPlan` to a human-readable preview.

Pure function, no I/O. Phase 1 ships the renderer; Phase 2's executor
takes the same plan after the user types the confirmation phrase.
"""

from __future__ import annotations

from genomeclaw_toolkit.prep.setup._types import SetupPlan


def _gb(n_bytes: int) -> str:
    return f"{n_bytes / 1000**3:.1f} GB"


def render(plan: SetupPlan) -> str:
    """Format ``plan`` as a multi-section preview for the user terminal."""
    nebula = plan.nebula
    target = plan.target_volume
    ident = plan.target_identity
    budget = plan.budget

    files_block = (
        "\n".join(f"      - {name}  ({_gb(size)})" for name, size in nebula.files)
        or "      (no files listed)"
    )

    lines = [
        "================================================================",
        "  genomeclaw host setup — dry-run preview (no changes yet)",
        "================================================================",
        "",
        "Source (Nebula deliverable):",
        f"  path:   {nebula.source_path}",
        f"  sample: {nebula.sample_id}",
        f"  total:  {_gb(nebula.total_bytes)}",
        "  files:",
        files_block,
        "",
        "Target drive:",
        f"  name:        {target.name}",
        f"  mount:       {target.mount_point}",
        f"  parent:      {target.parent_disk}",
        f"  filesystem:  {target.filesystem}  (will be reformatted to APFS)",
        f"  model:       {ident.model}",
        f"  firmware:    {ident.firmware}",
        f"  capacity:    {ident.capacity_gb} GB ({_gb(target.size_bytes)} reported)",
        f"  bus:         {ident.bus_type}",
        "",
        "Partition layout (proposed, after WIPE):",
        f"  Genome_Work  APFS  {_gb(target.size_bytes)}  (full drive)",
        "",
        "Move (after partitioning):",
        f"  {nebula.source_path}",
        f"    → /Volumes/Genome_Work/genomeclaw/raw/{nebula.sample_id}/",
        "",
        "Create on target:",
        "  /Volumes/Genome_Work/genomeclaw/raw/",
        "  /Volumes/Genome_Work/genomeclaw/reference/",
        "  /Volumes/Genome_Work/genomeclaw/derived/",
        "  /Volumes/Genome_Work/genomeclaw/_scratch/",
        f"  /Volumes/Genome_Work/genomeclaw/_scratch/scratch.raw  "
        f"({_gb(budget.scratch_bytes)} sparse)",
        "  /Volumes/Genome_Work/genomeclaw/_scratch/setup.log",
        "",
        "Space budget:",
        f"  raw:        {_gb(budget.raw_bytes)}",
        f"  reference:  {_gb(budget.reference_bytes)}",
        f"  scratch:    {_gb(budget.scratch_bytes)}",
        f"  margin:     {_gb(budget.margin_bytes)}",
        f"  ── total:   {_gb(budget.total_bytes)}",
        f"  free now:   {_gb(plan.target_free_bytes)}",
        "",
        "colima.yaml (will be rewritten to mount under /Volumes/Genome_Work/genomeclaw/):",
        "  - location: /Volumes/Genome_Work/genomeclaw/raw         writable: false",
        "  - location: /Volumes/Genome_Work/genomeclaw/reference   writable: false",
        "  - location: /Volumes/Genome_Work/genomeclaw/derived     writable: true",
        "",
        "lima additionalDisks (will be added):",
        "  - name: genomeclaw-scratch",
        "    format: false   # mkfs.ext4 happens once on first VM start",
        "",
        "================================================================",
        "  Phase 1: this is a non-destructive preview only.",
        "  The destructive runner will refuse to proceed unless you type",
        "  the following phrase exactly when prompted (Phase 2):",
        "",
        f"      {plan.confirmation_phrase}",
        "",
        "================================================================",
    ]
    return "\n".join(lines) + "\n"


__all__ = ["render"]
