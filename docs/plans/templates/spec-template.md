# Feature: <Name>

**Status**: Draft | Approved | In Progress | Complete
**Created**: <YYYY-MM-DD>
**Owner**: <name or agent>
**Related Plans**: <links to related plans, if any>

---

## Goal

<One sentence describing the outcome.>

## Background

<Why this feature is needed. What problem does it solve? What's broken or missing today? Cite the symptom, not just the desire.>

## Acceptance Criteria

Each criterion must be specific and testable. One AC should map to one or more tests.

- [ ] AC1: <criterion>
- [ ] AC2: <criterion>
- [ ] AC3: <criterion>

## Applicable Invariants

Reference IDs from [docs/reference/INVARIANTS.md](../../reference/INVARIANTS.md) and explain how each constrains this work.

- **INV-D001** Raw Genomic Files Are Source-of-Truth — <how it applies>
- **INV-E001** Assistant Claims Must Be Traceable to Evidence — <how it applies>
- **INV-P001** Privacy Is the Default Operating Mode — <how it applies>
- **INV-R001** Derived Stores Must Stay Rebuildable — <how it applies>
- **INV-C001** Separate Research Assistance from Clinical Advice — <how it applies>

## Proposed New Invariants

If this work introduces a project-wide constraint that should outlive the feature, propose it here. Otherwise: **None**.

- **NEW INV-?**: <Proposed name> — <rule + rationale>

## Technical Requirements

### Source Data Inputs
- <files / formats / locations>

### Derived Outputs
- <stores / schemas / locations>

### Schema / Migration Impact
- <new tables, columns, schema version bumps>

### Pipeline / Workflow Impact
- <new pipeline steps, ordering, idempotency>

### Agent / UX Impact
- <new prompts, report sections, interactive flows>

### External Dependencies
- <annotation datasets, reference builds, third-party tools>

## Privacy & Safety Considerations

- **Boundary scan**: <where could sensitive data leave the trusted environment?>
- **Default-off remote calls**: <list any optional remote integrations>
- **Redaction surface**: <what is redacted before any optional egress>
- **Clinical escalation**: <does this surface findings that warrant clinical confirmation? If so, how is that marked?>

## Out of Scope

Explicit boundaries. What this feature **does not** include.

- <out-of-scope item>
- <out-of-scope item>

## Dependencies

- <prerequisite features / data / infra>

## Open Questions

Unresolved before implementation can start.

- [ ] Q1: <question>
- [ ] Q2: <question>
