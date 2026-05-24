# GenomeClaw Project Invariants

**Status**: Living document
**Version**: 1.16
**Last Updated**: 2026-05-24

This is the **canonical reference** for GenomeClaw's project invariants. Every implementation plan, phase plan, and substantive code review must reference applicable invariants by their canonical ID (e.g., `INV-D001`). The five top-level rules in the root [CLAUDE.md](../../CLAUDE.md) are formalized here.

**v1.16 (2026-05-24)** — **explicit-runtime-negative-case coverage layer added for `INV-P002`**. The runtime SSRF probe (ssrf-runtime-probe plan Phase 1 + 1b) ships a `@pytest.mark.live_ssrf_probe`-gated test (`packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py`) that invokes a TEST-ONLY plugin tool (`genomeclaw_ssrf_probe_batch`, env-gated by `GENOMECLAW_ENABLE_SSRF_PROBE=1`) which issues a hardcoded 5-tuple probe sweep from inside the plugin's enforcement context. The ALLOW probe asserts HTTP 200 from `host.openshell.internal:8643 /v1/health` with a real body; the four DENY probes (off-port, RFC 1918 non-gateway, public hostname, public IP+non-standard port) each assert their `rejection_class` matches the per-tuple allow-set. This is the third coverage layer for INV-P002 (static YAML shape + implicit-via-live-LLM-tests were already in place). Catches policy-enforcement regression at CI time. Empirically OpenShell doesn't return a structured rejection body for L7 denies — it kills the connection — so deny probes classify as `deny_other` (generic fetch failure); sharpening the classifier would need a follow-up probe shape that's network-reachable but policy-blocked. No new invariant IDs; `INV-P002` rule text unchanged. See `docs/plans/active/ssrf-runtime-probe/` for the plan + the two openclaw runtime bugs surfaced during Path Y implementation (TypeBox array-of-object strip + Q-001 string-arg corruption).

**v1.15 (2026-05-23)** — **scope clarification on `INV-D006` (shim-side propagation) + `INV-T001` (plugin-load coverage)**. Two regressions during MVP Phase 7's canonical real-data run surfaced gaps in how the existing invariants were enforced. INV-D006 was only checked at the wrapper layer (paths annotated `SiblingMountablePath`); a meta-invariant test now also enforces that the shim's `_dood_scan_args` regex list is exhaustive over wrappers that import `as_sibling_mountable`. INV-T001 only covered argv-level pinning for external tools; the VEP plugin set (LOFTEE) loads perl modules at runtime via `do` + `install_driver` paths that `perl -c` syntax-check doesn't reach. The extended `test_vep_loftee_plugin.py` adds an explicit `perl -MDBD::SQLite -e 1`-style probe per runtime-loaded module. No new invariant IDs; the `INV-D006` + `INV-T001` rule text is unchanged. See [docs/plans/active/from-scratch-setup-protections/](../plans/active/from-scratch-setup-protections/) for the protections plan.

**v1.14 (2026-05-20)** — **adds `INV-R002`** (Never Cache a Degenerate Result) and **`INV-D008`** (Copy-Stage for DooD-Spawning Pipelines). Both surfaced during the 11 smoke iterations (v7–v17) that followed the path-crossing-discipline plan's close-out: v15 hit `ZeroMatchesError` because Tier 2's bcftools cache held 0 records from an earlier degenerate run (every subsequent iteration inherited the empty cache; the eventual symptom was 4 layers downstream from the root cause), and v14 hit `plink2: Failed to open high-LD-regions-hg38-GRCh38.txt` because nextflow's default symlink-staging dereferenced to a parent-container-only path. INV-R002 closes the silent-degenerate-cache class; INV-D008 closes the symlink-into-DooD-sibling class. See [docs/plans/active/prs-runtime-hardening/](../plans/active/prs-runtime-hardening/) for the iteration ledger.

**v1.13 (2026-05-19)** — **tightens `INV-D006`** and **adds `INV-D007`** (Shim Seam Singularity). The Phase 5 real-data smoke against `MPNRGLQ2K.cram` surfaced four distinct gaps the v1.12 discipline didn't catch: a stale smoke-driver `docker run` bypass, a Python 3.11/3.13 dev/prod skew, three sub-bugs in the Phase 1 shim (docker socket not mounted, user/socket-group mismatch, auto-DooD case-statement scoped to `$1 $2` only), and most importantly a fourth path-crossing layer the original three-layer model missed: the factory accepted canonical-mount paths (`/mnt/genomeclaw/...`) even though those are container-only and cannot be resolved by host-daemon-spawned siblings. INV-D006 now requires host-form paths (from `GENOMECLAW_<SUB>_DIR` env vars the shim publishes); INV-D007 promotes "the host shim is the canonical seam for DooD-spawning subcommands" with a discovery test forbidding bespoke `docker run` in `bin/`. See [docs/plans/active/path-crossing-discipline/phases/phase-6.md](../plans/active/path-crossing-discipline/phases/phase-6.md).

**v1.12 (2026-05-19)** — adds `INV-D005` (Identical-Path Bind Mounts for Sibling Containers), `INV-D006` (DooD-Safe Path Annotation), and introduces the new **`INV-T` category** (Tool Integration) with `INV-T001` (External-Tool Conventions Captured as Typed Wrappers). The three invariants close the path-crossing discipline gap that produced six Phase-5 smoke failures (the prs-input-coverage-fill plan's v1–v6) by capturing the contract at three layers: the shim's mount semantics (D005), the typed wrapper boundary (D006), and the tool-version contract (T001). See [docs/plans/active/path-crossing-discipline/](../plans/active/path-crossing-discipline/) and the source report at [docs/reports/path-crossing-discipline.md](../reports/path-crossing-discipline.md).

**v1.11 (2026-05-17)** — adds `INV-A003` (Agent-Curated Compute Provenance) and revises `INV-C001` to v1.7 with the **PRS-decline pattern** as a peer to the existing hard-genes decline. The PRS-decline pattern (four criteria: top-decile RR < ~1.5×; no independent replication; ancestry-calibration failure for this user; no biologically-grounded polygenic basis) is the methodological gate that prevents the agent from computing confident-looking percentiles for traits with no meaningful evidence base. `INV-A003` covers agent-triggered host-side compute more broadly: choice rationale + alternatives considered must be persisted both as a column on the derived-store row and as a memory note; the decline pattern is documented in the agent system prompt with the two-named-reasons rule. Both changes ride on the MVP Q8 v1.6 amendment (agent-driven PRS computation replaces the fixed-three-trait static panel; see [docs/reports/agent-driven-prs-computation.md](../reports/agent-driven-prs-computation.md)).

**v1.10 (2026-05-15)** — revises `INV-A002` to v1.7: clarifies that the synthesis-reasoning floor is the **model's ceiling**, not the literal string `"max"`. OpenClaw validates the `thinking` parameter per-model + silently rejects unsupported values. For the canonical default model `openai/gpt-5.5` the ceiling is `xhigh` (the supported set is `off, minimal, low, medium, high, xhigh`); `max` is rejected. Slices 1-4 of the agent-research-and-synthesis plan baked `max` and the gate fell through. Slice 5 fixes the bake to `xhigh` + adds a per-model validation gate. See [docs/plans/active/agent-research-and-synthesis/work-notes.md](../plans/completed/agent-research-and-synthesis/work-notes.md).

**v1.9 (2026-05-15)** — revises `INV-P001` to v1.7: distinguishes **native OpenAI `web_search`** (part of the agent provider's egress envelope; on by default when the agent is OpenAI) from **managed `web_search` providers** (Brave / Tavily / etc.; a separate named egress destination; opt-in). Confirms `web_fetch` remains a third named egress destination outside the OpenAI Responses API contract and ships disabled. The sandbox image's baked config matches: `tools.web.search.enabled: true` + no `tools.web.search.provider` pinned + `tools.web.fetch.enabled: false`. See [docs/plans/active/agent-research-and-synthesis/](../plans/active/agent-research-and-synthesis/).

**v1.8 (2026-05-15)** — adds `INV-A` (Agent Cognition & Memory) category with `INV-A001` (Memory Provenance) + `INV-A002` (Synthesis Reasoning Floor); revises `INV-C001` v1.6 to replace `reference/curated_notes/` with the agent-memory + reasoned-research pattern; clarifies `INV-P001` for the third user-configured named egress destination (web search / managed research). See [docs/plans/active/agent-research-and-synthesis/](../plans/active/agent-research-and-synthesis/).

If a rule is not in this document, it is not yet a project invariant. Convert hard rules into invariants here before treating them as enforceable.

---

## How to Use This Document

- **Plans** must enumerate applicable invariants in their **Critical Invariants to Respect** section, citing them by ID.
- **Phase plans** must list which invariants are *verified by tests* in that phase.
- **New invariants** are proposed in a development plan and promoted into this document only after the corresponding tests are merged.
- **Pull requests / reviews** that touch sensitive surfaces should cite the relevant `INV-xxx` so trade-offs are explicit.
- **Subagents** in `.claude/agents/` cite the invariants they are responsible for protecting.

---

## Invariant ID Convention

`INV-<CATEGORY><NUMBER>` where category is one of:

| Prefix | Category | Description |
|--------|----------|-------------|
| `INV-D` | Data & Source Artifact Integrity | Source-of-truth handling, raw file protection |
| `INV-E` | Evidence & Traceability | Citations, provenance of assistant claims |
| `INV-P` | Privacy & Sensitivity Boundaries | Local-first defaults, egress controls, secret separation |
| `INV-R` | Rebuildability & Provenance | Deterministic rebuilds, schema/tool versioning |
| `INV-C` | Communication & Clinical Boundary | Research vs. clinical framing, uncertainty handling |
| `INV-A` | Agent Cognition & Memory | Reasoning effort floors, memory note provenance, research-and-synthesis discipline |
| `INV-T` | Tool Integration | External-tool wrapper conventions, version pinning, contract probes |

Numbers are assigned in order of introduction within a category and never reused.

---

## INV-D001: Raw Genomic Files Are Source-of-Truth Artifacts

**Rule**: Source genomic artifacts (FASTQ, BAM, CRAM, VCF, gVCF, reference indexes, downloaded annotation datasets) are read-only by convention and must never be mutated in place.

**Requirements**:
- Pipelines write derived outputs to separate locations (e.g., `/mnt/genomeclaw/derived/<run-id>/`).
- Source paths are referenced, not modified — tools that would rewrite a source file (e.g., in-place sort, in-place index rebuild) must instead emit to a derived path.
- Reference and annotation downloads are versioned by URL or checksum, not overwritten.
- Any modification to a source-shaped file in `/mnt/genomeclaw/raw/` or `/mnt/genomeclaw/reference/` is treated as a bug.

**Where it applies**:
- All ingest, normalization, and annotation code under `packages/toolkit/src/genomeclaw_toolkit/prep/`.
- Any host-side tool that accepts paths under `/mnt/genomeclaw/raw/` or `/mnt/genomeclaw/reference/`.
- Any code path in `packages/toolkit/` that resolves source artifact paths.

**How to verify**:
- Pipeline tests assert source file content hash / mtime is unchanged after a run.
- File-system permissions: raw directories are mounted read-only at the OS layer; CI replicates this.
- Lint check forbids known mutating CLI flags against source paths.

---

## INV-D002: Raw Genomic Artifacts Are Host-Side Only

**Rule**: Raw genomic source files (FASTQ, BAM/CRAM, VCF, gVCF) and their immediate normalized intermediates must be processed exclusively by **host-side** code. They must never enter the OpenShell sandbox or any agent-reachable runtime.

**Requirements**:
- The agent-facing OpenShell sandbox has **no filesystem path** to `/mnt/genomeclaw/raw/` or to any other location holding raw artifacts.
- The host-side pipeline (`genomeclaw` and equivalents) runs as ordinary host processes, outside any NemoClaw / OpenShell sandbox.
- The sandbox accesses only the *derived* store, and only through a host-side HTTP service that exposes minimum-sufficient queries (governed by `INV-P002`).
- Bioinformatics tooling (`samtools`, `bcftools`, `bgzip`, `tabix`, `bedtools`, `SnpEff`, `SnpSift`, `cyvcf2`, `pysam`, `PharmCAT`, etc.) is installed only on the host, never in the sandbox image.

**Where it applies**:
- Host installation of the bioinformatics CLI (`packages/toolkit/`).
- The GenomeClaw sandbox `Dockerfile` (`packages/nemoclaw-plugin/sandbox/Dockerfile`) — must not COPY or RUN against `data/raw/` or any genomic source binary.
- The OpenShell network policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`) — whitelists only the host service endpoint(s), never a generic file-server endpoint that would expose raw artifacts.

**How to verify**:
- A test asserting the built sandbox image does not contain bioinformatics tool binaries on PATH (`samtools`, `bcftools`, `bgzip`, `SnpEff.jar`, etc.).
- A test asserting the OpenShell policy preset for GenomeClaw exposes only the agreed host service endpoint, not a generic file-server endpoint.
- A test asserting the host service refuses to serve raw byte ranges from `/mnt/genomeclaw/raw/`.

---

## INV-D003: Heavy Scratch Is Separated From Authoritative Outputs

**Rule**: Pipeline intermediates of meaningful size (anything > 1 GB) write to a scratch mount that is structurally distinct from the authoritative derived store. The scratch mount can be wiped without breaking derived; a mid-run crash on scratch can never produce a half-written artifact under derived. Originally proposed as "block-attached scratch, not virtiofs" — that framing was a Phase-2 implementation hypothesis that became unimplementable on colima 0.9.1; the underlying separation principle survives the pivot.

**Requirements**:
- Orchestrators (`ingest`, `normalize`, `annotate`, `materialize`, and any future CRAM→VCF / coverage / PRS step) write multi-GB intermediates to `/mnt/genomeclaw/scratch` (host-side: `<drive>/genomeclaw/_scratch/`), never to `/mnt/genomeclaw/derived`.
- Per-step shards are allocated via `shard_scratch(step, run_id, *, shard, base)` (a context manager): `<scratch>/<step>/<run-id>/<shard>/`. Cleanup runs on `__exit__`, even on exception, so zombie scratch dirs cannot accumulate.
- Final artifact promotion goes through `atomic_promote(src, dst)`: copy + fsync(file) + within-FS rename + fsync(parent dir). The destination directory under `derived/` never observes a partially-written file.
- Pre-flight assertions (`assert_derived_writable`, `assert_scratch_writable`) run at every orchestrator entry — a missing or read-only scratch mount is a typed `PreflightError` with a `genomeclaw host setup` hint.
- The setup orchestrator creates both mounts on the canonical layout; the container shim binds both at every container entry.

**Where it applies**:
- All orchestrators under `packages/toolkit/src/genomeclaw_toolkit/prep/` that emit large intermediates.
- The scratch-primitives library `packages/toolkit/src/genomeclaw_toolkit/prep/scratch.py` (`shard_scratch`, `atomic_promote`).
- The pre-flight assertion library `packages/toolkit/src/genomeclaw_toolkit/prep/preflight.py`.
- The setup orchestrator under `packages/toolkit/src/genomeclaw_toolkit/prep/setup/`.
- The host-side container shim `bin/genomeclaw`.

**How to verify**:
- `shard_scratch` tests assert per-step purge on success and on exception — no zombie scratch dirs.
- `atomic_promote` tests assert crash-safety: an interrupted promotion leaves `derived/` byte-identical; the orphaned `.tmp` lives on scratch and is harmless.
- Setup tests (`test_setup_execute.py`) assert the post-state layout contains all four canonical subdirs (`raw`, `reference`, `derived`, `_scratch`).
- Pre-flight tests assert each canonical mount-shape failure raises a typed exception with a fixable message.
- Doctor (`genomeclaw host doctor`) host-side existence + write probes for `derived/` and `_scratch/` give the user a single command to confirm the structural separation is intact.
- A scratch-discipline integration test observes write targets during a real `annotate` run and asserts every > 1 GB target is under `/mnt/genomeclaw/scratch`, none under `/mnt/genomeclaw/derived`. (Replaces the originally-proposed static lint rule, which couldn't reliably distinguish "final artifact" from "heavy scratch" — both write to disk, both are large.)

---

## INV-D004: Destructive Operations Require Explicit Confirmation

**Rule**: Any CLI command that mutates host state outside `derived/` (reformats a disk, ejects a drive, modifies colima/lima state, alters the canonical mount layout) requires one of two deliberate consents before it executes: an explicit `--yes` flag on the command line, or an interactive TTY where the user types an operation-specific phrase (the typed-confirmation pattern). Without either, the command refuses with exit code 2 (usage error) and an error envelope naming both ways forward.

**Requirements**:
- Destructive commands invoke `genomeclaw_toolkit._cli.confirm.require_destructive_confirmation()` (or equivalent gate) before any irreversible action.
- The typed-confirmation phrase is operation-specific (e.g., `REFORMAT GENOMECLAW DRIVE` for `host setup --force-reset`; the drive's mount-point basename for `host eject`). Generic yes/no prompts are not sufficient — the typed-phrase pattern is preferred because it prevents thoughtless `y\n` muscle-memory.
- Non-TTY invocation without `--yes` always refuses. This protects scripts and CI from accidental destructive flows.
- The confirmation gate is independent of other safety bypass flags (e.g., `host eject --force` bypasses the in-flight-pipeline check but does **not** imply confirmation; the user must pass `--yes --force` together).
- The error envelope on refusal names both routes forward (`--yes` and the typed phrase) in `suggested_actions` so the user / agent can pick the appropriate one.

**Where it applies**:
- `genomeclaw host setup --force-reset` (the destructive drive-reformat path).
- `genomeclaw host eject`.
- Any future command that mutates host state outside `derived/` (e.g., a hypothetical `host reset` or `host wipe-cache`).
- The `_cli/confirm.py` helper is the single seam for this invariant; new commands gain enforcement by calling it.

**How to verify**:
- Per-command refusal tests (`test_cli_host_setup_confirmation.py`, `test_cli_host_eject_confirmation.py`) cover both refusal paths: non-TTY without `--yes` → exit 2, and TTY with wrong-phrase → exit 2.
- Per-command accept tests cover both consent paths: `--yes` on non-TTY → proceeds, and typed-phrase on TTY → proceeds.
- Integration tests assert that `--force` (the pipeline-safety bypass) is independent of `--yes` — passing `--force` alone on non-TTY still refuses.
- The error envelope's `suggested_actions` is asserted to include both routes forward in the refusal-path tests.

---

## INV-D005: Identical-Path Bind Mounts for Sibling Containers

**Rule**: When a process inside a container will spawn sibling containers via Docker-out-of-Docker (DooD), every host path that may flow into a sibling's mount argument must be bind-mounted into the parent container at the **identical absolute path** as on the host. The canonical `/mnt/genomeclaw/...` mount convention is allowed **in addition to** (not instead of) the identical-path overlay.

**Requirements**:
- Any container that mounts `/var/run/docker.sock` (the DooD signal) must use identical-path bind mounts for every host directory referenced by paths it will pass to `docker run -v`.
- Code that constructs `docker run -v` arg strings inside a container must produce paths that are valid on the host filesystem — i.e., paths under an identical-path-mounted dir.
- The host shim auto-detects which subcommand groups spawn DooD siblings and sets `GENOMECLAW_DOOD=1` for them; the gate is per-subcommand so non-DooD subcommands don't pay the extra mount.
- The shim publishes the deployment's canonical roots through the `GENOMECLAW_HOST_ROOTS` env var so the inside-container factory (see `INV-D006`) can recognise them as sibling-mountable prefixes.

**Where it applies**:
- The host shim ([bin/genomeclaw](../../bin/genomeclaw)) for any subcommand that may spawn siblings (currently: `pipeline prs-compute`; future: any other Nextflow-based or DooD-spawning subcommand).
- Future host shims for other Nextflow-based tools (e.g., nf-core/sarek).

**How to verify**:
- [packages/toolkit/tests/integration/test_shim_identical_path_mounts.py](../../packages/toolkit/tests/integration/test_shim_identical_path_mounts.py) asserts the overlay mount exists when `GENOMECLAW_DOOD=1` and is absent when unset; also asserts the `GENOMECLAW_HOST_ROOTS` env-var threading.
- [packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py](../../packages/toolkit/tests/invariants/test_invD005_identical_path_mounts.py) walks the shim's docker invocation for a DooD subcommand and asserts every host path that may flow to a sibling is mounted at its identical absolute path.
- Runtime guard: `DooDPathError` (from `INV-D006`) fires when a code path about to call `docker run -v <host>:<container>` detects that `<host>` is not visible on the host filesystem.

---

## INV-D006: DooD-Safe Path Annotation

**Rule** *(v1.13)*: Any wrapper function that writes a path into a downstream tool's invocation **whose execution context is sibling-containers via DooD** must mark its path-typed parameters with a `SiblingMountablePath` annotation (a validated `Path` subclass). Construction goes through `as_sibling_mountable(path)`, which accepts ONLY host-form paths (under a `GENOMECLAW_HOST_ROOTS` prefix the shim publishes) and rejects canonical-mount paths (`/mnt/genomeclaw/<sub>/...`) with a translated hint naming the host-form equivalent.

**Requirements**:
- Wrappers that prepare inputs for Nextflow / pgsc_calc / similar accept `SiblingMountablePath` for those inputs, not bare `Path`.
- The orchestrator's "write merged VCF here" decision is constrained at the type level to choose a `SiblingMountablePath` location (`shard_scratch(...)` when rooted at the canonical scratch mount; `work_dir` is one), not a container-local scratch path (`ephemeral_scratch_base()` returns bare `Path` and is documented as **NOT sibling-mountable** in its docstring).
- The `as_sibling_mountable(path)` factory raises `DooDPathError` with a fixable message when the path is under a non-host-visible location (e.g., `/tmp/genomeclaw-scratch/...`).
- *(v1.13 tightening)* Canonical-mount paths (`/mnt/genomeclaw/<sub>/...`) are explicitly REJECTED. Reason: those paths exist only inside the toolkit container; DooD siblings spawned by the host daemon cannot resolve them against the host filesystem. The factory's error message translates the rejected path to its host-form equivalent using the matching `GENOMECLAW_<SUB>_DIR` env var (which the shim publishes for DooD subcommands).
- The shim publishes four per-subdir env vars (`GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`, `GENOMECLAW_SCRATCH_DIR`) plus the colon-list `GENOMECLAW_HOST_ROOTS`. Together they let the factory accept host-form paths and translate canonical-mount mistakes.

**Where it applies**:
- `compute_prs_with_coverage_fill` (the bug from smoke v3 lived here).
- `_write_pgsc_calc_samplesheet` and any future samplesheet writer that records host paths for sibling consumption.
- `_build_pgsc_calc_argv`, `compute_pgs`, and any future orchestrator that stages inputs for a Nextflow pipeline.
- `ephemeral_scratch_base()` is the negative case — its return type stays bare `Path` and its docstring is the authoritative warning.

**How to verify**:
- [packages/toolkit/tests/unit/test_sibling_mountable_path.py](../../packages/toolkit/tests/unit/test_sibling_mountable_path.py) covers factory accept/reject + `DooDPathError` surface + the ephemeral-scratch rejection (smoke v3 reproducer).
- [packages/toolkit/tests/unit/test_factory_rejects_canonical_mount.py](../../packages/toolkit/tests/unit/test_factory_rejects_canonical_mount.py) *(v1.13)* — canonical-mount paths under each of the four subdirs raise `DooDPathError` with the translated host-form path + the matching env var name in the message.
- [packages/toolkit/tests/integration/test_shim_publishes_per_subdir_env.py](../../packages/toolkit/tests/integration/test_shim_publishes_per_subdir_env.py) *(v1.13)* — the shim's DooD env block threads all four `GENOMECLAW_<SUB>_DIR` env vars; non-DooD subcommands don't.
- [packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py](../../packages/toolkit/tests/integration/test_compute_prs_rejects_non_sibling_path.py) asserts the orchestrator raises before any bcftools / pgsc_calc subprocess runs.
- [packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py](../../packages/toolkit/tests/invariants/test_invD006_dood_safe_path_annotation.py) walks the DooD-bound wrappers (parametrized over `_write_pgsc_calc_samplesheet`, `_build_pgsc_calc_argv`, `compute_pgs`, `compute_prs_with_coverage_fill`) and asserts the canonical path-typed parameters annotate `SiblingMountablePath`.
- [packages/toolkit/tests/invariants/test_invD006_shim_dood_scan_exhaustive.py](../../packages/toolkit/tests/invariants/test_invD006_shim_dood_scan_exhaustive.py) *(v1.15)* — meta-invariant covering the shim-side propagation surface: every pipeline subcommand whose wrapper imports `as_sibling_mountable` from `prep._paths` MUST appear in `bin/genomeclaw`'s `_dood_scan_args()` regex list. Without this, a bare invocation runs in non-DooD mode → empty `GENOMECLAW_HOST_ROOTS` → the in-container `as_sibling_mountable` rejects every path with a confusing error. Surfaced during MVP Phase 7 close session 1 (`pgs-compute` missing from the scan list).
- [packages/toolkit/tests/integration/test_prod_python_smoke.py](../../packages/toolkit/tests/integration/test_prod_python_smoke.py) *(v1.13)* — the rejection works in the toolkit image's Python 3.11 (closes the dev/prod skew gap that Phase 5 surfaced).

---

## INV-D007: Shim Seam Singularity

**Rule** *(v1.13)*: The host shim ([bin/genomeclaw](../../bin/genomeclaw)) is the canonical seam for invoking toolkit subcommands. Scripts and drivers that need to invoke a DooD-spawning subcommand MUST go through the shim. Bespoke `docker run` invocations that duplicate shim logic are prohibited; their drift from the shim's behaviour is exactly what surfaced as the seven Phase 5 smoke failures (`bin/genomeclaw-prs-smoke`'s pre-Phase-1 bypass survived the discipline plan because the plan's scope listed wrappers, not scripts, as migration targets).

**Requirements**:
- Scripts under `bin/` MUST invoke the toolkit through the shim (`bin/genomeclaw <subcommand>`). Bespoke `docker run` invocations of `genomeclaw/toolkit:*` are forbidden.
- The shim is the single seam where: mount layout (`raw`/`reference`/`derived`/`_scratch`), DooD detection + auto-`GENOMECLAW_DOOD=1` (per INV-D005), identical-path overlay, per-subdir env-var threading (per INV-D006 v1.13), docker socket mount, and `--user 0:0` default for DooD subcommands are all decided. Scripts that reimplement any of these silently drift when the shim evolves.
- When a script genuinely needs a one-off invocation (e.g., one-time setup that doesn't fit any current subcommand), the canonical answer is: add a CLI subcommand. The interim shape — bespoke `docker run` — is not a long-term resting state.
- The discipline test walks `bin/` and flags any `docker run` string outside `bin/genomeclaw` itself or an explicit allow-list (`_ALLOWED_BESPOKE_DOCKER_RUN`, empty by design).

**Where it applies**:
- Every executable script under [bin/](../../bin/). Today: `bin/genomeclaw` (the shim itself, exempt) and `bin/genomeclaw-prs-smoke` (the Phase 5 smoke driver — migrated in Phase 6 to use the shim exclusively).
- Future drivers / CI scripts that need to invoke the toolkit (gated by the discovery test).

**How to verify**:
- [packages/toolkit/tests/invariants/test_invD007_seam_singularity.py](../../packages/toolkit/tests/invariants/test_invD007_seam_singularity.py) — discovery test that walks `bin/` (excluding the shim itself and any allow-listed scripts) and asserts no `docker run` strings appear.
- [packages/toolkit/tests/integration/test_smoke_driver_canonical.py](../../packages/toolkit/tests/integration/test_smoke_driver_canonical.py) — driver-specific regression covering the canonical migration (no bespoke docker run; DooD-bound flags use host-form variables).

---

## INV-D008: Copy-Stage for DooD-Spawning Pipelines

**Rule** *(v1.14)*: Pipelines that spawn DooD sibling containers (currently only ``pgsc_calc`` via Nextflow) MUST stage tool inputs into per-task work-dirs via COPY, not symlink. The default symlink staging creates symlinks pointing at parent-container-only paths (e.g., ``/opt/nextflow/assets/...``) that don't exist in the sibling's namespace; the sibling dereferences the symlink and fails to open the file. For Nextflow this is ``process.stageInMode = 'copy'``; the equivalent setting applies to other DooD-spawning pipeline runners.

**Requirements**:
- The wrapper for any DooD-spawning pipeline writes the staging configuration into the work-dir (or passes it via the tool's config-file flag) BEFORE invoking the tool.
- The configuration MUST be effective for ALL of the pipeline's tasks (not just the ones we currently know about). A whole-pipeline default like Nextflow's ``process { stageInMode = 'copy' }`` covers future pipeline-revision changes.
- New DooD-spawning pipeline wrappers added under ``packages/toolkit/src/genomeclaw_toolkit/prep/`` MUST include this configuration as part of their first commit.

**Where it applies**:
- [packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/pgs.py) — ``_write_pgsc_calc_nextflow_config`` materialises ``nextflow.config`` with ``process.stageInMode = 'copy'``; ``_build_pgsc_calc_argv`` passes ``-c <config>`` to nextflow.
- Future wrappers for other DooD-spawning pipelines (e.g. nf-core/sarek, hypothetical custom pipelines) inherit this rule.

**How to verify**:
- [packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py::test_compute_pgs_writes_nextflow_config_redirecting_tmpdir](../../packages/toolkit/tests/integration/test_pgsc_calc_wrapper.py) asserts the generated ``nextflow.config`` contains ``stageInMode = 'copy'`` AND the argv carries ``-c <config>``.
- Smoke-time signal: a regression to symlink-staging surfaces as the canonical Phase-7-v14 error: ``plink2: Failed to open <staged-asset>.txt: No such file or directory``.

---

## INV-E001: Assistant Claims Must Be Traceable to Evidence

**Rule**: Every user-facing biomedical statement in a report, finding, or assistant response must be linkable to one of: a normalized observation, an annotation record, a literature/evidence record, or an explicitly labeled heuristic.

**Requirements**:
- The output schema for findings, reports, and assistant turns includes an `evidence` field (or equivalent) referencing source records.
- Generated text without an evidence link is labeled as `speculation` or `heuristic` and visually/structurally distinguished from evidence-backed text.
- Citations preserve enough identity to re-fetch the source (variant ID, ClinVar ID, gnomAD frequency record, paper identifier, internal record ID).
- Removing an evidence record invalidates dependent findings on the next rebuild — they must not silently persist.

**Where it applies**:
- Host service finding/report endpoints in `packages/toolkit/src/genomeclaw_toolkit/service/`.
- Plugin tool handlers in `packages/nemoclaw-plugin/src/` that forward findings to the agent.
- Finding/evidence/provenance schemas in `packages/toolkit/src/genomeclaw_toolkit/schemas/`.
- Any code path that emits an interpretation to the user.

**How to verify**:
- Snapshot tests for host service responses that fail if an evidence-bearing block lacks a citation.
- Unit tests on the finding schema rejecting an interpretation without an evidence reference.
- Integration tests confirming that deleting an evidence record causes dependent findings to be marked stale on the next rebuild.

---

## INV-P001: Privacy Is the Default Operating Mode

**Rule**: User genomic data and derived phenotype-linked data are sensitive by default. They must not leave the local trusted environment **except** via a small set of **user-configured, named egress destinations**, each governed by `INV-P002`'s minimal-sufficient-payload contract.

**Named egress destinations** *(v1.7, revised 2026-05-15 to distinguish native-vs-managed `web_search` after the option-B decision)*:

1. **The NemoClaw agent provider** (e.g., OpenAI gpt-5.5, Claude Opus, Gemini) — active when the user has configured the agent. Receives tool-call results (minimal-sufficient per `INV-P002`). **Native provider-side tools** are part of this destination's envelope, not separate destinations — see (1a).

   - **(1a) Native `web_search` on the agent provider's API** *(v1.7, new)*. When the agent provider is OpenAI Responses-API and `tools.web.search.enabled: true` + `tools.web.search.provider` unset, OpenAI's hosted `web_search` tool auto-activates. Per the OpenClaw web-search docs, this is "provider-owned behavior in the bundled OpenAI plugin and only applies to native OpenAI API traffic." Topic-term queries from this path go to OpenAI under the agent's existing API key — the **same** egress destination the user already configured for the agent. It is **not** a new named egress destination; the topic-only payload rule still applies. The sandbox image ships with this on by default so the agent's research-and-synthesis protocol works out-of-the-box for the canonical OpenAI deployment.

2. **The host-side `genomeclaw-service`** — the local HTTP surface the plugin reads (`127.0.0.1:8643` on the host machine). Not technically remote, but listed for clarity.

3. **Managed `web_search` provider** (Brave, Tavily, Perplexity, Exa, Firecrawl, DuckDuckGo, SearXNG, etc., per the OpenClaw web-search provider list) — **off by default**; the user opts in by running `openclaw config set tools.web.search.provider <name>` + supplying the provider's API key. Receives **topic-term queries only** — **never user-identifying genomic payload**. When a managed provider is pinned, OpenClaw routes `web_search` calls there instead of through OpenAI's native path. Adding a managed provider IS the act of adding a new named egress destination.

4. **`web_fetch`** *(v1.7, explicitly enumerated as a separate destination)* — issues outbound HTTP from the sandbox to arbitrary URLs. **NOT** part of the OpenAI Responses API contract. Off by default in the sandbox image (`tools.web.fetch.enabled: false`). The user enables it explicitly with `openclaw config set tools.web.fetch.enabled true` when their workflow requires it. Each fetched URL is itself effectively a target endpoint.

Other remote integrations (alternative annotators, telemetry, crash reporting) are off by default and gated behind explicit per-operation opt-in.

**Requirements**:
- **Genomic source files** (FASTQ, BAM/CRAM, VCF/gVCF) **never leave the device**, regardless of any configured egress destination.
- The `web_search` query payload contains only topic-term strings; it never contains the user's variants, rsids, genotypes, gene-by-gene exploration history, or sample identifiers. **This binds both the native OpenAI path AND any managed provider path** — the native-vs-managed distinction does not relax the topic-only rule.
- Native OpenAI `web_search` is treated as part of the agent-provider envelope only because the user has already consented to OpenAI egress by configuring the OpenAI provider. If the user switches to a non-OpenAI agent provider (Claude, Gemini), they have not consented to OpenAI search and the native-OpenAI path does not apply.
- Secrets, tokens, and credentials live outside `data/` and are never committed.
- Logs, traces, and crash dumps must not contain raw variants, sample identifiers, or phenotype-linked content unless the user enabled verbose local logging.
- Redaction or summarization happens *before* any payload constructed for an external service is materialized.

**Where it applies**:
- Network-egress code paths in `packages/toolkit/` (host service HTTP layer, fetcher modules) and `packages/nemoclaw-plugin/src/` (plugin's outbound `fetch` calls).
- The OpenShell network policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`) — the runtime egress floor.
- Logging, telemetry, and error reporting in both packages.
- Host config and environment-variable handling; secrets must live outside `data/` and outside any committed config.
- Any caching layer that might serialize sensitive content.
- The sandbox image's baked `openclaw.json` — the v1.7 contract is enforced at build time, not at runtime configuration.

**How to verify**:
- **Default-config baked-image gate**: `test_invP001_sandbox_web_egress_contract` (in [packages/toolkit/tests/invariants/](../../packages/toolkit/tests/invariants/test_invP001_sandbox_web_egress_contract.py)) reads the built sandbox image's `/sandbox/.openclaw/openclaw.json` and asserts (a) `tools.web.search.enabled: true`, (b) `tools.web.search.provider` absent, (c) `tools.web.fetch.enabled: false`. A regression flipping any of these gets caught at the `needs_sandbox` sweep on every image rebuild.
- **Default-config behavioural test**: with the v1.7 sandbox config, simulate a research-and-synthesis turn and assert (a) the `web_search` query payload contains only topic-term strings, (b) it does not contain any rsid, gene symbol from the user's variants, sample id, or genotype string, (c) the response is routed back into the agent envelope via the same minimal-sufficient surface. **No `web_fetch` call happens in the default config.**
- **Managed-provider opt-in test**: with a pinned managed `tools.web.search.provider`, assert (a) the request egresses to the managed provider's API host (not OpenAI), (b) the topic-only payload rule still binds.
- **`web_fetch` opt-in test**: with `tools.web.fetch.enabled: true`, assert the request egresses only to the URL the agent named + the URL itself does not contain user-identifying data.
- Unit tests on redaction utilities.
- Lint check / type guard around an `egress_safe(...)` boundary type so unredacted payloads cannot reach external clients.
- **Agent-prompt content gate**: `test_invP001_system_prompt_teaches_native_vs_managed_web_search` + `test_invP001_system_prompt_documents_web_fetch_disabled_default` (in [packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py](../../packages/toolkit/tests/invariants/test_agent_system_prompt_contract.py)) verify the prompt teaches the v1.7 distinction so the agent reasons correctly about its tool surface.

---

## INV-P002: Agent Egress Is a Named, Minimal-Sufficient Boundary

**Rule**: GenomeClaw is driven by a NemoClaw agent that typically runs on a cloud frontier model (e.g., OpenAI gpt-5.4, Claude Opus, Gemini). That model is a **named, user-configured egress destination** — not a free-for-all. Tool outputs that may travel to the agent must contain only the information the agent needs to answer the current request.

**Requirements**:
- The configured agent provider is named in user config and is changed only by deliberate user action.
- Tool outputs default to **minimal-sufficient** summaries: scoped findings, scoped variants, scoped evidence — not bulk dumps.
- Bulk transfer modes (e.g., shipping a whole VCF, a full annotation table, or unfiltered cohort data to the agent context) are gated behind explicit per-operation opt-in flags.
- Each plugin tool declares an `output_class` of `summary` or `bulk`. The default for any new tool is `summary`. Agent prompt scaffolding respects the classification.
- The agent boundary is the *only* remote destination for tool-call results by default. Other remote APIs are governed by `INV-P001`.

**Runtime enforcement layers** (all must hold):

1. **Host service shaping** — the host-side `genomeclaw-service` returns minimal-sufficient JSON over HTTP; bulk endpoints are distinct routes.
2. **Plugin output shaping** — the in-sandbox plugin re-shapes responses before returning to the agent, never widening fields the host service redacted.
3. **OpenShell L7 proxy + SSRF guard** — the GenomeClaw policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`) must declare both an explicit `endpoints` allow list and an `allowed_ips:` allowlist for the RFC 1918 ranges that `host.openshell.internal` resolves to (`10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`). Without `allowed_ips:`, OpenShell's SSRF guard rejects requests with `ssrf_denied: blocked: internal address`, even if the policy block exists.

**Where it applies**:
- Host service route definitions and response shapes.
- The plugin's command/tool handlers (`packages/nemoclaw-plugin/src/**`).
- The GenomeClaw OpenShell policy preset (`packages/nemoclaw-plugin/policy-preset.yaml`).
- Any future capability manifest emitted by the plugin.

**How to verify** (three coverage layers, all must hold):

*Layer 1 — Static shape*:
- Tests asserting default-mode tool outputs exclude bulk fields (full VCF rows, full annotation tables, unfiltered evidence dumps).
- Tests asserting every registered plugin tool has an `output_class` tag.
- Tests asserting the policy preset includes the `allowed_ips:` allowlist and limits HTTP methods/paths to the read-only host-service surface (`packages/toolkit/tests/invariants/test_invP002_policy_preset_shape.py`).
- Snapshot tests on representative tool outputs to catch accidental field bloat over time.

*Layer 2 — Implicit runtime*:
- The 4 live LLM tests under `packages/toolkit/tests/_live_smoke/` exercise the policy on every allowed call (any policy-side regression breaking the allowed surface would fail them).
- Default-config integration tests asserting no outbound call goes anywhere other than the configured agent endpoint and the configured host service.

*Layer 3 — Explicit runtime negative case* (ssrf-runtime-probe plan):
- `packages/toolkit/tests/invariants/test_invP002_ssrf_runtime_probe.py` — `@pytest.mark.live_ssrf_probe @pytest.mark.live_llm`-gated. Spawns the sandbox, docker-cp's the freshly built nemoclaw-plugin with the TEST-ONLY `genomeclaw_ssrf_probe_batch` tool active (`GENOMECLAW_ENABLE_SSRF_PROBE=1`), invokes the agent with no args, parses the per-probe classification array. ALLOW probe asserts HTTP 200 from the policy-permitted endpoint; 4 DENY probes assert un-allowlisted destinations are unreachable. One LLM call per run (~$0.10–0.50), ~98 s wall.

---

## INV-R001: Derived Assistant Stores Must Stay Rebuildable

**Rule**: Any derived store (DuckDB tables, SQLite/GenomicSQLite indexes, annotation caches, vector indexes, chunked literature corpora, materialized report inputs) must be reproducible from the recorded source inputs and pipeline configuration, modulo declared non-determinism.

**Requirements**:
- Each pipeline step records: input identity (path + content hash or version), tool name, tool version, parameters, schema version, run timestamp.
- Re-running a step against the same inputs and tools yields byte-equivalent outputs unless non-determinism is declared and documented.
- Schema versions are explicit; migrations are scripted and idempotent.
- Hand-edited derived data is forbidden unless explicitly marked and justified inline.

**Where it applies**:
- All host-side pipeline code under `packages/toolkit/src/genomeclaw_toolkit/prep/`.
- Derived store schema and migration code under `packages/toolkit/src/genomeclaw_toolkit/service/` (or equivalent).
- Caching layers that persist between sessions.

**How to verify**:
- Determinism tests: run a pipeline twice on a fixture, compare outputs byte-for-byte.
- Provenance tests: every derived row has the required provenance columns populated (`source_path`, `source_sha256`, `tool`, `tool_version`, `params_json`, `schema_version`, `created_at`).
- Schema-version tests: the host service refuses to load a derived store whose schema version is missing or unknown.

---

## INV-R002: Never Cache a Degenerate Result

**Rule** *(v1.14)*: Any wrapper that caches a derived artifact MUST validate that the artifact is non-degenerate before promoting it to the cache. A degenerate result (e.g., a bgzipped VCF with zero non-header records, a TSV with zero data rows, a JSON with the meaningful payload empty) MUST raise a typed error AND MUST NOT be cached. The error message MUST enumerate the most-likely root causes so the next debugger can resolve them fast.

**Requirements**:
- Wrappers that produce derived artifacts via external tools (bcftools, plink2, etc.) MUST count the result's meaningful payload AFTER the tool exits but BEFORE `atomic_promote` (or equivalent commit-to-cache step).
- The degeneracy check is wrapper-specific: count of variant records for VCFs, count of data rows for TSVs, count of populated fields for JSON summaries. The wrapper defines what "meaningful payload" means for its artifact.
- Degenerate results MUST raise a typed error of the wrapper's pre-existing error class (e.g., `BcftoolsError`). The error message MUST name 3+ plausible root causes (chromosome-prefix mismatch, reference-build mismatch, empty input, no coverage at target sites, etc.) AND MUST end with "NOT caching empty result; resolve the underlying issue and rerun." — surfacing the failure loudly + steering the debugger.
- This rule applies to all wrappers in `packages/toolkit/src/genomeclaw_toolkit/prep/` going forward. Existing wrappers gain the guard incrementally as their callers discover the failure mode.

**Where it applies**:
- [packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py](../../packages/toolkit/src/genomeclaw_toolkit/prep/coverage_fill.py) — `_force_genotype_tier1` + `_force_genotype_tier2` use `_count_vcf_records()` to refuse 0-record promotion.
- Future bcftools/plink2/similar wrappers inherit this rule on first commit.
- `INV-R001` is strengthened indirectly — without `INV-R002`, a degenerate cache poisons all subsequent rebuilds against the same key.

**How to verify**:
- [packages/toolkit/tests/integration/test_prs_coverage_fill_integration.py::test_force_genotype_tier1_refuses_to_cache_empty_vcf](../../packages/toolkit/tests/integration/test_prs_coverage_fill_integration.py) — fake bcftools writes header-only VCF; asserts `BcftoolsError` raised + `output_vcf` does NOT exist on disk + error message enumerates the root-cause categories.
- [packages/toolkit/tests/integration/test_prs_coverage_fill_tier2.py::test_force_genotype_tier2_refuses_to_cache_empty_vcf](../../packages/toolkit/tests/integration/test_prs_coverage_fill_tier2.py) — same shape; also asserts the error names the input PGS site count for context.
- Smoke-time signal: the canonical surfacing is `tier2 force-genotype produced ZERO output records despite N input PGS sites against <CRAM>. The bcftools pipe exited cleanly but produced a header-only VCF. Common causes: ... NOT caching empty result; resolve the underlying issue and rerun.` (Phase-7 smoke v17, 2026-05-20).

**Not to be confused with — low-but-valid downstream match rates**: `INV-R002` is the guard against caching a **degenerate** artifact (0 records, structurally empty payload). It is NOT a guard against *expected* downstream low-but-valid match rates on healthy artifacts. The canonical example is `pgsc_calc`'s match rate between a non-imputed single-sample WGS and a dense imputed PGS Catalog scoring file (e.g. snpnet / LASSO models): the empirical ceiling on this input class is **45–65%** per [docs/reports/prs-real-data-smoke-research-findings.md](../reports/prs-real-data-smoke-research-findings.md). A 47%-match-rate Tier 2 VCF that yields a 47% pgsc_calc match is a healthy artifact that pgsc_calc's *own* `--min_overlap 0.75` default rejects — the mitigation is to lower `--min_overlap` to ~`0.5` for non-imputed single-sample WGS (persisted in `pgs_scores.params_json` per `INV-R001`), not to widen `INV-R002`'s degenerate-cache definition. The two failure modes look superficially similar (both surface as "no usable PRS row") but have different root causes and different mitigations.

---

## INV-C001: Separate Clinical Advice from Lifestyle and Research Assistance

**Rule**: GenomeClaw is positioned as a research, exploration, and lifestyle/wellbeing assistant — *not* a clinical decision-maker. The boundary is not "no opinions"; it is **clinical advice (diagnosis, prescription, dose, treatment changes) is out, lifestyle and wellbeing optimization is in**. Both surfaces must be evidence-cited, but they have different framing rules.

**Requirements**:
- Findings carry a structural `category` field. Four canonical categories drive `INV-C001`:
  - **`clinical-actionable`** (e.g., ACMG SF list pathogenic, PharmCAT actionable PGx haplotypes) — carries a `clinical_escalation` marker; agent recommends clinical confirmation; agent does not issue diagnostic, prescriptive, or dose-changing advice.
  - **`clinical-non-actionable`** (variants in clinical-relevance genes that are benign / VUS / unlikely-pathogenic) — no escalation marker; agent reports cleanly without alarmism and without unprompted clinician-deferral.
  - **`lifestyle`** (e.g., caffeine metabolism via `CYP1A2`, lactase persistence via `LCT`, muscle-fiber composition via `ACTN3`, circadian preference, alcohol metabolism via `ALDH2`/`ADH1B`) — no escalation marker; agent may give **direct lifestyle advice with calibrated evidence framing**; clinician-deferral is *not* the default response. Recommendations are framed as falsifiable experiments rather than guidelines.
  - **`mixed`** (a finding with both a lifestyle dimension and a clinical-actionability angle) — carries both lifestyle framing and an escalation marker; the agent disambiguates the two angles in its response.
- Lifestyle advice must still cite evidence and **calibrate uncertainty explicitly**. The evidence base for lifestyle findings is generally weaker than for ClinVar-grade pathogenicity calls; the agent acknowledges this when relevant. Lifestyle findings include an `evidence_quality` field (e.g., `meta-analysis`, `replicated-rct`, `observational`, `mechanistic-only`) distinct from ClinVar's review-status stars.
- **PRS-decline pattern** *(v1.7, added 2026-05-17 per MVP Q8 v1.6 + [agent-driven PRS report](../reports/agent-driven-prs-computation.md))*: when the agent considers computing a PRS for a trait, it must first evaluate whether the PRS literature is mature enough to produce a meaningful result. **Decline gracefully** with two named reasons if any of the following hold: (a) top-decile relative risk < ~1.5× (discriminative power too low for the percentile to materially shift the user's prior); (b) no independent replication of the best available scorefile (single-lab PRSs in the published literature have repeatedly failed to replicate externally); (c) ancestry-calibration failure for this user (the `calibration_warning` would dominate the meaningful signal); (d) no biologically-grounded polygenic basis (heritability-only scorefiles produce percentiles that have no honest per-individual interpretation). The decline is *reasoned* — the agent runs the research step first; *not* hardcoded refusal. Peer to the existing hard-genes decline pattern (PER3 / CLOCK / VNTRs / paralogs / MT genome). Enforced by `INV-A003` (provenance) + the prompt-content gate + a `live_llm` decline behavioural test.
- **Lifestyle calibration via agent research-and-synthesis** *(v1.6; supersedes v1.5; per [agent-research-and-synthesis spec](../plans/active/agent-research-and-synthesis/spec.md))*: lifestyle findings cite evidence references of two new agent-side kinds — `memory:<file>#<anchor>` (a prior research synthesis the agent persisted to its workspace memory) and `web:<url>` (a current online source the agent retrieved during this turn). The agent composes lifestyle responses by reasoned research over (the model's training knowledge + current online sources via OpenClaw `web_search` + prior memory notes via `memory_search`), grounded in the user's specific variant call from the GenomeClaw host service. The synthesis happens at the maximum reasoning level the configured model supports — see `INV-A002`. The pre-authored `reference/curated_notes/<gene>.md` mechanism from v1.5 is **retired**.
- **Memory-validation requirement on every `memory:<id>` citation** *(v1.6, added 2026-05-15 to close a hallucination-propagation gap)*: when a synthesis turn cites a `memory:<id>` reference, the agent must apply reasoning at the `INV-A002` synthesis-turn floor to **validate** the cited memory note. Validation has three independent checks:
  1. **Conclusion ↔ source grounding** — does the memory note's stated conclusion actually follow from the primary sources the memory note cites? Or has the conclusion overreached its sources during prior synthesis?
  2. **Source quality** — are the cited primary sources sufficient (peer-reviewed, multi-source, free of obvious bias)? Has critical context been omitted?
  3. **Freshness** — is the memory note past its recorded freshness date, AND is the topic one where evidence has plausibly evolved (e.g., monthly-updated databases like ClinVar; ongoing meta-analyses)?

  **If any check fails, the agent must update the memory note** via the supersession mechanism in `INV-A001` (write a corrected/superseding note recording the gap found + the corrected synthesis + the validation reasoning) **before composing the user-facing reply**. The reply must reflect the updated synthesis, not the original. The reply must also cite the updated memory note, and the validation step must appear in the execution trace + the memory provenance record.

  Failure modes prevented: (a) "stale-memory amplification" — the agent recalls an old synthesis that was right when written but is now out of date, and treats it as currently authoritative; (b) "self-grounding" — the agent's prior conclusion that overreached its sources becomes the citation for the next session's prose, with the original source weakness now invisible; (c) "memory-of-memory chains" — repeated paraphrase across sessions drifts the synthesis away from the primary sources, with each link looking grounded but the chain rooted in a fabrication.

- Clinical findings use research/educational framing, never diagnostic phrasing.
- Uncertainty is expressed structurally (categorical confidence levels and evidence-quality fields), not buried in prose.
- Default report copy and prompt templates are reviewed for **over-claim *and* over-deferral** before merge — punting every lifestyle question to a clinician is its own failure mode.

**Where it applies**:
- Agent-rendered prose for report-shaped responses (assembled by the agent from `/v1/findings` + `/v1/health` plus its training; there is no host-service `/v1/report` endpoint in v0). Snapshot tests on the agent's rendered output against fixture conversations are the verification surface.
- Plugin tool descriptions (the `description` strings registered via `registerTool` in `packages/nemoclaw-plugin/src/`) — these flow into the agent's tool catalog and shape its framing.
- The finding schema in `packages/toolkit/src/genomeclaw_toolkit/schemas/` where `category`, `clinical_escalation`, and `evidence_quality` are structural fields.
- Agent prompt templates rendered by the user's NemoClaw stack (out-of-repo but in-scope for review).
- The agent's workspace memory under `~/.openclaw/workspace/<agent>/{MEMORY.md, memory/YYYY-MM-DD.md}` *(v1.6; per [agent-research-and-synthesis spec](../plans/active/agent-research-and-synthesis/spec.md))*. Memory notes are user-facing-copy as they accumulate; they live in the sandbox (not the repo) and are inspectable by the user via the agent's `memory_get` tool or by reading the workspace directly. Privacy-safety review applies to the **agent system prompt** that shapes the research-and-synthesis protocol, not to every individual memory note.

**How to verify**:
- Lint / snapshot tests on host service report responses and on plugin tool descriptions asserting absence of disallowed phrases for `clinical-actionable` findings (configurable list).
- Schema tests asserting that `clinical_escalation` is set on findings whose category is `clinical-actionable` and unset on `lifestyle` and `clinical-non-actionable`.
- Schema tests asserting `evidence_quality` is populated on `lifestyle` findings.
- Snapshot tests on lifestyle-category responses asserting that the response provides **direct guidance plus an evidence-quality caveat** — i.e., it does not punt to a clinician for what is a lifestyle question.
- Snapshot tests on lifestyle-category responses asserting that the agent cites at least one `memory:<id>` or `web:<url>` evidence reference, and that the response prose tracks the cited synthesis — no new claims introduced by the agent that aren't grounded in the cited sources. Failure modes: agent over-extending its memory ("the note doesn't say that"), agent fabricating a citation, agent over-deferring on a lifestyle question. *(v1.6)*
- **Memory-validation snapshot test** *(v1.6, added 2026-05-15)*: a fixture introduces a deliberately-weak memory note (conclusion overreaches its cited sources, OR the memory cites only other memory notes, OR the freshness date is past). When the agent recalls this note via `memory_search` and would otherwise cite it, the synthesis turn must (a) surface the gap in its reasoning trace (visible in `executionTrace`), (b) write a corrected / superseding memory note via the `INV-A001` supersession mechanism, (c) cite the updated note (not the original) in its reply, (d) reflect the corrected synthesis in the user-facing prose. Failure mode prevented: hallucination propagation across sessions via uncritically-recalled prior synthesis.
- **Memory-grounding audit** *(v1.6, added 2026-05-15)*: after N accumulated sessions, every memory note's chain of citations terminates in at least one primary source — a web URL, PubMed ID, ClinVar ID, gene-database identifier, or other external authority. A memory note that cites only other memory notes is malformed per `INV-A001` and would have been rejected at write time; this audit confirms the chain stays clean over time.
- Manual privacy-safety-reviewer agent pass on the agent system prompt + memory-note schema before merge.

---

## INV-C002: CLI Output Contract Stability

**Rule**: Every `genomeclaw` subcommand provides a `--json` mode whose stdout payload conforms to a versioned schema. The schema version travels with every payload as the `cli_output_schema_version` field. Stdout in `--json` mode is reserved for the structured result (single envelope, or NDJSON event stream); stderr is for progress, log, and diagnostic output. Adding new optional fields is additive (no version bump); renaming or removing fields requires a major-version bump and a deprecation cycle.

**Requirements**:
- Every command's `--json` output is a JSON object (or NDJSON stream of objects) carrying `cli_output_schema_version` at the envelope level.
- Two output modes coexist:
  - **One-shot envelope** for short commands: a single line `{"cli_output_schema_version": "1.0", "command": "...", "payload": {...}}` on stdout.
  - **NDJSON stream** for long-running commands: a first-line envelope `{"cli_output_schema_version": "1.0", "command": "...", "stream": true}` followed by one event object per line. The `"stream": true` field is the discriminator agents use to branch on stream-vs-envelope.
- Stdout is reserved for the structured result in `--json` mode. Rich-progress output, logs, and diagnostic prints go to stderr. The fetcher (`prep/fetch.py`) and any orchestrator that grew a `progress_callback` parameter suppress their legacy stdout prints when the callback is wired — the callback is the canonical surface for user-facing output.
- Trailing error envelopes (when a command fails mid-stream) go to **stderr** so they don't corrupt the stream. The `_cli.output.stdout_already_consumed` sentinel tracks whether a payload has been emitted; the exception boundary routes the error envelope accordingly.
- The per-command JSON shapes are documented in [docs/reference/cli-output-schemas.md](cli-output-schemas.md) with worked examples for both happy and failure paths.
- Field additions don't bump the version. Field renames or removals require a major version bump (`1.0` → `2.0`) and a deprecation cycle where both shapes are accepted.

**Where it applies**:
- `src/genomeclaw_toolkit/_cli/` — every command-handler module, the `emit()` dispatcher in `_cli/output.py`, the envelope writers in `commands/pipeline.py`, `commands/refs.py`, `commands/host.py`.
- `docs/reference/cli-output-schemas.md` — the single source of truth for the documented schemas + worked examples per command.
- The schema-version constant `CLI_OUTPUT_SCHEMA_VERSION = "1.0"` in `_cli/types/envelope.py`.

**How to verify**:
- Per-command JSON-shape tests assert `cli_output_schema_version == "1.0"` on every envelope.
- `test_cli_pipeline_events.py::test_pipeline_run_no_stdout_pollution_outside_events` asserts every stdout line in NDJSON mode parses as JSON — no legacy print pollution.
- `test_cli_refs_fetch.py::test_refs_fetch_json_emits_ndjson_event_stream` asserts the first-line envelope shape (`"stream": true`).
- The `stdout_already_consumed` sentinel is exercised by every test that emits a payload then triggers an error — the error envelope must appear on stderr, not stdout.
- `cli-output-schemas.md` documents the contract; PR reviewers cite this invariant when reviewing changes to the per-command schemas.

---

## INV-A001: Agent Memory Provenance

**Rule** *(v1.8; per [agent-research-and-synthesis spec](../plans/active/agent-research-and-synthesis/spec.md))*: when the agent persists a research synthesis to its workspace memory, the note must record enough provenance for a future agent session (or the user inspecting the workspace) to understand *what was learned, from where, at what reasoning level, and with what freshness*.

**Requirements**:
- Every memory note written by the research-and-synthesis pattern carries:
  - the verbatim user question that triggered the research,
  - the tool calls executed in the research phase (with each result's source attribution — URLs for web sources, ids for variant-keyed evidence, prior-note anchors for `memory:<id>` references),
  - the reasoning effort levels used for the **research phase** and the **synthesis phase** separately,
  - the synthesis verdict + a confidence note (e.g., *moderate evidence; heterogeneous studies*; *high-confidence call from variant + ClinVar review status*),
  - a **freshness as of** date so future sessions can decide whether to re-research vs. recall,
  - **at least one primary source citation** *(added 2026-05-15)* — a web URL, PubMed ID, ClinVar ID, PharmGKB id, gene-database identifier, or other external authority. A memory note that cites only other memory notes is malformed and the note-writer step must reject it.
- **Supersession mechanism** *(added 2026-05-15 in tandem with `INV-C001` v1.6 memory-validation)*: a memory note may be **superseded** by a later note when validation (per `INV-C001` v1.6) surfaces a gap in the original. The superseding note records: a `supersedes: <prior-anchor>` field, the specific gap found in the prior note (e.g., *"conclusion that habituation makes ADORA2A effect negligible overreaches the cited 2019 paper which only showed partial habituation"*), and the corrected synthesis with updated reasoning. The prior note is not deleted — the supersession trail stays auditable.
- Memory notes for conversational / recall turns (no health interpretation) are exempt from the structured-provenance requirement — they're free-form Markdown.
- The memory-note skeleton + the agent system prompt that produces it are reviewed by the privacy-safety-reviewer agent before any change.

**Where it applies**:
- Agent system prompt (out-of-repo for now; tracked under [agent-research-and-synthesis Phase 2](../plans/active/agent-research-and-synthesis/phases/phase-1.md) and the follow-up phase-2.md).
- Memory notes in the agent workspace: `~/.openclaw/workspace/<agent>/memory/YYYY-MM-DD.md` and `MEMORY.md`.

**How to verify**:
- A test fixture validates the memory-note skeleton parses correctly when the agent fills it in (deterministic format check).
- **Primary-source-required gate** *(added 2026-05-15)*: a fixture memory note that cites only other memory notes (no external URL / PubMed / ClinVar / etc.) is rejected by the note-writer step. The note never lands on disk; the agent must run fresh research instead.
- **Supersession-trail gate** *(added 2026-05-15)*: a fixture deliberately-weak memory note is followed by a synthesis turn that should validate it (per `INV-C001` v1.6). The test asserts the produced supersession note carries the `supersedes:` field, the gap description, and the corrected synthesis; the original note remains on disk for the audit trail.
- Live-LLM snapshot tests over Stories 4 / 9 / 10 assert the memory note produced by the synthesis turn contains: the question, tool-call list, reasoning levels for both phases, source citations including at least one primary source, a freshness date.
- Manual audit: `cat ~/.openclaw/workspace/<agent>/MEMORY.md` should be human-readable and contain no surprising claims that aren't provenanced. Every note's primary-source citation chain should resolve.

---

## INV-A002: Synthesis Reasoning Floor

**Rule** *(v1.8; per [agent-research-and-synthesis spec](../plans/active/agent-research-and-synthesis/spec.md))*: any **user-facing health-interpretation turn** must be composed at the maximum reasoning level the configured model supports. This is the bioinformatician-in-healthcare turn; lowering the reasoning effort here trades correctness for cost in a domain where the cost of an incorrect-sounding fluent answer is higher than the token cost of max-effort reasoning.

**Definition — health-interpretation turn**:
- Any reply that **interprets** the user's genomic data (variant, finding, gene-level summary, PRS) for clinical or lifestyle meaning, OR
- Any reply that gives guidance the user might plausibly act on (medication choice, dose, lifestyle change, lab follow-up, clinician consultation).

**Definition — non-interpretation turn (exempt from floor)**:
- Recall confirmation ("what did we talk about last week?", "remind me of the caffeine plan").
- Scheduling / commitments / conversational pacing.
- Casual back-and-forth that doesn't reach into the user's genomic data interpretively.

**Requirements**:
- The agent self-classifies the turn type via its system prompt; the configured model honours the agent's per-message reasoning effort request via OpenClaw's `thinking` parameter.
- For health-interpretation turns, the reasoning effort is the maximum the configured model supports — see the per-model ceiling table below. The string `"max"` is **NOT a universal alias** for the model's ceiling; OpenClaw's `thinking` parameter validates per-model and rejects values the model doesn't accept.
- For non-interpretation turns, the reasoning effort is the agent's default (typically `adaptive` or `medium`); the floor does not over-apply.
- The reasoning level used is recorded in the memory note's provenance per `INV-A001`.

**Per-model thinking-level ceilings** *(v1.7, slice-5 finding 2026-05-15; OpenClaw v2026.4.24)*:

| Model | Supported levels | Ceiling = synthesis floor |
|---|---|---|
| `openai/gpt-5.5` | `off, minimal, low, medium, high, xhigh` | **`xhigh`** |
| `openai/o3-class` (o3, o4, codex-series) | adds `max` | `max` |

The bug this gate closes: agent-research-and-synthesis slices 1-4 baked `agents.defaults.thinkingDefault: max` for an `openai/gpt-5.5` deployment. At config-set time, the schema accepts the value. At per-call dispatch time, OpenClaw's validation rejects it with *"Thinking level `max` is not supported for openai/gpt-5.5. Use one of: off, minimal, low, medium, high, xhigh."* — the call silently falls through to the model's default (probably `medium`). The synthesis floor was never actually enforced per-call for the four months of behavioural smokes — the smokes still produced calibrated answers because the model's *default* reasoning was good enough on the canonical questions, masking the bug. Slice 5 fixes the bake to `xhigh` (gpt-5.5's actual ceiling) and adds a baked-config gate that rejects `thinkingDefault` values the configured `agents.defaults.model` doesn't accept.

When the user switches default model (e.g. to `openai/o3` for higher-stakes deployments), **both** `agents.defaults.model` AND `agents.defaults.thinkingDefault` must be updated together; the per-model gate enforces consistency.

**Where it applies**:
- The agent's system prompt + per-message `thinking` overrides.
- OpenClaw's baked sandbox config (`agents.defaults.thinkingDefault`) — must be the configured model's ceiling.
- Live-LLM snapshot tests over Stories 4 / 9 / 10.

**How to verify**:
- **Static baked-config gate**: [test_sandbox_thinking_default_supported.py](../../packages/toolkit/tests/invariants/test_sandbox_thinking_default_supported.py) (`needs_sandbox`) reads the baked openclaw.json + asserts `thinkingDefault` is (a) in the supported set for the configured model, and (b) at the model's ceiling. A future Dockerfile flip back to `max` (or a default-model switch without a floor update) gets caught.
- **Behavioural per-call probe**: openclaw `--thinking <level>` validates the per-call level at dispatch time + errors loudly if invalid. A live-test probe at any unsupported level (e.g. `--thinking max` on gpt-5.5) surfaces `"Thinking level X is not supported for Y. Use one of: …"` — the message itself documents the valid set per model.
- Live-LLM snapshot tests (Stories 4 / 9 / 10) verify the agent produces calibrated answers; under the v1.7 fix they run at the model's actual ceiling.
- A negative gate: a manual probe asking *"what should I have for breakfast tomorrow?"* (non-interpretation, casual) should not elevate to the ceiling; if it does, the agent system prompt's classification rule is over-applying.

---

## INV-A003: Agent-Curated Compute Provenance

**Rule** *(v1.11; per [agent-driven PRS report](../reports/agent-driven-prs-computation.md) + MVP Q8 v1.6)*: when the agent triggers a host-side compute on behalf of the user (e.g., PRS computation via `pgsc_calc`), the agent's **choice + rationale + alternatives considered** must be persisted alongside the compute output, both as a column on the derived-store row and as a memory note. The compute path must respect a per-compute-class **decline pattern** documented in the agent system prompt with the two-named-reasons rule.

**Why this exists** — `INV-A003` extends `INV-A001` (Agent Memory Provenance) from research-and-synthesis turns to *agent-triggered compute* turns. The agent-driven PRS architecture (replacing the v1.5 fixed-three-trait static panel per Q8 v1.6) lets the agent decide which PGS Catalog scorefile to compute for the user's question; without `INV-A003`, that editorial decision becomes invisible — the user sees a percentile but not why this scorefile, what alternatives were considered, or whether the agent declined other candidates. The provenance lands at two layers (the row column for machine-readable audit; the memory note for the agent's own reasoning trail).

**Requirements**:
- **Choice rationale column**: every row in a derived-store table populated by an agent-triggered compute carries an `agent_choice_rationale` (TEXT) column + an `agent_requested_for_question` (TEXT) column. The first records the agent's reasoning for picking this specific compute target (PGS Catalog ID, scorefile, etc.) including alternatives considered + why this one over them. The second records the verbatim user question that triggered the compute. Both columns are not-null; an empty string is invalid.
- **Memory-note pairing**: every agent-triggered compute is also recorded as a memory note per `INV-A001`'s schema (Question, Tool calls, Sources retrieved, Synthesis, Calibration, Recommendation framing, Citations, Freshness, ≥1 primary source). The memory note's title or body cross-references the derived-store row's primary key so the audit trail is bidirectional.
- **Decline-pattern enforcement**: the agent system prompt documents a decline pattern for each compute class, with **two named reasons** required when declining (modelled on the existing hard-genes decline pattern under `INV-C001`). The decline criteria for PRS specifically are in `INV-C001` v1.7. Future compute classes (e.g., agent-triggered re-annotation, agent-triggered ancestry inference) define their own decline criteria as they land.
- **Decline-note persistence**: when the agent declines a compute, the decline + the two named reasons are themselves recorded as a memory note (same `INV-A001` schema, with `compute_decision: decline` as a section). Future sessions hit the decline note before re-deciding, with INV-C001 v1.6 memory-validation re-checking whether the literature has matured enough to reverse the decline.
- **Supersession on compute**: when a later compute supersedes an earlier one (e.g., a newer PGS scorefile lands; the agent recomputes), the prior row's `superseded_by` field points at the newer row's primary key (mirrors `INV-A001`'s supersession pattern for memory notes). The prior row stays on disk for the audit trail.

**Where it applies**:
- Derived-store wrappers under `packages/toolkit/src/genomeclaw_toolkit/prep/` that emit rows triggered by agent compute requests (currently: `pgs.py` for PRS; future: any other agent-triggered compute).
- The host-service compute-request endpoint + status-polling endpoint (currently planned: `POST /v1/pgs/compute` + `GET /v1/pgs/compute/{task_id}`; pattern generalizes).
- The agent system prompt at [packages/nemoclaw-plugin/sandbox/agent-system-prompt.md](../../packages/nemoclaw-plugin/sandbox/agent-system-prompt.md) — decline criteria + the two-named-reasons rule.
- The memory-note schema at [packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py](../../packages/toolkit/src/genomeclaw_toolkit/memory/note_validator.py) — extension to handle `compute_decision` notes.

**How to verify**:
- **Schema column gate**: a unit test on the `pgs_scores` table (and any future agent-triggered-compute table) asserts the two provenance columns exist + are NOT NULL + are populated with non-empty strings on every row.
- **Memory-note cross-reference gate**: an integration test asserts that for every row in `pgs_scores`, a memory note exists referencing the row's primary key + recording the agent's choice rationale.
- **Decline-pattern prompt-content gate**: a test on the agent system prompt asserts the PRS-decline pattern enumerates the four criteria + the two-named-reasons rule + at least one worked-example trait.
- **Behavioural `live_llm` decline gate**: ask the agent about a known-immature trait (e.g. creativity PRS); assert (a) the agent does NOT invoke `genomeclaw_pgs_compute`, (b) the reply names two specific decline reasons, (c) the trace shows the agent did the research step before declining (reasoned decline, not hardcoded refusal), (d) a decline-shaped memory note lands on disk with `compute_decision: decline`.
- **Behavioural `live_llm` compute-with-provenance gate**: a successful PRS compute (e.g. Story 10 CAD) produces a `pgs_scores` row whose `agent_choice_rationale` enumerates ≥1 alternative scorefile + states why this one over them; the matching memory note is well-formed per `INV-A001`.
- **Supersession gate**: pre-stage an outdated PRS computed row + ask a question that triggers re-evaluation; assert the agent (a) writes a new row with `superseded_by` set on the prior, (b) writes a memory note recording the gap, (c) the prior row stays on disk for audit.

---

## INV-T001: External-Tool Conventions Captured as Typed Wrappers

**Rule**: When GenomeClaw integrates an external bioinformatics tool (pgsc_calc, plink2, bcftools, VEP, etc.), the tool's path / argv / samplesheet / file-format conventions are captured in a typed `<Tool>Conventions` frozen dataclass at the wrapper layer. Each field's value is cited to upstream documentation OR to an empirical probe against the tool's actual binary; wrapper tests assert against the captured conventions, never against hand-rolled hardcoded strings.

**Requirements**:
- One `<Tool>Conventions` dataclass per integrated tool, located alongside the wrapper (`packages/toolkit/src/genomeclaw_toolkit/prep/_<tool>_conventions.py`).
- The dataclass is `frozen=True` and carries `verified_against_version: str` matching the pin in `_versions.py` (verified by a unit test that fails if the pin moves without the conventions being re-verified).
- Each field has a docstring with a citation: either a URL to upstream docs OR a path to a captured `tools/<tool>/probe-output.txt` file showing the empirical behaviour.
- Wrapper tests construct the tool's argv / samplesheet using the conventions dataclass and assert the wrapper consumes the field, not a hardcoded literal (parametrize via `dataclasses.replace` with a stubbed field value and assert the emitted argv carries the stubbed value).
- New tool integrations: write the conventions dataclass FIRST, then the wrapper.
- Existing wrappers: backfill the conventions dataclass during the next breaking change to the tool (e.g., when bumping the tool's pin in `_versions.py`). The discovery test enumerates the backfill queue (warn-only) so it stays visible.

**Where it applies**:
- Every external-tool wrapper in [packages/toolkit/src/genomeclaw_toolkit/prep/](../../packages/toolkit/src/genomeclaw_toolkit/prep/). The strict-tools roster is `pgsc_calc` (Phase-2 deliverable), `cyrius` (MVP Phase 6 Slice D — added 2026-05-22), and `pharmcat` (MVP Phase 6 Slice D' — added 2026-05-22). The warn-only backfill queue is `bcftools`, `bgzip`, `mosdepth`, `vcfanno`, `vep`.
- The `INV-T` category is created for this rule; future tool-integration invariants land under this prefix.

**How to verify**:
- [packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py](../../packages/toolkit/tests/invariants/test_invT001_tool_conventions_exist.py) — strict-tools test asserts every wrapper in `_STRICT_TOOLS` has a `<Tool>Conventions` frozen dataclass with `verified_against_version` populated; warn-tools test enumerates the backfill queue (currently bcftools, bgzip, mosdepth, vcfanno, vep).
- [packages/toolkit/tests/unit/test_pgsc_calc_conventions.py](../../packages/toolkit/tests/unit/test_pgsc_calc_conventions.py) — `pgsc_calc`'s dataclass field values match the recorded [tools/pgsc_calc/probe-output.txt](../../tools/pgsc_calc/probe-output.txt) baseline; wrapper-generated argv matches [tools/pgsc_calc/golden-argv.txt](../../tools/pgsc_calc/golden-argv.txt); regression-guard tests for known breakage modes (smoke v2 `--target` → `--input`; smoke v6 `path_prefix` suffix).
- [packages/toolkit/tests/integration/test_vep_loftee_plugin.py](../../packages/toolkit/tests/integration/test_vep_loftee_plugin.py) *(v1.15)* — VEP plugin-load coverage: extends the existing `perl -c LoF.pm` + `perl -c gerp_dist.pl` syntax checks with explicit `perl -M<runtime-loaded-module>` probes (`Bio::Perl`, `Bio::DB::BigFile`, `DBD::SQLite`). LoF.pm loads its SQLite driver at plugin-instantiate time via `install_driver`; the missing `DBD::SQLite` regression surfaced during MVP Phase 7's canonical real-data smoke (silent NULL on every `loftee_lof` column). The `-M` probes catch this class at unit-test time + run in milliseconds.

---

## Promoting a New Invariant

When a development plan proposes a new invariant:

1. The plan's `development-plan.md` includes a `Proposed New Invariants` section listing each candidate with rule + rationale.
2. The implementation lands tests that enforce the proposed rule.
3. After tests are green, this document is updated:
   - Pick the next available number in the appropriate category.
   - Fill in **Rule**, **Requirements**, **Where it applies**, **How to verify**.
   - Increment the **Version** at the top.
   - Update **Last Updated**.
4. The development plan moves to `docs/plans/completed/` with the invariant adoption noted.

If a proposed invariant is rejected, the plan records the rejection and rationale in `work-notes.md`.

---

## Invariant Index

| ID | Title | Category |
|----|-------|----------|
| INV-D001 | Raw Genomic Files Are Source-of-Truth Artifacts | Data |
| INV-D002 | Raw Genomic Artifacts Are Host-Side Only | Data |
| INV-D003 | Heavy Scratch Is Separated From Authoritative Outputs | Data |
| INV-D004 | Destructive Operations Require Explicit Confirmation | Data |
| INV-D005 | Identical-Path Bind Mounts for Sibling Containers | Data |
| INV-D006 | DooD-Safe Path Annotation | Data |
| INV-D007 | Shim Seam Singularity | Data |
| INV-D008 | Copy-Stage for DooD-Spawning Pipelines | Data |
| INV-E001 | Assistant Claims Must Be Traceable to Evidence | Evidence |
| INV-P001 | Privacy Is the Default Operating Mode | Privacy |
| INV-P002 | Agent Egress Is a Named, Minimal-Sufficient Boundary | Privacy |
| INV-R001 | Derived Assistant Stores Must Stay Rebuildable | Rebuildability |
| INV-R002 | Never Cache a Degenerate Result | Rebuildability |
| INV-C001 | Separate Clinical Advice from Lifestyle and Research Assistance | Clinical Boundary |
| INV-C002 | CLI Output Contract Stability | Communication |
| INV-A001 | Agent Memory Provenance | Agent Cognition |
| INV-A002 | Synthesis Reasoning Floor | Agent Cognition |
| INV-A003 | Agent-Curated Compute Provenance | Agent Cognition |
| INV-T001 | External-Tool Conventions Captured as Typed Wrappers | Tool Integration |
