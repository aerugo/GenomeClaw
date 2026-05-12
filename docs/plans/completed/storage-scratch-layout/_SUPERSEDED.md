# Superseded: storage-scratch-layout

**Closed**: 2026-05-09
**Successor**: [cram-scratch-strategy](../cram-scratch-strategy/) (5 phases; shipped 2026-05-09)

## Why superseded

`storage-scratch-layout` framed the four-mount problem as a configuration / env-var-discipline question: tell users how to point `GENOMECLAW_RAW_DIR`, `GENOMECLAW_REF_DIR`, `GENOMECLAW_DERIVED_DIR`, and `GENOMECLAW_WORK_DIR` at sensible host paths, and refuse to start when scratch nests under derived. That was the correct framing for the Phase-4A deliverable.

The actual production workload (CRAM → VCF on a Nebula deliverable, multi-hundreds-of-GB scratch under `pgsc_calc` Nextflow runs) made the env-var path insufficient: users needed an opinionated, destructive, one-shot setup that wiped a target external partition, formatted it APFS, laid out the canonical layout, and handed colima a working `mounts:` block. The cram-scratch-strategy plan absorbed that scope and added:

- A live destructive `genomeclaw-prep setup` orchestrator (Phase 2) with same-disk-source/target safeguards, hardware identity / firmware-safety check, computed-need pre-flight, typed-confirmation prompt, and an audit-log written to `_scratch/setup.log`.
- A pre-flight assertion library (Phase 3) that orchestrators call at every entry — `assert_raw_readonly`, `assert_reference_readonly`, `assert_derived_writable`, `assert_scratch_writable`, plus a `GENOMECLAW_SKIP_PREFLIGHT=1` test escape hatch.
- Pipeline primitives (Phase 4): `shard_scratch(step, run_id, ...)` context manager + `atomic_promote(src, dst)` (copy + fsync file + within-FS rename + fsync parent dir).
- `eject` / `doctor` subcommands (Phase 5).
- The new `INV-D003` (Heavy Scratch Is Separated From Authoritative Outputs) promoted into `docs/reference/INVARIANTS.md` v1.6.

The original `storage-scratch-layout` env-var path remains valid as the manual fallback for non-Sequoia hosts and unusual topologies (documented in `README.md` § Storage planning). It's still the implementation under `bin/genomeclaw-prep` — the cram-scratch-strategy delivered an interactive layer on top of it, not a replacement.

## What this plan contributed before being superseded

- The four-mount taxonomy (`raw/`, `reference/`, `derived/`, `_scratch/`) and per-mount lifecycle table that the cram-scratch-strategy reused without modification.
- The shim-refusal rule "scratch must not nest under derived" → became one of three INV-D003 enforcement layers.
- `~/.colima/default/colima.yaml` mounts-block guidance for macOS Sequoia + colima 0.9.1, including the documented `colima start --mount X:w replaces rather than appends` behavior.

## Pointers for future work

- For storage architecture changes, start from `cram-scratch-strategy/`, not here.
- The `_scratch` rename (was `work/`) lives in this plan; cram-scratch-strategy is consistent with it.
- Linux host support is explicitly deferred from cram-scratch-strategy — when that lands, it may revisit some of this plan's env-var portability framing.
