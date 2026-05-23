# Phase 2 — Inline auto-fetch missing scorefiles

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

When the worker's `_real_compute_fn` resolves a scorefile path and it's absent, **auto-fetch the scorefile from PGS Catalog inline** (subject to the existing kill-switch), then retry the resolution. The agent's compute requests for PGS IDs whose scorefiles aren't pre-staged now succeed end-to-end without operator intervention.

## Scope Boundaries

- **In scope**:
  - `prep/fetch.py::fetch_pgs_scorefile(pgs_id, scorefile_root) -> Path` — public extraction from the existing CLI `refs fetch` machinery.
  - `_ensure_scorefile_staged(...)` wrapper in `pgs_compute_orchestrator.py` that catches `PgsScorefileMissingError` + invokes the fetch + retries the resolve.
  - Kill-switch gating: `pgs.compute_enabled false` blocks both the compute AND the fetch.
  - New error class `PgsScorefileUnfetchableError(pgs_id, reason)` mapped to `failed:scorefile_unfetchable:<pgs_id>:<reason>` via `_structured_error`.
  - Retry policy on transient PGS Catalog 5xx (3 attempts; 1s/4s/16s backoff).
  - Structured INFO log lines on fetch start/finish.
- **Out of scope**:
  - Phase 3's containerised compute (independent layer).
  - Operator-facing CLI changes (the existing `genomeclaw refs fetch` continues to work; we just reuse its internals).
  - Scoring-weight version checks / re-fetch on stale cache (deferred).
  - Concurrent-fetch protection (the concurrency cap of 1 means only one fetch in flight at a time anyway).

## Invariants enforced in this phase

- **INV-P001** — kill-switch test asserts no PGS Catalog egress when `pgs.compute_enabled=false`.
- **INV-D006** — fetched scorefile lands at canonical layout `<scorefile_root>/<pgs_id>/<pgs_id>_hmPOS_GRCh38.txt.gz`; `_resolve_scorefile_path` finds it on the retry. (Re-validates the fix from commit `d0f9c4e`.)

---

## TDD Steps

### Step 2.1 — RED: write failing tests

New file: `tests/integration/test_pgs_compute_scorefile_autofetch.py`.

All tests use `pytest_httpserver` (already a project dep) to stand up a fake PGS Catalog endpoint matching `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/<pgs>/ScoringFiles/Harmonized/<pgs>_hmPOS_GRCh38.txt.gz`.

**Test cases**:

1. `test_cache_hit_no_fetch_attempted` — scorefile already at canonical layout → `_ensure_scorefile_staged` returns the path without firing a request. Httpserver records zero requests.
2. `test_cache_miss_happy_path_fetches_and_caches` — scorefile absent → fetch fires, file lands at canonical layout, second resolve succeeds. Httpserver served the request.
3. `test_cache_miss_kill_switch_off_propagates_missing_error` — scorefile absent + `compute_enabled_fn()` returns False → `PgsScorefileMissingError` propagates; httpserver records zero requests.
4. `test_cache_miss_pgs_catalog_404_maps_to_unfetchable` — fake server returns 404 → `PgsScorefileUnfetchableError(pgs_id, "404")` → worker transitions task to `failed:scorefile_unfetchable:PGS<id>:404`.
5. `test_cache_miss_transient_5xx_retries_then_succeeds` — fake server returns 503 twice, 200 on third → fetch succeeds; httpserver received 3 requests; total wall ≥ ~5s (backoff math).
6. `test_cache_miss_persistent_5xx_exhausts_retries` — fake server always 503 → fetch fails after 3 attempts → `PgsScorefileUnfetchableError(pgs_id, "server_unreachable")` after ~21s total backoff.
7. `test_invP001_no_egress_under_kill_switch` — patches the HTTP client to fail-fast on any outbound call; kill-switch off → `_ensure_scorefile_staged` raises without ever touching the network.
8. `test_log_lines_on_fetch` — caplog at INFO; fetch fires; assert records `transition=auto_fetch_scorefile_started` + `transition=auto_fetch_scorefile_done` with `pgs_id` + `bytes`.

After authoring, run the suite — **all 8 should fail for the right reason** (no `_ensure_scorefile_staged`; no `fetch_pgs_scorefile`; no `PgsScorefileUnfetchableError`).

### Step 2.2 — GREEN: minimal implementation

**`prep/fetch.py`** (MODIFY) — extract `fetch_pgs_scorefile`:

```python
def fetch_pgs_scorefile(
    pgs_id: str,
    scorefile_root: Path,
    *,
    base_url: str = _DEFAULT_BASE_URLS["pgs_scorefile"],
    max_retries: int = 3,
) -> Path:
    """Download <pgs_id>'s hmPOS_GRCh38 scoring file from PGS Catalog.

    Idempotent: if the canonical-layout file already exists, returns the
    path without hitting the network. Retries transient 5xx with
    exponential backoff (1s, 4s, 16s); persistent 5xx OR 404 raises
    PgsScorefileUnfetchableError with a short reason.
    """
    target = scorefile_root / pgs_id / f"{pgs_id}_hmPOS_GRCh38.txt.gz"
    if target.exists():
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    url = f"{base_url}/pub/databases/spot/pgs/scores/{pgs_id}/ScoringFiles/Harmonized/{pgs_id}_hmPOS_GRCh38.txt.gz"
    for attempt in range(max_retries):
        try:
            data = _http_get(url)
        except HTTPError as exc:
            if exc.code == 404:
                raise PgsScorefileUnfetchableError(pgs_id, "404") from exc
            if attempt + 1 == max_retries:
                raise PgsScorefileUnfetchableError(pgs_id, "server_unreachable") from exc
            time.sleep(4 ** attempt)
            continue
        target.write_bytes(data)
        return target
```

`PgsScorefileUnfetchableError` lands in `service/pgs_compute_orchestrator.py` (alongside the existing `PgsScorefileMissingError`).

**`service/pgs_compute_orchestrator.py`** (MODIFY):

```python
async def _ensure_scorefile_staged(
    scorefile_root: Path,
    pgs_id: str,
    *,
    compute_enabled_fn: Callable[[], bool],
) -> Path:
    """Resolve the scorefile path, auto-fetching from PGS Catalog if absent.

    Subject to the kill-switch: when compute_enabled_fn() is False,
    propagates PgsScorefileMissingError without attempting the fetch
    (INV-P001 — no PGS Catalog egress under kill-switch).
    """
    try:
        return _resolve_scorefile_path(scorefile_root, pgs_id)
    except PgsScorefileMissingError:
        if not compute_enabled_fn():
            raise
        _LOG.info(
            "Auto-fetching PGS scorefile from PGS Catalog",
            extra={"transition": "auto_fetch_scorefile_started", "pgs_id": pgs_id},
        )
        loop = asyncio.get_running_loop()
        path = await loop.run_in_executor(
            None, functools.partial(fetch_pgs_scorefile, pgs_id, scorefile_root),
        )
        _LOG.info(
            "Auto-fetched PGS scorefile",
            extra={
                "transition": "auto_fetch_scorefile_done",
                "pgs_id": pgs_id,
                "bytes": path.stat().st_size,
            },
        )
        return path
```

Update `_real_compute_fn` to call `_ensure_scorefile_staged` instead of `_resolve_scorefile_path`. Thread `compute_enabled_fn` through (currently bound at lifespan via `functools.partial`; needs `compute_enabled_fn` added to its kwargs).

Extend `_structured_error`:
```python
if isinstance(exc, PgsScorefileUnfetchableError):
    return f"scorefile_unfetchable:{exc.pgs_id}:{exc.reason}"
```

### Step 2.3 — REFACTOR

- The retry loop in `fetch_pgs_scorefile` is two-deep; extract `_fetch_with_retries(url, max_retries)` if a future fetch source needs it. Premature otherwise — rule of three.
- Update the agent system prompt's failure-mapping table to include `scorefile_unfetchable:<pgs_id>:<reason>` with the suggested user-facing framing ("the scorefile couldn't be fetched from PGS Catalog: <reason>").

---

## Implementation Details

### Reusing `prep/fetch.py`'s existing machinery

`prep/fetch.py` already has:
- `_http_get(url) -> bytes` — uses `urllib.request`, no subprocess, available on plain Python.
- `_SourceLayout["pgs_scorefile"]` — declares the canonical URL template + output filename.
- `_DEFAULT_BASE_URLS["pgs_scorefile"]` — the EBI FTP root.

The new `fetch_pgs_scorefile` is mostly a thin wrapper that:
1. Checks the cache (canonical layout).
2. Substitutes `{release_n}` → `<pgs_id>` in the URL template.
3. Calls `_http_get`.
4. Writes bytes to canonical layout.
5. Retries on transient 5xx; surfaces 404 + persistent 5xx as `PgsScorefileUnfetchableError`.

### Kill-switch is a single re-evaluated function

`_ensure_scorefile_staged` calls `compute_enabled_fn()` at fetch-decision time (not at startup). This means if the operator flips the kill-switch mid-run, the next compute request's fetch is blocked. Mirrors the existing worker-loop pattern.

### Egress, INV-P001, audit

- Same destination, transport, payload as the existing operator-driven `refs fetch`.
- INV-P001 install-time consent already covers PGS Catalog scorefile fetches per `architecture.md:405`.
- INFO log lines on fetch start/finish make every transitive fetch auditable on `tail -f` of the host log.

### Edge Cases to Handle

- **Cache hit during retry** — if the file appears mid-fetch (another worker / out-of-band copy), the second `_resolve_scorefile_path` succeeds. The wasted bytes from the in-flight download are written then read back; no harm.
- **Partial write on crash** — `target.write_bytes(data)` writes atomically (full buffer or nothing). A crash between `_http_get` returning + `write_bytes` finishing leaves the file absent → next attempt re-fetches.
- **PGS Catalog rate-limiting** — if PGS Catalog adds rate limits in the future, the existing retry policy handles transient 429s (treated as 5xx in the retry path).

### Privacy / Egress Notes

- No new egress surface.
- Fetched bytes carry no user data — scoring weights are public.
- Audit trail via structured INFO logs.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | Add public `fetch_pgs_scorefile(pgs_id, scorefile_root)` |
| `packages/toolkit/src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py` | MODIFY | Add `_ensure_scorefile_staged`, `PgsScorefileUnfetchableError`; wire into `_real_compute_fn`; extend `_structured_error` |
| `packages/toolkit/src/genomeclaw_toolkit/service/app.py` | MODIFY | Bind `compute_enabled_fn` through `functools.partial(...)` so `_real_compute_fn` can re-evaluate it for the fetch path |
| `packages/toolkit/tests/integration/test_pgs_compute_scorefile_autofetch.py` | CREATE | 8 tests covering happy-path + kill-switch + 404 + retries + log lines |
| `packages/nemoclaw-plugin/sandbox/agent-system-prompt.md` | MODIFY | Add `scorefile_unfetchable` row to the failure-mapping table |

---

## Verification

```bash
cd packages/toolkit

uv run pytest tests/integration/test_pgs_compute_scorefile_autofetch.py -v
# Expect: 8/8 PASS

uv run pytest tests/integration/test_pgs_compute_worker_integration.py tests/integration/test_pgs_compute_worker_skeleton.py tests/integration/test_pgs_compute_worker_recovery.py tests/integration/test_pgs_compute_config_loader.py -v
# Expect: 34/34 STILL PASS (Phase 4 + 5 baselines hold)

uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: 875 passed, 116 skipped (was 867; +8 new Phase 2 tests)

uv run mypy src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py \
            src/genomeclaw_toolkit/service/app.py \
            src/genomeclaw_toolkit/prep/fetch.py
uv run ruff check src/genomeclaw_toolkit/service/pgs_compute_orchestrator.py \
                  src/genomeclaw_toolkit/service/app.py \
                  src/genomeclaw_toolkit/prep/fetch.py \
                  tests/integration/test_pgs_compute_scorefile_autofetch.py
```

---

## Completion Criteria

- [ ] All 8 new tests pass.
- [ ] Existing 34 worker tests still pass (Phase 4 + Phase 5 baselines).
- [ ] Full toolkit suite stays green.
- [ ] mypy + ruff clean on touched files.
- [ ] Agent system prompt failure-mapping table updated.
- [ ] `work-notes.md` updated with the design choice (3-retry exponential backoff vs alternatives) + a sample log-output excerpt from a manual smoke test against the real PGS Catalog.

## Next

[Phase 3 — Containerised compute](phase-3.md).
