// SPDX-FileCopyrightText: Copyright (c) 2026 GenomeClaw contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * GenomeClaw — OpenClaw plugin for NemoClaw.
 *
 * Phase 5 Slice D migrated this plugin from the v0 `registerCommand` +
 * `GENOMECLAW_JSON:` text-encoding pattern to OpenClaw's published
 * `registerTool` agent-tool API (see [spec.md § Q2 / Q4](../../../docs/plans/active/mvp/spec.md)).
 * Each tool now ships:
 *
 * - A TypeBox schema describing its parameters (typed arrays for
 *   collections per Q4; scalars for single-record lookups).
 * - A `jsonResult(payload)` envelope on success: the pretty-printed JSON
 *   lands in `content[].text` and the structured payload is preserved in
 *   `details` for runtime consumers.
 * - A `failedTextResult(reason, details?)` envelope on error.
 *
 * Conformance:
 * - `INV-D001` / `INV-D002`: this plugin never reads raw genomic files.
 *   All access is via the host service over the configured network policy
 *   preset (`packages/nemoclaw-plugin/policy-preset.yaml`).
 * - `INV-P001` / `INV-P002`: every tool's `outputClass` is `summary`.
 *   Bulk-mode opt-ins are reserved for a separate policy preset; the
 *   `bulk` arg is rejected by the TypeBox schemas (they don't declare
 *   one).
 * - `INV-R001`: provenance metadata is forwarded verbatim from the host
 *   service into the `details` field; nothing is stripped or summarised.
 *
 * The five MVP tools registered here (per [spec.md AC3](../../../docs/plans/active/mvp/spec.md)):
 *
 * | Tool                  | Endpoint                          | Output class |
 * |-----------------------|-----------------------------------|--------------|
 * | `genomeclaw_status`   | `GET /v1/health`                  | summary      |
 * | `genomeclaw_findings` | `GET /v1/findings?...`            | summary      |
 * | `genomeclaw_variant`  | `GET /v1/variants/{key}`          | summary      |
 * | `genomeclaw_evidence` | `GET /v1/evidence/{ref}`          | summary      |
 * | `genomeclaw_gene`     | `GET /v1/gene/{symbol}`           | summary      |
 *
 * The 6th tool (`genomeclaw_pgs`) lands in Phase 6 alongside the PRS work.
 */

import { Type, type Static } from "@sinclair/typebox";
// Per the 2026-05-15 live sweep + OPENCLAW_PLUGIN_SDK_COMPAT_DEPRECATED
// runtime warning: the bare `openclaw/plugin-sdk` (compat) import is the
// deprecated path. `failedTextResult` is undefined there. The published
// subpath `openclaw/plugin-sdk/agent-runtime` carries both helpers as
// runtime functions. See https://docs.openclaw.ai/plugins/sdk-migration.
//
// Types continue to come from the bare `openclaw/plugin-sdk` because our
// local stub at [types/openclaw-plugin-sdk.d.ts](../types/openclaw-plugin-sdk.d.ts)
// declares the surface there; the real SDK's type tree mirrors the values.
import { failedTextResult, jsonResult } from "openclaw/plugin-sdk/agent-runtime";
import type {
  AgentToolContext,
  OpenClawPluginApi,
} from "openclaw/plugin-sdk";

// ---------------------------------------------------------------------------
// Plugin runtime config (sourced from plugins.entries.genomeclaw.config.*)
// ---------------------------------------------------------------------------

interface HostServiceConfig {
  baseUrl: string;
  timeoutMs: number;
}

interface PluginRuntimeConfig {
  hostService: HostServiceConfig;
  logVerbosity: "error" | "warn" | "info" | "debug";
}

const DEFAULT_CONFIG: PluginRuntimeConfig = {
  hostService: {
    baseUrl: "http://host.openshell.internal:8643",
    timeoutMs: 5000,
  },
  logVerbosity: "info",
};

function resolveConfig(api: OpenClawPluginApi): PluginRuntimeConfig {
  const raw = (api.pluginConfig ?? {}) as Record<string, unknown>;
  const host = (raw["hostService"] ?? {}) as Record<string, unknown>;
  return {
    hostService: {
      baseUrl:
        typeof host["baseUrl"] === "string"
          ? (host["baseUrl"] as string)
          : DEFAULT_CONFIG.hostService.baseUrl,
      timeoutMs:
        typeof host["timeoutMs"] === "number"
          ? (host["timeoutMs"] as number)
          : DEFAULT_CONFIG.hostService.timeoutMs,
    },
    logVerbosity:
      raw["logVerbosity"] === "error" ||
      raw["logVerbosity"] === "warn" ||
      raw["logVerbosity"] === "debug"
        ? (raw["logVerbosity"] as PluginRuntimeConfig["logVerbosity"])
        : DEFAULT_CONFIG.logVerbosity,
  };
}

// ---------------------------------------------------------------------------
// Host-service HTTP client
//
// One function for every tool; the path + optional query are passed in.
// Repeated-key query params (per spec Q4 + the host service's FastAPI
// `list[str]` convention) are produced by `URLSearchParams.append` rather
// than `set`.
// ---------------------------------------------------------------------------

type QueryParam = string | string[];

/**
 * Single HTTP client for every plugin → host-service call. INV-P001
 * defence-in-depth: one `fetch(...)` call site in the source so the
 * URL construction + timeout + auth-style discipline can't fork.
 *
 * Method dispatch: GET (no body) by default; POST (JSON body) when
 * `body` is supplied. Slice E v2's `genomeclaw_pgs_compute` is the
 * first POST tool; future write-tools (if any are ever added) use
 * the same code path.
 */
async function callHostService(
  cfg: HostServiceConfig,
  path: string,
  query?: Record<string, QueryParam | undefined>,
  body?: unknown,
): Promise<unknown> {
  const url = new URL(path, cfg.baseUrl);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      if (v === undefined) continue;
      if (Array.isArray(v)) {
        for (const item of v) url.searchParams.append(k, item);
      } else {
        url.searchParams.set(k, v);
      }
    }
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), cfg.timeoutMs);
  try {
    const method = body === undefined ? "GET" : "POST";
    const headers: Record<string, string> = { Accept: "application/json" };
    if (body !== undefined) headers["Content-Type"] = "application/json";
    // Build init step-by-step so `body` is only set when defined.
    // tsconfig's `exactOptionalPropertyTypes: true` rejects passing
    // `body: undefined` to `RequestInit` (which expects either a
    // present `BodyInit` or the key absent).
    const init: RequestInit = { method, headers, signal: ctrl.signal };
    if (body !== undefined) init.body = JSON.stringify(body);
    const res = await fetch(url.toString(), init);
    if (!res.ok) {
      throw new Error(
        `genomeclaw-service ${path} -> HTTP ${String(res.status)}`,
      );
    }
    return await res.json();
  } finally {
    clearTimeout(timer);
  }
}

/**
 * Wrap an HTTP call in the `jsonResult` / `failedTextResult` envelope
 * shape every tool returns. Centralises the success-vs-error envelope
 * choice so each tool's `execute` stays a 2-line body.
 */
async function safeCall<T = unknown>(
  cfg: HostServiceConfig,
  path: string,
  query?: Record<string, QueryParam | undefined>,
): Promise<ReturnType<typeof jsonResult<T>> | ReturnType<typeof failedTextResult>> {
  try {
    const payload = (await callHostService(cfg, path, query)) as T;
    return jsonResult(payload);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return failedTextResult(msg, { path });
  }
}

/**
 * POST variant of `safeCall` — passes `body` through to the consolidated
 * `callHostService` (one fetch call site for the whole plugin per INV-P001
 * defence-in-depth). Slice E v2's `genomeclaw_pgs_compute` uses this for
 * the `POST /v1/pgs/compute` path; the host service expects the
 * `PgsComputeRequest` body shape and returns a `PgsComputeTaskResponse`
 * envelope (task_id + status).
 */
async function safePost<T = unknown>(
  cfg: HostServiceConfig,
  path: string,
  body: unknown,
): Promise<ReturnType<typeof jsonResult<T>> | ReturnType<typeof failedTextResult>> {
  try {
    const payload = (await callHostService(cfg, path, undefined, body)) as T;
    return jsonResult(payload);
  } catch (err) {
    const msg = err instanceof Error ? err.message : String(err);
    return failedTextResult(msg, { path });
  }
}

// ---------------------------------------------------------------------------
// TypeBox parameter schemas (spec Q4)
// ---------------------------------------------------------------------------

const StatusParams = Type.Object({}, { additionalProperties: false });

const FindingsCategory = Type.Union([
  Type.Literal("clinical-actionable"),
  Type.Literal("clinical-non-actionable"),
  Type.Literal("lifestyle"),
  Type.Literal("mixed"),
]);

const FindingsParams = Type.Object(
  {
    category: Type.Optional(FindingsCategory),
    genes: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { minItems: 1 })),
    drugs: Type.Optional(Type.Array(Type.String({ minLength: 1 }), { minItems: 1 })),
    limit: Type.Optional(Type.Integer({ minimum: 1, maximum: 200 })),
  },
  { additionalProperties: false },
);

// Placeholder-string rejection: the agent occasionally generates tool
// calls with the literal string "undefined" / "null" / "none" / "nil"
// when its argument-resolution path produced no real value. These would
// otherwise pass minLength: 1 and produce wasted 404/400 round-trips
// against /v1/gene/undefined etc. (observed in the 2026-05-23
// eyesight-question deep-dive). The pattern is a negative-lookahead JSON
// Schema regex; it rejects the four placeholder tokens case-insensitively
// while accepting every real gene symbol / variant key / evidence ref.
const _NOT_PLACEHOLDER = "^(?![Uu][Nn][Dd][Ee][Ff][Ii][Nn][Ee][Dd]$)(?![Nn][Uu][Ll][Ll]$)(?![Nn][Oo][Nn][Ee]$)(?![Nn][Ii][Ll]$).+$";

const VariantParams = Type.Object(
  { key: Type.String({ minLength: 1, pattern: _NOT_PLACEHOLDER }) },
  { additionalProperties: false },
);

const EvidenceParams = Type.Object(
  { ref: Type.String({ minLength: 1, pattern: _NOT_PLACEHOLDER }) },
  { additionalProperties: false },
);

const GeneParams = Type.Object(
  { gene: Type.String({ minLength: 1, pattern: _NOT_PLACEHOLDER }) },
  { additionalProperties: false },
);

// Phase 6 Slice E v2 — agent-driven PRS tools (Q8 v1.6).
//
// PGS Catalog ID is the canonical key (not curator-named trait). Compute
// is async + agent-triggered; rationale + alternatives considered persist
// per INV-A003. The `rationale` field carries a minLength: 10 gate at the
// TypeBox layer (defence-in-depth with the host-service 422); together
// they enforce a non-empty rationale floor without rejecting agent-typical
// brevity. The agent system prompt continues to encourage ≥50-char
// "alternatives considered" framing; the 50-char gate was relaxed after
// the 2026-05-23 AMD-question incident where reasoning-pressured rationales
// (~41 chars) were 422'd, breaking the compute path.

const PgsListParams = Type.Object({}, { additionalProperties: false });

const PgsGetParams = Type.Object(
  { pgs_id: Type.String({ minLength: 1 }) },
  { additionalProperties: false },
);

const PgsComputeParams = Type.Object(
  {
    pgs_id: Type.String({ minLength: 1 }),
    trait_label: Type.String({ minLength: 1 }),
    rationale: Type.String({ minLength: 10 }),
    requested_for_question: Type.String({ minLength: 1 }),
  },
  { additionalProperties: false },
);

const PgsComputeStatusParams = Type.Object(
  { task_id: Type.String({ minLength: 1 }) },
  { additionalProperties: false },
);

// ---------------------------------------------------------------------------
// Plugin entry point
// ---------------------------------------------------------------------------

export default function register(api: OpenClawPluginApi): void {
  const cfg = resolveConfig(api);
  const host = cfg.hostService;

  // ── genomeclaw_status ───────────────────────────────────────────────
  api.registerTool({
    name: "genomeclaw_status",
    description:
      "Report GenomeClaw host service status: gateway health, active derived-store run-id, and schema version. " +
      "Use this first to confirm there is an active run before asking about findings, variants, or genes.",
    parameters: StatusParams,
    outputClass: "summary",
    execute: async (_args: Static<typeof StatusParams>, _ctx: AgentToolContext) => {
      return safeCall(host, "/v1/health");
    },
  });

  // ── genomeclaw_findings ─────────────────────────────────────────────
  api.registerTool({
    name: "genomeclaw_findings",
    description:
      "Return scoped findings (summary class). Filter by `category`, by an array of gene symbols `genes`, " +
      "by an array of drug names `drugs`, or by a `limit`. Each finding includes evidence references and a " +
      "clinical-escalation marker where applicable.",
    parameters: FindingsParams,
    outputClass: "summary",
    execute: async (args: Static<typeof FindingsParams>, _ctx: AgentToolContext) => {
      const query: Record<string, QueryParam | undefined> = {};
      if (args.category !== undefined) query["category"] = args.category;
      if (args.genes !== undefined) query["genes"] = args.genes;
      if (args.drugs !== undefined) query["drugs"] = args.drugs;
      if (args.limit !== undefined) query["limit"] = String(args.limit);
      return safeCall(host, "/v1/findings", query);
    },
  });

  // ── genomeclaw_variant ──────────────────────────────────────────────
  api.registerTool({
    name: "genomeclaw_variant",
    description:
      "Look up a single variant by its canonical key (`{chrom}-{pos}-{ref}-{alt}`, e.g. `chr1-12345-A-T`). " +
      "Returns the normalized variant record plus its annotation set (summary class). " +
      "Use this for one variant at a time; for browse-style queries use a future filtered endpoint.",
    parameters: VariantParams,
    outputClass: "summary",
    execute: async (args: Static<typeof VariantParams>, _ctx: AgentToolContext) => {
      return safeCall(host, `/v1/variants/${encodeURIComponent(args.key)}`);
    },
  });

  // ── genomeclaw_evidence ─────────────────────────────────────────────
  api.registerTool({
    name: "genomeclaw_evidence",
    description:
      "Fetch a single evidence record by its reference id (variant-keyed kinds only: " +
      "`clinvar:<id>`, `pgs_catalog:<PGS-id>`, `pharmgkb:<PA-id>`). Use this to expand a citation " +
      "surfaced by `genomeclaw_findings`. The earlier `gene_note:<gene>` and `topic:<topic>` kinds " +
      "were retired in v1.6 (lifestyle calibration flows through the agent's memory + reasoned " +
      "research, not host-side curated notes).",
    parameters: EvidenceParams,
    outputClass: "summary",
    execute: async (args: Static<typeof EvidenceParams>, _ctx: AgentToolContext) => {
      return safeCall(host, `/v1/evidence/${encodeURIComponent(args.ref)}`);
    },
  });

  // ── genomeclaw_gene ─────────────────────────────────────────────────
  api.registerTool({
    name: "genomeclaw_gene",
    description:
      "Aggregate per-gene summary for an HGNC symbol: variant count, mean coverage depth, and (for the " +
      "curated subset) the list of exons below the low-coverage threshold. Resolves case-insensitively — " +
      "`brca1` and `BRCA1` refer to the same gene.",
    parameters: GeneParams,
    outputClass: "summary",
    execute: async (args: Static<typeof GeneParams>, _ctx: AgentToolContext) => {
      return safeCall(host, `/v1/gene/${encodeURIComponent(args.gene)}`);
    },
  });

  // ── genomeclaw_pgs_list ─────────────────────────────────────────────
  // Phase 6 Slice E v2 (Q8 v1.6): list all PRSs the agent has computed
  // for this user. Call this BEFORE deciding to compute a new PGS —
  // if the right scorefile is already cached, skip the compute step.
  api.registerTool({
    name: "genomeclaw_pgs_list",
    description:
      "List PRSs already computed for this user. Each row carries pgs_id (PGS Catalog ID), " +
      "trait_label, percentile_in_user_ancestry, calibration_warning, and superseded_by. " +
      "Call this before `genomeclaw_pgs_compute` — if a suitable PGS is already computed, " +
      "use `genomeclaw_pgs_get` to fetch it instead of triggering a new ~5-minute compute.",
    parameters: PgsListParams,
    outputClass: "summary",
    execute: async (_args: Static<typeof PgsListParams>, _ctx: AgentToolContext) => {
      return safeCall(host, "/v1/pgs/computed");
    },
  });

  // ── genomeclaw_pgs_get ──────────────────────────────────────────────
  // Fetch one computed PRS in full, including agent_choice_rationale +
  // requested_for_question (the INV-A003 provenance fields).
  api.registerTool({
    name: "genomeclaw_pgs_get",
    description:
      "Fetch one computed PRS by its PGS Catalog ID (e.g. `PGS000018`). Returns the percentile, " +
      "raw score, study population, calibration warning, plus the agent's choice rationale " +
      "(alternatives considered + why this scorefile) and the verbatim user question that " +
      "triggered the compute. The choice-rationale field is the user's audit surface per INV-A003.",
    parameters: PgsGetParams,
    outputClass: "summary",
    execute: async (args: Static<typeof PgsGetParams>, _ctx: AgentToolContext) => {
      return safeCall(host, `/v1/pgs/computed/${encodeURIComponent(args.pgs_id)}`);
    },
  });

  // ── genomeclaw_pgs_compute ──────────────────────────────────────────
  // Agent-triggered async compute. Returns immediately with a task_id;
  // pgsc_calc runs in the background (~5 min for one PGS at 30× WGS).
  // Poll genomeclaw_pgs_compute_status until done; then fetch via
  // genomeclaw_pgs_get. No per-request user approval — egress consent
  // was given once at install per INV-P001.
  api.registerTool({
    name: "genomeclaw_pgs_compute",
    description:
      "Compute a PRS for a new PGS Catalog ID. Async: returns a task_id immediately; pgsc_calc " +
      "runs in the background (~5 min for one PGS at 30× WGS). Poll `genomeclaw_pgs_compute_status` " +
      "until done; then fetch via `genomeclaw_pgs_get`. **Always populate `rationale`** with what " +
      "alternative scorefiles you considered and why this one is best for the user's question — " +
      "this lands on the result row as the user's audit surface per INV-A003. Always populate " +
      "`requested_for_question` with the verbatim user question that triggered the compute. " +
      "Surface the in-flight state to the user ('I'm computing…; back in ~5 min'). If the " +
      "literature for this trait is too immature (top-decile RR < ~1.5×; no independent " +
      "replication; ancestry-calibration failure; no biologically-grounded polygenic basis), " +
      "decline gracefully with two named reasons per INV-C001 v1.7 instead of computing.",
    parameters: PgsComputeParams,
    outputClass: "summary",
    execute: async (args: Static<typeof PgsComputeParams>, _ctx: AgentToolContext) => {
      return safePost(host, "/v1/pgs/compute", args);
    },
  });

  // ── genomeclaw_pgs_compute_status ───────────────────────────────────
  // Poll an in-flight compute. Status transitions: queued → running →
  // done | failed. On `done`, fetch the result via genomeclaw_pgs_get.
  // The `failed` status carries an error message; one specific failure
  // is `compute_path_disabled` when the user has the kill-switch on.
  api.registerTool({
    name: "genomeclaw_pgs_compute_status",
    description:
      "Check status of an in-flight `genomeclaw_pgs_compute`. Returns one of `queued | running | " +
      "done | failed`. When `done`, fetch the result via `genomeclaw_pgs_get`. `failed` carries " +
      "an `error` field — surface it to the user; one specific failure mode is " +
      "`compute_path_disabled` when the user has set `pgs.compute_enabled false`.",
    parameters: PgsComputeStatusParams,
    outputClass: "summary",
    execute: async (args: Static<typeof PgsComputeStatusParams>, _ctx: AgentToolContext) => {
      return safeCall(host, `/v1/pgs/compute/${encodeURIComponent(args.task_id)}`);
    },
  });

  // Per [spec.md Q3](../../../docs/plans/active/mvp/spec.md) `genomeclaw_report`
  // is deliberately absent — the agent composes report-shaped responses
  // from `genomeclaw_status` + `genomeclaw_findings` + framing knowledge.

  api.logger.info(
    `GenomeClaw plugin registered (9 tools): host=${cfg.hostService.baseUrl}`,
  );
}
