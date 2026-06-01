# Feature: README Accuracy Refresh

**Status**: Draft
**Created**: 2026-06-01
**Owner**: agent (claude) + project owner review
**Related Plans**: consumes the shipped surfaces from [host-profile-personal-context](../../completed/host-profile-personal-context/), the agent-driven PRS layer, coverage-panel-v2, vep-mane-plus-clinical, and the rich-cli migration.

---

## Goal

Bring `README.md` back into **accurate, verified** alignment with the shipped CLI surface, host service, agent tools, and invariants — and add a **code-derived consistency test** so the enumerable README facts (tool list, CLI commands, host-service port, endpoint paths, invariants version) cannot silently drift again.

## Background

`README.md` (607 lines) has drifted across several sections as the toolkit shipped well beyond what the doc describes. Audited drift (2026-06-01, against `main` @ `c789b58`):

| README claim | Location | Reality |
|---|---|---|
| "**six agent-callable tools**" (`…genomeclaw_pgs`) | § How NemoClaw Agents Use GenomeClaw (~L219) | **Ten** tools: `genomeclaw_status/findings/variant/evidence/gene` + `genomeclaw_pgs_list/_get/_compute/_compute_status` + `genomeclaw_host_profile` (per `openclaw.plugin.json` `contracts.tools`). |
| host service "FastAPI on `127.0.0.1:8643`" | same § (~L219) | Port is **8645** (the README itself says 8645 at L307 — internal contradiction). |
| endpoint list ends at `/v1/pgs/{trait}` | same § (~L219) | `/v1/pgs/{trait}` was retired; actual: `/v1/pgs/computed`, `/v1/pgs/computed/{id}`, `POST /v1/pgs/compute`, `/v1/pgs/compute/{task_id}`, plus `/v1/host/profile` + `/v1/host/profile/completeness` + `/v1/capabilities`. |
| pipeline subcommands `fetch, ingest, normalize, annotate, materialize, cyp2d6-call, pgs-compute` | § How agents use… (~L218) | Actual `pipeline` group: `ingest, normalize, annotate, materialize, run, pgs-compute, prs-prepare-coverage, prs-compute, pharmcat, cyp2d6-call, pgs-config-write`; `fetch` is under `refs`, not pipeline. The whole `host profile` group is absent. |
| no mention of `host profile` | entire README | The `genomeclaw host profile {init,show,set,review,edit}` subgroup shipped (host-profile-personal-context) + `host setup --skip-profile`/`--thorough-profile`. |
| "[INVARIANTS v1.6]" | Status (~L13) | INVARIANTS is at **v1.26**. |
| Status: "Phases 1–3 … The full VEP-based annotation stack (Phase 4) is next." | Status (~L13) | Annotation, agent-driven PRS, coverage-panel-v2, VEP/MANE, CYP2D6 no-call, PharmCAT, the host service + plugin, and the host profile have all shipped. |

These are factual inaccuracies in the canonical entry-point doc — a contributor or agent reading the README to learn the CLI gets wrong commands, a wrong port, a wrong tool list, and a wrong endpoint set.

## Acceptance Criteria

- **AC1** — README documents the `genomeclaw host profile` subgroup (`init`, `show`, `set`, `review`, `edit`) and the `host setup --skip-profile` / `--thorough-profile` onboarding-chain flags.
- **AC2** — The agent-integration section names **all ten** plugin tools and no longer says "six". The count + names are derived from `openclaw.plugin.json` so they stay correct.
- **AC3** — Every host-service port reference in the README is **8645** (zero `8643` references to GenomeClaw's service).
- **AC4** — The documented endpoint set matches the actual host-service routes: includes `/v1/host/profile`(+`/completeness`) and the agent-driven PRS endpoints; excludes the retired `/v1/pgs/{trait}`.
- **AC5** — The documented `pipeline` subcommand list matches the actual `pipeline` Typer group; `fetch`/`list`/`verify`/`info` are correctly shown under `refs`, and `runs` (`list`/`show`/`current`) is documented.
- **AC6** — The README's invariants reference does not hardcode a stale version (link without a frozen number, or the number matches the current `INVARIANTS.md` Version).
- **AC7** — The Status / "Architecture at a glance" framing reflects shipped reality (annotation + PRS + coverage-panel-v2 + CYP2D6 + PharmCAT + host service + plugin + host profile), not "Phases 1–3, Phase 4 next".
- **AC8** — A **code-derived consistency test** (`packages/toolkit/tests/invariants/test_readme_accuracy.py`) passes: it derives ground truth from the Typer app + `openclaw.plugin.json` + `service/app.py` + `INVARIANTS.md` and asserts the README's enumerable facts match, and that retired strings (`8643` for the service, "six … tools", `/v1/pgs/{trait}`) are absent.
- **AC9** — Full toolkit suite stays green; **no code/behaviour change** ships in this plan (README + one new test only).
- **AC10** — A privacy-safety-reviewer pass confirms the README's "Privacy Posture" + agent-integration sections still describe the data-boundary / named-egress model accurately (no doc claim that understates host-profile sensitivity or the NemoClaw egress boundary).

## Applicable Invariants

- **INV-C002** (CLI Output Contract Stability) — the README is the human-facing description of that CLI surface; documenting commands/flags accurately is the prose side of the same contract. The consistency test pins it.
- **INV-P001 / INV-P002** (Privacy default / minimal-sufficient egress) — the README's privacy + agent-integration sections describe the egress model; they must remain accurate (the host profile is sensitive; the NemoClaw agent is the named egress; web_search is topic-only). AC10 verifies.
- **INV-D002** (Raw artifacts host-side only) — the README's storage + architecture framing must keep the host-side-only boundary accurate.
- **INV-V001** (Verification methodology) — the consistency test is *structural inspection over a source document* (README + code), the sanctioned mechanism; it does not enumerate forbidden phrases over agent output. The few "retired-string-absent" assertions target a static doc, annotated `# INV-V001-allow`.

## Proposed New Invariants

- *(Optional, provisional)* **INV-C-docs-accuracy** — "Enumerable README facts (tool list, CLI command tree, host-service port, endpoint paths) must match the code." Captured for now as the Phase-1 consistency test rather than a promoted invariant; promote only if it proves stable + valuable across a couple of doc-drift cycles. Decision deferred to Phase 4.

## Technical Requirements

### Source Data Inputs
- `README.md` (the document under repair).
- Ground-truth sources: `packages/toolkit/src/genomeclaw_toolkit/_cli/` (Typer app + command groups), `packages/nemoclaw-plugin/openclaw.plugin.json` (tool list), `packages/toolkit/src/genomeclaw_toolkit/service/app.py` (routes), `docs/reference/INVARIANTS.md` (Version), `docs/reference/cli-output-schemas.md` (envelope shapes).

### Derived Outputs
- An updated `README.md`.
- A new `packages/toolkit/tests/invariants/test_readme_accuracy.py`.

### Schema / Migration Impact
None. Docs + test only.

### Pipeline / Workflow Impact
None.

### Agent / UX Impact
Improves the entry-point doc agents/contributors read to learn the CLI. No runtime behaviour change.

### External Dependencies
None.

## Privacy & Safety Considerations

Docs-only change, but the README *describes* the privacy model, so a privacy-safety-reviewer pass (AC10) confirms the rewritten Privacy Posture + agent-integration sections accurately state: raw genomic files never leave the host (INV-D002); the NemoClaw agent is the named, minimal-sufficient egress (INV-P002); web_search payloads are topic-only (INV-P001); the host profile is sensitive host-side data reached only via the read-only tool surface. No new egress is introduced by documentation.

## Out of Scope

- Any code or behaviour change to the CLI, host service, plugin, or agent prompt.
- Rewriting `docs/reference/*` beyond what a README cross-link requires (those docs are separately maintained; `cli-output-schemas.md` is already current per the host-profile work).
- Prose-style/marketing polish beyond accuracy + clarity.
- Promoting INV-C-docs-accuracy (decision deferred; the test is the deliverable).

## Dependencies

- The shipped surfaces are already on `main` (host profile, PRS layer, etc.), so ground truth is stable.

## Open Questions

- **Q1** — Should the invariants reference in the README be version-pinned (and asserted by the test) or version-less (link only)? *Leaning version-less* to avoid a per-bump README edit; the test then only checks the link target exists, not a number. Resolve in Phase 1.
- **Q2** — Should the consistency test assert the *full* command tree (every subcommand) or a curated "load-bearing" subset (groups + host/pipeline subcommands + the host-profile group)? *Leaning curated subset* to avoid brittle over-pinning of rarely-changing leaf commands. Resolve in Phase 1.
