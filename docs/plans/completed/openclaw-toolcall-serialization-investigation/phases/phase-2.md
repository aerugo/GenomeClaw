# Phase 2 — Cross-model bisect

**Status**: Pending (gated on Phase 1 producing a reproducer)
**Started**:
**Completed**:
**Parent Plan**: [development-plan.md](../development-plan.md)

---

## Objective

Run the Phase 1 reproducer against ONE non-OpenAI model (Claude/Anthropic via openclaw if supported) to determine whether the failure modes are runtime-side (openclaw mangles args regardless of model) or model-side (gpt-5.5-specific quirk that Claude doesn't exhibit). Output: appended section in `findings.md`.

## Scope Boundaries

- **In scope**: one alternative model, same reproducer prompt, same harness, capture the same corruption-rate metric.
- **Out of scope**: matrix across multiple models, multiple thinking levels, multiple prompt variants. ONE additional model is enough to distinguish runtime-vs-model.

## Invariants enforced in this phase

- **INV-P001** — same synthetic prompt; no user genomic content.

---

## Steps

### 2.1 — Pick the alternative model

Three candidates by openclaw support:
- Claude (Anthropic) — most likely first-class via openclaw + the existing live-smoke harness.
- Gemini — possibly supported; check openclaw config schema.
- A local model via openclaw's local-inference path — useful but slower; defer unless Claude isn't available.

Pick whichever has the lowest activation cost. Document the choice in `findings.md`.

### 2.2 — Adapt the reproducer harness

Swap the openclaw config batch in `tests/_live_smoke/run.py::_build_in_container_script` to point at the alternative model:

```
models.providers.anthropic.apiKey = (env ANTHROPIC_API_KEY)
agents.defaults.model = "anthropic/claude-4.6-sonnet"  # or whatever the openclaw config expects
agents.defaults.thinkingDefault = (model's equivalent of xhigh, if any)
```

The reproducer script (`/tmp/openclaw_serialization_repro.py`) gains an `--alt-model` flag or env-driven variant.

### 2.3 — Run + record

Run the same reproducer 5 times against the alternative model. Capture:
- Per-run corruption count.
- Aggregate corruption rate.
- Raw payload sample (via Phase 1's Option A/B/C — same monkey-patch / proxy).

### 2.4 — Compare + classify

Two possible outcomes:

**Outcome A — Alternative model exhibits same corruption rate** → bug is runtime-side (openclaw's tool-arg unpacker; INDEPENDENT of model). Phase 3 should pick Path U (file openclaw issue).

**Outcome B — Alternative model has 0% corruption rate** → bug is model-specific (gpt-5.5 quirk). Phase 3 should pick Path D (document quirk + update sysprompt to bias toward fewer-args calls when on gpt-5.5).

**Outcome C — Alternative model has different corruption rate** (e.g. 20% vs gpt-5.5's 80%) → model-sensitive but not model-exclusive. Phase 3 should pick a blend: Path D (document the model-conditioned quirk) + possibly Path U if the runtime SHOULD handle it better.

### 2.5 — Append to findings.md

Add a "Cross-model bisect" section with:
- Alternative model + thinking level.
- Corruption rate across 5 runs.
- Outcome (A/B/C).
- Refined Path recommendation for Phase 3.

---

## Files

| File | Action | Purpose |
|------|--------|---------|
| `docs/plans/active/openclaw-toolcall-serialization-investigation/findings.md` | MODIFY | Append cross-model bisect section |
| `tests/_live_smoke/run.py` (possibly) | MODIFY | Extract the model+thinking config into a parameter for cross-model runs |
| `/tmp/openclaw_serialization_repro.py` | MODIFY | Add `--alt-model` support |

If the harness change to `run.py` is too invasive for an investigation, do it via a stand-alone reproducer script and don't touch the harness.

---

## Verification

Phase 2 is investigation. Acceptance gate:

- 5 runs against the alternative model completed.
- Corruption rate computed.
- Outcome A/B/C labelled in `findings.md`.
- Path U/D/L recommendation refined.

---

## Completion Criteria

- [ ] Alternative model picked + activated (one call worked end-to-end before the experiment).
- [ ] 5 reproducer runs against the alternative model.
- [ ] Corruption rate recorded.
- [ ] Outcome A/B/C classified.
- [ ] `findings.md` updated.
- [ ] Phase 3 path locked in.

## Next

[Phase 3 — Decide + execute](phase-3.md).
