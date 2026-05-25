# Demo Questions Verification — 2026-05-25 (Round 3)

**Audience**: same as the [2026-05-24 demo report](genomeclaw-demo-questions-2026-05-24.md)
**Subject**: the same five layman questions, against the same derived run (`2026-05-24T12-52-11Z-f2dae2`), through the persistent `nemoclaw genomeclaw` sandbox after the [onboard-persistent-agent-fix plan](../plans/completed/onboard-persistent-agent-fix/) closed
**Status**: verification re-run — confirms two infrastructure problems from the original session are gone; confirms one of the two deferred agent-tool bugs still reproduces and one didn't trigger this round

This is a short follow-up to the [2026-05-24 demo report](genomeclaw-demo-questions-2026-05-24.md). Same five questions, same operator genome, same sandbox image — but executed via the now-canonical onboarding path (`./scripts/onboard-sandbox.sh` end-to-end + `docker exec` smoke test), with all the Phase 1-3 fixes from `onboard-persistent-agent-fix` in place.

## Setup

```
sandbox       : openshell-genomeclaw-e5f1b678-7151-4181-9cb7-955693451645
                  ↑ created by ./scripts/onboard-sandbox.sh on 2026-05-25
sandbox image : genomeclaw/sandbox:port-8645
                  ↑ rebuilt 2026-05-25 with Phase 1 bakes (ENV HOME=/sandbox,
                    gateway.mode=local, plugins.allow=["genomeclaw"],
                    hostService config, openai apiKey as env-ref)
host service  : native Python uvicorn on 127.0.0.1:8645 (colima mounts: []
                  on this host, so the docker-wrapped path can't see the
                  derived dir — `host doctor`'s new colima_mounts_cover_derived
                  finding fires correctly here)
derived run   : 2026-05-24T12-52-11Z-f2dae2 (same as Rounds 1+2 — still ingest-only)
runner        : docs/reports/demo-2026-05-25-logs/runner_round3.sh
```

## Per-question results

| Q | Wall (s) | Agent-ms | Calls | Failures | Distinct tools |
|---|---------:|---------:|------:|---------:|----------------|
| 1 | 120 |  89,247 | 13 | 0 | `genomeclaw_status`, `genomeclaw_findings`, `memory_search`, `exec`, `write` |
| 2 | 122 |  95,229 | 19 | 0 | + `genomeclaw_gene` |
| 3 | 265 | 240,307 | 27 | 0 | + `update_plan`, `genomeclaw_pgs_list`, `genomeclaw_pgs_compute`, `sessions_spawn`, `sessions_list`, `read`, `process` |
| 4 |  96 |  71,931 |  6 | 0 | (no `genomeclaw_gene` this turn — see "Coverage gap" below) |
| 5 | 185 | 157,865 | 12 | + `update_plan`, `genomeclaw_pgs_list` (but NOT `genomeclaw_pgs_get`) |

**Total: 788s for all 5 questions; 77 tool calls; 0 failures.** All replies parsed as valid agent JSON envelopes with `status=ok`.

## What's confirmed fixed

These are the infrastructure problems from the [original 2026-05-24 session](genomeclaw-demo-questions-2026-05-24.md#onboarding-the-persistent-sandbox--what-broke) that the [onboard-persistent-agent-fix plan](../plans/completed/onboard-persistent-agent-fix/) targeted:

- ✅ **`nemoclaw onboard --from <Dockerfile>` build-context failure** — closed. The shim-Dockerfile pre-build pattern in the script works; `nemoclaw list` shows `genomeclaw` healthy.
- ✅ **Gateway refuses to start (missing `gateway.mode`)** — closed. Phase 1 bakes `gateway.mode=local` (+ the four other persistent-path keys) into the sandbox image at build time. Fresh sandbox starts the gateway cleanly on first run.
- ✅ **`openclaw config set` EACCESes on `/root/.openclaw`** — closed. Phase 1 added `ENV HOME=/sandbox` to the Dockerfile.
- ✅ **`nemoclaw genomeclaw exec` EACCESes on `/opt/genomeclaw`** — worked around. The script's auth-profile write + config patches all use plain `docker exec --user sandbox -e HOME=/sandbox` which bypasses the openshell-exec wrapper's restriction. (Upstream nemoclaw bug; not under our control.)
- ✅ **OpenAI API key leaked into a committed log via Python `-c` traceback** — closed structurally by Phase 2's stdin-based auth-profile write (`docker exec -i ... cat > ...`). The new INV-P003 invariant test (`packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py`) walks every `.sh` under `scripts/` and asserts the forbidden argv-secret patterns are absent.

## What's confirmed still broken

These are the agent-tool bugs that surfaced in the original session — both flagged as deferred follow-ups (not in `onboard-persistent-agent-fix` scope):

### `genomeclaw_pgs_compute` ack-without-row — STILL REPRODUCES

Two independent confirmations in Round 3:

**Q3 (T2D / PGS000014)** reply excerpt:
> I also attempted the canonical type-2 diabetes PRS, **PGS000014 / GPS_T2D**. […]
>
> **Bottom line:** Your DNA currently shows **no clear high-impact diabetes warning**, but I **cannot determine above- vs below-average T2D risk** until the PRS result is retrievable.

**Q5 (Alzheimer's / PGS000334)** reply excerpt:
> I tried to compute the Alzheimer's PRS **PGS000334**, but although the compute task reached `done`, the result endpoint did not return a percentile.

This is the third independent reproduction of the bug (Rounds 1, 2, and 3 all hit it on Q3; Rounds 2 and 3 hit it on Q5). Pattern is consistent: `genomeclaw_pgs_compute` returns `done`, but the subsequent `genomeclaw_pgs_get` (or equivalent retrieval) returns no row. Likely a race or a missing write to `pgs_scores` after the worker finishes — worth a focused investigation when the deferred follow-up plan is opened.

### `genomeclaw_gene` argument-serialization — DID NOT REPRO in Round 3

**Q2 + Q3 both used `genomeclaw_gene` with 0 failures.** Q3's reply specifically cites coverage values that could only come from a successful `genomeclaw_gene` response:

> Coverage looked generally usable: e.g. **FTO ~33.9×, PPARG ~34.2×, KCNJ11 ~31.9×, MC4R ~30.0×, IRS1 ~28.5×**.

Compare to Round 1 Q4's *"I tried gene-level summaries for CYP1A2, ADORA2A, and AHR, but the runtime hit an argument-serialization bug, so I'm not inferring genotype from those"* and Round 2 Q1's *"I attempted extra gene-level spot checks in major actionable genes like BRCA1/BRCA2/TP53/MMR/cardiac genes, but the `genomeclaw_gene` tool hit an argument-serialization bug."* This time, no such complaint.

**Caveat — Q4 + Q5 did NOT call `genomeclaw_gene` at all this round** (Q4 used only 6 tools, none of them gene-summary; Q5 used 12 tools, none gene-summary). The replies still cite specific coverage values for CYP1A2 / APOE-panel genes — those came from `memory_search` returning prior memory notes the agent wrote during Round 2 against the same active run, not from fresh gene-summary calls. So Round 3 does not actually demonstrate that the bug is fixed; it just demonstrates that under *this turn's specific tool choices*, the bug wasn't triggered.

A focused regression check (run `genomeclaw_gene` directly against CYP1A2 / ADORA2A / AHR / POR / BRCA1 / BRCA2 / TP53 — the gene names Rounds 1+2 hit the bug on) would close this question. Deferred to its own follow-up plan.

## What's new in Round 3

Two behavioural patterns showed up that weren't in Rounds 1+2:

- **`update_plan` tool fired on Q3 + Q5** — same as Round 2 (it's a persistent-agent-only tool that the ephemeral Round 1 didn't have). Used as the planner's working memory across the multi-step sweep.
- **Q3 spawned a sub-agent via `sessions_spawn` + `sessions_list` + `read` + `process`** — the agent-research-and-synthesis protocol's blocking-sub-agent pattern. Round 2 Q3 did not do this. Suggests the persistent-agent context-budget pressure pushes the model to delegate research at variable thresholds.

## Reply quality vs Round 1+2 — spot check

**Q1 (clinical risk sweep)**, 1,096 chars, more concise than Round 1 (1,484 chars) or Round 2 (1,599 chars). Names the run ID explicitly. Honest caveat (*"This is not the same as a clinical-grade 'all clear'"*). Cites ACMG framework. No `genomeclaw_gene` triggered, so the Round-2 "BRCA1/BRCA2/TP53 actionable-gene panel" detour didn't happen.

**Q2 (drug response)**, 1,771 chars. Lists the specific drug-and-gene pairs the agent checked (CYP2C19-clopidogrel, CYP2D6-codeine/tramadol, CYP2C9/VKORC1-warfarin, SLCO1B1-statins). Cites CPIC + FDA. The "I'd still ask about clinical PGx for these meds before starting" framing is the same shape as Round 1, sharper than Round 2.

**Q3 (T2D)**, 1,457 chars. Identical core finding to Rounds 1 + 2 (10-gene panel returns 0 variants; PGS000014 attempted; same ack-without-row failure). Reply quality strong; cites PGS Catalog + Khera et al. PMID.

**Q4 (caffeine)**, 1,531 chars. Cleanest of the three rounds' Q4 replies. Honest about what couldn't be queried (*"ADORA2A/AHR weren't retrievable from the gene-summary endpoint"*). Practical 2-week experiment is identical structure to Round 2's (noon cutoff, track sleep-onset / awakenings / next-day alertness, fallback to 2pm).

**Q5 (Alzheimer's)**, 1,417 chars. Lists 11 neurodegeneration-panel genes; surfaces specific low-coverage exons (APOE exons 1-2, PSEN2 exon 5, GRN exon 5, SNCA exon 4); refuses to infer APOE ε-status; same calibrated landing as Round 2 (*"No clear inherited Alzheimer's red flag was found, but I cannot say 'lower than average' or 'higher than average' from the current data surface"*).

## What this verification was, and what it wasn't

- **Was**: an end-to-end confirmation that the operator can now onboard the persistent agent via the canonical `./scripts/onboard-sandbox.sh` path + talk to it via `docker exec` + get coherent answers grounded in their real genome. Plus a deliberate check on whether the two known deferred bugs still reproduce.
- **Wasn't**: a fix for the two deferred bugs (out of `onboard-persistent-agent-fix` scope). The pgs_compute ack-without-row is now thrice-confirmed across three independent sessions; the `genomeclaw_gene` serialization bug needs a direct probe against the specific gene names Rounds 1+2 hit it on.

The pinned regression coverage for the *infrastructure* this verification exercised lives in:

- `packages/toolkit/tests/invariants/test_invP001_sandbox_baked_config_persistent_path.py` — 6 tests, all green.
- `packages/toolkit/tests/invariants/test_invP003_onboard_script_no_secrets_in_argv.py` — 3 tests, all green.
- `packages/toolkit/tests/integration/test_host_doctor_colima_mounts_coverage.py` — 6 tests, all green.

Plus the `./scripts/onboard-sandbox.sh` end-to-end smoke test (now uses `docker exec`, exits 0 with 1 tool call + 0 failures against `genomeclaw_status`).

Raw logs + per-question replies + trace JSONs live in [docs/reports/demo-2026-05-25-logs/](demo-2026-05-25-logs/).
