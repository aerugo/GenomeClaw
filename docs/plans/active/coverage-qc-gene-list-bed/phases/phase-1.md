# Phase 1 — Panel composition + design pass

**Status**: COMPLETE
**Started**: 2026-05-23
**Completed**: 2026-05-23
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Pick the canonical default panel BED's composition, source the exon coordinates, set the low-coverage threshold, and produce the artifact at `packages/toolkit/data/coverage_panel_default_v1.bed.gz` + sidecar `coverage_panel_default_v1.bed.provenance.json`. Output: the BED asset + a documented rationale in this plan's `work-notes.md`.

## Scope Boundaries

- **In scope**: gene-list selection; exon-coordinates source; BED + provenance JSON authoring; documentation of the curation rationale.
- **Out of scope**: ingest wiring (Phase 2); live verification (Phase 3); panel versioning beyond v1.

## Invariants enforced in this phase

- None directly. The asset is provenance-bearing (sidecar JSON records source + curation date); Phase 2's tests assert the provenance lands in `params_json`.

---

## Steps

### 1.1 — Gene list composition

Build the union of:
- **ACMG SF v3.2 list** — 73 secondary-findings-actionable genes. The canonical clinically-validated list.
- **Disease-area sysprompt panels** — from `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`'s "Canonical disease-area panels" table:
  - Eyesight: CFH, ARMS2, HTRA1, C2, C3, CFB, ABCA4, USH2A, RPE65, RHO, RPGR, MYOC, OPTN, TBK1, CYP1B1, TIMP3 (16 genes)
  - Cardiovascular: LDLR, APOB, PCSK9, APOE, LPA, MYH7, MYBPC3, TNNT2, KCNQ1, KCNH2, SCN5A, FBN1 (12 genes)
  - Cancer predisposition: BRCA1, BRCA2, TP53, MLH1, MSH2, MSH6, PMS2, APC, MUTYH, CDH1, PTEN, STK11, PALB2, ATM, CHEK2 (15 genes)
  - Neurodegeneration: APP, PSEN1, PSEN2, APOE, MAPT, GRN, C9orf72, LRRK2, SNCA, GBA, HTT (11 genes)
  - Metabolic: TCF7L2, HNF1A, HNF4A, GCK, MC4R, FTO, PPARG, KCNJ11, GLP1R, IRS1 (10 genes)
- **PharmCAT-flagged pharmacogenomic gene list** — the genes the existing `pharmcat` subcommand outputs findings for (~20 genes).
- **Common high-impact safety-net** — any gene appearing in ≥2 of the above lists is already covered; add any single-list "common-ask" genes if missing (likely a small handful).

Expected total after dedup: ~180-220 genes.

Record the dedup'd list in the plan's `work-notes.md` as a Python-readable list + a per-gene rationale (which source(s) included it).

### 1.2 — Exon coordinates source

Three options:
- **GENCODE primary-annotation v44**: rich, well-versioned, matches modern clinical pipelines. Coordinates available via the gtf file the toolkit image already ships (or fetches via `refs fetch --source gencode`).
- **RefSeq Curated**: more conservative, fewer transcripts; older convention.
- **Ensembl primary**: same coordinates as GENCODE primary; just a different source path.

**Recommendation**: GENCODE v44 primary-annotation, restricted to MANE Select transcripts where MANE exists. MANE Select gives one canonical transcript per gene; for genes outside MANE (rare), fall back to the GENCODE primary "canonical" tag.

This produces one row per exon, with chromosome / start / end / gene-symbol / exon-index columns. Coordinates are GRCh38 (matches the rest of GenomeClaw's reference).

### 1.3 — Low-coverage threshold

`mosdepth --thresholds <T>` flags exons whose mean depth falls below T. Options:
- `10×`: classic shallow-WGS warning threshold; surfaces only the worst exons.
- `20×`: clinical-WGS "marginal" threshold; surfaces ~5-10% of exons on a 30× nominal-coverage CRAM.
- `30×`: nominal-coverage threshold; surfaces "below average" exons (lots of noise).

**Recommendation**: `20×` as the primary threshold. The `params_json` records the threshold for provenance + future operators can re-run with a different one.

### 1.4 — Author the BED + provenance JSON

```
packages/toolkit/data/
├── coverage_panel_default_v1.bed.gz                   # bgzip-compressed BED, one row per exon
└── coverage_panel_default_v1.bed.provenance.json     # sidecar
```

BED row shape (GRCh38, 0-based BED4):
```
chr1  196659237  196659380  CFH_exon_1
chr1  196693814  196693989  CFH_exon_2
...
```

Provenance JSON shape:
```json
{
  "version": "v1",
  "created_at": "2026-05-23",
  "source": {
    "gene_list": [
      {"source": "ACMG_SF_v3.2", "url": "https://..."},
      {"source": "GenomeClaw disease-area sysprompt panels", "ref": "agent-system-prompt.md@<commit>"},
      {"source": "PharmCAT-flagged genes", "ref": "<list>"}
    ],
    "exon_coordinates": {
      "source": "GENCODE primary-annotation v44",
      "transcript_filter": "MANE Select where present, else GENCODE canonical",
      "build": "GRCh38"
    }
  },
  "gene_count": 207,
  "exon_count": 2143,
  "low_coverage_threshold_default": "20x",
  "curation_notes": "..."
}
```

### 1.5 — Author the BED (the actual data step)

This is the data-engineering step. Approach:
- Pull GENCODE v44 primary-annotation GTF (the toolkit image likely has it cached; otherwise `refs fetch`).
- Filter to MANE Select transcripts (`tag "MANE_Select"`).
- Filter to the gene-list dedup'd in 1.1.
- For genes missing MANE Select, fall back to the GENCODE canonical transcript (`tag "Ensembl_canonical"`).
- Extract exon coordinates; bgzip-compress; write the sidecar JSON.
- Sanity-check: ~200 genes × ~8-12 exons each = ~1600-2400 BED rows. File should be <500 KB compressed.

Tools needed: `gffutils` or `gtf` Python library OR `awk`/`grep` against the GTF directly. Both are available on the toolkit image.

### 1.6 — Record rationale

In `work-notes.md`, record:
- The gene list (deduplicated).
- Per-gene source attribution (1+ of: ACMG, disease-area sysprompt eye/cardio/cancer/neuro/metabolic, PharmCAT).
- The chosen exon-coordinates source + transcript filter.
- The chosen low-coverage threshold.
- File sizes + row counts.
- Sanity-check excerpts (a few rows for CFH, BRCA1, APOE).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/data/coverage_panel_default_v1.bed.gz` | CREATE | The bundled panel BED |
| `packages/toolkit/data/coverage_panel_default_v1.bed.provenance.json` | CREATE | Sidecar provenance JSON |
| `docs/plans/active/coverage-qc-gene-list-bed/work-notes.md` | MODIFY | Phase 1 design-pass + curation rationale |

No production code changes.

---

## Verification

```bash
# Sanity check the panel
zcat packages/toolkit/data/coverage_panel_default_v1.bed.gz | head -5
zcat packages/toolkit/data/coverage_panel_default_v1.bed.gz | awk '{print $4}' | sed 's/_exon.*//' | sort -u | wc -l   # gene count
zcat packages/toolkit/data/coverage_panel_default_v1.bed.gz | wc -l   # exon count

# Sidecar JSON valid + gene_count matches
jq . packages/toolkit/data/coverage_panel_default_v1.bed.provenance.json
```

No automated tests in this phase. The asset is the deliverable; Phase 2's tests verify it integrates correctly.

---

## Completion Criteria

- [ ] Gene list composed + recorded in work-notes.
- [ ] Exon-coordinates source picked + recorded.
- [ ] Low-coverage threshold picked + recorded.
- [ ] BED file checked in at the canonical path; ~200 genes; ~2000 exons; <500 KB.
- [ ] Provenance JSON sidecar matches BED's gene/exon counts.
- [ ] Sanity-check excerpts (CFH, BRCA1, APOE) verified non-empty + on correct chromosomes.
- [ ] `work-notes.md` carries the design-pass block.

## Next

[Phase 2 — Bundle + auto-engage](phase-2.md).
