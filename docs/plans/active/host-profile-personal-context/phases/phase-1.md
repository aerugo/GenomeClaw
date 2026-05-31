# Phase 1: Schema + Host-Side Storage + Service Endpoints

**Status**: Complete (privacy-safety-reviewer pass done)
**Started**: 2026-05-31
**Completed**: 2026-05-31
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Land the typed `HostProfile` Pydantic schema, the atomic JSON store + append-only audit log, and the two read-only HTTP endpoints (`GET /v1/host/profile` and `GET /v1/host/profile/completeness`). No CLI, no agent surface, no policy-preset changes in this phase — those land in Phases 2 and 3 once the data shape is pinned.

## Scope Boundaries

- **In scope**:
  - `schemas/host_profile.py` — `HostProfile` model + section sub-models + enums + `migrate_host_profile()` stub.
  - `host_profile/store.py` — `read_profile`, `write_profile_atomic`, `compute_completeness`.
  - `host_profile/audit.py` — field-level diff + append-only newline-delimited JSON log.
  - Two route handlers + Pydantic response models in `service/app.py`.
  - Default-egress privacy test confirming the new endpoint stays local.
- **Out of scope (deferred)**:
  - CLI subcommands — Phase 2.
  - Plugin tool registration — Phase 3.
  - Policy preset changes — Phase 3.
  - System prompt changes — Phase 4.

## Invariants Enforced in This Phase

- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — `test_invD002_host_profile_path_is_host_side`: the resolved profile path is under `<derived_root>/` and never inside any sandbox-image-bound directory.
- **INV-P001** Privacy Is the Default Operating Mode — `test_invP001_host_profile_endpoint_default_no_outbound`: starting the service + hitting both endpoints in default config produces zero outbound calls.
- **INV-R001** (lightweight) — `test_invR001_host_profile_schema_version_literal`: the schema's `schema_version` field is a `Literal["host_profile/1.0"]` and `migrate_host_profile()` accepts a v1.0 dict and returns v1.0 unchanged (proves the migration seam exists from day one).
- **INV-C002** (structural prep) — Pydantic response models use `ConfigDict(extra="forbid")` so the future CLI envelope (Phase 2) can compose them safely.

---

## TDD Steps

### Step 1.1 — RED: Write Failing Tests

**Test cases**:

Schema (`tests/unit/test_host_profile_schema.py`) — 13 cases:

1. `test_host_profile_minimal_valid_payload_parses` — minimal profile (identity-only + meta) parses cleanly.
2. `test_host_profile_rejects_unknown_top_level_field` — `extra="forbid"` rejects e.g. `{"weight_in_pounds": 180}`.
3. `test_host_profile_rejects_unknown_section_field` — section sub-models also reject unknowns.
4. `test_invR001_host_profile_schema_version_literal` — `schema_version` MUST equal `"host_profile/1.0"`; any other string raises `ValidationError`.
5. `test_host_profile_identity_sex_assigned_at_birth_enum` — only the four enum values `{female, male, intersex, prefer_not_to_say}` accepted.
6. `test_host_profile_lifestyle_smoking_status_enum` — only `{never, former, current, prefer_not_to_say}`.
7. `test_host_profile_freetext_max_length_enforced` — `medical_history.conditions[].notes` longer than 2000 chars raises `ValidationError`; `family_history.notes` longer than 4000 chars raises `ValidationError`.
8. `test_host_profile_ancestry_groups_validates_friendly_enum` — `identity.ancestry.groups` accepts the nine friendly values (`european`, `african`, `east_asian`, `south_asian`, `american_indigenous_latino`, `middle_eastern_north_african`, `oceanian`, `mixed_or_unsure`, `prefer_not_to_say`); rejects raw codes like `"EUR"` or garbage like `"viking"`.
9. `test_host_profile_ancestry_group_maps_to_pop1000g` — given `groups: ["european", "east_asian"]`, the schema's `model_validator` derives `population_codes: ["EUR", "EAS"]` automatically; `["prefer_not_to_say"]` derives an empty `population_codes` list.
10. `test_host_profile_ancestry_self_reported_freetext_bound` — `self_reported` longer than 500 chars raises `ValidationError`; `None` is valid.
11. `test_host_profile_family_history_is_freetext_not_list` — passing a list (the old shape) to `family_history` raises `ValidationError`; the only accepted shape is `{ notes: str | None, opted_out: bool }`.
12. `test_host_profile_no_goals_section_at_v1_0` — passing a `goals` key (the considered-and-dropped shape) raises `ValidationError` (`extra="forbid"` catches it; explicit test pins the absence).
13. `test_host_profile_migrate_v1_0_identity` — `migrate_host_profile({"schema_version": "host_profile/1.0", ...})` returns the dict unchanged + valid.

Store (`tests/unit/test_host_profile_store.py`):

14. `test_read_profile_returns_none_when_missing` — fresh `<derived_root>` with no `host_profile.json` returns `None`.
15. `test_write_profile_atomic_writes_to_tmp_then_replaces` — write goes through a `.tmp` then `os.replace`; the canonical file is never partially-written.
16. `test_write_profile_appends_audit_log_entry` — every mutation appends one NDJSON record carrying `timestamp`, `changed_paths`, `freetext_lengths` (no verbatim freetext value).
17. `test_write_profile_family_history_audit_log_records_length_only` — a `family_history.notes` write records `freetext_lengths: {"family_history.notes": <N>}` in the audit log and NEVER the verbatim narrative (privacy floor for `family_member_narrative=True` fields).
18. `test_compute_completeness_marks_empty_section_missing` — for an empty `medical_history.medications`, completeness map records `medical_history.medications: missing`.
19. `test_compute_completeness_marks_partial_when_some_fields_present` — partial completion reports `partial`, not `complete`.
20. `test_invD002_host_profile_path_is_host_side` — resolved path is under `<derived_root>/` and not under `/sandbox/`.

Endpoint (`tests/integration/test_service_host_profile_endpoint.py`):

21. `test_get_host_profile_returns_missing_signal_when_no_file` — fresh `<derived_root>`: `GET /v1/host/profile` returns HTTP 200 with `{"profile": null, "missing": true, "init_command": "genomeclaw host profile init"}`.
22. `test_get_host_profile_returns_full_payload_when_present` — happy path: profile present, full payload returned.
23. `test_get_host_profile_sections_query_filters_payload` — `GET /v1/host/profile?sections=medical_history.medications` returns only the requested section (plus `meta`).
24. `test_get_host_profile_completeness_returns_section_map` — `GET /v1/host/profile/completeness` returns `{"sections": {"identity": "complete", "medical_history.medications": "missing", ...}, "meta": {...}}` without the full payload.
25. `test_invP001_host_profile_endpoint_default_no_outbound` — patched `socket.connect` / outbound HTTP client asserts zero non-local outbound calls during the two endpoint requests.

**Sketch** (illustrative):

```python
# tests/unit/test_host_profile_schema.py
def test_invR001_host_profile_schema_version_literal():
    """INV-R001: schema_version is pinned to a literal so future migrations are mechanical."""
    with pytest.raises(ValidationError):
        HostProfile.model_validate({"schema_version": "host_profile/0.9", "meta": _MINIMAL_META, "identity": _MINIMAL_IDENTITY})
    HostProfile.model_validate({"schema_version": "host_profile/1.0", "meta": _MINIMAL_META, "identity": _MINIMAL_IDENTITY})

# tests/integration/test_service_host_profile_endpoint.py
def test_get_host_profile_returns_missing_signal_when_no_file(tmp_derived_root, service_client):
    """Fresh derived root surfaces the structured missing signal (NOT a 404)."""
    resp = service_client.get("/v1/host/profile")
    assert resp.status_code == 200
    body = resp.json()
    assert body["profile"] is None
    assert body["missing"] is True
    assert body["init_command"] == "genomeclaw host profile init"
```

**Run RED**. Confirm every test fails for the *right* reason (no module to import, no route registered, etc.). Paste the failing output into `work-notes.md`.

### Step 1.2 — GREEN: Minimal Implementation

**Files affected**:

- `packages/toolkit/src/genomeclaw_toolkit/schemas/host_profile.py` — CREATE. Pydantic `HostProfile` with sub-models and enums. `Literal["host_profile/1.0"]` schema version. `migrate_host_profile()` stub.
- `packages/toolkit/src/genomeclaw_toolkit/host_profile/__init__.py` — CREATE.
- `packages/toolkit/src/genomeclaw_toolkit/host_profile/store.py` — CREATE. `read_profile(derived_root)`, `write_profile_atomic(derived_root, profile)`, `compute_completeness(profile_or_none)`.
- `packages/toolkit/src/genomeclaw_toolkit/host_profile/audit.py` — CREATE. `append_audit_record(derived_root, before, after)` with field-level diff + freetext-length placeholders.
- `packages/toolkit/src/genomeclaw_toolkit/service/store.py` — MODIFY. Add `query_host_profile(derived_root, sections=None)` + `query_host_profile_completeness(derived_root)`.
- `packages/toolkit/src/genomeclaw_toolkit/service/app.py` — MODIFY. Register `GET /v1/host/profile` and `GET /v1/host/profile/completeness` with Pydantic response models.
- `packages/toolkit/src/genomeclaw_toolkit/schemas/host_profile.py` — also exports `HostProfileResponse` (wraps `profile: HostProfile | None` + `missing: bool` + `init_command: str`) and `HostProfileCompletenessResponse`.

Minimal implementation only — no CLI, no plugin, no docs changes yet. Keep each function single-purpose.

### Step 1.3 — REFACTOR

With tests green:

- Tighten section-model type annotations; ensure every enum has a docstring with a one-line rationale.
- Extract the completeness rule (per-section "complete" / "partial" / "missing" classification) into one helper used by both `query_host_profile_completeness` and `compute_completeness` so the rule has a single source of truth.
- Add comments only where the *why* is non-obvious:
  - The atomic-write tmp-file pattern's rationale (crash-safety).
  - The audit log's freetext-length-placeholder vs verbatim-value rule (privacy).
- Re-run all phase tests after each refactor step.

---

## Implementation Details

### Schema specifics

- `schema_version: Literal["host_profile/1.0"]`.
- `meta`: `{ created_at: datetime, updated_at: datetime, last_full_review_at: datetime | None, skipped_init_at: datetime | None, source: Literal["self_report"] }`.
- `identity`: `{ display_name: str | None, date_of_birth: date | None, sex_assigned_at_birth: SexAssignedAtBirth, gender_identity: str | None (bounded), ancestry: Ancestry }`.
- `Ancestry`: `{ self_reported: str | None (bounded ≤500 chars, freetext=True), groups: list[AncestryGroup] (friendly multi-select enum), population_codes: list[Pop1000G] (derived from groups at write time; persisted for PRS-calibration consumption) }`.
- `biometrics`: `{ height_cm: float | None, weight_kg: float | None, weight_recorded_at: datetime | None, blood_type: BloodType | None }`.
- `lifestyle`: `{ smoking_status: SmokingStatus, alcohol_use: AlcoholUse, exercise_frequency: ExerciseFrequency, dietary_pattern: str | None (bounded ≤200, freetext=True), sleep_pattern: str | None (bounded ≤200, freetext=True) }`.
- `medical_history`: `{ conditions: list[Condition], medications: list[Medication], allergies: list[Allergy], procedures: list[Procedure] }`.
- `family_history`: `{ notes: str | None (bounded ≤4000, freetext=True, family_member_narrative=True), opted_out: bool = False }`. *(v0 captures family history as a single free-text field; a structured per-relative list was considered and dropped — see development-plan Decision 10.)*
- **No `goals` section in v0.** *(Considered and dropped — see development-plan Decision 11.)*

### Friendly-enum → 1000G mapping

`AncestryGroup` (friendly, user-facing) → `Pop1000G` (consumed by PRS-calibration):

| `AncestryGroup` enum value | One-line description (shown in CLI prompt + tool description) | `Pop1000G` code |
|---|---|---|
| `european` | Most European countries, Iceland, Ashkenazi & North African Jewish, diaspora-European populations | `EUR` |
| `african` | Sub-Saharan African, African-American, Afro-Caribbean | `AFR` |
| `east_asian` | China, Korea, Japan, Mongolia, Vietnam | `EAS` |
| `south_asian` | India, Pakistan, Bangladesh, Sri Lanka, Nepal | `SAS` |
| `american_indigenous_latino` | Mexican, Central + South American Indigenous, Caribbean Latino, US Latino with Indigenous heritage | `AMR` |
| `middle_eastern_north_african` | Arabian Peninsula, Levant, Iran, Turkey, North Africa | `MID` |
| `oceanian` | Pacific Islander, Aboriginal Australian, Papuan | `OCE` |
| `mixed_or_unsure` | Significant ancestry from 3+ groups, or unknown (e.g., adopted with no records) | `ADM` |
| `prefer_not_to_say` | User declines to specify | *(no code persisted)* |

The mapping table is exported as a module-level constant `ANCESTRY_GROUP_TO_POP1000G` and exercised by `test_host_profile_ancestry_group_maps_to_pop1000g`.

### Completeness rule

For each top-level section (and the named sub-sections `medical_history.medications`, `medical_history.allergies`, `family_history.first_degree`):

- `complete` — required fields all present + at least one list element where lists are conventional (e.g. `medical_history.medications` is `complete` only if the user has actively declared *something*, including `"none"` via a sentinel `Medication(name="none_declared")` row).
- `partial` — required fields present but list-sentinel missing OR an obviously-empty subset.
- `missing` — section dict is default/zero.

The rule is deterministic + table-driven; the table lives next to the schema in `schemas/host_profile.py`.

### Endpoint shapes

```text
GET /v1/host/profile
GET /v1/host/profile?sections=medical_history.medications,family_history

Response (profile present):
  HTTP 200
  {
    "cli_output_schema_version": null,   # CLI envelope only added in Phase 2 wrappers
    "profile": { ...HostProfile... },
    "missing": false,
    "completeness": { "identity": "complete", ... },
    "init_command": null
  }

Response (no profile yet):
  HTTP 200
  {
    "profile": null,
    "missing": true,
    "completeness": null,
    "init_command": "genomeclaw host profile init"
  }

GET /v1/host/profile/completeness

Response:
  HTTP 200
  {
    "sections": { "identity": "complete", "biometrics": "partial", "medical_history.medications": "missing", ... },
    "missing": false | true,
    "meta": { "updated_at": "...", "last_full_review_at": null }
  }
```

### Edge Cases to Handle

- Profile file exists but is corrupted JSON → endpoint returns HTTP 500 with a structured `{ "error": "host_profile_corrupted", "detail": "..." }` envelope. The store layer raises a typed `HostProfileCorruptedError`.
- Profile file exists but schema_version is unknown → endpoint returns HTTP 500 with `{ "error": "host_profile_schema_unknown" }`. Future migrations will hook in via `migrate_host_profile()`.
- Sections filter contains an unknown section name → HTTP 400 with `{ "error": "host_profile_unknown_section", "section": "<name>", "known_sections": [...] }`.

### Error Handling

- All errors emit through the existing `service/app.py` exception handlers; new exceptions register through the same pattern as `PgsRouteError`.
- Audit log write failures are logged but do not block the profile write (the canonical file is authoritative; the audit log is best-effort).

### Privacy / Egress Notes

- The endpoint MUST be reachable only on the local interface (FastAPI's default bind, unchanged).
- The endpoint MUST NOT log the profile payload at INFO level by default. A structured log entry of `{ "event": "host_profile_read", "sections_returned": [...] }` is acceptable; the payload itself is not.
- The audit log records field-level diffs with values for structured fields and `<freetext len=N>` placeholders for freetext fields per the schema-level `freetext: True` annotation.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/schemas/host_profile.py` | CREATE | Pydantic schema + enums + completeness table + response models. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/__init__.py` | CREATE | Package init. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/store.py` | CREATE | Atomic read/write of `host_profile.json`. |
| `packages/toolkit/src/genomeclaw_toolkit/host_profile/audit.py` | CREATE | Field-level diff + audit log append. |
| `packages/toolkit/src/genomeclaw_toolkit/service/store.py` | MODIFY | Add `query_host_profile` + `query_host_profile_completeness`. |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Register two new GET routes. |
| `packages/toolkit/tests/unit/test_host_profile_schema.py` | CREATE | Schema validation tests (1–10). |
| `packages/toolkit/tests/unit/test_host_profile_store.py` | CREATE | Store + audit tests (11–16). |
| `packages/toolkit/tests/integration/test_service_host_profile_endpoint.py` | CREATE | Endpoint integration tests (17–20). |
| `packages/toolkit/tests/privacy/test_invP001_host_profile_default_egress.py` | CREATE | Default-egress test (21). |

---

## Verification

```bash
# Phase 1 tests
uv run --project packages/toolkit pytest \
  packages/toolkit/tests/unit/test_host_profile_schema.py \
  packages/toolkit/tests/unit/test_host_profile_store.py \
  packages/toolkit/tests/integration/test_service_host_profile_endpoint.py \
  packages/toolkit/tests/privacy/test_invP001_host_profile_default_egress.py \
  -v

# Full toolkit suite (must still be green)
uv run --project packages/toolkit pytest -q

# Type check
uv run --project packages/toolkit mypy src/genomeclaw_toolkit/schemas/host_profile.py src/genomeclaw_toolkit/host_profile/

# Lint
uv run --project packages/toolkit ruff check src/genomeclaw_toolkit/schemas/host_profile.py src/genomeclaw_toolkit/host_profile/ src/genomeclaw_toolkit/service/app.py
```

For the manual sanity check:

```bash
# Start the host service against a temp derived root and hit the no-profile case
GENOMECLAW_DERIVED_ROOT=/tmp/genomeclaw-phase1-fixture \
  uv run --project packages/toolkit python -m genomeclaw_toolkit.service.run &
curl -sS http://127.0.0.1:8645/v1/host/profile | jq
curl -sS http://127.0.0.1:8645/v1/host/profile/completeness | jq
```

---

## Completion Criteria

- [x] All listed test cases pass (27 — the 25 planned + 2 added: missing-profile completeness, unknown-section 400).
- [x] Static checks pass (`mypy`, `ruff`) on the new modules; pre-existing repo errors unchanged (verified via stash).
- [x] Each enforced `INV-xxx` is verified by at least one test in this phase (INV-D002, INV-P001, INV-R001; INV-C002 via `extra="forbid"` response models).
- [x] `<derived_root>/host_profile.json` is the only canonical location for the profile; no other code path writes the same content.
- [x] `<derived_root>/host_profile.audit.log` exists after one write and records the expected NDJSON shape (length-only free-text).
- [x] No raw genomic data, secrets, or sample IDs added to fixtures or repo.
- [x] `work-notes.md` updated with RED output, decisions, and final state.
- [x] Phase 1 status updated in `development-plan.md`.
- [x] Privacy-safety-reviewer agent pass complete (2026-05-31). Verdict: accept-with-changes; 2 blocking egress leaks (Issues 1, 4) + 1 doc/test gap (Issue 2) fixed; Issues 3/5/6/7 tracked as later-phase follow-ups in work-notes.
