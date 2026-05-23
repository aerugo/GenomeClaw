# Phase 4 — Worker compute integration

**Status**: **Complete**
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Replace Phase 3's `_noop_compute_fn` with the real `compute_prs_with_coverage_fill(...)` call + result persistence via the post-v23 `_stamp_pgs_row(...)` wiring. The worker now reads a `prs_compute_config.json` sidecar from the active run-dir (one-time-per-deployment configuration), invokes the Tier 1 + Tier 2 + merge + pgsc_calc algorithm `bin/genomeclaw-prs-smoke` already drives end-to-end, and stamps the resulting `pgs_scores` + `findings` row with the seven canonical INV-R001 provenance columns + INV-A003 `agent_choice_rationale` + `requested_for_question`. Errors are mapped to a structured `failed:<class>:<message>` shape rather than the catch-all `worker_unexpected_error` Phase 3 emitted.

## Scope Boundaries

- **In scope**:
  - `prs_compute_config.json` sidecar reader + validator.
  - Worker swaps `_noop_compute_fn` for `_real_compute_fn` that invokes `compute_prs_with_coverage_fill(...)` via `loop.run_in_executor(...)` (the call is blocking + CPU/IO-heavy; offloading prevents starving the FastAPI event loop).
  - Result persistence via `_stamp_pgs_row(...)` (the same shape `prs-compute --run-dir` uses).
  - INV-R002 degenerate-result guard — if the returned `PgsRow` carries a degenerate state, fail the task instead of stamping.
  - Structured error mapping for the known failure modes: `scorefile_missing`, `pgsc_calc_failed`, `zero_overlap`, `dood_path_error`, `prs_decline`.
  - Tests using a stub `compute_fn` (mocked at the call-site, not the underlying tools) — the worker's job is to wire inputs + outputs + errors; the underlying compute already has its own coverage in `tests/integration/test_compute_prs_with_coverage_fill.py` + the smoke v23 real-data verification.
- **Out of scope** (deferred):
  - Stale-running cleanup at app startup — Phase 5.
  - INFO-level transition logging — Phase 5.
  - End-to-end agent live test against the canonical run — Phase 6.
  - Scorefile auto-fetch at compute time — out of plan scope entirely (the worker surfaces `scorefile_missing:PGS<id>` + the agent's `error_hint` carries the `refs fetch` command).
  - Multi-sample compute — out of plan scope.

## Invariants Enforced in This Phase

- **INV-A003** (Agent-Curated Compute Provenance) — the worker threads `task.rationale` → `compute_prs_with_coverage_fill(agent_choice_rationale=...)` → `PgsRow.agent_choice_rationale` → `_stamp_pgs_row(...)` → `pgs_scores` row. A test enqueues with a distinctive rationale + asserts the resulting `pgs_scores` row carries that exact string.
- **INV-R001** (Rebuildability) — the seven provenance columns (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`) appear on every `pgs_scores` row the worker writes. A test inspects a worker-written row + asserts all seven are non-null.
- **INV-R002** (Never Cache a Degenerate Result) — a degenerate `PgsRow` (e.g. `pgs_variant_count == 0` or `score is None`) transitions the task to `failed:degenerate_result:<reason>` instead of stamping a `pgs_scores` row. A test injects a degenerate result + asserts no row appears in `pgs_scores`.

---

## TDD Steps

### Step 4.1 — RED: Write failing tests

Two new test files:

**A. `packages/toolkit/tests/integration/test_pgs_compute_worker_integration.py`** — happy-path + error mapping with a stub compute_fn.

**Test cases**:

1. `test_worker_invokes_real_compute_with_threaded_provenance` — enqueue with `rationale="canonical AMD PRS; smoker-relevant"` + `requested_for_question="do I have AMD risk?"` → stub `compute_prs_with_coverage_fill` records the kwargs it was called with → assert `agent_choice_rationale` + `requested_for_question` match the enqueued values verbatim. (INV-A003 plumbing.)
2. `test_invR001_worker_stamps_seven_provenance_columns` — happy-path completion → query the `pgs_scores` row by `pgs_id` → assert all seven INV-R001 columns are non-null + carry the documented shapes (`schema_version=cache.active.schema_version`, `tool="pgsc_calc"`, `tool_version="agent-driven"`, etc.). Mirrors the existing CLI-path provenance test.
3. `test_invR002_degenerate_result_does_not_stamp` — stub compute returns a `PgsRow` with `pgs_variant_count=0` → assert task transitions to `failed:degenerate_result:zero_overlap` AND no row exists in `pgs_scores` for that `pgs_id`.
4. `test_worker_persists_pgs_scores_and_findings` — happy-path completion → query both `pgs_scores` + `findings` tables → assert one row each, with the `findings` row's `kind="clinical-non-actionable"` (or whatever the canonical `_stamp_pgs_row` shape produces).
5. `test_worker_maps_scorefile_missing_to_structured_error` — stub compute raises `PgsScorefileMissingError("PGS004606")` → task → `failed:scorefile_missing:PGS004606`. The `error_hint` (if surfaced) carries the `genomeclaw refs fetch --source pgs_scorefile --pgs-id PGS004606` command shape.
6. `test_worker_maps_pgsc_calc_failure_to_structured_error` — stub raises `subprocess.CalledProcessError(rc=1, cmd=["nextflow", ...])` → task → `failed:pgsc_calc_failed:rc=1`.
7. `test_worker_maps_dood_path_error` — stub raises `DooDPathError(...)` → task → `failed:dood_path_error:<path>`. (This is exactly the INV-D006 surface the from-scratch-setup-protections cascade hardened against; the worker should not silently swallow it.)
8. `test_worker_maps_prs_decline` — stub raises `PRSDeclineError("decline_calibration_low_match", reason1, reason2)` → task → `failed:prs_decline:decline_calibration_low_match`. (Calibration DECLINE is an expected failure mode under INV-C001 v1.7; the agent surfaces the named reasons in the user-facing reply, but the task itself is `failed`.)
9. `test_worker_runs_compute_in_executor_not_event_loop` — instrument the stub to assert it was invoked from a thread distinct from the event loop's main thread (`threading.get_ident() != main_thread_ident`). Guards against accidentally awaiting a blocking call directly on the loop.

**B. `packages/toolkit/tests/integration/test_pgs_compute_config_loader.py`** — config sidecar contract.

**Test cases**:

10. `test_compute_config_loader_reads_canonical_sidecar` — write a `prs_compute_config.json` in a tmp run-dir with the canonical schema → loader returns a typed `PrsComputeConfig` dataclass with the right fields.
11. `test_compute_config_loader_missing_file_raises_with_canonical_path` — no sidecar → raises `PrsComputeConfigMissingError` whose message names the expected path (`<run-dir>/prs_compute_config.json`) so the operator can fix it.
12. `test_compute_config_loader_malformed_json_raises` — write invalid JSON → raises `PrsComputeConfigMalformedError`.
13. `test_compute_config_loader_missing_required_field_raises` — write JSON missing `cram_path` → raises `PrsComputeConfigMalformedError` naming the missing field.

**Sketch** (worker integration test):

```python
@pytest.mark.asyncio
async def test_worker_invokes_real_compute_with_threaded_provenance(
    tmp_path, monkeypatch, fake_compute_prs_with_coverage_fill
):
    monkeypatch.setenv("GENOMECLAW_PGS_WORKER_POLL_INTERVAL_S", "0.05")
    derived_root = _make_derived_root_with_prs_config(tmp_path)
    monkeypatch.setattr(
        "genomeclaw_toolkit.service.pgs_compute_orchestrator.compute_prs_with_coverage_fill",
        fake_compute_prs_with_coverage_fill,
    )

    app = create_app(derived_root=derived_root)
    with TestClient(app) as client:
        resp = client.post("/v1/pgs/compute", json={
            "pgs_id": "PGS000123",
            "trait_label": "test",
            "rationale": "canonical AMD PRS; smoker-relevant",
            "requested_for_question": "do I have AMD risk?",
        })
        task_id = resp.json()["task_id"]
        final = await _wait_for_terminal(client, task_id)

    assert final["status"] == "done"
    assert fake_compute_prs_with_coverage_fill.last_call["agent_choice_rationale"] == (
        "canonical AMD PRS; smoker-relevant"
    )
    assert fake_compute_prs_with_coverage_fill.last_call["requested_for_question"] == (
        "do I have AMD risk?"
    )
```

After authoring, run the suite — all 13 tests should fail for the right reason (no `_real_compute_fn`; no config loader; the worker still uses Phase 3's no-op).

### Step 4.2 — GREEN: Minimal implementation

**File `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_config.py`** (CREATE):

```python
@dataclass(frozen=True)
class PrsComputeConfig:
    sample_id: str
    cram_path: Path
    reference_root: Path
    scorefile_root: Path
    work_dir_root: Path
    panel_version: str
    sites_tsv: Path
    alleles_tsv: Path
    fasta: Path

class PrsComputeConfigMissingError(FileNotFoundError): ...
class PrsComputeConfigMalformedError(ValueError): ...

def load_prs_compute_config(run_dir: Path) -> PrsComputeConfig:
    """Read run_dir/prs_compute_config.json + return a typed config.

    Raises PrsComputeConfigMissingError / PrsComputeConfigMalformedError
    with messages that name the canonical path + missing field so the
    operator can fix the sidecar without spelunking the source.
    """
    ...
```

**File `pgs_compute_orchestrator.py`** (MODIFY — extend Phase 3's surface):

```python
async def _real_compute_fn(
    task: PgsComputeTaskFullRow,
    *,
    config: PrsComputeConfig,
    run_dir: Path,
) -> None:
    """Real compute path: Tier1+Tier2+merge+pgsc_calc → stamp pgs_scores+findings."""
    scorefile_path = config.scorefile_root / f"{task.pgs_id}.txt.gz"
    if not scorefile_path.exists():
        raise PgsScorefileMissingError(task.pgs_id)

    loop = asyncio.get_running_loop()
    pgs_row = await loop.run_in_executor(
        None,  # default ThreadPoolExecutor
        lambda: compute_prs_with_coverage_fill(
            sample_id=config.sample_id,
            cram_path=config.cram_path,
            sites_tsv=config.sites_tsv,
            alleles_tsv=config.alleles_tsv,
            scorefile_path=scorefile_path,
            fasta=config.fasta,
            panel_version=config.panel_version,
            reference_root=as_sibling_mountable(config.reference_root),
            output_root=run_dir,
            work_dir=as_sibling_mountable(config.work_dir_root),
            agent_choice_rationale=task.rationale,
            requested_for_question=task.requested_for_question,
            trait_label=task.trait_label,
        ),
    )

    if _is_degenerate(pgs_row):
        raise DegenerateResultError(f"zero_overlap:pgs_variant_count={pgs_row.pgs_variant_count}")

    _stamp_pgs_row(run_dir, pgs_row, vcf=_canonical_input_vcf(run_dir))


def _is_degenerate(row: PgsRow) -> bool:
    """INV-R002 guard: refuse to cache a degenerate PRS result."""
    if row.pgs_variant_count is not None and row.pgs_variant_count == 0:
        return True
    if row.score is None:
        return True
    return False


def _structured_error(exc: Exception) -> str:
    """Map known compute exceptions to a `failed:<class>:<short>` shape."""
    if isinstance(exc, PgsScorefileMissingError):
        return f"scorefile_missing:{exc.pgs_id}"
    if isinstance(exc, subprocess.CalledProcessError):
        return f"pgsc_calc_failed:rc={exc.returncode}"
    if isinstance(exc, DooDPathError):
        return f"dood_path_error:{exc.offending_path}"
    if isinstance(exc, PRSDeclineError):
        return f"prs_decline:{exc.structural_reason}"
    if isinstance(exc, DegenerateResultError):
        return f"degenerate_result:{exc.detail}"
    return f"worker_unexpected_error:{type(exc).__name__}"
```

Update the loop's exception handler (from Phase 3):

```python
try:
    await compute_fn(claimed)
    _mark_done(db_path, claimed.task_id)
except asyncio.CancelledError:
    raise
except Exception as exc:
    _mark_failed(db_path, claimed.task_id, _structured_error(exc))
    _LOG.exception("PGS compute worker failed task %s", claimed.task_id)
```

**Update `app.py` lifespan hook** to swap the no-op for `_real_compute_fn`:

```python
config = load_prs_compute_config(cache.active.run_dir)  # raises with clear msg
worker_task = asyncio.create_task(
    pgs_compute_worker_loop(
        db_path,
        compute_enabled_fn=lambda: _resolve_compute_enabled(cache),
        compute_fn=functools.partial(
            _real_compute_fn, config=config, run_dir=cache.active.run_dir
        ),
    ),
    name="pgs_compute_worker",
)
```

If `load_prs_compute_config` raises, log a clear WARNING + skip spawning the worker (don't crash the whole host service — the read routes still work; only compute is offline). A new health-response surface (e.g. `compute_status: "unconfigured"`) is a nice-to-have but not strictly required for Phase 4.

### Step 4.3 — REFACTOR

- Extract `_structured_error` into a small registry (a dict mapping exception class → builder lambda) if more error types accumulate. Three is the rule-of-three threshold; Phase 4 already has 5.
- If `_real_compute_fn` grows past ~30 lines, extract the scorefile-resolution step into `_resolve_scorefile_path(config, pgs_id) -> Path`.
- Tighten `compute_fn` signature: `Callable[[PgsComputeTaskFullRow], Awaitable[None]]` is the public callable shape; `_real_compute_fn`'s extra `config` + `run_dir` args are bound via `functools.partial` at the call site.
- Add a one-line comment on the `loop.run_in_executor(None, ...)` — *why* the default executor is fine here (single in-flight task; ThreadPool's default size matters less than the asyncio.Lock the worker already holds).

---

## Implementation Details

### `prs_compute_config.json` sidecar — canonical shape

```json
{
  "sample_id": "MPNRGLQ2K",
  "cram_path": "/Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram",
  "reference_root": "/Volumes/Genome_Work/genomeclaw/reference",
  "scorefile_root": "/Volumes/Genome_Work/genomeclaw/reference/pgs_scorefile",
  "work_dir_root": "/Volumes/Genome_Work/genomeclaw/_scratch/pgs-work",
  "panel_version": "v1",
  "sites_tsv": "/Volumes/Genome_Work/genomeclaw/reference/coverage/v1/sites.tsv",
  "alleles_tsv": "/Volumes/Genome_Work/genomeclaw/reference/coverage/v1/alleles.tsv",
  "fasta": "/Volumes/Genome_Work/genomeclaw/reference/grch38/genome.fa"
}
```

The paths are host-form (absolute under `/Volumes/Genome_Work/...` for the canonical deployment), so `as_sibling_mountable(...)` is the INV-D006 protection — it ensures pgsc_calc's DooD sibling-container path resolution works (the from-scratch-setup-protections cascade hardened this).

The config is **per-deployment**, not per-run. A single sidecar lives in the active run-dir + the host service reads it at startup. If the run-dir rotates (CURRENT symlink flips), the host service rotates with it via the existing SIGHUP / cache-reload path — but Phase 4 doesn't add a hot-reload of the config; a SIGHUP that flips to a run-dir without a sidecar simply logs + skips the worker spawn until the operator stages one.

### Compute integration — call shape

The worker invokes `compute_prs_with_coverage_fill(...)` with these key arguments threaded through:

- `agent_choice_rationale=task.rationale` (INV-A003)
- `requested_for_question=task.requested_for_question` (INV-A003)
- `output_root=run_dir` (per-run derived store; pgs_scores lives under `run_dir/`)
- `work_dir=as_sibling_mountable(config.work_dir_root)` (DooD-safe sibling-mountable work-dir)
- `reference_root=as_sibling_mountable(config.reference_root)` (DooD-safe)

The `loop.run_in_executor(None, lambda: ...)` runs the blocking call in the default ThreadPoolExecutor. Concurrency cap = 1 (held via the module-level `asyncio.Lock` from Phase 3) means at most one compute is in flight, so the default ThreadPool's size doesn't matter for correctness.

### Schema / Provenance Impact

- `pgs_scores` rows now appear via the worker path. The `_stamp_pgs_row(...)` call uses the same shape `prs-compute --run-dir` CLI produces, so existing post-v23 provenance contracts hold.
- `findings` rows of `kind='clinical-non-actionable'` (canonical PRS finding shape) are stamped alongside.
- Provenance: `source_path` = the canonical input VCF (resolved from the run-dir's manifest); `source_sha256` resolved from the manifest where available, NULL otherwise (matches CLI-path semantics).

### Edge Cases to Handle

- **Scorefile missing**: `_resolve_scorefile_path(config, pgs_id)` checks `scorefile_root/<pgs_id>.txt.gz` — if absent, raises `PgsScorefileMissingError`. The worker maps to `failed:scorefile_missing:<pgs_id>`. The agent's `_get_task` polling surfaces the error; the agent's reply tells the user to run `genomeclaw refs fetch --source pgs_scorefile --pgs-id <pgs_id>`.
- **Degenerate result (INV-R002)**: `pgs_variant_count==0` OR `score is None` → no `pgs_scores` row stamped; task is `failed:degenerate_result:<detail>`.
- **DooD path error**: bubbles up from `compute_prs_with_coverage_fill`'s `as_sibling_mountable(...)` boundary check; mapped to `failed:dood_path_error:<offending_path>`. Indicates a misconfigured `prs_compute_config.json` or a missing `GENOMECLAW_HOST_ROOTS` env — recoverable by operator.
- **PRS decline (INV-C001 v1.7)**: calibration decline raises `PRSDeclineError(structural_reason, reason1, reason2)`; task is `failed:prs_decline:<structural_reason>`. The agent's reply incorporates the two named reasons.
- **pgsc_calc failure**: `subprocess.CalledProcessError(rc=N)` → `failed:pgsc_calc_failed:rc=N`. Distinct from `dood_path_error` (which fires before any subprocess) + `degenerate_result` (which fires on a successful run with empty output).
- **Unknown exception**: `worker_unexpected_error:<ExceptionClass>` (Phase 3's fallback, preserved).

### Error Handling

| Error class | Failure mode | Task `error` column shape | Agent's `error_hint` (surfaced via `/v1/pgs/compute/{task_id}`) |
|-------------|--------------|---------------------------|------------------------------------------------------------------|
| `PgsScorefileMissingError` | Scorefile not pre-staged | `scorefile_missing:PGS<id>` | `genomeclaw refs fetch --source pgs_scorefile --pgs-id PGS<id>` |
| `subprocess.CalledProcessError` | pgsc_calc rc≠0 | `pgsc_calc_failed:rc=N` | "pgsc_calc reported a runtime error; see operator logs" |
| `DooDPathError` | Misconfigured paths | `dood_path_error:<path>` | "operator: check `GENOMECLAW_HOST_ROOTS` + `prs_compute_config.json`" |
| `PRSDeclineError` | INV-C001 v1.7 decline | `prs_decline:<structural_reason>` | The two named reasons surfaced to the user |
| `DegenerateResultError` | INV-R002 zero-overlap | `degenerate_result:zero_overlap:...` | "no overlap between sample variants + scorefile sites" |
| `Exception` (anything else) | Unmapped | `worker_unexpected_error:<class>` | "operator: see logs" |

### Privacy / Egress Notes

- The worker performs **zero network I/O**. Tier 1 force-genotype + Tier 2 force-genotype + merge + pgsc_calc are all local subprocesses against local references. PGS Catalog scorefile fetch happens at `genomeclaw refs fetch` time (operator-initiated, opt-in, separately gated), not at compute time.
- The `scorefile_missing` failure mode is the privacy-preserving boundary: the worker doesn't silently fetch on the user's behalf — it fails the task + tells the operator to fetch explicitly.
- INV-P001 test (`test_invP001_worker_makes_no_outbound_calls` from Phase 3) is re-run in Phase 4's regression sweep with the real compute_fn stubbed to a known-good local-only response.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_config.py` | CREATE | `PrsComputeConfig` dataclass + `load_prs_compute_config` + the two error classes |
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | MODIFY | Add `_real_compute_fn`, `_is_degenerate`, `_structured_error`, error classes (`PgsScorefileMissingError`, `DegenerateResultError`) |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Lifespan hook reads sidecar + binds `_real_compute_fn` via `functools.partial` |
| `packages/toolkit/tests/integration/test_pgs_compute_worker_integration.py` | CREATE | Tests 1–9 (compute integration + error mapping + INV-A003 / R001 / R002) |
| `packages/toolkit/tests/integration/test_pgs_compute_config_loader.py` | CREATE | Tests 10–13 (config sidecar contract) |

No plugin / sandbox changes.

---

## Verification

```bash
cd packages/toolkit

# Phase 4's new test files
uv run pytest \
  tests/integration/test_pgs_compute_worker_integration.py \
  tests/integration/test_pgs_compute_config_loader.py \
  -v
# Expect: 13/13 PASS

# Regression: Phase 3's tests stay green
uv run pytest tests/integration/test_pgs_compute_worker_skeleton.py -v
# Expect: 8/8 PASS

# Provenance test (INV-R001)
uv run pytest tests/provenance/ -v -k pgs_scores
# Expect: existing CLI-path provenance tests still pass; the worker writes
# the same row shape so no new test file needed under tests/provenance/
# (the INV-R001 assertion is in test_pgs_compute_worker_integration.py).

# Full sweep
uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: no regression.

# Type-check
uv run mypy \
  src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py \
  src/genomeclaw_toolkit/service/pgs_compute_config.py \
  src/genomeclaw_toolkit/service/app.py

# Lint
uv run ruff check \
  src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py \
  src/genomeclaw_toolkit/service/pgs_compute_config.py \
  src/genomeclaw_toolkit/service/app.py \
  tests/integration/test_pgs_compute_worker_integration.py \
  tests/integration/test_pgs_compute_config_loader.py
```

---

## Completion Criteria

- [ ] All 13 listed test cases pass.
- [ ] `test_worker_invokes_real_compute_with_threaded_provenance` cites INV-A003 in name or docstring.
- [ ] `test_invR001_worker_stamps_seven_provenance_columns` cites INV-R001.
- [ ] `test_invR002_degenerate_result_does_not_stamp` cites INV-R002.
- [ ] Phase 3's 8 tests stay green (no regression from the integration).
- [ ] Provenance: worker-written `pgs_scores` rows carry the same seven INV-R001 columns the CLI path produces (verified by tests #2 + the existing provenance test suite).
- [ ] mypy + ruff clean on touched files.
- [ ] Full toolkit suite green.
- [ ] `work-notes.md` updated with: RED output, the design choice of `prs_compute_config.json` sidecar vs env-var vs API-config, the choice of `loop.run_in_executor(None, ...)` vs a dedicated process pool, and the error-mapping table.
- [ ] Phase status updated in `development-plan.md`.

## Next

[Phase 5 — Crash recovery + observability](phase-5.md).
