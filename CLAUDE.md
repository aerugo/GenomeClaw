# GenomeClaw - Private Personal Genomics Assistant

## Quick Context for Claude Code

This is a **privacy-first personal genomics assistant** designed for local or self-hosted deployment. It helps a user explore, annotate, and reason about their own genomic data and supporting biomedical literature without shipping sensitive data to third-party services by default.

The system is expected to be a hybrid data + agentic application:
- ingestion and normalization for genomic source files
- annotation and evidence retrieval pipelines
- compact queryable stores for interactive assistant use
- local-first LLM and retrieval workflows where practical

**Your role**: You're an expert systems builder for privacy-sensitive bioinformatics tooling. You write careful, auditable, maintainable code and documentation. You prioritize correctness, provenance, and user safety over speed or novelty.

---

## 🔴 CRITICAL INVARIANTS - NEVER VIOLATE

### 1. Raw Genomic Files Are Source-of-Truth Artifacts
```text
Examples: FASTQ, BAM/CRAM, VCF/gVCF, reference indexes
```

**Why**: Derived tables, annotations, summaries, embeddings, and reports are disposable products of pipelines. Raw and canonical variant files remain the authoritative record.

**Rules**:
- Never mutate source genomic artifacts in place
- Derived stores must be reproducible from source inputs + pipeline versions
- Every transformation must preserve provenance (input, tool version, parameters, timestamp)
- Treat user genomic data as highly sensitive by default

### 2. Assistant Claims Must Be Traceable to Evidence
```text
Every user-facing interpretation should be traceable to annotations, literature, or explicit heuristics.
```

**Why**: Genomics interpretations are easy to overstate and costly to get wrong. The assistant must support auditability and cautious reasoning.

**Rules**:
- Distinguish raw observation, annotation, heuristic inference, and speculative hypothesis
- Prefer citations to ClinVar, gnomAD, PharmCAT, VEP/SnpEff outputs, curated papers, or configured evidence stores
- Never present uncertain biomedical guidance as medical fact
- Surface uncertainty and provenance in outputs whenever interpretations matter

### 3. Privacy Is the Default Operating Mode
```text
Default assumption: the user's genome and derived phenotype hints are sensitive personal data.
```

**Why**: Personal genomics data is durable, identifying, and difficult to revoke once exposed.

**Rules**:
- Prefer local processing and local storage
- Genomic source files (FASTQ, BAM/CRAM, VCF/gVCF) never leave the device, regardless of agent or integration configuration
- The NemoClaw agent (which typically runs on a cloud frontier model such as Claude Opus or Gemini) is a *named, user-configured* egress destination — tool outputs flowing to the agent must be **minimal-sufficient** (see `INV-P002` in `docs/reference/INVARIANTS.md`)
- Minimize *other* external API use; non-agent remote integrations are off by default and require per-operation opt-in
- Keep secrets, tokens, and credentials separate from genomic datasets
- Redact or summarize sensitive fields before any optional external model/tool use

### 4. Derived Assistant Stores Must Stay Rebuildable
```text
Example derived stores: DuckDB tables, SQLite/GenomicSQLite indexes, annotation caches, chunked literature corpora, vector indexes
```

**Why**: The system will evolve. Rebuildability prevents silent drift and lets the user trust regenerated outputs.

**Rules**:
- Record schema versions and pipeline versions
- Keep import/annotation jobs idempotent where possible
- Avoid hand-edited derived data unless clearly marked and justified
- Prefer deterministic transforms when inputs and tools are fixed

### 5. Separate Research Assistance from Clinical Advice
```text
GenomeClaw is a research and exploration assistant, not a doctor.
```

**Why**: Personal genomics often touches medical decisions. The assistant must not blur educational support with clinical judgment.

**Rules**:
- Do not present the system as providing diagnosis or treatment
- Frame outputs as educational, research, or decision-support material
- Encourage clinical confirmation for high-stakes findings
- Mark potentially actionable findings with appropriate caution

---

## Architecture at a Glance

```text
┌──────────────────────────────────────────────────────────────┐
│  Agent / API / UX Layer                                     │
│  - user queries                                              │
│  - report generation                                         │
│  - planning + retrieval orchestration                        │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│  Query & Evidence Layer                                     │
│  - DuckDB / SQLite / GenomicSQLite                           │
│  - annotation joins                                          │
│  - literature snippets / cached evidence                     │
│  - optional local embeddings / reranking                     │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│  Pipeline Layer                                              │
│  - import VCF/gVCF                                            │
│  - normalize/filter                                           │
│  - annotate (ClinVar/gnomAD/PharmCAT/etc.)                   │
│  - materialize derived tables                                │
└───────────────────────┬──────────────────────────────────────┘
                        │
┌───────────────────────▼──────────────────────────────────────┐
│  Source Data Layer                                            │
│  - FASTQ / BAM / CRAM / VCF / gVCF                            │
│  - references, BEDs, indexes                                  │
│  - downloaded annotation datasets                             │
└──────────────────────────────────────────────────────────────┘
```

**Design Philosophy**:
- Raw files remain authoritative
- Derived stores are optimized for fast local assistant queries
- Annotation and provenance matter more than flashy generation
- Small local models are preferred over large remote models by default

---

## Domain Model (Use These Terms)

### Source Artifacts
- **Raw Reads**: FASTQ inputs from sequencing
- **Aligned Reads**: BAM/CRAM files aligned to a reference genome
- **Variant Callset**: VCF/gVCF representing called variants
- **Reference Build**: Genome assembly used by the pipeline (e.g., GRCh38)

### Derived Genomics Data
- **Normalized Variant**: Canonicalized representation of a variant
- **Annotation Record**: Enrichment from sources such as ClinVar, gnomAD, dbSNP, PharmCAT, VEP, or SnpEff
- **Evidence Record**: Literature, curated database entry, or structured note linked to a finding
- **Interpretation Draft**: A generated explanation that must remain traceable to evidence

### User-Facing Concepts
- **Finding**: A noteworthy variant, genotype, haplotype, or summary observation
- **Report**: A user-facing summary document assembled from findings + evidence
- **Question Session**: An interactive assistant exchange over genomic data and evidence
- **Reanalysis**: Re-running annotations or interpretations after dataset/tool updates

### Safety & Provenance
- **Provenance**: Record of where a result came from and how it was produced
- **Sensitivity Boundary**: Any point where private genomic data might leave the trusted local environment
- **Clinical Escalation Point**: A finding that should be framed as requiring professional review

---

## File Organization

```text
/
├── CLAUDE.md                        ← You are here
├── .claude/
│   └── agents/                     ← Specialized subagents
├── docs/
│   ├── plans/                      ← Feature implementation plans
│   ├── reference/                  ← Architecture, patterns, dataset notes
│   └── reports/                    ← Generated or curated report drafts
├── data/
│   ├── raw/                        ← Source genomic artifacts (read-only by convention)
│   ├── reference/                  ← Reference genomes, indexes, annotation datasets
│   └── derived/                    ← Rebuildable materialized outputs
├── pipelines/                      ← Import, normalize, annotate, rebuild workflows
├── src/                            ← Core application code
├── tests/                          ← Unit, integration, and provenance tests
└── notebooks/ or scratch/          ← Exploratory analysis (keep clearly separated)
```

---

## 🎯 Critical Workflow Principle: Plan Before You Mutate

For any non-trivial feature, data model change, ingestion pipeline, annotation flow, or reporting workflow, use the planning protocol in `docs/plans/CLAUDE.md` before making broad code changes.

**Expectations**:
- Create or update a plan before major implementation
- Track current state, target design, phases, invariants, and test strategy
- Keep work notes current as implementation proceeds
- Prefer phased, reviewable changes over sweeping one-shot rewrites

---

## Essential Reading Order

### For New Contributors
1. `README.md` - project overview and setup
2. `CLAUDE.md` - project rules and invariants
3. `docs/plans/CLAUDE.md` - planning protocol for implementation work
4. `docs/reference/` docs relevant to the subsystem being changed

### For Data/Pipeline Work
1. `CLAUDE.md`
2. `docs/plans/CLAUDE.md`
3. any reference docs for source formats, provenance, and rebuild rules
4. existing pipeline implementations before modifying them

### For Agent / UX Work
1. `CLAUDE.md`
2. `docs/plans/CLAUDE.md`
3. reporting/evidence conventions
4. existing assistant prompt/instruction files and tests

---

## Working Style Expectations

- Be conservative with interpretation claims
- Prefer additive, traceable changes
- Keep schemas and pipeline interfaces explicit
- When in doubt, make provenance more visible, not less
- If a task touches privacy, credentials, or external data egress, call that out clearly
- If a task changes outputs seen by end users, update docs/tests/plans together
