"""Command groups for the GenomeClaw CLI.

Each module under this package owns one command group:

* :mod:`host` — environment setup, eject, diagnostic.
* :mod:`refs` — reference data: list, fetch, verify, info.
* :mod:`runs` — derived-run history: list, show, current.
* :mod:`pipeline` — orchestrators: ingest, normalize, annotate,
  materialize, run.

Group modules export their Typer ``app`` instance via the
``register(parent)`` function the top-level CLI calls during boot.
Adding a new group is a single-module change — no edits to the
top-level ``_cli/__init__.py`` beyond an import.

Quality bar: every command function has a Google-style docstring;
every public payload model is a Pydantic ``BaseModel``; ruff strict +
mypy strict are gates on this package.
"""

from __future__ import annotations
