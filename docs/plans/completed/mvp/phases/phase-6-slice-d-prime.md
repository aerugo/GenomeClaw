# Phase 6 Slice D' — PharmCAT pipeline + PGx findings emit

**Status**: **Complete** — real-data smoke against MPNRGLQ2K VCF + Slice D's CYP2D6 *1/*35 outside-call (2026-05-22) returned **9 user-applicable, actionable PGx findings** persisted to `findings` with `evidence_ref=pharmgkb:<id>` + `clinical_escalation=confirm_with_provider`. 135s wall.
**Started**: 2026-05-22
**Completed**: 2026-05-22
**Parent Plan**: [development-plan.md](../development-plan.md)
**Parent Phase**: [phase-6.md](phase-6.md)
**Sibling Slice**: [phase-6-slice-d.md](phase-6-slice-d.md) — Cyrius wrapper (closed 2026-05-22, produced CYP2D6 `*1/*35`)
**Spec**: [spec.md § AC4 (PGx findings) / Q6 (PharmCAT outside-call)](../spec.md)

---

## Objective

Stand up the host-side PharmCAT v3.2.0 pipeline behind a thin `prep/pharmcat.py` wrapper + a `genomeclaw pipeline pharmcat` CLI subcommand. PharmCAT consumes the user's VCF + Slice D's `cyp2d6_diplotype.json` (via PharmCAT's outside-call interface) and emits structured PGx recommendations. The slice converts those recommendations into `clinical-actionable` `findings` rows with `evidence_ref=pharmgkb:<id>` and `clinical_escalation=confirm_with_provider` — closing the user-facing half of the CYP2D6 PGx path that Story 4 depends on.

This is the third "wrapper + subcommand + findings emit" slice mirroring `pgs-compute` (Slice E.2) and `cyp2d6-call` (Slice D). Same pattern: typed `PharmCATConventions` dataclass (INV-T001 contract), pre-flight reference checks, subprocess-mock unit tests, real-data smoke as the GREEN-gate close-out.

## Scope Boundaries

- **In scope**:
  - `packages/toolkit/src/genomeclaw_toolkit/prep/_pharmcat_conventions.py` — INV-T001 typed dataclass pinning PharmCAT v3.2.0 argv + output JSON schema.
  - `packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py` — `run_pharmcat(*, vcf, run_dir, cyp2d6_diplotype_json, ...)` wrapper. Reads the Cyrius envelope, emits the outside-call TSV PharmCAT expects, invokes `pharmcat_pipeline`, parses the phenotype + recommendation JSONs, returns a typed list of `PharmCATFinding` rows.
  - `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` — `pharmcat` subcommand wrapping the call with `--vcf` / `--run-dir` / `--cyp2d6-diplotype-json` flags. INSERTs each emitted finding into `findings` with the canonical seven INV-R001 provenance columns + `evidence_ref=pharmgkb:<id>` + `clinical_escalation=confirm_with_provider` per INV-C001.
  - `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` — add `PGX_RUNTIME_VERSIONS["pharmcat"] = "3.2.0"`.
  - `packages/toolkit/Dockerfile` — new Stage `pharmcat` downloads + extracts the `pharmcat-pipeline-3.2.0.tar.gz` GitHub release artifact into `/opt/pharmcat/`. Runtime stage COPYs it + adds the entrypoint to PATH.
  - Unit tests against `subprocess.run` mock — wrapper argv shape, outside-call TSV emission, output parsing, INV-T001 dataclass pin matches `_versions.py`.
  - Integration tests for the CLI subcommand → DB insert path.
  - Real-data smoke against the project owner's VCF + Slice D's `cyp2d6_diplotype.json`.
- **Out of scope** (deferred):
  - PharmCAT's secondary genes beyond what the user's VCF + Cyrius outside-call cover. PharmCAT will emit recommendations for whatever genes it has data for; we INSERT what it produces, no curation.
  - The `annotate` step orchestrator integration. PharmCAT runs as its own subcommand mirroring `pgs-compute` (Slice E.2) — composing it into a one-shot `pipeline run` is a separate concern.
  - Web-rendered HTML report (`<prefix>.report.html`) — PharmCAT produces it; the agent path doesn't consume it; we keep the file on disk but don't parse it.
  - Multi-sample VCFs. v0 supports one VCF per invocation matching the toolkit's run-per-sample architecture.

## Invariants Enforced in This Slice

- **INV-T001** — `PharmCATConventions` frozen dataclass pins argv + output JSON schema; `verified_against_version` matches `PGX_RUNTIME_VERSIONS["pharmcat"]`; the discovery sweep in `test_invT001_tool_conventions_exist.py` extends to include `pharmcat` in `_STRICT_TOOLS`.
- **INV-R001** — every `findings` row INSERTed by the CLI carries the seven canonical provenance columns. `params_json` records the PharmCAT version + the CYP2D6 outside-call source (Slice D run-id).
- **INV-E001** — every emitted finding carries `evidence_ref=pharmgkb:<id>` (one ID per gene per PharmCAT's recommendation namespace).
- **INV-C001** v1.5 — `clinical-actionable` findings carry `clinical_escalation=confirm_with_provider`. The agent's prose-layer responsibility (Story 4 live snapshot) verifies the escalation surface; this slice just ensures the structured marker is set on the DB row.

## TDD Steps

### Step D'.1 — RED: write failing tests

Test files (all under `packages/toolkit/tests/`):

1. `unit/test_pharmcat_conventions.py` (3 tests):
   - `test_pharmcat_conventions_dataclass_exists_and_is_frozen`
   - `test_pharmcat_conventions_verified_against_version_matches_pin`
   - `test_pharmcat_conventions_argv_fields_are_non_empty_strings`
2. `unit/test_pharmcat_wrapper.py` (6 tests, `subprocess.run` mocked):
   - `test_run_pharmcat_argv_uses_conventions` — wrapper consumes `PharmCATConventions` fields rather than hardcoded literals.
   - `test_run_pharmcat_emits_outside_call_tsv` — wrapper reads `cyp2d6_diplotype.json` + writes the TSV PharmCAT expects (`gene\tdiplotype\n` for CYP2D6).
   - `test_run_pharmcat_writes_phenotype_json` — successful call writes `<run_dir>/pharmcat/<prefix>.report.json` (or whatever PharmCAT actually emits — verified at probe time).
   - `test_run_pharmcat_parses_findings_from_recommendations` — fixture PharmCAT output → list of `PharmCATFinding` rows.
   - `test_run_pharmcat_raises_on_nonzero_rc` — non-zero rc surfaces RuntimeError with stderr tail.
   - `test_run_pharmcat_threads_cyp2d6_diplotype_through_outside_call` — the diplotype from `cyp2d6_diplotype.json` lands in the emitted outside-call TSV.
3. `integration/test_cli_pipeline_pharmcat.py` (4 tests):
   - `test_cli_pharmcat_writes_findings_with_pharmgkb_evidence_refs` — each emitted finding has `evidence_ref=pharmgkb:<id>`.
   - `test_cli_pharmcat_stamps_inv_r001_provenance_on_each_finding_row`
   - `test_cli_pharmcat_marks_actionable_findings_with_clinical_escalation` — INV-C001 v1.5 structural check.
   - `test_cli_pharmcat_emits_machine_readable_json` — `--json` envelope shape per INV-C002.
4. `invariants/test_invT001_tool_conventions_exist.py` — extend `_STRICT_TOOLS` to include `pharmcat`.

### Step D'.2 — GREEN: minimal implementation

1. **`_versions.py`** — add `PGX_RUNTIME_VERSIONS["pharmcat"] = "3.2.0"`.
2. **`_pharmcat_conventions.py`** — frozen dataclass. Fields documented against the upstream PharmCAT v3.2.0 README + the empirical probe (captured during Step D'.4):
   - `verified_against_version: str = "3.2.0"`
   - `entrypoint: str = "pharmcat_pipeline"` (the Python wrapper that handles preprocessing + JAR invocation)
   - `vcf_flag: str` — TBD via probe (likely positional or `--vcf`)
   - `outside_call_flag: str = "--outside-call-file"` (per upstream README)
   - `output_dir_flag: str = "-o"` or `--output-dir`
   - `outside_call_tsv_header: tuple[str, ...]` — TBD via empirical probe
   - `phenotype_output_filename_template: str` — TBD
   - `report_output_filename_template: str` — TBD
3. **`prep/pharmcat.py`** — defines:
   - `PharmCATFinding` frozen dataclass: `gene`, `diplotype`, `phenotype`, `pharmgkb_id`, `recommendation_summary`, `clinical_escalation_required: bool`.
   - `run_pharmcat(*, vcf, run_dir, cyp2d6_diplotype_json, conventions=None) -> list[PharmCATFinding]`.
   - Reads `cyp2d6_diplotype.json`, writes outside-call TSV, invokes `pharmcat_pipeline`, parses output JSONs.
4. **`_cli/commands/pipeline.py`** — `pharmcat` Typer subcommand. INSERTs one `findings` row per `PharmCATFinding` with the seven canonical INV-R001 provenance columns + `category=clinical-actionable` + `clinical_escalation=confirm_with_provider` per INV-C001.
5. **INV-T001 discovery test** — extend `_STRICT_TOOLS` roster.

### Step D'.3 — REFACTOR

- Extract outside-call TSV serializer if it grows beyond a few lines.
- Tighten error messages on the non-zero rc + missing-Cyrius-diplotype paths.
- Documentation comments above `PharmCATConventions` linking to upstream v3.2.0 docs.

### Step D'.4 — Image build + empirical probe

1. Add `pharmcat-pipeline-3.2.0.tar.gz` download to a new Stage `pharmcat` in the Dockerfile. Mirrors the Stage `cyrius` pattern from Slice D (debian + curl/tar + extract).
2. Build the image: `docker build -t genomeclaw/toolkit:slice-d-prime packages/toolkit/`.
3. Capture probe at `tools/pharmcat/probe-output.txt` (`pharmcat_pipeline --help` + the outside-call TSV header from the upstream docs); reconcile any diff against `PharmCATConventions` defaults.
4. Run a synthetic smoke against a tiny test VCF to verify the wrapper threads through correctly before the real-data run.

### Step D'.5 — Real-data smoke

```bash
GENOMECLAW_IMAGE=genomeclaw/toolkit:slice-d-prime bin/genomeclaw pipeline pharmcat \
    --vcf /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz \
    --cyp2d6-diplotype-json /mnt/genomeclaw/derived/2026-05-22T09-30-XXZ-cyriusd/cyp2d6_diplotype.json \
    --run-dir /mnt/genomeclaw/derived/<new-run-id> \
    --json
```

Expected: a `findings` row per PharmCAT-actionable gene (CYP2D6 from outside-call + whatever else PharmCAT extracts from the VCF — likely CYP2C19, DPYD, TPMT, others). Wall: ~5-15 min (PharmCAT's preprocessor scans the VCF; the JAR is fast).

---

## Implementation Details

### PharmCAT v3.2.0 outside-call TSV format

Per the upstream PharmCAT v3 docs, the outside-call file is a TSV with these columns:

```
gene<TAB>diplotype<TAB>phenotype<TAB>activity_score
```

For CYP2D6 from Cyrius:
```
CYP2D6	*1/*35
```

(The phenotype + activity_score columns are optional — PharmCAT computes them from the diplotype using its internal lookup tables. The slice's v0 emits only `gene` + `diplotype`.)

**The actual column ordering + header presence is TBD via the empirical probe at Step D'.4** — the conventions dataclass pins what we discover.

### PharmCAT output JSON shapes

PharmCAT v3 emits (roughly, per upstream docs):
- `<prefix>.match.json` — variant→haplotype matches per gene
- `<prefix>.phenotype.json` — diplotype + phenotype per gene
- `<prefix>.report.json` — recommendations + clinical-annotation refs

The slice parses `report.json` since that's the recommendation-level surface. Each recommendation carries:
- `gene`
- `diplotype`
- `phenotype`
- `drug` (the affected drug, e.g. codeine)
- `pharmgkb_clinical_annotation_id` (the `pharmgkb:PA<n>` evidence ref)
- `recommendation_summary` (free text)

Exact field names + nesting **TBD via the empirical probe** (running PharmCAT against a known-result test VCF and capturing the actual output schema).

### `findings` row emit per recommendation

For each PharmCAT recommendation, the CLI INSERTs:

```sql
INSERT INTO findings (
    id, category, title, summary,
    evidence_ref, evidence_quality,
    gene_symbols, drugs, clinical_escalation,
    source_path, source_sha256, tool, tool_version,
    params_json, schema_version, created_at
) VALUES (
    'fnd-pharmcat-<gene>-<drug>',
    'clinical-actionable',
    '<gene> <diplotype> — <phenotype> (re <drug>)',
    '<recommendation_summary>',
    'pharmgkb:<clinical_annotation_id>',
    'high',
    ARRAY['<gene>'],
    ARRAY['<drug>'],
    'confirm_with_provider',
    '<vcf_path>',
    '<vcf_sha256>',
    'pharmcat',
    '3.2.0',
    '{"cyp2d6_diplotype": "*1/*35", "cyp2d6_outside_call_source": "<slice-d run-id>"}',
    'v0.2',
    NOW()
)
```

### Edge cases

- **No outside-call provided**: PharmCAT runs against the VCF only; CYP2D6 calls are absent or "indirect" (unreliable from VCF alone). The wrapper accepts `cyp2d6_diplotype_json=None` for this case; the user just doesn't get the CYP2D6 finding.
- **PharmCAT recommends but no `pharmgkb:<id>` present**: rare but possible for low-confidence recommendations. Skip the finding rather than emit one with empty `evidence_ref` (INV-E001 violation).
- **Multiple recommendations per gene** (e.g. CYP2D6 affects codeine, tamoxifen, fluoxetine independently): emit one finding per `gene × drug` pair, with the corresponding `pharmgkb:<id>` for each. Avoids collapsing distinct clinical guidance into one row.

### Privacy / egress notes

The wrapper introduces **zero new egress surfaces**. PharmCAT is host-side; the VCF never leaves the local environment. The PharmCAT JAR + preprocessor scripts ship in the toolkit image (downloaded at image-build time from GitHub).

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_pharmcat_conventions.py` | CREATE | INV-T001 dataclass pinning PharmCAT v3.2.0 |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pharmcat.py` | CREATE | `run_pharmcat(...)` wrapper + `PharmCATFinding` |
| `packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py` | MODIFY | Add `PGX_RUNTIME_VERSIONS["pharmcat"]` |
| `packages/toolkit/src/genomeclaw_toolkit/_cli/commands/pipeline.py` | MODIFY | `pharmcat` Typer subcommand + `_stamp_pharmcat_findings(...)` |
| `packages/toolkit/Dockerfile` | MODIFY | New Stage `pharmcat`; COPY + PATH in runtime |
| `packages/toolkit/tests/unit/test_pharmcat_conventions.py` | CREATE | 3 unit tests for the dataclass |
| `packages/toolkit/tests/unit/test_pharmcat_wrapper.py` | CREATE | 6 unit tests for `run_pharmcat(...)` |
| `packages/toolkit/tests/integration/test_cli_pipeline_pharmcat.py` | CREATE | 4 integration tests for the CLI + DB insert |
| `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` | MODIFY | `_STRICT_TOOLS` += `pharmcat` |
| `tools/pharmcat/probe.sh` + `probe-output.txt` | CREATE | Empirical probe baseline |

---

## Verification

```bash
# Unit + integration tests (mocked subprocess)
cd packages/toolkit
uv run pytest tests/unit/test_pharmcat_conventions.py tests/unit/test_pharmcat_wrapper.py -v
uv run pytest tests/integration/test_cli_pipeline_pharmcat.py -v
uv run pytest tests/invariants/test_invT001_tool_conventions_exist.py -v

# Full suite — confirm no regressions
uv run pytest tests/unit tests/integration tests/invariants --no-header -q

# Image build + real-data smoke
docker build -t genomeclaw/toolkit:slice-d-prime packages/toolkit/
GENOMECLAW_IMAGE=genomeclaw/toolkit:slice-d-prime bin/genomeclaw pipeline pharmcat \
    --vcf $NEBULA_VCF \
    --cyp2d6-diplotype-json $CYP2D6_JSON \
    --run-dir $DERIVED/<new-run-id> \
    --json
```

---

## Completion Criteria

- [x] All 16 unit + integration test cases pass (3 conventions + 7 wrapper + 4 CLI + 2 INV-T001 discovery)
- [x] INV-T001 discovery test passes (`PharmCATConventions` in `_STRICT_TOOLS`)
- [x] Each emitted `findings` row carries `evidence_ref=pharmgkb:<id>` (INV-E001) + `clinical_escalation=confirm_with_provider` (INV-C001 v1.5) + the seven INV-R001 provenance columns (verified against the v3 smoke's persisted rows)
- [x] Static checks pass (ruff clean on all touched files)
- [x] Full suite remains green (**776 passed**, 109 skipped; +14 from Slice D')
- [x] Toolkit image `genomeclaw/toolkit:slice-d-prime` built with PharmCAT v3.2.0 (~6.4 GB; pandas + colorama + packaging added to Stage 1; PharmCAT release tarball extracted in new Stage `pharmcat`)
- [x] **Real-data smoke against MPNRGLQ2K VCF**: **9 user-applicable actionable PGx findings** including CYP2D6 *1/*35 (from Slice D's outside-call) → atomoxetine + tamoxifen, UGT1A1 *1/*80+*28 → atazanavir, CYP2B6 *1/*6 → efavirenz + sertraline, CYP2C19 *1/*1 → 4 PPIs. 135s wall on 50 GB CRAM's matching 4.9M-variant VCF.
- [x] `tools/pharmcat/probe.sh` + `tools/pharmcat/probe-output.txt` captured + reconciled with empirical v3.2.0 shape
- [x] `work-notes.md` updated with the 4-discovery narrative (bioconda absence + Zenodo runtime fetch + permission error + report.json schema rewrite)
- [x] Phase 6 development-plan progress row updated
