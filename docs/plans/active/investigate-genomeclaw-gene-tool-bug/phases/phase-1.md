# Phase 1: Reproduce + Diagnose

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Determine empirically which of the 6 hypotheses in [spec.md § Background](../spec.md#background) is the actual root cause of the `genomeclaw_gene` "argument-serialization bug" wording in the agent's replies. Land a per-gene probe test + walk the existing trace JSONs + curl the live endpoint to extract enough evidence to pin the hypothesis.

## Scope Boundaries

- **In scope**: per-gene probe test against the live host service; trace-JSON walk for confabulation evidence; code-path inspection of plugin + service + system prompt; pinning the hypothesis in `work-notes.md`.
- **Out of scope**: writing the fix (Phase 2), shipping the structural invariant test (Phase 3).

## Invariants Enforced in This Phase

None. Diagnostic phase.

---

## TDD Steps

### Step 1.1 — RED-or-document: Per-gene probe test

`packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py`:

```python
"""Per-gene probe of /v1/gene/{symbol} for the gene sets the demo
sessions split into 'agent reported failed' vs 'agent used successfully'.

Diagnostic test for the investigate-genomeclaw-gene-tool-bug plan
Phase 1. Captures today's actual response shape per gene so the fix
target is unambiguous.

Either:
  - All genes return a uniform shape → hypothesis #6 (agent confabulation)
  - Genes split by response shape → hypothesis #1 / #5 (real server-side
    difference); investigate which shape difference matters
"""
from __future__ import annotations

from pathlib import Path

import httpx
import pytest

# Gene sets pulled from the 2026-05-24 + 2026-05-25 demo reports.
# These are the empirical regimes the agent's replies split into.
_AGENT_REPORTED_FAIL = (
    "CYP1A2",      # Round 1 Q4 caffeine
    "ADORA2A",     # Round 1 Q4 caffeine
    "AHR",         # Round 1 Q4 caffeine
    "POR",         # Round 2 Q4 caffeine
    "BRCA1",       # Round 2 Q1 clinical-risk
    "BRCA2",       # Round 2 Q1 clinical-risk
    "TP53",        # Round 2 Q1 clinical-risk
)

_AGENT_USED_SUCCESSFULLY = (
    "TCF7L2",      # Round 1 Q3 T2D
    "HNF1A",       # Round 1 Q3 T2D
    "FTO",         # Round 1 Q3 T2D
    "CYP2C19",     # Round 1 Q2 PGx
    "CYP2D6",      # Round 1 Q2 PGx
    "SLCO1B1",     # Round 1 Q2 PGx
)


@pytest.fixture
def host_service_url() -> str:
    # Probes the live host service; Phase 1 assumes the operator has it
    # running (see onboard-persistent-agent-fix close-out for how to
    # start it natively when colima mounts are empty).
    return "http://127.0.0.1:8645"


@pytest.fixture
def all_probed_genes() -> list[str]:
    return list(_AGENT_REPORTED_FAIL) + list(_AGENT_USED_SUCCESSFULLY)


def test_gene_endpoint_response_shape_per_gene(
    host_service_url: str,
    all_probed_genes: list[str],
    tmp_path: Path,
) -> None:
    """For each probed gene: capture the HTTP status + body shape.

    This is a CAPTURE test (not pass/fail-on-assertion) — it dumps the
    per-gene response shape to a fixture file that Phase 2 will assert
    against once the fix lands. RED today simply if any probe errors
    out at the HTTP layer; the body-shape diff is for human inspection.
    """
    results: dict[str, dict] = {}
    for gene in all_probed_genes:
        try:
            r = httpx.get(f"{host_service_url}/v1/gene/{gene}", timeout=5.0)
            results[gene] = {
                "status_code": r.status_code,
                "body": r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text[:500],
            }
        except Exception as exc:
            results[gene] = {"error": f"{type(exc).__name__}: {exc}"}

    # Write the per-gene snapshot for human inspection + Phase 2 baseline.
    snapshot = tmp_path / "gene_endpoint_snapshot.json"
    import json
    snapshot.write_text(json.dumps(results, indent=2, sort_keys=True))
    print(f"\n[probe] per-gene response snapshot written to {snapshot}")
    for gene, result in sorted(results.items()):
        regime = "fail-reported" if gene in _AGENT_REPORTED_FAIL else "used-OK"
        print(f"  [{regime}] {gene}: {result.get('status_code', result.get('error'))}")

    # The actual assertion for Phase 1: surfaces today's truth.
    # If the two regimes have IDENTICAL response shapes (same status,
    # same body schema), that's hypothesis #6 (confabulation) territory.
    # If they differ, the difference IS the bug.
    fail_shapes = {gene: results[gene] for gene in _AGENT_REPORTED_FAIL}
    success_shapes = {gene: results[gene] for gene in _AGENT_USED_SUCCESSFULLY}
    print(f"\n[probe] failing-reported genes: {len(fail_shapes)}")
    print(f"[probe] used-successfully genes: {len(success_shapes)}")

    # Soft assertion — Phase 1 is diagnostic, not assertion-driven.
    # No raise. Phase 2 will replace this with the post-fix assertion.
    pass


def test_gene_endpoint_returns_consistent_shape_for_hgnc_valid_symbols(
    host_service_url: str,
    all_probed_genes: list[str],
) -> None:
    """All HGNC-valid symbols should produce a parseable, non-error response.

    RED today if: any failing-reported gene returns HTTP 500 or a body
    the agent can't parse without error. GREEN after Phase 2 (Branch S)
    if the route handler returns a uniform shape for all genes.
    """
    failures: list[str] = []
    for gene in all_probed_genes:
        try:
            r = httpx.get(f"{host_service_url}/v1/gene/{gene}", timeout=5.0)
            if r.status_code >= 500:
                failures.append(f"  {gene}: HTTP {r.status_code} (server error)")
                continue
            try:
                r.json()
            except Exception as exc:
                failures.append(f"  {gene}: response body not JSON-parseable: {exc}")
        except Exception as exc:
            failures.append(f"  {gene}: probe failed: {type(exc).__name__}: {exc}")
    assert not failures, (
        "INV-A001-adjacent: /v1/gene/{symbol} returned a degraded response for "
        "an HGNC-valid symbol. The agent paraphrases such responses as "
        "'argument-serialization bug' even though the trace's failure count is 0. "
        "Make the endpoint return a uniform agent-parseable shape:\n"
        + "\n".join(failures)
    )
```

Run both tests. Capture per-gene snapshots into the work-notes. Note which regime each gene falls into.

### Step 1.2 — Trace-JSON walk for confabulation evidence

For each of the trace JSONs where the agent's reply reports failure:

- `docs/reports/demo-2026-05-24-logs/q4-caffeine.trace.json` (Round 1)
- `docs/reports/demo-2026-05-24-logs/round2-q1-serious-risk.trace.json` (Round 2)
- `docs/reports/demo-2026-05-24-logs/round2-q4-caffeine.trace.json` (Round 2)

…walk the `result.meta.executionTrace` (or whatever the per-tool-call log structure is). For each:

```bash
python3 -c "
import json
t = json.load(open('docs/reports/demo-2026-05-24-logs/round2-q1-serious-risk.trace.json'))
meta = t['result']['meta']
ts = meta.get('toolSummary', {})
print('toolSummary:', json.dumps(ts, indent=2))
# Walk per-call records (shape unknown — figure out from the JSON)
print('agentMeta keys:', list(meta.get('agentMeta', {}).keys()))
print('executionTrace shape:', type(meta.get('executionTrace')).__name__)
# Look for any field that records per-tool-call args + responses
"
```

Specifically: did the agent invoke `genomeclaw_gene` with `gene="BRCA1"`, `"BRCA2"`, `"TP53"`? If yes — what was the response? If no — that's confabulation (hypothesis #6) caught red-handed.

Document the findings in `work-notes.md`.

### Step 1.3 — Code-path inspection

Read:

- `packages/nemoclaw-plugin/src/index.ts` lines 454-470 — the `genomeclaw_gene` tool's `execute` body.
- Look up `GeneParams` definition — what's the TypeBox schema for the `gene` field?
- Look up `rejectIfPlaceholder` — what regex does it use? Does any of CYP1A2 / ADORA2A / AHR / POR / BRCA1 / BRCA2 / TP53 trip it?
- Look up `safeCall` — how does it wrap non-2xx responses? Does it return an error envelope the agent can read clearly, or a generic "tool call failed"?
- `packages/toolkit/src/genomeclaw_toolkit/service/app.py` line 443 — `/v1/gene/{symbol}` route handler. Status code on missing gene? Body shape?
- `packages/toolkit/src/genomeclaw_toolkit/service/store.py` — the per-gene query — does it return None / empty / raise for missing genes?

Document in `work-notes.md` what each path does for the probed gene set.

### Step 1.4 — System-prompt inspection

Read `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md`. Find any section about:

- `genomeclaw_gene` tool documentation
- Tool-error handling guidance
- Phrasing rules for "no data" responses

Is there an explicit instruction about how to paraphrase a no-data gene response? If not, that's evidence of hypothesis #6 (the agent is free-styling the wording).

### Step 1.5 — Pin the hypothesis

Based on Steps 1.1-1.4, name one of the 6 hypotheses (or articulate a new one) in `work-notes.md`:

```markdown
## Phase 1 conclusion

**Confirmed hypothesis**: #N — <name from spec.md>
**Evidence**:
- Probe test: <which genes returned which shape>
- Trace walk: <did the agent actually call the tool for failing genes?>
- Code path: <did rejectIfPlaceholder / GeneParams / route handler do something gene-specific?>
- System prompt: <does the prompt teach the right paraphrasing?>
**Ruled out**:
- Hypothesis #M — because <evidence>
- ...
**Implication for Phase 2 fix**:
- Branch <S | P | A>: <one-paragraph description of the fix shape>
```

---

## Implementation Details

### Edge Cases to Handle

- **Host service not running**: tests should skip cleanly (not error) if `127.0.0.1:8645` isn't bindable. The operator's onboarding flow includes starting the host service natively; without it, the per-gene probe can't run.
- **Curated panel reality**: if the host service genuinely doesn't have data for some genes, the probe should make that obvious — log the response body so the human reader can see "this gene has no row" vs "this gene has data but agent couldn't read it".

### Error Handling

- httpx exceptions caught + logged per-gene; one failing probe doesn't abort the others.

### Privacy / Egress Notes

- All probes are loopback. No egress.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/integration/test_service_gene_endpoint_per_gene.py` | CREATE | Per-gene probe + per-gene response-shape capture. |
| `docs/plans/active/investigate-genomeclaw-gene-tool-bug/work-notes.md` | MODIFY | Probe snapshots + trace walk + code-path findings + pinned hypothesis. |

---

## Verification

```bash
# Ensure host service is up (or start it natively per onboard-persistent-agent-fix close-out)
cd packages/toolkit
.venv/bin/python -c "from genomeclaw_toolkit._cli import main; main(['host','service','--derived-root','/Volumes/Genome_Work/genomeclaw/derived','--port','8645','--host','127.0.0.1'])" > /tmp/host-service.log 2>&1 &
sleep 5
curl -sf http://127.0.0.1:8645/v1/health

# Run the per-gene probe
.venv/bin/pytest tests/integration/test_service_gene_endpoint_per_gene.py -v -s
# -s flag preserves the print output so the per-gene snapshot is readable.

# Look at the saved snapshot
cat /tmp/pytest-of-*/test_gene_endpoint_response_*/gene_endpoint_snapshot.json | jq .
```

---

## Completion Criteria

- [ ] Probe test runs successfully against the live host service and produces a per-gene response snapshot.
- [ ] `work-notes.md` carries the snapshot summary + the trace-JSON walk findings + the code-path inspection.
- [ ] `work-notes.md` names one pinned hypothesis with evidence (Step 1.5).
- [ ] All existing service / plugin / integration tests still pass.
- [ ] Phase status updated to "Complete" in `development-plan.md`.
