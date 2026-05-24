# Codebase Functional Review

**Date**: 2026-05-24
**Scope**: subjective qualitative review — is the code logical, elegant, consistent, understandable?
**Method**: read representative modules in full, capture pull quotes, form judgments
**Companion to**: [codebase-maintainability-review-2026-05-24.md](codebase-maintainability-review-2026-05-24.md) (structural/typing audit)

---

## 0. TL;DR

The graduated core of GenomeClaw reads like **professionally finished work**: a tight CLI dispatch with a textbook exception boundary, a clear schema ontology with validators that encode invariants rather than busywork, and a pipeline orchestration template that is rigid enough to be predictable and narrative enough to be readable cold. The code thinks out loud about its own design choices in comments that future-you will be grateful for.

The drift is concentrated where you'd expect it — in the legacy `prep/` modules that have not graduated yet. The drift is not sloppy; it is **unfinished** in the specific sense that those modules are well-engineered toolkits but not yet integrated into the event/narrative/progress fabric the graduated modules share.

If I had to put it in one sentence: **the canon is real, the canon is good, and most of the code follows it.**

---

## 1. The Style Canon

A reader can extract the codebase's intended style from four anchor points:

1. **The exception boundary** at [_cli/__init__.py:196-267](../../packages/toolkit/src/genomeclaw_toolkit/_cli/__init__.py)
2. **The `emit()` dispatch** at [_cli/output.py:95-124](../../packages/toolkit/src/genomeclaw_toolkit/_cli/output.py)
3. **The ingest orchestrator narrative** at [prep/ingest.py:3-16](../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py)
4. **The `_enforce_inv_c001` model validator** at [schemas/finding.py](../../packages/toolkit/src/genomeclaw_toolkit/schemas/finding.py)

Each of these is **exemplary, not aspirational** — they exist in the code today, they work, and they set the bar for how the rest of the codebase should read.

### 1.1 The exception boundary — calm and complete

```python
def main(argv: list[str] | None = None) -> NoReturn:
    """Console-script entry point."""
    ...
    try:
        app(args=argv, standalone_mode=False)
    except CliError as exc:
        _emit_error(exc, debug=_is_debug_mode(effective_argv), argv=effective_argv)
        raise SystemExit(exc.exit_code) from exc
    except KeyboardInterrupt:
        get_console().print("\n[yellow]Interrupted.[/yellow]")
        raise SystemExit(EXIT_INTERRUPTED) from None
```

The boundary maps every failure shape to a stable exit code, and the helper `_emit_error` knows how to route the error envelope to stdout-vs-stderr depending on whether stdout has already been consumed. **It is the right amount of code for the job.** Nothing here is decorative.

### 1.2 The `emit()` dispatch — one place for the mode switch

```python
def emit(
    *,
    ctx: AppContext,
    command: str,
    payload: _PayloadT,
    rich_renderer: Callable[[_PayloadT], None],
) -> None:
    if ctx.is_json:
        envelope: CliEnvelope[Any] = CliEnvelope(command=command, payload=payload)
        sys.stdout.write(envelope.model_dump_json(exclude_none=True))
        ...
        mark_stdout_consumed()
        return
    rich_renderer(payload)
```

The pattern is: every command produces a Pydantic payload plus a renderer callable. The JSON-vs-Rich switch lives **here, once.** Commands are blind to which mode they're in. This is the kind of abstraction that pays back rent every time a new command is added.

### 1.3 The ingest narrative — design rendered as ASCII

```python
"""Composes the Phase-2 primitives into a single happy-path pipeline:

    validate inputs
        └→ compute SHA256 of source VCF
            └→ read contigs from header
                └→ sniff reference build (raises AmbiguousReferenceBuild)
                    └→ generate run-id
                        └→ create derived/<run-id>/
                            └→ index VCF if .tbi missing (under derived/)
                                └→ create DuckDB store + write variants
                                    └→ write manifest.json + provenance.json
                                        └→ atomically swing CURRENT
"""
```

Reading this is a **30-second cold-start** for any new contributor. You know the shape before reading a line of executable code. The remainder of the function obeys the diagram — the `emit_beat()` calls inside the body telegraph each step. The module is **self-documenting via event sequence**.

### 1.4 The finding model validator — invariants as code

```python
@model_validator(mode="after")
def _enforce_inv_c001(self) -> Finding:
    """Enforce `INV-C001` v1.5 in the model.

    Two failure modes:
    - clinical-actionable without escalation: agent renders as
      benign-looking prose, hiding urgency.
    - non-actionable WITH escalation: falsely elevates a lifestyle
      or non-actionable finding to clinical urgency.
    """
    if self.category == "clinical-actionable":
        if self.clinical_escalation is None:
            raise ValueError(
                "INV-C001 v1.5: clinical-actionable findings must declare a "
                "clinical_escalation marker (confirm_with_provider | urgent_consultation)"
            )
    ...
```

Three things here are good simultaneously: the validator **names the invariant it enforces**, its docstring **names the two failure modes** it prevents, and the `ValueError` message **cites the invariant version**. This is not a type check disguised as a validator. It is a state-machine rule, traceable to the specification, written so that a triage-time test failure tells you exactly what design rule fired.

---

## 2. Where the Canon Holds

A handful of additional pull quotes show the canon spreading:

### 2.1 Suggested actions are specific, not generic

From [_cli/commands/runs.py:170-180](../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/runs.py):

```python
raise PreconditionError(
    f"Run {run_id!r} not found under {derived_root}.",
    details={"run_id": run_id, "derived_root": str(derived_root)},
    suggested_actions=[
        "Run `genomeclaw runs list` to see available runs.",
        "Or `genomeclaw pipeline ingest` to create a new one.",
    ],
)
```

Every CLI error carries `suggested_actions`. They are **actionable and specific** — not "try again" noise. The error is also Pydantic-friendly via `to_envelope()` so it serializes cleanly into JSON mode.

### 2.2 Design comments embed the why

From [prep/materialize.py:233-243](../../packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py):

```python
# Per-row provenance attributes to the **source-of-truth VCF**, not
# the intermediate normalized VCF. Two reasons:
# 1. Determinism. ``bcftools norm`` embeds the wall-clock date + the
#    output path into the VCF header, so ``normalized.vcf.gz``'s
#    SHA256 isn't byte-stable across runs of identical inputs;
#    stamping that SHA on every row would poison the determinism
#    contract.
# 2. Semantics. The canonical identity of a variant row is the
#    genome file the user supplied...
```

This is **design thinking embedded in code**. A future maintainer doesn't have to guess why the provenance points at the source VCF — they get the reasoning and the rejected alternative. Comments like this only appear when someone has actually wrestled with the problem.

### 2.3 Failures of the past are documented at the failure site

From [prep/coverage_fill.py:213-214](../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py):

```python
# 2026-05-19 smoke failed with ``No such file: merged.vcf.gz.vcf`` —
# pgsc_calc auto-appends ``.vcf`` and re-detects ``.gz``.
```

This is **provenance of the code itself**. Three months from now, when someone wonders why this stem-rename exists, they get the smoke date and the upstream bug.

### 2.4 Schema ontology is a real hierarchy, not a pile of tables

```
Finding ──evidence_ref──→ Evidence ──EvidenceKind──→ (clinvar | pgs_catalog | pharmgkb)
   │
   └──variant_key──→ Variant
```

The composition is **semantic, not foreign-key**. `evidence_ref: str` carries `"clinvar:RCV000031"` rather than a database ID, so schemas stay independent while the resolver contract is documented in one place. Every schema declares `ConfigDict(extra="forbid")` — there are no `dict[str, Any]` escape hatches anywhere in [schemas/](../../packages/toolkit/src/genomeclaw_toolkit/schemas/).

---

## 3. Where the Canon Drifts

Three drift patterns are worth naming. None of them are sloppy; they are all "the work is unfinished in a way you can predict from looking at where the work began."

### 3.1 Non-graduated modules skip the event fabric

Compare what every graduated phase looks like…

```python
# prep/ingest.py:260-262
phase_start_mono = time.monotonic()
if progress_callback is not None:
    progress_callback(PhaseStart(phase="ingest"))
emit_beat(progress_callback, phase="ingest", message="...", logger=log)
```

…with `prep/pgs.py` and `prep/coverage_fill.py`, which **have no `progress_callback` argument at all**. The CLI can render live progress for an ingest run; it cannot render live progress for a PRS compute. This is not a bug — those modules pre-date the event contract — but it is a **missed integration point** that becomes visible when the user is staring at a silent terminal during a 20-minute PRS run.

The fix is mechanical: thread `progress_callback` through, build the same `ProvenanceTag` at the same moment, emit the same `PhaseStart`/`PhaseComplete` envelope. The module is professionally engineered already; the integration work is small.

### 3.2 Command-level logic creeps into the long commands

Compare the short command [_cli/commands/runs.py](../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/runs.py) — where every command function is a thin delegator — with [_cli/commands/refs.py:148-275](../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py):

```python
if all_sources:
    if source is not None or release is not None:
        raise UsageError("--all is mutually exclusive with --source / --release.")
    _fetch_release_set(...)
    return

if source is None or release is None:
    raise UsageError("--source and --release are required...")

if source not in _valid_fetch_sources():
    raise UsageError(...)
```

The validation is shallow and correct, but it is **command-level rather than delegated**. Worse, `_emit_release_sets()` (lines 282–330) embeds a mini-renderer inside the command file with a JSON branch (lines 292–322), violating the principle that renderers live in `_cli/renderers/`. The pattern works; it just doesn't feel as polished as `runs.py`. This is the place the style canon is showing its earliest cracks.

### 3.3 Shared helpers are copy-pasted, not consolidated

`_sha256_file` appears verbatim in four files:

- [prep/ingest.py:98-103](../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py)
- [prep/normalize.py:47-52](../../packages/toolkit/src/genomeclaw_toolkit/prep/normalize.py)
- [prep/annotate.py:54-59](../../packages/toolkit/src/genomeclaw_toolkit/prep/annotate.py)
- [prep/materialize.py:57-62](../../packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py)

```python
def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()
```

This is a **style signal**, not a bug. Each graduated orchestrator carries its own private helpers rather than reaching into a shared `prep/_util.py`. The rule in CLAUDE.md says "three similar lines is better than a premature abstraction," but four identical functions in four files is past that threshold.

---

## 4. Small Consistency Dings

These are small enough to fix in one sitting, large enough to surface in a functional review.

| # | Issue | Where | Fix shape |
|---|---|---|---|
| 1 | Mixed temporal field names: `created_at` everywhere except `Step.started_at` / `Step.completed_at` | `schemas/provenance.py:37-38` vs the rest of `schemas/` | Justified for steps (they have two timestamps), but the inconsistency could be documented at the field level so a new reader doesn't wonder if they mean the same thing |
| 2 | `rsid` and `dbsnp_rsid` coexist on the variant model | `schemas/variant.py:39, 67` | Pick one and add a `Field(description=...)` explaining what the other meant historically |
| 3 | Field-level documentation is sparse — model docstrings are excellent but most fields lack `Field(description="...")` | All of `schemas/` | A bioinformatician reading `title: str` on a `Finding` cannot tell whether that's a diagnosis code, prose, or a structured label |
| 4 | Some `# type: ignore[union-attr]` in `prep/pgs.py:547-589` are now unused per mypy | `prep/pgs.py:547-589` | Janitorial — delete the unused ignores |
| 5 | Two `urllib.request.urlopen` monkeypatches in `tests/privacy/test_invP001_cli_no_egress.py` bypass the `monkeypatch` fixture | privacy tests | Risk of cross-test state corruption on error before `finally` |

---

## 5. Two Genuine Elegance Wins

Worth calling out because they're the kind of work most codebases never finish:

### 5.1 The error taxonomy is semantic, not categorical

[_cli/errors.py:30-35](../../packages/toolkit/src/genomeclaw_toolkit/_cli/errors.py):

```python
EXIT_SUCCESS = 0
EXIT_RUNTIME_ERROR = 1
EXIT_USAGE_ERROR = 2
EXIT_PRECONDITION_ERROR = 3
EXIT_DATA_INTEGRITY_ERROR = 4
EXIT_INTERRUPTED = 130
```

Five concrete subclasses (`CliError`, `RuntimeFailure`, `UsageError`, `PreconditionError`, `DataIntegrityError`) map to five exit codes. Each subclass is documented with its semantics — when to raise it, with examples. The class hierarchy is not a "list that grew" — it is **the result of someone asking, what are the meaningfully distinct ways a CLI run can fail, and how should a shell script differentiate them?**

### 5.2 `SiblingMountablePath` as a type token

[prep/_paths.py:62](../../packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py):

```python
class SiblingMountablePath(type(Path())):  # type: ignore[misc]
    """A ``Path`` validated as visible on the host filesystem."""
```

This is **a typed boundary, not a workaround**. The factory `as_sibling_mountable()` does the validation; the subclass exists so mypy can refuse to let an un-validated path slip into a function that mounts it into a DooD sibling container. Path-safety is one of the things this codebase has actually been burned by — see [path-crossing-discipline.md](path-crossing-discipline.md) — and the type discipline here is the codified response.

The multi-line error messages (`_paths.py:195-244`) are equally good — they name the fixable alternatives (`shard_scratch`, `work_dir`, `GENOMECLAW_*_DIR` env vars) with enough context that a user reading the message at 2 AM can fix the problem without grepping the source.

---

## 6. Honest Weaknesses

Not the structural ones from the maintainability review — the qualitative ones a reader feels.

### 6.1 The big files reward navigation, not reading

[prep/fetch.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py) (1,654 lines), [_cli/commands/pipeline.py](../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py) (1,464 lines), and [prep/coverage_fill.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) (1,388 lines) are not unreadable — they are well-chunked internally — but you don't **read** them cold the way you can read `ingest.py` cold. The function bodies are competent, but the module-level docstring doesn't give you the ASCII diagram, the invariant labels, or the "what happens when" telegraph that the smaller graduated modules give you.

`coverage_fill.py` is the most striking example: the first 300 lines are helper functions (`_parse_faidx_fasta`, `_get_reference_bases`, `_parse_prune_in_to_alleles`), and the orchestrator entry point is not visible until you scroll well past that. The module is **mechanically rigorous** but **not introspectively clear**. A new reader has to work harder.

### 6.2 Subprocess discipline is inconsistent

The `bcftools_run()` wrapper at [prep/_bcftools.py:82-100](../../packages/toolkit/src/genomeclaw_toolkit/prep/_bcftools.py) is the right pattern: capture output, check exit code, convert stderr into a typed exception. But `prep/fetch.py` calls `subprocess.run()` inline for samtools and gunzip, and `prep/coverage_fill.py` mixes `subprocess.run()` and `subprocess.Popen()` for bcftools pipes and plink2 invocations, some of which lack explicit error checking. The discipline exists in one place; extending it to plink2 and samtools would let every subprocess failure surface as the same typed exception shape.

### 6.3 Rendering logic occasionally leaks into command files

The `_emit_release_sets()` helper in [_cli/commands/refs.py:282-330](../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/refs.py) builds a JSON envelope inline rather than handing a payload + a renderer to `emit()`. It's a small leak — one helper in one file — but it's the kind of thing that, if not caught, becomes the precedent the next command author follows.

### 6.4 The pgs.py Nextflow override comments are excellent — but they're alone

The block at `prep/pgs.py:252-300` explaining which Nextflow override fixes which smoke failure ("smoke v11, v14, v22c") is the **best comment in the codebase**. It tells you the smoke run, the failure mode, and why the override is necessary. But that style is mostly absent from `pgs.py` more broadly — the rest of the module reads like a requirements checklist, not a design narrative. The graduated modules have it; the non-graduated modules deserve it.

---

## 7. Recommendations

In order of leverage, not order of effort:

1. **Promote the integration shape, not just the typing.** When a `prep/` module graduates into the strict-typing scope, also (a) thread `progress_callback`, (b) add an ASCII-diagram docstring, (c) label invariants in comments. The strict-typing graduation is the gate; the readability graduation should ride alongside.

2. **Extract `prep/_util.py` for the four-times-copied helpers.** Start with `_sha256_file` and `_serialise_for_json`. Two functions, one new file, immediate decrease in coordinated-edit surface.

3. **Promote `bcftools_run()` to `prep/_subprocess.py`** with a generic shape, then port `plink2`, `samtools`, and `gunzip` invocations to it. Same capture, same error wrapping, same timeout policy.

4. **Add `Field(description="...")` to the schema fields a bioinformatician would hesitate on**: `Finding.title`, `Finding.category`, `Variant.rsid` vs `Variant.dbsnp_rsid`, `CoverageQCRow.mean_depth` nullability. Model docstrings are great; field docstrings would close the last documentation gap.

5. **Move `_emit_release_sets()` from `refs.py` into `_cli/renderers/`.** Small refactor, restores the rule that commands hand off to renderers.

6. **Audit the unused `# type: ignore` comments in `prep/pgs.py:547-589`.** Mypy already reports them as unused; this is a janitorial sweep.

---

## 8. Bottom Line

This codebase reads like the work of someone who **finishes things**. Where the work is done — the CLI dispatch, the schemas, the four graduated prep phases, the error taxonomy, the path-safety subclass — it is finished to a standard you don't usually see in pre-Phase-5 alpha. Where the work is unfinished, it is **unfinished in predictable, fixable ways**, and the codebase has already named the path forward in [pyproject.toml:131-144](../../packages/toolkit/pyproject.toml).

The most important quality of this code is that **its own design choices are written down inside the code itself**. The materialize provenance comment, the pgs.py Nextflow overrides, the coverage_fill smoke-failure annotations — these are the artifacts of a maintainer who has been burned and learned, and who has decided that the next maintainer should not have to learn the same lessons. Functional code review highlights these because they're rare. This one has more than most.

---

## 9. Pull Quotes (Reference)

For anyone wanting to see the canon at a glance:

- **Exception boundary**: [_cli/__init__.py:196-267](../../packages/toolkit/src/genomeclaw_toolkit/_cli/__init__.py)
- **Output dispatch**: [_cli/output.py:95-124](../../packages/toolkit/src/genomeclaw_toolkit/_cli/output.py)
- **Error taxonomy**: [_cli/errors.py:30-142](../../packages/toolkit/src/genomeclaw_toolkit/_cli/errors.py)
- **Suggested actions example**: [_cli/commands/runs.py:170-180](../../packages/toolkit/src/genomeclaw_toolkit/_cli/commands/runs.py)
- **Orchestration narrative**: [prep/ingest.py:3-16](../../packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py)
- **Design comment**: [prep/materialize.py:233-243](../../packages/toolkit/src/genomeclaw_toolkit/prep/materialize.py)
- **Smoke-failure annotation**: [prep/coverage_fill.py:213-214](../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py)
- **Invariant-as-validator**: [schemas/finding.py](../../packages/toolkit/src/genomeclaw_toolkit/schemas/finding.py) `_enforce_inv_c001`
- **Provenance contract**: [schemas/__init__.py:27-40](../../packages/toolkit/src/genomeclaw_toolkit/schemas/__init__.py)
- **Path safety token**: [prep/_paths.py:62](../../packages/toolkit/src/genomeclaw_toolkit/prep/_paths.py), error messages at `_paths.py:195-244`
- **Nextflow override block**: [prep/pgs.py:252-300](../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py)
