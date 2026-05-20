# Phase 2: PgscCalcConventions Dataclass + `pgs.py` Migration

**Status**: Pending
**Started**: 2026-05-19
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Capture pgsc_calc's argv + samplesheet + filename conventions in a typed `PgscCalcConventions` frozen dataclass; migrate `pgs.py` to consume it; pin the conventions to the version in `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`. The Phase-5 smoke surfaced four pgsc_calc-related bugs (v2: `--target` vs `--input`; v6: `path_prefix` suffix); after Phase 2, the same class of mismatch produces a typed test failure rather than a silent rc=1 in a real-tool smoke.

Phase 2 promotes **INV-T001** (External-Tool Conventions Captured as Typed Wrappers) — the first instance under the new `INV-T` category.

## Scope Boundaries

- **In scope**:
  - `PgscCalcConventions` frozen dataclass; one field per pgsc_calc convention with per-field doc citation.
  - `pgs.py:_build_pgsc_calc_argv` + `pgs.py:_write_pgsc_calc_samplesheet` refactored to consume the dataclass.
  - `tools/pgsc_calc/probe.sh` + `tools/pgsc_calc/probe-output.txt` + `tools/pgsc_calc/golden-argv.txt`.
  - Unit tests that assert the dataclass field values match the recorded probe-output baseline.
  - Generic INV-T001 discovery test that walks `prep/` and asserts every external-tool wrapper has a corresponding conventions dataclass.
- **Out of scope**:
  - `Plink2Conventions`, `BcftoolsConventions`, `MosdepthConventions`, `VepConventions`. Backfill expected on next breaking-change to each tool's pin; for now, the INV-T001 discovery test flags them as missing **without failing** (warn-only mode for the existing wrappers; strict for new wrappers).
  - `SiblingMountablePath` migration (Phase 3 owns it).
  - INVARIANTS.md edits — Phase 4 lifts the proposed INV-T001 text once Phase 2's tests are green.
  - The actual `.github/workflows/test.yml` gate on probe diffs. The Phase 2 deliverable is the probe.sh + recorded golden; CI integration is a Phase 4 follow-up.

## Invariants Enforced in This Phase

- **INV-T001** (NEW) — every external-tool wrapper has a `<Tool>Conventions` frozen dataclass with `verified_against_version` populated; field values track an empirical probe-output golden; wrapper-generated argv matches `golden-argv.txt`.

The phase keeps existing invariants intact:
- **INV-R001** strengthened indirectly — `verified_against_version` on the dataclass means a future pin bump produces a typed test failure if upstream argv changes.
- **INV-D001 / INV-D002 / INV-D003 / INV-P001** unchanged.

---

## TDD Steps

### Step 2.1 — RED: Write failing tests

**Test cases**:

1. `test_pgsc_calc_conventions_dataclass_exists_and_is_frozen` — the import works; `is_dataclass(PgscCalcConventions)` is True; `frozen=True` confirmed by attempting to mutate a field and catching `FrozenInstanceError`.
2. `test_pgsc_calc_conventions_verified_against_version_matches_pin` — `PgscCalcConventions().verified_against_version == _versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`. If a future pin bump moves the pin without updating the conventions, this test fails loudly.
3. `test_pgsc_calc_conventions_input_flag_is_dash_dash_input` — `conv.input_flag == "--input"`. The regression guard for smoke v2 (`--target` was wrong).
4. `test_pgsc_calc_conventions_samplesheet_columns_match_v2_schema` — `conv.samplesheet_columns == ("sampleset", "path_prefix", "chrom", "format", "vcf_genotype_field")`. Per the pgsc_calc README schema as of v2.2.0.
5. `test_pgsc_calc_conventions_path_prefix_strips_extension` — `conv.path_prefix_strips_extension is True`. The regression guard for smoke v6 (`.vcf.gz` suffix in path_prefix was wrong).
6. `test_pgsc_calc_conventions_accession_format_template` — `conv.accession_format.format(pgs_id="PGS000018") == "PGS000018_hmPOS_GRCh38"`. The naming convention the match-rate parser depends on (Phase 3b3a in `prs-input-coverage-fill`).
7. `test_build_pgsc_calc_argv_consumes_conventions` — call `_build_pgsc_calc_argv` with a stubbed `conventions=` parameter that flips `input_flag` to `--target`; assert the emitted argv carries `--target`, not `--input`. Proves the wrapper reads the field, not a hardcoded literal.
8. `test_write_pgsc_calc_samplesheet_consumes_conventions` — call `_write_pgsc_calc_samplesheet` with a stubbed `conventions=` parameter whose `samplesheet_columns` has columns reordered; assert the emitted CSV header matches the stubbed order. Proves the writer reads the field.
9. `test_write_pgsc_calc_samplesheet_path_prefix_rule_honors_conventions` — stub `path_prefix_strips_extension=False`; pass a `.vcf.gz` file; assert the resulting CSV row's `path_prefix` column carries the full `.vcf.gz` (no stripping). Pairs with #5 — both directions covered.
10. `test_invT001_pgsc_calc_conventions_field_values_match_probe_output` — read `tools/pgsc_calc/probe-output.txt`; for each `key=value` line, assert the corresponding `PgscCalcConventions` field equals the value. The empirical contract.
11. `test_invT001_external_tool_wrappers_have_conventions_dataclasses` — the discovery test. Walks `genomeclaw_toolkit.prep` for modules named `_<tool>.py` or `_<tool>_*.py` that wrap an external binary; asserts each has an adjacent `_<tool>_conventions.py` module exporting a `<Tool>Conventions` frozen dataclass. **Warn-only** for pre-existing wrappers (plink2, bcftools, vcfanno, mosdepth, bgzip, vep) until they're backfilled; **strict** for pgsc_calc (Phase 2's case) and any newly added wrapper.

**Sketch**:

```python
# tests/unit/test_pgsc_calc_conventions.py
from dataclasses import FrozenInstanceError, is_dataclass

def test_pgsc_calc_conventions_dataclass_exists_and_is_frozen():
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    assert is_dataclass(PgscCalcConventions)
    conv = PgscCalcConventions()
    with pytest.raises(FrozenInstanceError):
        conv.input_flag = "--something"

def test_pgsc_calc_conventions_verified_against_version_matches_pin():
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    from genomeclaw_toolkit.prep._versions import PRS_RUNTIME_VERSIONS
    assert PgscCalcConventions().verified_against_version == PRS_RUNTIME_VERSIONS["pgsc_calc"]

def test_pgsc_calc_conventions_input_flag_is_dash_dash_input():
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    # The smoke v2 regression: --target was wrong; the dataclass MUST pin --input.
    assert PgscCalcConventions().input_flag == "--input"
```

**Confirm failure**: tests fail with `ModuleNotFoundError` (the module doesn't exist yet) or `ImportError` (the names aren't defined). Paste the failing output into [work-notes.md](../work-notes.md) under a "Phase 2 RED" section.

### Step 2.2 — GREEN: Minimal Implementation

**Files created**:
- `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py` — the dataclass.
- `tools/pgsc_calc/probe.sh` — runs `nextflow run pgscatalog/pgsc_calc -r <pin> --help` inside the toolkit image; pipes output to `tools/pgsc_calc/probe-output.txt`.
- `tools/pgsc_calc/probe-output.txt` — recorded golden output; each non-trivial line annotated with the convention it pins.
- `tools/pgsc_calc/golden-argv.txt` — a successful real-tool argv captured from the Phase-5 smoke (post-v6-fix).

**Dataclass shape** (illustrative; see source for full fields + docstrings):

```python
@dataclass(frozen=True)
class PgscCalcConventions:
    """pgsc_calc argv + samplesheet + filename conventions.

    Verified against pgsc_calc v2.2.0 by:
      - Reading the pgsc_calc README + Help: https://pgsc-calc.readthedocs.io/
      - Running `tools/pgsc_calc/probe.sh` on 2026-05-19; recorded baseline at
        tools/pgsc_calc/probe-output.txt.
    """

    verified_against_version: str = "v2.2.0"

    # Argv flags (smoke v2 regression: must be --input, not --target).
    input_flag: str = "--input"
    target_build_flag: str = "--target_build"
    pgs_id_flag: str = "--pgs_id"
    run_ancestry_flag: str = "--run_ancestry"
    profile_flag: str = "-profile"
    revision_flag: str = "-r"
    work_dir_flag: str = "-work-dir"

    # Samplesheet schema.
    samplesheet_columns: tuple[str, ...] = (
        "sampleset", "path_prefix", "chrom", "format", "vcf_genotype_field",
    )
    # Smoke v6 regression: path_prefix is a basename PREFIX without the
    # .vcf.gz / .vcf suffix. pgsc_calc auto-appends `.vcf`.
    path_prefix_strips_extension: bool = True
    vcf_genotype_field_default: str = "GT"

    # PGS Catalog harmonised-scoring accession format.
    accession_format: str = "{pgs_id}_hmPOS_GRCh38"

    # Output file relative paths under -work-dir.
    aggregated_scores_relpath: str = "score/aggregated_scores.txt.gz"
    match_log_filename_template: str = "{sampleset}_log.csv.gz"
```

**Wrapper migration**:

```python
# pgs.py
def _build_pgsc_calc_argv(
    *,
    samplesheet: Path,
    pgs_id: str,
    work_dir: Path,
    reference_root: Path,
    conventions: PgscCalcConventions | None = None,
) -> list[str]:
    conv = conventions or PgscCalcConventions()
    return [
        "nextflow", "run", "pgscatalog/pgsc_calc",
        conv.revision_flag, PRS_RUNTIME_VERSIONS["pgsc_calc"],
        conv.profile_flag, "docker",
        conv.input_flag, str(samplesheet),
        conv.target_build_flag, "GRCh38",
        conv.pgs_id_flag, pgs_id,
        conv.run_ancestry_flag, str(_ancestry_reference_dir(reference_root)),
        conv.work_dir_flag, str(work_dir),
    ]
```

```python
# pgs.py
def _write_pgsc_calc_samplesheet(
    *,
    vcf: Path,
    sample_id: str,
    work_dir: Path,
    conventions: PgscCalcConventions | None = None,
) -> Path:
    conv = conventions or PgscCalcConventions()
    samplesheet = work_dir / "samplesheet.csv"
    prefix = str(vcf)
    if conv.path_prefix_strips_extension:
        prefix = prefix.removesuffix(".gz").removesuffix(".vcf")
    columns = ",".join(conv.samplesheet_columns)
    samplesheet.write_text(
        f"{columns}\n"
        f"{sample_id},{prefix},,vcf,{conv.vcf_genotype_field_default}\n"
    )
    return samplesheet
```

**Discovery test** (warn-only for pre-existing wrappers):

```python
# tests/invariants/test_invT001_tool_conventions_exist.py
EXTERNAL_TOOL_MODULES = [
    "_pgsc_calc",      # Phase 2 — strict
    # The following are pre-Phase-2 wrappers; flagged as expected-missing
    # until backfill plans land per `INV-T001`'s backfill clause.
    "_bcftools",       # warn
    "_bgzip",          # warn
    "_mosdepth",       # warn
    "_vcfanno",        # warn
    "_vep",            # warn
]
STRICT_TOOLS = {"_pgsc_calc"}

def test_invT001_external_tool_wrappers_have_conventions_dataclasses():
    missing_strict = []
    missing_warn = []
    for module_stem in EXTERNAL_TOOL_MODULES:
        conv_module = f"genomeclaw_toolkit.prep.{module_stem}_conventions"
        try:
            importlib.import_module(conv_module)
        except ImportError:
            if module_stem in STRICT_TOOLS:
                missing_strict.append(module_stem)
            else:
                missing_warn.append(module_stem)
    assert not missing_strict, f"INV-T001: missing strict-required conventions: {missing_strict}"
    # warn-only path: print but don't fail. Backfill plans land per INV-T001.
    if missing_warn:
        print(f"INV-T001 warn: pre-existing wrappers awaiting backfill: {missing_warn}")
```

### Step 2.3 — REFACTOR

With tests green:
- Verify ruff + mypy clean across the new files.
- Probe.sh is bash; shellcheck if available.
- Ensure `_pgsc_calc_conventions.py` is importable from `pgs.py` without a circular import.
- Add a docstring example to `PgscCalcConventions` showing a real argv construction.

---

## Implementation Details

### probe.sh shape

```bash
#!/usr/bin/env bash
# tools/pgsc_calc/probe.sh — capture pgsc_calc's contract under the current pin.
# Re-run when `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes.

set -euo pipefail

IMAGE="${GENOMECLAW_TOOLKIT_PRS_IMAGE:-genomeclaw/toolkit:prs-phase5a}"
PIN=$(grep -oE 'v[0-9]+\.[0-9]+\.[0-9]+' \
  "$(dirname "$0")"/../../packages/toolkit/src/genomeclaw_toolkit/prep/_versions.py | head -1)

OUT="$(dirname "$0")/probe-output.txt"
{
  echo "# pgsc_calc probe-output — captured $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "# Pin: $PIN"
  echo "# Image: $IMAGE"
  echo "#"
  echo "# Format: KEY=VALUE on its own line; lines starting with # are comments."
  echo "# Field semantics: see tests/unit/test_pgsc_calc_conventions.py and"
  echo "# packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py."
  echo
  docker run --rm --user 0:0 \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -e NXF_HOME=/opt/nextflow \
    "$IMAGE" \
    /opt/conda-prs/bin/nextflow run pgscatalog/pgsc_calc -r "$PIN" --help 2>&1 \
    | grep -E "(^Typical pipeline|^  --|^  -[a-z]|^pgs_id|^path_prefix|^sampleset)" || true
} > "$OUT"

echo "wrote $OUT"
```

The output structure: a few comment lines + the pgsc_calc `--help` invocation's argv-relevant sections. The test reads the file and asserts the conventions dataclass matches.

### golden-argv.txt shape

```text
# Captured 2026-05-19 from a successful Phase 5 smoke v6 run.
# pgsc_calc v2.2.0; -profile docker; --input <samplesheet.csv>.
nextflow run pgscatalog/pgsc_calc -r v2.2.0 -profile docker --input /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/<ts>/pgsc_calc_work/samplesheet.csv --target_build GRCh38 --pgs_id PGS000018 --run_ancestry /Volumes/Genome_Work/genomeclaw/reference/pgs_catalog_ancestry/v1 -work-dir /Volumes/Genome_Work/genomeclaw/_scratch/prs_phase5_smoke/<ts>/pgsc_calc_work
```

The test substitutes the timestamped `<ts>` placeholder and matches the wrapper-built argv against this golden modulo path differences.

### Edge cases to handle

- **Conventions parameter optional**. The wrapper defaults to `PgscCalcConventions()` when no override is passed. This keeps every existing call site at zero diff in the GREEN step.
- **`path_prefix_strips_extension=False` edge case**. If a future pgsc_calc release changes the rule, the dataclass field flips; the wrapper code reads it. No string manipulation in the wrapper outside the conditional.
- **CSV column escaping**. The samplesheet writer does NOT csv-escape the path (paths can't contain commas in our canonical layout). A comment in the writer notes this.
- **probe.sh requires docker + the toolkit image**. CI gates it behind `@pytest.mark.needs_prs_runtime`. Local runs auto-skip.

### Privacy / Egress Notes

- probe.sh runs the pgsc_calc image's `--help`. No genomic data. No new egress beyond what the pgsc_calc fetch already opens.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py` | CREATE | `PgscCalcConventions` frozen dataclass |
| `packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py` | MODIFY | Migrate `_build_pgsc_calc_argv` + `_write_pgsc_calc_samplesheet` to consume the dataclass |
| `packages/toolkit/tests/unit/test_pgsc_calc_conventions.py` | CREATE | Tests 1–10 |
| `packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py` | CREATE | Test 11 (discovery) |
| `packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py` | MODIFY | Update existing `--input` regression assertions to also check against the dataclass field (no behavior change; the assertion becomes more pinned) |
| `tools/pgsc_calc/probe.sh` | CREATE | Captures the empirical baseline |
| `tools/pgsc_calc/probe-output.txt` | CREATE | Recorded golden (committed) |
| `tools/pgsc_calc/golden-argv.txt` | CREATE | Recorded successful argv (committed) |

---

## Verification

```bash
cd packages/toolkit
uv run pytest tests/unit/test_pgsc_calc_conventions.py -v
uv run pytest tests/invariants/test_invT001_tool_conventions_exist.py -v
uv run pytest tests/integration/test_pgsc_calc_wrapper.py -v   # regression
uv run pytest                                                   # full suite

uv run ruff check src/ tests/
uv run mypy src/genomeclaw_toolkit/prep/_pgsc_calc_conventions.py \
            src/genomeclaw_toolkit/prep/pgs.py

# probe.sh (gated; requires the prs-phase5a toolkit image):
GENOMECLAW_TOOLKIT_PRS_IMAGE=genomeclaw/toolkit:prs-phase5a bash tools/pgsc_calc/probe.sh
diff tools/pgsc_calc/probe-output.txt /tmp/fresh-probe-output.txt   # should be empty
```

---

## Completion Criteria

- [ ] All 11 test cases pass (RED → GREEN → REFACTOR visible in commits)
- [ ] No regressions in existing tests
- [ ] ruff + mypy clean across the touched files
- [ ] `_pgsc_calc_conventions.py` carries per-field upstream citations (URL or `tools/pgsc_calc/probe-output.txt` reference)
- [ ] `tools/pgsc_calc/probe.sh` is committed + executable; `probe-output.txt` + `golden-argv.txt` are committed
- [ ] [development-plan.md](../development-plan.md) Progress Tracking table reflects Phase 2 completion
- [ ] [work-notes.md](../work-notes.md) gains a Phase 2 entry with RED output + decisions + final state
- [ ] `phases/phase-3.md` created from the template for the next phase

---

## Open Risks

- **R2.1**: probe.sh requires the toolkit image + Docker. If a contributor without docker tries to re-run the probe, the script exits cleanly with a hint. The recorded golden is the canonical source — the probe just keeps it honest.
- **R2.2**: pgsc_calc's `--help` output format may change between minor versions even if the argv contract doesn't. The probe-output.txt captures only the argv-relevant grep, which is robust against cosmetic changes. Field-value assertions go through the dataclass, not the raw help text.
- **R2.3**: The discovery test's strict-vs-warn split is a transitional accommodation. The backfill plan for plink2/bcftools/vcfanno/mosdepth/vep conventions is its own follow-up; this phase records the warn list explicitly so the backfill can iterate it.
