// SPDX-FileCopyrightText: Copyright (c) 2026 GenomeClaw contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * GenomeClaw — OpenClaw plugin for NemoClaw.
 *
 * Registers a small surface of agent-callable commands that proxy to a
 * host-side genomeclaw-service exposing minimal-sufficient JSON over HTTP.
 *
 * Conformance:
 * - INV-D001 / INV-D002: this plugin never reads raw genomic files. All access
 *   is via the host service over the configured network policy preset.
 * - INV-E001: every emitted finding/observation is bound to an evidence
 *   reference returned by the host service.
 * - INV-P001 / INV-P002: tool outputs default to the "summary" output class.
 *   Bulk variants of any command are reserved and require explicit per-call
 *   opt-in (not implemented in v0).
 * - INV-R001: provenance metadata is forwarded verbatim from the host
 *   service into every tool result.
 *
 * v0 design note on tool returns:
 *   OpenClaw plugin command handlers return PluginCommandResult, which has
 *   `text` and `mediaUrl(s)` fields. Until structured tool returns are
 *   confirmed (see docs/reference/architecture.md §Open issues), this plugin
 *   JSON-encodes results inside `text` with a "GENOMECLAW_JSON: " prefix so
 *   the agent can parse them deterministically.
 */

// NOTE: openclaw/plugin-sdk is provided by the OpenClaw runtime inside the
// sandbox. We import only the types here; at build time you'll likely want
// `npm install --save-peer openclaw` (or whatever the published name is) to
// satisfy TypeScript without bundling the SDK.
import type {
  OpenClawPluginApi,
  PluginCommandContext,
  PluginCommandResult,
} from "openclaw/plugin-sdk";

// ---------------------------------------------------------------------------
// Plugin runtime config (sourced from plugins.entries.genomeclaw.config.*)
// ---------------------------------------------------------------------------

interface HostServiceConfig {
  baseUrl: string;
  timeoutMs: number;
}

type OutputClass = "summary" | "bulk";

interface PluginRuntimeConfig {
  hostService: HostServiceConfig;
  outputClass: OutputClass;
  logVerbosity: "error" | "warn" | "info" | "debug";
}

const DEFAULT_CONFIG: PluginRuntimeConfig = {
  hostService: {
    baseUrl: "http://host.openshell.internal:8643",
    timeoutMs: 5000,
  },
  outputClass: "summary",
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
    outputClass:
      raw["outputClass"] === "bulk" ? "bulk" : DEFAULT_CONFIG.outputClass,
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
// ---------------------------------------------------------------------------

async function callHostService(
  cfg: HostServiceConfig,
  path: string,
  query?: Record<string, string>,
): Promise<unknown> {
  const url = new URL(path, cfg.baseUrl);
  if (query) {
    for (const [k, v] of Object.entries(query)) {
      url.searchParams.set(k, v);
    }
  }
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), cfg.timeoutMs);
  try {
    const res = await fetch(url.toString(), {
      method: "GET",
      headers: { Accept: "application/json" },
      signal: ctrl.signal,
    });
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

// ---------------------------------------------------------------------------
// Result encoding (v0: JSON-in-text with marker prefix)
// ---------------------------------------------------------------------------

const JSON_MARKER = "GENOMECLAW_JSON: ";
const ERROR_MARKER = "GENOMECLAW_ERROR: ";

function encodeResult(payload: unknown): PluginCommandResult {
  return { text: JSON_MARKER + JSON.stringify(payload) };
}

function encodeError(reason: string): PluginCommandResult {
  return { text: ERROR_MARKER + reason };
}

// ---------------------------------------------------------------------------
// Argument parsing
//
// OpenClaw command handlers receive a single `args` string. We accept simple
// `key=value` whitespace-separated tokens for v0; this is good enough for
// scoping queries (e.g. `category=pgx limit=20`) and avoids depending on a
// JSON parser in the agent's argument shape until structured tool args are
// confirmed.
// ---------------------------------------------------------------------------

function parseArgs(s: string | undefined): Record<string, string> {
  const out: Record<string, string> = {};
  if (!s) return out;
  for (const tok of s.split(/\s+/g).filter(Boolean)) {
    const eq = tok.indexOf("=");
    if (eq > 0) {
      out[tok.slice(0, eq)] = tok.slice(eq + 1);
    }
  }
  return out;
}

// Reject any arg that smells like a bulk-mode opt-in until INV-P002 bulk
// flow is designed and reviewed.
function rejectBulkAttempts(
  args: Record<string, string>,
): PluginCommandResult | undefined {
  if (args["class"] === "bulk" || args["bulk"] === "true") {
    return encodeError(
      "bulk output class is reserved (INV-P002); not enabled in v0",
    );
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Plugin entry point
// ---------------------------------------------------------------------------

export default function register(api: OpenClawPluginApi): void {
  const cfg = resolveConfig(api);

  // ── genomeclaw_status ────────────────────────────────────────────────
  // Health + active run-id + schema version. Always summary class.
  api.registerCommand({
    name: "genomeclaw_status",
    description:
      "Show GenomeClaw host service status: gateway health, active derived-store run-id, schema version, last refresh time. Output is summary class.",
    acceptsArgs: false,
    handler: async () => {
      try {
        const result = await callHostService(cfg.hostService, "/v1/health");
        return encodeResult(result);
      } catch (err) {
        return encodeError(err instanceof Error ? err.message : String(err));
      }
    },
  });

  // ── genomeclaw_findings ──────────────────────────────────────────────
  // Scoped findings list. Args (key=value, whitespace-separated):
  //   category=<...>   one of: pgx, acmg-sf, mendelian, complex
  //   limit=<n>        max rows (host service caps this)
  //   gene=<symbol>    filter to a specific gene
  api.registerCommand({
    name: "genomeclaw_findings",
    description:
      "Return scoped findings as structured JSON (summary class). " +
      "Args: category=<pgx|acmg-sf|mendelian|complex> limit=<n> gene=<symbol>. " +
      "Each finding includes evidence references and a clinical-escalation marker where applicable.",
    acceptsArgs: true,
    handler: async (ctx: PluginCommandContext) => {
      const args = parseArgs(ctx.args);
      const reject = rejectBulkAttempts(args);
      if (reject) return reject;
      try {
        const result = await callHostService(
          cfg.hostService,
          "/v1/findings",
          args,
        );
        return encodeResult(result);
      } catch (err) {
        return encodeError(err instanceof Error ? err.message : String(err));
      }
    },
  });

  // ── genomeclaw_variant ───────────────────────────────────────────────
  // Single-variant lookup by canonical key (e.g., chr-pos-ref-alt or rsid).
  api.registerCommand({
    name: "genomeclaw_variant",
    description:
      "Look up a single variant by canonical key. Args: key=<chr-pos-ref-alt|rsid>. " +
      "Returns the normalized variant record plus its annotation set (summary class).",
    acceptsArgs: true,
    handler: async (ctx: PluginCommandContext) => {
      const args = parseArgs(ctx.args);
      const reject = rejectBulkAttempts(args);
      if (reject) return reject;
      const key = args["key"];
      if (!key) return encodeError("missing required arg: key");
      try {
        const result = await callHostService(
          cfg.hostService,
          `/v1/variants/${encodeURIComponent(key)}`,
        );
        return encodeResult(result);
      } catch (err) {
        return encodeError(err instanceof Error ? err.message : String(err));
      }
    },
  });

  // ── genomeclaw_evidence ──────────────────────────────────────────────
  // Fetch a single evidence record by reference id.
  api.registerCommand({
    name: "genomeclaw_evidence",
    description:
      "Fetch a single evidence record by reference id. Args: ref=<evidence-id>. " +
      "Use this to expand a citation surfaced by genomeclaw_findings.",
    acceptsArgs: true,
    handler: async (ctx: PluginCommandContext) => {
      const args = parseArgs(ctx.args);
      const reject = rejectBulkAttempts(args);
      if (reject) return reject;
      const ref = args["ref"];
      if (!ref) return encodeError("missing required arg: ref");
      try {
        const result = await callHostService(
          cfg.hostService,
          `/v1/evidence/${encodeURIComponent(ref)}`,
        );
        return encodeResult(result);
      } catch (err) {
        return encodeError(err instanceof Error ? err.message : String(err));
      }
    },
  });

  // ── genomeclaw_report ────────────────────────────────────────────────
  // Drafts a report from a scoped findings set. v0 returns the structured
  // assembly metadata only (sections, finding ids, evidence refs); the agent
  // is expected to render the prose because rendering belongs to the agent
  // layer, not to GenomeClaw (INV-C001 framing stays in agent prompts).
  api.registerCommand({
    name: "genomeclaw_report",
    description:
      "Assemble a report skeleton: sections, finding ids per section, evidence refs, " +
      "clinical-escalation markers. Args: scope=<pgx|acmg-sf|all>. The agent renders " +
      "the prose using its own report-writing template; this tool only returns the structure.",
    acceptsArgs: true,
    handler: async (ctx: PluginCommandContext) => {
      const args = parseArgs(ctx.args);
      const reject = rejectBulkAttempts(args);
      if (reject) return reject;
      try {
        const result = await callHostService(
          cfg.hostService,
          "/v1/report",
          args,
        );
        return encodeResult(result);
      } catch (err) {
        return encodeError(err instanceof Error ? err.message : String(err));
      }
    },
  });

  // ── Startup banner ───────────────────────────────────────────────────
  api.logger.info("");
  api.logger.info("  ┌─────────────────────────────────────────────────────┐");
  api.logger.info("  │  GenomeClaw plugin registered (v0)                   │");
  api.logger.info(
    `  │  Host service: ${cfg.hostService.baseUrl.padEnd(36)} │`,
  );
  api.logger.info(`  │  Output class: ${cfg.outputClass.padEnd(36)} │`);
  api.logger.info(
    "  │  Tools: genomeclaw_status, genomeclaw_findings,      │",
  );
  api.logger.info(
    "  │         genomeclaw_variant, genomeclaw_evidence,     │",
  );
  api.logger.info(
    "  │         genomeclaw_report                            │",
  );
  api.logger.info("  └─────────────────────────────────────────────────────┘");
  api.logger.info("");
}
