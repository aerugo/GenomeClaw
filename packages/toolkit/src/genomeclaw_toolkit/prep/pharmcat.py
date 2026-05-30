"""PharmCAT v3.2.0 pipeline wrapper (Phase 6 Slice D').

Wraps PharmGKB's PharmCAT — the Java-based pharmacogenomics
recommendation engine. Consumes the user's VCF + an optional outside-
call TSV (carrying Slice D's Cyrius CYP2D6 diplotype) and emits typed
:class:`PharmCATFinding` rows ready for INSERT into the ``findings``
table by the CLI subcommand.

**Two-subprocess architecture** (empirically verified 2026-05-22 against
genomeclaw/toolkit:slice-d-prime):

1. ``pharmcat_vcf_preprocessor -vcf <input> -o <preprocessed_dir>``
   → produces ``<base>.preprocessed.vcf.bgz``.
2. ``pharmcat -vcf <preprocessed.vcf.bgz> -po <outside_calls.tsv>
    -o <reports_dir> -reporterJson`` → produces ``<base>.report.json``.

The upstream ``pharmcat_pipeline`` Python wrapper does NOT expose the
``-po`` flag — for outside-call workflows the documented pattern is
preprocessor + JAR explicitly. Verified by reading
github.com/PharmGKB/PharmCAT/blob/v3.2.0/docs/using/Outside-Call-Format.md.

The wrapper does NOT INSERT into the ``findings`` table directly — the
CLI subcommand owns the DB write so the seven canonical INV-R001
provenance columns are stamped consistently at the orchestrator
boundary (mirrors ``pgs-compute``'s pattern).

Slice plan: [phases/phase-6-slice-d-prime.md](../../../../docs/plans/active/mvp/phases/phase-6-slice-d-prime.md)
"""

from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from genomeclaw_toolkit.prep._pharmcat_conventions import PharmCATConventions


@dataclass(frozen=True)
class PharmCATFinding:
    """One PharmCAT recommendation, ready for INSERT by the CLI subcommand.

    Carries the per-(gene × drug) fields PharmCAT v3 emits in its
    report.json. The seven canonical INV-R001 provenance columns are
    stamped at INSERT time by the CLI, not by the wrapper.
    """

    gene: str
    diplotype: str
    phenotype: str
    pharmgkb_id: str
    recommendation_summary: str
    drugs: tuple[str, ...] = field(default_factory=tuple)


def _write_outside_call_tsv(
    cyp2d6_diplotype_json: Path,
    *,
    output_path: Path,
    conventions: PharmCATConventions,
) -> Path:
    """Read Slice-D's `cyp2d6_diplotype.json` and emit the PharmCAT outside-call TSV.

    Per docs/using/Outside-Call-Format.md (v3.2.0): tab-separated, no
    header line; columns are ``gene\\tdiplotype\\tphenotype\\tactivity_score``
    with the last two optional. The wrapper emits the minimal
    ``gene\\tdiplotype`` form for CYP2D6 — PharmCAT looks up the
    phenotype + activity score itself.
    """
    envelope = json.loads(cyp2d6_diplotype_json.read_text())
    diplotype = envelope.get("diplotype")
    if not diplotype:
        raise ValueError(
            f"cyp2d6_diplotype_json={cyp2d6_diplotype_json!s} carries no 'diplotype' field; "
            "Slice D's wrapper should always populate it on a PASS run."
        )
    row_values = {"gene": "CYP2D6", "diplotype": diplotype}
    row = "\t".join(row_values.get(col, "") for col in conventions.outside_call_tsv_columns)
    # Explicit UTF-8 encoding (bioreview-small-fixes Fix 3): PharmCAT
    # activity scores include `≥` (U+2265); without an explicit encoding
    # Path.write_text falls back to the system locale, which silently
    # corrupts on cp1252/Latin-1 hosts.
    output_path.write_text(f"{row}\n", encoding="utf-8")
    return output_path


def _build_preprocessor_argv(
    *,
    vcf: Path,
    output_dir: Path,
    conventions: PharmCATConventions,
    reference_fasta: Path | None = None,
) -> list[str]:
    """Build the ``pharmcat_vcf_preprocessor`` invocation argv from conventions.

    ``reference_fasta`` is essentially required at runtime — without it
    the preprocessor tries to fetch the GRCh38 reference from Zenodo
    into ``/opt/pharmcat/`` (read-only inside the toolkit image).
    The wrapper threads our existing reference via ``-refFna``.
    """
    argv = [
        conventions.preprocessor_entrypoint,
        conventions.preprocessor_vcf_flag,
        str(vcf),
        conventions.preprocessor_output_dir_flag,
        str(output_dir),
    ]
    if reference_fasta is not None:
        argv += [
            conventions.preprocessor_reference_fasta_flag,
            str(reference_fasta),
        ]
    return argv


def _build_pharmcat_argv(
    *,
    preprocessed_vcf: Path,
    output_dir: Path,
    outside_call_tsv: Path | None,
    conventions: PharmCATConventions,
) -> list[str]:
    """Build the PharmCAT JAR invocation argv from conventions.

    Every flag string comes from :class:`PharmCATConventions` — a
    future pin bump that flips a flag produces a typed-test failure
    rather than a silent rc=1.
    """
    argv = [
        conventions.entrypoint,
        conventions.vcf_flag,
        str(preprocessed_vcf),
        conventions.output_dir_flag,
        str(output_dir),
        conventions.reporter_json_flag,
    ]
    if outside_call_tsv is not None:
        argv += [conventions.outside_call_flag, str(outside_call_tsv)]
    return argv


def _extract_user_phenotypes(genes_block: dict) -> dict[str, str]:
    """Map gene → user's primary phenotype, derived from ``recommendationDiplotypes``.

    PharmCAT v3 reports the user's per-gene phenotype inside each gene's
    ``recommendationDiplotypes[0].phenotypes[0]``. The "recommendation"
    diplotype is what PharmCAT uses to match against drug annotations
    (it differs from the raw source diplotype when activity scores or
    phasing collapse the call).
    """
    phenotypes: dict[str, str] = {}
    for gene_name, gene_data in genes_block.items():
        if not isinstance(gene_data, dict):
            continue
        rec_diplos = gene_data.get("recommendationDiplotypes") or []
        if not rec_diplos or not isinstance(rec_diplos[0], dict):
            continue
        pheno_list = rec_diplos[0].get("phenotypes") or []
        if pheno_list:
            phenotypes[gene_name] = pheno_list[0]
    return phenotypes


def _annotation_matches_user(annotation: dict, user_phenotypes: dict[str, str]) -> bool:
    """Return True iff every gene in ``annotation.phenotypes`` matches the user's.

    PharmCAT v3 enumerates ALL possible recommendations for ALL possible
    phenotype combinations per drug; the user-applicable annotation is
    the one whose ``phenotypes`` dict matches the user's per-gene
    phenotype exactly.
    """
    ann_phenos = annotation.get("phenotypes") or {}
    if not isinstance(ann_phenos, dict) or not ann_phenos:
        return False
    return all(
        user_phenotypes.get(gene) == expected_pheno
        for gene, expected_pheno in ann_phenos.items()
    )


def _annotation_is_actionable(annotation: dict) -> bool:
    """Return True iff the annotation carries an actionable recommendation.

    PharmCAT v3 flags actionable annotations with boolean fields:
    ``dosingInformation``, ``alternateDrugAvailable``, or
    ``otherPrescribingGuidance``. v0 skips "no change needed"
    annotations to keep the findings table focused on actionable PGx.
    """
    return bool(
        annotation.get("dosingInformation")
        or annotation.get("alternateDrugAvailable")
        or annotation.get("otherPrescribingGuidance")
    )


def _extract_diplotype_for_gene(annotation: dict, gene: str) -> str:
    """Extract the ``<allele1>/<allele2>`` diplotype string for ``gene``.

    Walks ``annotation.genotypes[].diplotypes[]`` for the entry matching
    ``gene``. Returns an empty string if no match (rare — PharmCAT's
    annotation structure typically carries the genotype that matches
    its phenotype).
    """
    for genotype_block in annotation.get("genotypes") or []:
        if not isinstance(genotype_block, dict):
            continue
        for diplo in genotype_block.get("diplotypes") or []:
            if not isinstance(diplo, dict):
                continue
            if diplo.get("gene") == gene:
                allele1 = (diplo.get("allele1") or {}).get("name") or "?"
                allele2 = (diplo.get("allele2") or {}).get("name") or "?"
                return f"{allele1}/{allele2}"
    return ""


def _parse_pharmcat_report(report_path: Path) -> list[PharmCATFinding]:
    """Parse PharmCAT v3.2.0's report.json into a list of :class:`PharmCATFinding`.

    Algorithm (verified empirically 2026-05-22 against the project owner's
    MPNRGLQ2K VCF + Slice D's CYP2D6 *1/*35 outside-call):

    1. Build a ``gene → user_phenotype`` map from each gene's
       ``recommendationDiplotypes[0].phenotypes[0]``.
    2. For each drug × guideline × annotation under
       ``drugs["CPIC Guideline Annotation"]``:
       a. Check if the annotation's ``phenotypes`` dict matches the
          user's phenotypes for those genes (all-or-nothing).
       b. Check if the annotation is actionable
          (``dosingInformation || alternateDrugAvailable ||
          otherPrescribingGuidance``).
       c. If both: emit a :class:`PharmCATFinding` with the drug's
          PharmGKB ID as ``pharmgkb_id``, the matched gene's diplotype,
          and the annotation's ``drugRecommendation``.

    Each drug contributes at most one finding (the first user-applicable
    actionable annotation per guideline).

    DPWG / FDA guideline branches are skipped in v0 — adding them is
    follow-on work once the CPIC path is proven in production.
    """
    raw = json.loads(report_path.read_text())
    user_phenotypes = _extract_user_phenotypes(raw.get("genes") or {})

    findings: list[PharmCATFinding] = []
    cpic_drugs = (raw.get("drugs") or {}).get("CPIC Guideline Annotation") or {}
    if not isinstance(cpic_drugs, dict):
        return findings

    for drug_name, drug in cpic_drugs.items():
        if not isinstance(drug, dict):
            continue
        drug_id = drug.get("id")
        if not drug_id:
            continue
        emitted_for_drug = False
        for guideline in drug.get("guidelines") or []:
            if emitted_for_drug or not isinstance(guideline, dict):
                continue
            for annotation in guideline.get("annotations") or []:
                if not isinstance(annotation, dict):
                    continue
                if not _annotation_matches_user(annotation, user_phenotypes):
                    continue
                if not _annotation_is_actionable(annotation):
                    continue
                ann_phenos = annotation.get("phenotypes") or {}
                primary_gene = next(iter(ann_phenos), "")
                if not primary_gene:
                    continue
                findings.append(
                    PharmCATFinding(
                        gene=primary_gene,
                        diplotype=_extract_diplotype_for_gene(annotation, primary_gene),
                        phenotype=ann_phenos.get(primary_gene) or "",
                        pharmgkb_id=drug_id,
                        recommendation_summary=annotation.get("drugRecommendation") or "",
                        drugs=(drug_name,),
                    )
                )
                emitted_for_drug = True
                break
    return findings


def _find_preprocessed_vcf(preprocessed_dir: Path) -> Path:
    """Locate the preprocessor's output VCF under ``preprocessed_dir``.

    PharmCAT v3 names it ``<base>.preprocessed.vcf.bgz`` where ``<base>``
    is the input VCF's basename stem. The wrapper globs rather than
    recompute the prefix.
    """
    matches = sorted(preprocessed_dir.glob("*.preprocessed.vcf.bgz"))
    if not matches:
        raise RuntimeError(
            f"pharmcat_vcf_preprocessor produced no *.preprocessed.vcf.bgz under "
            f"{preprocessed_dir!s}; preprocessor returned 0 but the expected "
            "output is missing."
        )
    return matches[0]


def _find_pharmcat_report(output_dir: Path) -> Path:
    """Locate PharmCAT's report.json under ``output_dir``.

    Glob ``*.report.json`` to tolerate prefix differences between
    preprocessor versions.
    """
    matches = sorted(output_dir.glob("*.report.json"))
    if not matches:
        raise RuntimeError(
            f"PharmCAT produced no *.report.json under {output_dir!s}; "
            "subprocess returned 0 but the expected output is missing."
        )
    return matches[0]


def _run_or_raise(argv: list[str], *, stage_name: str) -> None:
    """Run ``argv`` via subprocess.run; raise RuntimeError on non-zero rc."""
    proc = subprocess.run(argv, capture_output=True, check=False)
    if proc.returncode != 0:
        stderr_text = proc.stderr.decode("utf-8", errors="replace").strip()
        stdout_tail = "\n".join(
            proc.stdout.decode("utf-8", errors="replace").splitlines()[-20:]
        )
        raise RuntimeError(
            f"pharmcat {stage_name} failed (rc={proc.returncode}):\n"
            f"--- stderr ---\n{stderr_text}\n"
            f"--- stdout (last 20 lines) ---\n{stdout_tail}"
        )


def run_pharmcat(
    *,
    vcf: Path,
    run_dir: Path,
    cyp2d6_diplotype_json: Path | None,
    reference_fasta: Path | None = None,
    conventions: PharmCATConventions | None = None,
) -> list[PharmCATFinding]:
    """Run preprocessor → JAR against ``vcf``; return parsed findings.

    Args:
        vcf: source VCF (read-only). The preprocessor opens it host-side;
            no genomic data crosses any network boundary (INV-D001).
        run_dir: derived run directory. The preprocessor writes under
            ``run_dir / preprocessor_output_dir_relpath``; the JAR writes
            its reports under ``run_dir / output_dir_relpath``.
        cyp2d6_diplotype_json: optional path to Slice D's
            ``cyp2d6_diplotype.json``. When provided, converted into
            PharmCAT's outside-call TSV format + threaded into the JAR
            via ``-po``.
        reference_fasta: optional GRCh38 reference fasta. **Essentially
            required at runtime** — without it the preprocessor attempts
            to download the reference from Zenodo into ``/opt/pharmcat/``
            (read-only). When provided, threaded through ``-refFna``.
        conventions: optional :class:`PharmCATConventions`.

    Returns:
        A list of :class:`PharmCATFinding`.

    Raises:
        RuntimeError: when either subprocess exits non-zero OR a
            required output file is missing.
        ValueError: when ``cyp2d6_diplotype_json`` exists but carries
            no diplotype field.
    """
    conv = conventions or PharmCATConventions()
    run_dir.mkdir(parents=True, exist_ok=True)

    preprocessed_dir = run_dir / conv.preprocessor_output_dir_relpath
    preprocessed_dir.mkdir(parents=True, exist_ok=True)

    output_dir = run_dir / conv.output_dir_relpath
    output_dir.mkdir(parents=True, exist_ok=True)

    # Step 1: write the outside-call TSV (if provided) — before
    # subprocess fires so a missing diplotype field is caught early.
    outside_call_tsv: Path | None = None
    if cyp2d6_diplotype_json is not None:
        outside_call_tsv = _write_outside_call_tsv(
            cyp2d6_diplotype_json,
            output_path=run_dir / conv.outside_call_tsv_filename,
            conventions=conv,
        )

    # Step 2: run the preprocessor with the reference fasta threaded
    # through to avoid the Zenodo runtime fetch + read-only write to
    # /opt/pharmcat/.
    preprocessor_argv = _build_preprocessor_argv(
        vcf=vcf,
        output_dir=preprocessed_dir,
        conventions=conv,
        reference_fasta=reference_fasta,
    )
    _run_or_raise(preprocessor_argv, stage_name="preprocessor")

    # Step 3: locate the preprocessed VCF.
    preprocessed_vcf = _find_preprocessed_vcf(preprocessed_dir)

    # Step 4: run the JAR with outside-call (if any).
    jar_argv = _build_pharmcat_argv(
        preprocessed_vcf=preprocessed_vcf,
        output_dir=output_dir,
        outside_call_tsv=outside_call_tsv,
        conventions=conv,
    )
    _run_or_raise(jar_argv, stage_name="jar")

    # Step 5: parse the report.
    report_path = _find_pharmcat_report(output_dir)
    return _parse_pharmcat_report(report_path)


__all__ = [
    "PharmCATFinding",
    "run_pharmcat",
]
