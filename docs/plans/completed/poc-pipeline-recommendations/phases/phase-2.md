# Phase 2: Architecture + INVARIANTS

**Status**: Complete
**Started**: 2026-05-08
**Completed**: 2026-05-08
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Propagate the Q5–Q10 decisions (now landed in `mvp/spec.md` per Phase 1) into the two reference documents that codify the system shape: `docs/reference/architecture.md` (components, endpoints, tool table, data layout, network topology, invariant-traceability table) and `docs/reference/INVARIANTS.md` (INV-C001 v1.5 — recognize `reference/curated_notes/` as a calibration surface). After Phase 2, the architecture is internally consistent against the recommendations report; subsequent phases of this plan (grand-plan, user-stories, MVP dev-plan, MVP phase-2) can cite the architecture as the source of truth for component shape and INVARIANTS for the curated-notes recognition.

## Scope Boundaries

- **In scope**:
  - `docs/reference/architecture.md` — Component 1 description (pipeline tool list), Component 2 endpoint list, Component 3 plugin tool table, layered diagram, Repo layout, Data layout, Network topology, "Why this shape — invariant traceability" table.
  - `docs/reference/INVARIANTS.md` — version bump (v1.4 → v1.5), Last Updated date stamp (2026-05-08), INV-C001 Requirements + "Where it applies" sections, Invariant Index table preserved.
  - `docs/plans/active/poc-pipeline-recommendations/work-notes.md` — Phase 2 progress block, doc-checks RED → GREEN, INVARIANTS diff summary, sections-touched summary.
  - `docs/plans/active/poc-pipeline-recommendations/phases/phase-3.md` — authored at end of Phase 2 (Grand plan + user stories detailed plan).
- **Out of scope**:
  - `docs/reference/grand-plan.md` — Phase 3.
  - `docs/reference/user-stories.md` — Phase 3.
  - `docs/plans/active/mvp/*` — Phase 4 (and Phase 1 already covered the spec).
  - Authoring the actual curated-note files under `reference/curated_notes/<gene>.md`. **Those land in MVP Phase 6.** Phase 2 documents the directory's existence, naming convention, and resolver path; the notes themselves are user-authored content.
  - Any code under `packages/`. Strictly no code in this phase.
  - Promoting a new INV-xxx. INV-C001 v1.5 is a clarifying revision; no new invariant lands.

## Invariants Enforced in This Phase

This phase edits the canonical INVARIANTS doc directly, plus the architecture doc that traces invariants to enforcement points. The phase's primary discipline is **no canonical INV-xxx is weakened**.

- **INV-C001** — INVARIANTS.md INV-C001 Requirements gains a bullet recognizing `reference/curated_notes/<gene>.md` as the primary calibration surface for lifestyle findings; "Where it applies" lists curated-notes editing as in-scope (so the privacy-safety-reviewer agent reviews it). The structural fields (`category`, `clinical_escalation`, `evidence_quality`) and the four-category schema are preserved verbatim. Over-deferral discipline preserved verbatim. **Strengthened, not weakened.**
- **INV-E001** — Architecture's invariant-traceability table gains an explicit recognition of `gene_note:<gene>` and `topic:<topic>` as evidence-reference forms accepted by the host service evidence resolver. INVARIANTS.md INV-E001 Requirements text is unchanged (the rule already permits internal record IDs); the architecture-side recognition is what carries the day.
- **INV-D001 / INV-D002** — Architecture Component 1 description names `mosdepth`, `Cyrius`, `bcftools stats`, and `pgsc_calc` as host-side tools that read source artifacts read-only. Sandbox image content is unchanged.
- **INV-P001 / INV-P002** — Architecture Network topology gains a third egress path (PGS Catalog HTTPS, host-side, deliberate, opt-in). Component 2 endpoint list and Component 3 plugin tool table both encode `output_class: summary` defaults for the two new tools.
- **INV-R001** — Architecture Data layout enumerates the new derived locations (`derived/<run-id>/coverage_qc.duckdb` or table; `derived/<run-id>/pgs_scores.duckdb` or table; `derived/<run-id>/cyp2d6_diplotype.json`); each inherits the seven canonical provenance columns.

---

## TDD Steps

### Step 2.1 — RED: Write Failing Doc-Checks

Capture the pre-edit state of `architecture.md` and `INVARIANTS.md` so the GREEN state has something to compare against.

**Doc-check cases**:

**Architecture (`docs/reference/architecture.md`)**:

1. `check_arch_component1_lists_mosdepth` — `grep "mosdepth" docs/reference/architecture.md` should match (after edit). RED before edit: 0.
2. `check_arch_component1_lists_cyrius` — `grep "Cyrius" docs/reference/architecture.md` should match (after edit). RED: 0.
3. `check_arch_component1_lists_bcftools_stats` — `grep "bcftools stats" docs/reference/architecture.md` should match (after edit). RED: 0.
4. `check_arch_component1_lists_pgsc_calc` — `grep "pgsc_calc" docs/reference/architecture.md` should match (after edit). RED: 0.
5. `check_arch_component1_lists_vep_stack` — each of `VEP`, `LOFTEE`, `AlphaMissense`, `SpliceAI`, `vcfanno`, `MANE Select` appears (after edit). RED: only `VEP` is present (in deferred-questions cross-reference).
6. `check_arch_component2_lists_gene_endpoint` — `grep "/v1/gene/{symbol}" docs/reference/architecture.md` should match (after edit). RED: 0.
7. `check_arch_component2_lists_pgs_endpoint` — `grep "/v1/pgs/{trait}" docs/reference/architecture.md` should match (after edit). RED: 0.
8. `check_arch_plugin_tool_table_six_rows` — the plugin tool table (Component 3 / layered diagram tool list) lists exactly six tools: `genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_gene`, `genomeclaw_pgs`. RED: four tools.
9. `check_arch_data_layout_curated_notes` — `grep "reference/curated_notes/" docs/reference/architecture.md` should match (after edit). RED: 0.
10. `check_arch_data_layout_coverage_qc` — `grep "coverage_qc" docs/reference/architecture.md` should match (after edit). RED: 0.
11. `check_arch_data_layout_pgs_scores` — `grep "pgs_scores" docs/reference/architecture.md` should match (after edit). RED: 0.
12. `check_arch_data_layout_cyp2d6_diplotype` — `grep "cyp2d6_diplotype" docs/reference/architecture.md` should match (after edit). RED: 0.
13. `check_arch_network_topology_pgs_catalog` — `grep -i "PGS Catalog" docs/reference/architecture.md` should match (after edit). RED: 0.
14. `check_arch_invariant_table_gene_note` — `grep "gene_note" docs/reference/architecture.md` should match (after edit) in the invariant-traceability table. RED: 0.
15. `check_arch_invariant_table_topic_hard_genes` — `grep "topic:hard-genes" docs/reference/architecture.md` should match (after edit). RED: 0.

**INVARIANTS (`docs/reference/INVARIANTS.md`)**:

16. `check_inv_version_v15` — `grep "Version.*v1\\.5" docs/reference/INVARIANTS.md` (or `Version.*1\.5`) should match (after edit). RED: matches `1.4` instead.
17. `check_inv_last_updated_2026_05_08` — `grep "Last Updated.*2026-05-08" docs/reference/INVARIANTS.md` should match (after edit). RED: matches `2026-05-06`.
18. `check_inv_c001_curated_notes_in_requirements` — `grep "curated_notes" docs/reference/INVARIANTS.md` should match in INV-C001's Requirements section (after edit). RED: 0.
19. `check_inv_c001_where_it_applies_curated_notes` — `grep -A3 "Where it applies" docs/reference/INVARIANTS.md` (in INV-C001) mentions `reference/curated_notes/` (after edit). RED: 0.
20. `check_inv_index_seven_rows` — the Invariant Index table at the end of `INVARIANTS.md` still lists exactly seven canonical IDs. RED: seven (preserved).

**Procedure**:

```bash
# RED — capture pre-edit grep state
echo "=== Architecture RED ==="
for term in "mosdepth" "Cyrius" "bcftools stats" "pgsc_calc" "LOFTEE" "AlphaMissense" "SpliceAI" "MANE Select" \
            "/v1/gene/{symbol}" "/v1/pgs/{trait}" "genomeclaw_gene" "genomeclaw_pgs" \
            "reference/curated_notes/" "coverage_qc" "pgs_scores" "cyp2d6_diplotype" \
            "PGS Catalog" "gene_note" "topic:hard-genes"; do
  printf "%-30s " "$term:"; grep -c -i "$term" docs/reference/architecture.md
done

echo "=== INVARIANTS RED ==="
for term in "Version.*1\\.5" "Last Updated.*2026-05-08" "curated_notes"; do
  printf "%-30s " "$term:"; grep -c -E "$term" docs/reference/INVARIANTS.md
done

echo "=== Tool count in architecture ==="
# Count rows in the plugin tool table; expected RED: 4
```

After running, paste the RED state into `work-notes.md` Phase 2 block.

### Step 2.2 — GREEN: Edit `architecture.md` and `INVARIANTS.md`

The edits are bigger than Phase 1 because `architecture.md` is more structurally substantive. Suggested edit sequence (10 separate `Edit` calls):

**Edit A1 — Component 1 description**: append the four new tools to the responsibility paragraph and the subcommand surface mention.

Locate the existing paragraph under `### 1. Host pipeline CLI — \`genomeclaw-prep\``. Update the **Implementation** and **Responsibility** lines:

```markdown
**Implementation**: Python (driven by ecosystem: `cyvcf2`, `pysam`, DuckDB Python bindings, PharmCAT). Wraps host-installed bioinformatics tools.

**Responsibility**: ingest → normalize → filter → annotate → materialize, plus per-Q7 `mosdepth` (per-gene mean coverage), per-Q5 **VEP + LOFTEE + AlphaMissense + SpliceAI + vcfanno** annotation (with **MANE Select** transcript pinning; HGVSc/HGVSp emitted server-side), per-Q6 **Cyrius** (CYP2D6 diplotype call from BAM/CRAM, fed into PharmCAT's outside-call interface), per-Q5 `bcftools stats` summary into `manifest.json`, and per-Q8 `pgsc_calc` (PRS computation against PGS Catalog scoring weights). Reads from `/mnt/genomeclaw/raw/` and `/mnt/genomeclaw/reference/`; writes to `/mnt/genomeclaw/derived/<run-id>/` with full provenance columns.

**Why host-side**: `INV-D002`. Bioinformatics tools are heavy, host-native, and must never be reachable from the agent.
```

**Edit A2 — Component 2 endpoints**: append the two new endpoints to the endpoint list. Locate the bullet list under `### 2. Host service — \`genomeclaw-service\``:

After the existing `GET /v1/provenance/{run-id}` bullet, before the `(Per MVP spec Q3 …)` paragraph, insert:

```markdown
- `GET /v1/gene/{symbol}` — gene-level facts (per Q7): `{top_user_variants, gene_loeuf, omim_disease, omim_inheritance, mean_coverage, low_coverage_exons}`. `mean_coverage` is a scalar (number, scaled to 1× depth); `low_coverage_exons` is a list of exon IDs whose mean depth fell below a configurable threshold (default 10×). Defaults to active run.
- `GET /v1/pgs/{trait}` — PRS results (per Q8): `{percentile_in_user_ancestry, raw_score, source_pgs_id, study_population, calibration_warning}`. `trait` is one of the three initial traits (CAD, T2D, breast or prostate cancer in v0). Defaults to active run.
```

Then update the existing endpoint-recap paragraph immediately above to mention the new endpoints in the same MVP-spec-Q3 paragraph if appropriate (no — keep Q3 paragraph as-is since it only affects `/v1/report`).

**Evidence resolver clarification**: under the existing `/v1/evidence/{ref}` bullet, append a sub-bullet:

```markdown
  - Recognized non-variant-keyed reference forms (per Q9 / `INV-E001`): `gene_note:<gene>` (resolves to `reference/curated_notes/<gene>.md`), `topic:<topic>` (resolves to `reference/curated_notes/topics/<topic>.md`; e.g., `topic:hard-genes`).
```

**Edit A3 — Component 3 / plugin tool table**: locate the layered diagram's tool list and the `### 3. NemoClaw plugin` description.

In the Layered diagram (mermaid `Agent` block), replace:

```text
Tools registered:<br/>genomeclaw_status, genomeclaw_findings,<br/>genomeclaw_variant, genomeclaw_evidence
```

with:

```text
Tools registered (6):<br/>genomeclaw_status, genomeclaw_findings,<br/>genomeclaw_variant, genomeclaw_evidence,<br/>genomeclaw_gene, genomeclaw_pgs
```

In Component 3's text, update the responsibility line that mentions "registers agent-callable commands" to make the count explicit ("six tools per Q7/Q8").

**Edit A4 — Repo layout / data layout**: extend the existing data-layout block.

Replace the existing data-layout block:

```text
/mnt/genomeclaw/
├── raw/         (RO — Nebula FASTQ/BAM/VCF; chmod-enforced read-only)
├── reference/   (RO at runtime; written only by `genomeclaw-prep fetch`)
└── derived/     (RW; pipeline writes <run-id>/ here)
    └── <run-id>/
        ├── manifest.json             (run identity, schema version, tool versions)
        ├── variants.duckdb
        ├── annotations/
        ├── evidence/
        └── provenance.json
```

with:

```text
/mnt/genomeclaw/
├── raw/         (RO — Nebula FASTQ/BAM/CRAM/VCF; chmod-enforced read-only)
├── reference/   (RO at runtime; written only by `genomeclaw-prep fetch` and `pgsc_calc fetch-weights`)
│   ├── grch38/
│   ├── clinvar/
│   ├── gnomad/
│   ├── dbsnp/
│   ├── vep_cache/                       (Q5 — VEP + LOFTEE + AlphaMissense + SpliceAI data files)
│   ├── pgs_catalog/                     (Q8 — scoring weights for the three initial traits)
│   └── curated_notes/                   (Q9 — host-side, user-authored markdown notes)
│       ├── lct.md
│       ├── cyp1a2.md
│       ├── adora2a.md
│       ├── aldh2.md
│       ├── adh1b.md
│       ├── apoe.md
│       ├── mthfr.md
│       └── topics/
│           └── hard-genes.md            (Q7 companion — systematic short-read-WGS blind-spot caveat)
└── derived/     (RW; pipeline writes <run-id>/ here)
    └── <run-id>/
        ├── manifest.json                (run identity, schema version, tool versions, qc.bcftools_stats per Q5)
        ├── variants.duckdb              (canonical variants table + Q5 annotation columns + coverage_qc + pgs_scores tables)
        ├── cyp2d6_diplotype.json        (Q6 — Cyrius diplotype, consumed by PharmCAT outside-call)
        ├── annotations/
        ├── evidence/
        └── provenance.json
```

(Whether `coverage_qc` and `pgs_scores` are separate `.duckdb` files or tables inside `variants.duckdb` is a Phase-4/6 implementation choice; the data-layout block leaves the option open with the parenthetical.)

**Edit A5 — Network topology**: extend the existing network-topology section to include the PGS Catalog egress path.

Locate the "Two paths cross trust boundaries" paragraph; rewrite to "Three paths" and append:

```markdown
3. **PGS Catalog scoring weights fetch** (host → catalog): `pgsc_calc fetch-weights` → `https://www.pgscatalog.org/...` (HTTPS). Host-side, deliberate, opt-in only — the user invokes the subcommand once per added trait. No genomic data traverses this boundary; only PGS scoring weights flow inbound. Same discipline as `genomeclaw-prep fetch --source clinvar`.
```

**Edit A6 — Invariant traceability table**: extend the table to record the new invariant-enforcement paths.

Replace the existing INV-E001 row:

```markdown
| `INV-E001` | The host service binds every emitted finding/observation to an evidence reference; the plugin forwards the reference verbatim. |
```

with:

```markdown
| `INV-E001` | The host service binds every emitted finding/observation to an evidence reference; the plugin forwards the reference verbatim. The evidence resolver accepts variant-keyed references (ClinVar IDs, gnomAD records, PMIDs) **and** non-variant-keyed references: `gene_note:<gene>` (resolves to `reference/curated_notes/<gene>.md` per Q9) and `topic:<topic>` (resolves to `reference/curated_notes/topics/<topic>.md`; e.g., `topic:hard-genes` per Q7). |
```

Replace the existing INV-P002 row to mention the new tool count and PGS Catalog path:

```markdown
| `INV-P002` | Three enforcement layers: host service shaping, plugin re-shaping, OpenShell policy + SSRF guard. Six plugin tools (per Q7/Q8) each carry an `output_class` declaration; default is `summary`, which is what `genomeclaw_gene` and `genomeclaw_pgs` ship with. The plugin's binary is policy-denied any host or port other than the configured host service. The PGS Catalog fetch path (per Q8) is host-side and deliberate, not subject to the sandbox policy preset. |
```

Replace the existing INV-C001 row to include curated-notes:

```markdown
| `INV-C001` | Report tools render clinical-escalation markers from finding records; the host service's finding schema includes the marker as a structural field. Lifestyle findings cite a `gene_note:<gene>` evidence reference (per Q9); editing a curated note is a user-facing-copy change reviewed by the privacy-safety-reviewer agent per `INV-C001` v1.5. |
```

**Edit I1 — INVARIANTS version + Last Updated**: at the top of the doc.

Replace:

```markdown
**Status**: Living document
**Version**: 1.4
**Last Updated**: 2026-05-06
```

with:

```markdown
**Status**: Living document
**Version**: 1.5
**Last Updated**: 2026-05-08
```

**Edit I2 — INV-C001 Requirements**: append a bullet recognizing curated notes.

Locate the **Requirements** section under INV-C001. After the existing bullet about `evidence_quality` field, append:

```markdown
- **Curated lifestyle calibration via `reference/curated_notes/`**: lifestyle findings may cite a `gene_note:<gene>` evidence reference resolving to a host-side, user-authored markdown note (per [MVP spec Q9](../plans/active/mvp/spec.md#q9--lifestyle-calibration-via-referencecurated_notes-gene-shortlist-lct-cyp1a2-adora2a-aldh2-adh1b-apoe-mthfr)). The note carries the project owner's calibrated framing of the variant's effect, evidence quality, and any disclosure language. The structured `evidence_quality` field above remains in the schema for future-proofing but is **not the primary calibration surface** in v0; the agent composes lifestyle responses from the user's variant call plus the curated note's framing, in the user's voice. This pattern is uniquely well-suited to single-user systems and uniquely poorly-suited to multi-user systems.
```

**Edit I3 — INV-C001 "Where it applies"**: add a bullet listing curated-notes editing.

Locate the **Where it applies** section under INV-C001. After the existing bullets (agent-rendered prose, plugin tool descriptions, finding schema, agent prompt templates), append:

```markdown
- The `reference/curated_notes/<gene>.md` and `reference/curated_notes/topics/<topic>.md` files (per [MVP spec Q9](../plans/active/mvp/spec.md#q9--lifestyle-calibration-via-referencecurated_notes-gene-shortlist-lct-cyp1a2-adora2a-aldh2-adh1b-apoe-mthfr)). Editing a curated note is a user-facing-copy change. The privacy-safety-reviewer agent reviews curated-note diffs before merge.
```

**Edit I4 — INV-C001 "How to verify"**: extend with a new test target.

Locate the **How to verify** section under INV-C001. After the existing snapshot-test bullets, append:

```markdown
- Snapshot tests on lifestyle-category responses asserting that the agent cites `gene_note:<gene>` as the evidence reference and that the response prose tracks the curated note's framing (no new claims introduced by the agent that aren't in the note). Failure modes: agent over-extending the note ("the note doesn't say that"), agent ignoring the note (over-deferral or generic clinical-deferral on a lifestyle question).
```

### Step 2.3 — REFACTOR

With the doc-checks GREEN:

- Read `architecture.md` end-to-end. Confirm the layered diagram, Component sections, Data layout, Network topology, and invariant-traceability table all read coherently with the new content. Specifically: does the tool count "six" appear consistently across the layered diagram, Component 3 description, and the invariant-traceability table? (It must.)
- Read `INVARIANTS.md` end-to-end. Confirm INV-C001 v1.5 reads coherently; the Rule line is unchanged; Requirements / Where it applies / How to verify all extended cleanly. The Invariant Index table at the bottom still lists exactly seven canonical IDs.
- Confirm cross-references: each "per Q5" / "per Q6" / "per Q7" / "per Q8" / "per Q9" reference in the architecture doc points at the right MVP spec block. Use a sanity-grep:

```bash
grep -E "per Q[5-9]|per Q10" docs/reference/architecture.md
```

- Re-run all doc-checks (Step 2.1); capture GREEN output in `work-notes.md`.

---

## Implementation Details

### Edit ordering

The two-file edit set has a natural ordering:

1. Architecture edits A1 → A6 (build outward: Component 1, Component 2, Component 3 / diagram, Repo / Data layout, Network topology, invariant-traceability table).
2. INVARIANTS edits I1 → I4 (header, then INV-C001's three subsections).

A1 should be the largest single edit (component description); A4 (data layout) is the most structurally complex. The remaining edits are 1–3 line additions.

### Cross-reference syntax

Architecture doc's references to MVP spec Q-blocks should use markdown links of the form:

```markdown
per [Q7](../plans/active/mvp/spec.md#q7--coverage-aware-gene-queries-mosdepth--genomeclaw_gene-5th-tool)
```

The exact anchor depends on how markdown renderers slugify the Q5/Q6/Q7/Q8/Q9/Q10 headings. For Phase 2 the `(per Q7)` plain-text shorthand is acceptable — full-anchor markdown links are nice-to-have but not required for doc-check correctness.

### Edge Cases to Handle

- **The mermaid layered diagram is plain text inside a code block.** Editing it preserves whitespace exactly; a stray newline inside the `Agent[...]` cell will break the renderer. After Edit A3, eyeball the diagram source in `architecture.md` and confirm the `<br/>` separators line up.
- **The `### 2. Host service` section already lists endpoints with parameter descriptions for `category`, `genes`, `drugs`, `limit`.** The new `/v1/gene/{symbol}` and `/v1/pgs/{trait}` endpoints have **scalar path parameters** (no list types), so they don't need the typed-array convention paragraph.
- **The data-layout block is ASCII-art-shaped.** When editing, preserve the box-drawing characters (`├──`, `└──`) exactly. A character-class drift will break the visual.
- **INVARIANTS.md's INV-C001 "Where it applies" section already has bullets that name `packages/...` paths.** The new bullet's `reference/curated_notes/` path follows the same indentation and bullet style.

### Error Handling

- If an `Edit` to `architecture.md` fails because `old_string` is not unique (component descriptions repeat similar sentences), widen the context until it is.
- If an `Edit` accidentally collapses two paragraphs (unbalanced trailing newlines), re-read the affected region and fix with a follow-up `Edit`.

### Privacy / Egress Notes

- Phase 2 documents the PGS Catalog egress in architecture.md but does not introduce it at runtime (no code lands).
- The privacy-safety-reviewer agent's existing scope (per `INV-C001`'s "Where it applies") expands to include curated-notes editing — but Phase 2 does not invoke the agent because no curated note is created or edited in this phase. The agent invocation lands in MVP Phase 6 when the first note is written.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/reference/architecture.md` | MODIFY | Component 1 (4 new tools); Component 2 (2 new endpoints + evidence resolver clarification); Component 3 / layered diagram (6 tools); Repo / Data layout (`curated_notes/`, `pgs_catalog/`, `vep_cache/`, `coverage_qc`, `pgs_scores`, `cyp2d6_diplotype.json`); Network topology (PGS Catalog path); invariant-traceability table (INV-E001, INV-P002, INV-C001 rows). |
| `docs/reference/INVARIANTS.md` | MODIFY | Version 1.4 → 1.5; Last Updated 2026-05-08; INV-C001 Requirements / Where it applies / How to verify each gain a curated-notes bullet. |
| `docs/plans/active/poc-pipeline-recommendations/work-notes.md` | MODIFY (append) | Phase 2 progress block, doc-checks RED → GREEN, INVARIANTS diff summary, sections-touched summary. |
| `docs/plans/active/poc-pipeline-recommendations/phases/phase-3.md` | CREATE | At end of Phase 2, author Phase 3's detailed plan (Grand plan + user stories) per the existing planning protocol. |

---

## Verification

```bash
# From repo root, after edits land

# Architecture component / endpoint / tool / data-layout / network / invariant-table checks
echo "=== Component 1 ==="
for term in "mosdepth" "Cyrius" "bcftools stats" "pgsc_calc" "LOFTEE" "AlphaMissense" "SpliceAI" "MANE Select"; do
  printf "%-20s " "$term:"; grep -c "$term" docs/reference/architecture.md
done

echo "=== Component 2 endpoints ==="
grep -E "GET /v1/gene/\\{symbol\\}|GET /v1/pgs/\\{trait\\}" docs/reference/architecture.md

echo "=== Component 3 / diagram tools ==="
grep -E "genomeclaw_(gene|pgs)" docs/reference/architecture.md | wc -l
# Expected: at least 4 — 2 in diagram + 2 in Component 3 description (or more)

echo "=== Data layout ==="
for term in "reference/curated_notes/" "vep_cache" "pgs_catalog" "coverage_qc" "pgs_scores" "cyp2d6_diplotype"; do
  printf "%-30s " "$term:"; grep -c "$term" docs/reference/architecture.md
done

echo "=== Network topology ==="
grep -i -c "PGS Catalog" docs/reference/architecture.md

echo "=== Invariant-traceability table ==="
grep "gene_note:<gene>" docs/reference/architecture.md
grep "topic:hard-genes" docs/reference/architecture.md

echo "=== INVARIANTS version + date ==="
head -10 docs/reference/INVARIANTS.md | grep -E "Version|Last Updated"

echo "=== INVARIANTS INV-C001 curated-notes recognition ==="
grep -c "curated_notes" docs/reference/INVARIANTS.md
# Expected: 3+ (Requirements bullet + Where-it-applies bullet + How-to-verify bullet, each mentioning the path)

echo "=== INVARIANTS Invariant Index table preserved ==="
grep -E "^\\| INV-(D001|D002|E001|P001|P002|R001|C001) \\|" docs/reference/INVARIANTS.md | wc -l
# Expected: 7
```

Final reading-test:
- Re-read `architecture.md` end-to-end; confirm tool count "six" / "6" appears consistently in the layered diagram, Component 3 description, and the invariant-traceability table.
- Re-read `INVARIANTS.md` INV-C001 end-to-end; confirm the four-category schema, escalation markers, evidence_quality, and over-deferral discipline are all preserved verbatim. The new content is additive.
- Cross-doc check: `mvp/spec.md` Q9 cites `INV-C001` v1.5; `INVARIANTS.md` now reads v1.5; consistent.

---

## Completion Criteria

- [ ] All 20 doc-checks (Step 2.1) pass GREEN after edits.
- [ ] Final reading-test: `architecture.md` reads coherently end-to-end with the new components, endpoints, tool count, data layout, network topology, and invariant-traceability table.
- [ ] INVARIANTS Invariant Index table still lists exactly seven canonical IDs (INV-D001, INV-D002, INV-E001, INV-P001, INV-P002, INV-R001, INV-C001).
- [ ] INV-C001 v1.5 Rule line is **unchanged**; only Requirements / Where it applies / How to verify gain new bullets. (The clarifying-revision discipline.)
- [ ] No reference doc other than `architecture.md` and `INVARIANTS.md` is touched.
- [ ] No `mvp/*` doc is touched in this phase. No code under `packages/` is touched.
- [ ] `work-notes.md` Phase 2 block captures: RED output (pre-edit grep failures), GREEN output (post-edit grep matches), INVARIANTS-diff summary, sections-touched summary, invariant-preservation review.
- [ ] Phase 2 status set to **Complete** in [development-plan.md](../development-plan.md) Progress Tracking table.
- [ ] [phases/phase-3.md](phase-3.md) of *this* plan is authored before Phase 2 closes (Grand plan + user stories detailed plan).
