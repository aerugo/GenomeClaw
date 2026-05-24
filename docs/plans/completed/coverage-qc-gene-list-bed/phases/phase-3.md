# Phase 3 — Live verification (canonical run + agent reply)

**Status**: Pending (gated on Phase 2)
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Run `pipeline run` against the user's real CRAM with the default panel auto-engaged; verify `coverage_qc` populates with ≥200 real rows; verify the agent's eyesight question now names specific per-gene coverage values. Close the plan.

## Scope Boundaries

- **In scope**:
  - One operator-run smoke against the canonical CRAM.
  - One live agent test extending `test_live_agent_prs_compute_e2e.py`.
  - Documentation update (architecture.md + plan move to completed/).
- **Out of scope**:
  - Re-running Phase 1/2's unit + integration tests (their own verification gates).
  - Panel-content tuning based on the smoke results (defer to a v2 panel plan).

## Invariants enforced in this phase

- **INV-R001** — assert the persisted `coverage_qc` rows carry the seven provenance columns + the `params_json` panel-version + threshold.
- **INV-T001** — mosdepth output still matches `MosdepthConventions` (the existing INV-T001 probe test covers this).

---

## Steps

### 3.1 — Manual smoke

Re-run the canonical pipeline against the user's real CRAM:

```bash
cd /Users/hugi/GitRepos/GenomeClaw
GENOMECLAW_IMAGE=genomeclaw/toolkit:<latest> \
  bin/genomeclaw pipeline ingest \
    --vcf /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.hc.vcf.gz \
    --bam /mnt/genomeclaw/raw/MPNRGLQ2K/MPNRGLQ2K.mm2.sortdup.bqsr.cram \
    --reference /mnt/genomeclaw/reference/grch38/ncbi-2014 \
    --sample-id MPNRGLQ2K \
    --json | tee /tmp/coverage_qc_smoke.ndjson
```

Note: `--bed` is INTENTIONALLY omitted — Phase 2's auto-engage should pick up the default panel.

Verify the output:

```bash
# Coverage QC row count (expect ≥200)
echo "SELECT count(*) FROM coverage_qc;" | duckdb /Volumes/Genome_Work/genomeclaw/derived/<latest-run-id>/variants.duckdb

# Sample rows (verify mean_depth populated)
echo "SELECT gene, mean_depth, low_coverage_exons FROM coverage_qc WHERE gene IN ('CFH','BRCA1','APOE','MYOC') LIMIT 10;" \
  | duckdb /Volumes/Genome_Work/genomeclaw/derived/<latest-run-id>/variants.duckdb

# Provenance shape (expect panel_version + threshold)
echo "SELECT DISTINCT params_json FROM coverage_qc LIMIT 1;" | duckdb /Volumes/Genome_Work/genomeclaw/derived/<latest-run-id>/variants.duckdb
```

Record the smoke wall-clock + the per-gene mean-depth excerpt (CFH, BRCA1, APOE, MYOC) in this plan's `work-notes.md`.

### 3.2 — Extend live agent E2E test

Add to `packages/toolkit/tests/integration/test_live_agent_prs_compute_e2e.py`:

```python
@pytest.mark.live_llm
def test_live_agent_eyesight_question_surfaces_real_coverage(tmp_path: Path) -> None:
    """The eyesight-question reply names specific per-gene mean_depth.

    Closes the coverage-qc-gene-list-bed plan: with the default panel
    auto-engaged on ingest, the canonical run-dir's coverage_qc table
    has real rows; genomeclaw_gene returns real mean_depth +
    low_coverage_exons; the disease-area-discovery sysprompt directs
    the agent to report them.

    Required env:
    - GENOMECLAW_PGS_E2E_REAL_RUN_DIR=<canonical-run-dir>
    - GENOMECLAW_SANDBOX_IMAGE=<image with the disease-area-discovery prompt>
    - OPENAI_API_KEY=...
    """
    real_run_dir = os.environ.get("GENOMECLAW_PGS_E2E_REAL_RUN_DIR")
    if not real_run_dir:
        pytest.skip("requires GENOMECLAW_PGS_E2E_REAL_RUN_DIR")

    derived_root = Path(real_run_dir).parent
    trace = run_agent_in_sandbox(
        "Do I have any risk factors for loss of eyesight?",
        derived_root=derived_root,
        sandbox_image=os.environ["GENOMECLAW_SANDBOX_IMAGE"],
        openai_api_key=os.environ["OPENAI_API_KEY"],
        timeout_s=600,
    )
    reply = trace.get("result", trace).get("payloads", [{}])[0].get("text", "")
    assert reply

    # Reply names at least one gene with a numeric mean_depth value
    # (e.g. "CFH mean depth 32×" or "ARMS2: 18× mean coverage").
    depth_pattern = re.compile(
        r"(?:CFH|ARMS2|HTRA1|ABCA4|USH2A|MYOC|OPTN|TBK1|CYP1B1|RPE65|RHO|RPGR|TIMP3|C2|C3|CFB)"
        r".{0,40}?"
        r"\d+(?:\.\d+)?\s*(?:×|x|mean depth|coverage)",
        re.IGNORECASE,
    )
    assert depth_pattern.search(reply), (
        "agent's reply did not name a per-gene mean-depth value. "
        "With coverage_qc populated, the disease-area-discovery pattern "
        "should report real coverage status, not just 'no low-coverage warnings'.\n"
        f"Reply prefix: {reply[:1500]!r}"
    )
```

### 3.3 — Update architecture doc

Brief paragraph in `docs/reference/architecture.md`'s pipeline section:

> *Coverage QC*: when `pipeline ingest --bam <CRAM>` is given without `--bed`, the toolkit auto-engages a bundled default gene-panel BED (~200 disease-area-relevant genes covering the ACMG SF v3.2 list + the agent's disease-area-discovery sysprompt panels + PharmCAT-flagged pharmacogenomic genes). Mosdepth populates `coverage_qc` with per-gene mean depth + low-coverage exon flags (default threshold 20×). Opt out with `--no-coverage-qc`. INV-T001 mosdepth tool-conventions probe is unchanged.

### 3.4 — Close-out

- Record smoke + live-test outcomes in `work-notes.md`.
- Update the completed `agent-prs-compute-fix` plan's open-follow-ups list to mark "AC8 coverage_qc / gene-list BED" as resolved.
- `git mv docs/plans/active/coverage-qc-gene-list-bed → docs/plans/completed/coverage-qc-gene-list-bed`.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `packages/toolkit/tests/integration/test_live_agent_prs_compute_e2e.py` | MODIFY | Add `test_live_agent_eyesight_question_surfaces_real_coverage` |
| `docs/reference/architecture.md` | MODIFY (light) | Document the default-panel + opt-out behavior |
| `docs/plans/active/coverage-qc-gene-list-bed/work-notes.md` | MODIFY | Phase 3 close block with smoke wall-clock + agent reply excerpt |
| `docs/plans/completed/agent-prs-compute-fix/work-notes.md` | MODIFY (light) | Mark AC8 open-follow-up resolved |

After live PASS: `git mv` to completed/.

---

## Verification

```bash
# Manual smoke (operator-run; ~2-4h wall)
bin/genomeclaw pipeline ingest --vcf <vcf> --bam <CRAM> --reference <ref-dir> ...
# Expect: coverage_qc has ≥200 rows; sample rows have non-null mean_depth.

# Live agent test
cd packages/toolkit
GENOMECLAW_PGS_E2E_REAL_RUN_DIR=<run-dir> \
GENOMECLAW_SANDBOX_IMAGE=<image> \
OPENAI_API_KEY=... \
  uv run pytest tests/integration/test_live_agent_prs_compute_e2e.py::test_live_agent_eyesight_question_surfaces_real_coverage -v -s
# Expect: PASS

# Full sweep
uv run pytest tests/unit tests/integration tests/invariants tests/provenance tests/privacy --no-header -q
# Expect: 874+ passed, no regressions.
```

---

## Completion Criteria

- [ ] Manual smoke against canonical CRAM populates `coverage_qc` with ≥200 rows.
- [ ] `coverage_qc.params_json` shows the panel-version + threshold (INV-R001).
- [ ] `test_live_agent_eyesight_question_surfaces_real_coverage` PASSES.
- [ ] Agent's reply to the eyesight question names ≥1 specific per-gene mean-depth value.
- [ ] `architecture.md` updated.
- [ ] `agent-prs-compute-fix`'s open-follow-up "AC8 coverage_qc" marked resolved.
- [ ] Plan moved from `active/` to `completed/`.

## Next

Plan closes. No further phases.
