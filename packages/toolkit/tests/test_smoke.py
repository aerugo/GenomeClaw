"""Smoke tests for the toolkit package shape.

These verify the basics: the package imports, the new ``genomeclaw``
console entry point is reachable, the planned subpackages exist, and
the test-category directories are present.

Updated post-rich-cli Phase 1: the entry point is ``genomeclaw`` (not
``genomeclaw``); the CLI lives under ``_cli`` (not ``cli``).
"""

from __future__ import annotations

import importlib
import subprocess
from pathlib import Path


def test_package_imports() -> None:
    """The ``genomeclaw_toolkit`` package imports + carries a version string."""
    mod = importlib.import_module("genomeclaw_toolkit")
    assert hasattr(mod, "__version__")
    assert isinstance(mod.__version__, str)
    assert mod.__version__


def test_cli_help_runs() -> None:
    """``genomeclaw --help`` exits 0 and references the program name."""
    result = subprocess.run(
        ["genomeclaw", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "genomeclaw" in result.stdout.lower()


def test_subpackages_exist() -> None:
    """The canonical subpackages are all importable."""
    for name in ("_cli", "prep", "service", "schemas"):
        importlib.import_module(f"genomeclaw_toolkit.{name}")


def test_test_categories_directories_exist() -> None:
    """The seven first-class test category dirs are present as Python packages."""
    here = Path(__file__).resolve().parent
    for sub in (
        "integration",
        "provenance",
        "determinism",
        "privacy",
        "evidence",
        "reports",
        "invariants",
    ):
        assert (here / sub / "__init__.py").exists(), sub
