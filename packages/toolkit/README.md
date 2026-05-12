# genomeclaw-toolkit

Host-side bioinformatics toolkit for GenomeClaw. Owns the `genomeclaw-prep`
CLI, the FastAPI host service, and the schemas they share.

> Phase 1 (current): scaffolding only. `genomeclaw-prep --help` runs;
> subcommands print a "not implemented yet" notice and return non-zero.
> Real pipeline work lands in Phase 2 onward.
> See [`docs/plans/active/mvp/`](../../docs/plans/active/mvp/) for the plan.

## Requirements

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/) ≥ 0.5

## Install + run tests

From the repository root:

```bash
cd packages/toolkit
uv sync                # creates a venv and installs deps
uv run pytest -q       # runs the test suite
uv run ruff check .    # lints
uv run genomeclaw-prep --help
```

## Layout

```text
packages/toolkit/
├── pyproject.toml
├── README.md
├── src/genomeclaw_toolkit/
│   ├── __init__.py            # exports __version__
│   ├── cli.py                 # genomeclaw-prep entry point
│   ├── prep/                  # pipeline subcommands (Phase 2+)
│   ├── service/               # FastAPI host service (Phase 5)
│   └── schemas/               # Pydantic models (Phase 2+)
└── tests/
    ├── test_smoke.py          # Phase 1 smoke tests
    ├── integration/           # ingest -> normalize -> annotate -> query
    ├── provenance/            # canonical provenance columns + manifest versions
    ├── determinism/           # byte-equivalent reruns
    ├── privacy/               # privacy-default egress assertions
    ├── evidence/              # finding -> evidence binding
    ├── reports/               # rendered-prose snapshot tests
    └── invariants/            # one or more tests per INV-xxx
```

The seven test-category directories match the first-class test categories
in [`docs/plans/CLAUDE.md`](../../docs/plans/CLAUDE.md). Phases drop tests
into the matching directory and name invariant tests so the `INV-xxx`
identifier appears in the filename or test name.
