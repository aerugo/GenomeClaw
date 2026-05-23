# Agent Quirks

**Status**: Skeleton — content pending Phase 3 outcome of [docs/plans/active/openclaw-toolcall-serialization-investigation/](../plans/active/openclaw-toolcall-serialization-investigation/)

This document catalogues observed agent / openclaw runtime / LLM-provider
quirks that affect how GenomeClaw's nemoclaw plugin and host service
interact with the agent. Each entry is a labelled, reproducible, defanged
failure mode — not a bug-tracker substitute and not a workaround manifest;
the goal is institutional memory so future contributors recognise a
quirk on sight instead of spending hours rediscovering it.

Entries land here under three conditions:

1. The quirk is observed across at least two independent agent runs.
2. The runtime mitigation (a guard, a retry, a documented workaround) is
   stable and tested.
3. The classification (model-side / provider-side / runtime-side) is
   evidence-supported, not speculative.

> Content for the first entry — the **2026-05-23 tool-call
> argument-serialization corruption** — is pending Phase 3 outcome of
> the investigation plan. The skeleton headers below preview the shape
> entries will take; until Phase 3 lands, the empty sections are
> intentional.

---

## Quirk Index

| ID  | Title | Observed | Status | Classification |
|-----|-------|----------|--------|----------------|
| _(content pending Phase 3 outcome)_ | | | | |

---

## Quirk Q-001 — _(title pending Phase 3 outcome)_

### Symptom

_(content pending Phase 3 outcome)_

### Reproduction

_(content pending Phase 3 outcome)_

### Classification

_(content pending Phase 3 outcome)_

### Workaround in place

_(content pending Phase 3 outcome)_

### Upstream tracking

_(content pending Phase 3 outcome)_

### Detection

_(content pending Phase 3 outcome — pointer to the live-gated test that
exercises this quirk + the related vitest unit tests on the plugin's
arg-guard.)_

---

## Adding a new quirk

When a future investigation closes with a Path D outcome (document the
quirk), add a new section using the Q-XYZ heading shape above. Each
quirk gets:

- An `INV-xxx` reference IF the workaround is enforced by a project
  invariant; otherwise the test path is the enforcement surface.
- A pointer to the live-gated reproducer + the static unit test that
  pins the workaround.
- The upstream issue link (Path U) OR the local-fix commit SHA (Path L).
- A clear "what to do when this surfaces again" recipe for future
  agents — concrete steps, not vague advice.

Out of scope for this doc:

- Bugs that are fixed upstream and no longer reproduce.
- Speculation about quirks that haven't been observed twice.
- Workarounds that don't have test coverage.
