# Path-Crossing Discipline: Lessons from the Phase 5 Smoke

> **Editor's note (2026-05-19, post-promotion)**: this report's draft uses the IDs `INV-D004`, `INV-D005`, `INV-T001`. **The live INVs are renumbered** because `INV-D004` was already taken by *Destructive Operations Require Explicit Confirmation*. The mapping is:
>
> | Draft ID (this report) | Live ID ([INVARIANTS.md v1.12](../reference/INVARIANTS.md)) | Title |
> |------------------------|------------------------------------------------------------|-------|
> | `INV-D004` (draft) | **`INV-D005`** | Identical-Path Bind Mounts for Sibling Containers |
> | `INV-D005` (draft) | **`INV-D006`** | DooD-Safe Path Annotation |
> | `INV-T001` | **`INV-T001`** (unchanged; new `INV-T` category created) | External-Tool Conventions Captured as Typed Wrappers |
>
> The report stays unedited below as historical context — it's the source-of-thought, not the source-of-truth. For the canonical rules, requirements, and verification gates, follow the live IDs into INVARIANTS.md.

**Audience**: future GenomeClaw contributors, current me, anyone designing pipelines that compose containerised tools.
**Date**: 2026-05-19
**Trigger**: six smoke-driver failures (v1 through v6) across two real-data smoke attempts against `MPNRGLQ2K.cram`, four of which were path-related.
**Status**: lessons-learned report; proposed three new invariants. Promoted into [INVARIANTS.md v1.12](../reference/INVARIANTS.md) (see editor's note above for the renumber).

---

## 0. TL;DR

GenomeClaw's PRS pipeline composes four layers (host shell → toolkit container → orchestrator → Nextflow → pgsc_calc sibling containers). Each layer has its own view of the filesystem. **A file path is only useful if it resolves at every layer that needs it.** The Phase 5 smoke kept failing because paths that worked at one layer were invisible at the next.

The fix is a discipline, not a single line of code:

1. **Identical-path bind mounts** for anything that crosses a DooD boundary.
2. **Tool-convention dataclasses** that record each external tool's path expectations (file-suffix auto-append, chr-prefix, column semantics) so wrappers don't reinvent assumptions.
3. **Real-tool smoke before merging** any wrapper that calls an external binary — stubbed `subprocess.run` tests accept whatever argv you write, even when it's wrong.

Three proposed invariants — `INV-D004`, `INV-D005`, `INV-T001` — formalize this. Details in §3.

---

## 1. The bug catalog

Six smoke runs across 2026-05-18 / 2026-05-19. Each failure is a path that didn't survive a layer boundary:

| # | Smoke | Surface error | Real cause | Layer |
|---|---|---|---|---|
| 1 | v1 | bash hung post-plink2 | `start_mem_sampler` background subshell held the `$()` pipe open | not a path bug — bash gotcha, included for context |
| 2 | v2 | "Nextflow update is available" + rc=1 | `pgs.py:_build_pgsc_calc_argv` emitted `--target <vcf>` but pgsc_calc v2.2.0 needs `--input <samplesheet.csv>` | tool argv shape |
| 3 | v3 | "Nextflow update is available" + rc=1 | merged VCF staged at `/tmp/genomeclaw-scratch/...` (toolkit container's local fs); sibling containers spawned by pgsc_calc via DooD see only host paths, can't see the merged VCF | **container ↔ sibling-container** |
| 4 | v4 | same as v3 | re-run after the v3 fix; revealed v5's deeper issue | _interim_ |
| 5 | v5 | "Nextflow update is available" + rc=1 | the shim mounts host paths to `/mnt/genomeclaw/...` (canonical paths); the CLI references `/mnt/genomeclaw/...` paths; pgsc_calc passes those paths to sibling-container `-v` mounts; the host daemon resolves the mount source against the HOST filesystem, where `/mnt/genomeclaw/...` doesn't exist | **host ↔ sibling-container** (transitively, via two layers) |
| 6 | v6 | `No such file: merged.vcf.gz.vcf` | samplesheet `path_prefix` column carried `.vcf.gz` suffix; pgsc_calc auto-appends `.vcf` to the prefix, so it looked for `merged.vcf.gz.vcf` (file not found) | **wrapper ↔ external tool** convention mismatch |

Four of six failures (v2/v3/v5/v6) were path-related. Every "Nextflow update is available" message turned out to be the only-stderr-content of a Nextflow process that bailed with rc=1 for reasons that surfaced ONLY in the `.nextflow.log` inside the container — which we couldn't see post-mortem because the container's working directory was ephemeral.

---

## 2. Why the existing tests didn't catch them

GenomeClaw has ~691 unit + integration tests. The relevant ones look like:

```python
def test_compute_pgs_invokes_pgsc_calc_with_run_ancestry(...):
    """Wrapper builds the right argv: --target_build, --pgs_id, --run_ancestry."""
    ...
    with patch("genomeclaw_toolkit.prep.pgs.subprocess.run", _fake_pgsc_calc_run(work_dir)):
        compute_pgs(...)
    argv = fake_run.call_args_list[0].args[0]
    assert "--target_build" in argv and argv[argv.index("--target_build") + 1] == "GRCh38"
    assert "--pgs_id" in argv and argv[argv.index("--pgs_id") + 1] == "PGS000018"
    assert "--run_ancestry" in argv_str
```

This test passes if the wrapper emits `--target_build`, `--pgs_id`, and `--run_ancestry`. It does **not** check:

- That `--target` vs. `--input` matches pgsc_calc v2.2.0's actual contract.
- That the samplesheet's `path_prefix` column follows pgsc_calc's documented conventions.
- That the paths passed to the tool are resolvable in the runtime environment (DooD or otherwise).

The stubbed `subprocess.run` accepts whatever argv we hand it. **The wrapper's argv shape is whatever we said it is** — not what pgsc_calc actually wants.

This pattern is the deeper failure mode: stubbed-process tests verify the wrapper's intent, not the tool's contract. To catch real-tool bugs, we need either (a) real-tool integration tests, or (b) convention dataclasses tested against upstream documentation.

---

## 3. Proposed new invariants

Three invariants for promotion into [INVARIANTS.md](../reference/INVARIANTS.md) after tests are in place to enforce them. IDs assigned by category — `INV-D004` and `INV-D005` extend the Data-integrity family; `INV-T001` opens a new Tool-integration category.

### INV-D004: Identical-Path Bind Mounts for Sibling Containers

**Rule**: When a process inside a container will spawn sibling containers via Docker-out-of-Docker (DooD), every host path that may flow into a sibling's mount argument must be bind-mounted into the parent container at the **identical absolute path** as on the host.

**Requirements**:
- Any container that mounts `/var/run/docker.sock` (the DooD signal) must use identical-path bind mounts for every host directory referenced by paths it will pass to `docker run -v`.
- The canonical `/mnt/genomeclaw/...` mount convention is allowed **in addition to** (not instead of) the identical-path bind mount.
- Code that constructs `docker run -v` arg strings inside a container must accept paths that are valid both inside and outside the container (i.e., paths under an identical-path-mounted dir).

**Where it applies**:
- The host shim ([`bin/genomeclaw`](../../bin/genomeclaw)) when invoking the toolkit image for any subcommand that may spawn siblings (currently: `pipeline prs-compute`; future: anything else using Nextflow).
- The Phase 5 smoke driver ([`bin/genomeclaw-prs-smoke`](../../bin/genomeclaw-prs-smoke)) — fixed in smoke v5.
- Future host shims for other Nextflow-based tools (e.g., nf-core/sarek).

**How to verify**:
- Integration test that asserts every `--mount` flag in the shim's docker run includes an identical-path entry for host directories that downstream code may pass to a sibling.
- A runtime guard: a `DooDPathError` typed exception that fires when a code path about to call `docker run -v <host>:<container>` detects that `<host>` is not a path visible on the host.

### INV-D005: DooD-Safe Path Annotation

**Rule**: Any wrapper function that may write a path argument into a downstream tool's invocation **whose execution context is sibling-containers via DooD** must mark its path-typed parameters with a `SiblingMountablePath` annotation (a `Path` subclass or `Annotated[Path, ...]`), and a static check or runtime guard rejects paths that are not within a `/var/lib/docker`-resolvable host filesystem prefix.

**Requirements**:
- Wrappers that prepare inputs for Nextflow / pgsc_calc / similar accept `SiblingMountablePath` for those inputs, not bare `Path`.
- The orchestrator's "write merged VCF here" decision is constrained at the type level to choose a `SiblingMountablePath` location (`work_dir`), not a container-local scratch path (`/tmp/genomeclaw-scratch`).
- The `ephemeral_scratch_base()` helper is documented as **NOT sibling-mountable** in its docstring + the type system surfaces it as `Path`, not `SiblingMountablePath`.

**Where it applies**:
- `compute_prs_with_coverage_fill` (the bug from smoke v3 lived here).
- `_write_pgsc_calc_samplesheet` and any future samplesheet writer that records host paths for sibling consumption.
- Any future orchestrator that stages inputs for a Nextflow pipeline.

**How to verify**:
- Tests that pass a non-sibling-mountable path (e.g., a `tmp_path / "tmp" / "merged.vcf.gz"`) to the orchestrator and assert that the typed exception fires before the bcftools step runs.
- Lint check (via mypy `Annotated` propagation) that flags raw-`Path` arguments where `SiblingMountablePath` is expected.

### INV-T001: External-Tool Conventions Captured as Typed Wrappers

**Rule**: When GenomeClaw integrates an external tool (pgsc_calc, plink2, bcftools, VEP, etc.), the tool's **path / argv / file-format conventions** are captured in a typed `<Tool>Conventions` dataclass at the wrapper layer, with each field's value cited to upstream documentation (or to an empirical probe against the tool's actual binary). Wrapper tests assert against these captured conventions, not against hand-rolled assumptions.

**Requirements**:
- One `<Tool>Conventions` dataclass per integrated tool. Examples:
  - `PgscCalcConventions(samplesheet_columns=..., path_prefix_strips_extension=True, vcf_genotype_field_default="GT", accession_naming="<PGS_ID>_hmPOS_GRCh38", ...)`.
  - `Plink2Conventions(panel_chrom_naming="bare", lf_pruning_default_r2=0.05, ...)`.
  - `BcftoolsConventions(cram_chrom_naming="chr-prefix", min_bq_default=20, ...)`.
- Each field has a docstring with a citation: either a URL to upstream docs OR a path to a captured `tools/<tool>/probe-output.txt` file showing the empirical behaviour.
- Wrapper tests construct the tool's argv using the conventions dataclass and assert the resulting argv against a golden file (`tools/<tool>/golden-argv.txt`) captured from a successful real invocation.

**Where it applies**:
- New tool integrations: write the conventions dataclass FIRST, then the wrapper.
- Existing wrappers: backfill the conventions dataclass during the next breaking change (e.g., when bumping the tool's pin in `_versions.py`).

**How to verify**:
- The conventions dataclass exists for every external-tool wrapper in `prep/`.
- Each integration test references the conventions dataclass, not hardcoded strings.
- A `tools/<tool>/probe.sh` script (or pytest fixture) records the tool's actual behaviour for the documented conventions; CI runs it when the tool's pin changes.

---

## 4. Specific code changes to land alongside the invariants

These can land in any order; they don't depend on each other.

### Change 1 — Identical-path mounts in the shim

[`bin/genomeclaw`](../../bin/genomeclaw) currently mounts canonical paths only:
```bash
--mount type=bind,source=${raw_dir},target=/mnt/genomeclaw/raw,readonly
--mount type=bind,source=${ref_dir},target=/mnt/genomeclaw/reference
--mount type=bind,source=${derived_dir},target=/mnt/genomeclaw/derived
--mount type=bind,source=${scratch_dir},target=/mnt/genomeclaw/scratch
```

When any subcommand may spawn DooD siblings, ADD identical-path mounts:
```bash
--mount type=bind,source=${canonical_root},target=${canonical_root}
```

Effect: the toolkit container sees the host's path tree at the same absolute paths. When pgsc_calc tells a sibling "mount this host path", the host daemon resolves correctly.

The `/mnt/genomeclaw/...` canonical mounts stay — they preserve the read-only `raw` enforcement and serve subcommands that don't need DooD. The identical-path mount is an additive overlay; it never conflicts with the canonical mounts as long as the canonical_root is different from `/mnt/`.

Conditional on a new env var (`GENOMECLAW_DOOD=1`) so non-Nextflow subcommands don't pay the mount cost.

### Change 2 — `SiblingMountablePath` type

```python
from pathlib import Path
from typing import NewType

# Marker subclass; runtime is a Path, but type-checker tracks it separately.
class SiblingMountablePath(Path):
    """A Path that resolves on both host and any sibling container spawned via DooD.

    Construct via `as_sibling_mountable(path)` which verifies the path is
    under a known sibling-mountable prefix (configured via env or settings).
    """

def as_sibling_mountable(path: Path) -> SiblingMountablePath:
    """Validate + tag a Path as sibling-mountable.

    Raises DooDPathError if the path is under ephemeral_scratch_base() or
    any other non-host-visible location.
    """
    ...
```

Wrappers like `compute_pgs` annotate:
```python
def compute_pgs(*, vcf: SiblingMountablePath, work_dir: SiblingMountablePath, ...) -> PgsRow:
    ...
```

Static check (mypy + a lint rule): callers must construct `SiblingMountablePath` via the validated factory.

### Change 3 — `PgscCalcConventions` dataclass

```python
@dataclass(frozen=True)
class PgscCalcConventions:
    """pgsc_calc v2.x argv + samplesheet conventions.

    Verified against pgsc_calc README + 2026-05-19 empirical probe.
    Bump `verified_against_version` when the upstream contract changes.
    """
    verified_against_version: str = "v2.2.0"

    # Argv flags
    input_flag: str = "--input"  # ← was --target in pre-v2.2 era
    samplesheet_required: bool = True

    # Samplesheet column semantics
    samplesheet_columns: tuple[str, ...] = (
        "sampleset", "path_prefix", "chrom", "format", "vcf_genotype_field",
    )
    # path_prefix is a basename PREFIX without the .vcf.gz suffix;
    # pgsc_calc auto-appends `.vcf` and detects .gz separately.
    path_prefix_strips_extension: bool = True
    vcf_genotype_field_default: str = "GT"

    # Accession naming for harmonised scoring files
    accession_format: str = "{pgs_id}_hmPOS_GRCh38"

    # Output files
    aggregated_scores_relpath: str = "score/aggregated_scores.txt.gz"
    match_log_relpath_pattern: str = "**/{sampleset}_log.csv.gz"
```

The wrapper consumes this constant; tests assert the constructed argv + samplesheet shape against it.

A `tools/pgsc_calc/probe.sh` script invokes pgsc_calc against a minimal fixture + records:
- `nextflow run pgscatalog/pgsc_calc -r v2.2.0 --help` (full output)
- A successful real run's argv + the samplesheet contents that work

When the pin in `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes, CI runs `probe.sh` + diffs against the recorded baseline; any mismatch flags the conventions dataclass as needing review.

---

## 5. The deeper principle: paths cross layers; trust nothing

Every path in this codebase moves through some chain of:

```
HOST FS
  → host shell (bin/genomeclaw)
    → docker run -v (translation 1: host path → container path)
      → toolkit container code (uses /mnt/genomeclaw/... or the host path)
        → subprocess.run for nested tool
          → tool's own argv parsing (translation 2: argv → file lookup)
            → tool's own file-suffix conventions (translation 3: prefix → actual filename)
              → tool spawns sibling container via DooD
                → docker run -v <host_path>:<sibling_container_path> (translation 4)
                  → host docker daemon resolves <host_path> against HOST FS
                    → sibling container opens file (via its mount view)
```

That's **four path translations** between when a path leaves your Python code and when a sibling container actually opens the file. Each translation can drop context. The shim, the wrapper, the tool's argv parser, the tool's filename convention, and DooD's host-daemon resolution all introduce assumptions that can disagree.

The discipline isn't "be careful with paths"; that's hopeful. The discipline is:

1. **Make boundaries explicit** in types (`SiblingMountablePath`) so the compiler knows where translations happen.
2. **Capture tool conventions** in typed dataclasses (`PgscCalcConventions`) so the tool's contract isn't reinvented per-test.
3. **Bind-mount identically** when paths cross DooD boundaries so translations are no-ops.
4. **Smoke-test against the real tool** before declaring a wrapper "working".

This is the same lesson the 2026-05-17 research brief surfaced for variant-only VCFs (the variant-only VCF was a representation that worked at one layer but failed at another). The PRS pipeline has now produced two reports about layer mismatches; the meta-lesson is that **multi-layer composition without explicit contracts is the dominant failure mode** in this codebase.

---

## 6. What to do next

In rough priority order:

1. **Promote `INV-D004` first.** Lowest friction (just add the identical-path mount in the shim, conditional on `GENOMECLAW_DOOD=1`); biggest immediate win (unblocks Phase 5 + any future Nextflow integration).
2. **Add `PgscCalcConventions` dataclass + the regression-guard tests already in place.** Phase 5 surfaced enough bugs in pgsc_calc's argv that the conventions are well-understood at this point; capture them while fresh.
3. **Promote `INV-D005` after the path-typing migration is real**. The `SiblingMountablePath` type is more invasive (touches many wrappers); defer to a dedicated migration that includes static-check enforcement.
4. **Backfill `INV-T001` to plink2 + bcftools wrappers** during the next breaking change to either of those tools.
5. **Update [docs/plans/CLAUDE.md](../plans/CLAUDE.md)** to require a real-tool smoke run as part of any plan that integrates a new external tool, not just stubbed-subprocess tests.

The Phase 5 smoke is the canary; future tool integrations should not need a five-day debugging marathon to surface the same class of bug.

---

## 7. Honest postscript

I (the engineering assistant) wrote the original `pgs.py` wrapper using `--target` + the original samplesheet with the full path, and the wrapper passed every stubbed-subprocess test. The 2026-05-17 smoke had documented in work-notes that `-profile docker` worked, but the samplesheet format the smoke used was correct in a way the wrapper didn't preserve. The discipline gap was real: stubbed-subprocess tests **cannot** catch tool-contract mismatches; they only catch "did the wrapper construct the argv I told it to construct?".

The path-handling failures of v2/v3/v5/v6 cost an estimated **8 hours of debugging + four 90-minute Tier 1 rebuilds + a CRAM-cache invalidation**. The invariants proposed here would have caught all four bugs at test time. The cost of writing the conventions dataclass + the path types is maybe 2–4 hours; the payback is preventing the next 8-hour debugging cycle.

I'm logging this report as the artefact that translates this session's lessons into durable repo discipline. The next contributor (or the next-me) doesn't need to re-learn it from a smoke run.
