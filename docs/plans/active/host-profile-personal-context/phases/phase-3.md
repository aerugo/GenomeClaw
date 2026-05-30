# Phase 3: Plugin Tool + Policy Preset + Cross-Language Enum Mirror

**Status**: Pending
**Started**: —
**Completed**: —
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Register the `genomeclaw_host_profile` plugin tool, allow `GET /v1/host/profile` and `GET /v1/host/profile/completeness` in the OpenShell policy preset, and pin the profile's structured enums across the Python ↔ TypeScript boundary so a future enum addition surfaces as a typed cross-language diff (INV-A004 pattern).

## Scope Boundaries

- **In scope**:
  - `packages/nemoclaw-plugin/src/index.ts` — register `genomeclaw_host_profile` with TypeBox params + `safeCall` + `rejectIfPlaceholder` + `output_class: "summary"`.
  - `packages/nemoclaw-plugin/policy-preset.yaml` — add the two GET paths.
  - Cross-language enum-mirror test (INV-A004 pattern adapted from `test_invA004_decline_taxonomy_traverse.py`).
  - Tool description enumerates sections + names the incompleteness-surfacing requirement.
- **Out of scope**:
  - System prompt changes — Phase 4.
  - Live behavioural tests — Phase 4.

## Invariants Enforced in This Phase

- **INV-P002** Agent Egress Is Named, Minimal-Sufficient — policy-preset shape gate + plugin output-shape test; the tool defaults to `output_class: "summary"`.
- **INV-A004** Decline Taxonomy Traverses Every Layer (pattern reuse) — cross-language enum-diff gate for `SexAssignedAtBirth`, `SmokingStatus`, `AlcoholUse`, `ExerciseFrequency`, `ConditionStatus`, `RelationshipClass`, `BloodType`, `AncestryCode`, `GoalTag`.
- **INV-A005** Tool-Failure Narratives Match Trace Evidence — the tool's no-profile response shape is `HTTP 200 + missing: true`, NOT an error envelope; the plugin's `wrapHostResponse` lets it through cleanly.

---

## TDD Steps

### Step 3.1 — RED: Write Failing Tests

**Test cases**:

Plugin (`packages/nemoclaw-plugin/tests/host_profile_tool.test.ts`):

1. `host_profile tool is registered with summary output_class` — assert `tools.find(t => t.name === "genomeclaw_host_profile")?.outputClass === "summary"`.
2. `host_profile tool accepts empty params (full profile)` — TypeBox validation accepts `{}`.
3. `host_profile tool accepts sections array` — TypeBox validation accepts `{ sections: ["medical_history.medications"] }`.
4. `host_profile tool rejects unknown section name` — TypeBox + plugin guard reject `{ sections: ["medical_history.dragons"] }` with a structured error referencing the known-sections list.
5. `host_profile tool rejects placeholder section name` — `rejectIfPlaceholder` fires on `{ sections: ["undefined"] }`.
6. `host_profile tool returns missing-signal envelope on no-profile host` — `safeCall` returns the `{ profile: null, missing: true, init_command: "..." }` body verbatim, NOT as an error envelope.
7. `host_profile tool surfaces host-side 500 as failedTextResult` — `HostProfileCorruptedError` (HTTP 500) becomes a `failedTextResult` envelope per `safeCall` conventions.

Policy preset (`packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py` — extend existing):

8. `test_invP002_policy_preset_allows_host_profile_paths` — `_ALLOWED_V0_PATHS` now includes `("GET", "/v1/host/profile")` and `("GET", "/v1/host/profile/completeness")`; YAML parse confirms.
9. `test_invP002_policy_preset_no_write_paths_added` — preset still has zero write paths outside `/v1/pgs/compute`.

Cross-language (`packages/toolkit/tests/invariants/test_invA004_host_profile_enums_traverse.py`):

10. `test_invA004_host_profile_enums_python_typescript_diff` — parse the TypeBox unions in `index.ts` (grep for the `HostProfileSexUnion`, `HostProfileSmokingStatusUnion`, … blocks) and assert set-equality against the Python `Sex`, `SmokingStatus`, … enum values.

**Sketch**:

```typescript
// host_profile_tool.test.ts
test("host_profile tool returns missing-signal envelope on no-profile host", async () => {
  const mockHostFetch = vi.fn().mockResolvedValue({
    status: 200,
    body: { profile: null, missing: true, init_command: "genomeclaw host profile init" },
  });
  const tool = getRegisteredTool("genomeclaw_host_profile");
  const result = await tool.execute({}, { hostFetch: mockHostFetch });
  expect(result.isError).toBeFalsy();
  expect(result.details.missing).toBe(true);
  expect(result.details.init_command).toBe("genomeclaw host profile init");
});
```

```python
# test_invA004_host_profile_enums_traverse.py
def test_invA004_host_profile_enums_python_typescript_diff():
    """INV-A004 pattern: every Python enum value appears as a Type.Literal in index.ts."""
    py_enums = {
        "SexAssignedAtBirth": {v.value for v in SexAssignedAtBirth},
        "SmokingStatus": {v.value for v in SmokingStatus},
        # ...
    }
    ts_source = (PLUGIN_DIR / "src/index.ts").read_text()
    for enum_name, py_values in py_enums.items():
        ts_values = _parse_typebox_union(ts_source, f"HostProfile{enum_name}Union")
        assert ts_values == py_values, (
            f"INV-A004: {enum_name} values diverge — "
            f"py - ts = {py_values - ts_values}, ts - py = {ts_values - py_values}"
        )
```

**Run RED**. Confirm the tool isn't registered, the policy preset doesn't include the paths, and the enum unions don't exist in `index.ts` yet.

### Step 3.2 — GREEN: Minimal Implementation

**Files affected**:

- `packages/nemoclaw-plugin/src/index.ts`:
  - Add TypeBox unions: `HostProfileSexAssignedAtBirthUnion`, `HostProfileSmokingStatusUnion`, etc. — one `Type.Union([Type.Literal(...), ...])` per Python enum.
  - Add `HostProfileSectionsParam = Type.Optional(Type.Array(Type.String({ minLength: 1, maxLength: 80 })))`.
  - Register tool:

```typescript
api.registerTool({
  name: "genomeclaw_host_profile",
  description:
    "Retrieve the host owner's self-reported personal profile (identity, biometrics, " +
    "lifestyle, medical history, family history, goals). Call this BEFORE any reply " +
    "that interprets the user's genome — see INV-C004. When sections relevant to the " +
    "current question are empty or missing, surface the gap to the user and recommend " +
    "the canonical CLI command in the returned envelope's `init_command` field. " +
    "Pass `sections: ['<dotted.path>', ...]` to fetch a scoped subset (e.g. " +
    "`['medical_history.medications']` for a PGx question). A 200 response with " +
    "`missing: true` is a structured no-profile signal, NOT a tool failure (INV-A005).",
  parameters: HostProfileParams,
  outputClass: "summary",
  execute: async (args, ctx) => {
    if (args.sections) {
      for (const s of args.sections) {
        const rejection = rejectIfPlaceholder(s, "sections", {
          toolName: "genomeclaw_host_profile",
          argName: "sections[]",
          hint: "Pass a dotted section path, e.g. 'medical_history.medications'.",
        });
        if (rejection) return rejection;
      }
    }
    const query = args.sections ? { sections: args.sections.join(",") } : undefined;
    return safeCall(ctx.config, "/v1/host/profile", query);
  },
});
```

- `packages/nemoclaw-plugin/policy-preset.yaml`:
  - Add `{ method: GET, path: "/v1/host/profile" }` and `{ method: GET, path: "/v1/host/profile/completeness" }` to the v0 GenomeClaw block.
- `packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py`:
  - Extend `_ALLOWED_V0_PATHS` with the two new GETs.
- New test file `packages/toolkit/tests/invariants/test_invA004_host_profile_enums_traverse.py`.

### Step 3.3 — REFACTOR

- Confirm tool description text matches the wording in the system prompt's Step 1.5 (Phase 4) — they should reinforce, not contradict. (Phase 4 will update the prompt with quoting this description.)
- Factor TypeBox unions into a single block at the top of `index.ts` next to other shared schemas; do not inline-define per tool.
- Re-run all phase tests after each refactor.

---

## Implementation Details

### Tool parameters (TypeBox)

```typescript
const HostProfileParams = Type.Object(
  {
    sections: Type.Optional(
      Type.Array(Type.String({ minLength: 1, maxLength: 80 }), {
        description:
          "Optional dotted-path section names (e.g. ['medical_history.medications', " +
          "'family_history']). Omit to fetch the full profile.",
      }),
    ),
  },
  { additionalProperties: false },
);
```

### Policy preset block

```yaml
# packages/nemoclaw-plugin/policy-preset.yaml — additions
- endpoint: host.openshell.internal:8645
  methods: [GET]
  paths:
    # ... existing v0 paths ...
    - /v1/host/profile
    - /v1/host/profile/completeness
```

### Edge Cases to Handle

- Tool called with `sections: []` (empty array) → treat as "full profile" (matches `args.sections === undefined`).
- Plugin's `safeCall` receives a 200 + `missing: true` body — must NOT wrap it as an error envelope. Confirm `wrapHostResponse` does not flip on `missing: true`.
- Host service returns 400 (`host_profile_unknown_section`) → plugin surfaces the error verbatim with the known-sections list — gives the agent a recovery surface.

### Error Handling

- Use existing `safeCall` + `wrapHostResponse` envelope. No new error class needed on the plugin side.

### Privacy / Egress Notes

- The tool defaults to `output_class: "summary"`. The host service returns minimal-sufficient payload (no internal IDs, no foreign keys, no schema-internal flags beyond what the response model declares).
- The TypeBox params accept `sections` so the agent can fetch only what's relevant to the current question — aligns with INV-P002 minimal-sufficient.
- The policy preset adds zero write paths.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/nemoclaw-plugin/src/index.ts` | MODIFY | Register `genomeclaw_host_profile`; add TypeBox enum unions. |
| `packages/nemoclaw-plugin/policy-preset.yaml` | MODIFY | Allow the two new GETs. |
| `packages/nemoclaw-plugin/tests/host_profile_tool.test.ts` | CREATE | Plugin tool unit tests (1–7). |
| `packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py` | MODIFY | Extend `_ALLOWED_V0_PATHS` (8, 9). |
| `packages/toolkit/tests/invariants/test_invA004_host_profile_enums_traverse.py` | CREATE | Cross-language enum-diff gate (10). |

---

## Verification

```bash
# Plugin tests
cd packages/nemoclaw-plugin && bun test tests/host_profile_tool.test.ts

# Plugin build
cd packages/nemoclaw-plugin && bun run build

# Invariant tests
uv run --project packages/toolkit pytest \
  packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py \
  packages/toolkit/tests/invariants/test_invA004_host_profile_enums_traverse.py \
  -v

# Live smoke (sandbox-gated, optional at phase boundary)
uv run --project packages/toolkit pytest -m needs_sandbox -k host_profile
```

---

## Completion Criteria

- [ ] All 10 listed test cases pass.
- [ ] Plugin builds clean (`bun run build`).
- [ ] Each enforced `INV-xxx` is verified by at least one test (INV-P002, INV-A004, INV-A005).
- [ ] Tool description text is consistent with the system prompt wording landing in Phase 4.
- [ ] `work-notes.md` updated.
- [ ] Phase 3 status updated in `development-plan.md`.
