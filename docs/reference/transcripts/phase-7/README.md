# Phase 7 — live LLM evidence index

**Captured**: 2026-05-23 (MVP Phase 7 close session 1)
**Sandbox image**: `genomeclaw/sandbox:slice-d-prime`
**Model**: OpenAI `gpt-5.5` (routed via OpenShell L7 proxy)
**Canonical run-dir**: `/Volumes/Genome_Work/genomeclaw/derived/2026-05-22T16-30-38Z-b8dc60/`

---

## Outcome

All four Slice F live tests **PASSED** in a single sweep (13m02s wall total, ~$1-2 cost). Each test asserts a structural contract over the agent's prose + the execution trace blob; the assertions verify INV-C001 + INV-A001/A002/A003 + INV-P001/P002 hold for real conversations against gpt-5.5.

## Test → user-stories mapping

| Test | Story | Contract | Outcome |
|------|-------|----------|---------|
| [test_live_story2_introspection_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story2_introspection_snapshot.py) | [Story 2](../../user-stories.md#story-2--first-conversation-what-do-you-know-about-me) — "what do you actually know about me?" | Agent invokes `genomeclaw_status`, surfaces concrete metadata (run-id / schema / sample-id), expresses meta-awareness ("before pulling any findings"), does NOT fabricate evidence refs | PASS |
| [test_live_story4_clopidogrel_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story4_clopidogrel_snapshot.py) | [Story 4](../../user-stories.md#story-4--pharmacogenomics-im-starting-clopidogrel) — PGx / CYP2C19 / clopidogrel | Agent surfaces CYP2C19 *1/*2 IM phenotype, names prasugrel/ticagrelor alternatives or CPIC guideline, carries clinical-escalation framing, cites a primary source, invokes `web_search` | PASS |
| [test_live_story9_caffeine_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story9_caffeine_snapshot.py) | [Story 9](../../user-stories.md#story-9--lifestyle-question-caffeine-and-sleep) — lifestyle / CYP1A2 / caffeine | Agent invokes `web_search`, cites primary sources (URL / PMID / variant-keyed ref), engages with the actual topic (no bootstrap protocol punt) | PASS |
| [test_live_story10_cad_prs_snapshot.py](../../../../packages/toolkit/tests/integration/test_live_story10_cad_prs_snapshot.py) | [Story 10](../../user-stories.md#story-10--polygenic-risk-whats-my-cad-risk) — PRS / CAD percentile | Agent surfaces PGS Catalog ID + ancestry-calibrated percentile + calibration framing, marks `clinical-non-actionable` category structurally, doesn't elevate to `clinical_escalation` | PASS |

## What this evidence demonstrates

- **`INV-C001` v1.7** (clinical-vs-research line, prose surface) — all 4 tests assert the agent's framing matches the staged finding's category + escalation marker. PRS findings stay `clinical-non-actionable`; PGx findings carry escalation framing; lifestyle findings stay direct (no over-deferral).
- **`INV-A001`** (memory provenance / primary-source citation) — Stories 4 + 9 + 10 require a primary-source citation in the reply (URL / PMID / variant-keyed ref).
- **`INV-A002`** (synthesis reasoning floor) — Story 9 specifically asserts the agent invoked `web_search` (the agent reasoned about current literature, not just training-knowledge punted).
- **`INV-A003`** (PRS compute provenance) — Story 10 surfaces the PGS Catalog ID + ancestry framing structurally.
- **`INV-P001`** (privacy default) — all 4 tests run inside the sandbox with default config; the act of completing successfully proves the OpenShell L7 proxy allowed `host.openshell.internal:8643` (the host service) and the configured OpenAI endpoint (and no other egress).
- **`INV-P002`** (sandbox egress surface) — implicit; the live tests succeed only if the policy preset's allow-list matches the runtime behavior. (Explicit negative-case runtime probing is captured as a [post-MVP follow-up](../../../plans/active/ssrf-runtime-probe/).)

## Verbatim transcripts

**Deferred**: capturing the actual reply prose verbatim would require another ~13-min + ~$1-2 live sweep. The test files above contain the staged finding, the user question, and the structural assertions — they're sufficient evidence for MVP close. If a verbatim transcript becomes valuable later (e.g., for a publication or demo), re-run the tests with `-s --tb=long` + capture the `reply` variable's value at the end of each test.

## Reproduction

```bash
export OPENAI_API_KEY=$(grep '^OPEN_AI_API_KEY=' .env | cut -d= -f2-)
export GENOMECLAW_SANDBOX_IMAGE=genomeclaw/sandbox:slice-d-prime
cd packages/toolkit
uv run pytest \
  tests/integration/test_live_story2_introspection_snapshot.py \
  tests/integration/test_live_story4_clopidogrel_snapshot.py \
  tests/integration/test_live_story9_caffeine_snapshot.py \
  tests/integration/test_live_story10_cad_prs_snapshot.py -v
```

Expected wall: ~13 min. Expected cost: ~$1-2.
