# Phase 5a: PGS scoring-file fetch source + setup integration

**Status**: Pending
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)
**Parent Phase**: [phase-5.md](phase-5.md) — discovered while pre-flighting Phase 5's real-data smoke.

---

## Objective

Make PGS Catalog scoring files **first-class `refs fetch` sources** so the user can stage everything the PRS pipeline needs (including PGS000018) from scratch via the canonical setup path — without manual `curl`s, manual placement, or undocumented prerequisites.

Discovered while pre-flighting [Phase 5's smoke driver](phase-5.md): the driver's pre-flight fails with `scorefile missing: <path>` because there's no `refs fetch` source for it. The user's expectation (correct): every piece of reference data the pipeline consumes should be reachable via `host setup --fetch-all` / `refs fetch`, not require manual handling. Phase 5a closes that gap before Phase 5's smoke runs.

## Scope Boundaries

- **In scope**:
  - New `pgs_scorefile` source in [`fetch.py:_LAYOUTS`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py), parameterised by the PGS Catalog ID (using the existing `{release_n}` substitution machinery — the PGS ID becomes the "release" string).
  - `pgs_scorefile` entry in [`release_sets/default.toml`](../../../../packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml) for `PGS000018` (the smoke baseline). Additional canonical PGS IDs (PGS003725 / caPRS / etc.) are deferred to a future doc-set expansion.
  - Doctor probe `_collect_pgs_scorefiles_ready` surfacing per-PGS scorefile presence under `reference/pgs_scorefiles/`.
  - Smoke driver pre-flight: when the scorefile is missing, the message points at `genomeclaw refs fetch --source pgs_scorefile --release <PGS_ID>` (not at a manual download).
  - One real-fetch validation against the live PGS Catalog FTP (URL `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/PGS000018/ScoringFiles/Harmonized/PGS000018_hmPOS_GRCh38.txt.gz`).

- **Out of scope**:
  - A per-PGS metadata index / mirror catalog (just one file per ID is enough for MVP).
  - PGS Catalog scorefile SHA256 verification (the file's content shapes its Tier 2 cache key already; an upstream re-harmonization invalidates the cache automatically per Phase 2's design — separate SHA verification would be belt-and-braces).
  - VCF integrity verification — these are TSVs, not bgzip files.
  - Adding more PGS IDs to the release set (PGS003725, caPRS) — Phase 5b decision once Phase 5's smoke validates the bridge.

## Invariants Enforced in This Phase

- **INV-D001**: scorefile is a reference artifact; landed under `reference/pgs_scorefiles/` read-only at runtime.
- **INV-P001**: fetching the scorefile is a **named, deliberate egress destination** (the existing `refs fetch` machinery). No new egress paths outside `refs fetch`.
- **INV-R001**: the release-set toml records the PGS Catalog ID as the release string. Two users on the same toolkit version + same release_set fetch the same scorefile.

---

## TDD Steps

### Step 5a.1 — RED: Write Failing Tests

**Test cases** (target: 6 tests):

1. `test_pgs_scorefile_layout_declared` — `_LAYOUTS["pgs_scorefile"]` exists; its single file's `relpath` carries `{release_n}` substitution + targets the canonical PGS Catalog FTP path.
2. `test_pgs_scorefile_default_base_url_is_pgs_catalog_ftp` — `_DEFAULT_BASE_URLS["pgs_scorefile"] == "https://ftp.ebi.ac.uk"`.
3. `test_pgs_scorefile_fetch_happy_path_via_pytest_httpserver` — synthetic HTTP server serves a tiny scoring file at the expected URL; `fetch(source="pgs_scorefile", release="PGS000018", ...)` lands it at `reference/pgs_scorefiles/PGS000018_hmPOS_GRCh38.txt.gz`.
4. `test_pgs_scorefile_skip_detection_invD001` — second `fetch` against the same release raises `VersionAlreadyExists` (the file's existence is the durable signal; no `presence_relpath` needed because there's no post-fetch transform).
5. `test_pgs000018_in_default_release_set` — `release_sets/default.toml` lists `pgs_scorefile` with release `PGS000018`.
6. `test_doctor_reports_pgs_scorefile_present_when_staged` — doctor's new section reports `status: "ready"` when `reference/pgs_scorefiles/PGS000018_hmPOS_GRCh38.txt.gz` exists; `"missing"` with a fix hint otherwise.

**Sketch**:

```python
@pytest.fixture
def _PGS_SCOREFILE_RELPATH() -> str:
    return (
        "/pub/databases/spot/pgs/scores/PGS000018/"
        "ScoringFiles/Harmonized/PGS000018_hmPOS_GRCh38.txt.gz"
    )


def test_pgs_scorefile_fetch_happy_path_via_pytest_httpserver(
    httpserver: HTTPServer, tmp_path: Path
) -> None:
    from genomeclaw_toolkit.prep.fetch import fetch

    httpserver.expect_request(_PGS_SCOREFILE_RELPATH).respond_with_data(
        b"#pgs_id=PGS000018\nhm_chr\thm_pos\teffect_allele\tother_allele\teffect_weight\n22\t20001\tG\tA\t0.0123\n"
    )
    base_url = httpserver.url_for("").rstrip("/")

    fetch(
        source="pgs_scorefile",
        reference_root=tmp_path,
        release="PGS000018",
        base_url=base_url,
    )

    target = tmp_path / "pgs_scorefiles" / "PGS000018_hmPOS_GRCh38.txt.gz"
    assert target.exists()
    assert target.stat().st_size > 0
```

After writing the tests, run them and **confirm they fail for the intended reason** — `KeyError: 'pgs_scorefile'` from `_LAYOUTS`. Paste the failing output into [work-notes.md](../work-notes.md).

### Step 5a.2 — GREEN: Minimal Implementation

**Files affected**:

- `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` — MODIFY:
  - Add `pgs_scorefile` to `_LAYOUTS`. Single `_FetchFile` with `relpath="/pub/databases/spot/pgs/scores/{release_n}/ScoringFiles/Harmonized/{release_n}_hmPOS_GRCh38.txt.gz"`, `output_filename="{release_n}_hmPOS_GRCh38.txt.gz"`, `output_subdir="pgs_scorefiles"`. No post-fetch hook (the .txt.gz is consumed directly).
  - Add `pgs_scorefile` to `_DEFAULT_BASE_URLS` → `"https://ftp.ebi.ac.uk"`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml` — MODIFY: add a `[[sources]]` block for `pgs_scorefile` / `PGS000018`.
- `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` — MODIFY: add `_collect_pgs_scorefiles_ready(reference_root, release_set)` informational section. Mirrors `_collect_ancestry_ready`'s pattern. Wired into `doctor()`'s report dict.
- `packages/toolkit/tests/integration/test_refs_fetch_pgs_scorefile.py` — CREATE: tests 1–5.
- `packages/toolkit/tests/integration/test_doctor.py` — MODIFY: add test 6 (`test_doctor_reports_pgs_scorefile_present_when_staged`).
- `bin/genomeclaw-prs-smoke` — MODIFY: update the scorefile pre-flight message to cite `genomeclaw refs fetch --source pgs_scorefile --release <PGS_ID>` instead of just "missing".

### Step 5a.3 — REFACTOR

- Verify the real fetch works: `curl -I https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/PGS000018/ScoringFiles/Harmonized/PGS000018_hmPOS_GRCh38.txt.gz` returns 200; then `bin/genomeclaw refs fetch --source pgs_scorefile --release PGS000018` actually downloads the ~12 MB file.
- Lint + type check clean.
- Full suite green.

---

## Implementation Details

### URL pattern

PGS Catalog publishes the harmonised scoring files at:

```text
https://ftp.ebi.ac.uk/pub/databases/spot/pgs/scores/<PGS_ID>/ScoringFiles/Harmonized/<PGS_ID>_hmPOS_GRCh38.txt.gz
```

Where `<PGS_ID>` is the PGS Catalog ID (e.g., `PGS000018`). The same pattern holds for every published score; only the ID varies. Files are typically 5–50 MB compressed depending on variant count.

The hmPOS_GRCh38 harmonisation suffix is what pgsc_calc expects + what Phase 3b3a's `_extract_pgs_id_from_scorefile` parses. Don't accept the non-harmonised native form — pgsc_calc requires the harmonisation for cross-build consistency.

### Cache key + invalidation

Phase 2's Tier 2 cache key already includes the scorefile's SHA-8 (`pgs/<PGS_ID>-<sha8>/tier2.vcf.gz`). When PGS Catalog re-harmonises a scoring file (rare but it happens), the new download's SHA changes → Tier 2 cache misses → re-builds. **No separate verification step needed** at the fetch layer; the cache-key mechanism already provides the right cache invalidation. The fetch layer's job is just to write the file deterministically.

### Doctor probe shape

Mirrors `_collect_ancestry_ready`'s pattern:

```json
{
    "status": "ready" | "partial" | "missing",
    "release_set_pgs_ids": ["PGS000018"],
    "present_pgs_ids": ["PGS000018"],
    "missing_pgs_ids": [],
    "fix": "Install with `genomeclaw refs fetch --source pgs_scorefile --release <PGS_ID>`."
}
```

`status: "ready"` when every PGS ID in the release set has its scorefile staged. `status: "partial"` when some are present. `status: "missing"` when none.

### Edge Cases to Handle

- **Upstream URL change**: the PGS Catalog URL has been stable since 2021 but isn't immutable. If the fetch fails with 404, the wrapper's error surfaces the constructed URL so the user sees what was attempted.
- **PGS ID validation**: invalid IDs like `PGS999999` (nonexistent) return 404 from the FTP. The error message includes the URL + the PGS Catalog browse link (`https://www.pgscatalog.org/score/<PGS_ID>/`) so the user can sanity-check.
- **Network egress under INV-P001**: the fetch is a deliberate named egress; nothing new vs. existing `refs fetch` semantics.

### Privacy / Egress Notes

This adds **one** new URL pattern to the existing `refs fetch` egress envelope. Already-named egress destination; no new privacy surface.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | MODIFY | Add `pgs_scorefile` to `_LAYOUTS` + `_DEFAULT_BASE_URLS` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml` | MODIFY | Add `pgs_scorefile` entry for PGS000018 |
| `packages/toolkit/src/genomeclaw_toolkit/prep/doctor.py` | MODIFY | New `_collect_pgs_scorefiles_ready` section |
| `packages/toolkit/tests/integration/test_refs_fetch_pgs_scorefile.py` | CREATE | Tests 1–5 |
| `packages/toolkit/tests/integration/test_doctor.py` | MODIFY | Test 6 |
| `bin/genomeclaw-prs-smoke` | MODIFY | Pre-flight error message references `refs fetch` |

---

## Verification

```bash
# Tests
cd packages/toolkit
uv run pytest tests/integration/test_refs_fetch_pgs_scorefile.py tests/integration/test_doctor.py -v

# Real fetch (validates the URL pattern against the live PGS Catalog FTP)
bin/genomeclaw refs fetch --source pgs_scorefile --release PGS000018
ls -la /Volumes/Genome_Work/genomeclaw/reference/pgs_scorefiles/

# End-to-end via host setup (verifies the release-set wiring picks it up)
bin/genomeclaw host setup --fetch-all
# Should include PGS000018 in the fetch sequence
```

---

## Completion Criteria

- [ ] All 6 tests pass.
- [ ] `bin/genomeclaw refs fetch --source pgs_scorefile --release PGS000018` actually downloads the file from the real PGS Catalog FTP.
- [ ] `bin/genomeclaw refs list` shows `pgs_scorefile` in its source list.
- [ ] `bin/genomeclaw host doctor` reports `pgs_scorefiles_ready: ready` when the file is staged.
- [ ] Phase 5's smoke driver's pre-flight message points at `refs fetch` (not at manual download instructions).
- [ ] Lint + mypy clean across the touched files.

---

## Open Risks

- **PGS Catalog URL stability**: if EBI restructures the FTP layout, the URL pattern breaks. Mitigated by the live-fetch verification step — if it fails, we update the pattern before Phase 5 runs.
- **Release-set proliferation**: as more canonical PGS IDs land (PGS003725 / caPRS / etc.), the release_set toml grows. Phase 5b decides which become defaults.
