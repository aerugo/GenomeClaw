# Phase 3: Agent-Integration Section Rewrite

**Status**: Pending
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

Rewrite the README's "How NemoClaw Agents Use GenomeClaw" section to match reality: ten plugin tools, host-service port 8645, the real endpoint list (incl. `/v1/host/profile`(+`/completeness`) + the agent-driven PRS endpoints; drop the retired `/v1/pgs/{trait}`), and a one-line note that the agent retrieves the host profile before genome-informable replies (INV-C004). Blocking privacy-safety-reviewer pass on the rewritten privacy + agent-integration sections.

## Invariants Enforced in This Phase

- **INV-P001 / INV-P002** — the rewritten privacy + agent sections keep the egress model accurate (host-side-only raw data; NemoClaw the named egress; topic-only web_search; host profile sensitive + read-only). Verified by the privacy-safety-reviewer pass (blocking).
- **INV-D002** — host-side-only framing accurate.

## TDD Steps

- **GREEN**: the Phase-1 gate's tools (#1,#2), port (#3), endpoints (#4) assertions turn green.
- **Edits**:
  - Replace "six agent-callable tools … `genomeclaw_pgs`" with the ten tools (names + one-liners), grouped (status/findings/variant/evidence/gene; pgs_list/_get/_compute/_compute_status; host_profile).
  - Fix the host-service port to 8645; sweep ALL port references for the 8643/8645 self-contradiction.
  - Replace the endpoint list with the actual routes; add `/v1/host/profile`(+`/completeness`); remove `/v1/pgs/{trait}`.
  - Add a sentence: the agent calls `genomeclaw_host_profile` before any genome-informable reply (INV-C004); profile content is host-side, minimal-sufficient, never in `web_search`.
- **REFACTOR**: reconcile against the host-profile plan's wording so the README + agent prompt + INVARIANTS describe INV-C004 consistently.

## Privacy / Egress Notes

The README *describes* the privacy model; an inaccurate description is itself a safety issue. The privacy-safety-reviewer pass confirms: raw files never leave the host (INV-D002); NemoClaw is the named minimal-sufficient egress (INV-P002); web_search is topic-only (INV-P001); host profile is sensitive host-side data via a read-only tool. File the review output under `privacy-review.md`.

## Files

| File | Action | Purpose |
|------|--------|---------|
| `README.md` | MODIFY | Agent-integration + privacy sections. |
| `docs/plans/active/readme-accuracy-refresh/privacy-review.md` | CREATE | Privacy-safety-reviewer output. |

## Verification

```bash
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_readme_accuracy.py -v -k "tool or port or endpoint"
```

## Completion Criteria

- [ ] Ten tools named; no "six" (AC2). Port 8645 everywhere (AC3). Endpoint list matches; `/v1/host/profile` present, `/v1/pgs/{trait}` gone (AC4).
- [ ] Privacy-safety-reviewer pass approved; findings (if any) addressed (AC10).
- [ ] Phase-1 gate tools/port/endpoints assertions pass.
- [ ] `work-notes.md` + `development-plan.md` updated.
