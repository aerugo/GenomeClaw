"""Phase 6 Slice D' — ``prep/pharmcat.py`` wrapper unit tests.

Wraps PharmCAT's two-subprocess pipeline:

1. ``pharmcat_vcf_preprocessor`` — VCF prep.
2. ``pharmcat`` (the bash wrapper around the JAR) — match + phenotype +
   reporter; ``-po`` threads in the outside-call TSV.

Tests mock both subprocess calls so they run on any host without
PharmCAT installed; the real-data smoke runs once after the Dockerfile
bakes PharmCAT v3.2.0.

Slice plan: [phases/phase-6-slice-d-prime.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d-prime.md)
"""

from __future__ import annotations

import dataclasses
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest


def _write_cyp2d6_diplotype_json(run_dir: Path, diplotype: str = "*1/*35") -> Path:
    """Write a minimal Slice-D-shaped ``cyp2d6_diplotype.json`` envelope."""
    path = run_dir / "cyp2d6_diplotype.json"
    path.write_text(
        json.dumps(
            {
                "sample_id": "TESTSAMPLE",
                "diplotype": diplotype,
                "filter_status": "PASS",
                "raw_cyrius_output": {},
                "provenance": {
                    "source_path": "/dummy/sample.cram",
                    "source_sha256": "f" * 64,
                    "tool": "cyrius",
                    "tool_version": "1.1.1",
                    "params_json": "{}",
                    "schema_version": "v0.2",
                    "created_at": "2026-05-22T00:00:00+00:00",
                },
            }
        )
    )
    return path


def _fake_pharmcat_report() -> dict:
    """PharmCAT v3.2.0 report.json shape, verified empirically 2026-05-22.

    The schema:
    - ``genes[<gene>].recommendationDiplotypes[0].phenotypes[0]`` carries
      the user's per-gene phenotype.
    - ``drugs["CPIC Guideline Annotation"][<drug>].guidelines[].annotations[]``
      enumerates per-phenotype recommendations; the user-applicable one
      matches the gene-phenotype map exactly.

    Fixture: a user with CYP2C19 Intermediate Metabolizer + CYP2D6
    Normal Metabolizer phenotypes. The fixture's only actionable
    annotation is clopidogrel for the IM phenotype.
    """
    return {
        "genes": {
            "CYP2C19": {
                "recommendationDiplotypes": [
                    {
                        "phenotypes": ["Intermediate Metabolizer"],
                        "allele1": {"gene": "CYP2C19", "name": "*1"},
                        "allele2": {"gene": "CYP2C19", "name": "*2"},
                    }
                ],
            },
            "CYP2D6": {
                "recommendationDiplotypes": [
                    {
                        "phenotypes": ["Normal Metabolizer"],
                        "allele1": {"gene": "CYP2D6", "name": "*1"},
                        "allele2": {"gene": "CYP2D6", "name": "*35"},
                    }
                ],
            },
        },
        "drugs": {
            "CPIC Guideline Annotation": {
                "clopidogrel": {
                    "id": "PA449053",
                    "guidelines": [
                        {
                            "annotations": [
                                {
                                    "drugRecommendation": (
                                        "Avoid standard dose clopidogrel (75 mg). "
                                        "Use prasugrel or ticagrelor."
                                    ),
                                    "classification": "Strong",
                                    "phenotypes": {"CYP2C19": "Intermediate Metabolizer"},
                                    "dosingInformation": False,
                                    "alternateDrugAvailable": True,
                                    "otherPrescribingGuidance": False,
                                    "genotypes": [
                                        {
                                            "diplotypes": [
                                                {
                                                    "gene": "CYP2C19",
                                                    "allele1": {"name": "*1"},
                                                    "allele2": {"name": "*2"},
                                                }
                                            ]
                                        }
                                    ],
                                },
                                # A non-matching annotation: Normal Metabolizer.
                                {
                                    "drugRecommendation": "Standard dose.",
                                    "classification": "Strong",
                                    "phenotypes": {"CYP2C19": "Normal Metabolizer"},
                                    "dosingInformation": False,
                                    "alternateDrugAvailable": False,
                                    "otherPrescribingGuidance": False,
                                    "genotypes": [
                                        {
                                            "diplotypes": [
                                                {
                                                    "gene": "CYP2C19",
                                                    "allele1": {"name": "*1"},
                                                    "allele2": {"name": "*1"},
                                                }
                                            ]
                                        }
                                    ],
                                },
                            ]
                        }
                    ],
                },
                # A drug whose user-applicable annotation is "no change" —
                # should NOT produce a finding (not actionable).
                "codeine": {
                    "id": "PA449088",
                    "guidelines": [
                        {
                            "annotations": [
                                {
                                    "drugRecommendation": "Use codeine label-recommended dosing.",
                                    "classification": "Strong",
                                    "phenotypes": {"CYP2D6": "Normal Metabolizer"},
                                    "dosingInformation": False,
                                    "alternateDrugAvailable": False,
                                    "otherPrescribingGuidance": False,
                                    "genotypes": [
                                        {
                                            "diplotypes": [
                                                {
                                                    "gene": "CYP2D6",
                                                    "allele1": {"name": "*1"},
                                                    "allele2": {"name": "*35"},
                                                }
                                            ]
                                        }
                                    ],
                                },
                            ]
                        }
                    ],
                },
            },
        },
    }


class _SubprocessStubs:
    """Records subprocess.run calls + writes the fixture outputs each stage expects.

    PharmCAT's pipeline is two subprocess calls (preprocessor + JAR).
    The stub recognises which stage is firing by inspecting argv and
    materialises the corresponding fixture file so the wrapper's
    glob/parse steps succeed.
    """

    def __init__(self, run_dir: Path, *, preprocessor_rc: int = 0, jar_rc: int = 0):
        self.run_dir = run_dir
        self.preprocessor_rc = preprocessor_rc
        self.jar_rc = jar_rc
        self.calls: list[list[str]] = []

    def __call__(self, argv, **kwargs):
        argv_list = list(argv)
        self.calls.append(argv_list)
        binary = argv_list[0]
        if binary.endswith("pharmcat_vcf_preprocessor"):
            preprocessed_dir = self.run_dir / "pharmcat_preprocessed"
            preprocessed_dir.mkdir(parents=True, exist_ok=True)
            if self.preprocessor_rc == 0:
                (preprocessed_dir / "sample.preprocessed.vcf.bgz").write_bytes(b"fake bgzf")
            stderr = b"" if self.preprocessor_rc == 0 else b"preprocessor failed: synthetic"
            return subprocess.CompletedProcess(
                args=argv_list, returncode=self.preprocessor_rc, stdout=b"", stderr=stderr
            )
        if binary.endswith("pharmcat") or "pharmcat.jar" in binary:
            output_dir = self.run_dir / "pharmcat"
            output_dir.mkdir(parents=True, exist_ok=True)
            if self.jar_rc == 0:
                (output_dir / "sample.report.json").write_text(
                    json.dumps(_fake_pharmcat_report())
                )
            stderr = b"" if self.jar_rc == 0 else b"pharmcat failed: synthetic"
            return subprocess.CompletedProcess(
                args=argv_list, returncode=self.jar_rc, stdout=b"", stderr=stderr
            )
        raise AssertionError(f"unexpected subprocess invocation: {argv_list!r}")


def test_run_pharmcat_argv_uses_conventions(tmp_path: Path) -> None:
    """Wrapper consumes ``PharmCATConventions`` fields rather than literals."""
    from genomeclaw_toolkit.prep._pharmcat_conventions import PharmCATConventions
    from genomeclaw_toolkit.prep.pharmcat import run_pharmcat

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vcf = tmp_path / "sample.vcf.gz"
    vcf.write_bytes(b"fake vcf")
    cyp2d6_json = _write_cyp2d6_diplotype_json(run_dir)

    custom_conv = dataclasses.replace(
        PharmCATConventions(),
        outside_call_flag="--alt-outside-call",
        output_dir_flag="--alt-output-dir",
        reporter_json_flag="--alt-reporter-json",
    )
    stubs = _SubprocessStubs(run_dir)

    with patch.object(subprocess, "run", side_effect=stubs):
        run_pharmcat(
            vcf=vcf,
            run_dir=run_dir,
            cyp2d6_diplotype_json=cyp2d6_json,
            conventions=custom_conv,
        )

    # The JAR call (second subprocess) uses the overridden flags.
    jar_argv = stubs.calls[1]
    assert "--alt-outside-call" in jar_argv
    assert "--alt-output-dir" in jar_argv
    assert "--alt-reporter-json" in jar_argv
    # Defense in depth: the default flags must not appear when conventions override them.
    assert "-po" not in jar_argv
    assert "-reporterJson" not in jar_argv


def test_run_pharmcat_emits_outside_call_tsv(tmp_path: Path) -> None:
    """Wrapper reads `cyp2d6_diplotype.json` + writes the TSV PharmCAT expects."""
    from genomeclaw_toolkit.prep.pharmcat import run_pharmcat

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vcf = tmp_path / "sample.vcf.gz"
    vcf.write_bytes(b"fake vcf")
    _write_cyp2d6_diplotype_json(run_dir, diplotype="*1/*4")
    stubs = _SubprocessStubs(run_dir)

    with patch.object(subprocess, "run", side_effect=stubs):
        run_pharmcat(
            vcf=vcf,
            run_dir=run_dir,
            cyp2d6_diplotype_json=run_dir / "cyp2d6_diplotype.json",
        )

    tsv_path = run_dir / "pharmcat_outside_calls.tsv"
    assert tsv_path.exists(), "outside-call TSV must be written before PharmCAT runs"
    content = tsv_path.read_text()
    assert "CYP2D6" in content
    assert "*1/*4" in content
    # Per docs/using/Outside-Call-Format.md: tab-separated, no header.
    first_line = content.splitlines()[0]
    assert "\t" in first_line
    assert first_line.split("\t")[0] == "CYP2D6"


def test_run_pharmcat_threads_cyp2d6_diplotype_through_outside_call(tmp_path: Path) -> None:
    """The diplotype from ``cyp2d6_diplotype.json`` lands in the JAR's argv."""
    from genomeclaw_toolkit.prep.pharmcat import run_pharmcat

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vcf = tmp_path / "sample.vcf.gz"
    vcf.write_bytes(b"fake vcf")
    _write_cyp2d6_diplotype_json(run_dir, diplotype="*4/*5")
    stubs = _SubprocessStubs(run_dir)

    with patch.object(subprocess, "run", side_effect=stubs):
        run_pharmcat(
            vcf=vcf,
            run_dir=run_dir,
            cyp2d6_diplotype_json=run_dir / "cyp2d6_diplotype.json",
        )

    # The exact diplotype string must land in the TSV.
    tsv_content = (run_dir / "pharmcat_outside_calls.tsv").read_text()
    assert "*4/*5" in tsv_content
    # And the JAR call must thread the TSV via -po.
    jar_argv = stubs.calls[1]
    assert "-po" in jar_argv
    po_idx = jar_argv.index("-po")
    assert jar_argv[po_idx + 1].endswith("pharmcat_outside_calls.tsv")


def test_run_pharmcat_parses_findings_from_report(tmp_path: Path) -> None:
    """The wrapper parses PharmCAT's report into a list of `PharmCATFinding`."""
    from genomeclaw_toolkit.prep.pharmcat import PharmCATFinding, run_pharmcat

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vcf = tmp_path / "sample.vcf.gz"
    vcf.write_bytes(b"fake vcf")
    _write_cyp2d6_diplotype_json(run_dir)
    stubs = _SubprocessStubs(run_dir)

    with patch.object(subprocess, "run", side_effect=stubs):
        findings = run_pharmcat(
            vcf=vcf,
            run_dir=run_dir,
            cyp2d6_diplotype_json=run_dir / "cyp2d6_diplotype.json",
        )

    assert isinstance(findings, list)
    assert all(isinstance(f, PharmCATFinding) for f in findings)
    # Fixture: user is CYP2C19 IM + CYP2D6 NM. Clopidogrel-for-IM is
    # actionable (alternateDrugAvailable=True); codeine-for-NM is not.
    # Expect exactly the clopidogrel finding.
    assert len(findings) == 1
    clopidogrel = findings[0]
    assert clopidogrel.gene == "CYP2C19"
    assert clopidogrel.diplotype == "*1/*2"
    assert clopidogrel.pharmgkb_id == "PA449053"
    assert "clopidogrel" in clopidogrel.drugs
    assert "prasugrel" in clopidogrel.recommendation_summary.lower() or "avoid" in clopidogrel.recommendation_summary.lower()


def test_run_pharmcat_raises_on_preprocessor_failure(tmp_path: Path) -> None:
    """Non-zero rc from the preprocessor surfaces RuntimeError."""
    from genomeclaw_toolkit.prep.pharmcat import run_pharmcat

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vcf = tmp_path / "sample.vcf.gz"
    vcf.write_bytes(b"fake vcf")
    _write_cyp2d6_diplotype_json(run_dir)
    stubs = _SubprocessStubs(run_dir, preprocessor_rc=2)

    with patch.object(subprocess, "run", side_effect=stubs):
        with pytest.raises(RuntimeError) as excinfo:
            run_pharmcat(
                vcf=vcf,
                run_dir=run_dir,
                cyp2d6_diplotype_json=run_dir / "cyp2d6_diplotype.json",
            )

    assert "preprocessor" in str(excinfo.value).lower()
    assert "rc=2" in str(excinfo.value)


def test_run_pharmcat_raises_on_jar_failure(tmp_path: Path) -> None:
    """Non-zero rc from the JAR surfaces RuntimeError."""
    from genomeclaw_toolkit.prep.pharmcat import run_pharmcat

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vcf = tmp_path / "sample.vcf.gz"
    vcf.write_bytes(b"fake vcf")
    _write_cyp2d6_diplotype_json(run_dir)
    stubs = _SubprocessStubs(run_dir, jar_rc=1)

    with patch.object(subprocess, "run", side_effect=stubs):
        with pytest.raises(RuntimeError) as excinfo:
            run_pharmcat(
                vcf=vcf,
                run_dir=run_dir,
                cyp2d6_diplotype_json=run_dir / "cyp2d6_diplotype.json",
            )

    assert "jar" in str(excinfo.value).lower()
    assert "rc=1" in str(excinfo.value)


def test_run_pharmcat_accepts_no_outside_call(tmp_path: Path) -> None:
    """``cyp2d6_diplotype_json=None`` is valid — JAR runs without outside-call."""
    from genomeclaw_toolkit.prep.pharmcat import run_pharmcat

    run_dir = tmp_path / "run"
    run_dir.mkdir()
    vcf = tmp_path / "sample.vcf.gz"
    vcf.write_bytes(b"fake vcf")
    stubs = _SubprocessStubs(run_dir)

    with patch.object(subprocess, "run", side_effect=stubs):
        findings = run_pharmcat(vcf=vcf, run_dir=run_dir, cyp2d6_diplotype_json=None)

    # Without outside-call, the TSV must NOT be created.
    assert not (run_dir / "pharmcat_outside_calls.tsv").exists()
    # And the JAR call must NOT carry `-po`.
    jar_argv = stubs.calls[1]
    assert "-po" not in jar_argv
    assert isinstance(findings, list)
