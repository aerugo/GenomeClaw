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
// Registration shape
// ---------------------------------------------------------------------------

describe("registerTool migration", () => {
  test("registers exactly the nine v0 tools (5 MVP + 4 PGS per Q8 v1.6)", () => {
    const api = makeMockApi();
    register(api);

    const toolNames = api.tools.map((t) => t.name).sort();
    expect(toolNames).toEqual([
      "genomeclaw_evidence",
      "genomeclaw_findings",
      "genomeclaw_gene",
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
  test("HTTP non-2xx surfaces as a failedTextResult envelope", async () => {
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
    expect(result.content[0]?.text.toLowerCase()).toContain("503");
  });

  test("network failure surfaces as a failedTextResult envelope", async () => {
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
    expect(result.content[0]?.text).toContain("network");
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

  test("genomeclaw_pgs_compute rejects rationale shorter than 50 chars at the TypeBox layer", async () => {
    // Defence-in-depth with the host-service 422: even before any HTTP call
    // fires, the plugin's TypeBox schema should reject a short rationale,
    // forcing the agent's `INV-A003` "alternatives considered" contract.
    const api = makeMockApi();
    register(api);
    const compute = api.tools.find((t) => t.name === "genomeclaw_pgs_compute");
    expect(compute).toBeDefined();
    if (!compute) return;

    const out = await invokeTool(compute, {
      pgs_id: "PGS000018",
      trait_label: "coronary artery disease",
      rationale: "too short",
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
