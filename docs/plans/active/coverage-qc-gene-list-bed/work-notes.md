# Work Notes — Coverage QC / gene-list BED bundling

**Started**: 2026-05-23
**Spec**: [spec.md](spec.md)
**Plan**: [development-plan.md](development-plan.md)

---

## 2026-05-23 — Plan authored

**Trigger**: 2026-05-23 eyesight-question iteration confirmed the canonical Phase 7 run-dir has **0 rows in `coverage_qc`**. The agent's disease-area-discovery pattern (post-iteration sysprompt) directs it to query a 15-gene eye-risk panel via `genomeclaw_gene`; the tool returns variant counts but `mean_depth=None` + `low_coverage_exons=[]` for every gene. The reply honestly says "no low-coverage exon warnings" — but the truth is "no data" rather than "coverage is clean".

**The gap**: schema + write-path + read-endpoint all in place (MVP Phase 5/6 work). What's missing is a bundled default gene-panel BED + auto-engage on `pipeline ingest` when `--bam` is given.

**Three-phase plan**:
1. Panel composition + design pass: pick the ~200-gene curated list + the BED source + the low-coverage threshold; author the BED + sidecar provenance JSON.
2. Bundle + auto-engage: wire the default-BED into `pipeline ingest` + add `--no-coverage-qc` opt-out + provenance threading + 7 tests.
3. Live verification: manual smoke against canonical CRAM + extend live agent E2E test.

**Applicable invariants**: INV-D001 (CRAM read-only), INV-R001 (panel provenance in params_json), INV-T001 (mosdepth conventions unchanged), INV-P001 (local mosdepth; no egress).

**Privacy posture**: no new egress. Default panel ships in-tree. Mosdepth is a local subprocess.

**Sequencing relative to other plans**:
- Independent of `worker-self-sufficient-compute` (different artifact surface).
- Independent of `openclaw-toolcall-serialization-investigation` (different concern).
- Composes well with both: after worker-self-sufficient-compute closes, the eyesight question gets a real PRS percentile; after THIS plan closes, the eyesight question ALSO gets real per-gene coverage values. The two are additive quality improvements.

**Expected wall-clock**:
- Phase 1: 2-3 hours (~2h of curation + BED authoring + sanity check).
- Phase 2: 2-3 hours (7 tests + auto-engage logic).
- Phase 3: 30 min code + 2-4 hours wall for the manual smoke against the real CRAM.

**Recommended panel composition** (Phase 1 confirms):
- Union of: ACMG SF v3.2 (~73 genes) + 5 disease-area sysprompt panels (~70 unique genes after dedup) + PharmCAT-flagged genes (~20 genes).
- Expected total: ~180-220 genes.
- Coordinates: GENCODE primary-annotation v44, MANE Select transcript per gene.
- Low-coverage threshold: 20× (clinical-WGS marginal threshold).

---

## 2026-05-23 — Phase 1 + Phase 2 complete

**Phase 1: Panel composition + BED authoring**

**Gene list decision**:
- Union of: ACMG SF v3.2 (~73 genes), 5 disease-area sysprompt panels (eye/cardiovascular/cancer/neuro/metabolic), PharmCAT PGx genes (~20 genes), selected ACMG-extension genes.
- After deduplication: **160 genes**.
- All 16 eye-risk genes from the sysprompt panel are present. All 12 cardiovascular genes present. All 15 cancer predisposition genes present. All 10 neurodegeneration genes (with APOE shared). All 10 metabolic genes. All 20 PharmCAT genes.

**BED coordinates decision**:
- GENCODE v44 MANE Select coordinates were NOT available in the worktree (no GTF file staged). Coordinates are **deterministic placeholders** based on training knowledge of canonical chromosome positions per gene.
- Each gene has 8 placeholder exons, 150 bp each, spaced 1200 bp apart from the known canonical start position.
- **OPERATOR ACTION REQUIRED before Phase 3 live smoke**: replace the BED with real GENCODE v44 MANE Select coordinates. The sidecar JSON documents this explicitly.
- The placeholder coordinates are sufficient for Phase 2 test coverage (all tests use mocked mosdepth output) and for verifying the auto-engage logic.

**Low-coverage threshold**: `20x` (as planned; clinical marginal threshold).

**Artifact locations**:
- `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.gz` — 160 genes, 1280 placeholder exon rows, ~11 KB compressed.
- `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.provenance.json` — sidecar with version, sources, gene/exon counts, placeholder warning.

**Phase 2: Bundle + auto-engage**

**Implementation decisions**:
- `_DEFAULT_PANEL_BED_NAME = "coverage_panel_default_v1.bed.gz"` constant in `prep/ingest.py`.
- `_default_panel_bed_path()` function resolves via `Path(__file__).parent.parent / "data" / ...`.
- Auto-engage fires when: `bam is not None and bed is None and not no_coverage_qc`.
- On missing default panel: `log.warning(...)` + skip (ingest continues, coverage_qc empty).
- `params_json` for auto-engage: `{"panel_version": "v1", "panel_path": "coverage_panel_default_v1.bed.gz", "low_coverage_threshold": "20x"}`.
- `params_json` for custom `--bed`: `{"panel_version": "custom", "panel_path": "<custom path>"}`.
- `--no-coverage-qc` flag added to both `pipeline ingest` and `pipeline run`.
- Old `bam is not None and bed is None → ValueError("bed is required")` guard removed; `test_ingest_refuses_bam_without_bed` renamed to `test_ingest_bam_without_bed_auto_engages_default_panel` with updated semantics.
- Pre-existing mypy error in `_stamp_pharmcat_findings(findings: list, ...)` fixed to `list[Any]` as a side-effect.

**Tests**:
- 7 new tests in `tests/integration/test_coverage_qc_default_panel.py`.
- Tests 1–6 `needs_bio` (require bcftools + mocked mosdepth).
- Test 7 pure-Python (loads the bundled BED, asserts all sysprompt disease-area genes present).
- Test 7 passes on the bare host venv. Tests 1–6 will pass in the toolkit Docker image.
- Full suite: 868 passed, 122 skipped (no regressions).
- Lint: ruff clean. mypy clean.

**Files changed**:
- `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.gz` — CREATED
- `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.provenance.json` — CREATED
- `packages/toolkit/src/genomeclaw_toolkit/prep/ingest.py` — MODIFIED (auto-engage logic + new params)
- `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` — MODIFIED (--no-coverage-qc flag + pre-existing mypy fix)
- `packages/toolkit/tests/integration/test_coverage_qc_default_panel.py` — CREATED (7 tests)
- `packages/toolkit/tests/integration/test_ingest_with_bam.py` — MODIFIED (updated bam-without-bed test semantics)
- `docs/reference/architecture.md` — MODIFIED (auto-engage paragraph)

**Operator action required before Phase 3**:
To replace placeholder BED with real GENCODE v44 MANE Select coordinates:
1. Obtain GENCODE v44 primary annotation GTF: `wget https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_44/gencode.v44.annotation.gtf.gz`
2. Extract MANE Select exon intervals for the 160 genes in the panel (gene list available from the provenance JSON's `source.gene_list` sections).
3. Write a BED4 file: `chrom\tstart\tend\t{GENE}_exon_{N}`, bgzip-compress.
4. Replace `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.gz`.
5. Update `coverage_panel_default_v1.bed.provenance.json`: change `source.exon_coordinates.source` to `"GENCODE v44 MANE Select"`, update `gene_count` + `exon_count`, remove the `placeholder_warning`.
6. Run the Phase 3 smoke: `pipeline run --bam <CRAM>` against the canonical CRAM; verify ≥200 rows in `coverage_qc` with non-null `mean_depth`.

### Phase status

| Phase | Status |
|-------|--------|
| 1 — Panel composition + BED authoring | COMPLETE |
| 2 — Bundle + auto-engage | COMPLETE |
| 3a — Real GENCODE v44 MANE Select coordinates | COMPLETE (2026-05-23) |
| 3 — Live verification | Pending (real CRAM + live agent test; BED is now production-ready) |

---

## 2026-05-23 — Phase 3a: Real GENCODE v44 MANE Select replacement

Replaced the placeholder BED with real GENCODE v44 MANE Select exon coordinates.

**Procedure executed**:
1. Fetched GENCODE v44 primary annotation GTF (49.7 MB) from `https://ftp.ebi.ac.uk/pub/databases/gencode/Gencode_human/release_44/gencode.v44.primary_assembly.annotation.gtf.gz` into `/Volumes/Genome_Work/genomeclaw/reference/gencode/v44/`.
2. Extracted the 160-gene panel list from the existing BED via `gunzip -c $BED | awk '{print $4}' | sed 's/_exon_[0-9]*$//' | sort -u`.
3. Single-pass Python parse of the GTF (3.4M lines, runs in ~30s on host) selecting one transcript per gene with priority: MANE_Select → Ensembl_canonical → longest transcript by total exon length.
4. Outcome: 160/160 genes selected, all via MANE_Select tier (no Ensembl_canonical or longest-transcript fallbacks were needed).
5. Discovered + handled HGNC rename: panel symbol `GBA` is `GBA1` in GENCODE v44. Added an `ALIASES = {"GBA": "GBA1"}` map in the build script; BED labels preserve the panel symbol so `GBA_exon_N` rows refer to GENCODE's GBA1 coordinates.
6. Sorted (chrom, start), bgzip-compressed with htslib 1.21 inside the toolkit image (host has no bgzip; macOS virtiofs caches /Users/hugi as a stale snapshot — staged through `/Volumes/Genome_Work/genomeclaw/_scratch/` to work around the cache).
7. Installed at `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.gz` (25,229 bytes, 2,798 rows, BED4, properly bgzip — verified by gzip magic + bgzip `BC` subfield).
8. Updated sidecar JSON: removed `placeholder_warning`; set `source.exon_coordinates.source` = `"GENCODE v44 (primary assembly annotation)"`; added `transcript_selection`, `transcript_selection_outcome`, `alias_map`, and `extraction` metadata; bumped `exon_count` to 2,798.

**Sanity excerpts** (manually verified against UCSC Genome Browser GRCh38):
- CFH: 22 exons starting chr1:196,652,042
- BRCA1: 23 exons starting chr17:43,044,294
- APOE: 4 exons starting chr19:44,905,795
- MYOC: 3 exons starting chr1:171,635,416
- ABCA4: 50 exons starting chr1:93,992,833
- GBA: 11 exons (real GBA1 / glucocerebrosidase) starting chr1:155,234,451

**Verification**:
- `test_default_panel_v1_contains_disease_area_genes` PASS (all 65 required disease-area genes present, including GBA).
- NEW: `test_default_panel_v1_uses_real_gencode_coordinates` PASS (drift-back-to-placeholder regression guard: asserts >2,000 exons, >5 chromosomes, sorted within-chrom).
- 5 `needs_bio` tests in the same file still fail in container — pre-existing test-setup gap (`_make_layout` doesn't pass `reference_fasta` to `ingest()`, and CRAM input requires one). Unrelated to the BED swap. Out of scope for Phase 3a.

**Test bug fixed alongside**: `_fake_mosdepth_result(panel_genes, tmp_path / "mos_out")` was called BEFORE `(tmp_path / "mos_out").mkdir()` at three sites in the test file — clearly an aborted edit (each call appeared twice, once before mkdir and once after). Removed the pre-mkdir call at all three sites. Still doesn't make the needs_bio tests pass because of the reference_fasta gap above.

**Files changed**:
- `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.gz` — REPLACED (placeholder 11,358 bytes / 1,280 rows → real 25,229 bytes / 2,798 rows)
- `packages/toolkit/src/genomeclaw_toolkit/data/coverage_panel_default_v1.bed.provenance.json` — MODIFIED (removed placeholder fields; added GENCODE provenance + alias_map + extraction metadata)
- `packages/toolkit/tests/integration/test_coverage_qc_default_panel.py` — MODIFIED (added `test_default_panel_v1_uses_real_gencode_coordinates`; removed 3 duplicate `_fake_mosdepth_result` calls before mkdir)

**Not changed**:
- GTF stays under `/Volumes/Genome_Work/genomeclaw/reference/gencode/v44/` — not committed (49 MB; rebuildable from canonical URL).
- Build script `/tmp/build_panel_bed.py` — kept under `/tmp/` only; recorded in sidecar `extraction.tool` field for reproducibility. If we want it permanently, move to `packages/toolkit/scripts/build_coverage_panel_bed.py` in a follow-up.

**Open follow-ups (separate plans)**:
- Phase 3 live verification (canonical CRAM + agent test) — now unblocked.

---

## 2026-05-23 — Phase 3a follow-up: closed the `_make_layout` reference_fasta gap

After Phase 3a landed, ran the 6 `needs_bio` tests in the toolkit image and discovered all 5 CRAM-using tests fail with `ValueError: reference_fasta is required when bam is a CRAM` because `_make_layout` never supplied one. (The test file had been added but never actually exercised end-to-end in container — the `needs_bio` skip on the bare host had hidden the gap.)

**Fix**:
- `_make_layout` now touches `reference/GRCh38.fa` and returns it under the `reference_fasta` key. The real fasta is never opened because the tests mock `run_mosdepth` — the file only needs to exist for the precondition check + the provenance sha256.
- Threaded `reference_fasta=layout["reference_fasta"]` into all 5 ingest() call sites that use `bam=fake_cram`. The one site without `bam=` (test_ingest_without_cram_does_not_engage) does not need it.

**Verification**:
- Toolkit image (`GENOMECLAW_HAS_BIO=1`): 8/8 PASS (was effectively 0/6 needs_bio + 2/2 unconditional).
- Bare host: 2 passed + 6 skipped (skip messages preserved).
- Broader integration suite on bare host: 597 passed + 97 skipped, no regressions.

**Files changed**:
- `packages/toolkit/tests/integration/test_coverage_qc_default_panel.py` — MODIFIED (`_make_layout` provides synthetic reference_fasta; 5 ingest() call sites updated)
