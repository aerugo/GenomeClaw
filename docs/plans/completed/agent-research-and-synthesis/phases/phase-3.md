# Phase 3: Live verification sweep

**Status**: In progress (slice 1: Story-9 live snapshot on real derived store)
**Started**: 2026-05-15
**Completed**:
**Parent Plan**: [../development-plan.md](../development-plan.md)
**Spec**: [../spec.md](../spec.md) (AC1, AC2, AC8b, AC10; partial AC3 + AC4)

---

## Objective

Pin the **behavioural** contract of the research-and-synthesis protocol against gpt-5.5 in the rebuilt sandbox image. Phase 2 + 2b shipped the static contracts (prompt content gates, baked-config gates, validator); Phase 3 verifies the *agent actually executes the protocol correctly* on real research questions over a real (synthetic) derived store.

Live snapshot tests live behind a new `live_llm` pytest marker, gated on `OPENAI_API_KEY` + `GENOMECLAW_SANDBOX_IMAGE`. They are **structural** snapshots (tool-call presence, citation shape, no HTTP 500 from genomeclaw tools), not byte-exact (LLM output varies). Cost-sensitive: each test fires one real OpenAI call.

Phase 3 is scoped wide; slice 1 ships **only** the Story-9 caffeine snapshot + the test infrastructure (live_llm marker, synthetic-store stager, bootstrap-bypass injection). Stories 4 + 10 + validation-driven supersession + the gateway-scope investigation land as separate slices once slice 1 sets the pattern.

## Scope Boundaries

### Slice 1 — Story 9 caffeine live snapshot (this slice)

- **In scope**:
  - Add `live_llm` pytest marker + conftest auto-skip when `OPENAI_API_KEY` absent.
  - Build a `_stage_run_with_findings_for_smoke()` helper that materialises a Story-9 CYP1A2 finding (rs762551 slow-metabolizer) into a derived store on the host. Reuse the `_FIXTURE_FINDINGS` pattern from [test_service_findings.py](../../../../packages/toolkit/tests/integration/test_service_findings.py); adapt to a temp directory the smoke fixture can serve.
  - Build a `_run_agent_in_sandbox(message, *, derived_root, openai_api_key)` helper that:
    1. Starts the host service against the staged `derived_root` as a background process.
    2. Pre-stages `IDENTITY.md` + `USER.md` into a tmp dir bind-mounted into the sandbox at `/sandbox/.openclaw/workspace/` so the pi-harness bootstrap doesn't intercept the first turn (the bypass pattern from the Phase 2b live smoke).
    3. Invokes `docker run` against `genomeclaw/sandbox:ars-phase-2b` with `--add-host=host.openshell.internal:host-gateway -e OPENAI_API_KEY` and pipes a shell script that configures the OpenAI provider + `agents.defaults.thinkingDefault: max`, starts the gateway, runs `openclaw agent --agent genomeclaw --message <msg> --json --timeout 240`, and emits the raw JSON to a host-mounted volume.
    4. Tears down the host-service process + returns the parsed JSON.
  - Write `tests/integration/test_live_story9_caffeine_snapshot.py` with one test `test_invA001_invA002_story9_caffeine_live`:
    - **Pre-conditions**: `OPENAI_API_KEY` env var, sandbox image built, host service is host-runnable.
    - **Action**: stage CYP1A2 finding, send Story-9 question, capture JSON trace.
    - **Structural assertions**:
      - HTTP rc == 0 from `openclaw agent`.
      - `result.payloads[0].text` non-empty (the agent produced a user-facing reply).
      - The reply contains a CYP1A2-related token (`CYP1A2` OR `rs762551` OR `caffeine` — looser than byte-match).
      - The reply cites at least one primary source (URL with `http`, PubMed ID `PMID\s+\d+`, or a `clinvar:`/`pgs_catalog:`/`pharmgkb:` ref).
      - The raw trace blob contains the string `web_search` AT LEAST once (the agent invoked native search per AC8b).
      - **No HTTP 500 markers**: the trace must NOT contain `"status_code":500` or the substring `HTTP 500` (a structural regression check — Phase 2a's smoke saw the staged store's missing findings table cause 500s; Slice 1's bedrock is "real derived store, no 500s").
- **Out of scope** (deferred to later Phase-3 slices):
  - Story 4 PGx (clopidogrel/CYP2C19) live snapshot.
  - Story 10 PRS (CAD) live snapshot.
  - Validation-driven supersession against a pre-staged weak memory note (AC4b).
  - Per-call reasoning-effort probe to pin `INV-A002` to actual model thinking level (the JSON trace at this code path doesn't echo it).
  - Investigation of OpenClaw gateway `pairing required: scope upgrade pending approval` → embedded fallback.
  - Pi-harness BOOTSTRAP.md **structural** fix (slice 1 uses the bypass-by-pre-staging workaround; structural fix is its own slice).
  - Pinning a managed `web_search` provider (Brave/Tavily). Slice 1 verifies the native-OpenAI path only.

### Slices 2+ (future)

- Slice 2: Story 4 + Story 10 live snapshots (mostly fixture-stager extensions + one test per story).
- Slice 3: Validation-driven supersession live snapshot (AC4b). Pre-stages a weak memory note; asserts supersession.
- Slice 4: Pi-harness BOOTSTRAP.md structural fix (one of the three remediation options from Phase 2a work-notes).
- Slice 5: INV-A002 per-call reasoning probe + gateway-scope investigation.

## Invariants Enforced in This Phase

- **`INV-A001`** *(behavioural)* — the agent's memory-note write step actually runs in a live turn. Slice 1 checks at least that the agent's trace shows a writer attempt; full validator-correctness depends on whether the `pi` harness's memory backend is the same as the validator expects (TBD investigation in slice 1).
- **`INV-A002`** *(structural floor)* — the agent's configured `thinkingDefault` is `max`. Slice 1 verifies the config-set path persists; per-call probe to confirm the *actual* model reasoning effort used is deferred to slice 5.
- **`INV-P001` v1.7** *(behavioural — native search activation)* — the trace surfaces a `web_search` tool call routed through the agent-provider envelope. AC8b.
- **`INV-E001`** *(behavioural — primary-source surfacing)* — the reply cites at least one primary source. Closes the "agent fabricates a fluent answer with no citation" failure mode at the behavioural layer.

---

## TDD Steps

### Step 3.1 — RED: write the failing test

**Test cases (slice 1)**:

1. `test_invA001_invA002_story9_caffeine_live` — the structural snapshot described in the In-Scope section.

**Fixtures**:
- `staged_run_dir_with_cyp1a2_finding` (function-scoped, returns `Path`) — builds a temp `derived/<run-id>/variants.duckdb` with the Story-9 CYP1A2 finding.
- `workspace_bypass_dir` (function-scoped, returns `Path`) — builds a temp dir with `IDENTITY.md` + `USER.md` for bind-mount into the sandbox.

**Helpers**:
- `_stage_run_with_findings_for_smoke(derived_root: Path, findings: tuple[dict, ...]) -> Path` — like the integration-test helper but parameterised on which findings to stage.
- `_run_agent_in_sandbox(message: str, *, derived_root: Path, workspace_bypass: Path, sandbox_image: str, openai_api_key: str, timeout_s: int = 240) -> dict` — orchestrates the docker-run-with-host-service-up pattern.

**RED**: at this point the test fails because the helpers + marker don't exist yet.

### Step 3.2 — GREEN: implement the marker + helpers + test

1. Add `live_llm` to `[tool.pytest.ini_options].markers` in [packages/toolkit/pyproject.toml](../../../../packages/toolkit/pyproject.toml). Conftest auto-skip when `OPENAI_API_KEY` is unset.
2. Move `_stage_run_with_findings` + `_FIXTURE_FINDINGS` from `test_service_findings.py` into a shared module under `tests/_live_smoke/staging.py` (or similar). Adapt to parameterised findings tuple. Keep the existing integration tests still using their fixture but importing from the shared module.
3. Build `_run_agent_in_sandbox(...)` in `tests/_live_smoke/run.py`. Note: this runs `subprocess.run("docker run ...")` synchronously per call. Each call costs one real OpenAI request.
4. Wire up `test_live_story9_caffeine_snapshot.py` against the helpers; assert structural shape.

### Step 3.3 — Refactor + verify

- Verify `uv run pytest -m live_llm -v` runs the new test and it passes against the project owner's `OPENAI_API_KEY`.
- Verify `uv run pytest` (no marker filter) skips the live test cleanly when `OPENAI_API_KEY` is unset.
- Ruff + format clean on the new files.
- Updated work-notes.md with slice-1 results.

---

## Files

| File | Action | Notes |
|------|--------|-------|
| `packages/toolkit/pyproject.toml` | MODIFY | Add `live_llm` to `[tool.pytest.ini_options].markers`. |
| `packages/toolkit/tests/conftest.py` | MODIFY | Auto-skip `live_llm`-marked tests when `OPENAI_API_KEY` unset. |
| `packages/toolkit/tests/_live_smoke/__init__.py` | CREATE | Empty package marker. |
| `packages/toolkit/tests/_live_smoke/staging.py` | CREATE | Shared synthetic-store stager. |
| `packages/toolkit/tests/_live_smoke/run.py` | CREATE | `_run_agent_in_sandbox(...)` orchestrator. |
| `packages/toolkit/tests/integration/test_live_story9_caffeine_snapshot.py` | CREATE | The first `live_llm` test. |
| `packages/toolkit/tests/integration/test_service_findings.py` | MODIFY (small) | Import `_FIXTURE_FINDINGS` + `_stage_run_with_findings` from the shared module instead of defining inline. Keep the test contract identical. |

---

## Verification

```bash
cd packages/toolkit

# Default (no API key, no sandbox image): live test skips
uv run pytest -q

# With OPENAI_API_KEY + GENOMECLAW_SANDBOX_IMAGE: live test runs
set -a ; source /Users/hugi/GitRepos/GenomeClaw/.env ; set +a
OPENAI_API_KEY="${OPENAI_API_KEY:-$OPEN_AI_API_KEY}" \
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:ars-phase-2b \
  uv run pytest -m live_llm -v
```

---

## Completion Criteria

Slice 1 is complete when:

- [ ] `test_invA001_invA002_story9_caffeine_live` passes against `genomeclaw/sandbox:ars-phase-2b` + a valid `OPENAI_API_KEY`.
- [ ] `uv run pytest -q` on the host venv skips the live test cleanly (no API key + no sandbox image → 0 failures, 1 new skip).
- [ ] No regressions in the 570-test host suite.
- [ ] Ruff + format clean on all new files.
- [ ] `docs/plans/active/agent-research-and-synthesis/work-notes.md` updated with slice-1 results + the full punch list for slices 2-5.

Slices 2-5 are deliberately not gated here — they are listed under "Out of scope" and tracked in work-notes.md as the Phase 3 punch list.
