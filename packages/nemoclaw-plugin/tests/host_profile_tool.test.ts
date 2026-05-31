// SPDX-FileCopyrightText: Copyright (c) 2026 GenomeClaw contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * host-profile-personal-context Phase 3 — `genomeclaw_host_profile` tool.
 *
 * Verifies the tool registration, TypeBox param contract, the plugin-side
 * section guard (known-sections mirror + placeholder rejection), and the
 * INV-A005 missing-signal pass-through (HTTP 200 + `missing: true` is a
 * structured no-profile signal, NOT a tool failure).
 */

import { beforeEach, describe, expect, test, vi } from "vitest";

import { invokeTool, makeMockApi } from "./sdk-mock";

vi.mock("openclaw/plugin-sdk", () => ({
  jsonResult<TDetails>(payload: TDetails) {
    return {
      content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }],
      details: payload,
      isError: false as const,
    };
  },
  failedTextResult<TDetails = undefined>(text: string, details?: TDetails) {
    return { content: [{ type: "text" as const, text }], details, isError: true as const };
  },
}));

vi.mock("openclaw/plugin-sdk/agent-runtime", () => ({
  jsonResult<TDetails>(payload: TDetails) {
    return {
      content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }],
      details: payload,
      isError: false as const,
    };
  },
  failedTextResult<TDetails = undefined>(text: string, details?: TDetails) {
    return { content: [{ type: "text" as const, text }], details, isError: true as const };
  },
}));

import register from "../src/index";
import type { RegisteredTool } from "./sdk-mock";

function getTool(): RegisteredTool {
  const api = makeMockApi();
  register(api);
  const tool = api.tools.find((t) => t.name === "genomeclaw_host_profile");
  if (!tool) throw new Error("genomeclaw_host_profile not registered");
  return tool;
}

/** Stub fetch with a per-path (status, body) so we can exercise 200 + 500. */
function stubFetch(routes: Record<string, { status: number; body: unknown }>): void {
  vi.spyOn(globalThis, "fetch").mockImplementation(
    async (input: string | URL | Request): Promise<Response> => {
      const url = typeof input === "string" ? input : input.toString();
      for (const [path, resp] of Object.entries(routes)) {
        if (url.includes(path)) {
          return new Response(JSON.stringify(resp.body), {
            status: resp.status,
            headers: { "content-type": "application/json" },
          });
        }
      }
      return new Response(JSON.stringify({ detail: "not found" }), { status: 404 });
    },
  );
}

interface FailureEnvelope {
  status: "failed";
  error_type: string;
  [k: string]: unknown;
}

function parseFailure(result: unknown): FailureEnvelope {
  const r = result as { isError?: boolean; content: { text: string }[] };
  expect(r.isError).toBe(true);
  return JSON.parse(r.content[0].text) as FailureEnvelope;
}

beforeEach(() => {
  stubFetch({
    "/v1/host/profile": {
      status: 200,
      body: { profile: { schema_version: "host_profile/1.0" }, missing: false },
    },
  });
});

describe("genomeclaw_host_profile registration", () => {
  test("is registered with summary output_class", () => {
    expect(getTool().outputClass).toBe("summary");
  });

  test("description names the missing-signal + sections contract", () => {
    const desc = getTool().description;
    expect(desc.length).toBeGreaterThan(40);
    expect(desc).toContain("missing");
    expect(desc).toContain("sections");
  });
});

describe("genomeclaw_host_profile params", () => {
  test("accepts empty params (full profile)", async () => {
    const res = await invokeTool(getTool(), {});
    expect(res.ok).toBe(true);
  });

  test("accepts a sections array", async () => {
    const res = await invokeTool(getTool(), { sections: ["medical_history.medications"] });
    expect(res.ok).toBe(true);
  });

  test("rejects unknown property (additionalProperties: false)", async () => {
    const res = await invokeTool(getTool(), { bogus: true });
    expect(res.ok).toBe(false);
  });
});

describe("genomeclaw_host_profile section guard", () => {
  test("rejects an unknown section name with the known-sections list", async () => {
    const res = await invokeTool(getTool(), { sections: ["medical_history.dragons"] });
    expect(res.ok).toBe(true); // TypeBox passes (it's a string); the guard fires inside execute
    const env = parseFailure((res as { ok: true; result: unknown }).result);
    expect(env.error_type).toBe("unknown_section");
    expect(Array.isArray(env.known_sections)).toBe(true);
    expect(env.known_sections as string[]).toContain("medical_history.medications");
  });

  test("rejects a placeholder section name", async () => {
    const res = await invokeTool(getTool(), { sections: ["undefined"] });
    expect(res.ok).toBe(true);
    const env = parseFailure((res as { ok: true; result: unknown }).result);
    expect(env.error_type).toBe("placeholder_rejected");
  });
});

describe("genomeclaw_host_profile responses", () => {
  test("returns the missing-signal body verbatim (NOT an error) — INV-A005", async () => {
    stubFetch({
      "/v1/host/profile": {
        status: 200,
        body: { missing: true, init_command: "genomeclaw host profile init" },
      },
    });
    const res = await invokeTool(getTool(), {});
    expect(res.ok).toBe(true);
    const r = (res as { ok: true; result: { isError?: boolean; details: Record<string, unknown> } })
      .result;
    expect(r.isError).toBeFalsy();
    expect(r.details.missing).toBe(true);
    expect(r.details.init_command).toBe("genomeclaw host profile init");
  });

  test("surfaces a host-side 500 as a failure envelope", async () => {
    stubFetch({ "/v1/host/profile": { status: 500, body: { error: "host_profile_corrupted" } } });
    const res = await invokeTool(getTool(), {});
    expect(res.ok).toBe(true);
    const env = parseFailure((res as { ok: true; result: unknown }).result);
    expect(env.error_type).toBe("http_error");
    expect(env.http_status).toBe(500);
  });
});
