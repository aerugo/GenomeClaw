# Feature: PRS Reference-Data Bootstrap

**Status**: Draft
**Created**: 2026-05-17
**Owner**: TBD
**Related Plans**: [docs/plans/active/mvp/phases/phase-6-slice-e-v2.md](../mvp/phases/phase-6-slice-e-v2.md) (this closes the ancestry-data gap that Slice E.3's orchestrator gate will check); [docs/plans/active/prs-runtime-bootstrap/](../prs-runtime-bootstrap/) (sibling — runtime side)

---

## Goal

Make `genomeclaw refs fetch --source pgs_catalog_ancestry` a real command that materialises the 1000G + HGDP continuous-ancestry reference data needed by `pgsc_calc --run_ancestry`, on the same release-set + manifest + doctor footing as VEP cache and gnomAD.

## Background

Slice E v2 wired an ancestry-reference gate in [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py:59-75](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py#L59-L75) that points the user at:

```
genomeclaw refs fetch --source pgs_catalog_ancestry --reference-root <root>
```

**That source does not exist.** It is not in [release_sets/default.toml](../../../packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml), not in the `_LAYOUTS` table in [prep/fetch.py](../../../packages/toolkit/src/genomeclaw_toolkit/prep/fetch.py), and is consequently unreachable from `genomeclaw refs fetch --all`. The install hint is a phantom — running the suggested command errors out with "unknown source." The README explicitly promises "no host-side bioinformatics install dance" ([README.md:48](../../../README.md#L48)); this gap breaks that promise for PRS workflows.

Per `INV-C001` v1.7's PRS-decline pattern the agent will sometimes invoke compute; per the report at [docs/reports/agent-driven-prs-computation.md](../../../docs/reports/agent-driven-prs-computation.md), each compute requires the 1000G + HGDP panels for ancestry calibration. Without them, the orchestrator either (a) silently produces non-calibrated scores — violating `INV-C001` v1.7 — or (b) fails opaquely deep inside a Nextflow subprocess.

The upstream artifact is the PGS Catalog's curated reference bundle (`pgsc_HGDP+1kGP_v1.tar.zst`, ~5-7 GB compressed → ~50-60 GB extracted into `ancestry/{1000g,hgdp}/`), hosted at `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/`. This is the bundle the `pgsc_calc` maintainers themselves point users at — there is no compositing or curation step on our side, only fetch + extract + verify.

## Acceptance Criteria

Each maps to one or more tests under the phase plans.

- [ ] **AC1**: `genomeclaw refs fetch --source pgs_catalog_ancestry --release <pin>` downloads the PGS Catalog reference bundle from `ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/`, verifies it against an upstream checksum, extracts it into `reference/pgs_catalog_ancestry/<release>/{1000g,hgdp}/`, and exits 0.
- [ ] **AC2**: A second invocation with the same `--release` raises `VersionAlreadyExists` per `INV-D001` — the existing skip-detection path applies without modification.
- [ ] **AC3**: `pgs_catalog_ancestry` is listed in [release_sets/default.toml](../../../packages/toolkit/src/genomeclaw_toolkit/prep/release_sets/default.toml) so that `genomeclaw host setup --fetch-all` lands it alongside the other references.
- [ ] **AC4**: `genomeclaw refs list` reports per-source status (OK / partial / missing) for `pgs_catalog_ancestry` identically to the other multi-file sources.
- [ ] **AC5**: `genomeclaw host doctor` adds an `ancestry_ready` check that confirms both `reference/pgs_catalog_ancestry/<release>/1000g/` and `.../hgdp/` are present and contain the expected file inventory (not bare directory existence — file count + at least one canonical filename).
- [ ] **AC6**: [pgs.py:59-75](../../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py#L59-L75) `_check_ancestry_reference` is repointed at the new canonical path (`reference/pgs_catalog_ancestry/<release>/ancestry/{1000g,hgdp}/` or whatever the materialised layout produces). The install hint matches the actual subcommand exactly.
- [ ] **AC7**: The integration tests under [tests/integration/test_fetch_mocked.py](../../../packages/toolkit/tests/integration/test_fetch_mocked.py) cover the new source end-to-end against a mocked HTTP server; a separate real-data smoke against the project owner's host (`genomeclaw refs fetch --source pgs_catalog_ancestry`) is documented as a phase-completion gate.

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the ancestry panels are read-only reference data; the fetcher writes once into `reference/`, never mutates.
- **INV-D002** Sandbox Is Bioinformatics-Free — the fetcher runs on the host (inside the toolkit container); no sandbox surface change.
- **INV-P001** Privacy Default — the fetch hits `ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/`, an existing whitelisted reference mirror, on deliberate user invocation. No new always-on egress.
- **INV-R001** Rebuildability — the fetcher records `source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at` in the materialised layout per the existing fetch contract.
- **INV-C001 v1.7** Separate Research from Clinical — ancestry calibration is a *correctness* requirement for any PRS output the agent surfaces; this plan removes the silent-degradation failure mode where the reference is missing.

## Proposed New Invariants

**None new.** This plan implements existing `INV-R001` + `INV-D001` at the PGS-ancestry layer.

## Technical Requirements

### Source Data Inputs
- Upstream: `https://ftp.ebi.ac.uk/pub/databases/spot/pgs/resources/pgsc_calc/pgsc_HGDP+1kGP_v1.tar.zst` (or its current canonical release — confirm in Phase 1).
- Pinned release tag: `v1` initially; `refs fetch --release` accepts the explicit version.

### Derived Outputs
- `reference/pgs_catalog_ancestry/<release>/1000g/` — 1000 Genomes Project panel files (pgen / pvar / psam).
- `reference/pgs_catalog_ancestry/<release>/hgdp/` — Human Genome Diversity Project panel files.

### Schema / Migration Impact
- No DB schema change. The fetched bundle is on-disk reference data, not derived rows.
- Release-set TOML gains one entry: `{ source = "pgs_catalog_ancestry", release = "v1" }`.

### Pipeline / Workflow Impact
- `genomeclaw refs fetch --all` includes the new source.
- `genomeclaw refs list` reports it.
- `genomeclaw refs verify` runs structural checks (file presence + size sanity) on the extracted tree.
- `genomeclaw host doctor` adds the readiness gate.
- The Slice E.3 PGS-compute orchestrator's pre-flight check calls the existing `_check_ancestry_reference` helper, which now resolves the real layout.

### Agent / UX Impact
- Per `INV-A002` v1.7 the agent does not invoke `refs fetch` directly — this is a setup-time concern. The agent only consumes the outcome via the PGS-compute path.
- A missing reference still surfaces through the same install-hint pattern, just now pointing at a real command.

### External Dependencies
- `zstandard>=0.22` Python library — added to toolkit deps in Phase 1 (Q3 resolved). Stream-decompress via `ZstdDecompressor.stream_reader` paired with `tarfile.open(mode="r|")` keeps the multi-GB extracted tree out of memory and avoids needing a `zstd` system binary in the toolkit image. Wheels available for `linux/amd64` + `linux/arm64`.

## Privacy & Safety Considerations

- **Boundary scan**: One upstream egress to a public reference mirror (`ftp.ebi.ac.uk`), on deliberate user invocation. No PII, no telemetry, no genomic data leaves the device.
- **Default-off remote calls**: Fetch is opt-in via explicit CLI invocation, exactly like every other `refs fetch` source. `host setup --fetch-all` is itself opt-in.
- **Redaction surface**: N/A — only public reference data flows.
- **Clinical escalation**: Indirect. Ancestry calibration is a precondition for any PRS finding the agent surfaces; the plan strengthens correctness, doesn't introduce new clinical claims.

## Out of Scope

- **PGS scoring weights cache.** `pgsc_calc` fetches per-PGS weights on-demand from pgscatalog.org at compute time; that egress is governed by `INV-P001` install-time consent (separate from this plan). A pre-cache of all PGS Catalog scoring weights is intentionally not scoped — it would be ~tens of GB of mostly-unused weights.
- **Nextflow + JRE + plink install.** Sibling plan [`prs-runtime-bootstrap`](../prs-runtime-bootstrap/) covers those.
- **Alternative ancestry references** (e.g., custom local panels). The PoC uses the PGS Catalog–curated bundle; bespoke panels are a follow-up.
- **Manifest-anchored integrity beyond what `refs fetch` currently provides.** [refs-integrity-hardening](../refs-integrity-hardening/) is the umbrella for that work and applies to this source uniformly once it lands.

## Dependencies

- MVP Phase 4 refs surface (live).
- Slice E v2 wrapper + CLI (E.1 + E.2 complete) — provides the consumer side that surfaces `_check_ancestry_reference`'s install hint.

## Open Questions

- [ ] **Q1**: Is the canonical upstream release tag `v1` (matching the `pgsc_HGDP+1kGP_v1.tar.zst` filename) or does the PGS Catalog version their reference bundle independently? Confirm with a single `curl -I` against the FTP listing in Phase 1.
- [ ] **Q2**: Does the extracted bundle land directly as `1000g/` + `hgdp/`, or is there an outer `pgsc_HGDP+1kGP_v1/` directory we need to flatten? Confirm against an actual extraction in Phase 1; adjust `_LAYOUTS` accordingly.
- [x] **Q3 (resolved Phase 1)**: `zstandard` Python library, NOT `zstd` binary. Reverses the original recommendation. Reasons in [work-notes.md](work-notes.md): one Python dep with wheels on both archs; streams through `tarfile` cleanly so memory stays bounded; tests work on bare host venv without a system binary; leaves the runtime-bootstrap plan's Dockerfile changes orthogonal to ours.
- [ ] **Q4**: Does an upstream MD5 / SHA256 sidecar exist for the bundle? If yes, wire it into the same Content-Length + checksum verification pattern the gnomAD sources use; if no, defer hash recording to [refs-integrity-hardening](../refs-integrity-hardening/).
