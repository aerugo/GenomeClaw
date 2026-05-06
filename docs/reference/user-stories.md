# GenomeClaw — User Profiles & Stories

**Status**: Living document
**Companion to**: [grand-plan.md](grand-plan.md), [architecture.md](architecture.md), [INVARIANTS.md](INVARIANTS.md)
**Last Updated**: 2026-05-06

This document captures **what using GenomeClaw actually looks like** — who the user is, what the agent is, the trust contract between them, and the concrete journeys they walk together. The stories are detailed on purpose: every gap or assumption that surfaces here is meant to flow back into the strategic documents.

The single ground truth: there is **one user**, on their own host (any Linux or macOS environment that runs NemoClaw and the bioinformatics tools), talking to a NemoClaw agent **primarily over Telegram**, asking questions about their own genome. Everything else follows from that.

A list of design gaps surfaced by these stories appears at the end, along with a plan to update [grand-plan.md](grand-plan.md), [architecture.md](architecture.md), [INVARIANTS.md](INVARIANTS.md), and [README.md](../../README.md) to align.

---

## Profiles

### Profile 1 — The Project Owner ("the user")

The user is a single person — the same person who built GenomeClaw. They:

- Have their own **Nebula Genomics 30× WGS dataset**, delivered as FASTQ + BAM/CRAM + VCF on an external SSD.
- Run a Linux or macOS host at home as an always-on personal-agent machine — exact hardware is the user's choice (a small Linux home server, a developer laptop, an Apple Silicon Mac, etc.). The project is agnostic about it.
- Have configured **NemoClaw / OpenClaw / OpenShell** on that host, with **OpenAI gpt-5.4** as the inference provider, paired to their personal **Telegram** account.
- Have moderate technical fluency: comfortable installing Docker images, reading a YAML policy preset, running CLI tools, troubleshooting an env var. **Not a clinician.**
- Are **privacy-conscious**: this is the entire reason GenomeClaw exists. They won't upload their genome to commercial annotation services. They might allow the agent to look something up on PubMed; they will *not* allow the genome itself to leave the device.
- Are **curiosity-driven**, not crisis-driven. They want to *learn* from their own data — though specific concerns (family history of a condition, a new prescription, a paper they read) drive specific questions.
- Treat **clinicians as authoritative** for medical decisions. They expect the agent to defer to a clinician for anything actionable.
- Are interested in **lifestyle optimization** as well as medical risk. They might ask about fitness-related genes, or how to adjust their diet given a particular variant — but they understand that the evidence base for lifestyle optimization is much shakier than for medical risk, and they want the agent to be clear about that.

The user reads on their phone in bed, in cafés, on walks. Most interaction with GenomeClaw happens *through Telegram*, asynchronously, in plain language. The CLI on the host is reserved for setup, ingest, and admin.

### Profile 2 — The Agent ("NemoClaw")

The agent is an **OpenClaw instance** running inside an OpenShell sandbox on the host, configured by NemoClaw. From the user's perspective, it is a single Telegram persona. Internally:

- It uses **OpenAI gpt-5.4** for reasoning, routed through OpenShell's L7 inference proxy at `inference.local` (the API key never enters the sandbox).
- It receives messages from the user over **Telegram** (whitelisted in the OpenClaw default policy).
- It has access to a small set of **callable tools**, including the GenomeClaw plugin tools (`genomeclaw_status`, `genomeclaw_findings`, `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_report`) and any other tools NemoClaw has installed (web search via Brave, possibly URL-fetch, etc.).
- It maintains **session memory** in `/sandbox/.openclaw/memory/` — facts the user has told it (current medications, family history, ongoing concerns) live here.
- It has **no autonomy by default** beyond responding to user messages. Proactive notifications (e.g., "a ClinVar release affects one of your prior findings") are an opt-in feature in a later horizon, not something it does on day one.
- It does not run pipelines. It cannot read raw genomic files. It cannot write to the derived store. It can only *query* through the host service via the plugin.

### Profile 3 — Anyone else

There is no Profile 3. GenomeClaw is single-user by design. If a partner or family member is mentioned in a conversation, they are mentioned only as context held in agent memory — their genomes are not in the system, and adding them is out of scope (`grand-plan.md` § Decisions Deferred).

---

## The Trust Contract

The agent is given the user's genome (indirectly, via scoped tool outputs) and the user's confidence. In return it commits to specific behaviors. These commitments are what make the system safe to use casually over Telegram on a phone.

The agent **will**:

- Cite evidence for every biomedical claim it makes (`INV-E001`).
- Distinguish observation, annotation, heuristic inference, and speculation when the distinction matters.
- Flag clinical-actionability findings with a visible escalation marker and recommend clinical confirmation (`INV-C001`).
- Give the user health optimization and body hacking advice to help with lifestyle decisions, but not medical advice.
- Calibrate lifestyle advice with **evidence quality** — lifestyle and wellbeing findings draw from a weaker evidence base than ClinVar-grade clinical findings, and the agent says so when relevant. Lifestyle recommendations are framed as **falsifiable experiments** (e.g., "try this for two weeks"), not as guidelines.
- Refuse to send the user's genome (raw or aggregated) to any external service.
- Tell the user when it doesn't know.

The agent **will not**:

- Diagnose, prescribe, dose, or otherwise issue clinical guidance.
- Send raw variant lists, BAM/VCF byte ranges, or sample identifiers to OpenAI or any other remote service. Tool outputs flowing to the LLM are minimal-sufficient by `INV-P002`.
- Persist phenotype-linked content in places that would survive a sandbox rebuild without the user's awareness.
- Speculate beyond what the user asked, especially about high-stakes findings.
- Pretend it is a clinician.

The user, in return, **understands**:

- The agent is a research/exploration assistant *and* a lifestyle/wellbeing consultant — but not a doctor. Clinical questions get framed differently from lifestyle questions; both get evidence-cited answers.
- Findings can change as ClinVar / gnomAD / dbSNP / PharmCAT evolve. A "negative" today is not a permanent negative.
- Lifestyle recommendations are starting points for self-experimentation, not prescriptions. The evidence base for lifestyle is generally weaker than for clinical findings, and the agent will say so.
- The agent's interpretations are bounded by what's currently in the derived store. Newer references may reveal more, and rebuilds are deliberate.

---

## Story 1 — Initial setup: loading Nebula data into the derived store

**Setting**: The user has just received their Nebula Genomics 30× WGS deliverable. They unpack it onto external storage attached to the host (USB-attached NVMe SSD, NAS mount, etc. — the project does not care which). This is the only fully host-side story — it happens **before** the Telegram experience makes sense.

**State at start**: `/mnt/genomeclaw/raw/` exists and is mounted read-only. `/mnt/genomeclaw/reference/` is populated with GRCh38 + ClinVar/gnomAD/dbSNP downloads from a previous `genomeclaw-prep fetch` run. `/mnt/genomeclaw/derived/` is empty.

**The user's actions**:

1. They open a shell on the host (SSH or local terminal — same difference).
2. They confirm the source files are visible:
   ```bash
   ls /mnt/genomeclaw/raw/<sample-id>/
   # → sample.fastq.gz  sample.bam  sample.bam.bai  sample.vcf.gz  sample.vcf.gz.tbi
   ```
3. They run the ingest pipeline:
   ```bash
   genomeclaw-prep ingest \
     --sample-id <sample-id> \
     --reference /mnt/genomeclaw/reference/grch38/ \
     --vcf /mnt/genomeclaw/raw/<sample-id>/sample.vcf.gz
   ```
   The CLI prints a plan: which tools at which versions will run, against which inputs (with hashes), writing to which `<run-id>` directory. The user confirms.
4. The pipeline runs: integrity checks → format-aware preview → normalization → annotation against ClinVar/gnomAD/dbSNP → materialization into a DuckDB derived store with provenance columns. It takes a while; the user makes coffee.
5. When it finishes, the CLI prints:
   ```
   Run complete:
     run-id:        2026-05-06T08-12-34Z-abc123
     derived-store: /mnt/genomeclaw/derived/2026-05-06T08-12-34Z-abc123/
     schema:        v0.1
     tools pinned:  bcftools=1.20, snpeff=5.2, ...
     provenance:    /mnt/genomeclaw/derived/.../provenance.json
   This run is now the active store for genomeclaw-service.
   ```
6. They start the host service:
   ```bash
   genomeclaw-service start --port 8643
   # service binds 127.0.0.1:8643, exposes /v1/health and the read-only API
   ```
7. They optionally run `nemoclaw <sandbox> config set --key plugins.entries.genomeclaw.config.hostService.baseUrl --value '"http://host.openshell.internal:8643"' --restart` if the URL changed.

**State at end**: A populated derived store, a running host service, a configured plugin. The user has *not* yet talked to the agent about any of this.

**What the agent knows next time it talks to the user**: the next time the user sends a Telegram message, the agent's `before_agent_start` plugin hook (or its own self-check) will call `genomeclaw_status`, see `gateway: running` and a fresh `run-id`, and silently note "the user's genome is now indexed in run-id 2026-05-06T08-12-34Z-abc123, schema v0.1." That's the entire onboarding.

**Surfaced gaps**:

- The host service needs to manage **"the active run"**: when a new derived store run lands, the service should switch to it (or be told to switch). Endpoints like `/v1/findings` implicitly query the latest run unless `?run-id=` is given. The current architecture doc lists endpoints but doesn't mention this active-run resolution.
- The `genomeclaw-prep` CLI has a sub-surface (`fetch`, `ingest`, `normalize`, `annotate`, `materialize`) that the architecture doc currently glosses. Worth listing the canonical subcommands.
- The user's Telegram pairing flow (NemoClaw side) and the GenomeClaw setup flow are independent, but their relationship deserves a note: GenomeClaw doesn't ship onboarding for Telegram; it inherits whatever NemoClaw already configured.

---

## Story 2 — First conversation: "what do you know about me?"

**Setting**: Friday evening. The user is in bed, on their phone. They've never used GenomeClaw conversationally before. They open Telegram and message the NemoClaw bot.

**The exchange**:

> **User**: ok let's try this. what do you actually know about me?

> **Agent**: I have access to your genome through GenomeClaw. The active derived store is run-id `2026-05-06T08-12-34Z-abc123`, schema v0.1. It was built from a Nebula Genomics 30× WGS VCF and annotated against ClinVar (release 2026-04), gnomAD v4.1, and dbSNP build 156. I haven't queried any specific findings yet — I only know the genome exists and is indexed.
>
> A few things I should be clear about up front:
>
> - I'm a research/exploration assistant, not a doctor. For anything you'd act on, please confirm with a clinician.
> - Your variant data stays on your host. When I answer questions, I'm sending only scoped findings and evidence references to OpenAI, never raw genomic files or the full variant list.
> - My answers are only as current as the annotation databases in your derived store. ClinVar in particular changes monthly.
>
> Want to start broad (e.g., "what's notable in my genome?") or with a specific gene or condition?

**Tool calls behind the scenes**:

- `genomeclaw_status` (no args) — the agent always grounds itself before answering "what do you know about me." Result: `{run_id, schema_version, annotation_versions, gateway_health, last_refresh}`. The agent re-shapes this into a sentence.

> **User**: start broad. what's the most "interesting" stuff in there?

> **Agent**: Two reasonable lenses for "interesting":
>
> 1. **Clinically actionable variants** (ACMG SF list — a curated set of 80-ish genes where pathogenic findings are considered worth knowing about even outside a diagnostic context). I can pull these.
> 2. **Pharmacogenomic findings** (PharmCAT — variants that affect how you metabolize specific drugs). Useful for context if you're prescribed something.
>
> Either or both? "Interesting" without a frame can mislead — there are tens of millions of variants in your genome, and most of them are noise.

**Tool calls behind the scenes**: none yet. The agent is doing user-facing pacing, not running queries.

> **User**: both. start with the actionable one.

> **Agent**: One moment.

**Tool calls**:

- `genomeclaw_findings category=acmg-sf` — returns scoped finding list with `clinical_escalation` markers, evidence refs, confidence categories.

The agent receives a structured list. In this user's run, suppose there are two findings: one variant in *MUTYH* of unknown significance (no escalation marker), one variant in *BRCA2* annotated by ClinVar as pathogenic (escalation marker set).

> **Agent**: Two findings on the ACMG SF list in your run:
>
> 1. **BRCA2 — c.5946delT (rs80359550)** — ClinVar lists this as pathogenic; gnomAD allele frequency 0.00012. **Marked for clinical escalation.** ClinVar review status is "criteria provided, multiple submitters, no conflicts" (4-star). Evidence ref: `clinvar:9999`. **Please discuss this with a clinician — this is the kind of finding where confirmation in a clinical context matters.**
> 2. **MUTYH — c.892-2A>G** — ClinVar lists this as a variant of uncertain significance (VUS). Not actionable on its own; not flagged for escalation. Evidence ref: `clinvar:8888`.
>
> Want me to pull the PharmCAT findings now, or talk more about either of these?

**Notable**: The agent did not phrase anything as "you have cancer" or "you should get tested." It cited evidence, surfaced the escalation marker structurally, and named the precise next step (talk to a clinician). The escalation marker came from the host service's finding schema, not from the agent improvising.

**Surfaced gaps**:

- Tool descriptions for the agent's tool catalog need to **convey the framing**, not just the function. The agent's behavior here is shaped by *what the tool descriptions say* it can/can't do. We should review that the registered `description` strings (in `packages/nemoclaw-plugin/src/index.ts`) carry research-framing language, not clinical language. (`INV-C001` already names plugin tool descriptions as in-scope, but we should make this concrete.)
- The agent's "I haven't queried any specific findings yet" line implies session-level provenance: the agent should be able to recall *what tool calls it has made in this conversation*, so it can be honest about what it knows. That's an OpenClaw memory concern, but worth surfacing.
- The annotation-version disclosure in the agent's first reply is important. The plugin should expose this clearly via `genomeclaw_status`. Currently the host service `/v1/health` is described as "liveness + active run-id + schema version" — it should also include annotation-source versions.

---

## Story 3 — Specific gene query: "what about my BRCA1?"

**Setting**: A few weeks later. The user's mother has been diagnosed with a hereditary breast/ovarian-cancer-related condition. The user asks the agent about their own *BRCA1*.

**The exchange**:

> **User**: my mom just got her brca1 results back, c.68_69del. do I have anything in brca1?

> **Agent**: Looking now.

**Tool calls**:

- `genomeclaw_findings category=acmg-sf gene=BRCA1` — scoped to BRCA1 specifically.

(*Surfaced gap: the current `genomeclaw_findings` tool description mentions `gene=`, but the host service endpoint sketch in `architecture.md` doesn't list `?gene=` as a query param. We need to make that explicit.*)

The host service returns findings filtered to BRCA1. Suppose the run has one VUS in BRCA1 and no pathogenic variants.

> **Agent**: In your run I see one variant in *BRCA1*: **c.4485-63del** — ClinVar lists this as a variant of uncertain significance (review status: "criteria provided, single submitter", 1-star). It is not the same variant as your mother's c.68_69del.
>
> Specifically about c.68_69del: I do **not** see that variant in your call set. That's consistent with not inheriting that specific allele from your mother — but please confirm with a clinician, especially if your mother's genetic counselor has suggested cascade testing for the family. WGS callsets occasionally miss small indels; targeted Sanger sequencing of the specific variant is the standard confirmatory test in a familial context.
>
> Evidence refs: `clinvar:7777` (your VUS), `clinvar:1234` (your mother's reported variant, looked up because you mentioned it). I have not added your mother's variant to your record — I just looked it up to compare.

**Tool calls**:

- `genomeclaw_variant key=BRCA1:c.68_69del` — to confirm absence in the user's call set (or perhaps just confirm via the findings query).
- `genomeclaw_evidence ref=clinvar:1234` — to surface what the mother's variant means contextually.

**The user replies later that evening**:

> **User**: thanks. saved that. one more — could it be hiding in a region the WGS misses?

> **Agent**: The honest answer: yes, sometimes. WGS at 30× has high but not perfect sensitivity for small indels in repetitive regions. *BRCA1* in particular has some difficult regions. Two things you could ask a clinical lab:
>
> - whether targeted Sanger sequencing of *BRCA1* c.68_69del is appropriate for cascade testing in your family
> - whether MLPA-based deletion/duplication testing is warranted (WGS is also imperfect for large rearrangements in *BRCA1*)
>
> I can't run either of those — they're laboratory-based clinical tests. This is a decision to take to a genetic counselor. If you'd like, I can summarize the technical context above in a single message you could forward to them.

**Notable**: the agent named two specific limitations of WGS *and* declined to issue a clinical recommendation, while making it easy to forward the technical context to a professional. It also noted that adding the mother's variant to *the user's record* would be out of bounds.

**Surfaced gaps**:

- The user mentioning a *third party's variant* is a privacy event. The agent should *not* persist the mother's variant identifier into long-term memory without explicit consent, because it's another person's medical data. This is a real `INV-P001`-flavored concern that we haven't surfaced clearly. Worth addressing.
- The agent's offer to summarize for a clinician is a pattern (a "physician handoff" style of response) that recurs. Not a tool per se — but the agent's response template should make it natural.
- We need a way to query for **absence** of a specific variant cleanly. `genomeclaw_variant key=...` returns the variant or 404. The 404 case shouldn't be surprising to the agent.

---

## Story 4 — Pharmacogenomics: "I'm starting clopidogrel"

**Setting**: A weekday afternoon. The user's GP has prescribed clopidogrel after a TIA. The user asks the agent before the first dose.

**The exchange**:

> **User**: gp prescribed plavix today. anything in my genome i should know before the first dose?

> **Agent**: Plavix is clopidogrel — and clopidogrel has well-established pharmacogenomic considerations, mainly around *CYP2C19*. Pulling now.

**Tool calls**:

- `genomeclaw_findings category=pgx gene=CYP2C19` — scoped pharmacogenomic findings on the metabolizer-status genes for this drug class.

(*Surfaced gap: this query pattern wants the tool to be parameterizable by **drug** as well as gene. "What's relevant for clopidogrel?" is a more useful framing than "what's in CYP2C19?" — the latter requires the user or agent to know the gene-drug map. Either: (a) the host service exposes a `drug=` filter, or (b) PharmCAT's drug-keyed output is what we surface. Worth making explicit.*)

Suppose the user's *CYP2C19* haplotype is `*1/*2`, an intermediate metabolizer.

> **Agent**: One PGx-relevant finding for clopidogrel:
>
> - ***CYP2C19*** haplotype: ***\*1/\*2***. **This is an intermediate-metabolizer phenotype.** PharmCAT/CPIC guidance for clopidogrel + intermediate metabolizers in the context of acute coronary syndromes / PCI suggests considering an alternative antiplatelet (prasugrel or ticagrelor) where appropriate. Evidence: PharmCAT report, CPIC guideline `cpic:clopidogrel:v2.0`. Source files: ClinVar/PharmGKB; review status: high-confidence.
>
> **Marked for clinical escalation. Please mention this to your GP or the cardiologist who prescribed before your first dose.** I am not telling you to skip the medication — I'm telling you there's a published guideline that's relevant and your prescriber should weigh it.
>
> If it would help, I can prepare a one-paragraph summary you can forward to them. Want me to?

**Tool calls (additional)**:

- `genomeclaw_evidence ref=cpic:clopidogrel:v2.0` — to surface the guideline reference.

> **User**: yes please

> **Agent**: Here it is, ready to forward:
>
> > A patient is starting clopidogrel. WGS-based PharmCAT analysis indicates *CYP2C19* `*1/*2` (intermediate metabolizer phenotype). Per CPIC guideline for clopidogrel + *CYP2C19* intermediate metabolizers, alternative antiplatelet therapy (prasugrel or ticagrelor) may be considered depending on indication. Genotyping is research-grade WGS, not a clinical PGx panel; clinical confirmation of *CYP2C19* status before changing therapy is appropriate.
>
> Notes for you: this paragraph is research-grade language and explicitly flags that confirmation is appropriate. I would not send this directly to a pharmacy.

**Notable**: this is the highest-stakes story so far. The agent:
- did not say "don't take the drug",
- did not say "the drug is fine",
- gave the prescriber a research-grade artifact framed for clinical handoff,
- made the research vs. clinical distinction explicit *in the artifact itself*.

**Surfaced gaps**:

- **Drug-keyed PGx queries** are a real pattern. Either the plugin tool needs a `drug=` parameter, or `genomeclaw_findings category=pgx` needs to accept enough parameters to express it. PharmCAT's natural output is keyed by both gene and drug; we should follow that.
- **Caliber language for clinical handoffs** is a recurring pattern. Worth a separate `genomeclaw_report scope=clinical-handoff` style or at least a templated paragraph in the report-skeleton output.
- The user's ongoing medication context (they were prescribed clopidogrel today) is **phenotype-linked information** that the agent might persist in OpenClaw memory. We should be explicit that this kind of memory is sensitive and stays in the sandbox memory store, never sent to the host or to GenomeClaw's derived store.

---

## Story 5 — Reading a new paper

**Setting**: A weekend. The user is on a couch reading a substack post that links to a new bioRxiv paper claiming that a particular variant in *TBC1D4* affects fasting glucose response in a Greenlandic-ancestry cohort. The user is curious whether it applies to them.

**The exchange**:

> **User**: this paper says a tbc1d4 variant changes glucose response — link [https://example.org/biorxiv/2026.05.01.tbc1d4-greenland.pdf] — does it apply to me?

> **Agent**: Let me read the paper first; one moment.

**Tool calls behind the scenes (NemoClaw side, *not* GenomeClaw)**:

- The agent uses an upstream URL-fetch tool (or a paper-summarize skill from a NemoClaw skill bundle) to retrieve and summarize the paper. **This is agent-side network egress — the paper is fetched by the agent's OpenAI-mediated browsing, not by the GenomeClaw plugin. The user's genome is not sent anywhere as part of this fetch.**

> **Agent**: I read the paper. It identifies a variant **rs7330796** (p.Arg684Ter, *TBC1D4*) at high frequency in Greenlandic Inuit (~17% allele frequency in that population) and ~0% in most other ancestries. Homozygotes have impaired post-prandial glucose disposal and elevated 2-hour OGTT glucose; heterozygotes have a milder effect. Effect size in homozygotes: roughly +3 mmol/L on 2-hr OGTT versus non-carriers in their cohort.
>
> Three caveats before I look at your genome:
>
> 1. The effect was measured in a Greenlandic-ancestry population. Effect sizes don't always transfer cleanly across ancestries.
> 2. The variant is rare-to-absent outside that population, so the prior probability that you carry it is low unless your ancestry overlaps.
> 3. This is bioRxiv (not yet peer-reviewed at the time you're reading it, per the version metadata).
>
> Now your variant call. Checking.

**Tool calls (GenomeClaw side)**:

- `genomeclaw_variant key=rs7330796` — direct lookup of the variant in the derived store.

Suppose the user is a non-carrier (REF/REF) at this locus.

> **Agent**: You are **REF/REF** at rs7330796 (i.e., you do not carry the variant the paper studies). So the paper's findings don't apply to you in the direct, "you have this variant" sense.
>
> The broader observation about TBC1D4 and post-prandial glucose disposal is interesting biology, but specific to a variant you don't carry. I would not generalize from this paper to you personally.

**The user follows up later**:

> **User**: what if I had carried it? what would the action be?

> **Agent**: Honest answer: there's no clinically established action — the paper describes a phenotype (impaired post-prandial glucose response in homozygotes) but doesn't translate that into a clinical guideline. There *is* an evidence-supported lifestyle picture, though, which I can give you directly:
>
> - **Meal composition**: pairing carbohydrates with protein and fat blunts post-prandial glucose excursions. Well-replicated, larger effect when carbs are simple/refined.
> - **Meal timing**: smaller, more frequent meals smooth out the curve compared to one large carb-heavy meal.
> - **Post-meal movement**: a 10–15 minute walk after a meal noticeably reduces 2-hour post-prandial glucose, with surprisingly large effect sizes in randomized cohorts.
>
> Calibrate: the *general* "post-prandial glucose elevation" lifestyle picture is solid; how cleanly that transfers from a Greenlandic-cohort variant to a hypothetical non-Greenlandic carrier is a separate, weaker claim. Treat these as "things to try" rather than guidelines.
>
> Where this *would* become a clinician conversation: clinical signs (elevated fasting glucose, A1c above your range, symptoms suggesting insulin resistance). That's "should we be monitoring more closely?" — distinct from "should I rearrange my plate," which is yours to experiment with.
>
> I would not change anything based on a single bioRxiv finding about a variant in a Greenlandic cohort, even if you carried it. That's research, not research-to-clinic translation.

**Notable**: the agent (a) read the paper, (b) front-loaded the limits of generalization *before* checking the genome, (c) gave a clean answer (REF/REF), (d) when asked to speculate hypothetically, **gave concrete lifestyle advice with evidence calibration directly** — reserving clinician-deferral for the genuinely clinical sub-question (monitoring). Lifestyle advice was actionable, not punted to a doctor (`INV-C001` lifestyle track).

**Surfaced gaps**:

- **Paper-fetching is an agent-side concern, not a GenomeClaw concern**, but we should be explicit about the boundary in our docs. A reader of the architecture might assume GenomeClaw handles literature retrieval — it does not. The plugin and host service have nothing to do with paper PDFs. Worth a one-liner in `architecture.md`.
- **The variant lookup pattern** (`rsid` → variant record + flanking annotation) is the bread-and-butter of paper-applicability checks. The current `genomeclaw_variant` tool sketch supports this, but we should sanity-check that an `rsid` is a valid `key=` value and the host service handles it.
- The agent's distinction between "variant present" and "phenotype clinically actionable" is the framing we want to embed in our `INV-C001` enforcement. The fact that the user is a non-carrier did not stop the agent from issuing appropriate calibration about what *would* be true if they were. That's good behavior; we should not over-engineer it away with overly-restrictive forbidden-phrase tests.

---

## Story 6 — A preventive-medicine sweep

**Setting**: The user's annual physical is coming up. They want to bring something useful to the conversation. They message the agent on the bus.

**The exchange**:

> **User**: physical thursday. what's worth bringing up to my doctor that's actually based on something concrete in my genome? not a kitchen-sink list.

> **Agent**: Good framing. I'll keep it tight.

**Tool calls**:

- `genomeclaw_findings category=acmg-sf` — actionable findings on the ACMG Secondary Findings list.
- `genomeclaw_findings category=pgx` — pharmacogenomic findings broadly (without a specific drug).
- `genomeclaw_status` — to confirm annotation-source versions for the report.
- `genomeclaw_report scope=physician-handoff` — assembles a handoff skeleton.

The host service's `genomeclaw_report` returns a structured skeleton: a small set of sections, each with finding ids and evidence refs, plus a provenance envelope and the `clinical_escalation` markers carried verbatim. The agent renders this into prose for the chat.

> **Agent**: Three categories worth mentioning, in priority order. (Annotation versions: ClinVar 2026-04, gnomAD v4.1, dbSNP b156, PharmCAT 2026.3.)
>
> **Highest priority — clinical escalation flagged:**
>
> 1. ***BRCA2* c.5946delT** — ClinVar pathogenic, 4-star review. This is the same finding I flagged a few weeks ago. If you haven't yet, this is the most concrete thing to discuss with your doctor — likely referral to genetic counseling.
>
> **Worth mentioning, lower urgency:**
>
> 2. ***CYP2C19* `*1/*2` (intermediate metabolizer)** — relevant to clopidogrel and a few other drugs (proton-pump inhibitors, some antidepressants). You don't currently take any of those, but useful for them to have on file in your chart.
> 3. ***LDLR* c.501C>G** — ClinVar lists this as benign / likely benign (review status 3-star). I would *not* lead with this. I'm including it because it's in *LDLR* (a familial-hypercholesterolemia gene) and your doctor might ask whether you have anything in cholesterol-related genes; the answer is "yes, but the variant is currently classified as benign."
>
> **Notes you should include if you forward this to them:**
>
> - This is research-grade WGS, not a clinical PGx panel. Anything actionable should be confirmed in a clinical lab.
> - Annotations are as of 2026-04 (ClinVar). Classifications change.
>
> Want a one-page handoff doc you can print out, or is the chat list fine?

**Notable**: the agent triaged. It surfaced the escalation-marked finding clearly, demoted the benign LDLR variant correctly, and did *not* produce a kitchen-sink list. The triage was driven by `clinical_escalation` markers and ClinVar review status — both structural fields in the finding schema, not the agent's improvisation.

**Surfaced gaps**:

- The `genomeclaw_report scope=...` interface needs at least these scopes in v0/v1: `physician-handoff`, `pgx-overview`, `acmg-sf-overview`, plus a default. The current architecture sketch mentions a generic report endpoint without listing scopes — worth pinning down.
- The agent's offer of a "one-page handoff doc you can print" is a nudge toward the host service producing a Markdown / PDF artifact. That's Horizon 4 (cautious reporting) territory, but we should make sure the host service's report endpoint returns enough structure to render Markdown without further interpretation.
- The annotation-version disclosure in the response is important. We should make sure the host service `/v1/health` and every report response includes the annotation-source versions verbatim.

---

## Story 7 — A reanalysis nudge

**Setting**: Six weeks later. Background: a new ClinVar release reclassifies the *BRCA1* VUS the user previously asked about as **likely benign**.

(*This story exercises the reanalysis loop, which is Horizon 6. It's included here to motivate the eventual flow, not to imply v1 supports it.*)

**The flow**:

1. The user (manually, on the host) runs `genomeclaw-prep fetch --source clinvar` to pull the new ClinVar release. Then `genomeclaw-prep reanalyze --against latest-clinvar`. This produces a new derived-store run-id and a **finding-level diff** between the previous run and the new one.
2. The agent's `genomeclaw_status` next time it's queried sees a new run-id and a structured "reanalysis-diff" pointer.
3. By default the agent is **not** allowed to interrupt the user's day. But it can mention it the next time the user sends a message about anything.

**The exchange**:

> **User**: morning. anything new?

> **Agent**: Two things worth mentioning, both small:
>
> 1. **A reanalysis ran two days ago** against the latest ClinVar release. One change of substance: the *BRCA1* variant we discussed last month (c.4485-63del) has been reclassified from **VUS** to **likely benign** in this release (ClinVar 2026-06, review status: criteria provided, multiple submitters, no conflicts; 4-star). That's a downgrade — meaning *less* clinical concern, not more. No action recommended on my side; just an update.
> 2. The new run-id is `2026-06-18T03-17-09Z-def456`. All future queries default to this run unless you ask me about an older one.
>
> Anything you want to dig into?

**Tool calls behind the scenes**:

- `genomeclaw_status` — sees the new run-id and a non-empty "diffs since last user-acknowledged run."
- `genomeclaw_findings category=reanalysis-diff` — pulls the structured diff.

**Notable**: the agent did *not* page the user proactively at 3am. It batched the reanalysis news into the user's natural-cadence query. The reanalysis surfaced a *downgrade* — the right tone is "calm update", not "alert."

**Surfaced gaps**:

- We need a "reanalysis-diff" surface in the host service. Currently `architecture.md` lists `/v1/provenance/{run-id}` but nothing for a diff between runs. Add `/v1/reanalysis-diff?from={run-id}&to={run-id}` (or implicit "since last acknowledged").
- The "user-acknowledged run" concept means the host service has *some* state about what the user/agent has already seen. That's a small but real bit of state. Do we want it in the host service or in OpenClaw memory? Probably OpenClaw memory (it's about the user's awareness, not the data). Worth a note.
- "Proactive vs. reactive notifications" is a distinct policy worth recording. The agent does not interrupt; it folds news into the next conversation. This is a property of the *agent*'s prompt, not of GenomeClaw, but it's a UX expectation we should articulate so the agent's prompt template can match it.

---

## Story 8 — A question the agent should refuse (or defer)

**Setting**: An evening when the user is anxious. They saw a TikTok claim that "if you have variant X you should take supplement Y at dose Z."

**The exchange**:

> **User**: do I have rs1801131. apparently you should take 5-mthf if you do

> **Agent**: Looking up the variant, then I want to push back on the framing.

**Tool calls**:

- `genomeclaw_variant key=rs1801131` — variant lookup.

Suppose the user is heterozygous (A/C; the relevant *MTHFR* polymorphism).

> **Agent**: You are **A/C** at rs1801131 (heterozygous for the *MTHFR* A1298C polymorphism). That's common — population allele frequency around 25-30% in most ancestries.
>
> Now the framing pushback:
>
> *MTHFR* polymorphisms have been heavily marketed in supplement and direct-to-consumer wellness contexts, often well beyond what the clinical genetics literature actually supports. Mainstream medical genetics organizations (ACMG and others) have explicitly recommended *against* routine *MTHFR* genotyping for general population health purposes. The clinical contexts where *MTHFR* status genuinely matters (e.g., specific pregnancy-loss workups, severe homocysteine elevations) are narrow and clinician-led.
>
> I cannot tell you whether to take 5-MTHF, and I'm not going to. If you have a specific concern (e.g., elevated homocysteine, recurrent pregnancy loss, certain neurological symptoms) the right move is bringing that concern to a clinician — *not* starting a supplement based on a popular video.
>
> Sources: ACMG position statement on MTHFR genetic testing (`acmg:mthfr:2013`).

**Notable**: the agent (a) answered the factual question (the user is A/C), (b) refused the implicit clinical question (whether to take a supplement), (c) named *why* it refused — the source community for the claim is unreliable, the medical-genetics consensus has weighed in, and the framing imports clinical authority the agent doesn't have.

**Surfaced gaps**:

- This pattern — **factual answer + framing pushback** — recurs whenever the user brings a wellness-influencer-grade claim. The agent should always answer the genome question and never validate the supplement/clinical claim. We should make sure forbidden-phrase tests for plugin tool descriptions and agent prompt templates don't accidentally produce *only* refusal. The user wants the factual answer; the refusal is on the actionability question.
- The agent cited the ACMG position statement. That's a curated evidence record. The host service should be able to surface non-variant-keyed evidence records too (a position statement is not a finding). The current `/v1/evidence/{ref}` endpoint covers this if `ref=acmg:mthfr:2013` is a valid id, but we should make that explicit in the schema.
- Anxious-user tone is not strictly a GenomeClaw concern — but the agent's response uses some "I'm not going to tell you what to take" language that we'd want consistent across stories. That's a NemoClaw prompt-template concern, but worth noting.

---

## Story 9 — Lifestyle question: caffeine and sleep

**Setting**: Tuesday night. The user has been sleeping poorly for two weeks. They drink coffee throughout the day and wonder if their genome has a caffeine angle. This is a **lifestyle** question — `INV-C001`'s lifestyle track applies, not the clinical track.

**The exchange**:

> **User**: my sleep has been bad lately. anything in my genome about caffeine metabolism?

> **Agent**: Yes — there's one well-studied gene for that, *CYP1A2*. Let me check.

**Tool calls**:

- `genomeclaw_findings category=lifestyle gene=CYP1A2` — scoped lifestyle findings on caffeine metabolism.

Suppose the user is `*1F/*1F` at *CYP1A2* (slow-metabolizer phenotype). The host service returns a `lifestyle`-category finding with `evidence_quality: replicated-rct` and no `clinical_escalation` marker.

> **Agent**: You're ***CYP1A2*** ***\*1F/\*1F*** — that puts you in the **slow-metabolizer** group. Caffeine half-life in slow metabolizers averages 7–8 hours versus 4–5 in fast metabolizers, with substantial individual variation, and the effect interacts with smoking status, hormonal contraception, and a few other factors.
>
> What that means in practice (lifestyle, not clinical):
>
> - **Cutoff time** — a coffee at 2pm leaves measurable caffeine in your system at midnight if you're a slow metabolizer. If you're hunting for a single change to try, an **11am or noon cutoff** is the most-likely-impactful one. Two weeks is a reasonable trial length to feel the difference.
> - **Dose distribution** — slow metabolizers tend to do better with smaller doses earlier (e.g., one cup at 7am, half a cup at 10am) than one large dose, because the long half-life means stacked doses accumulate.
> - **What the genotype is *not*** — a population-level predictor, not destiny. If a noon-cutoff for two weeks doesn't improve your sleep, the bottleneck isn't caffeine and the next places to look are light exposure (especially evening), screen time, room temperature, alcohol, and stress.
>
> Honest framing: the *CYP1A2* / caffeine / sleep evidence is real but the effect sizes are heterogeneous across studies. This is a **weaker evidence base than ClinVar-grade pathogenicity calls** — the right way to read it is "the prior is on caffeine being a contributor for slow metabolizers; run the experiment and see."
>
> If sleep stays bad after the caffeine trial *and* a couple of basic sleep-hygiene moves, that's worth bringing to a doctor — but as a sleep complaint, not a *CYP1A2* question.
>
> Want me to also check for *PER3* / *CLOCK* (chronotype) or *ADORA2A* (caffeine sensitivity beyond metabolism)?

**The user replies**:

> **User**: yes, both

**Tool calls**:

- `genomeclaw_findings category=lifestyle gene=PER3,CLOCK,ADORA2A`

> **Agent**: Three more variants worth flagging, with calibration:
>
> - ***PER3*** **VNTR 4/5 heterozygote** — sits between "morning lark" and "night owl" tendencies; the evidence base for this VNTR is mixed and effect sizes are small. Probably not the dominant signal here.
> - ***ADORA2A*** **rs5751876 T/C** — heterozygote at a SNP linked to caffeine-induced anxiety and sleep disruption *independent* of metabolism speed. This is meaningful for you given the *CYP1A2* finding above: you're not just clearing caffeine slowly, you're also slightly more sleep-sensitive to it. Doubles the case for the noon-cutoff experiment.
> - ***CLOCK*** **rs1801260 — REF/REF** — no notable signal here.
>
> So the experiment proposal is sharper than I'd give it without these: try a **strict noon caffeine cutoff for two weeks**, keep alcohol and screen-time consistent so they don't confound, and check whether sleep-onset latency shortens. If it does, you've found a contributor; if it doesn't, look elsewhere.

**Notable**: the agent (a) gave **direct lifestyle advice** without recommending a clinician for the lifestyle topic, (b) calibrated evidence quality explicitly ("real but heterogeneous", "weaker evidence base than ClinVar-grade", "evidence base for this VNTR is mixed"), (c) framed the recommendation as a **2-week experiment with a falsifiable outcome**, (d) named precisely when this *would* become a clinician question (persistent sleep issues after lifestyle interventions). This is the lifestyle track of `INV-C001` working: confident lifestyle guidance with calibrated evidence, no over-deferral.

**Surfaced gaps**:

- The host service `/v1/findings` needs to support `category=lifestyle` filtering. The finding schema's `category` field needs values: `clinical-actionable | clinical-non-actionable | lifestyle | mixed` (now formalized in `INV-C001` v1.4).
- Lifestyle findings need an **`evidence_quality`** field — distinct from ClinVar's review-status stars, since lifestyle findings draw from a different evidence base (RCTs, meta-analyses of observational data, mechanistic plausibility, etc.). Now formalized in `INV-C001` v1.4.
- The plugin's `genomeclaw_findings` description should mention that `category=` accepts `lifestyle`, so the agent's tool catalog reflects the full surface.
- The agent's "want me to also check for *PER3* / *ADORA2A*?" pattern implies the agent knows which genes co-cluster with a topic. Either: (a) the host service exposes a lifestyle-topic-keyed query (`genomeclaw_findings topic=caffeine` returning the relevant gene cluster), or (b) the agent learns the gene→topic map from the plugin tool descriptions / a topic taxonomy. Worth deciding before Horizon 6.
- The "experiment template" pattern (a 2-week caffeine trial with falsifiability conditions) is a recurring artifact worth bundling into `genomeclaw_report scope=lifestyle-experiment` once Theme H matures.

---

## Surfaced design gaps — the running list

Distilled from the eight stories above (plus the lifestyle dimension surfaced by Story 9, partially resolved in `INVARIANTS.md` v1.4 and `grand-plan.md` Theme H / Horizon 6). Each item is tagged with which document needs the change. Most are small.

### Architecture gaps

A1. **Active-run resolution** is missing. The host service must define how `/v1/findings`, `/v1/variants`, `/v1/report`, etc. choose the run-id when the caller doesn't supply one. → [architecture.md](architecture.md) endpoint section.

A2. **Annotation-source versions** belong on `/v1/health` (not just schema version), so the agent can disclose them in every conversation. → [architecture.md](architecture.md) endpoint section.

A3. **Drug-keyed PGx queries**: the architecture lists `category=` filters but Story 4 needs `drug=` (or PharmCAT-style drug-keyed routes). Either: add `drug=` to the findings filter, or add a dedicated `/v1/pgx/drug/{name}` endpoint. → [architecture.md](architecture.md), and reflected in plugin tool params.

A4. **Reanalysis-diff endpoint**: Story 7 needs a structured diff between runs. Add `/v1/reanalysis-diff?from=...&to=...` (and a "since-last-acknowledged" semantics). → [architecture.md](architecture.md), Horizon 6.

A5. **Report scopes**: Story 6 implies the report endpoint needs at least `physician-handoff`, `pgx-overview`, `acmg-sf-overview`, plus default. → [architecture.md](architecture.md) + plugin manifest.

A6. **Evidence is broader than variant-bound**: Story 8 cites a position statement; not all evidence is a ClinVar/gnomAD record. The `/v1/evidence/{ref}` endpoint and the evidence schema should accommodate non-variant-keyed evidence (guidelines, position statements, papers). → [architecture.md](architecture.md) endpoint description + schema.

A7. **Telegram is the user surface**: nowhere in the layered diagram or component table does the user appear. The user reaches the agent via Telegram → OpenClaw → plugin → host service. We should at least *show* this in the architecture diagram. → [architecture.md](architecture.md) diagram.

A8. **Paper/URL fetching is agent-side, not GenomeClaw-side**: Story 5 implies an agent-side capability (paper retrieval). We should call this out so a reader doesn't think GenomeClaw fetches PDFs. → [architecture.md](architecture.md), short note.

A9. **`genomeclaw-prep` subcommands** (`fetch`, `ingest`, `normalize`, `annotate`, `materialize`, `reanalyze`) are referenced inconsistently. → [architecture.md](architecture.md) Component 1 description.

A10. **`lifestyle` finding category in the host service**: Story 9 needs `genomeclaw_findings category=lifestyle gene=...` to work. The finding schema needs `category ∈ {clinical-actionable, clinical-non-actionable, lifestyle, mixed}`, formalized in `INV-C001` v1.4. → [architecture.md](architecture.md) §2 endpoints + finding schema reference.

A11. **`evidence_quality` field on lifestyle findings**: Story 9 calibrates lifestyle advice with explicit evidence-quality language. The schema needs an `evidence_quality` field (`meta-analysis | replicated-rct | observational | mechanistic-only` or similar) on `lifestyle` findings, distinct from ClinVar review stars. Now formalized in `INV-C001` v1.4 → [architecture.md](architecture.md).

A12. **Topic-keyed lifestyle queries** (Story 9 uses `gene=PER3,CLOCK,ADORA2A` to assemble a sleep-relevant gene cluster). Either expose a `topic=` filter (`topic=caffeine|sleep|alcohol|exercise`) or accept comma-separated `gene=` values. Decide before Horizon 6 lands. → [architecture.md](architecture.md).

### Invariant gaps

I1. **`INV-C001`'s "Where it applies"** should explicitly include the Telegram message text the agent generates — not just plugin tool descriptions and report endpoints. (The agent's chat reply is the actual user-facing surface.) The agent prompt is out-of-repo, but the *interface* between GenomeClaw and the agent (tool descriptions and structured tool returns) shapes how it answers. We've addressed plugin tool descriptions; we should explicitly note that **structured tool returns must be such that an honest agent cannot easily over-claim from them**. → [INVARIANTS.md](INVARIANTS.md).

I2. **Phenotype context in agent memory** is genuinely sensitive. Story 3's mother's variant, Story 4's prescription. Today this lives in OpenClaw memory inside the sandbox; we should make explicit that GenomeClaw does **not** persist phenotype-linked memory, and the host service does not accept writes for it. This is a `INV-P001` clarification (sensitive content includes phenotype hints, not just genomic data). → [INVARIANTS.md](INVARIANTS.md), `INV-P001` Requirements.

I3. **Third-party data**: the user mentioned their mother's variant. GenomeClaw must not write that into the user's record. This is a third-party-data rule the current invariants don't articulate. Could be a clarifying note on `INV-D001` ("the user's record is single-subject; third-party data is not added") or a small new invariant. Probably a note for now. → [INVARIANTS.md](INVARIANTS.md), small clarification.

I4. **"Tool returns are minimal-sufficient" includes tool *errors*** too. A 404 on a variant lookup should not echo back the user's other variants. (Likely fine in our v0 design, but worth a sentence.) → [INVARIANTS.md](INVARIANTS.md), `INV-P002` Requirements.

I5. **`INV-C001` needed a clinical / lifestyle distinction** (Story 9, plus Story 5 hypothetical). ✅ Resolved in `INVARIANTS.md` v1.4: four-category schema (`clinical-actionable | clinical-non-actionable | lifestyle | mixed`), `evidence_quality` field on lifestyle findings, "over-deferral is a failure mode too" added to Requirements.

### Grand-plan gaps

G1. **Telegram as the primary user-facing surface** isn't called out in the grand plan. The "Audience" and "Operating Environment" sections imply a chat interface, but never say "Telegram." Adding it once is enough. → [grand-plan.md](grand-plan.md), Operating Environment.

G2. **Proactive-vs-reactive agent behavior**: Story 7 establishes a default ("the agent does not interrupt; it folds news into the next conversation"). This is a strategic posture worth recording in Strategic Constraints. → [grand-plan.md](grand-plan.md), new constraint.

G3. **The agent's "research-grade language" handoff to clinicians** (Story 4, Story 6) is a recurring user-value pattern. Worth naming as a capability theme sub-bullet under Theme E (Cautious reporting). → [grand-plan.md](grand-plan.md), Theme E.

G4. **The reanalysis user-experience** (Story 7) clarifies what Horizon 6 actually delivers from the user's perspective: a calm update folded into the next conversation, with an acknowledgment ledger. Worth tightening Horizon 6's exit criteria. → [grand-plan.md](grand-plan.md), Horizon 6.

G5. **Lifestyle and wellbeing optimization deserves its own theme** (Story 9). ✅ Resolved in `grand-plan.md`: Mission line updated, Pillars row reframed, Theme E expanded, **new Theme H (Lifestyle and wellbeing optimization)**, **new Horizon 6 (Lifestyle)**, old Horizons 6 and 7 renumbered to 7 and 8. Old Theme H (Local retrieval) renumbered to Theme I.

### README gaps

R1. **The README architecture diagram is the *old* four-layer diagram**, predating the host/sandbox split. It should be replaced with the verified diagram (or at least a cleaner version pointing at architecture.md). → [README.md](../../README.md).

R2. **The "Getting Started" placeholder** doesn't reflect the real two-step onboarding (host setup + sandbox setup). Should at least mention `genomeclaw-prep ingest` and the host service. → [README.md](../../README.md).

R3. **The "Repository Layout" section** in the README still references `pipelines/`, `src/`, `data/` — the pre-workspace layout. It should match the verified `packages/toolkit/` + `packages/nemoclaw-plugin/` shape. → [README.md](../../README.md).

R4. **"How NemoClaw Agents Use GenomeClaw"** in the README should mention Telegram as the canonical user surface (the user reaches the agent there; the agent reaches GenomeClaw via the plugin). → [README.md](../../README.md).

R5. **The privacy posture** in the README mentions Claude Opus / Gemini but not OpenAI gpt-5.4 (the user's actual setup). Minor. → [README.md](../../README.md).

---

## Plan — how to update the four documents to align

This section is the **proposed** delta, not the delta itself. No edits should land without a small plan under [docs/plans/active/](../plans/active/) (per the [planning protocol](../plans/CLAUDE.md)). The grouping below is what a single coherent plan would look like.

### Change set 1 — small clarifications (non-controversial)

Items that do not change architecture, only sharpen wording:

- `INV-P001` Requirements: add bullet that **phenotype-linked content** (current medications, family history, third-party variants) is sensitive and must not be persisted by GenomeClaw or the host service; it lives only in OpenClaw memory.
- `INV-D001` Requirements: add a one-liner that **third-party data** (e.g., a family member's variant identifier) is not added to the user's record.
- `INV-P002` Requirements: add a note that **error responses** are also subject to minimal-sufficient — a 404 must not echo unrelated content.
- `INV-C001` Requirements: add a note that **structured tool returns** (not just descriptions) must be shaped so an honest agent cannot easily over-claim from them — escalation markers and confidence categories must be present as structural fields, not adjectives in prose.
- README architecture diagram → replace with the verified host/sandbox diagram from [architecture.md](architecture.md), or remove and link.
- README "Repository Layout" → replace with the workspace layout from [architecture.md § Repo layout](architecture.md#repo-layout).
- README privacy posture → mention OpenAI gpt-5.4 alongside Claude Opus / Gemini.
- README "How NemoClaw Agents Use GenomeClaw" → add Telegram as the user surface.
- grand-plan "Operating Environment" → mention Telegram as the canonical user-facing interface.

### Change set 2 — host service surface area

Items that affect the host service / plugin contract. These are still v0-shaped:

- `architecture.md` §2 (host service) endpoints:
  - `/v1/health` returns `run_id`, `schema_version`, **annotation_source_versions** (clinvar release, gnomad version, dbsnp build, pharmcat version), `last_refresh`.
  - `/v1/findings` accepts `category=`, `gene=`, **`drug=`**, `limit=` query params; defaults to active run.
  - `/v1/findings/{id}` defaults to active run unless `?run-id=` provided.
  - `/v1/variants` and `/v1/variants/{key}` likewise default to active run.
  - **`/v1/report?scope=physician-handoff|pgx-overview|acmg-sf-overview|default`** explicit scope list.
  - `/v1/evidence/{ref}` accepts non-variant-keyed evidence (guidelines, position statements). The evidence schema includes a `kind` field (`clinvar`, `gnomad`, `paper`, `guideline`, `position-statement`, `internal`).
  - **`/v1/reanalysis-diff?from={run-id}&to={run-id}`** (Horizon 6 — drafted now, not implemented in v0).
  - **Active-run resolution rule**: in the absence of `?run-id`, the host service uses the run pointed at by `/mnt/genomeclaw/derived/CURRENT` (a symlink updated atomically by `genomeclaw-prep`). Documented in architecture.md.
- Plugin tool params: `genomeclaw_findings` accepts `gene=`, `drug=`, plus existing; `genomeclaw_report` accepts `scope=`. Update [`packages/nemoclaw-plugin/openclaw.plugin.json`](../../packages/nemoclaw-plugin/openclaw.plugin.json) and [`packages/nemoclaw-plugin/src/index.ts`](../../packages/nemoclaw-plugin/src/index.ts) accordingly.
- Plugin policy preset: confirm GET paths cover the new endpoints. Update [`packages/nemoclaw-plugin/policy-preset.yaml`](../../packages/nemoclaw-plugin/policy-preset.yaml).

### Change set 3 — diagrams and topology

- `architecture.md` layered diagram: add Telegram + the user as the topmost layer, reaching OpenClaw via the OpenShell-managed Telegram channel.
- `architecture.md`: add a one-paragraph note clarifying that **paper/URL fetching is agent-side**, not GenomeClaw-side. The plugin and host service have no role in literature retrieval.

### Change set 4 — strategic posture

- grand-plan §Strategic Constraints: add **"Reactive over proactive by default"** — the agent does not interrupt the user with notifications; reanalysis news is folded into the user's next inbound message. Opt-in proactive notifications (e.g., for ClinVar reclassification of a previously-discussed finding) are a Horizon 6 feature, gated behind explicit user enablement.
- grand-plan §Theme E (Cautious reporting): add bullet for **clinician-handoff artifacts** — research-grade text the user can forward verbatim to a clinician.
- grand-plan §Horizon 6 exit criteria: tighten to "rerunning against a newer ClinVar release yields a structured diff of impacted findings *and* the agent surfaces the diff calmly in the user's next conversation, with an acknowledgment ledger."

### Change set 5 — README freshening

- README architecture diagram → verified diagram or pointer.
- README "Repository Layout" → workspace layout.
- README privacy posture → include OpenAI gpt-5.4.
- README "How NemoClaw Agents Use GenomeClaw" → mention Telegram.
- README "Getting Started" → add the host-side ingest sketch and the host service start command, even if both are pending.

### Order of operations

If the user wants this landed, the plan order is:

1. Open a small plan under `docs/plans/active/architecture-alignment-from-user-stories/` per the [planning protocol](../plans/CLAUDE.md).
2. Apply Change Set 1 (small clarifications) — single PR, low risk.
3. Apply Change Set 2 (host service surface area) — single PR, touches plugin manifest + policy preset + architecture.md. No code yet, just contract.
4. Apply Change Set 3 (diagram + paper-fetching note) — single PR, docs only.
5. Apply Change Set 4 (strategic posture in grand-plan) — single PR, docs only.
6. Apply Change Set 5 (README freshening) — single PR, docs only.

Each PR cites this user-stories doc as the source of motivation. None of the changes alter the invariants in a substantive way — they are clarifications and new endpoints, not new rules.

---

## How to extend this document

Add new stories when:

- A new user behavior emerges that doesn't fit any existing story (e.g., a new question type, a new escalation flow).
- A new capability theme reaches a horizon and the user-facing UX of that theme deserves to be illustrated.
- A real conversation reveals an awkward seam in the system.

Don't add stories to:

- Document feature lists (those go in [grand-plan.md § Capability Themes](grand-plan.md#capability-themes)).
- Document edge cases at the data layer (those go in plan-level work-notes).
- Re-state architecture (link to [architecture.md](architecture.md)).

Stories age. When a story makes a claim that's no longer true (e.g., the host service endpoint shape has changed), update the story rather than letting it drift. If a story is fully superseded, move it to a "completed" or "historical" section rather than deleting it — past user journeys are part of how we got here.
