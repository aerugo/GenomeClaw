# Phase 1: VEP Invocation Change and `VepConventions` Dataclass

**Status**: Complete (2026-05-25)
**Phase plan created**: 2026-05-25
**Estimated duration**: 3 days

---

## Invariants enforced in this phase

- **INV-T001**: `VepConventions` frozen dataclass created and verified; `"vep"` moved from `_WARN_TOOLS` to `_STRICT_TOOLS` in the discovery test.
- **INV-R001**: The updated flag list (`--mane`, `--pick_order`) is recorded in `provenance.json` via `build_vep_flags`; no change to the recording mechanism is required. Tests assert the exact flags.
- **INV-D001**: No write path to raw or reference artifacts introduced; `_vep.py` and `annotate_vep.py` are modified only at the flag-construction and conventions layers.

---

## Pre-phase verification requirement

Before writing any test or implementation code, verify two facts against the actual toolkit image:

**A. `--mane` vs `--mane_select` in VEP v114.1**

Run inside the toolkit container:
```
vep --help 2>&1 | grep -B1 -A3 "\-\-mane"
```
Confirm:
- `--mane` is accepted and activates both `MANE_SELECT` and `MANE_PLUS_CLINICAL` CSQ fields.
- `--mane_select` is accepted and activates only `MANE_SELECT`.
- The two flags are not aliases; switching from `--mane_select` to `--mane` does not break any other flag.

Record the relevant `--help` section in `initial_findings.md` (create if needed).

**B. `--pick_order` does not suppress CSQ entries**

Run VEP on a 2-variant synthetic VCF that includes a MANE Plus Clinical gene (e.g., a TCF3 site), with and without `--pick_order`. Confirm:
- The CSQ entry count per record is identical with and without `--pick_order`.
- The `PICK` field value on the winning entry changes, but no entries are removed from the CSQ string.

Record the result in `initial_findings.md`.

These verifications close open questions 1 and 2 from `spec.md` and must be documented before the Phase 1 RED step is marked complete.

---

## Step 1.1 — RED: failing tests

Write the following tests and confirm they fail for the correct reasons (import errors or assertion failures, not syntax errors or missing fixtures).

### File: `packages/toolkit/tests/unit/test_vep_conventions.py` (CREATE)

```
test_vep_conventions_dataclass_exists
    Import genomeclaw_toolkit.prep._vep_conventions.
    Assert VepConventions is a frozen dataclass.
    Expect: ModuleNotFoundError (module does not exist yet).

test_vep_conventions_verified_against_version_is_114_1
    Assert VepConventions().verified_against_version == "114.1".
    Expect: ModuleNotFoundError.

test_vep_conventions_mane_flag_is_mane_not_mane_select
    Assert VepConventions().mane_flag == "--mane".
    Expect: ModuleNotFoundError.

test_vep_conventions_pick_order_flag
    Assert VepConventions().pick_order_flag == "--pick_order".
    Expect: ModuleNotFoundError.

test_vep_conventions_pick_order_value_includes_mane_plus_clinical
    Assert "mane_plus_clinical" in VepConventions().pick_order_value.
    Expect: ModuleNotFoundError.

test_vep_conventions_pick_order_value_starts_with_rank
    Assert VepConventions().pick_order_value.startswith("rank,").
    Expect: ModuleNotFoundError.

test_vep_conventions_mane_select_csq_field
    Assert VepConventions().mane_select_csq_field == "MANE_SELECT".
    Expect: ModuleNotFoundError.

test_vep_conventions_mane_plus_clinical_csq_field
    Assert VepConventions().mane_plus_clinical_csq_field == "MANE_PLUS_CLINICAL".
    Expect: ModuleNotFoundError.

test_vep_conventions_is_frozen
    Instantiate VepConventions(). Attempt to mutate any field. Assert FrozenInstanceError.
    Expect: ModuleNotFoundError.
```

### File: `packages/toolkit/tests/unit/test_vep_flags.py` (MODIFY — add new test cases)

```
test_vep_flags_use_mane_not_mane_select
    Build flags from a minimal VepConfig.
    Assert "--mane" in argv.
    Assert "--mane_select" not in argv.
    Expect: assertion failure (argv currently contains "--mane_select").

test_vep_flags_contains_pick_order_flag
    Assert "--pick_order" in argv.
    Expect: assertion failure (no --pick_order currently).

test_vep_flags_pick_order_value_follows_flag
    Assert the token immediately after "--pick_order" in argv equals
    "rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length".
    Expect: assertion failure.

test_vep_flags_pick_order_value_includes_mane_plus_clinical
    Assert "mane_plus_clinical" in the pick_order value string in argv.
    Expect: assertion failure.
```

### File: `packages/toolkit/tests/unit/test_csq.py` (MODIFY — add new test cases)

```
test_direct_field_map_includes_mane_plus_clinical
    Import _DIRECT_FIELD_MAP from genomeclaw_toolkit.prep._csq.
    Assert any(csq_field == "MANE_PLUS_CLINICAL" for csq_field, _ in _DIRECT_FIELD_MAP).
    Expect: assertion failure (MANE_PLUS_CLINICAL not in map).

test_direct_field_map_mane_plus_clinical_maps_to_mane_plus_clinical_transcript
    Assert the value associated with "MANE_PLUS_CLINICAL" is "mane_plus_clinical_transcript".
    Expect: assertion failure.

test_pick_canonical_entry_prefers_mane_select_over_mane_plus_clinical
    entries = [
        CsqEntry with MANE_PLUS_CLINICAL="NM_xxx.1", MANE_SELECT="", CANONICAL="NO",
        CsqEntry with MANE_SELECT="NM_yyy.1", MANE_PLUS_CLINICAL="", CANONICAL="NO",
    ]
    result = pick_canonical_entry(entries)
    Assert result is the MANE_SELECT entry.
    Expect: passes (existing logic; verify does not regress).

test_pick_canonical_entry_falls_back_to_mane_plus_clinical
    entries = [
        CsqEntry with MANE_SELECT="", MANE_PLUS_CLINICAL="NM_xxx.1", CANONICAL="NO",
        CsqEntry with MANE_SELECT="", MANE_PLUS_CLINICAL="",           CANONICAL="YES",
    ]
    result = pick_canonical_entry(entries)
    Assert result is the MANE_PLUS_CLINICAL entry (step 2 of new rank).
    Expect: assertion failure (current code falls through to CANONICAL=YES).

test_pick_canonical_entry_falls_back_to_canonical_when_no_mane
    entries = [
        CsqEntry with MANE_SELECT="", MANE_PLUS_CLINICAL="", CANONICAL="YES",
        CsqEntry with MANE_SELECT="", MANE_PLUS_CLINICAL="", CANONICAL="NO",
    ]
    result = pick_canonical_entry(entries)
    Assert result is the CANONICAL=YES entry.
    Expect: passes (existing logic; verify does not regress).
```

### File: `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` (MODIFY)

```
Move "vep" from _WARN_TOOLS to _STRICT_TOOLS.
Expect: test_invT001_strict_tools_have_conventions_dataclass fails
        (VepConventions does not exist yet).
```

---

## Step 1.2 — GREEN: minimal implementation

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py` (CREATE)

Create a `VepConventions` frozen dataclass with fields as described in the Solution Design section of `development-plan.md`:

- `verified_against_version: str = "114.1"`
- `mane_flag: str = "--mane"`
- `pick_order_flag: str = "--pick_order"`
- `pick_order_value: str = "rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length"`
- `mane_select_csq_field: str = "MANE_SELECT"`
- `mane_plus_clinical_csq_field: str = "MANE_PLUS_CLINICAL"`

Module docstring must cite INV-T001 and reference the pre-phase verification findings.

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py` (MODIFY)

In `_STATIC_FLAGS` at line 135:
- Replace `"--mane_select"` with `"--mane"`.
- Add `"--pick_order"` and `"rank,mane_select,mane_plus_clinical,canonical,appris,tsl,biotype,ccds,length"` as the next two elements, immediately after `"--mane"`.

The `_STATIC_FLAGS` constant should draw the flag names and values from `VepConventions` where practical — or at minimum the docstring must cross-reference `_vep_conventions.py` so a reviewer can confirm alignment. Fully binding `_STATIC_FLAGS` to `VepConventions()` fields is preferred; if that creates a circular-import risk, a module-level constant pulled from the conventions dataclass at import time is acceptable.

Update the module docstring to reflect `--mane` (replaces `--mane_select`) and add a note that `--pick_order` is now emitted.

### File: `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py` (MODIFY)

In `_DIRECT_FIELD_MAP` at line 137: add
```python
("MANE_PLUS_CLINICAL", "mane_plus_clinical_transcript"),
```
immediately after the `("MANE_SELECT", "mane_select_transcript")` entry.

In `pick_canonical_entry` at line 106: insert a MANE_PLUS_CLINICAL tier between the existing MANE_SELECT and CANONICAL tiers:

```python
for entry in entries:
    if entry.by_name.get("MANE_SELECT"):
        return entry
# NEW: prefer MANE Plus Clinical when Select is absent
for entry in entries:
    if entry.by_name.get("MANE_PLUS_CLINICAL"):
        return entry
for entry in entries:
    if entry.by_name.get("CANONICAL") == "YES":
        return entry
return entries[0]
```

Update `pick_canonical_entry`'s docstring to document the new tier.

Update the module docstring to include `mane_plus_clinical_transcript` in the Phase-4D column list.

### File: `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` (MODIFY)

Move `"vep"` from `_WARN_TOOLS` to `_STRICT_TOOLS` (this was done in Step 1.1; confirm it is still correct after the conventions module exists).

---

## Step 1.3 — REFACTOR

After all Phase 1 tests are green:

1. Add `__all__` to `_vep_conventions.py`.
2. Confirm `_STATIC_FLAGS` in `_vep.py` references `VepConventions` fields or has an inline cross-reference comment pointing to the conventions module. The flag values must not be duplicated silently.
3. Review `_csq.py` `pick_canonical_entry` docstring for completeness — the four-step order must be explicit.
4. Run `mypy` (or equivalent type checker for the toolkit) against the modified files. No new type errors.
5. Run the full toolkit unit test suite to confirm no regressions in tests not part of this phase.

---

## Files

| Action | File path |
|---|---|
| CREATE | `packages/toolkit/src/genomeclaw_toolkit/prep/_vep_conventions.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/_vep.py` |
| MODIFY | `packages/toolkit/src/genomeclaw_toolkit/prep/_csq.py` |
| CREATE | `packages/toolkit/tests/unit/test_vep_conventions.py` |
| MODIFY | `packages/toolkit/tests/unit/test_vep_flags.py` |
| MODIFY | `packages/toolkit/tests/unit/test_csq.py` |
| MODIFY | `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` |

---

## Verification

```
# From the toolkit package root
pytest packages/toolkit/tests/unit/test_vep_conventions.py -v
pytest packages/toolkit/tests/unit/test_vep_flags.py -v
pytest packages/toolkit/tests/unit/test_csq.py -v
pytest packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py -v

# Full toolkit suite (no regressions)
pytest packages/toolkit/tests/ -v
```

---

## Completion criteria

- [ ] `VepConventions` frozen dataclass exists at `prep/_vep_conventions.py` with all required fields.
- [ ] `build_vep_flags(...)` argv contains `"--mane"` and `"--pick_order"` with the standard value string.
- [ ] `build_vep_flags(...)` argv does NOT contain `"--mane_select"`.
- [ ] `_DIRECT_FIELD_MAP` in `_csq.py` contains `("MANE_PLUS_CLINICAL", "mane_plus_clinical_transcript")`.
- [ ] `pick_canonical_entry` MANE_PLUS_CLINICAL tier is between Select and CANONICAL in the rank.
- [ ] `"vep"` is in `_STRICT_TOOLS` in the INV-T001 discovery test and that test passes.
- [ ] All Phase 1 unit and invariant tests pass.
- [ ] Full toolkit test suite passes (no regressions).
- [ ] Pre-phase verification results (VEP `--help` and `--pick_order` CSQ-entry-count check) documented in `initial_findings.md`.
- [ ] `work-notes.md` updated with this session's decisions.
