# Feature: Path-Crossing Discipline for DooD-Composed Pipelines

**Status**: Draft
**Created**: 2026-05-19
**Owner**: GenomeClaw maintainers
**Related Plans**:
- [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md) — the lessons-learned report this plan implements
- [docs/plans/active/prs-input-coverage-fill/](../prs-input-coverage-fill/) — the Phase 5 smoke that produced the lessons

---

## Goal

Promote three new project-wide invariants (identical-path bind mounts across DooD boundaries, DooD-safe path typing, external-tool conventions as typed wrappers) and ship the code + tests that enforce them, so the next external-tool integration does not need a five-day debugging marathon to surface the same class of bug.

## Background

The 2026-05-18 / 2026-05-19 Phase 5 PRS smoke produced six driver failures against `MPNRGLQ2K.cram`, four of which were path-related — paths that worked at one layer of the pipeline were invisible at the next. Cataloged in [docs/reports/path-crossing-discipline.md](../../../reports/path-crossing-discipline.md):

| # | Symptom | Root cause | Layer that dropped the path |
|---|---------|------------|-----------------------------|
| v2 | rc=1 "Nextflow update is available" | `_build_pgsc_calc_argv` emitted `--target <vcf>` instead of `--input <samplesheet.csv>` | wrapper → tool argv |
| v3 | rc=1 same surface | merged VCF staged at `/tmp/genomeclaw-scratch/...` (container-local fs); sibling containers spawned via DooD can't see it | container → sibling container |
| v5 | rc=1 same surface | shim mounts canonical `/mnt/genomeclaw/...` only; pgsc_calc passes those to sibling `-v` mounts; host daemon resolves against host FS where `/mnt/genomeclaw/` doesn't exist | host → sibling container (transitive) |
| v6 | `No such file: merged.vcf.gz.vcf` | samplesheet `path_prefix` column carried `.vcf.gz`; pgsc_calc auto-appends `.vcf` | wrapper → tool filename convention |

The existing ~691 unit + integration tests passed throughout. Stubbed-`subprocess.run` tests accept whatever argv the wrapper hands them — they verify intent, not tool contract. The discipline gap is structural; only invariants + new test surfaces close it.

The report proposes three invariants (`INV-D004`, `INV-D005`, `INV-T001`). **The IDs in the report conflict with the live INVARIANTS.md** — `INV-D004` is already in use for "Destructive Operations Require Explicit Confirmation" (added in the [completed/host-mount-lifecycle](../../completed/host-mount-lifecycle/) plan). This plan renumbers to `INV-D005`, `INV-D006`, `INV-T001` and calls the renumbering out in §"Open Questions" so the report and the live invariant text don't diverge silently.

## Acceptance Criteria

Each criterion is testable and maps to at least one phase. ACs in CAPS are blocking for the corresponding phase's GREEN gate.

- [ ] **AC1** When `GENOMECLAW_DOOD=1` is set, the shim adds an identical-path bind mount overlay for `${canonical_root}` on top of the canonical `/mnt/genomeclaw/...` mounts; with the env var unset, the shim's behavior is byte-identical to today's.
- [ ] **AC2** Subcommands that spawn DooD siblings (`pipeline prs-compute`) set `GENOMECLAW_DOOD=1` automatically. Subcommands that don't (`ingest`, `normalize`, `annotate`, `materialize`, `host *`, `refs fetch`) keep the today-shape.
- [ ] **AC3** A `DooDPathError` typed exception fires when code about to invoke `docker run -v <host>:<container>` detects that `<host>` is not visible on the host filesystem (e.g., the path is under `ephemeral_scratch_base()` or an in-container-only `/tmp/...`).
- [ ] **AC4** A `SiblingMountablePath` type (Path subclass) exists, constructed via `as_sibling_mountable(path)` which validates the path is under a known host-visible prefix. Wrappers that pass paths into DooD siblings accept `SiblingMountablePath`, not bare `Path`.
- [ ] **AC5** mypy + pytest reject any code path that hands a bare `Path` where `SiblingMountablePath` is required. A regression test exercises this with a synthetic `tmp_path / "tmp" / "merged.vcf.gz"` against `compute_prs_with_coverage_fill`.
- [ ] **AC6** A `PgscCalcConventions` frozen dataclass exists, each field cited to upstream docs or a captured `tools/pgsc_calc/probe-output.txt` empirical baseline. The `pgs.py` wrapper consumes the dataclass for argv + samplesheet construction; wrapper tests assert against the dataclass, not against hardcoded strings.
- [ ] **AC7** A `tools/pgsc_calc/probe.sh` script (run on demand) records pgsc_calc's actual `--help` output + a known-good real-tool argv + samplesheet. CI runs `probe.sh` whenever `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` changes; mismatch against the recorded golden fails the build.
- [ ] **AC8** [docs/reference/INVARIANTS.md](../../../reference/INVARIANTS.md) is updated with the three new invariants (`INV-D005`, `INV-D006`, `INV-T001`). Version is bumped (current 1.11 → 1.12); Last Updated is set; the Invariant Index table gets three new rows; the Invariant ID Convention table gets a new `INV-T` row.
- [ ] **AC9** [docs/reference/architecture.md](../../../reference/architecture.md) is updated with: (a) a new "Path-crossing layers" subsection under §"Network topology" or §"Host-side packaging", showing the four DooD path translations the report enumerates, and (b) updates to the invariant-traceability table covering the three new IDs.
- [ ] **AC10** [docs/plans/CLAUDE.md](../../CLAUDE.md) is updated under §"TDD Principles" to require a real-tool smoke run (not just stubbed-subprocess tests) for any plan that integrates a new external bioinformatics tool.
- [ ] **AC11** A real-tool integration smoke run of `pipeline prs-compute` against the project owner's `MPNRGLQ2K.cram` completes without any of the v2/v3/v5/v6 path bugs recurring. The smoke command and output are captured in `work-notes.md`.

## Applicable Invariants

- **INV-D001** Raw Genomic Files Are Source-of-Truth — the identical-path overlay mount is **read-only** for `raw/` (same as the canonical `/mnt/genomeclaw/raw` mount); the additive overlay can never widen the `raw/` mount from `:ro` to `:rw`.
- **INV-D002** Raw Genomic Artifacts Are Host-Side Only — DooD is a host-only mechanism; sibling containers spawned by pgsc_calc are host-side workers. The OpenShell sandbox has no `docker.sock` and no DooD path. This plan does not alter that.
- **INV-D003** Heavy Scratch Is Separated From Authoritative Outputs — the `SiblingMountablePath` factory rejects paths under `ephemeral_scratch_base()` (the container-local `/tmp` that is NOT bind-mounted from the host); rejected paths route to the canonical `_scratch/` mount, which IS host-visible, preserving INV-D003 while making the path DooD-safe.
- **INV-R001** Derived Stores Must Stay Rebuildable — capturing tool conventions as typed dataclasses with `verified_against_version` fields strengthens rebuildability: a future pgsc_calc bump that changes argv shape produces a typed mismatch at test time, not a silent rc=1 in a smoke run.
- **INV-P001** Privacy Default — no new network egress. DooD is a host-side mechanism; the identical-path overlay does not open any new boundary.

## Proposed New Invariants

Three. Texts below are the proposed entries for [INVARIANTS.md](../../../reference/INVARIANTS.md) once tests are green. See [development-plan.md](development-plan.md) §"Proposed Invariant Texts" for the full drafts.

- **INV-D005**: Identical-Path Bind Mounts for Sibling Containers — when a process inside a container spawns sibling containers via DooD, every host path that may flow into a sibling's `-v` mount must be bind-mounted into the parent at the **identical absolute path**.
- **INV-D006**: DooD-Safe Path Annotation — wrappers that pass paths into DooD-spawned tools accept `SiblingMountablePath` (a validated `Path` subclass), not bare `Path`. mypy + a runtime guard enforce.
- **INV-T001**: External-Tool Conventions Captured as Typed Wrappers — every external tool's argv / samplesheet / filename convention is captured in a `<Tool>Conventions` frozen dataclass with each field cited to upstream docs or a captured probe; wrapper tests assert against the dataclass, not against hardcoded strings.

`INV-T001` opens a new category `INV-T` for **Tool integration & external-binary contracts**. The Invariant ID Convention table gets a new row.

## Technical Requirements

### Source Data Inputs
- None new. The plan touches the shim, the toolkit Python code, and the test surface only.

### Derived Outputs
- None new. The `PgscCalcConventions` dataclass changes how `pgsc_calc` argv is constructed but produces byte-identical argv to the smoke-validated v6 fix.

### Schema / Migration Impact
- None. No derived-store schema changes.

### Pipeline / Workflow Impact
- `pipeline prs-compute` gains the `GENOMECLAW_DOOD=1` auto-set in the shim. Behavior under default config is unchanged for users on the canonical `/Volumes/Genome_Work/genomeclaw/...` layout; the identical-path overlay re-resolves to the same host paths the canonical mounts already expose.
- For users with custom `GENOMECLAW_*_DIR` overrides pointing to paths NOT under a single canonical root, the overlay strategy needs the four mount sources separately. The shim picks the longest common prefix of the four `*_DIR` paths and mounts that as the overlay; if no common prefix exists above `/`, the shim falls back to four separate identical-path mounts.

### Agent / UX Impact
- None. The agent sees `pgs_scores` rows via the host service, same shape as today.

### External Dependencies
- pgsc_calc — already pinned via `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]`. The conventions dataclass cites the pinned version explicitly.
- Future plink2, bcftools conventions dataclasses are deferred to Phase 4 (backfill on next bump).

## Privacy & Safety Considerations

- **Boundary scan**: no new boundaries. DooD is host-side; sibling containers run on the host docker daemon, never reachable from the OpenShell sandbox.
- **Default-off remote calls**: none added.
- **Redaction surface**: n/a.
- **Clinical escalation**: n/a — this plan is plumbing.

## Out of Scope

Explicit boundaries:

- **Backfilling `Plink2Conventions` and `BcftoolsConventions`**. Deferred to the next breaking change to either of those tools' pins per the report's §6 priority ordering. The `INV-T001` rule applies *forward* (new tool integrations must do this on the way in); the *backfill* is opportunistic. Phase 4 documents the policy; the backfill itself is its own plan.
- **Removing DooD entirely** in favor of a Nextflow-in-a-pod / Kubernetes-style scheduler. Substantial re-architecture; not what the report recommends. The report's discipline is "make DooD work safely", not "abolish DooD".
- **The 2026-05-17 variant-only-VCF report** (the predecessor lesson the report's §5 alludes to). That predecessor produced the `prs-input-coverage-fill` plan, which is in progress and not blocked by this plan.
- **Static linting via mypy alone**. mypy's enforcement of `SiblingMountablePath` is necessary but not sufficient (mypy can be bypassed). The runtime guard in `as_sibling_mountable` is the load-bearing check; mypy adds early feedback.

## Dependencies

- [docs/plans/active/prs-input-coverage-fill/](../prs-input-coverage-fill/) — the smoke that produced the lessons. This plan can land independently of it; the conventions dataclass + identical-path mounts make `prs-input-coverage-fill`'s Phase 5 smoke more robust but don't gate its completion.
- `_versions.PRS_RUNTIME_VERSIONS["pgsc_calc"]` — pinned. Conventions dataclass cites the pinned version.

## Open Questions

- [ ] **Q1**: The report uses `INV-D004` and `INV-D005` for the two new data-integrity invariants. The live INVARIANTS.md has `INV-D004` taken (Destructive Operations). **Decision Taken**: this plan renumbers to `INV-D005` and `INV-D006`. The report file is annotated with a leading editor's note pointing at the renumber.
- [ ] **Q2**: Should the identical-path overlay be unconditional (always on), or gated on `GENOMECLAW_DOOD=1`? **Recommended**: gate on the env var, auto-set for subcommands that need it. Two reasons: (a) the overlay adds a second bind-mount entry per canonical mount, which is wasted IOMMU work for non-DooD subcommands; (b) gating makes the dependency visible — a future contributor adding a new DooD-spawning subcommand explicitly opts in. Confirmation needed before Phase 1 starts.
- [ ] **Q3**: When the four `*_DIR` env vars point to paths with no common prefix above `/`, should the shim mount four separate identical-path overlays, or refuse with a setup-hint error? **Recommended**: four separate overlays (no refusal). Rationale: refusing breaks any deployment with split storage trees, which is a legitimate setup. The cost is four extra mount entries, which docker handles fine.
- [ ] **Q4**: Does the `SiblingMountablePath` factory need to handle macOS-VZ-virtiofs quirks (the `$HOME` mount that's read-only inside the container unless Full Disk Access is granted to limactl, documented in [architecture.md](../../../reference/architecture.md) §"Engine VM file-sharing")? **Recommended**: yes, document the quirk in the factory's docstring; the factory's job is to validate host-visibility, and a `$HOME`-rooted path that's not in `colima.yaml`'s `mounts:` list is not host-visible from the engine VM's perspective. Test fixture covers this by checking the colima mounts list.
- [ ] **Q5**: Should `INV-T001`'s probe-output goldens be checked into the repo, or generated on demand? **Recommended**: checked in under `tools/pgsc_calc/probe-output.txt` with a per-line comment citing where each line was observed. Generation-on-demand defeats the purpose (the golden is the contract; if it's not version-controlled, the contract evolves invisibly).
