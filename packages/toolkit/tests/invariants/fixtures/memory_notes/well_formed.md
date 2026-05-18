## 2026-05-15 — CYP1A2 caffeine metabolism + sleep

**Question**: my sleep has been bad lately. anything in my genome about caffeine metabolism?

**Tool calls (research phase, reasoning=high)**:
- `memory_search "CYP1A2 caffeine sleep"`: empty (no prior synthesis on this topic).
- `genomeclaw_variant key=rs762551`: user is C/C at the diagnostic CYP1A2 SNP (slow-metabolizer phenotype).
- `web_search "CYP1A2 rs762551 caffeine half-life slow metabolizer 2026 meta-analysis"`: 3 sources retrieved.

**Sources retrieved**:
- https://www.pharmgkb.org/gene/PA27101: PharmGKB CYP1A2 gene page. Notes smoking + OCPs induce/inhibit more than genotype.
- PMID 12345678: 2024 meta-analysis. Caffeine half-life: slow metabolizers ~7-8h vs fast ~4-5h. Effect size moderate; substantial individual variation.
- https://www.ncbi.nlm.nih.gov/pubmed/87654321: Review on CYP1A2 and sleep. Notes the noon-cutoff intervention has modest n-of-1 evidence in slow metabolizers.

**Synthesis (reasoning=max)**:
User is C/C at rs762551 — slow CYP1A2 metabolizer phenotype. Genotype effect on caffeine half-life is moderate (7-8h vs 4-5h average), but with substantial individual variation. Smoking and oral contraceptive use modulate CYP1A2 activity more than genotype does — if either applies to the user, the genotype is the smaller signal. For the sleep complaint, the noon-cutoff intervention is a reasonable falsifiable experiment: 2 weeks of strict noon cutoff, sleep-onset latency as the outcome.

**Calibration**:
- Effect size: moderate (caffeine half-life ratio ~1.5-2× between fast/slow, but high individual variation; per PMID 12345678).
- Evidence quality: moderate (meta-analysis-supported on metabolism; weaker on sleep-outcome causation in n-of-1 trials).
- Heterogeneity: heterogeneous (sleep-outcome effect sizes scatter across studies).
- Modulators: smoking (induces), oral contraceptives (inhibit ~40%), age, caffeine habituation, baseline sleep hygiene.

**Recommendation framing**:
Falsifiable experiment: strict noon caffeine cutoff for 2 weeks, sleep-onset latency as the outcome. Keep alcohol + screen-time + room-temperature constant so they don't confound. If sleep-onset shortens, caffeine is a contributor; if not, the bottleneck is elsewhere (look at light exposure, alcohol, stress). Clinical-escalation trigger: persistent sleep issues after the trial + a couple of basic sleep-hygiene moves — frame as sleep complaint, not CYP1A2 question.

**Citations surfaced to the user**:
https://www.pharmgkb.org/gene/PA27101, PMID 12345678

**Freshness**: as of 2026-05-15. Re-research if asked after 6 months, or if user explicitly requests an update, or if a major new meta-analysis on CYP1A2 + sleep emerges.
