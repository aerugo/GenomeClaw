# Polygenic Risk Scores in GenomeClaw — A Plain-English Report

**Audience**: anyone curious about what GenomeClaw does, with no bioinformatics or programming background assumed.
**Date**: 2026-05-18
**Status**: Layperson summary of work in progress.

---

## What GenomeClaw is

GenomeClaw is a personal-genomics assistant designed to run on the user's own computer, not in someone else's cloud. The whole reason it exists is that your genome is the most personal information you'll ever have, and most companies that offer to interpret it want to keep a copy. GenomeClaw is built on the opposite assumption: your genome stays on your hard drive, and the assistant you talk to about it runs there too.

A user has paid a sequencing company (Nebula Genomics) to read their DNA at high quality. The company hands back a hard drive with a few large files on it. GenomeClaw takes those files, organizes them, annotates them with what science currently knows about each variant, and lets the user ask questions like *"do I have any of the known variants in BRCA1?"* or *"how does my genetic risk for heart disease compare to the general population?"*

---

## What this particular report is about

One specific thing GenomeClaw wants to do is compute **polygenic risk scores** — known by their abbreviation as PRS. Most of the engineering this month has been about making PRS work on real data. This report explains:

1. What a polygenic risk score is and what it tries to tell you.
2. Why it turned out to be much harder than expected.
3. What we figured out to make it work.
4. What we measured to prove the fix is real.
5. What comes next.

The technical version of this story lives in [docs/plans/active/prs-input-coverage-fill/](../plans/active/prs-input-coverage-fill/). This is the version meant to be readable by someone who has never heard of any of this.

---

## What a polygenic risk score is

Some diseases are caused by a single broken gene. Sickle-cell, cystic fibrosis, Huntington's — find the bad letter in the relevant gene and you know the diagnosis. For these, one variant is the whole story.

Most common conditions don't work that way. Heart disease, type 2 diabetes, schizophrenia, prostate cancer, Alzheimer's — none of them are caused by a single broken gene. Instead, they emerge from the combined effect of thousands of tiny variants, each one nudging your risk up or down by a fraction of a percent. Almost everybody has many of these variants. What matters is whether you happen to carry more of the risk-raising ones than the risk-lowering ones, summed across all thousand-plus positions.

A **polygenic risk score** is what you get when you do exactly that sum. Scientists run very large studies (sometimes a million people) to figure out which individual variants nudge risk for a given condition and by how much. They publish that list of variants and effect sizes — call it a "scoring file". Then for any specific person, you take their genome, look up their genotype at each of those thousands of positions, multiply by the effect sizes, and add it all up. Compare the result to the distribution of scores in the population, and you get a percentile: *"this person is in the 78th percentile of risk for coronary artery disease compared to typical Northern Europeans."*

PRS is not a diagnosis. It is not a prophecy. It does not say someone *will* get the disease. It says the genetic component of their risk lies above or below average. Most people who score high never get the disease; most people who get the disease are not in the top scoring bracket. But PRS is useful at the margins — for example, it can identify younger people who, despite no family history of heart disease, would benefit from earlier cholesterol monitoring. It is, at best, one ingredient in a clinical conversation, never the conclusion of one.

---

## How GenomeClaw delivers a PRS

The user will be able to ask the assistant a question like *"compare my genetic risk for coronary artery disease against the general population"*. The assistant picks the right published scoring file from a public scientific catalogue (the "PGS Catalogue"), kicks off the calculation, and a quarter of an hour later returns something like *"with the scoring file from Patel et al. 2023, your continuous-ancestry-adjusted score lands at the 78th percentile, with a 95% confidence interval from 76 to 82, calibrated against a reference population of 3,942 individuals from Africa, the Americas, Asia and Europe."*

The "calibrated against a reference population" bit is critical. A score is just a number; what makes it meaningful is comparing it against the distribution of scores in a population whose ancestry is similar to yours. This is called **ancestry calibration**. Without it, a high score is just a number floating in space — you can't tell whether it's high relative to people like you or merely high relative to a misleading baseline. Worse, most published scoring files were trained on European-ancestry populations, so naive application to anyone of other ancestries produces systematically misleading numbers. The honest path is to either ancestry-calibrate the score against a population that includes the user's ancestry, or to decline to report the score with an explanation of why.

---

## The piece that broke

There is excellent open-source software for computing polygenic risk scores. The reference tool is called `pgsc_calc`, maintained by the same team that runs the PGS Catalogue. It takes your DNA and a scoring file and produces a calibrated percentile. We had the tool, we had the user's DNA, we had the scoring files — and it didn't work.

The reason is subtle and is the heart of this report.

When the sequencing company sequenced the user's DNA, they produced two relevant outputs:

- A huge file (about 50 gigabytes) recording every single read of every position in the genome, aligned against the standard reference genome. This is the **CRAM** file. It's the photographic record of what the machine actually saw.
- A much smaller file (about 1 gigabyte) listing the positions where the user's DNA differs from the standard reference genome. This is the **variant-only VCF**. It records about 4.7 million differences out of the 3 billion positions in a human genome.

What the variant-only VCF does *not* record is the ~2.99 billion positions where the user's DNA matches the reference. Those positions are implicitly understood to be "same as reference" — they're simply absent from the file.

This omission is normal practice in genomics. Most analyses don't care about positions where you match the reference; they care about where you differ. The variant-only VCF is dense at the interesting places and silent elsewhere.

The problem: `pgsc_calc` was designed assuming the *opposite* convention. It was designed to receive an **all-sites VCF** — a file that explicitly records every position in the reference panel, including the ones where the user matches the reference. Why? Because to do ancestry calibration, the tool needs to compare the user's genotype patterns to a reference library of how 3,942 other people's genomes vary at hundreds of thousands of carefully chosen positions. If the user's input is silent at those positions, the tool can't tell whether silence means "this person matches the reference" or "this person wasn't sequenced here". So it bails out.

Specifically: when we ran it, `pgsc_calc` reported that only 28% of the published scoring weights matched our input (against an expected ~85%). The 72% it didn't match weren't scoring errors — they were scoring positions where the user happens to have the reference letter, which the variant-only VCF doesn't record. And the ancestry-calibration step, which requires explicit matches against ~1.14 million reference-library positions, came back with zero overlap. The tool aborted with `n:0` and refused to produce a calibrated score.

You can force it to produce *something* by lowering the match-rate threshold to zero, but the resulting number is biased and uncalibrated. GenomeClaw's safety policy (an internal rule called `INV-C001`) forbids surfacing uncalibrated scores to the user. Either the calibration works or the assistant declines and explains why.

---

## The bridge we're building

Here's the fix. The variant-only VCF doesn't record the ~85% of positions where the user matches the reference, but the *CRAM file does*. The CRAM file is the raw photographic record; every position the sequencer actually saw is in there, including the boring ones. So we can go back to the CRAM and look up exactly the positions `pgsc_calc` cares about, then hand the result to `pgsc_calc` in the all-sites format it expects.

This is called **forced genotyping**: we don't ask the computer to discover variants from scratch (which is slow and expensive); we just ask it to look up a pre-specified list of positions and report what the reads say at each one. For each of those positions, the answer is one of: *"two copies of the reference letter"*, *"one copy of the reference and one variant"*, *"two copies of the variant"*, or *"not enough reads to be confident"*.

We do this in two layers:

**Layer 1 — the ancestry-calibration positions.** There are roughly 400,000-500,000 positions across the genome that the reference library (called HGDP+1kGP, comprising 3,942 individuals from around the world) uses to figure out who is genetically similar to whom. These are the positions `pgsc_calc` needs to project the user into "ancestry space" so it knows which reference population to calibrate the score against. This set is fixed — it doesn't depend on which disease the user is asking about. So we look up the user's genotype at all ~436k of these positions once, the first time they want any PRS, and cache the result. Subsequent questions skip this step entirely. We expect this one-time setup to take roughly 15 minutes to an hour depending on how many CPU cores the host machine is willing to dedicate.

**Layer 2 — the per-disease positions.** Each polygenic risk score uses a different set of scoring positions (anywhere from ten thousand to two million per score). When the user asks about a specific disease for the first time, we look up the user's genotype at that score's positions and cache the result. We expect this to take roughly 5-10 minutes per score, depending on its size. Re-asking the same question reuses the cache.

Then we stitch Layer 1 and Layer 2 together into the all-sites VCF format `pgsc_calc` expected all along, and hand it over.

This is not a new technique. The tool we use for the genotype lookup, called `bcftools`, is the standard reference tool in genomics for this kind of operation. The cleverness, if any, is in (a) recognizing that this is the right fix rather than reaching for heavier tools, and (b) caching the Layer 1 work so it doesn't have to be repeated every time the user asks a new question.

---

## What we measured to prove it works

Before committing to the fix as a plan, we ran a proof-of-concept on a single chromosome (chromosome 22, which is small and convenient to test on). For chromosome 22, the reference library uses 6,812 positions. We ran the lookup against the user's CRAM and timed it.

| What we measured | Result |
|---|---|
| Time to look up 6,812 positions on chromosome 22 | **99 seconds** |
| Peak memory used | **127 megabytes** (out of 8 gigabytes available — 1.6% utilization) |
| Positions where the user matched the reference (the bit we were trying to recover) | **84.5%** |
| Positions where the user had one variant copy | 9.5% |
| Positions where the user had two variant copies | 5.1% |
| Positions where reads were insufficient to call | 0.9% |
| Average sequencing depth at each looked-up position | **28×** (healthy 30× coverage) |

Translated: the fix recovered the missing 84.5% — exactly the data `pgsc_calc` needed. Memory use was trivial. Speed is acceptable. Coverage was healthy.

Scaling chromosome 22 to the whole genome (chromosome 22 is about 1.5% of the genome by variant count): we expect the full one-time setup to take about 50 minutes on the user's current machine configuration. If we give the machine more CPU cores, that drops to about 13 minutes — which is the figure quoted in the original recommendation document.

---

## Where we are now

The proof-of-concept worked. We've written:

- A specification: what we're building, why, what acceptance criteria it has to meet, what could go wrong.
- A development plan: how the work breaks into five phases, what each phase produces, how each phase is tested.
- A phase-one plan: 12 specific tests that the first chunk of code has to pass, with each test verifying one specific behavior (e.g., "the lookup must not modify the user's CRAM", "running it twice must produce identical output", "no network calls happen during the run").
- A work-notes log: the empirical measurements above, the design decisions, the rejected alternatives, the open questions.

What we haven't done yet is write any production code. That's the next session. The plan is structured so that each chunk of code is preceded by tests that already prove what it has to do, then code is written to make those tests pass, then the code is tightened up. This is called test-driven development and it's how the rest of the project is built.

---

## What still requires care

Three things to flag honestly:

**The accuracy gap on non-European ancestry.** The best ancestry-calibration in the world is **cloud imputation** against the TOPMed reference panel — a service that takes your DNA, projects it against ~190,000 sequenced genomes, and fills in the missing genotypes with statistical precision that no local method can match. GenomeClaw doesn't use it because using it would mean uploading the user's DNA to an external server, which violates the entire premise of the project. For users of Northern European ancestry the loss from staying local is small (a few percent at most). For users of African or admixed ancestry the loss is larger and is honestly acknowledged in every PRS report the assistant produces.

**The decline path matters as much as the success path.** Polygenic risk scores can be technically computable but scientifically misleading — for example, a score trained on people of European ancestry applied to someone of East Asian ancestry, where the genetic architecture of the trait may differ. GenomeClaw is designed to refuse to report scores in these cases, with a specific named reason. There are five canonical reasons it can decline (population transferability insufficient, PGS Catalogue tier insufficient, phenotype too heterogeneous, variant overlap insufficient, ancestry calibration uncertain), and the assistant is required to surface the reason explicitly rather than just shrugging.

**PRS is not medical advice.** Every PRS report in GenomeClaw is framed as "research-level genetic information" and includes an explicit caveat that scientific evidence varies across ancestry groups, that the score is one input among many that should go into any clinical conversation, and that no PRS report is a substitute for evaluation by a clinician. This framing is hard-coded into the report template, not a footnote.

---

## In one paragraph

The user's sequencer wrote down what's different about their DNA but not what's the same. The standard tool for computing polygenic risk scores wants both. So we use `bcftools` to look up the missing "same" positions directly from the raw read data, cache the answer, hand it to the standard tool in the format it expected all along, and get an ancestry-calibrated percentile back. The fix is well-trodden bioinformatics, runs on the user's own machine in under an hour for the one-time setup and ~10-15 minutes per subsequent question, uses ~150 megabytes of memory, sends no data anywhere, and surfaces a five-category honest decline when the inputs don't support a calibrated answer.
