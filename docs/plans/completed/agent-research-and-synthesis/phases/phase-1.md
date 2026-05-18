# Phase 1: Configure memory + web_search; drop curated_notes/ from the code

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [../development-plan.md](../development-plan.md)
**Spec**: [../spec.md](../spec.md) (AC8, AC9; sets up AC1–AC7 for Phase 2)

---

## Objective

Land the surgical-cleanup + OpenClaw-configuration phase: drop the `gene_note:` and `topic:` evidence-resolver kinds from the host service (along with their tests + helpers); remove `reference/curated_notes/` references from the codebase + docs; configure `web_search` (off by default per `INV-P001`) + `memory-core` (on by default) in the sandbox image's openclaw.json; update the policy preset to allowlist the chosen web_search provider's host(s) when opt-in. No new agent-prose behaviour ships in this phase — Phase 2 brings the system prompt and the memory schema online.

## Scope Boundaries

- **In scope**:
  - Remove `gene_note` + `topic` from `_SUPPORTED_EVIDENCE_KINDS` in [service/store.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/store.py).
  - Delete `_resolve_gene_note` + `_resolve_topic` helpers.
  - Remove `reference_dir` parameter from `build_app(...)` ([service/app.py](../../../../packages/toolkit/src/genomeclaw_toolkit/service/app.py)) if no other consumer; otherwise keep but unused for evidence resolution.
  - Drop curated-notes test cases from [test_service_evidence.py](../../../../packages/toolkit/tests/integration/test_service_evidence.py).
  - Adjust the `EvidenceKind` Literal in [schemas/evidence.py](../../../../packages/toolkit/src/genomeclaw_toolkit/schemas/evidence.py) — drop `gene_note` + `topic`.
  - Configure OpenClaw `tools.web.search.enabled: false` in the sandbox image's openclaw.json (the default per `INV-P001`).
  - Configure OpenClaw `memory-core` in `plugins.allow` (confirm it loads + `memory_search` / `memory_get` are reachable to the agent).
  - Update the policy preset doc to document the future web_search opt-in path (not enable it).
  - Update [test_invP002_policy_preset_shape.py](../../../../packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py) — `/v1/evidence/*` allowlist stays; no change.
- **Out of scope**:
  - Agent system-prompt authoring (Phase 2).
  - Memory-note schema authoring (Phase 2).
  - Live LLM verification (Phase 3).
  - Authoring 7 curated gene notes (this plan supersedes that work entirely).
  - INVARIANTS.md updates (live in this same session but tracked under the parent plan, not this phase).

## Invariants Enforced in This Phase

- **`INV-P001`** — clarified default. The sandbox image ships with `web_search` disabled. A new host-runnable test reads the sandbox image's openclaw.json and asserts `tools.web.search.enabled == false`.
- **`INV-E001`** — unchanged in spirit. Findings still carry evidence_ref; the resolvable kinds shrink to variant-keyed only.
- **`INV-C001`** — moves to v1.6 in this session (lives in INVARIANTS.md, not this phase doc). Lifestyle findings cite `memory:<id>` or `web:<url>` going forward — but those resolvers are agent-side, not host-side, so no host-service test changes.

---

## TDD Steps

### Step 1.1 — RED: Write the new failing tests

**Test cases (host-runnable, fast)**:

1. `test_evidence_returns_400_for_gene_note_kind` — `GET /v1/evidence/gene_note:CYP1A2` returns 400 (kind dropped from `_SUPPORTED_EVIDENCE_KINDS`), not 404.
2. `test_evidence_returns_400_for_topic_kind` — same for `topic:hard-genes`.
3. `test_supported_evidence_kinds_pinned` — assert `_SUPPORTED_EVIDENCE_KINDS == {"clinvar", "pgs_catalog", "pharmgkb"}` exactly.
4. `test_invP001_sandbox_image_disables_web_search_by_default` — read the openclaw.json baked into the sandbox image at build time; assert `tools.web.search.enabled` is missing OR `false`. Gated on `needs_sandbox`.

**Test cases to delete** (after the RED step runs):

1. `test_evidence_resolves_gene_note_from_curated_dir` (currently passing)
2. `test_evidence_resolves_gene_note_case_insensitively`
3. `test_evidence_resolves_topic_from_curated_dir`
4. `test_evidence_returns_404_for_unknown_gene_note` (covered by the new 400 test, since the kind itself fails before the per-id lookup)

Run the new tests; confirm they fail because the old kinds are still supported.

### Step 1.2 — GREEN: Surgical cleanup

**File-by-file changes**:

- `schemas/evidence.py`: `EvidenceKind = Literal["clinvar", "pgs_catalog", "pharmgkb"]`.
- `service/store.py`:
  - `_SUPPORTED_EVIDENCE_KINDS = frozenset({"clinvar", "pgs_catalog", "pharmgkb"})`.
  - Delete `_resolve_gene_note(...)`.
  - Delete `_resolve_topic(...)`.
  - `resolve_evidence(...)` — remove the `kind == "gene_note"` and `kind == "topic"` branches; the `pgs_catalog` + `pharmgkb` branches stay as stubs (return `None`); the `clinvar` branch is the only real resolver until Slices D + E ship.
  - `resolve_evidence` no longer takes `reference_dir` if it has no remaining use — verify in app.py whether `reference_dir` is still threaded; remove cleanly.
- `service/app.py`:
  - `build_app(...)` — drop the `reference_dir` parameter if unused after the cleanup. Update the docstring.
  - The `/v1/evidence/{ref:path}` route now passes only `run_dir` to `resolve_evidence`.
- `_cli/commands/host.py`:
  - `host service` command — drop `--reference-dir` flag if unused after the cleanup (currently only fed into `build_app`).
- `tests/integration/test_service_evidence.py`:
  - Delete the 4 curated-notes test cases.
  - Add the 3 new tests from Step 1.1.
- `tests/integration/test_service_provenance_and_gene.py` and any other test consuming `build_app(reference_dir=...)`:
  - Update call signatures.

**OpenClaw config changes**:

- Sandbox Dockerfile (`packages/nemoclaw-plugin/sandbox/Dockerfile`): write an additional config-set step that ensures `tools.web.search.enabled: false` is explicit in the baked openclaw.json. Use `openclaw config set tools.web.search.enabled false`.
- (No policy-preset changes in Phase 1 — opt-in egress lands in Phase 2 if the user chooses Brave/OpenAI; the docs note the upgrade path.)

### Step 1.3 — REFACTOR

After tests are green:
- Inspect the `evidence.py` schema's `EvidenceKind` Literal — confirm the 3-kind enum reads cleanly.
- Inspect `service/store.py` — confirm `_resolve_clinvar` is now the only `_resolve_*` helper, and the dispatch table in `resolve_evidence` is 3 branches.
- Update module docstrings to remove curated-notes references.
- Run the full toolkit suite + ruff + format.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/evidence.py` | MODIFY | Shrink `EvidenceKind` to 3 variant-keyed kinds |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY | Drop `_resolve_gene_note` + `_resolve_topic`; shrink `_SUPPORTED_EVIDENCE_KINDS` |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Drop `reference_dir` from `build_app(...)` if no other consumer |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/host.py` | MODIFY | Drop `--reference-dir` flag from `host service` if unused |
| `packages/toolkit/tests/integration/test_service_evidence.py` | MODIFY | Delete 4 curated-notes tests; add 3 new gates |
| `packages/toolkit/tests/integration/test_service_provenance_and_gene.py` | MODIFY (if needed) | Update `build_app` call signatures |
| `packages/toolkit/tests/invariants/test_invP001_sandbox_disables_web_search.py` | CREATE | `needs_sandbox` test reading the baked openclaw.json |
| `packages/nemoclaw-plugin/sandbox/Dockerfile` | MODIFY | Explicit `openclaw config set tools.web.search.enabled false` |

---

## Verification

```bash
# Toolkit suite (host venv)
cd packages/toolkit
uv run pytest -q
uv run ruff check src/ tests/
uv run ruff format --check src/ tests/

# Sandbox image rebuild + INV-P001 default-config gate
docker build -f packages/nemoclaw-plugin/sandbox/Dockerfile -t genomeclaw/sandbox:phase-1 .
GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:phase-1 \
  uv run pytest tests/invariants/test_invP001_sandbox_disables_web_search.py tests/invariants/test_invD002_sandbox_image_no_bio_binaries.py tests/invariants/test_invD002_plugin_registers_inside_sandbox.py -v

# Endpoint smoke: gene_note: + topic: now return 400
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8643/v1/evidence/gene_note:CYP1A2  # expect 400
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8643/v1/evidence/topic:hard-genes   # expect 400
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8643/v1/evidence/clinvar:RCV000031  # expect 200 or 404
```

---

## Completion Criteria

- [ ] `_SUPPORTED_EVIDENCE_KINDS` shrunk to `{clinvar, pgs_catalog, pharmgkb}` and pinned by a test.
- [ ] `_resolve_gene_note` + `_resolve_topic` deleted from `service/store.py`.
- [ ] `build_app(...)` no longer takes `reference_dir` (or the parameter is documented for non-evidence use only).
- [ ] 4 curated-notes test cases removed; 3 new gates added; INV-P001 sandbox-image gate added.
- [ ] Sandbox image rebuilt; INV-P001 + INV-D002 + plugin-load tests pass against the new image.
- [ ] Full toolkit suite passes; ruff + format clean.
- [ ] [work-notes.md](../work-notes.md) updated for this session with RED output + decisions taken.
- [ ] Phase 2 (`phases/phase-2.md`) authored before this phase closes.
