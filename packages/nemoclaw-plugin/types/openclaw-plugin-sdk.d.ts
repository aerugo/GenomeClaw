// SPDX-FileCopyrightText: Copyright (c) 2026 GenomeClaw contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Local stub of the `openclaw/plugin-sdk` types we depend on.
 *
 * The real SDK is provided by the NemoClaw sandbox base image at runtime
 * (under `/sandbox/.openclaw/extensions/...`). It is not published to npm,
 * so local typecheck + vitest need this stub to compile.
 *
 * The shape mirrors the documented `registerTool` API recovered from the
 * 2026-04-24 in-sandbox investigation (see [spec.md § Q2](../../../docs/plans/active/mvp/spec.md)):
 *
 * - `registerTool({ name, description, parameters, execute })` registers an
 *   agent-callable tool. `parameters` is a TypeBox schema. `execute` is the
 *   handler receiving the parsed-and-validated arguments and the tool
 *   context; it returns an `AgentToolResult<TDetails>` envelope.
 * - `jsonResult(payload)` builds the result envelope: the JSON-pretty-
 *   printed payload becomes a `content[{type:'text', text}]` block, and
 *   the structured `payload` is preserved in `details`.
 * - `failedTextResult(text, details?)` builds an error envelope.
 *
 * Keep this file mechanical: any field used by `src/index.ts` lands here;
 * everything else stays absent on purpose so a future drift between
 * `index.ts` and the real SDK surfaces as a type error rather than
 * silently widening the stub.
 */

declare module "openclaw/plugin-sdk" {
  import type { TSchema, Static } from "@sinclair/typebox";

  /** Bag the runtime hands the plugin's `register` entry point. */
  export interface OpenClawPluginApi {
    /** Free-form per-plugin config from the runtime (validated against `configSchema`). */
    readonly pluginConfig?: Record<string, unknown>;
    /** Structured logger; trace levels match the manifest's `logVerbosity` config. */
    readonly logger: PluginLogger;
    /** Registers an agent-callable tool. May be invoked once per tool. */
    registerTool<TParams extends TSchema, TDetails>(
      tool: AgentTool<TParams, TDetails>,
    ): void;
  }

  /** Minimal logger surface; the SDK provides more methods in practice. */
  export interface PluginLogger {
    info(...args: unknown[]): void;
    warn(...args: unknown[]): void;
    error(...args: unknown[]): void;
    debug(...args: unknown[]): void;
  }

  /** One agent-callable tool registration record. */
  export interface AgentTool<TParams extends TSchema, TDetails> {
    /** Tool identifier exposed to the agent (e.g. `genomeclaw_status`). */
    name: string;
    /** Human-readable description; the agent uses this for tool selection. */
    description: string;
    /** TypeBox schema describing the tool's parameters object. */
    parameters: TParams;
    /** `summary` (default) or `bulk` per `INV-P002`. */
    outputClass?: "summary" | "bulk";
    /** Handler called with parsed-and-validated arguments + tool context. */
    execute(
      args: Static<TParams>,
      ctx: AgentToolContext,
    ): Promise<AgentToolResult<TDetails>> | AgentToolResult<TDetails>;
  }

  /** Runtime context handed to each `execute` call. */
  export interface AgentToolContext {
    /** Stable id for tracing (logs, audit). */
    readonly traceId?: string;
    /** Configured logger; per-call context augments the registration-time logger. */
    readonly logger: PluginLogger;
  }

  /** Envelope shape returned by `jsonResult` / `failedTextResult`. */
  export interface AgentToolResult<TDetails> {
    /** LLM-visible content array. v0 always carries exactly one text block. */
    content: AgentToolContentBlock[];
    /** Structured payload preserved for runtime consumers; not LLM-visible. */
    details?: TDetails;
    /** Whether the tool call succeeded. Built-in helpers set this correctly. */
    isError?: boolean;
  }

  /** One block in `AgentToolResult.content`. v0 only uses `type: 'text'`. */
  export interface AgentToolContentBlock {
    type: "text";
    text: string;
  }

  /**
   * Build a successful tool result.
   *
   * Pretty-prints `payload` as JSON into the LLM-visible text block and
   * preserves `payload` in `details` for runtime consumers.
   */
  export function jsonResult<TDetails>(
    payload: TDetails,
  ): AgentToolResult<TDetails>;

  /**
   * Build a failed tool result.
   *
   * `text` becomes the LLM-visible error message; optional `details`
   * carries structured context for the runtime (e.g. error codes,
   * upstream HTTP status).
   */
  export function failedTextResult<TDetails = undefined>(
    text: string,
    details?: TDetails,
  ): AgentToolResult<TDetails>;
}

declare module "openclaw/plugin-sdk/agent-runtime" {
  // The non-deprecated location of jsonResult + failedTextResult per the
  // 2026.4.24 SDK + the migration guide at
  // https://docs.openclaw.ai/plugins/sdk-migration. Other helpers exist
  // here too; we only re-declare what `src/index.ts` imports.
  import type { AgentToolResult } from "openclaw/plugin-sdk";

  export function jsonResult<TDetails>(payload: TDetails): AgentToolResult<TDetails>;
  export function failedTextResult<TDetails = undefined>(
    text: string,
    details?: TDetails,
  ): AgentToolResult<TDetails>;
}
