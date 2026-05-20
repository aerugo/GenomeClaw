# Phase 5: Real-tool smoke re-run + plan close-out

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Validate the cumulative effect of Phases 1–4 against the project owner's real CRAM (`MPNRGLQ2K.cram`) by re-running `bin/genomeclaw pipeline prs-compute` end-to-end through the canonical shim (not the per-smoke driver). The four path-related smoke reproducers (v2 / v3 / v5 / v6 from the prs-input-coverage-fill plan) must NOT fire; the run completes with a `pgs_scores` row landed + `INTERSECT_THINNED` non-empty + `Z_norm2` populated.

This is the "did the discipline actually work end-to-end" gate. Synthetic tests caught the regressions one by one; the real-tool smoke validates that, against the actual `MPNRGLQ2K.cram` on the actual two-CPU Colima setup, every one of the six prior smoke failures is closed.

## Scope Boundaries

- **In scope**:
  - One clean run of `bin/genomeclaw pipeline prs-compute --pgs-id PGS000018 --sample-id MPNRGLQ2K` against the project owner's CRAM (50–60 min on 2-CPU Colima).
  - Capture the full trace in `work-notes.md`: shim's argv (with the identical-path overlay + HOST_ROOTS env var), inside-container subprocess calls, pgsc_calc Nextflow trace, final `pgs_scores` row.
  - Plan-directory move: `docs/plans/active/path-crossing-discipline/` → `docs/plans/completed/path-crossing-discipline/`.
  - `development-plan.md` reflects the *final* implemented design (any divergences from the original draft documented).
- **Out of scope**:
  - Backfilling the warn-tools (bcftools / bgzip / mosdepth / vcfanno / vep) — each is its own short plan triggered on the next pin bump for that tool.
  - CI gate on `tools/pgsc_calc/probe.sh` rerun on pin change — deferred Phase-2 follow-up.
  - Any new code; Phase 5 is purely validation + close-out.

## Invariants Enforced in This Phase

None new. Phase 5 **validates** the cumulative behaviour of INV-D005 + INV-D006 + INV-T001 + the existing INV-D001..INV-D004 invariants.

The implicit contracts being verified end-to-end:
- INV-D005 — the shim emits the identical-path overlay; siblings see the canonical roots.
- INV-D006 — the orchestrator wraps paths via `as_sibling_mountable` and no `DooDPathError` fires (paths are sibling-mountable by construction in the canonical layout).
- INV-T001 — the conventions dataclass + golden argv match what the real pgsc_calc binary accepts.

---

## TDD Steps

### Step 5.1 — No new RED (this is a validation phase)

There are no new tests. The pass/fail signal is "did the smoke run rc=0 with the expected outputs."

### Step 5.2 — Execute the real smoke

1. **Preflight**:
   - Confirm `MPNRGLQ2K.cram` (+ `.crai`) exists under the canonical raw mount.
   - Confirm the toolkit image with Phase 1–3 changes is built (`genomeclaw/toolkit:path-crossing-disc` or equivalent) and the shim's `GENOMECLAW_IMAGE` is pointing at it.
   - Confirm `genomeclaw host doctor` is clean (all four mounts; ancestry reference data; PGS scorefile cached).
2. **Invocation**:
   ```bash
   bin/genomeclaw pipeline prs-compute \
     --pgs-id PGS000018 \
     --sample-id MPNRGLQ2K \
     --rationale "smoke validation for path-crossing-discipline plan" \
     --question "verification: does the discipline hold end-to-end against the real CRAM"
   ```
3. **Capture**:
   - Full shim argv (set `GENOMECLAW_DEBUG=1` to print it).
   - Inside-container exception traces (none expected, but if any fire they go in work-notes).
   - The final `pgs_scores` row (`genomeclaw query pgs MPNRGLQ2K PGS000018 --json`).
   - The pgsc_calc Nextflow `INTERSECT_THINNED` + `Z_norm2` numbers from `<work_dir>/score/aggregated_scores.txt.gz` + `<work_dir>/ancestry/aggregated_scores_norm.txt.gz`.

### Step 5.3 — Plan close-out

Once the smoke passes:

1. **Update `development-plan.md`**:
   - Reflect the *final* implemented design. Any divergences from the original draft (e.g., autouse fixture for `GENOMECLAW_HOST_ROOTS` was not in the original plan; Test 13 dropped; `compute_pgs` parameter retypes added) get a §"Divergences from initial design" section.
   - Bump §Progress Tracking with the Phase 5 row complete.
2. **Move the plan**:
   ```bash
   git mv docs/plans/active/path-crossing-discipline docs/plans/completed/path-crossing-discipline
   ```
3. **Update work-notes.md** with the Phase 5 entry (smoke trace + decision log).
4. **List follow-ups explicitly** in development-plan.md:
   - Warn-tool conventions backfill plans (bcftools, bgzip, mosdepth, vcfanno, vep).
   - CI gate on `tools/pgsc_calc/probe.sh` re-run when `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes.

---

## Files

| Action | Path | Purpose |
| --- | --- | --- |
| MODIFY | [development-plan.md](../development-plan.md) | Phase 5 row complete; final-design reconciliation; follow-ups list |
| MODIFY | [work-notes.md](../work-notes.md) | Phase 5 smoke-trace entry |
| GIT-MV | docs/plans/active/path-crossing-discipline → docs/plans/completed/ | Close-out move |

## Verification

Two gates:

1. **Smoke run rc=0**:
   ```bash
   GENOMECLAW_DEBUG=1 bin/genomeclaw pipeline prs-compute ... 2>&1 | tee smoke.log
   echo "RC=$?"
   ```
2. **Final row exists + has populated fields**:
   ```bash
   bin/genomeclaw query pgs MPNRGLQ2K PGS000018 --json \
     | jq '.percentile_in_user_ancestry, .raw_score, .calibration_status'
   ```
   Both `percentile_in_user_ancestry` and `raw_score` non-null; `calibration_status` is `clean` or `warning` (not `decline`).
3. **No prior-smoke reproducer fired** in the captured trace:
   - No `No such file: merged.vcf.gz.vcf` (smoke v6).
   - No `Please provide an input samplesheet` (smoke v2).
   - No nextflow `No such file` for any path under `/tmp/genomeclaw-scratch/...` (smoke v3).
   - No host-daemon mount-resolution failures (smoke v5).

## Completion Criteria

- [ ] Smoke run rc=0 against the real CRAM; trace captured.
- [ ] `pgs_scores` row landed with non-null percentile + raw_score.
- [ ] Four prior-smoke reproducers absent from the trace.
- [ ] [development-plan.md](../development-plan.md) reflects final implemented design + follow-ups list.
- [ ] Plan moved from `active/` to `completed/`.
- [ ] [work-notes.md](../work-notes.md) Phase 5 entry written.

## Open Questions for the Implementer

1. **Toolkit image rebuild required?** Yes — Phases 1–3 added new Python modules (`_paths.py`, `_pgsc_calc_conventions.py`) and changed the shim. The smoke needs an image with the latest source baked. Verify the running image's commit SHA matches HEAD.
2. **Tier 1 cache reuse?** The 90-minute Tier 1 cache from prior smokes is fine to reuse if the bcftools / mosdepth versions match the new image. If not, re-running Tier 1 adds ~30 min.
3. **Concurrent runs?** The smoke validates the single-sample, single-PGS happy path. Concurrent / multi-PGS validation is a future plan, not this one.
