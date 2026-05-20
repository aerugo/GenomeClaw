# PRS Pipeline Runtime Hardening

**Status**: Active
**Created**: 2026-05-20
**Owner**: hugi

---

## Goal

Codify the 11-smoke-iteration hardening pass that landed after [path-crossing-discipline](../../completed/path-crossing-discipline/) closed: deployment-config controls (resource caps, mount lifecycle), pgsc_calc internal-path discipline (stageInMode, tarball semantics, sampleset naming), and the never-cache-degenerate guard. Each fix shipped as a point change; this plan binds them into a coherent contract + promotes two new invariants the iterations earned.

## Background

The path-crossing-discipline plan validated the discipline end-to-end against `MPNRGLQ2K.cram` (Phase 7). Smoke v7–v17 then exercised the pipeline at **real data scale** and surfaced 8+ distinct deployment + content issues — none of them path-crossing failures, all of them gaps in how the wrapper composes pgsc_calc against a deployment.

Each fix landed as it surfaced:
- v7–v8: pgsc_calc resource ask exceeds colima VM capacity → env-var caps
- v9: colima `mounts: []` lost external drive after restart → explicit mounts config
- v10: pgsc_calc `EXTRACT_DATABASE` wanted a tarball, got a directory → `_ancestry_reference_bundle()` helper
- v11: VM data disk full (98 GB images accumulated) → `docker image prune -af`
- v12: image rebuild failed silently with netlink error → retry
- v13: pgsc_calc internal filename derivation broke on dotted sampleset → strip `.vcf` + `.gz`
- v14: nextflow symlink staging points at parent-container-only path → `process.stageInMode = 'copy'`
- v15: Tier 2 cache held 0 records from an earlier degenerate run → empty-cache guard
- v16: rebuilt on stale image → retry
- v17: cooking now — fresh Tier 2 build with the guard in place

The work shipped fast, but the **history exists only in chat + tmp log files**. This plan brings it into the planning protocol as a coherent record + promotes the operational invariants the iterations earned.

## Acceptance Criteria

1. **Iteration ledger preserved**: every smoke v7–v17's root cause + fix is recorded in this plan's `work-notes.md`, traceable to the source diff.
2. **Two new invariants promoted into [INVARIANTS.md](../../../reference/INVARIANTS.md)**:
   - **`INV-R002` — Wrappers MUST validate cached artifacts are non-degenerate before reuse** (the empty-cache guard). Cached artifacts where the meaningful payload is missing (e.g., bcftools VCF with 0 records, scoring file with 0 weights) MUST surface as a typed error, not be silently served.
   - **`INV-D008` — DooD-spawning pipelines MUST use copy-staging for tool inputs**. The default symlink staging dereferences to parent-container-only paths, invisible to siblings. Pipelines that spawn DooD siblings MUST set `process.stageInMode = 'copy'` (or equivalent for non-nextflow tools).
3. **PgscCalcConventions tightened** to capture per-flag value semantics (not just flag names). The `run_ancestry_flag` value is a tarball, not a directory; codify the value type so a future bundle-extraction change surfaces as a typed test failure (the gap the user flagged after smoke v10).
4. **Follow-up backlog explicit**: colima memory ceiling (F3), per-sample sex info for chrX scoring (F4), `bin/genomeclaw refs materialize` CLI subcommand (F5), CI gate on `tools/pgsc_calc/probe.sh` (F6) — each carries an open-question line for a future plan to pick up.
5. **Suite green**: every existing test passes, plus the new tests landed during smoke iteration (chrX filter, sampleset, TMPDIR config, empty-cache guard, etc.).

## Applicable Invariants

| ID | How it constrains this plan |
|----|------------------------------|
| `INV-D001` | Tier 1/2 force-genotyping is read-only on `raw/`; the guard MUST fail closed (raise) rather than overwrite. |
| `INV-D003` | Empty cache guard runs in `shard_scratch`; promotion is conditional on validation. |
| `INV-D005` / `INV-D006` / `INV-D007` (Phase 1+3 invariants) | All paths flowing into the new bcftools / nextflow steps follow the discipline. |
| `INV-T001` | The conventions tightening extends INV-T001 (it captures more of the tool contract). |
| `INV-R001` (rebuildability) | The empty-cache guard MAKES Tier 1/2 rebuildable from source — without it, a degenerate cache poisons future runs. |

## Proposed New Invariants

- **`INV-R002`** — Never Cache a Degenerate Result. **Rule**: Any wrapper that caches a derived artifact MUST validate non-degeneracy at write-time (record count > 0 for VCFs, line count > 0 for TSVs, etc.). A degenerate result MUST raise a typed error and MUST NOT be cached. **Why**: a 0-record VCF (or analogous "completed cleanly but empty" result) is a silent-failure signal — every subsequent call against the cache inherits the empty result, and the eventual user-facing symptom surfaces many layers downstream from the actual bug. Smoke v15 surfaced this for Tier 2 (bcftools pipe exited 0 with header-only VCF; pgsc_calc match rate 2.9% was the eventual symptom).

- **`INV-D008`** — Copy-Stage for DooD-Spawning Pipelines. **Rule**: Pipelines that spawn DooD siblings (currently only `pgsc_calc` via nextflow) MUST stage inputs into per-task work-dirs via COPY, not symlink. **Why**: the default symlink staging creates symlinks pointing at parent-container-local paths (e.g., `/opt/nextflow/assets/...`) that don't exist in the sibling's namespace. The sibling dereferences the symlink and fails to open the file. Phase 7 smoke v14 surfaced this for `high-LD-regions-hg38-GRCh38.txt`. For nextflow this is `process.stageInMode = 'copy'`; for other pipeline runners the equivalent setting applies.

## Out of Scope

- **Allele-orientation fix in `_extract_pgs_sites_from_scorefile`** (F7 in work-notes). Surfaced by smoke v17 — the wrapper assumes `REF=other_allele, ALT=effect_allele` but the PGS Catalog `effect_allele` can be either; bcftools rejects sites with reversed assumptions. Fix needs per-site reference lookup via `samtools faidx`. Substantial change; its own plan.
- **chrX/sex-info handling for PRS scoring**: current behavior is `_merge_tier1_tier2` filters to autosomes only (drops chrX/chrY/chrM). Adding proper sex-info via samplesheet `--psam` is a separate plan (F4).
- **Colima memory bump strategy**: the macOS host's 16 GB ceiling vs pgsc_calc's 16 GB ask is hardware-environmental, not pipeline. The env-var resource caps work around it; a proper "rent a bigger VM for compute-heavy steps" strategy is F3.
- **PCA-sites materialization as a CLI subcommand**: smoke driver currently preflights on missing PCA sites. Wiring a `genomeclaw refs materialize --target prs_pca_sites` is F5.

## Privacy & Safety Considerations

No new egress. No new sensitive data flows. The new invariants harden existing pipeline behaviors against silent failure (which is the opposite of a privacy concern — they make failures LOUD, not quiet).

The empty-cache guard fails closed: a degenerate cache is REJECTED rather than served. This is the privacy-safe default — better to surface an error than to silently produce a wrong PRS percentile from incomplete data.

## Open Questions

1. **Should the value-type descriptor in `PgscCalcConventions` be a free-text doc field or a structured enum?** Recommendation: free-text doc field for now (sufficient for human-readable contract); upgrade to enum if a third tool wrapper joins INV-T001.

2. **INV-R002 scope: how strict?** "0 records" is the cleanest threshold; some tools might legitimately produce 0 records (e.g., a coverage report on an empty region). The guard applies to wrappers whose contract is "fill this artifact with results"; tools whose output may legitimately be empty document the exception in their wrapper. Initial scope: Tier 1 + Tier 2 only. Other wrappers join the guard pattern as their callers discover degenerate failure modes.

3. **INV-D008 enforcement: discovery test?** Could walk nextflow `process { stageInMode = ... }` settings in pipeline configs. Today there's only one nextflow pipeline (pgsc_calc); the test would check that pgs.py's `_TMPDIR_REDIRECT_CONFIG` includes `stageInMode = 'copy'`. Larger generalization is a Phase 2 of this plan if more nextflow pipelines join.

4. **Should the colima memory + disk recommendations land in `host doctor`?** Yes per F3 — a separate small plan can add `pgsc_calc_resource_budget` + `vm_data_disk_capacity` doctor checks.
