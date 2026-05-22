"""INV-D006 meta-invariant: shim's `_dood_scan_args` is exhaustive.

Catches the "shim forgets to auto-enable DooD mode for a subcommand whose
wrapper requires `as_sibling_mountable(...)`" bug class. Surfaced during
MVP Phase 7 close session 1 (2026-05-22/23): `pgs-compute` failed twice
on the canonical real-data run because the shim's ``_dood_scan_args``
listed ``prs-compute`` + ``prs-prepare-coverage`` but NOT ``pgs-compute``,
even though ``pgs-compute`` calls ``compute_pgs(...)`` (which uses
``as_sibling_mountable`` on every input path).

The pattern this enforces:

  - Any wrapper module under ``prep/`` that imports
    ``as_sibling_mountable`` spawns DooD sibling containers (Nextflow /
    pgsc_calc / bcftools-shard / similar). The pre-flight check inside
    the wrapper requires ``GENOMECLAW_HOST_ROOTS`` to be non-empty.
  - That env var is only set by the shim when ``GENOMECLAW_DOOD=1`` is
    enabled.
  - The shim auto-enables DooD only for subcommands listed in
    ``_dood_scan_args()``.
  - Therefore: every wrapper using ``as_sibling_mountable`` must have
    its CLI subcommand in the shim's scan list.

The test walks ``_cli/commands/pipeline.py`` for ``@app.command(...)``
decorators, traces which wrapper module each subcommand calls, checks
whether that wrapper imports ``as_sibling_mountable``, and asserts each
DooD-needing subcommand appears in the shim's scan list.

Plan: [docs/plans/active/from-scratch-setup-protections/](../../../../docs/plans/active/from-scratch-setup-protections/)
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[4]
_PIPELINE_CLI = (
    _REPO_ROOT / "packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py"
)
_PREP_DIR = _REPO_ROOT / "packages/toolkit/src/genomeclaw_toolkit/prep"
_SHIM = _REPO_ROOT / "bin/genomeclaw"


def _subcommands_from_pipeline_cli() -> dict[str, str]:
    """Return {subcommand_name: handler_function_name} for every @app.command in pipeline.py.

    AST-based parse rather than regex so a decorator on multiple lines or
    with comments interleaved still resolves cleanly.
    """
    tree = ast.parse(_PIPELINE_CLI.read_text(), filename=str(_PIPELINE_CLI))
    out: dict[str, str] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for decorator in node.decorator_list:
            # Match @app.command("name")
            if (
                isinstance(decorator, ast.Call)
                and isinstance(decorator.func, ast.Attribute)
                and decorator.func.attr == "command"
                and isinstance(decorator.func.value, ast.Name)
                and decorator.func.value.id == "app"
                and decorator.args
                and isinstance(decorator.args[0], ast.Constant)
                and isinstance(decorator.args[0].value, str)
            ):
                out[decorator.args[0].value] = node.name
    return out


def _wrappers_imported_by_pipeline_cli() -> dict[str, set[str]]:
    """Return {handler_fn_name: set of prep-module names it calls}.

    Heuristic: inside each `pipeline_*` handler, find `from
    genomeclaw_toolkit.prep.<mod> import ...` AND any `prep.<mod>`-prefixed
    attribute access. The handler usually imports its wrapper via either
    top-of-file or inside the function body.
    """
    source = _PIPELINE_CLI.read_text()
    tree = ast.parse(source, filename=str(_PIPELINE_CLI))

    # 1. Top-of-file imports — map {imported_name: prep_module}
    top_imports: dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("genomeclaw_toolkit.prep."):
                prep_mod = node.module.removeprefix("genomeclaw_toolkit.prep.")
                for alias in node.names:
                    top_imports[alias.asname or alias.name] = prep_mod

    # 2. Per-function: imports inside the function + name references
    out: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        if not node.name.startswith("pipeline_") and node.name != "_stamp_pharmcat_findings" and node.name != "_stamp_pgs_row":
            continue
        modules: set[str] = set()
        # Local imports inside the function body
        for sub in ast.walk(node):
            if isinstance(sub, ast.ImportFrom) and sub.module:
                if sub.module.startswith("genomeclaw_toolkit.prep."):
                    modules.add(sub.module.removeprefix("genomeclaw_toolkit.prep."))
            elif isinstance(sub, ast.Name) and sub.id in top_imports:
                modules.add(top_imports[sub.id])
        out[node.name] = modules
    return out


def _wrappers_using_as_sibling_mountable() -> set[str]:
    """Return {prep-module-name} for every prep/<mod>.py that IMPORTS as_sibling_mountable.

    AST-based: parses each module's import statements; a substring match
    on the file text would false-positive on comments + docstrings that
    reference the name. The accurate signal is `from ...prep._paths
    import as_sibling_mountable` (or `SiblingMountablePath`); presence
    of either name as an import means the module is on the DooD-spawning
    code path.
    """
    targets = {"as_sibling_mountable", "SiblingMountablePath"}
    out: set[str] = set()
    for path in sorted(_PREP_DIR.glob("*.py")):
        if path.name == "_paths.py":
            # `_paths.py` itself DEFINES the names; skip the defining module.
            continue
        try:
            tree = ast.parse(path.read_text(), filename=str(path))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            if node.module and node.module.endswith("prep._paths"):
                for alias in node.names:
                    if alias.name in targets:
                        out.add(path.stem)
                        break
    return out


def _shim_dood_scan_subcommands() -> set[str]:
    """Parse bin/genomeclaw's _dood_scan_args() function; return the subcommand list.

    The function body looks roughly like:

        _dood_scan_args() {
          # ...
          if [[ "$prev" == "pipeline" && ( "$cur" == "prs-compute" \\
              || "$cur" == "prs-prepare-coverage" ) ]]; then
            return 0
          fi
          ...
        }
    """
    text = _SHIM.read_text()
    # Grab the body of _dood_scan_args() — between the function header and
    # the next function definition or top-level statement.
    m = re.search(r"_dood_scan_args\(\)\s*\{(.*?)^\}", text, re.MULTILINE | re.DOTALL)
    if m is None:
        raise AssertionError(
            "Could not find _dood_scan_args() function in bin/genomeclaw; "
            "the shim's contract has shifted enough that this test needs updating."
        )
    body = m.group(1)
    # Match `"$cur" == "<name>"` patterns.
    return set(re.findall(r'"\$cur"\s*==\s*"([^"]+)"', body))


def test_invD006_shim_dood_scan_covers_all_sibling_mountable_subcommands() -> None:
    """For every pipeline subcommand whose wrapper uses `as_sibling_mountable`,
    the shim's `_dood_scan_args` MUST include the subcommand name. Without
    this, a bare invocation runs in non-DooD mode → empty
    `GENOMECLAW_HOST_ROOTS` → `as_sibling_mountable` rejects every path
    with a confusing error.

    INV-D006 enforcement at the shim-side propagation layer.
    """
    subcommand_to_handler = _subcommands_from_pipeline_cli()
    handler_to_modules = _wrappers_imported_by_pipeline_cli()
    dood_wrappers = _wrappers_using_as_sibling_mountable()
    shim_subcommands = _shim_dood_scan_subcommands()

    # For each subcommand, derive whether its handler touches any DooD-
    # spawning wrapper module.
    dood_subcommands: set[str] = set()
    for subcmd, handler in subcommand_to_handler.items():
        modules = handler_to_modules.get(handler, set())
        if modules & dood_wrappers:
            dood_subcommands.add(subcmd)

    missing = sorted(dood_subcommands - shim_subcommands)
    assert not missing, (
        f"INV-D006 shim-side gap: the following pipeline subcommands have wrappers "
        f"that use `as_sibling_mountable(...)` (DooD-spawning) but are NOT in "
        f"`bin/genomeclaw`'s `_dood_scan_args()` regex list: {missing}.\n"
        f"\n"
        f"Without inclusion, bare invocations run in non-DooD mode → "
        f"`GENOMECLAW_HOST_ROOTS=[]` → the in-container pre-flight rejects every "
        f"path with a confusing error.\n"
        f"\n"
        f"Fix: add each missing subcommand to the `_dood_scan_args()` regex check "
        f"in `bin/genomeclaw` (alongside `prs-compute` / `prs-prepare-coverage`).\n"
        f"\n"
        f"Audit context: shim's current list = {sorted(shim_subcommands)}; "
        f"detected DooD-spawning subcommands = {sorted(dood_subcommands)}."
    )


def test_invD006_shim_dood_scan_test_machinery_is_sound() -> None:
    """Sanity check: the discovery machinery should find at least the known
    DooD-spawning subcommands. If this fails, the test above is silently
    not catching the bug class it's meant to.
    """
    subcommand_to_handler = _subcommands_from_pipeline_cli()
    handler_to_modules = _wrappers_imported_by_pipeline_cli()
    dood_wrappers = _wrappers_using_as_sibling_mountable()

    assert "prs-compute" in subcommand_to_handler, (
        "discovery sanity: prs-compute should appear in @app.command list"
    )
    assert "pgs-compute" in subcommand_to_handler, (
        "discovery sanity: pgs-compute should appear in @app.command list"
    )
    assert "pgs" in dood_wrappers, (
        "discovery sanity: prep/pgs.py should appear in as_sibling_mountable-using wrappers"
    )
    assert "coverage_fill" in dood_wrappers, (
        "discovery sanity: prep/coverage_fill.py should appear in as_sibling_mountable-using wrappers"
    )
    # Re-derive the dood subcommands + assert pgs-compute is in there.
    dood_subcommands: set[str] = set()
    for subcmd, handler in subcommand_to_handler.items():
        modules = handler_to_modules.get(handler, set())
        if modules & dood_wrappers:
            dood_subcommands.add(subcmd)
    assert "pgs-compute" in dood_subcommands, (
        "discovery sanity: pgs-compute's handler uses prep.pgs which is DooD-spawning"
    )
