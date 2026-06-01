# Phase 1: Audit Host-Service Tool-Result Shapes

**Status**: Pending
**Started**: <YYYY-MM-DD>
**Completed**: <YYYY-MM-DD>
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Inventory each GenomeClaw tool's current host-service response shape. For each tool, identify the **diagnostic richness gap** — what raw trace, query results, command logs, or analysis output the agent would benefit from seeing but doesn't currently receive. Produce `phases/phase-1-host-service-audit.md` as the data Phase 2 implements against.

## Scope Boundaries

- **In scope**:
  - All tools surfaced by the plugin: `genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_gene`, `genomeclaw_pgs_list`, `genomeclaw_pgs_get`, `genomeclaw_pgs_compute`, `genomeclaw_pgs_compute_status`.
  - Both success and failure response shapes.
  - Host-service route handlers in `packages/toolkit/src/genomeclaw_toolkit/service/`.
- **Out of scope**:
  - Implementation changes (Phase 2).
  - Plugin-side changes (Phase 3).
  - Other plugins (this plan is scoped to nemoclaw-plugin).

## Invariants Enforced in This Phase

- None directly. Audit feeds Phase 2's `INV-A005` v1.23 work + (potential) `INV-D010` promotion.

---

## Steps

### Step 1.1 — Map each tool to its host-service route + response model

For each plugin tool, find:
- The host endpoint it hits (e.g., `genomeclaw_pgs_compute` → `POST /v1/pgs/compute`).
- The Pydantic response model in `service/`.
- The handler implementation.

Use `grep` over [packages/nemoclaw-plugin/src/index.ts](../../../../../packages/nemoclaw-plugin/src/index.ts) for `safeCall`/`safePost` callsites + the path arg.

### Step 1.2 — Capture current response shape (success + failure)

For each tool:
- Read the Pydantic model fields.
- Read the handler's response construction to see what's actually populated.
- Note structured detail vs. minimal envelope vs. opaque fields.

### Step 1.3 — Identify the diagnostic gap

For each tool, ask:
1. **Failure path**: When the tool fails, does the agent see enough to give the user a real explanation? E.g., for `genomeclaw_pgs_compute` failure: does the response include the nextflow command, the stage that failed, partial log tail, the upstream cause (missing scorefile, missing config, scorefile_missing)?
2. **Success path**: When the tool succeeds, does the response carry useful interpretive metadata? E.g., for `genomeclaw_pgs_compute` success: does the response carry match-rate, effective_rate, ancestry context, decline reasons (if any) alongside the percentile?
3. **Trace info**: For tools that internally make sub-calls (pgsc_calc wrapping nextflow; force-genotyping running mpileup), is the sub-call trace available?

Categorize each gap as **high-value** (agent needs this to give a real user answer), **medium-value** (operator debugging), **low-value** (noise / already implicit).

### Step 1.4 — Produce the audit document

Write `phases/phase-1-host-service-audit.md` with one section per tool, structured as:

```markdown
## genomeclaw_pgs_compute

**Endpoint**: `POST /v1/pgs/compute`
**Response model**: `PgsComputeTaskResponse` in `service/pgs_compute.py`

**Current response — success path**:
- `task_id` (str)
- `pgs_id` (str)
- `status` ("queued" | "running" | "done")
- `error` (str | null)

**Current response — failure path (status: "failed")**:
- Same shape with `status="failed"`, `error=<code>`.

**Identified gaps (high-value)**:
- No nextflow command surface for compute failures.
- No stage info (which step failed).
- No partial trace excerpt.

**Identified gaps (medium-value)**:
- No effective_rate breakdown on success.
- No ancestry context.

**Proposed Phase 2 extensions**:
- Add `diagnostic_trace: ToolDiagnosticTrace | null` field. Structure: `{stage, command, partial_log, upstream_cause}`.
- Add `compute_metadata: PgsComputeMetadata | null` field on success: `{match_rate, effective_rate, ancestry_label, ...}`.

**Priority**: High (this is the AC8 muscle-question scenario; failures here drove the v1.22 misship).
```

Repeat for every tool. Estimate ~30 minutes per tool, including handler-code reading.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `phases/phase-1-host-service-audit.md` | CREATE | Per-tool inventory + gap analysis + proposed extensions. |
| [work-notes.md](../work-notes.md) | MODIFY | Append audit headline summary (priority counts, high-value tools list). |

---

## Verification

The audit is correct when:

```bash
# Every plugin tool name appears in the audit document
for tool in genomeclaw_status genomeclaw_findings genomeclaw_variant genomeclaw_evidence genomeclaw_gene genomeclaw_pgs_list genomeclaw_pgs_get genomeclaw_pgs_compute genomeclaw_pgs_compute_status; do
  grep -q "^## $tool" docs/plans/active/agent-synthesis-over-rich-tool-data/phases/phase-1-host-service-audit.md && echo "  ✓ $tool" || echo "  ✗ $tool MISSING"
done
```

---

## Completion Criteria

- [ ] All 9 plugin tools covered in the audit doc.
- [ ] Each tool has current shape + gap analysis + Phase 2 proposal.
- [ ] Priorities assigned (high / medium / low).
- [ ] `work-notes.md` updated with headline (X high-value tools, Y medium, Z low).
- [ ] Phase 1 row in `development-plan.md` progress table set to **Complete**.
