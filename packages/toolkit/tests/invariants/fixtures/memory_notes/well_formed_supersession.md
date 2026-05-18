## 2026-05-15 — CYP1A2 caffeine + sleep [SUPERSEDES memory:2026-03-15-cyp1a2.md#cyp1a2-summary]

**Supersedes**: memory:2026-03-15-cyp1a2.md#cyp1a2-summary

**Gap found in prior note**:
The prior note's conclusion ("noon caffeine cutoff is universally recommended for CYP1A2 slow metabolizers with sleep complaints") overreached its single cited source. The 2024 meta-analysis it pointed at reports moderate, heterogeneous effect sizes — not universal applicability. The prior note also omitted the smoking + OCP modulators which the meta-analysis flags as more impactful than genotype in many subgroups. Validation triggered re-research.

**Question**: my sleep has been bad lately. anything in my genome about caffeine metabolism?

**Tool calls (research phase, reasoning=high)**:
- `memory_search "CYP1A2 caffeine sleep"`: hit prior note (memory:2026-03-15-cyp1a2.md).
- `memory_get "memory:2026-03-15-cyp1a2.md"`: retrieved.
- Validation check 1 (conclusion-↔-source): **FAILED** — note overreached its single source.
- `web_search "CYP1A2 rs762551 caffeine half-life slow metabolizer 2024 meta-analysis"`: 3 sources retrieved including the original + 2 newer reviews.
- `genomeclaw_variant key=rs762551`: C/C.

**Sources retrieved**:
- https://www.pharmgkb.org/gene/PA27101: PharmGKB CYP1A2 gene page.
- PMID 12345678: 2024 meta-analysis (the one the prior note overreached).
- PMID 87654321: 2025 review on CYP1A2 + sleep that explicitly addresses modulator heterogeneity.

**Synthesis (reasoning=max)**:
User is C/C at rs762551 — slow CYP1A2 metabolizer. Effect on caffeine half-life is moderate; high inter-individual variation. The earlier "universal noon cutoff" framing was an overreach. Correct framing: noon cutoff is a reasonable 2-week experiment for slow metabolizers with sleep complaints, especially if neither smoking nor OCP use is present. If either applies, those are larger signals than the genotype.

**Calibration**:
- Effect size: moderate (per the 2024 meta-analysis + 2025 review; heterogeneous).
- Evidence quality: moderate-replicated.
- Heterogeneity: heterogeneous — the noon-cutoff intervention has scatter across cohorts.
- Modulators: smoking (induces; dominates genotype effect), OCPs (inhibit ~40%; can dominate), age, habituation, baseline sleep hygiene.

**Recommendation framing**:
Two-week noon-cutoff experiment IF user doesn't smoke AND isn't on OCPs. If either applies, address that modulator first (smoking has a much larger effect on CYP1A2 than genotype). Falsifiable outcome: sleep-onset latency.

**Citations surfaced to the user**:
https://www.pharmgkb.org/gene/PA27101, PMID 12345678, PMID 87654321

**Freshness**: as of 2026-05-15. The prior note from 2026-03-15 stays on disk as the audit trail.
