// SPDX-FileCopyrightText: Copyright (c) 2026 GenomeClaw contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * In-test mock of `openclaw/plugin-sdk`.
 *
 * The real SDK is provided by the NemoClaw sandbox base image at runtime;
 * local tests need an implementation that matches the documented contract
 * (see [spec.md § Q2](../../../../docs/plans/active/mvp/spec.md) and
 * [types/openclaw-plugin-sdk.d.ts](../../types/openclaw-plugin-sdk.d.ts)).
 *
 * `jsonResult(payload)` pretty-prints `payload` into a `content[].text`
 * block and preserves `payload` in `details`. `failedTextResult(text, ...)`
 * builds an error envelope. The real SDK's TypeBox-validation step is
 * mirrored by `Value.Check` here so invalid arguments fail the same way
 * they would in production.
 */

import { Value } from "@sinclair/typebox/value";
import type { Static, TSchema } from "@sinclair/typebox";

export interface RegisteredTool<TParams extends TSchema = TSchema, TDetails = unknown> {
  name: string;
  description: string;
  parameters: TParams;
  outputClass?: "summary" | "bulk";
  execute(
    args: Static<TParams>,
    ctx: { logger: typeof loggerStub },
  ): Promise<unknown> | unknown;
}

export const loggerStub = {
  info: (..._args: unknown[]): void => undefined,
  warn: (..._args: unknown[]): void => undefined,
  error: (..._args: unknown[]): void => undefined,
  debug: (..._args: unknown[]): void => undefined,
};

export interface MockApi {
  pluginConfig?: Record<string, unknown>;
  logger: typeof loggerStub;
  tools: RegisteredTool[];
  registerTool<TParams extends TSchema, TDetails>(
    tool: RegisteredTool<TParams, TDetails>,
  ): void;
}

export function makeMockApi(pluginConfig?: Record<string, unknown>): MockApi {
  const api: MockApi = {
    logger: loggerStub,
    tools: [],
    registerTool<TParams extends TSchema, TDetails>(
      tool: RegisteredTool<TParams, TDetails>,
    ): void {
      api.tools.push(tool as unknown as RegisteredTool);
    },
  };
  if (pluginConfig !== undefined) {
    api.pluginConfig = pluginConfig;
  }
  return api;
}

/**
 * Invoke a registered tool's `execute` after validating args through the
 * tool's TypeBox schema — the same gate the real SDK applies before the
 * handler runs.
 */
export async function invokeTool(
  tool: RegisteredTool,
  args: unknown,
): Promise<{ ok: true; result: unknown } | { ok: false; reason: string }> {
  if (!Value.Check(tool.parameters, args)) {
    return {
      ok: false,
      reason: `parameter validation failed: ${[...Value.Errors(tool.parameters, args)].map((e) => e.message).join("; ")}`,
    };
  }
  const result = await Promise.resolve(
    tool.execute(args as never, { logger: loggerStub }),
  );
  return { ok: true, result };
}

/** Build a fake `fetch` that returns the given map of `path → response body`. */
export function makeFetchStub(routes: Record<string, unknown>): typeof fetch {
  return async (input: string | URL | Request): Promise<Response> => {
    const url = typeof input === "string" ? input : input.toString();
    for (const [path, body] of Object.entries(routes)) {
      // Match path-prefix so callers can register `/v1/variants` for both
      // list + single-variant routes when needed.
      if (url.includes(path)) {
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "content-type": "application/json" },
        });
      }
    }
    return new Response(JSON.stringify({ detail: "not found" }), {
      status: 404,
      headers: { "content-type": "application/json" },
    });
  };
}
