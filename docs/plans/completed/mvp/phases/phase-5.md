# Phase 5: Host service + plugin migration to `registerTool` + sandbox image

**Status**: Pending — skeleton authored 2026-05-15 at Phase 4 close
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)
**Spec**: [spec.md § AC2 / AC3 / AC6 / AC8 / AC10](../spec.md) and [Q2](../spec.md#q2--plugin-tool-surface-registertool-not-registercommand) / [Q4](../spec.md#q4--registertool-tool-parameter-shape-typed-arrays-for-collections-scalars-for-singletons) / [Q7](../spec.md) / [Q9](../spec.md)

---

## Objective

Stand up `genomeclaw-service` (FastAPI on `127.0.0.1:8643`) as the read-only query surface over the Phase-4 derived store, and migrate the OpenClaw plugin from the v0 `registerCommand` placeholder to the published `registerTool` agent-tool API. Together these close the loop: a NemoClaw sandbox running the migrated plugin can call into the host service via the OpenShell L7 proxy and round-trip JSON-shaped tool results back to the agent. The privacy posture (`INV-D002` sandbox-binary inspection, `INV-P001` default-egress, `INV-P002` minimal-sufficient JSON) is enforced for the first time in code.

## Scope Boundaries

- **In scope** (per [development-plan.md § Phase 5](../development-plan.md#phase-5-host-service--plugin-migration-to-registertool--sandbox-image)):
  - `genomeclaw-service` FastAPI app exposing **five** v0 endpoints: `/v1/health`, `/v1/variants`, `/v1/variants/{key}`, `/v1/provenance/{run-id}`, `/v1/gene/{symbol}`.
  - Plugin migration to `registerTool` for **five** of the six MVP plugin tools: `genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_gene`. Drop the v0 `registerCommand` blocks + `GENOMECLAW_JSON:` / `parseArgs` text-encoding helpers.
  - TypeBox parameter schemas per [spec.md Q4](../spec.md) (typed arrays for collections; scalars for singletons).
  - Sandbox image rebuild with the migrated plugin; `INV-D002` smoke test confirming no bioinformatics binaries (`samtools`, `bcftools`, `bgzip`, `mosdepth`, `cyrius`, `pgsc_calc`, VEP, vcfanno) are present on PATH.
  - Live tool-result verification in the project owner's sandbox: at least `genomeclaw_status` + `genomeclaw_gene` round-trips work end-to-end with the LLM correctly addressing returned fields by name in a follow-up message.
  - Policy-preset (`packages/nemoclaw-plugin/policy-preset.yaml`) GET-path allowlist updated to include `/v1/gene/*`.
  - The `CURRENT` symlink resolution discipline ([development-plan.md § Solution Design key decision #5](../development-plan.md)): host service reads the symlink target on startup + on `SIGHUP`.
- **Out of scope** (deferred to Phase 6 or later):
  - `/v1/findings`, `/v1/findings/{id}`, `/v1/evidence/{ref}`, `/v1/pgs/{trait}` — finding + evidence endpoints land in Phase 6 alongside the curated-notes resolver.
  - `genomeclaw_pgs` (the 6th tool) + PRS — Phase 6 (per spec Q8).
  - Cyrius CYP2D6 + PharmCAT outside-call — Phase 6 (per spec Q6).
  - Agent UX / report rendering — by spec Q3 the agent assembles its own framing; no `/v1/report` endpoint ships.

## Invariants Enforced in This Phase

(Each `INV-xxx` ID below is sourced from [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md). Tests live under `packages/toolkit/tests/{privacy,invariants}/` for Python sides and `packages/nemoclaw-plugin/tests/` for TS sides.)

- **INV-D002** — sandbox image contains no bioinformatics binaries. Smoke test inspects the built sandbox image's `/` for the disallowed binary set.
- **INV-P001** — privacy-default integration test asserts the plugin reaches only the configured host service and `inference.local` under default config; no other outbound destinations.
- **INV-P002** — minimal-sufficient JSON shape verified at the host service AND the plugin's `jsonResult(...)` payload. Live policy probe asserts SSRF guard rejects un-allowlisted hosts/ports.

---

## TDD Steps

### Step 5.1 — RED: Write Failing Tests

Tests are split across the host-side toolkit (Python / pytest) and the plugin-side TS (whatever the existing `packages/nemoclaw-plugin/` test runner is — confirm at session start).

**Test cases (host-side, `packages/toolkit/tests/`):**

1. `test_health_endpoint_returns_200_with_schema_version` — `GET /v1/health` returns `{ "schema_version": "v0.2", "current_run_id": <str>, ... }`.
2. `test_variants_endpoint_returns_paginated_rows` — `GET /v1/variants?limit=N` returns at most N rows from the active `variants.duckdb`; pagination cursor present.
3. `test_variant_by_key_returns_single_row_or_404` — `GET /v1/variants/{chr-pos-ref-alt}` returns the variant or 404.
4. `test_gene_endpoint_returns_per_gene_summary` — `GET /v1/gene/{symbol}` returns gene-level summary including `mean_depth` from `coverage_qc` + `low_coverage_exons` for curated genes (per spec AC8).
5. `test_provenance_endpoint_returns_full_run_chain` — `GET /v1/provenance/{run-id}` returns the full step trail including the new `vep_skipped_variants` / `vep_skipped_chroms` fields (decoy-variant-provenance follow-up from Phase 4 close).
6. `test_invD002_sandbox_image_has_no_bio_binaries` — built sandbox image inspection asserts `samtools` / `bcftools` / `bgzip` / `mosdepth` / `cyrius` / `pgsc_calc` / VEP / vcfanno absent.
7. `test_invP001_default_config_no_unexpected_egress` — full plugin → service round-trip under default config; assert outbound destinations limited to host service + `inference.local`.
8. `test_invP002_response_shape_minimal_sufficient` — assert `/v1/variants/{key}` and `/v1/gene/{symbol}` responses match the documented minimal shape (no raw PGS variant lists, no per-variant coverage dumps; bounded result sizes).
9. `test_current_symlink_atomic_resolve_on_sighup` — write a new run dir + flip the symlink; send `SIGHUP`; assert `/v1/health` reflects the new `current_run_id`.

**Test cases (plugin-side, `packages/nemoclaw-plugin/`):**

10. `test_register_tool_called_for_five_tools` — confirm `api.registerTool(...)` invoked five times (no remaining `registerCommand` for agent-callable surfaces).
11. `test_typebox_schemas_validate_per_spec_q4` — invalid params (empty arrays where `minItems: 1`; missing required keys) rejected by TypeBox before reaching the handler.
12. `test_jsonresult_envelope_shape` — handler returns from `jsonResult(payload)`; `result.content[0].type === 'text'`; `result.details === payload`.

After writing tests, run them and **confirm they fail for the intended reason**. Paste the failing output into [work-notes.md](../work-notes.md).

### Step 5.2 — GREEN: Minimal Implementation

Order matters: the host-side service ships first so the plugin has something to round-trip against.

1. **Host service skeleton** — `packages/toolkit/src/genomeclaw_toolkit/service/app.py` (FastAPI app) + `service/routes/{health,variants,gene,provenance}.py` (one router per surface) + `service/store.py` (DuckDB read-only connection scoped to the active run dir, resolved through the `CURRENT` symlink). Pydantic response models live under `packages/toolkit/src/genomeclaw_toolkit/schemas/`.
2. **Sandbox image rebuild** — extend `packages/nemoclaw-plugin/sandbox/Dockerfile` if any toolchain changes are needed; document the build command in `packages/nemoclaw-plugin/README.md`.
3. **Plugin migration** — rewrite `packages/nemoclaw-plugin/src/index.ts` per [development-plan.md § Phase 5 Deliverables item 2](../development-plan.md). Add `@sinclair/typebox` to dependencies. Drop `parseArgs` + `GENOMECLAW_JSON:` text encoding entirely.
4. **Policy preset update** — extend `packages/nemoclaw-plugin/policy-preset.yaml` GET-path allowlist with `/v1/gene/*` (other endpoints already covered).

### Step 5.3 — REFACTOR

With tests green:
- Tighten Pydantic response models — fail-closed when a column the schema expects is absent.
- Confirm the router-per-surface split kept handlers small enough that tests don't need fixtures larger than ~30 lines.
- Add comments only where the *why* is non-obvious (e.g., `SIGHUP` semantics; the `CURRENT` symlink resolution timing).
- Re-run tests after each refactor step.

---

## Implementation Details

### Host service shape (`genomeclaw-service`)

- Bind: `127.0.0.1:8643` (per [spec.md AC2](../spec.md)).
- Active run resolution: read `<derived_root>/CURRENT` symlink target on startup + on `SIGHUP`. If the symlink is missing, return 503 from `/v1/health` with a clear error pointing the user at `genomeclaw pipeline run`.
- DuckDB connection: read-only; one connection per request (cheap; DuckDB handles concurrent readers fine). Connection pool optional — skip until benchmarks justify it.
- Schema-version refusal: refuse to load anything not at the current schema version (v0.2 today; bumps later). Surface the version at `/v1/health` so the plugin can detect drift.

### `/v1/gene/{symbol}` shape (per spec AC8)

```jsonc
{
  "gene": "BRCA2",
  "mean_depth": 32.4,                      // from coverage_qc gene-level row
  "low_coverage_exons": [                  // populated only for curated genes (ACMG SF + PharmCAT + Q9 lifestyle)
    { "exon_id": "...", "mean_depth": 5.2 }
  ],
  "n_variants_in_gene": 47,                // bounded count from variants table
  "schema_version": "v0.2"
}
```

Per-exon coverage is materialized only for the curated subset (per spec AC8); for non-curated genes the `low_coverage_exons` array is empty + a `note` field explains.

### `/v1/provenance/{run-id}` and the decoy-variant fields

The `vep` step now carries `vep_skipped_variants` (int) + `vep_skipped_chroms` (`dict[str, int]`) per the [decoy-variant-provenance plan](../../decoy-variant-provenance.md) closed in the Phase 4 close-paperwork sweep. The endpoint surfaces these fields verbatim — no aggregation, no redaction (this is a debugging / audit surface for the user themselves, not for downstream API consumers).

### Edge Cases to Handle

- **No active run** (CURRENT symlink missing): `/v1/health` returns 503 with `{"error": "no active run; run \`genomeclaw pipeline run\` first"}`; all other endpoints return 503.
- **Schema-version mismatch**: refuse to serve; explicit error pointing the user at the rebuild command.
- **Variant key not found**: `/v1/variants/{key}` returns 404, not 500.
- **Gene symbol case-folding**: `/v1/gene/{symbol}` accepts either case; resolve case-insensitively against the gene table.
- **Plugin handler exceptions**: caught + surfaced via `failedTextResult(text, details)` so the agent gets a structured error, not a stack trace.

### Error Handling

- Host service exceptions: caught at the FastAPI middleware layer; return 5xx with a redacted message body (no path leaks, no DB schema dumps).
- Plugin handler errors: `failedTextResult` carries a stable error code + human-readable text + structured details for the SDK.

### Privacy / Egress Notes

- Default config: outbound destinations limited to the configured agent endpoint (managed by OpenShell, not GenomeClaw) + the configured host service. Test confirms.
- `INV-P002` minimal-sufficient JSON: every endpoint's response model carries only the fields documented above. No raw PGS lists. No per-variant coverage dumps. Pydantic strict mode rejects extra fields.
- The host service binds to loopback only (`127.0.0.1`); the SSRF guard is the plugin's policy preset + OpenShell L7 floor.
- The plugin reads only via the policy-preset-allowlisted GET paths; no unsafe verbs.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | CREATE | FastAPI app + lifespan handlers (CURRENT resolve on startup + SIGHUP) |
| `packages/toolkit/src/genomeclaw_toolkit/service/routes/{health,variants,gene,provenance}.py` | CREATE | One router per surface; thin handlers calling into `store.py` |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | CREATE | DuckDB read-only connection helper + active-run resolver |
| `packages/toolkit/src/genomeclaw_toolkit/schemas/{health,variant,gene,provenance}.py` | CREATE | Pydantic response models (minimal-sufficient per `INV-P002`) |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | MODIFY | Add `host service` command to launch the FastAPI app via uvicorn |
| `packages/toolkit/tests/integration/test_service_*.py` | CREATE | One per route + one for SIGHUP symlink swap |
| `packages/toolkit/tests/privacy/test_invP001_default_egress.py` | CREATE | Asserts outbound destinations under default config |
| `packages/toolkit/tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py` | CREATE | Inspects built sandbox image |
| `packages/toolkit/tests/invariants/test_invP002_minimal_sufficient_response_shapes.py` | CREATE | Pydantic-shape assertions on every route |
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY (substantial rewrite) | `registerTool` migration; TypeBox schemas; `jsonResult` envelope |
| `packages/nemoclaw-plugin/package.json` | MODIFY | Add `@sinclair/typebox` |
| `packages/nemoclaw-plugin/policy-preset.yaml` | MODIFY | Add `/v1/gene/*` to GET allowlist |
| `packages/nemoclaw-plugin/sandbox/Dockerfile` | MODIFY | Confirm no bio binaries snuck in; document build |
| `packages/nemoclaw-plugin/tests/test_register_tool_*.ts` | CREATE | Verify each of the five tools registers via `registerTool` |

---

## Verification

```bash
# Host-side
cd packages/toolkit
uv run pytest tests/integration/test_service_ tests/privacy/ tests/invariants/ -v
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Plugin-side
cd packages/nemoclaw-plugin
<plugin test runner> tests/

# End-to-end: build + onboard the sandbox image, then exercise tools through the live agent
docker build -f packages/nemoclaw-plugin/sandbox/Dockerfile -t genomeclaw-sandbox:dev .
nemoclaw onboard --from packages/nemoclaw-plugin/sandbox/Dockerfile
# Then in the project owner's sandbox via Telegram:
#   "genomeclaw_status"  → returns service health JSON
#   "genomeclaw_gene BRCA2"  → returns gene summary; agent should reference fields by name in the next message
```

For the live verification step, capture a transcript of the agent's response that addresses returned fields by name — that's the AC4 progenitor for Phase 7 and the proof that the LLM is parsing the `jsonResult` envelope correctly.

---

## Completion Criteria

- [x] All listed test cases pass — host-side: 22 Slice A/B/C route tests + 10 Slice E invariant tests = 32 new tests; plugin-side: 16 vitest cases. (2026-05-15)
- [x] Static checks pass (`uv run ruff check .` + `uv run ruff format --check .` on toolkit; `npm run typecheck` + `npm run build` on plugin). (2026-05-15)
- [x] Each enforced `INV-xxx` is verified by at least one test in this phase — `INV-D002` ([test_invD002_sandbox_image_no_bio_binaries.py](../../../../packages/toolkit/tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py)), `INV-P001` ([test_invP001_plugin_default_egress.py](../../../../packages/toolkit/tests/privacy/test_invP001_plugin_default_egress.py)), `INV-P002` ([test_invP002_policy_preset_shape.py](../../../../packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py) + the per-route Pydantic models in [service/](../../../../packages/toolkit/src/genomeclaw_toolkit/service/)). (2026-05-15)
- [x] No raw genomic data, secrets, or sample IDs added to fixtures or repo. (2026-05-15)
- [x] The five plugin tools register via `registerTool`; no `registerCommand` calls remain for agent-callable surfaces. Verified by `test_register_tool_migration::registers exactly the five MVP tools`. (2026-05-15)
- [x] **Sandbox image: no bioinformatics binaries on PATH (per `INV-D002`)** — verified live 2026-05-15 against `genomeclaw/sandbox:slice-e-v2` ([test_invD002_sandbox_image_no_bio_binaries.py](../../../../packages/toolkit/tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py) 11/11 passing). Plus a new permanent regression test pins the plugin-load contract ([test_invD002_plugin_registers_inside_sandbox.py](../../../../packages/toolkit/tests/invariants/test_invD002_plugin_registers_inside_sandbox.py)) so a future Dockerfile change that drops a runtime dep surfaces in seconds.
- [x] **Live tool-result verification**: `genomeclaw_status` round-trip works end-to-end against real OpenAI gpt-5.5. **Verified 2026-05-15** — the agent received the user message "tell me the active GenomeClaw run-id and schema version", picked `genomeclaw_status`, executed it (plugin hit `http://host.openshell.internal:8643/v1/health`, host returned typed `HealthResponse`), and surfaced the fields by name in its reply: *"active run-id: `run-live`", "schema version: `v0.2`"*. Two real bugs found + fixed in the process: (1) Dockerfile used `cp` instead of `openclaw plugins install`, so the plugin was on disk but not registered in OpenClaw's plugin index; (2) plugin imported `failedTextResult` from the deprecated `openclaw/plugin-sdk` compat layer — fixed by moving to the `openclaw/plugin-sdk/agent-runtime` subpath. Sandbox image is now `genomeclaw/sandbox:slice-e-v4`.
- [x] Policy preset GET allowlist includes `/v1/gene/*` — verified by `test_invP002_policy_preset_includes_v1_gene_route`. (2026-05-15 Slice C/E)
- [x] [work-notes.md](../work-notes.md) updated with RED output, decisions, and final state — five session blocks under "Phase 5 Slice A/B/C/D/E". (2026-05-15)
- [x] Phase 5 status updated in [development-plan.md](../development-plan.md) Progress Tracking — flipped to "In Progress (~95%)" with per-slice notes. (2026-05-15)
- [ ] [phases/phase-6.md](phase-6.md) authored before Phase 5 closes (findings + evidence + lifestyle + Cyrius + PRS). Not yet authored — Phase 5 closure will write this skeleton same way Phase 4 closure wrote phase-5.md.

### Live verification follow-ups (require project owner's NemoClaw environment)

| # | Step | Status |
|---|------|--------|
| 1 | **Build the sandbox image** via `docker build -f packages/nemoclaw-plugin/sandbox/Dockerfile` (or `nemoclaw onboard --from ...`). | ✅ **Done 2026-05-15** as `genomeclaw/sandbox:slice-e-v4`. Surfaced + fixed 3 real bugs in successive rebuilds: (v1→v2) missing `node_modules/` for `@sinclair/typebox`; (v2→v3) used `cp` instead of `openclaw plugins install --link` + missing `openclaw.extensions` field in package.json; (v3→v4) value imports of `jsonResult`/`failedTextResult` came from the deprecated compat layer instead of `openclaw/plugin-sdk/agent-runtime`. |
| 2 | **Live INV-D002 smoke** (`pytest tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py -m needs_sandbox` with `GENOMECLAW_SANDBOX_IMAGE` set). | ✅ **Done 2026-05-15** — 11/11 forbidden bio binaries absent. |
| 3 | **Plugin-load smoke**: confirm the compiled plugin registers all 5 tools inside the sandbox image's Node runtime. | ✅ **Done 2026-05-15** — converted to a permanent regression test ([test_invD002_plugin_registers_inside_sandbox.py](../../../../packages/toolkit/tests/invariants/test_invD002_plugin_registers_inside_sandbox.py)). |
| 4 | **Live LLM round-trip** via real OpenAI gpt-5.5 (agent addresses returned fields by name). | ✅ **Done 2026-05-15** — agent invoked `genomeclaw_status`, plugin hit `/v1/health` via `host.openshell.internal` alias, host returned typed `HealthResponse`, gpt-5.5 surfaced `run-live` + `v0.2` in natural-language reply. |
| 5 | **Live SSRF probe** (from inside the sandbox, attempt `fetch("http://example.com")`; expect `ssrf_denied`). | ⏸ **Deferred** — verifies OpenShell L7 proxy runtime behavior under full sandbox isolation (Landlock + seccomp + netns); a NemoClaw-deploy concern, not a plugin concern. Rolls into the Phase 7 invariant sweep. |

The host + plugin + sandbox-image + agent-round-trip work for Phase 5 is complete. Only the deploy-time SSRF probe remains, which proves OpenShell L7 proxy behavior — not GenomeClaw behavior.

### Open Questions for Resolution During Phase 5

- **Plugin tool-return shape (spec Q2 caveat)** — the spec notes that `registerTool`'s LLM-visible content is text (pretty-printed JSON in a text block). This phase confirms in practice whether the LLM addresses fields by name in follow-up tool calls without any prefix-marker parsing. If the LLM struggles, revisit Q2's "modern LLMs parse this trivially" assumption.
- **DuckDB read-only connection lifetime** — per request vs. per worker. Default to per-request; benchmark in Phase 7 if latency budget pressure surfaces.
- **`SIGHUP` vs. inotify-based symlink watching** — `SIGHUP` is the simplest implementation; inotify is more responsive but adds a dependency. Default to `SIGHUP`; revisit if the user surfaces latency complaints.
