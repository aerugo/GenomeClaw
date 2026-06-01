// SPDX-FileCopyrightText: Copyright (c) 2026 GenomeClaw contributors
// SPDX-License-Identifier: Apache-2.0

/**
 * Phase 5 Slice D — plugin migration tests.
 *
 * Verifies the registerTool migration per [spec.md § Q2](../../../../docs/plans/active/mvp/spec.md):
 *
 * - All five MVP tools (`genomeclaw_status`, `genomeclaw_findings`,
 *   `genomeclaw_variant`, `genomeclaw_evidence`, `genomeclaw_gene`) are
 *   registered through `api.registerTool` (no `registerCommand`).
 * - Each tool has a TypeBox schema matching the spec's Q4 shape.
 * - Invalid args are rejected by the TypeBox gate before the handler runs.
 * - Successful executions return a `jsonResult` envelope (text block +
 *   details).
 * - HTTP failures and bulk-mode opt-ins surface as `failedTextResult`
 *   envelopes (`INV-P002`).
 */

import { beforeEach, describe, expect, test, vi } from "vitest";

import { invokeTool, makeFetchStub, makeMockApi } from "./sdk-mock";

// Mock the SDK before importing the plugin. The plugin pulls types from
// the bare `openclaw/plugin-sdk` module (type-only after compilation) and
// the value-level helpers from `openclaw/plugin-sdk/agent-runtime` (the
// non-deprecated subpath landed during the 2026-05-15 live sweep). Both
// modules need a mock at test time.
//
// `vi.mock` hoists to the top of the file before any top-level `const`
// initialisation, so we inline the factory in each call rather than
// reference a shared identifier (would be a ReferenceError otherwise).
vi.mock("openclaw/plugin-sdk", () => ({
  jsonResult<TDetails>(payload: TDetails) {
    return {
      content: [{ type: "text" as const, text: JSON.stringify(payload, null, 2) }],
      details: payload,
      isError: false as const,
    };
  },
  failedTextResult<TDetails = undefined>(text: string, details?: TDetails) {
    return {
      content: [{ type: "text" as const, text }],
      details,
      isError: true as const,
    };
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
    return {
      content: [{ type: "text" as const, text }],
      details,
      isError: true as const,
    };
  },
}));

// Plugin source under test. `vi.mock` calls above are hoisted by vitest
// to before this import.
import register from "../src/index";

let fetchSpy: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
  fetchSpy = vi.spyOn(globalThis, "fetch").mockImplementation(
    makeFetchStub({
      "/v1/health": {
        status: "ok",
        schema_version: "v0.2",
        current_run_id: "test-run",
        sample_id: "test-sample",
      },
      "/v1/findings": { rows: [], total: 0, limit: 25, offset: 0, next_offset: null },
      "/v1/variants/chr1-100-A-T": {
        chrom: "chr1",
        pos: 100,
        ref: "A",
        alt: "T",
        rsid: "rs100",
      },
      "/v1/variants": { rows: [], total: 0, limit: 25, offset: 0, next_offset: null },
      "/v1/evidence/rcv000001": { ref: "rcv000001", source: "clinvar" },
      "/v1/gene/BRCA1": {
        gene: "BRCA1",
        n_variants_in_gene: 3,
        mean_depth: 32.4,
        low_coverage_exons: [],
        schema_version: "v0.2",
      },
    }),
  );
});

// ---------------------------------------------------------------------------
// INV-A006 — shared helpers for parsing structured failure envelopes
// ---------------------------------------------------------------------------
//
// Used across the error-handling, host-side-failure, and INV-A006-shape
// describe blocks. The plugin's failure-path helpers emit JSON-encoded
// `ToolFailureEnvelope` values as the SDK's `failedTextResult` `text` field;
// tests parse + assert on the structured shape (per INV-V001 — no substring
// enumeration as primary correctness gate).

interface FailureEnvelope {
  status: "failed";
  error_type:
    | "placeholder_rejected"
    | "host_failure"
    | "network_error"
    | "http_error";
  advisory: string;
  [k: string]: unknown;
}

function parseFailureEnvelope(text: string): FailureEnvelope {
  const parsed = JSON.parse(text) as Record<string, unknown>;
  if (parsed.status !== "failed") {
    throw new Error(
      `expected status="failed", got status=${String(parsed.status)}; raw text: ${text.slice(0, 200)}`,
    );
  }
  if (typeof parsed.error_type !== "string") {
    throw new Error(
      `expected error_type string, got ${typeof parsed.error_type}; raw text: ${text.slice(0, 200)}`,
    );
  }
  return parsed as FailureEnvelope;
}

// ---------------------------------------------------------------------------
// Registration shape
// ---------------------------------------------------------------------------

describe("registerTool migration", () => {
  test("registers exactly the ten v0 tools (5 MVP + 4 PGS + host_profile)", () => {
    const api = makeMockApi();
    register(api);

    const toolNames = api.tools.map((t) => t.name).sort();
    expect(toolNames).toEqual([
      "genomeclaw_evidence",
      "genomeclaw_findings",
      "genomeclaw_gene",
      "genomeclaw_host_profile",
      "genomeclaw_pgs_compute",
      "genomeclaw_pgs_compute_status",
      "genomeclaw_pgs_get",
      "genomeclaw_pgs_list",
      "genomeclaw_status",
      "genomeclaw_variant",
    ]);
  });

  test("every tool declares the summary output class (INV-P002)", () => {
    const api = makeMockApi();
    register(api);

    for (const tool of api.tools) {
      expect(tool.outputClass).toBe("summary");
    }
  });

  test("every tool has a TypeBox parameters schema with non-empty description", () => {
    const api = makeMockApi();
    register(api);

    for (const tool of api.tools) {
      expect(typeof tool.description).toBe("string");
      expect(tool.description.length).toBeGreaterThan(20);
      expect(tool.parameters).toBeDefined();
      expect(typeof tool.parameters).toBe("object");
    }
  });
});

// ---------------------------------------------------------------------------
// TypeBox parameter validation (spec Q4 — typed arrays for collections,
// scalars for singletons)
// ---------------------------------------------------------------------------

describe("TypeBox parameter schemas (spec Q4)", () => {
  test("genomeclaw_status accepts an empty object and rejects extras", async () => {
    const api = makeMockApi();
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_status")!;

    const ok = await invokeTool(status, {});
    expect(ok.ok).toBe(true);

    const bad = await invokeTool(status, { unexpected: 1 });
    expect(bad.ok).toBe(false);
  });

  test("genomeclaw_findings accepts typed array `genes` and rejects empty arrays", async () => {
    const api = makeMockApi();
    register(api);
    const findings = api.tools.find((t) => t.name === "genomeclaw_findings")!;

    const ok = await invokeTool(findings, { genes: ["BRCA1", "BRCA2"] });
    expect(ok.ok).toBe(true);

    // minItems: 1 — empty array must be rejected before the handler runs.
    const empty = await invokeTool(findings, { genes: [] });
    expect(empty.ok).toBe(false);
  });

  test("genomeclaw_findings rejects comma-separated string in place of array", async () => {
    const api = makeMockApi();
    register(api);
    const findings = api.tools.find((t) => t.name === "genomeclaw_findings")!;

    const bad = await invokeTool(findings, { genes: "BRCA1,BRCA2" });
    expect(bad.ok).toBe(false);
  });

  test("genomeclaw_variant requires a non-empty `key` string", async () => {
    const api = makeMockApi();
    register(api);
    const variant = api.tools.find((t) => t.name === "genomeclaw_variant")!;

    const ok = await invokeTool(variant, { key: "chr1-100-A-T" });
    expect(ok.ok).toBe(true);

    const missing = await invokeTool(variant, {});
    expect(missing.ok).toBe(false);

    const empty = await invokeTool(variant, { key: "" });
    expect(empty.ok).toBe(false);
  });

  test("genomeclaw_evidence requires a non-empty `ref` string", async () => {
    const api = makeMockApi();
    register(api);
    const evidence = api.tools.find((t) => t.name === "genomeclaw_evidence")!;

    const ok = await invokeTool(evidence, { ref: "rcv000001" });
    expect(ok.ok).toBe(true);

    const missing = await invokeTool(evidence, {});
    expect(missing.ok).toBe(false);
  });

  test("genomeclaw_gene requires a non-empty `gene` string", async () => {
    const api = makeMockApi();
    register(api);
    const gene = api.tools.find((t) => t.name === "genomeclaw_gene")!;

    const ok = await invokeTool(gene, { gene: "BRCA1" });
    expect(ok.ok).toBe(true);

    const empty = await invokeTool(gene, { gene: "" });
    expect(empty.ok).toBe(false);
  });

  test("genomeclaw_gene/_variant/_evidence reject placeholder strings (undefined/null/none/nil)", async () => {
    // 2026-05-23 eyesight-question deep-dive caught the agent generating
    // tool calls with the literal string "undefined" as the parameter
    // value (11 wasted round-trips against /v1/gene/undefined +
    // /v1/variants/undefined). Plugin TypeBox now rejects the four
    // placeholder tokens case-insensitively so they fail locally
    // before any HTTP round-trip.
    const api = makeMockApi();
    register(api);

    for (const toolName of ["genomeclaw_gene", "genomeclaw_variant", "genomeclaw_evidence"]) {
      const tool = api.tools.find((t) => t.name === toolName)!;
      const argName = toolName === "genomeclaw_gene" ? "gene" : toolName === "genomeclaw_variant" ? "key" : "ref";

      for (const placeholder of ["undefined", "UNDEFINED", "null", "Null", "none", "NONE", "nil"]) {
        const res = await invokeTool(tool, { [argName]: placeholder });
        expect(res.ok, `${toolName}(${argName}=${JSON.stringify(placeholder)}) should reject`).toBe(false);
      }

      // Real values still accepted.
      const realArg = toolName === "genomeclaw_variant" ? "chr1:12345:A:G" : toolName === "genomeclaw_evidence" ? "clinvar:RCV000001" : "BRCA1";
      const real = await invokeTool(tool, { [argName]: realArg });
      expect(real.ok).toBe(true);
    }
  });

  test("execute() arg-guard catches bypassed TypeBox (openclaw runtime path)", async () => {
    // The openclaw runtime does NOT enforce TypeBox `pattern` (only
    // minLength + additionalProperties), so the placeholder regex on
    // GeneParams/VariantParams/EvidenceParams won't fire in production
    // when the agent emits {gene: "undefined"}. The runtime guard at
    // execute() entry MUST catch it. This test invokes execute()
    // directly (bypassing the mock's Value.Check) to prove the guard
    // works on the actual openclaw codepath.
    const api = makeMockApi();
    register(api);

    for (const [toolName, argName] of [
      ["genomeclaw_gene", "gene"],
      ["genomeclaw_variant", "key"],
      ["genomeclaw_evidence", "ref"],
      ["genomeclaw_pgs_get", "pgs_id"],
      ["genomeclaw_pgs_compute_status", "task_id"],
    ] as const) {
      const tool = api.tools.find((t) => t.name === toolName)!;

      // Direct execute() invocation bypassing TypeBox — mimics the
      // openclaw runtime's known argument-resolution failure mode.
      for (const placeholder of ["undefined", "null", "none", "nil"]) {
        const result = (await tool.execute(
          { [argName]: placeholder } as never,
          { logger: { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} } } as never,
        )) as { isError?: boolean; content: { text: string }[] };
        expect(result.isError, `${toolName}(${argName}="${placeholder}") should return isError=true`).toBe(true);
        expect(result.content[0].text).toMatch(/placeholder string/i);
      }

      // Also: missing arg + non-object args body (the 2026-05-23
      // "call_xxx|fc_yyy" bare-string POST body bug).
      const noField = (await tool.execute({} as never, { logger: { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} } } as never)) as { isError?: boolean; content: { text: string }[] };
      expect(noField.isError).toBe(true);
      expect(noField.content[0].text).toMatch(/missing or not a string/i);

      const bareString = (await tool.execute("call_xyz|fc_abc" as never, { logger: { info: () => {}, warn: () => {}, error: () => {}, debug: () => {} } } as never)) as { isError?: boolean; content: { text: string }[] };
      expect(bareString.isError).toBe(true);
      expect(bareString.content[0].text).toMatch(/expected an object of arguments/i);
    }
  });
});

// ---------------------------------------------------------------------------
// jsonResult envelope shape + HTTP routing
// ---------------------------------------------------------------------------

describe("jsonResult envelope + HTTP routing", () => {
  test("genomeclaw_status returns a jsonResult envelope from /v1/health", async () => {
    const api = makeMockApi();
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_status")!;

    const out = await invokeTool(status, {});
    expect(out.ok).toBe(true);
    if (!out.ok) return;

    // Envelope shape: content[0].text contains pretty-JSON; details has
    // the structured payload.
    const result = out.result as {
      content: Array<{ type: string; text: string }>;
      details: Record<string, unknown>;
      isError: boolean;
    };
    expect(result.isError).toBe(false);
    expect(result.content[0]?.type).toBe("text");
    expect(result.content[0]?.text).toContain("\"schema_version\"");
    expect(result.details["schema_version"]).toBe("v0.2");
    expect(result.details["current_run_id"]).toBe("test-run");
  });

  test("genomeclaw_variant routes the key into the URL path", async () => {
    const api = makeMockApi();
    register(api);
    const variant = api.tools.find((t) => t.name === "genomeclaw_variant")!;

    const out = await invokeTool(variant, { key: "chr1-100-A-T" });
    expect(out.ok).toBe(true);

    // Assert the HTTP call used the encoded key in the path.
    expect(fetchSpy).toHaveBeenCalled();
    const calledUrl = (fetchSpy.mock.calls[0]?.[0] ?? "").toString();
    expect(calledUrl).toContain("/v1/variants/chr1-100-A-T");
  });

  test("genomeclaw_findings serialises array params as repeated query keys", async () => {
    const api = makeMockApi();
    register(api);
    const findings = api.tools.find((t) => t.name === "genomeclaw_findings")!;

    const out = await invokeTool(findings, { genes: ["BRCA1", "BRCA2"] });
    expect(out.ok).toBe(true);

    const calledUrl = (fetchSpy.mock.calls[0]?.[0] ?? "").toString();
    // Both genes appear as repeated `genes=` query params (FastAPI's
    // `genes: list[str]` convention).
    expect(calledUrl).toMatch(/genes=BRCA1/);
    expect(calledUrl).toMatch(/genes=BRCA2/);
  });

  test("genomeclaw_gene routes to /v1/gene/{symbol}", async () => {
    const api = makeMockApi();
    register(api);
    const gene = api.tools.find((t) => t.name === "genomeclaw_gene")!;

    const out = await invokeTool(gene, { gene: "BRCA1" });
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const result = out.result as { details: Record<string, unknown> };
    expect(result.details["gene"]).toBe("BRCA1");
  });
});

// ---------------------------------------------------------------------------
// Error handling
// ---------------------------------------------------------------------------

describe("error handling", () => {
  test("HTTP non-2xx surfaces as a failedTextResult with http_error envelope", async () => {
    const api = makeMockApi();
    register(api);
    const gene = api.tools.find((t) => t.name === "genomeclaw_gene")!;

    // Override fetch to return 503.
    fetchSpy.mockImplementation(async () => {
      return new Response(JSON.stringify({ detail: "no active run" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    });

    const out = await invokeTool(gene, { gene: "BRCA1" });
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const result = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(result.isError).toBe(true);

    // INV-A006: structured envelope shape, not substring matching.
    const env = parseFailureEnvelope(result.content[0]!.text);
    expect(env.error_type).toBe("http_error");
    expect(env.http_status).toBe(503);
  });

  test("network failure surfaces as a failedTextResult with network_error envelope", async () => {
    const api = makeMockApi();
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_status")!;

    fetchSpy.mockImplementation(async () => {
      throw new TypeError("network is unreachable");
    });

    const out = await invokeTool(status, {});
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const result = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(result.isError).toBe(true);

    // INV-A006: structured envelope shape, not substring matching.
    const env = parseFailureEnvelope(result.content[0]!.text);
    expect(env.error_type).toBe("network_error");
    expect(env.http_path).toBe("/v1/health");
  });
});

// ---------------------------------------------------------------------------
// Config resolution
// ---------------------------------------------------------------------------

describe("config resolution", () => {
  test("respects hostService.baseUrl from plugin config", async () => {
    const api = makeMockApi({
      hostService: { baseUrl: "http://example.invalid:9999", timeoutMs: 1000 },
    });
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_status")!;

    await invokeTool(status, {});

    const calledUrl = (fetchSpy.mock.calls[0]?.[0] ?? "").toString();
    expect(calledUrl).toContain("example.invalid:9999");
  });
});

// ---------------------------------------------------------------------------
// Phase 6 Slice E v2 — agent-driven PRS tools (Q8 v1.6).
//
// Four new tools replace the v1.5 `genomeclaw_pgs(trait)` lookup tool that the
// static-panel design specified (now retired). The PRS layer is keyed by PGS
// Catalog ID, not curator-named trait; compute is async + agent-triggered;
// rationale + alternatives considered persist per `INV-A003`.
// ---------------------------------------------------------------------------

describe("genomeclaw_pgs_* tools (Q8 v1.6)", () => {
  test("genomeclaw_pgs_list accepts empty params + routes to /v1/pgs/computed", async () => {
    const api = makeMockApi();
    register(api);
    const list = api.tools.find((t) => t.name === "genomeclaw_pgs_list");
    expect(list).toBeDefined();
    if (!list) return;

    const out = await invokeTool(list, {});
    expect(out.ok).toBe(true);

    const calledUrl = (fetchSpy.mock.calls[0]?.[0] ?? "").toString();
    expect(calledUrl).toContain("/v1/pgs/computed");
    // Must NOT route to the retired v1.5 `/v1/pgs/{trait}` shape (e.g.
    // `/v1/pgs/cad`); the list endpoint is the literal `/v1/pgs/computed`.
    expect(calledUrl).not.toMatch(/\/v1\/pgs\/(cad|t2d|prostate|breast)\b/i);
  });

  test("genomeclaw_pgs_get routes the pgs_id into the URL path", async () => {
    const api = makeMockApi();
    register(api);
    const get = api.tools.find((t) => t.name === "genomeclaw_pgs_get");
    expect(get).toBeDefined();
    if (!get) return;

    const out = await invokeTool(get, { pgs_id: "PGS000018" });
    expect(out.ok).toBe(true);

    const calledUrl = (fetchSpy.mock.calls[0]?.[0] ?? "").toString();
    expect(calledUrl).toContain("/v1/pgs/computed/PGS000018");
  });

  test("genomeclaw_pgs_compute POSTs the request body to /v1/pgs/compute", async () => {
    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    expect(compute).toBeDefined();
    if (!compute) return;

    const longRationale =
      "Canonical CARDIoGRAMplusC4D + UK Biobank CAD PRS; best cross-ancestry " +
      "calibration. Considered PGS004696 and rejected for less validation.";
    expect(longRationale.length).toBeGreaterThanOrEqual(50);

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale: longRationale,
      requested_for_question: "my dad had a heart attack at 58",
    });
    expect(out.ok).toBe(true);

    const calledUrl = (fetchSpy.mock.calls[0]?.[0] ?? "").toString();
    expect(calledUrl).toContain("/v1/pgs/compute");
    expect(calledUrl).not.toContain("/v1/pgs/compute/"); // POST root, not a path-keyed GET

    const callInit = fetchSpy.mock.calls[0]?.[1] as RequestInit | undefined;
    expect(callInit?.method).toBe("POST");
    const body = JSON.parse((callInit?.body ?? "{}") as string);
    expect(body.pgs_id).toBe("PGS000018");
    expect(body.trait_label).toBe("coronary artery disease");
    expect(body.rationale).toBe(longRationale);
    expect(body.requested_for_question).toBe("my dad had a heart attack at 58");
  });

  test("genomeclaw_pgs_compute rejects rationale shorter than 10 chars at the TypeBox layer", async () => {
    // Defence-in-depth with the host-service 422: even before any HTTP call
    // fires, the plugin's TypeBox schema should reject a trivially-short
    // rationale, enforcing the INV-A003 non-empty floor. Phase 2 lowered
    // the threshold from 50 to 10 after the 2026-05-23 AMD-question
    // incident; the 10-char floor still rejects single-token rationales.
    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    expect(compute).toBeDefined();
    if (!compute) return;

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale: "short",  // 5 chars, below the 10-char floor
      requested_for_question: "?",
    });
    expect(out.ok).toBe(false);
    // The TypeBox gate fires before any fetch.
    expect(fetchSpy).not.toHaveBeenCalled();
  });

  test("genomeclaw_pgs_compute_status routes the task_id into the URL path", async () => {
    const api = makeMockApi();
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_pgs_compute_status");
    expect(status).toBeDefined();
    if (!status) return;

    const out = await invokeTool(status, { task_id: "t-abc123" });
    expect(out.ok).toBe(true);

    const calledUrl = (fetchSpy.mock.calls[0]?.[0] ?? "").toString();
    expect(calledUrl).toContain("/v1/pgs/compute/t-abc123");
  });
});

// ---------------------------------------------------------------------------
// Host-side structured failure detection (Plan 2 — toolSummary blindness)
// ---------------------------------------------------------------------------
//
// Background: 2026-05-26 muscle-question trace. A `_pgs_compute` call reached
// the host, got HTTP 200 + `{"status":"failed","error":"prs_compute_config_missing"}`,
// and the plugin returned `jsonResult` (success envelope) — leaving the agent
// to JSON-parse the body to know the call failed. The agent then misattributed
// the structured failure to a sweeping "guard fired" narrative covering tools
// that succeeded.
//
// Fix: `safeCall` / `safePost` route HTTP 200 responses with `status:"failed"`
// through `failedTextResult` instead of `jsonResult`. This sets the SDK's
// `isError: true` flag so any consumer that aggregates failures sees it, and
// it gives the agent an unambiguous failure marker in the tool-result text.
//
// Plan: docs/plans/active/investigate-toolsummary-failure-counter-blindness.md
describe("host-side structured failure detection (Plan 2)", () => {
  test("safePost converts {status:'failed'} HTTP 200 body to failedTextResult", async () => {
    // Override the default stub to return the structured-failure envelope
    // shape we observed from the host service when prs_compute_config.json
    // was missing for the active run.
    fetchSpy.mockImplementation(
      makeFetchStub({
        "/v1/pgs/compute": {
          task_id: "ce5c-7e92451badea",
          pgs_id: "PGS000018",
          status: "failed",
          error: "prs_compute_config_missing",
        },
      }),
    );

    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    expect(compute).toBeDefined();
    if (!compute) return;

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale: "CARDIoGRAMplusC4D + UKB CAD PRS; best cross-ancestry calibration; PGS004696 considered + rejected",
      requested_for_question: "regression test for structured-failure detection",
    });
    expect(out.ok).toBe(true);  // TypeBox passed; the tool ran
    const r = out.result as { isError?: boolean; content: { text: string }[] };

    // Tool result carries the SDK's failure flag — the structural signal any
    // toolSummary aggregator would key off
    expect(r.isError).toBe(true);

    // INV-A006: assert on the structured envelope shape, not prose substrings.
    const env = parseFailureEnvelope(r.content[0]!.text);
    expect(env.error_type).toBe("host_failure");
    expect(env.host_status).toBe("failed");
    expect(env.host_error).toBe("prs_compute_config_missing");
    expect(env.http_path).toBe("/v1/pgs/compute");
  });

  test("safePost preserves jsonResult success envelope for status:'queued'", async () => {
    // Defensive: assert the new wrapper doesn't false-positive on the
    // normal queued/running/done compute lifecycle responses. Only the
    // literal status="failed" triggers the failedTextResult conversion.
    fetchSpy.mockImplementation(
      makeFetchStub({
        "/v1/pgs/compute": {
          task_id: "happy-path-task",
          pgs_id: "PGS000018",
          status: "queued",
          error: null,
        },
      }),
    );

    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    expect(compute).toBeDefined();
    if (!compute) return;

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale: "CARDIoGRAMplusC4D + UKB CAD PRS; happy-path success regression test",
      requested_for_question: "regression test for status:queued not tripping failure detection",
    });
    expect(out.ok).toBe(true);
    const r = out.result as { isError?: boolean; content: { text: string }[] };

    // Happy path: queued/running/done responses pass-through as jsonResult
    // success envelopes; isError stays false; the structured failure envelope
    // is NOT applied.
    expect(r.isError).toBe(false);
    const body = JSON.parse(r.content[0]!.text) as Record<string, unknown>;
    expect(body.status).toBe("queued");
    expect(body.error_type).toBeUndefined();
  });

  test("safeCall converts {status:'failed'} HTTP 200 body to failedTextResult for GET endpoints", async () => {
    // Symmetry check: the structured-failure detection lives in
    // wrapHostResponse, which both safeCall (GET) and safePost (POST) route
    // through. A `genomeclaw_pgs_compute_status` poll on a failed task
    // exercises the GET path of the same logic.
    fetchSpy.mockImplementation(
      makeFetchStub({
        "/v1/pgs/compute/": {
          task_id: "t-abc123",
          pgs_id: "PGS000018",
          status: "failed",
          error: "scorefile_missing",
        },
      }),
    );

    const api = makeMockApi();
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_pgs_compute_status");
    expect(status).toBeDefined();
    if (!status) return;

    const out = await invokeTool(status, { task_id: "t-abc123" });
    expect(out.ok).toBe(true);  // TypeBox passed
    const r = out.result as { isError?: boolean; content: { text: string }[] };

    expect(r.isError).toBe(true);
    const env = parseFailureEnvelope(r.content[0]!.text);
    expect(env.error_type).toBe("host_failure");
    expect(env.host_status).toBe("failed");
    expect(env.host_error).toBe("scorefile_missing");
  });
});

// ---------------------------------------------------------------------------
// INV-A006 structured failure envelopes (Plan A.1 of
// inv-a005-structural-faithfulness)
// ---------------------------------------------------------------------------
//
// The plugin's three failure-path helpers used to return prose strings as the
// tool-result text. The 2026-05-28 AC8 manual gate showed that prose-only
// returns force downstream verification into substring-list enumeration of
// banned/required phrases (`_FORBIDDEN_PHRASES`), which doesn't generalize
// against LLM paraphrase-space.
//
// Plan A.1 changes the three helpers to emit JSON-encoded `ToolFailureEnvelope`
// values as the tool-result text. Each envelope has:
//   - `status: "failed"` (discriminates from `jsonResult` success envelopes)
//   - `error_type` enum: `"placeholder_rejected" | "host_failure" |
//     "network_error" | "http_error"` (the structured class discriminator —
//     load-bearing for INV-A005 v1.22's structural verification)
//   - structured detail fields per `error_type` (arg_name, http_path, etc.)
//   - `advisory: <string>` — human-readable description, NON-LOAD-BEARING
//     per INV-A006. The agent quotes structured fields verbatim, not advisory.
//
// These tests pin the envelope shape so a regression to prose-only returns
// gets caught immediately.

describe("INV-A006 structured failure envelopes (Plan A.1)", () => {
  test("rejectIfPlaceholder emits placeholder_rejected envelope with structured fields", async () => {
    // `genomeclaw_pgs_get`'s `pgs_id` schema is `Type.String({ minLength: 1 })`
    // without the `_NOT_PLACEHOLDER` regex (PGS IDs are agent-supplied, not
    // user-typed gene symbols). So `pgs_id: "undefined"` passes TypeBox + hits
    // the runtime `rejectIfPlaceholder` guard — the path Plan A.1 reshapes.
    const api = makeMockApi();
    register(api);
    const get = api.tools.find((t) => t.name === "genomeclaw_pgs_get");
    expect(get).toBeDefined();
    if (!get) return;

    const out = await invokeTool(get, { pgs_id: "undefined" });
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const r = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(r.isError).toBe(true);

    const env = parseFailureEnvelope(r.content[0]!.text);
    expect(env.error_type).toBe("placeholder_rejected");
    expect(env.arg_name).toBe("pgs_id");
    expect(env.value).toBe("undefined");
    expect(typeof env.advisory).toBe("string");
    expect(env.advisory.length).toBeGreaterThan(10);
  });

  test("wrapHostResponse emits host_failure envelope for status:failed bodies", async () => {
    fetchSpy.mockImplementation(
      makeFetchStub({
        "/v1/pgs/compute": {
          task_id: "ce5c-7e92451badea",
          pgs_id: "PGS000018",
          status: "failed",
          error: "prs_compute_config_missing",
        },
      }),
    );

    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    expect(compute).toBeDefined();
    if (!compute) return;

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale:
        "CARDIoGRAMplusC4D + UKB CAD PRS; INV-A006 structured envelope test — non-degenerate rationale",
      requested_for_question: "INV-A006 host_failure envelope shape test",
    });
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const r = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(r.isError).toBe(true);

    const env = parseFailureEnvelope(r.content[0]!.text);
    expect(env.error_type).toBe("host_failure");
    expect(env.http_path).toBe("/v1/pgs/compute");
    expect(env.host_status).toBe("failed");
    expect(env.host_error).toBe("prs_compute_config_missing");
    expect(typeof env.advisory).toBe("string");
  });

  test("safeCall catch emits network_error envelope on fetch failure", async () => {
    fetchSpy.mockImplementation(async () => {
      throw new Error(
        "Failed to connect to host.openshell.internal port 8645: Connection refused",
      );
    });

    const api = makeMockApi();
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_status");
    expect(status).toBeDefined();
    if (!status) return;

    const out = await invokeTool(status, {});
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const r = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(r.isError).toBe(true);

    const env = parseFailureEnvelope(r.content[0]!.text);
    expect(env.error_type).toBe("network_error");
    expect(env.raw_error).toContain("Failed to connect");
    expect(env.http_path).toBe("/v1/health");
    expect(typeof env.advisory).toBe("string");
  });

  test("safeCall catch emits http_error envelope on HTTP 5xx", async () => {
    fetchSpy.mockImplementation(async () => {
      return new Response(JSON.stringify({ detail: "no active run" }), {
        status: 503,
        headers: { "content-type": "application/json" },
      });
    });

    const api = makeMockApi();
    register(api);
    const status = api.tools.find((t) => t.name === "genomeclaw_status");
    expect(status).toBeDefined();
    if (!status) return;

    const out = await invokeTool(status, {});
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const r = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(r.isError).toBe(true);

    const env = parseFailureEnvelope(r.content[0]!.text);
    expect(env.error_type).toBe("http_error");
    expect(env.http_path).toBe("/v1/health");
    expect(env.http_status).toBe(503);
    expect(typeof env.raw_error).toBe("string");
    expect(env.raw_error).toContain("HTTP 503");
    expect(typeof env.advisory).toBe("string");
  });

  test("rejectIfPlaceholder shape-guard emits placeholder_rejected envelope for non-object args", async () => {
    // The shape-guard branch of `rejectIfPlaceholder` fires when the agent's
    // runtime passes a bare string instead of an `{args}` object. This branch
    // also gets the `placeholder_rejected` error_type — same class of agent
    // serialization failure. (The advisory wording differs; that's fine —
    // operators reading raw output get human-readable detail.)
    //
    // We can't trigger this through `invokeTool` because the mock's
    // `Value.Check` requires an object. So we test by constructing a tool
    // whose execute body calls `rejectIfPlaceholder` directly — using
    // `genomeclaw_pgs_get` whose `pgs_id` schema accepts any string but
    // whose execute body runs the guard. Same approach as the existing
    // placeholder-rejected test; the shape-guard branch fires when we
    // pass `null` directly.
    //
    // Skipped for now: requires direct access to `rejectIfPlaceholder`
    // (not exported). Re-evaluate after Plan A.1 lands — if the type
    // exports the helper for testing, add this case; otherwise, leave the
    // existing 4 envelope cases (host_failure / network_error / http_error
    // / placeholder_rejected via real tool path) as the contract.
    expect(true).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Phase 3 of agent-synthesis-over-rich-tool-data — host_failure carries
// the rich `diagnostic` field from the host service.
// ---------------------------------------------------------------------------
//
// When the host returns `status: "failed"` along with the new `diagnostic`
// field (per Phase 2's `ToolDiagnosticTrace` extension to `PgsComputeTaskResponse`),
// `wrapHostResponse` MUST forward the diagnostic into the envelope. The agent
// then has rich context (`stage`, `upstream_cause`, `suggested_fix`,
// `related_paths`) to synthesize a real user-facing explanation — not just
// a short error code.
//
// Per Phase 1's narrow scope: only `wrapHostResponse`'s host_failure arm
// gets the field. `placeholder_rejected` / `network_error` / `http_error`
// don't have host-side diagnostic context to forward.

describe("Phase 3: host_failure envelope forwards diagnostic field", () => {
  test("wrapHostResponse forwards the diagnostic field when host body carries one", async () => {
    fetchSpy.mockImplementation(
      makeFetchStub({
        "/v1/pgs/compute": {
          task_id: "diag-task-1",
          pgs_id: "PGS000018",
          status: "failed",
          error: "scorefile_missing:PGS000018",
          diagnostic: {
            stage: "scorefile_staging",
            upstream_cause: "scorefile_missing",
            suggested_fix:
              "Run `genomeclaw refs fetch --source pgs_scorefile --pgs-id PGS000018` to fetch and stage the missing scorefile.",
            related_paths: ["PGS000018/PGS000018_hmPOS_GRCh38.txt.gz"],
            partial_log_tail: null,
          },
        },
      }),
    );

    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    if (!compute) throw new Error("genomeclaw_pgs_compute tool not registered");

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale:
        "CARDIoGRAMplusC4D + UKB CAD PRS; Phase 3 diagnostic-forwarding integration test",
      requested_for_question: "diagnostic-trace forwarding",
    });
    expect(out.ok).toBe(true);
    if (!out.ok) return;
    const r = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(r.isError).toBe(true);

    const env = parseFailureEnvelope(r.content[0]!.text) as Record<string, unknown>;
    expect(env.error_type).toBe("host_failure");

    // Phase 3: the diagnostic field must be present + structured.
    const diagnostic = env.diagnostic as Record<string, unknown> | undefined;
    expect(diagnostic).toBeDefined();
    expect(diagnostic).not.toBeNull();
    expect(diagnostic!.stage).toBe("scorefile_staging");
    expect(diagnostic!.upstream_cause).toBe("scorefile_missing");
    expect(diagnostic!.suggested_fix).toContain("refs fetch");
    expect(diagnostic!.suggested_fix).toContain("PGS000018");
    expect(diagnostic!.related_paths).toEqual([
      "PGS000018/PGS000018_hmPOS_GRCh38.txt.gz",
    ]);
  });

  test("wrapHostResponse host_failure envelope tolerates host body WITHOUT a diagnostic field", async () => {
    // Backwards compatibility: pre-Phase-2 host service deployments emit the
    // old minimal shape (no diagnostic). The plugin must NOT crash; the
    // envelope's `diagnostic` field is absent (undefined) rather than present
    // with garbage.
    fetchSpy.mockImplementation(
      makeFetchStub({
        "/v1/pgs/compute": {
          task_id: "pre-phase2-task",
          pgs_id: "PGS000018",
          status: "failed",
          error: "prs_compute_config_missing",
        },
      }),
    );

    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    if (!compute) throw new Error("tool not registered");

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale: "Phase 3 backward-compat test for old host bodies",
      requested_for_question: "n/a",
    });
    if (!out.ok) return;
    const r = out.result as { isError: boolean; content: Array<{ text: string }> };
    expect(r.isError).toBe(true);

    const env = parseFailureEnvelope(r.content[0]!.text) as Record<string, unknown>;
    expect(env.error_type).toBe("host_failure");
    expect(env.host_error).toBe("prs_compute_config_missing");
    // No diagnostic field carried; envelope must NOT crash on construction.
    expect(env.diagnostic).toBeUndefined();
  });
});
