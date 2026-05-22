"""Phase 2 — ``PgscCalcConventions`` frozen dataclass + ``pgs.py`` migration.

Captures pgsc_calc v2.2.0's argv + samplesheet + filename conventions in a
typed dataclass. Each field's value either matches the upstream README OR
a recorded empirical probe at ``tools/pgsc_calc/probe-output.txt``. Wrapper
tests assert against the dataclass, not against hardcoded strings — so a
future pin bump that changes a flag name produces a clear typed-test
failure rather than a silent rc=1 in a real-tool smoke.

Promotes ``INV-T001`` (External-Tool Conventions Captured as Typed Wrappers).

Phase plan: [phases/phase-2.md](../../../../docs/plans/active/path-crossing-discipline/phases/phase-2.md)
Source report: [docs/reports/path-crossing-discipline.md](../../../../docs/reports/path-crossing-discipline.md)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError, is_dataclass
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Test 1 — dataclass shape: exists, is_dataclass, frozen
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_dataclass_exists_and_is_frozen() -> None:
    """The dataclass imports, is recognised as a dataclass, and is frozen."""
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    assert is_dataclass(PgscCalcConventions)
    conv = PgscCalcConventions()
    with pytest.raises(FrozenInstanceError):
        conv.input_flag = "--something-else"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Test 2 — verified_against_version matches the pinned version in _versions.py
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_verified_against_version_matches_pin() -> None:
    """If a future pin bump moves ``PRS_RUNTIME_VERSIONS["pgsc_calc"]`` without
    updating the conventions, this test fails loudly — the contract belongs
    to the version it was verified against."""
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    from genomeclaw_toolkit.prep._versions import PRS_RUNTIME_VERSIONS

    assert PgscCalcConventions().verified_against_version == PRS_RUNTIME_VERSIONS["pgsc_calc"]


# ---------------------------------------------------------------------------
# Test 3 — input_flag is --input, NOT --target
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_input_flag_is_dash_dash_input() -> None:
    """Smoke v2 regression guard: pgsc_calc v2.2.0 retired ``--target`` in favour
    of ``--input <samplesheet.csv>``. The conventions dataclass MUST pin --input."""
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    assert PgscCalcConventions().input_flag == "--input"
    # Defense in depth — the wrapper code paths NEVER reference --target.
    assert "target" not in PgscCalcConventions().input_flag


# ---------------------------------------------------------------------------
# Test 4 — samplesheet_columns match pgsc_calc v2.2.0 schema
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_samplesheet_columns_match_v2_schema() -> None:
    """The samplesheet header columns per pgsc_calc v2.2.0 README."""
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    assert PgscCalcConventions().samplesheet_columns == (
        "sampleset",
        "path_prefix",
        "chrom",
        "format",
        "vcf_genotype_field",
    )


# ---------------------------------------------------------------------------
# Test 5 — path_prefix_strips_extension is True (smoke v6 regression)
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_path_prefix_strips_extension() -> None:
    """Smoke v6 regression guard: pgsc_calc auto-appends ``.vcf`` to the
    ``path_prefix`` column; the prefix MUST NOT carry the ``.vcf.gz`` suffix.
    The conventions field encodes this rule."""
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    assert PgscCalcConventions().path_prefix_strips_extension is True


# ---------------------------------------------------------------------------
# Test 6 — accession_format produces the canonical hmPOS_GRCh38 string
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_accession_format_template() -> None:
    """The PGS Catalog harmonised-scoring accession is ``<PGS_ID>_hmPOS_GRCh38``.

    Phase 3b3a of ``prs-input-coverage-fill`` (the match-rate parser) depends
    on this format to look up rows in pgsc_calc's per-variant log CSV.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    formatted = PgscCalcConventions().accession_format.format(pgs_id="PGS000018")
    assert formatted == "PGS000018_hmPOS_GRCh38"


# ---------------------------------------------------------------------------
# Test 7 — _build_pgsc_calc_argv reads the conventions field
# ---------------------------------------------------------------------------


def test_build_pgsc_calc_argv_consumes_conventions(tmp_path: Path) -> None:
    """The argv wrapper reads ``conv.input_flag``, not a hardcoded literal.

    Pass a stubbed conventions with ``input_flag="--TARGET-FAKE"`` and assert
    the emitted argv carries that fake flag. Proves the wrapper is field-
    driven, not literal-driven — a future pin bump that flips the flag in
    the dataclass produces the right argv WITHOUT modifying the wrapper.
    """
    from dataclasses import replace

    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    from genomeclaw_toolkit.prep.pgs import _build_pgsc_calc_argv

    samplesheet = tmp_path / "samplesheet.csv"
    samplesheet.write_text("")
    reference_root = tmp_path / "reference"
    (reference_root / "pgs_catalog_ancestry" / "v1").mkdir(parents=True)
    work_dir = tmp_path / "work"

    fake_conventions = replace(PgscCalcConventions(), input_flag="--TARGET-FAKE")
    argv = _build_pgsc_calc_argv(
        samplesheet=samplesheet,
        pgs_id="PGS000018",
        work_dir=work_dir,
        reference_root=reference_root,
        conventions=fake_conventions,
    )
    assert "--TARGET-FAKE" in argv, (
        f"wrapper must consume conv.input_flag, not a hardcoded literal; argv={argv}"
    )
    assert "--input" not in argv, (
        "wrapper should not emit hardcoded --input when conventions override the field"
    )


# ---------------------------------------------------------------------------
# Test 8 — samplesheet writer reads samplesheet_columns
# ---------------------------------------------------------------------------


def test_write_pgsc_calc_samplesheet_consumes_conventions(tmp_path: Path) -> None:
    """The samplesheet writer reads ``conv.samplesheet_columns``, not a hardcoded list."""
    from dataclasses import replace

    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    from genomeclaw_toolkit.prep.pgs import _write_pgsc_calc_samplesheet

    vcf = tmp_path / "merged.vcf.gz"
    vcf.write_bytes(b"")
    work_dir = tmp_path / "work"

    # Stub the conventions with reordered columns to confirm the writer reads the field.
    fake_conventions = replace(
        PgscCalcConventions(),
        samplesheet_columns=("vcf_genotype_field", "format", "chrom", "path_prefix", "sampleset"),
    )
    samplesheet = _write_pgsc_calc_samplesheet(
        vcf=vcf, sample_id="MPNRGLQ2K", work_dir=work_dir, conventions=fake_conventions
    )
    first_line = samplesheet.read_text().splitlines()[0]
    assert first_line == "vcf_genotype_field,format,chrom,path_prefix,sampleset", (
        f"header must follow conv.samplesheet_columns order; got: {first_line!r}"
    )


# ---------------------------------------------------------------------------
# Test 9 — path_prefix_strips_extension flag controls suffix handling
# ---------------------------------------------------------------------------


def test_write_pgsc_calc_samplesheet_path_prefix_rule_honors_conventions(
    tmp_path: Path,
) -> None:
    """``path_prefix_strips_extension=False`` keeps the full path; True strips ``.vcf.gz``.

    Both directions covered to prove the writer reads the field rather than
    always stripping (or never stripping).
    """
    from dataclasses import replace

    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    from genomeclaw_toolkit.prep.pgs import _write_pgsc_calc_samplesheet

    vcf = tmp_path / "merged.vcf.gz"
    vcf.write_bytes(b"")
    work_dir_strip = tmp_path / "work_strip"
    work_dir_keep = tmp_path / "work_keep"

    # Default conventions strip → path_prefix has no .vcf.gz suffix.
    samplesheet_strip = _write_pgsc_calc_samplesheet(
        vcf=vcf, sample_id="MPNRGLQ2K", work_dir=work_dir_strip
    )
    row_strip = samplesheet_strip.read_text().splitlines()[1]
    path_prefix_strip = row_strip.split(",")[1]
    assert not path_prefix_strip.endswith(".vcf.gz"), (
        f"default conventions must strip; got: {path_prefix_strip!r}"
    )
    assert not path_prefix_strip.endswith(".vcf")

    # Override to NOT strip → path_prefix carries the full .vcf.gz.
    keep_conventions = replace(PgscCalcConventions(), path_prefix_strips_extension=False)
    samplesheet_keep = _write_pgsc_calc_samplesheet(
        vcf=vcf, sample_id="MPNRGLQ2K", work_dir=work_dir_keep, conventions=keep_conventions
    )
    row_keep = samplesheet_keep.read_text().splitlines()[1]
    path_prefix_keep = row_keep.split(",")[1]
    assert path_prefix_keep.endswith(".vcf.gz"), (
        f"override conventions must keep the suffix; got: {path_prefix_keep!r}"
    )


# ---------------------------------------------------------------------------
# Test 10 — dataclass field values match the recorded probe-output baseline
# ---------------------------------------------------------------------------


def test_invT001_pgsc_calc_conventions_field_values_match_probe_output() -> None:
    """The conventions dataclass tracks an empirical baseline.

    Reads ``tools/pgsc_calc/probe-output.txt``; for each ``KEY=VALUE`` line,
    asserts the corresponding ``PgscCalcConventions`` field equals the value.
    If a future pgsc_calc bump changes a convention, the probe is re-run
    and BOTH the probe-output AND the dataclass field are updated together.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    repo_root = Path(__file__).resolve().parents[4]
    probe_output = repo_root / "tools" / "pgsc_calc" / "probe-output.txt"
    assert probe_output.exists(), f"missing baseline: {probe_output}"

    conv = PgscCalcConventions()
    pairs: dict[str, str] = {}
    for raw_line in probe_output.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        pairs[key.strip()] = value.strip()

    assert pairs, "probe-output.txt has no KEY=VALUE lines"
    for key, expected in pairs.items():
        actual = getattr(conv, key, None)
        # Tuple fields are written as comma-separated values in the probe.
        if isinstance(actual, tuple):
            actual_str = ",".join(actual)
            assert actual_str == expected, (
                f"PgscCalcConventions.{key} = {actual_str!r}, probe-output baseline = {expected!r}"
            )
        elif isinstance(actual, bool):
            assert str(actual).lower() == expected.lower(), (
                f"PgscCalcConventions.{key} = {actual}, baseline = {expected}"
            )
        else:
            assert str(actual) == expected, (
                f"PgscCalcConventions.{key} = {actual!r}, baseline = {expected!r}"
            )


# ---------------------------------------------------------------------------
# Tests 11–13 — value-type descriptors (prs-runtime-hardening Slice 1.C)
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_run_ancestry_value_pattern_matches_tarball() -> None:
    """``run_ancestry_value_pattern`` matches a tarball path (``.tar.zst``)
    and DOES NOT match a directory.

    Phase 7 smoke v10 surfaced the bug — the wrapper pointed
    ``--run_ancestry`` at the extracted directory; pgsc_calc's
    ``EXTRACT_DATABASE`` does ``tar -xf <value>`` and crashed. The pattern
    pins the value-type semantic so a future regression to "pass the dir"
    surfaces at unit-test time, not at smoke-time."""
    import re as _re

    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    pat = PgscCalcConventions().run_ancestry_value_pattern
    # Tarball-shaped paths match.
    assert _re.match(pat, "/Volumes/x/y/pgs_catalog_ancestry.tar.zst"), pat
    assert _re.match(pat, "pgs_catalog_ancestry.tar.zst"), pat
    # Directory paths do NOT match.
    assert not _re.match(pat, "/Volumes/x/y/pgs_catalog_ancestry/v1"), pat
    assert not _re.match(pat, "/Volumes/x/y/pgs_catalog_ancestry/v1/"), pat
    # Plain ``.tar`` (no zstd) does NOT match — the bundle is .tar.zst.
    assert not _re.match(pat, "/Volumes/x/y/pgs_catalog_ancestry.tar"), pat


def test_pgsc_calc_conventions_input_value_pattern_matches_csv() -> None:
    """``input_value_pattern`` matches ``samplesheet.csv`` and rejects
    non-CSV inputs (e.g., raw VCF passed directly — a regression to the
    pre-v2.2 ``--target <vcf>`` shorthand)."""
    import re as _re

    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    pat = PgscCalcConventions().input_value_pattern
    assert _re.match(pat, "samplesheet.csv"), pat
    assert _re.match(pat, "/Volumes/x/work/samplesheet.csv"), pat
    # VCF as input value is the v2-regression mistake — must be rejected.
    assert not _re.match(pat, "/Volumes/x/raw/sample.vcf.gz"), pat
    assert not _re.match(pat, "sample.vcf"), pat


def test_build_pgsc_calc_argv_run_ancestry_value_matches_pattern(
    tmp_path: Path,
) -> None:
    """Closes the loop: ``_build_pgsc_calc_argv`` emits a ``--run_ancestry``
    value that matches the conventions' pattern.

    Catches the v10-class regression at unit-test time. The wrapper code
    derives the value via ``_ancestry_reference_bundle()``; if a future
    refactor reverts that to ``_ancestry_reference_dir``, this test fails
    with a clear "pattern mismatch" message, not a 5-hour smoke iteration."""
    import re as _re

    from genomeclaw_toolkit.prep._paths import as_sibling_mountable
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions
    from genomeclaw_toolkit.prep.pgs import _build_pgsc_calc_argv

    samplesheet = as_sibling_mountable(tmp_path / "samplesheet.csv")
    samplesheet.write_text("sampleset,path_prefix,chrom,format,vcf_genotype_field\n")
    work_dir = as_sibling_mountable(tmp_path / "work")
    work_dir.mkdir(exist_ok=True)
    reference_root = as_sibling_mountable(tmp_path / "ref")
    (reference_root / "pgs_catalog_ancestry" / "v1").mkdir(parents=True)

    argv = _build_pgsc_calc_argv(
        samplesheet=samplesheet,
        pgs_id="PGS000018",
        work_dir=work_dir,
        reference_root=reference_root,
    )

    # Find the --run_ancestry value + assert it matches the pattern.
    flag_idx = argv.index("--run_ancestry")
    value = argv[flag_idx + 1]
    pat = PgscCalcConventions().run_ancestry_value_pattern
    assert _re.match(pat, value), (
        f"--run_ancestry value {value!r} does not match the conventions' "
        f"value-type pattern {pat!r}. A regression here means the wrapper "
        f"is pointing pgsc_calc at the wrong kind of artifact (likely "
        f"the extracted directory instead of the .tar.zst tarball)."
    )

    # Same loop for --input value.
    flag_idx = argv.index("--input")
    value = argv[flag_idx + 1]
    pat = PgscCalcConventions().input_value_pattern
    assert _re.match(pat, value), (
        f"--input value {value!r} does not match {pat!r}. Should be a CSV."
    )


# ---------------------------------------------------------------------------
# prs-non-imputed-wgs Phase 1 — min_overlap_default_for_non_imputed_wgs field
# ---------------------------------------------------------------------------


def test_pgsc_calc_conventions_min_overlap_default_for_non_imputed_wgs() -> None:
    """The conventions dataclass pins ``--min_overlap`` to 0.5 for the
    non-imputed single-sample WGS input class (GenomeClaw's default).

    pgsc_calc's published default is 0.75 — calibrated by Lambert et al. 2024
    *Nature Genetics* on cohort-imputed data. The 45-65% empirical match-rate
    ceiling for non-imputed single-sample WGS against dense imputed scoring
    files (per docs/reports/prs-real-data-smoke-research-findings.md) makes
    0.75 a structural rejection of healthy artifacts. 0.5 is the input-class-
    appropriate default; the field's docstring MUST cite the research-
    findings report so a future reader who sees the value diverge from
    pgsc_calc's upstream default knows why.
    """
    from genomeclaw_toolkit.prep._pgsc_calc_conventions import PgscCalcConventions

    conv = PgscCalcConventions()
    assert conv.min_overlap_default_for_non_imputed_wgs == 0.45, (
        "Phase 1 of prs-non-imputed-wgs: the conventions dataclass MUST pin "
        "min_overlap_default_for_non_imputed_wgs to 0.45 (per the research "
        "findings doc's documented 45-65% range + smoke v22e's empirical "
        "49.51% measurement for PGS000018). Changing this default in "
        "isolation breaks the smoke v22 gate."
    )
    # The field type is float, not str — pgsc_calc parses it as a float
    # downstream, and the env-var override path must produce a float too.
    assert isinstance(conv.min_overlap_default_for_non_imputed_wgs, float)

    # Citation gate: the field's docstring (sourced via the dataclass's
    # __dataclass_fields__) must reference the research-findings report so
    # the rationale is co-located with the value.
    import dataclasses as _dc

    field = _dc.fields(PgscCalcConventions)
    field_map = {f.name: f for f in field}
    assert "min_overlap_default_for_non_imputed_wgs" in field_map, (
        f"field not declared; got fields={sorted(field_map)}"
    )
    # docstring lives on the class attribute, not on dataclasses.Field.metadata.
    # Read via __annotations__ + the class source via inspect.
    import inspect as _inspect

    source = _inspect.getsource(PgscCalcConventions)
    assert "prs-real-data-smoke-research-findings" in source, (
        "Phase 1 contract: the field's docstring MUST cite "
        "docs/reports/prs-real-data-smoke-research-findings.md so the rationale "
        "for diverging from pgsc_calc's 0.75 default is co-located with the "
        "value. Without this citation a future contributor seeing 0.5 has no "
        "audit trail to the literature validation that justified it."
    )
