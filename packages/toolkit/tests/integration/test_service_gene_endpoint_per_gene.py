"""Per-gene probe of /v1/gene/{symbol} for the gene sets the demo
sessions split into 'agent reported failed' vs 'agent used successfully'.

Diagnostic test for the investigate-genomeclaw-gene-tool-bug plan
Phase 1. Captures today's actual response shape per gene so the fix
target is unambiguous.

Either:
  - All genes return a uniform shape → hypothesis #6 (agent confabulation)
  - Genes split by response shape → hypothesis #1 / #5 (real server-side
    difference); investigate which shape difference matters

Run instructions: ensure the host service is up on 127.0.0.1:8645. The
test SKIPS cleanly when the service isn't reachable, so this file is safe
to leave in the suite.
"""
from __future__ import annotations

import json
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
    return "http://127.0.0.1:8645"


@pytest.fixture
def all_probed_genes() -> list[str]:
    return list(_AGENT_REPORTED_FAIL) + list(_AGENT_USED_SUCCESSFULLY)


def _probe_or_skip(url: str) -> None:
    """Skip the test if the host service isn't reachable on `url`/v1/health."""
    try:
        r = httpx.get(f"{url}/v1/health", timeout=2.0)
        if r.status_code != 200:
            pytest.skip(f"host service unhealthy at {url}: HTTP {r.status_code}")
    except httpx.HTTPError as exc:
        pytest.skip(f"host service not reachable at {url}: {type(exc).__name__}: {exc}")


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
    _probe_or_skip(host_service_url)

    results: dict[str, dict] = {}
    for gene in all_probed_genes:
        try:
            r = httpx.get(f"{host_service_url}/v1/gene/{gene}", timeout=5.0)
            ct = r.headers.get("content-type", "")
            body = r.json() if ct.startswith("application/json") else r.text[:500]
            results[gene] = {"status_code": r.status_code, "body": body}
        except httpx.HTTPError as exc:
            results[gene] = {"error": f"{type(exc).__name__}: {exc}"}

    snapshot = tmp_path / "gene_endpoint_snapshot.json"
    snapshot.write_text(json.dumps(results, indent=2, sort_keys=True))
    print(f"\n[probe] per-gene response snapshot written to {snapshot}")
    for gene, result in sorted(results.items()):
        regime = "fail-reported" if gene in _AGENT_REPORTED_FAIL else "used-OK"
        status = result.get("status_code", result.get("error"))
        body = result.get("body")
        if isinstance(body, dict):
            tag = f"n_variants={body.get('n_variants_in_gene', '?')}, region_class={body.get('region_class', '?')}"
        else:
            tag = str(body)[:80] if body else ""
        print(f"  [{regime}] {gene}: HTTP {status} · {tag}")


def test_gene_endpoint_returns_consistent_shape_for_hgnc_valid_symbols(
    host_service_url: str,
    all_probed_genes: list[str],
) -> None:
    """All HGNC-valid symbols should produce a parseable, non-error response.

    RED today if: any failing-reported gene returns HTTP 500 or a body
    the agent can't parse without error. GREEN after Phase 2 (Branch S)
    if the route handler returns a uniform shape for all genes.
    """
    _probe_or_skip(host_service_url)

    failures: list[str] = []
    for gene in all_probed_genes:
        try:
            r = httpx.get(f"{host_service_url}/v1/gene/{gene}", timeout=5.0)
            if r.status_code >= 500:
                failures.append(f"  {gene}: HTTP {r.status_code} (server error)")
                continue
            try:
                r.json()
            except json.JSONDecodeError as exc:
                failures.append(f"  {gene}: response body not JSON-parseable: {exc}")
        except httpx.HTTPError as exc:
            failures.append(f"  {gene}: probe failed: {type(exc).__name__}: {exc}")
    assert not failures, (
        "INV-A001-adjacent: /v1/gene/{symbol} returned a degraded response for "
        "an HGNC-valid symbol. The agent paraphrases such responses as "
        "'argument-serialization bug' even though the trace's failure count is 0. "
        "Make the endpoint return a uniform agent-parseable shape:\n"
        + "\n".join(failures)
    )
