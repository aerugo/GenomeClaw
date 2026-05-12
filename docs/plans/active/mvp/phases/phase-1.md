# Phase 1: Repo scaffolding & test infrastructure

**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Establish a working `packages/toolkit/` Python package with a usable test harness, a `genomeclaw-prep` CLI entrypoint stub, and a CI workflow. No genome work, no invariant assertions beyond "the test infrastructure runs and the package imports." The goal is to clear the runway so subsequent phases can land code without wrestling toolchain.

## Scope Boundaries

- **In scope**:
  - `packages/toolkit/pyproject.toml` (uv-managed Python project).
  - `packages/toolkit/src/genomeclaw_toolkit/` package skeleton with `cli.py`, `prep/`, `service/`, `schemas/` subpackages (each containing only `__init__.py` for now).
  - `packages/toolkit/tests/` directory with subdirectories matching the first-class test categories (`integration/`, `provenance/`, `determinism/`, `privacy/`, `evidence/`, `reports/`, `invariants/`) — each with an `__init__.py` and a placeholder skip-marker test.
  - A `genomeclaw-prep` console-script entrypoint that runs and prints `--help`.
  - `.github/workflows/test.yml` running pytest + lint on push/PR.
  - A `README.md` inside `packages/toolkit/` documenting how to install and run tests locally.
- **Out of scope**:
  - Any pipeline subcommand beyond `--help`.
  - Any provenance, determinism, or privacy assertions.
  - The host service (`packages/toolkit/src/genomeclaw_toolkit/service/` is empty for now).
  - Schemas (`packages/toolkit/src/genomeclaw_toolkit/schemas/` is empty for now).
  - Plugin work (no changes to `packages/nemoclaw-plugin/`).

## Invariants Enforced in This Phase

None of `INV-Dxxx` / `INV-Exxx` / `INV-Pxxx` / `INV-Cxxx` yet — this phase is foundations. The only assertion is that the test harness itself works.

A test naming convention is established here so later phases can drop in invariant tests without renaming:

```text
packages/toolkit/tests/invariants/test_invD001_*.py
packages/toolkit/tests/invariants/test_invD002_*.py
packages/toolkit/tests/invariants/test_invE001_*.py
packages/toolkit/tests/invariants/test_invP001_*.py
packages/toolkit/tests/invariants/test_invP002_*.py
packages/toolkit/tests/invariants/test_invR001_*.py
packages/toolkit/tests/invariants/test_invC001_*.py
```

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

Create `packages/toolkit/tests/test_smoke.py`:

**Test cases**:

1. `test_package_imports` — `import genomeclaw_toolkit` succeeds; the version is readable.
2. `test_cli_help_runs` — running `genomeclaw-prep --help` exits 0 and prints a banner that includes `genomeclaw-prep`.
3. `test_subpackages_exist` — the four subpackages (`cli`, `prep`, `service`, `schemas`) all import.
4. `test_test_categories_directories_exist` — the seven test category subdirectories under `tests/` all exist as importable packages (so later phases can drop in tests under canonical paths).

**Sketch** (illustrative, not final):

```python
import importlib
import subprocess
from pathlib import Path


def test_package_imports():
    mod = importlib.import_module("genomeclaw_toolkit")
    assert hasattr(mod, "__version__")


def test_cli_help_runs():
    result = subprocess.run(
        ["genomeclaw-prep", "--help"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0
    assert "genomeclaw-prep" in result.stdout


def test_subpackages_exist():
    for name in ("cli", "prep", "service", "schemas"):
        importlib.import_module(f"genomeclaw_toolkit.{name}")


def test_test_categories_directories_exist():
    here = Path(__file__).resolve().parent
    for sub in ("integration", "provenance", "determinism",
                "privacy", "evidence", "reports", "invariants"):
        assert (here / sub / "__init__.py").exists(), sub
```

After writing the tests, **run them and confirm they fail for the intended reason** (e.g., `ModuleNotFoundError: genomeclaw_toolkit`). Paste the failing output into `work-notes.md`.

### Step 1.2 — GREEN: Minimal Implementation

Land the smallest set of files that turns the tests green.

**Files to create**:

```text
packages/toolkit/
├── pyproject.toml                  # uv project; defines genomeclaw-prep entry-point
├── README.md                       # how to install and run locally
├── src/
│   └── genomeclaw_toolkit/
│       ├── __init__.py             # exports __version__
│       ├── cli.py                  # argparse / click / typer entrypoint with --help
│       ├── prep/__init__.py
│       ├── service/__init__.py
│       └── schemas/__init__.py
└── tests/
    ├── __init__.py
    ├── test_smoke.py               # the four tests above
    ├── integration/__init__.py
    ├── provenance/__init__.py
    ├── determinism/__init__.py
    ├── privacy/__init__.py
    ├── evidence/__init__.py
    ├── reports/__init__.py
    └── invariants/__init__.py
```

**`pyproject.toml`** outline (no real deps yet, just the entrypoint):

```toml
[project]
name = "genomeclaw-toolkit"
version = "0.0.1"
description = "GenomeClaw host-side bioinformatics toolkit (CLI + service)"
requires-python = ">=3.11"
license = "Apache-2.0"

[project.scripts]
genomeclaw-prep = "genomeclaw_toolkit.cli:main"

[tool.uv]
dev-dependencies = ["pytest>=8", "ruff>=0.5"]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
```

**`cli.py`** — minimal `--help` runner; prints the planned subcommand list as a sketch:

```python
"""genomeclaw-prep — host-side pipeline CLI (Phase 1: scaffold only)."""

import argparse
import sys


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="genomeclaw-prep",
        description="GenomeClaw host pipeline. Subcommands land in later phases.",
    )
    sub = parser.add_subparsers(dest="cmd")
    for name, help_ in [
        ("fetch", "(Phase 2) download reference and annotation data"),
        ("ingest", "(Phase 2) ingest a Nebula VCF"),
        ("normalize", "(Phase 3) normalize a VCF (left-align, split multi-allelics)"),
        ("annotate", "(Phase 4) annotate a normalized VCF"),
        ("materialize", "(Phase 3/4) materialize the derived store"),
    ]:
        sub.add_parser(name, help=help_)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    parser.parse_args(argv)
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

### Step 1.3 — REFACTOR

With tests green:

- Tighten `pyproject.toml` metadata (license, classifiers, project URLs).
- Confirm `ruff` runs cleanly on the package (configure `pyproject.toml [tool.ruff]` minimally).
- Add `mypy` config later — not now (Phase 1 is foundations only).
- Re-run tests to confirm green.

---

## Implementation Details

### Toolchain choice

- **Python 3.11+** — matches the bioinformatics ecosystem.
- **uv** — for dependency management, virtualenv, locking. Already implied by NemoClaw's stack which uses uv.
- **pytest** — test runner.
- **ruff** — formatter + linter.

### CI Workflow

`.github/workflows/test.yml`:

```yaml
name: test
on:
  push:
    branches: [main, "feature/**"]
  pull_request:
    branches: [main]
jobs:
  toolkit:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: packages/toolkit
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync
      - run: uv run pytest -q
      - run: uv run ruff check .
```

### Edge Cases to Handle

- `genomeclaw-prep` (no args) must not crash; printing help and exiting 0 is acceptable for Phase 1.
- The CI workflow must NOT install bioinformatics tools (`samtools` etc.) — those land in Phase 2 with proper `INV-D002` discipline (toolkit deps only on the host, never inside the sandbox image).

### Privacy / Egress Notes

- No network calls in Phase 1.
- No data files in Phase 1.
- No secrets in Phase 1.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/pyproject.toml` | CREATE | uv project + `genomeclaw-prep` entrypoint |
| `packages/toolkit/README.md` | CREATE | local install + test instructions |
| `packages/toolkit/src/genomeclaw_toolkit/__init__.py` | CREATE | exports `__version__` |
| `packages/toolkit/src/genomeclaw_toolkit/cli.py` | CREATE | `--help` entrypoint |
| `packages/toolkit/src/genomeclaw_toolkit/{prep,service,schemas}/__init__.py` | CREATE | empty subpackages |
| `packages/toolkit/tests/__init__.py` | CREATE | tests root |
| `packages/toolkit/tests/test_smoke.py` | CREATE | smoke + import + entrypoint tests |
| `packages/toolkit/tests/{integration,provenance,determinism,privacy,evidence,reports,invariants}/__init__.py` | CREATE | seven first-class test category dirs |
| `.github/workflows/test.yml` | CREATE | CI |

---

## Verification

```bash
# From the repo root
cd packages/toolkit

# Install + test
uv sync
uv run pytest -q

# CLI smoke
uv run genomeclaw-prep --help

# Lint
uv run ruff check .
```

Expected outcomes:
- `pytest` reports 4 passing tests.
- `genomeclaw-prep --help` exits 0 and prints a banner mentioning the planned subcommands.
- `ruff check` passes with no errors.

CI:
- Push to `feature/mvp` triggers `.github/workflows/test.yml`.
- The workflow runs the same three commands and reports green.

---

## Completion Criteria

- [ ] All four `test_smoke.py` test cases pass.
- [ ] `uv run genomeclaw-prep --help` exits 0 with the expected banner.
- [ ] `uv run ruff check .` passes.
- [ ] CI workflow runs green on a feature branch.
- [ ] `work-notes.md` updated with the RED failing output, the GREEN diff summary, and the final test results.
- [ ] Phase 1 status set to **Complete** in [development-plan.md](../development-plan.md).
- [ ] [phases/phase-2.md](phase-2.md) authored and ready before Phase 1 is closed.
