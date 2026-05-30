# Spec: VEP MANE Plus Clinical — API Exposure

## Goal

Project the two columns added by [`vep-mane-plus-clinical`](../../completed/vep-mane-plus-clinical/) (`mane_plus_clinical_transcript`, `transcript_discordant`) into the HTTP-layer response models so the NemoClaw agent can actually consult them when reasoning about a variant.

## Background

The completed `vep-mane-plus-clinical` plan delivered:

- VEP invocation change `--mane_select` → `--mane` + `--pick_order` with MANE Plus Clinical in the rank.
- 4-tier canonical pick: MANE Select → MANE Plus Clinical → CANONICAL → first.
- New DuckDB columns on `variants`: `mane_plus_clinical_transcript`, `transcript_discordant`.
- Dual-row emission when Select vs Plus-Clinical disagree on IMPACT tier.
- Agent system prompt §6 updated to mention "consult MANE Plus Clinical guidance when relevant."

Real-data smoke (2026-05-25, `derived/2026-05-25T19-42-58Z-c88e02`, MPNRGLQ2K) verified the schema layer:

- `mane_plus_clinical_transcript` populated on 390 of 4,812,994 variants.
- `transcript_discordant = true` on 24 variants (real Select vs Plus-Clinical IMPACT-tier disagreement: `MUTYH`, `NFASC`, `INPP4A`, ...).

But the HTTP boundary doesn't project either field:

```
$ curl http://127.0.0.1:8645/v1/variants/chr1-45345193-G-A | jq '.mane_plus_clinical_transcript // "NOT_IN_RESPONSE"'
"NOT_IN_RESPONSE"
```

The agent's `genomeclaw_variant` tool therefore can't act on the guidance the system prompt asks it to use. This is a "data exists in DB but isn't reachable" gap.

The original `vep-mane-plus-clinical` spec/dev-plan scoped only schema + extraction; API exposure was implicitly assumed but never landed. This plan closes that loop.

## Acceptance criteria

1. `VariantResponse` (Pydantic, `extra="forbid"`) lists `mane_plus_clinical_transcript: str | None` and `transcript_discordant: bool | None` (nullable because the columns are nullable in DuckDB).
2. `_VARIANTS_GET_COLUMNS` (in `service/store.py`) includes the two new column names.
3. `genomeclaw_variant` TypeBox response schema in `packages/nemoclaw-plugin/src/index.ts` declares the two fields, matching Pydantic nullability.
4. Existing field-bloat-guard test for `VariantResponse` is updated to expect the new fields (not break).
5. A new integration test queries `/v1/variants/<key>` for at least one `transcript_discordant=true` row from the real-data run dir and asserts both new fields are present + populated.
6. The agent system prompt §6 wording (already updated by `vep-mane-plus-clinical`) now describes a reachable surface — no prompt change needed in this plan.

## Applicable invariants

- **`INV-A004`** Decline / safety taxonomy must traverse every layer — directly analogous: any column added to the DB that the agent is asked to consult must be projected through the HTTP layer + the TypeBox schema. The Plan 4 omission is exactly the failure mode INV-A004 was promoted to prevent (then for `decline_reason`; here for MANE+ / discordant).
- **`INV-R001`** Rebuildability — no schema/version change; this plan only widens response projections.
- **`INV-P002`** Minimal-sufficient agent payloads — the two added fields are both bounded scalars (one short transcript ID, one bool); negligible bytes added per response.

## Proposed new invariants

None. INV-A004 already covers this class of gap; the cross-language schema-diff test it enforces should be extended (in this plan) to compare DuckDB `variants` columns against `VariantResponse` fields against the TypeBox schema, with an explicit allowlist for columns intentionally not surfaced (e.g., the seven provenance columns).

## Out of scope

- Re-running annotate against the real-data run dir. The existing run already has both columns populated.
- Bumping `schema_version`. No DDL change; the projection-layer change is backwards-compatible.
- Changing the system prompt. The wording landed with `vep-mane-plus-clinical` already.
- Re-running the bioreview-followup-meta close-out smokes. This plan ships its own one-test integration probe.

## Privacy & safety considerations

- The two new fields are both publicly derivable from MANE / RefSeq annotation. No identifying or sensitive information is added.
- `INV-P002` minimal-sufficient: bounded scalars, no list / nested object expansion.
- No new egress; the HTTP service stays local-only.

## Open questions

None. The work shape is fully constrained by the schema layer that landed in `vep-mane-plus-clinical`.
