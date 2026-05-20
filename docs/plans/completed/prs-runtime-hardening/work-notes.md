# PRS Pipeline Runtime Hardening — Work Notes

**Plan**: [development-plan.md](development-plan.md) | **Spec**: [spec.md](spec.md)

Append-only session log.

---

## 2026-05-20 — Plan creation + smoke v7–v17 iteration ledger (backfill)

**Context**:
- [path-crossing-discipline plan](../../completed/path-crossing-discipline/) closed at Phase 7. The smoke driver run that validated the discipline end-to-end stopped at the colima VM memory ceiling — a documented follow-up (F3), out of discipline scope.
- After that close-out, smokes v7–v17 happened: 11 iterations against `MPNRGLQ2K.cram` over ~6 hours, surfacing 8+ deployment + content issues. Each fix shipped as a point change; the iteration history existed only in chat + `/tmp/phase7-smoke-vN.log` files until this plan landed.
- This entry backfills the ledger.

**Iteration ledger (v7–v17)**:

| Smoke | Image | Outcome | Root cause | Fix | Where in code |
|-------|-------|---------|------------|-----|---------------|
| **v7** | `phase6` (original) | rc=1 in 1 sec | `DooDPathError` because smoke driver bypassed the shim — Phase 1+3 fixes weren't engaged. | Updated driver `bin/genomeclaw-prs-smoke` Stage C to invoke via `"$SHIM"` instead of bespoke `docker run`. | `bin/genomeclaw-prs-smoke` (Phase 6 INV-D007 work) |
| **v8** | post-shim fix | rc=1 / nextflow "resources exceed availability" | pgsc_calc `process_medium` default = 16 GB RAM > colima VM's 11.7 GB executor capacity. | Env-var resource caps: `GENOMECLAW_PGSC_CALC_MAX_MEMORY=10.GB` + `_MAX_CPUS=2`. | `pgs.py:_build_pgsc_calc_argv` |
| **v9** | post-cap | preflight fail: "CRAM not found" | colima `mounts: []` in colima.yaml lost `/Volumes/Genome_Work` mount after `colima stop && colima start` (architecture.md's documented gotcha). | Explicit `mounts:` block in `~/.colima/default/colima.yaml` listing `/Users/hugi` + `/Volumes/Genome_Work`. | (user host config — not in repo) |
| **v10** | post-mount fix | `EXTRACT_DATABASE exit 2` (`tar -xf v1`) | `--run_ancestry` pointed at the extracted ancestry **directory**; pgsc_calc's internal script does `tar -xf <value>` and expects a **tarball**. | `_ancestry_reference_bundle()` returns `reference/pgs_catalog_ancestry/v1/pgs_catalog_ancestry.tar.zst` (the tarball alongside the extracted files). | `pgs.py:_ancestry_reference_bundle` |
| **v11** | post-tarball | `INTERSECT_VARIANTS ENOSPC` mid-stream | Colima VM data disk full (98 GB of accumulated docker images from prior toolkit/sandbox tags). | `docker image prune -af` (98 GB → 3 GB used). | (deployment hygiene — not in repo) |
| **v12** | post-prune | preflight fail: "image not present" | Image rebuild failed silently — `Unexpected error 9 on netlink descriptor 4` during VEP install (transient colima network glitch). | Retry. | (transient; documented for posterity) |
| **v13** | rebuilt | `INTERSECT_VARIANTS: FileNotFoundError: GRCh38_merged.afreq.gz` | pgsc_calc derives downstream filenames as `GRCh38_<sampleset>_<chrom>.<ext>`; intersect_cli parses back by stripping `_<chrom>`. Our sampleset was `"merged.vcf"` (from `Path("merged.vcf.gz").stem` keeping the `.`); the derivation broke on the period. | Strip BOTH `.gz` and `.vcf` for sampleset: `vcf.name.removesuffix(".gz").removesuffix(".vcf")` → `"merged"`. | `pgs.py:compute_pgs` (sample_id derivation) |
| **v14** | post-sampleset | `FILTER_VARIANTS exit 3`: plink2 "Failed to open high-LD-regions-hg38-GRCh38.txt" | Nextflow's default `stageInMode = 'symlink'` created a symlink in the work-dir pointing at `/opt/nextflow/assets/.../high-LD-regions-hg38-GRCh38.txt`. That path exists inside the toolkit container only; the plink2 sibling couldn't dereference it. **The fifth path-crossing layer the discipline missed** — tool-internal symlinks. | `process.stageInMode = 'copy'` in the auto-generated `nextflow.config`. Nextflow physically copies inputs into the work-dir (which IS bind-mounted to siblings). | `pgs.py:_TMPDIR_REDIRECT_CONFIG` (extended) |
| **v15** | post-stageInMode | `ZeroMatchesError`: pgsc_calc match rate 2.9% | **Tier 2 cache had 0 records** from an earlier degenerate run (`tier2.qc.json: total_records: 0`). Every subsequent smoke iteration inherited the empty cache. The merge step concatenated tier1 (370K records) + tier2 (0 records); pgsc_calc's intersect against PGS000018's 1.7M sites yielded only the tiny PCA-overlap. The actual symptom (low match rate) was 4 layers downstream from the actual bug (silent empty cache). | Nuked the tier2 cache + added the **empty-cache guard**: `_count_vcf_records()` raises `BcftoolsError` if the bcftools pipe produces a header-only VCF. Applied to both `_force_genotype_tier1` + `_force_genotype_tier2`. | `coverage_fill.py:_count_vcf_records` + guard sites |
| **v16** | post-nuke (pre-guard rebuild) | rc=1 quickly | Ran on stale image — guard not yet baked. | Rebuild. | — |
| **v17** | post-guard, fresh Tier 2 | **Guard fired** ✓ — exit 1 with the actionable diagnostic. Tier 2 bcftools pipe genuinely produced 0 records, and the guard refused to cache the empty result (validating `INV-R002`). | **Underlying bug — allele-orientation mismatch.** `_extract_pgs_sites_from_scorefile` assumes `REF=other_allele, ALT=effect_allele`; `bcftools call --constrain alleles` rejects sites where this assumption is reversed vs the actual reference base. Manual probe at chr1:21806025: scorefile says `A,G` (other_allele=A, effect_allele=G) but the reference at that position is G → `The reference alleles are not compatible at chr1:21806025 .. A vs G`. **Fix is non-trivial** — needs per-site reference lookup via samtools faidx + orientation flip — and is its own follow-up (see F7 below). | — (deferred to F7) |

**Test coverage summary** (landed during smoke iterations, all in tree):

| Test | Asserts |
|------|---------|
| `test_compute_pgs_writes_nextflow_config_redirecting_tmpdir` | TMPDIR redirect + stageInMode='copy' in nextflow.config; `-c <config>` in argv |
| `test_compute_pgs_samplesheet_sampleset_has_no_period` | sampleset stripped of `.vcf` + `.gz` extensions |
| `test_merge_tier1_tier2_filters_to_autosomes_only` | merge pipe filters to chr1..chr22 (no chrX/chrY/chrM) |
| `test_force_genotype_tier1_refuses_to_cache_empty_vcf` | empty-cache guard for Tier 1 |
| `test_force_genotype_tier2_refuses_to_cache_empty_vcf` | empty-cache guard for Tier 2 + cites input site count in error |

Suite at **699 passed / 108 skipped / 0 failed** after the iteration work landed.

**Invariants the iterations earned**:

1. **`INV-R002` — Never Cache a Degenerate Result.** v15 was the textbook surfacing. A 0-record VCF cached forever poisons all downstream work; the diagnostic surfaces 4 layers downstream from the actual bug. The guard refuses to promote a degenerate result and raises with an actionable diagnostic ("ZERO output records ... NOT caching ... chr-prefix mismatch / build mismatch / ...").

2. **`INV-D008` — Copy-Stage for DooD-Spawning Pipelines.** v14 was the canonical case. Nextflow's default symlink staging dereferences to parent-container-local paths invisible to siblings. The fix (`process.stageInMode = 'copy'`) is the only DooD-safe staging for nextflow; analogous setting applies to other pipeline runners.

**Open question the user flagged after v10** (addressed in Slice 1.C of this plan):

> "INV-T001 captures the flag name (`--run_ancestry`) but not what KIND of value the flag accepts (tarball, not directory). My PgscCalcConventions dataclass missed the value-type semantic. The golden-argv.txt I wrote also encoded the wrong path shape. The discipline needs to be extended OR a follow-up plan needs to address tool-input-semantics specifically."

This plan's Slice 1.C addresses it: per-flag value-type descriptors in `PgscCalcConventions` (e.g., `run_ancestry_value_pattern = r".*\.tar\.zst$"`), with a unit test asserting the wrapper's argv `--run_ancestry` value matches the pattern. Catches the v10-class regression at unit-test time, not at smoke-time.

**Follow-ups carried forward** (not in this plan's scope; track for future plans):

- **F3** (from discipline plan): host doctor checks for colima resource budget (`vm_memory >= max_memory_cap_used + overhead`; `vm_data_disk_capacity >= heuristic`).
- **F4** (new): per-sample sex info via samplesheet `--psam` so chrX scoring can re-enable. Today autosomes-only loses some PRS signal for sex-stratified components.
- **F5** (from discipline plan): `bin/genomeclaw refs materialize --target prs_pca_sites` CLI subcommand.
- **F6** (from discipline plan): CI gate on `tools/pgsc_calc/probe.sh` when `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes.
- **F7** (NEW, surfaced by v17): **Allele-orientation fix in `_extract_pgs_sites_from_scorefile`**. The PGS Catalog `effect_allele` can be either the forward-strand REF or ALT relative to the reference fasta; pre-assigning `REF=other_allele` rejects every site where the assumption is wrong. Fix: use `samtools faidx` (or pysam's FastaFile) to look up the actual REF at each site + assign REF/ALT correctly (skip tri-allelic mismatches). Add a unit test that simulates orientation-mismatched scorefile rows + asserts the extractor produces orientation-correct (chrom, pos, REF, ALT) tuples. The empty-cache guard from this plan caught this at smoke-time; F7 catches it at extractor-time.

**Next steps** (this plan):
1. Slice 1.B: lift `INV-R002` + `INV-D008` into INVARIANTS.md (v1.13 → v1.14).
2. Slice 1.C: tighten `PgscCalcConventions` with value-type descriptors + add 2 unit tests.
3. Slice 1.D: 2 traceability rows in architecture.md.
4. Wait on smoke v17; record its outcome here + close the iteration ledger.

---

## 2026-05-20 — Phase 1 close-out

**All four slices landed in one pass while smoke v17 cooked.**

- **Slice 1.A** (iteration ledger): the v7–v17 table above + v17 outcome update + F7 follow-up added to the spec.
- **Slice 1.B** (INVARIANTS.md): v1.13 → v1.14; `INV-R002` (Never Cache a Degenerate Result) lifted under the INV-R section; `INV-D008` (Copy-Stage for DooD-Spawning Pipelines) lifted under the INV-D section; both rows added to the Invariant Index.
- **Slice 1.C** (PgscCalcConventions value-types): `run_ancestry_value_pattern = r".*\.tar\.zst$"` + `input_value_pattern = r".*\.csv$"` added to the dataclass; matching KEY=VALUE lines added to `tools/pgsc_calc/probe-output.txt`; 3 new unit tests in `test_pgsc_calc_conventions.py` (tarball-match, csv-match, wrapper-argv-loop-closure).
- **Slice 1.D** (architecture.md): 2 new traceability rows for INV-R002 + INV-D008; INV-T001 row annotated *(v1.12 / v1.14 tighten)*.

**Test suite**: 699 → **702 passed** / 108 skipped / 0 failed. ruff + mypy clean on touched files.

**Cross-reference grep**: 41 mentions of `INV-R002` + `INV-D008` across INVARIANTS.md, architecture.md, and the plan's 4 markdown files.

**Smoke v17 outcome** (recorded above in iteration ledger): guard fired ✓ — the actual root cause was the allele-orientation mismatch in `_extract_pgs_sites_from_scorefile` (F7). The guard worked as designed: surfaced the bug LOUDLY at smoke-time + refused to cache the empty result so future runs surface the same diagnostic until F7 lands. Without the guard, every subsequent smoke would have silently inherited a 0-record tier2.vcf.gz + the eventual symptom (low match rate) would have remained 4 layers downstream from the actual bug.

**Phase 1 status**: **COMPLETE**.

**Plan status**: this is a single-phase plan. Phase 1 close-out = plan close-out.

**Follow-ups carried forward** (out of this plan's scope; tracked above F3–F7):
- F3 host doctor checks for VM resource budget
- F4 sex-info handling for chrX scoring
- F5 `bin/genomeclaw refs materialize` CLI subcommand
- F6 CI gate on `tools/pgsc_calc/probe.sh` pin bumps
- **F7 allele-orientation fix in `_extract_pgs_sites_from_scorefile`** (NEW, blocking the user's actual `pgs_scores` row; needs its own small plan)

**Next session**: open the F7 plan + implement the per-site reference lookup. After F7 lands, smoke v18 should produce the actual `pgs_scores` row.
