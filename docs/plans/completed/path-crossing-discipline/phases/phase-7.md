# Phase 7: Real-tool smoke (v2) + plan close-out

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Why a second smoke phase

[Phase 5](phase-5.md) was scoped as the validation gate; in practice it functioned as a *debug* gate. Seven iterations against `MPNRGLQ2K.cram` surfaced four discipline gaps the v1.12 plan didn't catch (see [phase-6.md §"Why this phase exists"](phase-6.md#why-this-phase-exists)). Phase 6 closed all four.

Phase 7 is the actual validation gate: re-run the smoke against the project owner's real CRAM with all Phase 1–6 fixes in place; assert none of the seven prior failure modes recur; close the plan.

If Phase 7 surfaces a fifth gap, the discipline still has a missing layer — open a new follow-up plan instead of cycling within this one.

---

## Objective

Run `bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018` to rc=0. The driver invokes only through the shim (INV-D007). The Phase 1–6 fixes — identical-path overlay (INV-D005), docker-socket mount, `--user 0:0` default, per-subdir env vars, factory rejection of canonical-mount paths (INV-D006 v1.13) — all engage. pgsc_calc spawns DooD siblings, they resolve their `-v <host>:<container>` bind mounts against the host filesystem, tasks complete, an `aggregated_scores.txt.gz` lands under the work dir, the CLI emits a success envelope, the driver records a `pgs_scores`-shaped JSON file.

---

## Scope Boundaries

- **In scope**:
  - One smoke run against `MPNRGLQ2K.cram` with the Phase 6 image (`genomeclaw/toolkit:phase6` or a successor tag).
  - Capture the trace into `work-notes.md` Phase 7 entry: total wall-clock, peak RSS, sibling-container ledger (which pgsc_calc subimages spawned + their exit codes), pgs_scores row.
  - Run `GENOMECLAW_PHASE5_SMOKE_DIR=<dir> uv run pytest -m needs_phase5_smoke_artifacts` to exercise the 10 verification gates.
  - Move the plan from `docs/plans/active/` to `docs/plans/completed/`.
  - Reconcile `development-plan.md`'s Progress Tracking + add a "Divergences from initial design" section documenting the four gaps that surfaced + their close-outs.

- **Out of scope**:
  - Colima VM resource sizing (pgsc_calc may need >2 CPU; if so, a separate one-line note in the work-notes; not in this plan's responsibility).
  - Backfill of `INV-T001`'s warn-tools list (`bcftools`, `bgzip`, `mosdepth`, `vcfanno`, `vep`). Separate small plans triggered on each tool's next pin bump.
  - A `bin/genomeclaw refs materialize --target prs_pca_sites` CLI subcommand (the smoke driver currently preflight-errors when PCA sites aren't materialized). Separate plan for the CLI wiring.

## Invariants Affected

None new. Phase 7 **validates** the cumulative behaviour of:
- INV-D001..INV-D005 (existing).
- INV-D006 v1.13 (Phase 6 tightening).
- INV-D007 (Phase 6 NEW).
- INV-T001 (Phase 2 / v1.12).

---

## TDD Steps

### Step 7.1 — RED: no new tests

Phase 7 is validation, not development. The pass/fail signal comes from the smoke run + the existing `needs_phase5_smoke_artifacts` gates.

### Step 7.2 — Execute the smoke

1. **Preflight**:
   ```bash
   docker image inspect genomeclaw/toolkit:phase6 >/dev/null && echo OK
   ls /Volumes/Genome_Work/genomeclaw/raw/MPNRGLQ2K/*.cram >/dev/null && echo CRAM_OK
   ls /Volumes/Genome_Work/genomeclaw/reference/prs_pca_sites/v1/pca_*.tsv >/dev/null && echo SITES_OK
   ls /Volumes/Genome_Work/genomeclaw/reference/pgs_scorefile/PGS000018/*.txt.gz >/dev/null && echo SCOREFILE_OK
   ls /Volumes/Genome_Work/genomeclaw/reference/pgs_catalog_ancestry/v1/GRCh38_HGDP*ALL.pgen >/dev/null && echo PANEL_OK
   ```
2. **Invocation**:
   ```bash
   GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:phase6 \
   bin/genomeclaw-prs-smoke MPNRGLQ2K PGS000018 2>&1 | tee /tmp/phase7-smoke.log
   ```
   Expected wall-clock: ~30–60 min on a 2-CPU Colima (Tier 1 cache hits in 90s; Tier 2 builds in ~5–10 min; pgsc_calc nextflow in ~25–45 min).

3. **Verify success envelope**:
   ```bash
   jq . "$SMOKE_DIR/cli_envelope.json"
   # Expected: {"cli_output_schema_version": "1.0", "command": "pgs", "pgs": {...}}
   # The pgs object should have:
   #   - pgs_id: "PGS000018"
   #   - percentile_in_user_ancestry: <0..100>
   #   - raw_score: <float>
   #   - calibration_status: "clean" or "warning" (not "decline")
   ```

4. **Verify pgsc_calc output files**:
   ```bash
   ls "$SMOKE_DIR/pgsc_calc_work/results/score/"  # aggregated_scores.txt.gz expected
   ls "$SMOKE_DIR/pgsc_calc_work/results/ancestry/"  # aggregated_scores_norm.txt.gz expected
   ```

5. **Run artifact-gated tests**:
   ```bash
   GENOMECLAW_PHASE5_SMOKE_DIR="$SMOKE_DIR" \
   GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:phase6 \
     uv run pytest -m "needs_phase5_smoke_artifacts or needs_prod_python" --no-header
   ```
   All 10 + 2 = 12 tests should pass.

### Step 7.3 — Plan close-out

After the smoke passes (and only after):

1. **Append to [work-notes.md](../work-notes.md)** a Phase 7 entry covering:
   - Smoke wall-clock + peak RSS.
   - Sibling-container ledger (which pgsc_calc subimages spawned, their exit codes).
   - The `pgs_scores` row's `pgs_id`, `percentile_in_user_ancestry`, `raw_score`, `calibration_status`.
   - Affirmation that none of the v1–v7 reproducers fired (search the log for `DooDPathError`, `_flavour`, `EXTRACT_DATABASE`, `permission denied`).
2. **Update [development-plan.md](../development-plan.md)**:
   - Phase 7 row in Progress Tracking → Complete.
   - Add a "Divergences from initial design" section listing the four gaps Phase 6 closed and one paragraph explaining: the original three-layer model was incomplete; the discipline plan now operates on four layers (shim seam / overlay / wrapper boundary / tool conventions); ledger of original design vs. delivered design.
3. **Move the plan directory**:
   ```bash
   git mv docs/plans/active/path-crossing-discipline docs/plans/completed/
   ```
4. **Add a §Follow-ups** section in the moved `development-plan.md` with:
   - Backfill `BcftoolsConventions`, `BgzipConventions`, `MosdepthConventions`, `VcfannoConventions`, `VepConventions` (INV-T001's warn-tools list).
   - Wire a `bin/genomeclaw refs materialize --target prs_pca_sites` CLI subcommand (the smoke driver currently preflight-errors here).
   - CI gate on `tools/pgsc_calc/probe.sh` re-run when `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes.
   - Per-phase `needs_prod_python` retroactive backfill (Phase 1 / 2 / 3 weren't gated; their tests only ran on host venv).

---

## Files

| Action | Path | Purpose |
| --- | --- | --- |
| MODIFY | [work-notes.md](../work-notes.md) | Phase 7 smoke trace |
| MODIFY | [development-plan.md](../development-plan.md) | Phase 7 row complete + Divergences section + Follow-ups |
| GIT-MV | `docs/plans/active/path-crossing-discipline/` → `docs/plans/completed/path-crossing-discipline/` | Plan close-out |

## Completion Criteria

- [ ] Smoke rc=0 against `MPNRGLQ2K.cram`; the cli_envelope is a success envelope (not an error one).
- [ ] pgs_scores fields populated (percentile_in_user_ancestry + raw_score both non-null; calibration_status is "clean" or "warning").
- [ ] Zero `DooDPathError` / `_flavour` / `EXTRACT_DATABASE` exit-127 in the trace.
- [ ] All `needs_phase5_smoke_artifacts` + `needs_prod_python` tests pass.
- [ ] [work-notes.md](../work-notes.md) Phase 7 entry written.
- [ ] Plan moved from `active/` to `completed/`.

## Open Questions (provisional answers)

1. **What if pgsc_calc hits the "resources exceed availability" warning + stalls?** Not a discipline issue. Document the colima VM resource sizing recommendation in the Phase 7 work-notes; offer the user the option to increase CPU/memory allocation. The smoke can complete on 2 CPUs but takes longer; the warning is purely advisory.

2. **What if a NEW (5th) gap surfaces?** Open a new plan (`path-crossing-discipline-v2` or a small standalone). Do NOT extend this plan further — at six phases, this plan has earned its close-out. The cumulative learning from gaps 1–4 + Phase 6's process improvements (prod-python gate + INV-D007 seam) should make a 5th gap rarer.

3. **What's the cleanest fixture for capturing the smoke trace?** Append the full log + grep summaries to work-notes. No structured JSON capture — the smoke is a one-off real-data validation, not a recurring test.
