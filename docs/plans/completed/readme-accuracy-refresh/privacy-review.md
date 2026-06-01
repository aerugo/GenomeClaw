# Privacy-safety review — README accuracy refresh (Phase 3)

**Date**: 2026-06-01
**Reviewer**: `privacy-safety-reviewer` agent (blocking pass per phase-3.md)
**Scope**: accuracy of the *described* privacy / data-boundary model in `README.md` after the Phase-2/3 rewrites (intro, Privacy Posture, "How NemoClaw Agents Use GenomeClaw", the new "Personal-context profile" subsection).

**Verdict**: Accept with required changes. The **rewritten sections were confirmed accurate** (no overclaim); the blocking findings were stale fossils in *older, unrevised* prose — exactly the drift this plan exists to fix. All findings addressed.

---

## Findings + resolutions

| # | Severity | Location | Finding | Resolution |
|---|----------|----------|---------|------------|
| 1 | BLOCKING | README L220 (Privacy Posture) | Cited `INV-C001 v1.5 (with curated-notes recognition)` — wrong version + a **retired** mechanism (curated_notes retired at v1.6). | Updated to `INV-C001 v1.7` (lifestyle direct-guidance + PRS-decline) + added `INV-C004`. |
| 2 | BLOCKING | README L34 (What it is) | Described the retired `reference/curated_notes/<gene>.md` calibration as the current mechanism. | Rewrote to the current **research-and-synthesis** path (training knowledge + `web_search` + memory + reasoning at the model ceiling); noted curated_notes retired at v1.6. |
| 3 | ADVISORY (companion) | INVARIANTS.md L351 (INV-P001 named egress) | Pre-existing: host service listed as `127.0.0.1:8643` (that's DevRelClaw's port). | Corrected to `8645` (+ "8643 is DevRelClaw's port"). Out of the README's strict scope but a 1-line factual fix the review surfaced. |
| 4 | ADVISORY | README L253 (repo-layout tree) | `INVARIANTS.md … — v1.6` (current is v1.26). | Updated to v1.26. |
| 5 | ADVISORY | README L204 ("Planned data sources") | `curated_notes` listed as an active planned lifestyle-calibration source. | Replaced with the host personal-context profile (`INV-C004`); annotated curated_notes retired at v1.6. |
| — | (also fixed) | README L13 (Status) | Stale `INVARIANTS v1.6` link + "Phases 1–3, Phase 4 next". | Rewrote Status to shipped reality (full pipeline + PRS + host profile + schema v0.4); invariants link made version-less (plan Q1). |
| — | (also fixed) | README L155 (architecture diagram) | `reference/ … + curated_notes` implied an active reference source. | Removed `curated_notes` from the diagram. |

## Confirmed accurate (no change needed)

The reviewer explicitly cleared the rewritten sections:
- **Intro + Privacy Posture** — "genomic source files never leave the device" (INV-D002/P001); NemoClaw agent as the *named, minimal-sufficient* egress (INV-P002); bulk transfer opt-in; secrets outside data dirs; logs exclude sample IDs / coords. Egress model correct: native `web_search` is within the agent provider's existing egress envelope, managed search is a separate opt-in, topic-only rule binds.
- **How NemoClaw Agents Use GenomeClaw** — CLI groups, host service `127.0.0.1:8645`, endpoint list incl. `/v1/host/profile`(+`/completeness`), ten tools, "agent calls `genomeclaw_host_profile` before any genome-informable reply (INV-C004)", "profile content … never enters a `web_search` payload" — all accurate.
- **Personal-context profile subsection** — free-text stays host-side; agent paraphrases family history at relation-class + condition + age-class and never copies verbatim into memory / `web_search`; audit log records changed-paths + free-text **lengths only**. Correctly nuanced (does not imply free-text is sanitised before the agent sees it).

## Durable guard added

`test_readme_no_retired_curated_notes_calibration_citation` (in `test_readme_accuracy.py`) blocks the specific `INV-C001 v1.5` / "curated-notes recognition" fossils from returning (INV-V001-allow retired-string checks over the static doc).
