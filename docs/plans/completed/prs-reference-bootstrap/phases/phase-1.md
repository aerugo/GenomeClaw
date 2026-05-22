# Phase 1: Fetcher + Release-Set Integration

**Status**: Pending
**Goal**: Make `genomeclaw refs fetch --source pgs_catalog_ancestry --release v1` materialise the PGS Catalog ancestry bundle into `reference/pgs_catalog_ancestry/v1/{1000g,hgdp}/` end-to-end, and repoint Slice E v2's ancestry-reference check at the canonical layout.

---

## Invariants Enforced in This Phase

- **INV-D001** Raw Genomic Files Are Source-of-Truth — covered by skip-detection test (second `refs fetch` raises `VersionAlreadyExists`; no overwrite).
- **INV-R001** Rebuildability — covered by canonical-filename inventory test (every file the layout declares is present after fetch).

---

## TDD Steps

### Step 1.1 — RED: failing test cases

Create `packages/toolkit/tests/integration/test_refs_fetch_pgs_ancestry.py` with:

1. **`test_fetch_pgs_catalog_ancestry_happy_path`** — given a mocked HTTP server returning a synthetic tiny `.tar.zst` containing `1000g/sample.pgen` + `hgdp/sample.pgen`, assert that `fetch(source="pgs_catalog_ancestry", release="v1", ...)` produces `reference/pgs_catalog_ancestry/v1/1000g/sample.pgen` and `.../hgdp/sample.pgen` on disk.

2. **`test_fetch_pgs_catalog_ancestry_skip_detection_invD001`** — second invocation against the same `--release` raises `VersionAlreadyExists` without re-downloading. Assert mock HTTP server received exactly one request.

3. **`test_fetch_pgs_catalog_ancestry_bad_checksum_fails`** — if upstream MD5/SHA256 is available and the download body doesn't match, fetch raises and leaves `_staging/` cleaned up.

4. **`test_fetch_pgs_catalog_ancestry_canonical_filenames_invR001`** — after a successful fetch, every filename declared in `_LAYOUTS["pgs_catalog_ancestry"]` is present on disk under the expected relative path.

5. **`test_check_ancestry_reference_resolves_canonical_layout`** — extend `tests/integration/test_pgsc_calc_wrapper.py` (or add new file): stage `reference/pgs_catalog_ancestry/v1/{1000g,hgdp}/` directly, call `_check_ancestry_reference(reference_root)` from `prep/pgs.py`, assert it does **not** raise.

6. **`test_check_ancestry_reference_missing_install_hint_points_at_real_command`** — when `_check_ancestry_reference` raises `PgsReferenceMissingError`, the message contains the literal string `genomeclaw refs fetch --source pgs_catalog_ancestry` (matches the actual subcommand).

**Run**: `uv run pytest packages/toolkit/tests/integration/test_refs_fetch_pgs_ancestry.py -v` — confirm all six fail for the right reason (no `_LAYOUTS` entry, install hint mismatch).

### Step 1.2 — GREEN: minimal implementation

1. **`packages/toolkit/Dockerfile`** — add `zstd` to the Stage 1 micromamba `mamba install` line. Rebuild and tag as `genomeclaw/toolkit:prs-refs-phase1`.

2. **`packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py`** — add `_LAYOUTS["pgs_catalog_ancestry"]` entry:
   - upstream URL: `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/pgsc_HGDP+1kGP_<release>.tar.zst` (parametrise the release tag)
   - canonical filename list: confirmed from Phase 1 manual extraction (`1000g/*.pgen`, `1000g/*.pvar`, `1000g/*.psam`, `hgdp/*.pgen`, `hgdp/*.pvar`, `hgdp/*.psam` — confirm exact set against actual extract)
   - post-fetch hook: shell out to `tar --use-compress-program=unzstd -xf <bundle>.tar.zst -C reference/pgs_catalog_ancestry/<release>/`, then `rm <bundle>.tar.zst`
   - if extracted bundle nests under outer `pgsc_HGDP+1kGP_<release>/`, flatten via `mv pgsc_HGDP+1kGP_<release>/* . && rmdir pgsc_HGDP+1kGP_<release>` in the post-hook

3. **`packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml`** — append:
   ```toml
   [[sources]]
   source = "pgs_catalog_ancestry"
   release = "v1"
   ```

4. **`packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py`** — `_check_ancestry_reference`:
   - change probe path from `reference_root / "ancestry" / "1000g"` to `reference_root / "pgs_catalog_ancestry" / "v1" / "1000g"` (same for `hgdp`). Use the release tag from a constant or surface it as a parameter — defer the parameterisation question to E.3 (the orchestrator already knows which release it requested).
   - install hint exactly: `"genomeclaw refs fetch --source pgs_catalog_ancestry --reference-root <root>"`

5. Run tests until all six pass.

### Step 1.3 — REFACTOR

- Extract the `.tar.zst` extraction into a small reusable helper (`_extract_tar_zstd(bundle_path, dest_dir)`) — future sources may use the same format.
- Verify the `_LAYOUTS` entry shape matches the existing entries' conventions (don't introduce a new field unless every source would benefit).
- Re-run full suite: `uv run pytest packages/toolkit/tests` — confirm no regressions.

---

## Files

### CREATE

| File | Purpose |
|------|---------|
| `packages/toolkit/tests/integration/test_refs_fetch_pgs_ancestry.py` | End-to-end mocked-HTTP fetch coverage |

### MODIFY

| File | Change |
|------|--------|
| `packages/toolkit/Dockerfile` | Add `zstd` to Stage 1 micromamba env |
| `packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py` | Add `_LAYOUTS["pgs_catalog_ancestry"]` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml` | Add release-set entry |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | Repoint `_check_ancestry_reference` at canonical path; align install hint |
| `packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py` | Extend with canonical-layout + install-hint tests (or move those to the new file) |

---

## Verification

```bash
# Static + unit
uv run ruff check packages/toolkit
uv run ruff format --check packages/toolkit
uv run pytest packages/toolkit/tests/integration/test_refs_fetch_pgs_ancestry.py -v
uv run pytest packages/toolkit/tests -x

# Real-data smoke (project owner's host, not committed as a test)
genomeclaw refs fetch --source pgs_catalog_ancestry --release v1
genomeclaw refs list  # expect pgs_catalog_ancestry: OK
ls -la /Volumes/Genome_Work/genomeclaw/reference/pgs_catalog_ancestry/v1/{1000g,hgdp}/
```

---

## Completion Criteria

- [ ] All 6 phase tests pass (RED → GREEN → REFACTOR visible in commit history)
- [ ] `ruff check` + `ruff format` clean on the toolkit package
- [ ] Full toolkit test suite still green (no regressions in the existing 593-pass / 99-skip baseline)
- [ ] At least one test references `INV-D001` (skip-detection) and one references `INV-R001` (canonical-filename inventory)
- [ ] Real-data smoke passes on the project owner's host (documented in work-notes, not committed)
- [ ] `prep/pgs.py` install hint string exactly matches the real subcommand
- [ ] Phase status updated to **Complete** in `development-plan.md` and `work-notes.md`
