"""INV-D006 discovery test — DooD-bound wrappers annotate ``SiblingMountablePath``.

Walks the canonical DooD-bound wrapper functions and asserts that every
parameter whose value will flow into a sibling container's ``-v <host>:...``
mount argument is annotated as :class:`SiblingMountablePath`, not bare
:class:`pathlib.Path`.

The list of (function, param-names) pairs is the canonical INV-D006
surface. Adding a new DooD-spawning wrapper means adding a row here AND
annotating its params accordingly.

Phase plan: [phases/phase-3.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-3.md)
"""

from __future__ import annotations

import importlib
from inspect import signature

import pytest

# The canonical DooD-bound surface as of Phase 3. Each entry is
# (module_path, function_name, [param-names-that-must-be-SiblingMountablePath]).
#
# `_write_pgsc_calc_samplesheet` writes a host path into a CSV pgsc_calc's
# siblings will resolve; the path must be on the host.
#
# `_build_pgsc_calc_argv` constructs pgsc_calc's argv directly — the
# samplesheet path, work_dir, and reference_root all become sibling mount
# sources.
#
# `compute_pgs` is the public entry — its vcf/work_dir/reference_root will
# transit through the two helpers above.
#
# `compute_prs_with_coverage_fill` is the orchestrator — its work_dir +
# reference_root reach pgsc_calc through `compute_pgs`.
_DOOD_BOUND_WRAPPERS: list[tuple[str, str, list[str]]] = [
    (
        "genomeclaw_toolkit.prep.pgs",
        "_write_pgsc_calc_samplesheet",
        ["vcf"],
    ),
    (
        "genomeclaw_toolkit.prep.pgs",
        "_build_pgsc_calc_argv",
        ["samplesheet", "work_dir", "reference_root"],
    ),
    (
        "genomeclaw_toolkit.prep.pgs",
        "compute_pgs",
        ["vcf", "work_dir", "reference_root"],
    ),
    (
        "genomeclaw_toolkit.prep.coverage_fill",
        "compute_prs_with_coverage_fill",
        ["work_dir", "reference_root"],
    ),
]


def _annotation_is_sibling_mountable(annotation: object) -> bool:
    """Match either the class itself or its forward-reference string."""
    from genomeclaw_toolkit.prep._paths import SiblingMountablePath

    if annotation is SiblingMountablePath:
        return True
    if isinstance(annotation, str) and annotation.split(".")[-1] == "SiblingMountablePath":
        return True
    return False


@pytest.mark.parametrize(
    "module_path,function_name,must_be_sibling_mountable",
    _DOOD_BOUND_WRAPPERS,
)
def test_invD006_dood_bound_wrapper_params_annotate_sibling_mountable(
    module_path: str,
    function_name: str,
    must_be_sibling_mountable: list[str],
) -> None:
    """Every DooD-bound parameter annotates :class:`SiblingMountablePath`.

    A future contributor who downgrades a parameter to bare :class:`Path`
    (which is easy to do accidentally — they're interchangeable at runtime
    until the factory validates them) trips this test.
    """
    mod = importlib.import_module(module_path)
    fn = getattr(mod, function_name)
    sig = signature(fn)
    failures: list[str] = []
    for param_name in must_be_sibling_mountable:
        assert param_name in sig.parameters, (
            f"{module_path}.{function_name} does not have parameter {param_name!r}; "
            f"signature: {sig}"
        )
        annotation = sig.parameters[param_name].annotation
        if not _annotation_is_sibling_mountable(annotation):
            failures.append(f"{param_name}: {annotation!r}")
    assert not failures, (
        f"{module_path}.{function_name} must annotate the following parameters "
        f"as SiblingMountablePath; got: {failures}"
    )
