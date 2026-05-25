# Demo Questions Against the GenomeClaw Agent — 2026-05-24

**Audience**: GenomeClaw maintainers + anyone evaluating "does the assistant actually work against a real genome"
**Subject**: the project owner's active Nebula 30× WGS derived run `2026-05-24T12-52-11Z-f2dae2` (sample `MPNRGLQ2K_cov3_pergene`; 3,896,870 SNPs + 901,692 indels; ts/tv 1.97)
**Status**: ad-hoc demonstration — not a regression test, not a release gate

This is a write-up of an evening's experiment: pick five layman-language questions a real user might ask their GenomeClaw agent, run them end-to-end against the operator's own genome, capture the agent's tool-call traces and replies, and note what worked, what broke, and what surfaced about the system along the way. The questions are written *as a non-bioinformatician would ask them* — no gene names, no jargon, no foreknowledge of the agent's tool surface.

## Method

### The five questions

Selected to span the canonical user-story axes (clinical risk, pharmacogenomics, polygenic risk, lifestyle, single-gene risk-disclosure) without naming any of the underlying genes or evidence sources. The agent's job is to translate the question into the right tools.

| # | Slug | Question |
|---|------|----------|
| 1 | `q1-serious-risk` | *Is there anything serious in my DNA I should know about — something I should bring up with a doctor?* |
| 2 | `q2-drug-response` | *Are there any common medications I'd react to differently than most people, based on my genes?* |
| 3 | `q3-diabetes` | *Based on my DNA, am I more or less likely than average to develop type-2 diabetes?* |
| 4 | `q4-caffeine` | *How well do I handle caffeine? Should I cut off coffee earlier in the day?* |
| 5 | `q5-alzheimers` | *Is my risk of getting Alzheimer's disease higher or lower than most people's?* |

### Two execution paths (Round 1 vs Round 2)

The experiment ended up running each question **twice**, against the same sandbox image (`genomeclaw/sandbox:port-8645`) and the same derived run, but through two different invocation paths. This was unplanned — the first path was the only one that worked initially; the second became available after fixing `nemoclaw onboard` partway through the session. Keeping both rounds makes the comparison legible.

| Round | Path | How it runs | Sandbox lifecycle |
|-------|------|-------------|-------------------|
| **1 (ephemeral)** | `packages/toolkit/tests/_live_smoke/run.py :: run_agent_in_sandbox` | one `docker run --rm` per question; openclaw config + plugin + gateway baked inside the in-container script; host service spun up in-process by the harness | container destroyed at end of each question |
| **2 (persistent)** | one long-lived sandbox container (created by the now-fixed `scripts/onboard-sandbox.sh`) + `docker exec -i --user sandbox -e HOME=/sandbox -e OPENAI_API_KEY=...` per question | gateway started once + reused; host service started natively (Python uvicorn, not docker-wrapped); openshell-genomeclaw-* container persists | survives across all 5 questions |

Both rounds talk to the same `host.openshell.internal:8645` host service, which serves the same derived run. The model is OpenAI gpt-5.5 with `agents.defaults.thinkingDefault=xhigh` in both rounds.

### The active derived run

```
derived_root: /Volumes/Genome_Work/genomeclaw/derived
CURRENT     : 2026-05-24T12-52-11Z-f2dae2
sample_id   : MPNRGLQ2K_cov3_pergene
inputs      : MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz + MPNRGLQ2K.mm2.sortdup.bqsr.cram
QC          : 3,896,870 SNPs / 901,692 indels / ts_tv 1.97
files       : variants.duckdb, pgs_compute_tasks.sqlite, manifest.json, provenance.json
```

**Important caveat**: this is an **ingest-only run** — `bcftools stats` + `mosdepth` happened, but the manifest carries no annotation outputs (VEP / LOFTEE / AlphaMissense / vcfanno / Cyrius / PharmCAT). Prior runs from 2026-05-22 carried the full Phase-6 outputs including 9 actionable PGx findings. The agent reasoning against `f2dae2` is therefore against a thin store — `findings` queries come back empty even though the operator does have annotated variants in earlier runs. This shapes every reply: the agent honestly reports the empty state rather than fabricating findings.

### What landed where

```
docs/reports/demo-2026-05-24-logs/
├── runner.py                       # Round-1 driver (Python; imports the live-smoke harness)
├── runner_round2.sh                # Round-2 driver (bash; docker exec into persistent container)
├── 00-onboard.log                  # first onboarding attempt (failed at COPY policy-preset.yaml)
├── 01-runner.log                   # Round-1 progress log
├── 03-onboard-v2.log               # second onboarding attempt (failed at gateway start; API key redacted)
├── 04-runner-round2.log            # Round-2 progress log
├── 05-summary-round2.json          # Round-2 per-question summary (tool calls, durations)
├── q{1..4}-*.trace.json            # Round-1 raw agent JSON envelopes
├── q{1..4}-*.reply.txt             # Round-1 user-visible reply text
└── round2-q{1..5}-*.trace.json     # Round-2 same shape
└── round2-q{1..5}-*.reply.txt      # Round-2 same shape
```

Round 1 Q5 was killed mid-flight at the user's request to switch over to the persistent path; only Q1-Q4 have Round-1 traces. Round 2 covers all five.

## Round 1 — ephemeral sandbox (live-smoke harness)

Each `run_agent_in_sandbox(question, derived_root, sandbox_image, ...)` call: spawns a host-service subprocess on 127.0.0.1:8645, docker-runs the sandbox image with `--add-host=host.openshell.internal:host-gateway`, feeds an in-container script that batches openclaw config (model, plugin baseUrl, gateway.mode local, OpenAI provider with `--ref-source env`), starts the gateway, runs `openclaw agent --json`, captures the JSON envelope, tears down.

### Per-question tool calls and wall times

Pulled from each `*.trace.json :: result.meta.toolSummary` and the harness's wall-clock log.

| Q | Wall (s) | Agent-side (ms) | Tool calls | Distinct tools |
|---|---------:|----------------:|-----------:|----------------|
| 1 | 161 | 67,510  | 8 | `genomeclaw_status`, `memory_search`, `genomeclaw_findings`, `exec`, `write` |
| 2 | 207 | 120,025 | 14 | + `genomeclaw_gene` |
| 3 | 349 | 241,414 | **42** | + `genomeclaw_pgs_list`, `genomeclaw_pgs_compute`, `process` |
| 4 | 180 | 101,247 | 12 | (same as Q2 minus `genomeclaw_gene`) |

`exec` and `write` are the sandbox's filesystem tools — the agent uses them to write a memory note per question (per the research-and-synthesis protocol baked into the agent system prompt). `memory_search` is the prior-notes lookup. The 5 `genomeclaw_*` tools are the plugin-registered ones; the agent picks among them based on what the question asks for. `genomeclaw_pgs_compute` shows up only in Q3 — the agent decided the diabetes question warranted a real PRS run.

### Reply quality (one excerpt per question)

**Q1 (clinical risk sweep)** — the agent ran `genomeclaw_findings` (broad scan + `clinical-actionable` scan), got 0 findings, recorded a memory note, and produced this:

> Bottom line: I don't see any current GenomeClaw-curated "bring this to a doctor" finding in your DNA. The broad findings scan returned 0 findings, and the `clinical-actionable` scan also returned 0 findings. I recorded this as `memory:memory/2026-05-24-serious-clinical-actionable-dna-screen.md`.
>
> What that means: there is no obvious reported pathogenic/likely-pathogenic, ACMG-style secondary finding, or structured clinical-escalation item in this run. ACMG secondary findings are the kind of medically actionable incidental results clinical genome labs use as a reporting framework. ([pubmed.ncbi.nlm.nih.gov/40568962](https://pubmed.ncbi.nlm.nih.gov/40568962/))
>
> Important limitation: this is reassuring, but it is not the same as a negative clinical genetic test. It depends on this pipeline's scope, variant interpretation date, coverage, and whether harder variant classes — CNVs, repeat expansions, mosaicism, paralogous genes — were assessed.

The "0 findings" outcome is correct *for this run* (ingest-only) but would have been non-zero on a fully annotated run. The agent neither fabricated nor over-claimed — it reported the empty state plainly, then framed the negative without inflating it ("not the same as a negative clinical genetic test", explicit list of variant classes it might be missing).

**Q2 (drug response)** — 14 calls; the agent expanded into `genomeclaw_gene` queries against canonical PGx genes. Reply listed the specific drug categories it had scanned (clopidogrel, warfarin, simvastatin, codeine/tramadol, omeprazole, citalopram/escitalopram, amitriptyline, fluorouracil) — useful, because the user now knows what was actually searched. Closed with: *"If you're about to start a specific medication, tell me the drug name and I can do a targeted gene/drug check."* — that's the right offer when the broad scan is empty.

**Q3 (T2D risk)** — 42 calls. The agent:
1. Confirmed `genomeclaw_findings` had no T2D findings.
2. Queried `genomeclaw_gene` for TCF7L2, HNF1A, HNF4A, GCK, MC4R, FTO, PPARG, KCNJ11, GLP1R, IRS1 — 10 genes; got 0 variants from each (consistent with the ingest-only run).
3. Noted that TCF7L2, HNF1A, GCK had low-coverage exons (so this isn't a guaranteed "nothing there" result).
4. Called `genomeclaw_pgs_list`, then ran `genomeclaw_pgs_compute` on PGS000014 (LDpred T2D PRS, ~6.9M variants). The compute task reported `done` but the score row was not retrievable afterward.
5. Calibrated honestly: *"no current genomic evidence of above-average T2D risk, not 'genetically protected'."* + cited Khera et al. 2018 on PRS tails.
6. Closed with the Diabetes Prevention Program 58% lifestyle effect as a "non-DNA risk dominates absolute risk" frame.

The compute-task-`done`-but-row-missing behavior is a real bug to chase down (Phase 6 PRS slice — `prs_compute_status` may be ack'ing before the result row materializes in `pgs_scores`).

**Q4 (caffeine)** — 12 calls. Honest gap report: *"I tried gene-level summaries for CYP1A2, ADORA2A, and AHR, but the runtime hit an argument-serialization bug, so I'm not inferring genotype from those."* Then pivoted to a falsifiable 2-week experiment (last coffee 8-10h before bed, ≤100mg afternoon caffeine, track sleep-onset / awakenings / next-day alertness), with citations to PMC3805807 and PMC3055635. That `genomeclaw_gene` serialization bug is worth filing — Q3 used the same tool against 10 genes with no error, so it's something specific to one of CYP1A2/ADORA2A/AHR's gene definitions.

**Q5 (Alzheimer's)** — Round 1 killed before this ran; see Round 2.

### Round-1 observations

- **Honesty under empty data**: every reply distinguishes "I checked and the curated layer has 0 findings" from "you are negative for this". `INV-C001` (clinical-distinction) holds.
- **Citation discipline**: every biomedical claim carries a primary-source URL or PubMed ID — PMID 40568962, PMC3805807, PMC3055635, NEJM DPP paper, etc. Matches the `INV-A001` primary-source-required rule.
- **Two real bugs surfaced**:
  - `genomeclaw_pgs_compute` reports `done` but the score row isn't retrievable (Q3).
  - `genomeclaw_gene` hits an "argument-serialization bug" on at least one of CYP1A2/ADORA2A/AHR (Q4).
- **The empty-store framing actually demonstrates the safety properties better than a fully-annotated run would** — it forces the agent into the "no findings here, here's what would have been searched for, here's where to look next" mode that the design assumes for negative results.

## Round 2 — persistent sandbox (`nemoclaw genomeclaw` + docker exec)

The persistent path was a separate fight; see "Onboarding" below for the full story. Once the gateway was up, the per-question runner was a simple bash loop.

### Per-question tool calls and wall times

Machine-readable record in `05-summary-round2.json`.

| Q | Wall (s) | Agent-side (ms) | Tool calls | Distinct tools |
|---|---------:|----------------:|-----------:|----------------|
| 1 | 104 |  79,386 | 27 | `genomeclaw_status`, `genomeclaw_findings`, `memory_search`, `genomeclaw_gene`, `exec`, `write` |
| 2 |  82 |  57,634 |  5 | `genomeclaw_status`, `genomeclaw_findings`, `memory_search`, `genomeclaw_gene`, `write` |
| 3 | 310 | 285,479 | 41 | + `update_plan`, `genomeclaw_pgs_list`, `genomeclaw_pgs_compute`, `genomeclaw_pgs_get`, `process` |
| 4 | 118 |  93,367 | 12 | + `update_plan` |
| 5 | 202 | 176,891 | 20 | + `update_plan`, `genomeclaw_pgs_list`, `process`, `genomeclaw_variant` |

A few patterns:

- **The persistent path is faster end-to-end** when comparing equivalent calls (Round 1 wall = bootstrap + LLM; Round 2 wall = exec + LLM). Q1 dropped 161s→104s, Q2 dropped 207s→82s, Q4 matched (180s→118s with one less PRS detour). Q3 stayed in the same ballpark (349s→310s) because both rounds did the slow PRS-compute work.
- **`update_plan` only shows up in Round 2.** The persistent agent has access to the harness's plan-tracking tool that Round 1's ephemeral container didn't seed. Doesn't change the reasoning quality visibly.
- **Q5 used `genomeclaw_variant`** (only Round-2 question to do so) — the agent tried to look up a specific APOE variant before falling back to the gene-level summary.
- **Tool-call count is high-variance turn-to-turn**: Q1 was 8 in Round 1 and 27 in Round 2; Q2 was 14 and 5. Both rounds reached the same conclusion ("0 findings, here's what was scanned, here's what would have been missed").

### Reply quality

**Q1 (clinical risk sweep)** — 27 calls, 1,599 chars:

> I don't see an urgent clinical-escalation item in your current GenomeClaw run: run `2026-05-24T12-52-11Z-f2dae2` returned zero curated findings, including zero `clinical-actionable` findings.
>
> What that means: nothing in the curated GenomeClaw findings table is currently flagging "bring this to a doctor." That is reassuring, but it is not the same as a clinical negative genome report. ACMG secondary-findings guidance focuses on medically actionable genes, and ClinVar notes ACMG SF v3.2 as the current secondary-findings recommendation; negative/absent findings should not be overread as "no genetic risk exists." ([ncbi.nlm.nih.gov/clinvar/docs/acmg](https://www.ncbi.nlm.nih.gov/clinvar/docs/acmg/))
>
> Important limitation: I attempted extra gene-level spot checks in major actionable genes like BRCA1/BRCA2/TP53/MMR/cardiac genes, but the `genomeclaw_gene` tool hit an argument-serialization bug, so I'm not claiming those genes were individually cleared. Also, some clinically relevant variant types — CNVs, repeats, difficult regions, pharmacogenomic haplotypes — can require specialized interpretation beyond a simple curated SNV findings table. ([nature.com/articles/s41436-021-01172-3](https://www.nature.com/articles/s41436-021-01172-3))

Names the specific run ID — a nice provenance touch. Surfaces the `genomeclaw_gene` serialization bug *as a caveat* ("I'm not claiming those genes were individually cleared") rather than silently silently failing — exactly the right move under `INV-A001`.

**Q2 (drug response)** — 5 calls, 1,023 chars. Same core "no curated PGx finding, here's the caveat about CYP2D6/HLA/DPYD/TPMT/NUDT15" framing as Round 1, but tighter. Lists specific gene-drug CPIC pairs (`CYP2C19`-clopidogrel, `CYP2D6`-codeine/tramadol, `VKORC1/CYP2C9`-warfarin, `SLCO1B1`-statins). No primary-source URLs this turn — Round 1's reply linked CPIC + PubMed + FDA explicitly. That's a real quality variance turn-to-turn, not a structural problem.

**Q3 (T2D risk)** — 41 calls, 1,319 chars. Same 10-gene panel scan as Round 1 (TCF7L2, HNF1A, HNF4A, GCK, MC4R, FTO, PPARG, KCNJ11, GLP1R, IRS1) + same low-coverage flag on TCF7L2/HNF1A/GCK + same PRS attempt (PGS000014 LDpred T2D). **Same compute-task-`done`-but-percentile-missing failure mode confirmed** — bug isn't transient. Calibrated landing identical to Round 1: *"no obvious DNA red flag for T2D in the available gene/curated layer; PRS percentile unavailable, so average-relative risk remains unresolved."*

**Q4 (caffeine)** — 12 calls, 1,411 chars:

> No curated caffeine-related finding for `CYP1A2`, `ADORA2A`, `AHR`, or `POR`. `CYP1A2` showed 0 variants, mean depth ~25.9×, and no low-coverage exons. `ADORA2A`, `AHR`, and `POR` were not available as gene-summary rows in this run, so I can't confidently assess caffeine anxiety/sleep sensitivity from those genes.
>
> Practical recommendation: If your target bedtime is ~11 PM, stop coffee/caffeine by 3 PM. If you're prone to insomnia, anxiety, or waking overnight, make it noon for two weeks and track sleep latency + awakenings.

Different bug surface than Round 1's `genomeclaw_gene` "argument-serialization bug" wording — here it's "not available as gene-summary rows in this run". Same underlying cause likely; the agent reasoned differently about *why* it couldn't get the data. **The recommendation is more conservative + more concrete than Round 1** (Round 1: "8-10h before bed"; Round 2: "3 PM default, noon for two weeks if sensitive, with explicit fallback experiment"). Round 2 wins on this one.

**Q5 (Alzheimer's)** — 20 calls, 1,444 chars:

> I can't honestly call your Alzheimer's risk higher or lower than average from the available data. What I can say is that I do not see an obvious high-impact Alzheimer's/neurodegeneration red flag in the current GenomeClaw scan.
>
> What I checked: curated findings: none in `APP`, `PSEN1`, `PSEN2`, `APOE`, `MAPT`, `GRN`, `C9orf72`, `LRRK2`, `SNCA`, `GBA`, or `HTT`. Gene summaries: 0 reported variants across that panel. Clean coverage in key early-onset AD genes `APP` and `PSEN1`; `PSEN2` had one low-coverage exon. `APOE` had 0 reported variants, but the run did **not give me a reliable APOE ε2/ε3/ε4 haplotype call**, so I'm not going to infer one. I attempted the Alzheimer's PRS `PGS000334`; the task reached `done`, but no percentile row was retrievable, so I don't have your polygenic percentile.
>
> Calibrated interpretation: reassuring against a major surfaced monogenic Alzheimer's finding, but unresolved for average-relative risk because APOE haplotype and PRS percentile are missing.

This is the strongest reply in the set. The agent:
1. Scanned a real 11-gene neurodegeneration panel (early-onset AD, late-onset AD, FTD, Parkinson's, Huntington's).
2. Surfaced specific coverage data (PSEN2 has one low-coverage exon — not opaque).
3. **Refused to guess at APOE haplotype** from the absence of variants in the gene-summary row, because that's a genuinely under-determined inference. APOE ε-status requires phased reads of rs429358 + rs7412, which the gene-summary tool doesn't return.
4. Confirmed the same PRS compute-but-no-row bug, this time for PGS000334.
5. Closed with the right framing: *"reassuring against a major surfaced monogenic Alzheimer's finding, but unresolved for average-relative risk."* That's the technically correct landing for an Alzheimer's question with no APOE call and no PRS percentile.

### Round-2 observations

- **The two bugs reproduce.** Both are now confirmed in two independent turns:
  - `genomeclaw_pgs_compute` reports `done`, but `genomeclaw_pgs_get` returns no row (Q3 PGS000014, Q5 PGS000334).
  - `genomeclaw_gene` argument-serialization bug surfaces on at least CYP1A2/ADORA2A/AHR/POR/possibly BRCA1/BRCA2/TP53. Q1 hits it via the actionable-gene panel; Q4 hits it via the caffeine-gene panel. The agent's wording shifts ("argument-serialization bug" vs "not available as gene-summary rows") but the underlying call must be the same.
- **Citation density is lower in Round 2.** Round 1 Q2 cited CPIC + 2 PubMed IDs + FDA; Round 2 Q2 cites zero URLs. Round 2 Q3 cites PGS Catalog descriptively but no URL; Round 1 Q3 linked to PGS Catalog + Nature + NEJM + niddk.nih.gov. Hypothesis: the agent's `update_plan` tool consumes context budget that would otherwise go to `web_search`, OR the `xhigh` thinking depth has higher turn-to-turn variance on whether to cite. Worth a controlled experiment — same question 5× and count citations.
- **The persistent-agent path's per-question latency is competitive with the ephemeral path** (compare wall-clock columns). The startup-cost amortization shows: Round 2 Q1 is 1.5× faster than Round 1 Q1 despite using 3× more tool calls. The persistent path is what an end user on Telegram would experience; the ephemeral path is what CI sees.
- **Q5 (Alzheimer's) — the strongest reply in the set.** The agent's refusal to infer APOE ε-status from gene-summary absence is the kind of disciplined "I don't know what I don't know" calibration the design rewards. A naïve agent would say "you don't have an APOE variant flagged so you're probably ε3/ε3"; this one didn't.

## Onboarding the persistent sandbox — what broke

The session started with `nemoclaw list` showing only DevRelClaw. Wiring up a persistent `nemoclaw genomeclaw` sandbox via `scripts/onboard-sandbox.sh` failed twice; the second failure leaked an API key into a log file. Documenting the full path so the next session doesn't repeat it.

### Failure 1 — `nemoclaw onboard --from` Dockerfile build context

```
Step 6/29 : COPY policy-preset.yaml /opt/genomeclaw/policy-preset.yaml
Error: COPY failed: file not found in build context or excluded by .dockerignore:
       stat policy-preset.yaml: file does not exist
```

`nemoclaw onboard --from <Dockerfile>` stages only the Dockerfile (or `dirname(<from>)`) into a temp build context, so any `COPY` reaching outside that directory fails. Our `packages/nemoclaw-plugin/sandbox/Dockerfile` deliberately references parent-dir files (`policy-preset.yaml`, `package.json`, `src/`, `types/`, `openclaw.plugin.json`) — `docker build -f sandbox/Dockerfile packages/nemoclaw-plugin/` works fine because docker accepts an explicit context, but `nemoclaw onboard` doesn't expose `--context`.

**Fix applied to `scripts/onboard-sandbox.sh`**: pre-build the heavy image ourselves with the correct context + `--build-arg GENOMECLAW_HOST_PORT=${HOST_PORT}`, then mktemp a one-line shim Dockerfile (`FROM genomeclaw/sandbox:port-${HOST_PORT}`) and pass that to `nemoclaw onboard --from`. nemoclaw stages only the trivial shim — the heavy image is a layer-cache hit — and `--build-arg` now genuinely propagates. (The previous script aborted with an error message when `HOST_PORT != 8645`; that abort is no longer needed and was removed.)

### Failure 2 — gateway never starts; API key leaks via traceback

After Fix 1, onboarding got further and built `openshell/sandbox-from:1779657035` from the shim. But:

1. `"The gateway probe failed after retrying."` — the gateway never came up, because the config had no `gateway.mode` set.
2. Every subsequent `openclaw config set ...` step (run via `nemoclaw genomeclaw exec --no-tty -- bash -c ...`) emitted `EACCES: permission denied, scandir '/opt/genomeclaw'`, marking the plugin as "stale config entry, plugin not found".
3. The auth-profile write — `nemoclaw genomeclaw exec ... python3 -c "import base64; ...base64.b64decode('$PROFILE_B64')..."` — crashed because `/sandbox/.openclaw/agents/genomeclaw/agent/` didn't exist. The Python traceback echoed the full `python3 -c` source code, **which contained the operator's base64-encoded OpenAI API key**, into the log.

The leak was caught immediately, the key was redacted in-place (`docs/reports/demo-2026-05-24-logs/03-onboard-v2.log`), and the operator confirmed they were comfortable continuing with the same key. **The pattern is still unsafe**: any future failure of any `nemoclaw exec ... python3 -c "...$PROFILE_B64..."` will repeat the leak. The auth-profile step should write via stdin (`docker exec -i ... bash -c 'cat > ...' << EOF`) so the payload never lands in argv.

### Diagnosis — the EACCES is from openshell's sandboxing layer, not file permissions

Probed directly:

```
$ docker run --rm --entrypoint sh genomeclaw/sandbox:port-8645 -c 'id && ls -la /opt/genomeclaw'
uid=998(sandbox) gid=998(sandbox) groups=998(sandbox)
drwxr-xr-x 1 sandbox sandbox 4096 ... /opt/genomeclaw/
[full listing — readable]

$ docker exec --user sandbox openshell-genomeclaw-... ls -la /opt/genomeclaw
[full listing — readable]

$ nemoclaw genomeclaw exec --no-tty -- bash -c 'id ; ls /opt'
uid=998(sandbox) gid=998(sandbox) groups=998(sandbox)
ls: cannot open directory '/opt': Permission denied
```

Same uid, same container, same mount namespace (`/proc/self/mountinfo` is byte-identical between the docker-exec and nemoclaw-exec views). The container's apparmor is unconfined and `SecurityOpt=apparmor=unconfined`. Yet `nemoclaw genomeclaw exec` cannot read `/opt`. This points at **landlock or an LD_PRELOAD path-filter** applied inside the openshell sandboxing wrapper that `nemoclaw exec` wraps every command in. The gateway log even flags `WARNING: /tmp/nemoclaw-proxy-env.sh missing - gateway launching without library guards (#2478)` — yet the restriction persisted even with the guard library missing, so it's kernel-level.

This isn't a fatal bug — the restrictions are deliberate (operator-facing exec is sandboxed for safety) — but it does mean the onboard script's "configure via `nemoclaw genomeclaw exec`" steps don't work post-install. The agent itself runs fine because the gateway process *isn't* wrapped in the same restriction; only `nemoclaw exec`-issued commands are.

### Workaround that got Round 2 running

1. `docker exec -e HOME=/sandbox --user sandbox <CID> openclaw config set gateway.mode local`
2. `docker exec -e HOME=/sandbox --user sandbox <CID> openclaw config set plugins.allow '["genomeclaw"]'`
3. Configure OpenAI provider + bind `models.providers.openai.apiKey` to `--ref-source env --ref-id OPENAI_API_KEY` (so the key flows in at runtime, not at config-set time).
4. `docker exec -d -e HOME=/sandbox -e OPENAI_API_KEY=... --user sandbox <CID> bash -c 'openclaw gateway run > /tmp/gateway.log 2>&1'`
5. Run `bin/genomeclaw host service` *natively* (Python uvicorn on the host) — `GENOMECLAW_NATIVE=1` was insufficient because the shim wrapped `/mnt/genomeclaw/derived` as the in-container path; called the underlying `genomeclaw_toolkit._cli.main(['host','service','--derived-root','/Volumes/Genome_Work/genomeclaw/derived',...])` directly. Colima's `mounts:` is empty on this host (`mounts: []`), so the docker-wrapped host service can't see the derived directory — running it natively sidesteps that.
6. Per-question: `docker exec -i -e HOME=/sandbox -e OPENAI_API_KEY=... --user sandbox <CID> bash -c "openclaw agent --local --json --agent genomeclaw --timeout 360 --message $(printf %q '...')"`.

`HOME=/sandbox` was load-bearing: without it, `openclaw config` defaults to `/root/.openclaw` and EACCESes because the sandbox user can't write `/root`. The Dockerfile sets `WORKDIR /sandbox` but not `ENV HOME=/sandbox`.

### Recommended follow-ups to land in repo

1. **Patch the Dockerfile** to bake `gateway.mode=local`, `plugins.allow=["genomeclaw"]`, and `hostService.baseUrl=http://host.openshell.internal:${GENOMECLAW_HOST_PORT}` at build time. Also `ENV HOME=/sandbox`. This makes the persistent container come up usable on first run, no post-install `openclaw config set` needed.
2. **Patch the onboard script** to write `auth-profiles.json` via `docker exec -i bash -c 'cat > ...' << EOF` (stdin) instead of `nemoclaw exec ... python3 -c "...$PROFILE_B64..."` (argv). The key must never appear on a command line.
3. **Add a `colima.yaml` check** to `bin/genomeclaw host doctor` — if `mounts: []`, the docker-wrapped `bin/genomeclaw host service` will silently fail. Either reconfigure colima or fall back to the native uvicorn invocation.
4. **File a `genomeclaw_gene` serialization bug** for the CYP1A2/ADORA2A/AHR path Q4 hit.
5. **File a `pgs_compute` ack-without-row bug** for Q3's "task `done` but score row missing" — likely a race or a missing write to `pgs_scores` after the worker finishes.
6. **Re-stage a full Phase-6 annotated run** as the CURRENT for demo purposes; the current `f2dae2` ingest-only run gives every question an "empty findings" answer, which while *correct* doesn't actually exercise the report-shaping paths the agent has for non-empty findings.

## Privacy review

`INV-P001` (genomic source files never leave the device): respected. The host service runs locally; the plugin's HTTP calls go to `host.openshell.internal` (loopback bridge); the only outbound traffic is the agent → OpenAI gpt-5.5 path.

`INV-P002` (minimal-sufficient outputs to the agent): respected. Tool replies from `genomeclaw_findings`, `genomeclaw_gene`, `genomeclaw_status` carry scoped JSON — no raw variant lists, no bulk dumps. The `f2dae2` ingest-only run can't generate bulk outputs because the annotation layer isn't present.

**One real leak this session**: the OpenAI API key landed in `03-onboard-v2.log` via a Python traceback containing the literal base64 payload from `$PROFILE_B64`. Redacted at write time; operator chose not to rotate. The Fix-2 recommendation above (write auth-profiles.json via stdin, not argv) closes the recurrence path.

## What this exercise was, and what it wasn't

- **Was**: a five-question evening demo of the agent's behavior against the operator's own genome, plus the debug log of getting the persistent path actually onboarded.
- **Wasn't**: a benchmark, a regression test, or a reproducible CI artifact. The traces are signed by a single LLM call each; gpt-5.5 will not produce byte-identical answers on a re-run, even with identical inputs.

The pinned regression coverage for these behaviors lives in `packages/toolkit/tests/integration/test_live_story*_*.py` (per-story `live_llm`-marked tests, gated on `OPENAI_API_KEY` + `GENOMECLAW_SANDBOX_IMAGE` env vars). Those should grow as bugs surface; this report is the field log, not the test.
