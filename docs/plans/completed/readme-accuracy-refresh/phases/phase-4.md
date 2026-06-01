# Phase 4: Freshness + Cross-Links + Final Verify

**Status**: Pending
**Parent Plan**: [../development-plan.md](../development-plan.md)

---

## Objective

De-stale the README's Status / "Architecture at a glance" framing to reflect shipped reality, resolve the invariants-version reference (Q1), verify cross-links, get the full consistency gate + toolkit suite green, do a manual read-through, decide the INV-C-docs-accuracy promotion question, and archive the plan.

## Invariants Enforced in This Phase

- **INV-C002** — full consistency gate green.
- All prior invariants re-verified via the full suite.

## TDD Steps

- **GREEN**: the Phase-1 gate's invariants-link assertion (#7) turns green; the *whole* gate passes.
- **Edits**:
  - Status section: replace "Phases 1–3 … Phase 4 (annotation) next" with an accurate shipped-state summary (annotation stack + agent-driven PRS + coverage-panel-v2 + VEP/MANE + CYP2D6 no-call + PharmCAT + host service + plugin + host profile / INV-C004). Keep it honest about what's still in flight.
  - Invariants reference: de-stale "v1.6" per Q1 (version-less link, or current version).
  - Verify all intra-repo links resolve (plans moved to `completed/`, etc.).
- **REFACTOR**: manual read-through for prose quality + internal consistency (no contradictory port/tool/endpoint claims anywhere).

## Files

| File | Action | Purpose |
|------|--------|---------|
| `README.md` | MODIFY | Status/overview freshness + invariants link + cross-links. |
| `docs/reference/INVARIANTS.md` | MODIFY (only if INV-C-docs-accuracy promoted — default NO) | Optional invariant promotion. |

## Verification

```bash
# Full consistency gate
cd packages/toolkit
.venv/bin/pytest tests/invariants/test_readme_accuracy.py -v

# Full toolkit suite — must be green (modulo the documented pre-existing failures)
.venv/bin/pytest -q

# Plugin tests unaffected (no plugin change) — sanity
cd ../nemoclaw-plugin && bun run test
```

## Completion Criteria

- [ ] Status/overview reflects shipped reality (AC7); invariants link de-staled (AC6).
- [ ] Full `test_readme_accuracy.py` green (AC8); toolkit suite green modulo documented pre-existing failures (AC9).
- [ ] Manual read-through done; no internal contradictions remain.
- [ ] INV-C-docs-accuracy promotion decision recorded (default: not promoted; test stands alone).
- [ ] `work-notes.md` reflects actual work; `development-plan.md` reconciled with as-shipped.
- [ ] Plan moved `active/ → completed/`.
