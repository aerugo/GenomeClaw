# GenomeClaw CLI `--json` output schemas

**Status**: Living document
**Schema version**: 1.0
**Last updated**: 2026-05-12
**Provisional invariant**: `INV-C-cli-output-stability` (see [rich-cli plan](../plans/active/rich-cli/spec.md)).

This document is the **canonical contract** between the GenomeClaw CLI
and its consumers — humans piping `--json` output to `jq`, agents
calling the CLI as a tool surface, and CI scripts asserting on
structured fields.

Every `--json` payload conforms to a versioned envelope:

```json
{
  "cli_output_schema_version": "1.0",
  "command": "<dotted.path>",
  "payload": { ... },           // mutually exclusive with `error`
  "error": { ... }              // populated on non-zero exit
}
```

## Versioning rules

- **Additive changes** (new optional fields, new event types in
  streaming payloads) **do not** bump the version. Consumers must
  tolerate unknown fields.
- **Renames, removals, or semantic changes** require a major bump
  (1.0 → 2.0) and a deprecation cycle (one minor release where both
  versions are emitted via a config flag).
- The version is in every payload — agents can version-check once at
  startup.

## Output discipline

When `--json` is active:

- **stdout** is reserved for the single envelope (one-shot commands)
  or for newline-delimited envelopes (streaming commands).
- **stderr** carries progress, log, and diagnostic output. Never JSON
  unless explicitly documented as a streaming event channel.
- **No banner / header lines** on stdout. The first byte of stdout is
  the opening `{` of the envelope (or, for streaming, the first event).

## Exit-code contract

| Code | Meaning | When |
|---|---|---|
| `0` | success | Operation completed and post-conditions hold. |
| `1` | runtime error | The operation tried and failed. |
| `2` | usage error | Invalid CLI args or flag combination. |
| `3` | precondition error | A required input (file, env, layout) is missing. |
| `4` | data integrity error | A file failed validation (truncated bgzip, schema mismatch). |
| `130` | interrupted | SIGINT (Ctrl+C). |

## Error envelope

When `error` is populated:

```json
{
  "cli_output_schema_version": "1.0",
  "command": "error",
  "error": {
    "error_type": "precondition_error",
    "message": "no CURRENT symlink under /mnt/genomeclaw/derived; run `genomeclaw pipeline ingest` first",
    "details": { "derived_root": "/mnt/genomeclaw/derived" },
    "suggested_actions": [
      "Run `genomeclaw pipeline ingest` to create a derived run.",
      "Or pass --run-dir <path> explicitly."
    ],
    "traceback": null
  }
}
```

`traceback` is `null` unless the user passed `--debug`, in which case
it's an array of Python traceback lines.

---

## Per-command schemas

### `host doctor`

**Phase 1 — published.**

```json
{
  "cli_output_schema_version": "1.0",
  "command": "host.doctor",
  "payload": {
    "checks": [
      {"name": "raw_present", "status": "OK", "message": ""}
    ],
    "setup_log": {
      "found": true,
      "incomplete": false,
      "no_events": false,
      "last_started_at": "2026-05-11T21:48:43Z",
      "last_completed_at": "2026-05-11T21:48:43Z",
      "toolkit_version": "0.0.1",
      "target_partition": "Genome_Work"
    },
    "colima": {
      "installed": true,
      "version": "0.9.1",
      "status": "running"
    },
    "paths": {
      "raw": "/Volumes/Genome_Work/genomeclaw/raw",
      "reference": "/Volumes/Genome_Work/genomeclaw/reference",
      "derived": "/Volumes/Genome_Work/genomeclaw/derived",
      "scratch": "/Volumes/Genome_Work/genomeclaw/_scratch"
    },
    "references": {
      "release_set": "default",
      "sources": [
        {
          "source": "grch38",
          "expected_release": "ncbi-2014",
          "on_disk_release": "ncbi-2014",
          "status": "OK",
          "present_files": ["..."],
          "missing_files": []
        }
      ]
    },
    "raw_sample": {
      "staged": true,
      "sample_id": "MPNRGLQ2K",
      "files": ["MPNRGLQ2K.mm2.sortdup.bqsr.cram", "..."]
    },
    "derived_runs": [
      {
        "run_id": "2026-05-12T06-41-52Z-f121da",
        "sample_id": "MPNRGLQ2K",
        "started_at": "2026-05-12T06:41:52Z",
        "stage": "normalized"
      }
    ]
  }
}
```

**Field stability**: every field above is part of the v1.0 contract.
Adding new fields (e.g. a per-source `last_fetched_at` timestamp) is
additive and won't bump the version.

### `host setup`

**Phase 6 — published.** ``host setup`` emits **two** JSON envelopes
under ``--json``: a "plan" envelope describing what it's about to do,
then a "result" envelope describing what happened. Both share the
``host.setup`` command name + are distinguished by the ``phase`` field.

The destructive ``--force-reset`` path requires either ``--yes`` on
the command line or a typed-confirmation phrase on an interactive
TTY (``REFORMAT GENOMECLAW DRIVE``). Without either, the command
exits with code 2 and emits a standard error envelope to stderr
(after the plan envelope on stdout).

**Worked example** (`--json --yes host setup --force-reset --dry-run --source ... --target-volume Genome_Work`):

```jsonl
{"cli_output_schema_version":"1.0","command":"host.setup","payload":{"phase":"plan","dry_run":true,"force_reset":true,"fetch_all":false,"source":"/tmp/nebula","target_volume":"Genome_Work"}}
{"cli_output_schema_version":"1.0","command":"host.setup","payload":{"phase":"result","exit_code":0}}
```

Field reference:

| Field | Type | Notes |
|-------|------|-------|
| `payload.phase` | `"plan"` \| `"result"` | Envelope discriminator |
| `payload.dry_run` | bool | (plan) ``--dry-run`` flag value |
| `payload.force_reset` | bool | (plan) ``--force-reset`` flag value |
| `payload.fetch_all` | bool | (plan) ``--fetch-all`` flag value |
| `payload.source` | string \| null | (plan) Nebula source path |
| `payload.target_volume` | string \| null | (plan) Target volume name |
| `payload.exit_code` | int | (result) Orchestrator exit code (`0` on success) |

### `host eject`

**Phase 6 — published.** ``host eject`` emits a single result
envelope. Like ``host setup``, the destructive operation requires
either ``--yes`` or an interactive TTY where the user types the
drive's mount-point basename (e.g. ``Genome_Work`` for
``/Volumes/Genome_Work``).

The separate ``--force`` flag bypasses the in-flight-pipeline safety
check — it does **not** imply confirmation. Combining ``--yes
--force`` is the unattended-during-pipeline-run path.

**Worked example** (`--json --yes host eject --drive /Volumes/Genome_Work`):

```json
{
  "cli_output_schema_version": "1.0",
  "command": "host.eject",
  "payload": {
    "drive": "/Volumes/Genome_Work",
    "force_used": false,
    "exit_code": 0
  }
}
```

Field reference:

| Field | Type | Notes |
|-------|------|-------|
| `payload.drive` | string | Mount point that was ejected |
| `payload.force_used` | bool | ``True`` iff ``--force`` was passed |
| `payload.exit_code` | int | ``eject_impl`` return value (`0` on success) |

### `refs list`

**Phase 2 — published.** Read-only release-set classification.

```json
{
  "cli_output_schema_version": "1.0",
  "command": "refs.list",
  "payload": {
    "release_set": "default",
    "reference_root": "/mnt/genomeclaw/reference",
    "sources": [
      {
        "source": "grch38",
        "expected_release": "ncbi-2014",
        "on_disk_release": "ncbi-2014",
        "status": "OK",
        "present_files": ["grch38.fa.gz", "grch38.fa.gz.fai"],
        "missing_files": []
      }
    ]
  }
}
```

`status` ∈ {`"OK"`, `"partial"`, `"missing"`}. Partial means the
release dir exists but some expected files are absent; missing means
the release dir itself isn't on disk.

### `refs verify`

**Phase 2 — published.** Bgzip-EOF integrity sweep across the release set.

```json
{
  "cli_output_schema_version": "1.0",
  "command": "refs.verify",
  "payload": {
    "release_set": "default",
    "reference_root": "/mnt/genomeclaw/reference",
    "files_checked": 26,
    "failures": [
      {"source": "gnomad-exomes", "relpath": "by_chrom/chr6.vcf.bgz", "reason": "truncated"}
    ]
  }
}
```

`reason` ∈ {`"truncated"`, `"missing"`, `"unreadable"`}.
Empty `failures` → exit 0. Any failure → exit 4 (data integrity error).

### `refs info <source>`

**Phase 2 — published.** Single-source per-file detail.

```json
{
  "cli_output_schema_version": "1.0",
  "command": "refs.info",
  "payload": {
    "reference_root": "/mnt/genomeclaw/reference",
    "detail": {
      "source": "clinvar",
      "expected_release": "2026-05-09",
      "on_disk_release": "2026-05-09",
      "status": "OK",
      "present_files": ["clinvar.vcf.gz", "clinvar.vcf.gz.md5", "clinvar.vcf.gz.tbi"],
      "missing_files": [],
      "files": [
        {
          "relpath": "clinvar.vcf.gz",
          "present": true,
          "size_bytes": 191838814,
          "bgzip_ok": true
        }
      ]
    }
  }
}
```

`bgzip_ok` is `null` for non-bgzipped sidecars (`.md5`, `.tbi`, `.fai`, `.gzi`).

### `runs list`

**Phase 2 — published.** Derived-run history (newest first).

```json
{
  "cli_output_schema_version": "1.0",
  "command": "runs.list",
  "payload": {
    "derived_root": "/mnt/genomeclaw/derived",
    "runs": [
      {
        "run_id": "2026-05-12T06-41-52Z-f121da",
        "sample_id": "MPNRGLQ2K",
        "started_at": "2026-05-12T06:41:52Z",
        "stage": "normalized"
      }
    ]
  }
}
```

`stage` ∈ {`"ingested"`, `"normalized"`, `"annotated"`, `"materialized"`, `"unknown"`}.
The `CURRENT` symlink is filtered out (it points at one of the listed runs).

### `runs show <run-id>` / `runs current`

**Phase 2 — published.** Both commands emit the same payload shape.

```json
{
  "cli_output_schema_version": "1.0",
  "command": "runs.show",
  "payload": {
    "detail": {
      "run_id": "2026-05-12T06-41-52Z-f121da",
      "run_dir": "/mnt/genomeclaw/derived/2026-05-12T06-41-52Z-f121da",
      "sample_id": "MPNRGLQ2K",
      "schema_version": "v0.2",
      "created_at": "2026-05-12T06:41:52Z",
      "stage": "normalized",
      "manifest": { /* full manifest.json contents */ },
      "steps": [
        {
          "step": "ingest",
          "tool": "genomeclaw-prep",
          "tool_version": "0.0.1",
          "started_at": "2026-05-12T06:41:53Z",
          "completed_at": "2026-05-12T06:43:01Z",
          "params": {"sample_id": "MPNRGLQ2K"}
        }
      ]
    }
  }
}
```

`runs current` resolves the `CURRENT` symlink and delegates to the
same payload-building path as `runs show`.

**Note on `steps[].tool`**: the value carries whatever was recorded
at run time. Existing runs produced before the rich-cli CLI cutover
carry `"tool": "genomeclaw-prep"` (the legacy entry-point name);
post-cutover runs will carry `"tool": "genomeclaw"`. The field is
informational — `provenance.json` rebuildability (`INV-R001`) doesn't
depend on the literal string, and the per-run-dir value is preserved
so existing runs stay parseable. Agents reading manifests should
accept either value without branching behavior.

### `refs fetch` (single source) / `refs fetch --all`

**Phase 1 — minimal payload, formal schema in Phase 3.**

Phase 1 single-source emits:

```json
{
  "cli_output_schema_version": "1.0",
  "command": "refs.fetch",
  "payload": {
    "source": "clinvar",
    "release": "2026-05-09",
    "path": "/mnt/genomeclaw/reference/clinvar/2026-05-09/clinvar.vcf.gz"
  }
}
```

Phase 3 will add the streaming NDJSON event mode (`{event: "file_start", ...}` etc.) for `--all` runs.

### `pipeline ingest` / `pipeline normalize` / `pipeline annotate` / `pipeline materialize` / `pipeline run`

**Phase 1 — minimal "wrote X" payload; full per-step events in Phase 3.**

```json
{
  "cli_output_schema_version": "1.0",
  "command": "pipeline.ingest",
  "payload": {"run_dir": "/mnt/genomeclaw/derived/2026-05-12T..."}
}
```

### `version` (via `--version`)

**Phase 1 — published.**

```json
{
  "cli_output_schema_version": "1.0",
  "command": "version",
  "payload": {
    "toolkit_version": "0.0.1",
    "image_digest": "sha256:...",
    "git_commit": "abc1234"
  }
}
```

`image_digest` is `null` when running host-native; `git_commit` is
`null` when running from an installed wheel.

### `events.*` — long-running operation progress (NDJSON)

Long-running commands like `refs fetch` (rich-cli Phase 4 — shipped)
and `pipeline run` (rich-cli Phase 5 — pending) emit one JSON object
per line under `--json` mode in place of a single envelope. Each line
is a discriminated event with the structure `{"event": "<type>",
...fields}`. The event types are defined in
[`prep/_events.py`](../../packages/toolkit/src/genomeclaw_toolkit/prep/_events.py).

The dataclass hierarchy shipped in **Phase 3**. The `refs fetch` CLI
wiring shipped in **Phase 4** with the wire shape pinned below; the
`pipeline run` wiring lands in **Phase 5** following the same first-
line-envelope + per-event-line convention.

Discriminator values:

| `event` | Fired by | Fields |
|---------|----------|--------|
| `file_start` | `refs fetch` per file | `source`, `relpath`, `total_bytes\|null` |
| `file_progress` | `refs fetch` per file (periodic) | `source`, `relpath`, `bytes_so_far`, `total_bytes\|null` |
| `file_complete` | `refs fetch` per file | `source`, `relpath`, `bytes_written`, `md5\|null`, `duration_sec` |
| `file_failed` | `refs fetch` per file | `source`, `relpath`, `reason`, `message` |
| `phase_start` | `pipeline run` per stage | `phase` |
| `phase_complete` | `pipeline run` per stage | `phase`, `duration_sec`, `run_dir` |
| `phase_failed` | `pipeline run` per stage | `phase`, `error_type`, `message` |
| `pipeline_complete` | `pipeline run` terminal | `run_dir`, `duration_sec` |

Example NDJSON stream (one line per event):

```jsonl
{"event":"file_start","source":"gnomad-exomes","relpath":"chr22.vcf.bgz","total_bytes":null}
{"event":"file_progress","source":"gnomad-exomes","relpath":"chr22.vcf.bgz","bytes_so_far":67108864,"total_bytes":7340032000}
{"event":"file_complete","source":"gnomad-exomes","relpath":"chr22.vcf.bgz","bytes_written":7340032000,"md5":"abc...","duration_sec":312.4}
```

In NDJSON mode the `cli_output_schema_version` envelope wrapper is
emitted **once** as the first line; every subsequent line is a raw
event. This keeps each event small while still pinning the schema
version. Wire shape confirmed in Phase 4 for `refs fetch`; the same
shape applies to `pipeline run` once Phase 5 ships.

**First-line envelope** (pinned in Phase 4):

```json
{"cli_output_schema_version":"1.0","command":"refs.fetch","stream":true}
```

The `"stream": true` field is the marker that distinguishes a NDJSON
stream from a one-shot envelope — agents should branch on this flag
before consuming the rest of stdout.

**Worked `refs fetch` example** (one ClinVar file):

```jsonl
{"cli_output_schema_version":"1.0","command":"refs.fetch","stream":true}
{"event":"file_start","source":"clinvar","relpath":"clinvar.vcf.gz","total_bytes":null}
{"event":"file_progress","source":"clinvar","relpath":"clinvar.vcf.gz","bytes_so_far":67108864,"total_bytes":180000000}
{"event":"file_complete","source":"clinvar","relpath":"clinvar.vcf.gz","bytes_written":180000000,"md5":"abc123...","duration_sec":12.4}
```

**Worked `pipeline run` example** (rich-cli Phase 5 — all four stages
chained against a single derived run):

```jsonl
{"cli_output_schema_version":"1.0","command":"pipeline.run","stream":true}
{"event":"phase_start","phase":"ingest"}
{"event":"phase_complete","phase":"ingest","duration_sec":71.2,"run_dir":"/derived/2026-05-12T15-04-12Z-abc123"}
{"event":"phase_start","phase":"normalize"}
{"event":"phase_complete","phase":"normalize","duration_sec":38.5,"run_dir":"/derived/2026-05-12T15-04-12Z-abc123"}
{"event":"phase_start","phase":"annotate"}
{"event":"phase_complete","phase":"annotate","duration_sec":612.7,"run_dir":"/derived/2026-05-12T15-04-12Z-abc123"}
{"event":"phase_start","phase":"materialize"}
{"event":"phase_complete","phase":"materialize","duration_sec":24.1,"run_dir":"/derived/2026-05-12T15-04-12Z-abc123"}
{"event":"pipeline_complete","run_dir":"/derived/2026-05-12T15-04-12Z-abc123","duration_sec":746.5}
```

The single-stage commands (`pipeline ingest` / `pipeline normalize` /
`pipeline annotate` / `pipeline materialize`) emit the same envelope
shape with their respective `phase_start` + `phase_complete` event
pair, but **without** a terminal `pipeline_complete` event — only
`pipeline run` aggregates across all four stages.

**Worked failure example** (truncated download surfaces a
`file_failed` event before the command exits with code 4):

```jsonl
{"cli_output_schema_version":"1.0","command":"refs.fetch","stream":true}
{"event":"file_start","source":"gnomad-exomes","relpath":"chr6.vcf.bgz","total_bytes":null}
{"event":"file_failed","source":"gnomad-exomes","relpath":"chr6.vcf.bgz","reason":"incomplete_bgzip","message":"http://...: downloaded 8350000000 bytes but the canonical BGZF EOF marker is absent; treating as truncated"}
```

After a `file_failed` event the command writes a standard error
envelope to **stderr** (not stdout) and exits with the appropriate
exit code (typically `4` for integrity failures). The NDJSON stdout
stream terminates after the failing event.

`reason` values for `file_failed`: one of `"truncated"`,
`"incomplete_bgzip"`, `"stalled"`, `"checksum_mismatch"`. These map to
the fetcher's exception types `TruncatedDownload`, `IncompleteBgzip`,
`DownloadStalled`, `ChecksumMismatch` respectively.

---

## Adding a new command's schema

When a new command lands:

1. Define a Pydantic `BaseModel` for the payload in the command's module
   (e.g. `_cli/commands/<group>.py`).
2. Document the schema in this file under `## Per-command schemas`
   with a worked example.
3. Add the command to the privacy-default test
   (`tests/privacy/test_invP001_cli_no_egress.py`) so its `--json`
   output is asserted to make zero outbound HTTP calls.
4. The provisional `INV-C-cli-output-stability` invariant is promoted
   to canonical in [INVARIANTS.md](INVARIANTS.md) at rich-cli Phase 6
   close (assuming a privacy-safety-reviewer pass).
