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

### Next step

Surface the plan to the user for sign-off. Phase 1 starts after sign-off.
