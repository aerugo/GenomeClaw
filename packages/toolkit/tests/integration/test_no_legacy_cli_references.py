"""Phase 8 — regression guard: user-facing docs use the canonical CLI name.

The Phase-1 clean-slate cutover removed ``genomeclaw-prep`` from the
code base; Phase 8 finishes the job in the documentation surface. This
test pins the contract so the legacy name doesn't sneak back in via a
future doc edit.

Scope (intentionally narrow):

* ``README.md``, ``CLAUDE.md`` (root)
* ``docs/reference/`` — user-facing reference docs
* ``.claude/agents/`` — subagent instructions that flow into the
  agent's tool-catalog framing

Out of scope:

* ``docs/plans/active/mvp/**`` — on hold; cleanup happens when MVP
  resumes.
* ``docs/plans/completed/**`` — historical record.
* The rich-cli plan itself — intentional record of early phases that
  used the legacy name.
* ``docs/reference/cli-output-schemas.md`` — documents on-disk JSON
  payload shapes including the ``"tool": "genomeclaw-prep"``
  provenance literal that the code deliberately preserves for back-
  compat with existing ``manifest.json`` files. Updating the literal
  would invalidate prior derived runs' provenance trails.
"""

from __future__ import annotations

from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]


_EXCLUDED_FILENAMES = frozenset({"cli-output-schemas.md"})


def _in_scope_doc_files() -> list[Path]:
    """Collect the doc files that must not reference the legacy CLI name."""
    files: list[Path] = []
    for top in [
        _REPO_ROOT / "README.md",
        _REPO_ROOT / "CLAUDE.md",
    ]:
        if top.is_file():
            files.append(top)
    for subdir, glob in [
        (_REPO_ROOT / "docs" / "reference", "*.md"),
        (_REPO_ROOT / ".claude" / "agents", "*.md"),
    ]:
        if subdir.is_dir():
            files.extend(p for p in subdir.glob(glob) if p.name not in _EXCLUDED_FILENAMES)
    return files


def test_user_facing_docs_have_no_genomeclaw_prep_references() -> None:
    """No ``genomeclaw-prep`` references in the user-facing doc surface."""
    offenders: list[tuple[Path, int, str]] = []
    for doc in _in_scope_doc_files():
        for lineno, line in enumerate(doc.read_text().splitlines(), start=1):
            if "genomeclaw-prep" in line:
                offenders.append((doc.relative_to(_REPO_ROOT), lineno, line.rstrip()))
    assert not offenders, (
        "Found legacy ``genomeclaw-prep`` references in user-facing docs:\n"
        + "\n".join(f"  {path}:{ln}  {text}" for path, ln, text in offenders[:20])
    )


def test_invariants_md_contains_inv_c002_cli_output_stability() -> None:
    """``INV-C002`` is defined in the canonical INVARIANTS.md."""
    inv_path = _REPO_ROOT / "docs" / "reference" / "INVARIANTS.md"
    text = inv_path.read_text()
    assert "INV-C002" in text, "INV-C002 should be promoted in Phase 8"
    assert "CLI Output Contract Stability" in text


def test_invariants_md_contains_inv_d004_destructive_confirmation() -> None:
    """``INV-D004`` is defined in the canonical INVARIANTS.md."""
    inv_path = _REPO_ROOT / "docs" / "reference" / "INVARIANTS.md"
    text = inv_path.read_text()
    assert "INV-D004" in text, "INV-D004 should be promoted in Phase 8"
    assert "Destructive Operations" in text or "destructive operations" in text
