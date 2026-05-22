// Slice E live verification harness: load the compiled plugin inside the
// sandbox image's Node runtime, intercept the `openclaw/plugin-sdk` import
// with a mock, invoke `register`, and assert the registered tool surface
// matches Phase 5 Slice D's contract.

// Use a custom loader hook to intercept the SDK import.
import { register as registerLoader } from "node:module";
import { pathToFileURL } from "node:url";

// The plugin (post-Slice-D) imports value-level helpers from the
// `openclaw/plugin-sdk/agent-runtime` subpath (the non-deprecated location of
// jsonResult + failedTextResult per the 2026-05-15 live sweep). Both bare
// `openclaw/plugin-sdk` and the agent-runtime subpath get mocked here so the
// harness works against any plugin version (Slice D and beyond).
registerLoader(
  "data:text/javascript;base64," +
    Buffer.from(
      `
      const MOCK_SDK_URL = "data:text/javascript;base64," + Buffer.from(
        \`
        export function jsonResult(payload) {
          return {
            content: [{ type: "text", text: JSON.stringify(payload, null, 2) }],
            details: payload,
            isError: false,
          };
        }
        export function failedTextResult(text, details) {
          return {
            content: [{ type: "text", text }],
            details,
            isError: true,
          };
        }
      \`).toString("base64");

      const MOCKED_SPECIFIERS = new Set([
        "openclaw/plugin-sdk",
        "openclaw/plugin-sdk/agent-runtime",
      ]);

      export async function resolve(specifier, context, nextResolve) {
        if (MOCKED_SPECIFIERS.has(specifier)) {
          return { url: MOCK_SDK_URL, shortCircuit: true, format: "module" };
        }
        return nextResolve(specifier, context);
      }
    `,
    ).toString("base64"),
  pathToFileURL("/"),
);

// Phase 5 Slice E switched the install path from
//   /sandbox/.openclaw/extensions/genomeclaw/dist/index.js  (cp pattern)
// to
//   /opt/genomeclaw/dist/index.js                            (plugins install --link)
// Agent-research-and-synthesis Phase 1 preserved this; the harness uses the
// link target directly so it works regardless of where openclaw's index points.
const pluginPath = "/opt/genomeclaw/dist/index.js";
const mod = await import(pluginPath);

// Build a stub OpenClawPluginApi that captures registered tools.
const tools = [];
const api = {
  pluginConfig: {
    hostService: { baseUrl: "http://host.openshell.internal:8643", timeoutMs: 5000 },
  },
  logger: {
    info: (...args) => console.log("[info]", ...args),
    warn: (...args) => console.log("[warn]", ...args),
    error: (...args) => console.log("[error]", ...args),
    debug: () => {},
  },
  registerTool(tool) {
    tools.push({
      name: tool.name,
      outputClass: tool.outputClass,
      description_length: tool.description.length,
      has_parameters: !!tool.parameters,
      has_execute: typeof tool.execute === "function",
    });
  },
};

const result = mod.default(api);
console.log("---");
console.log("tools registered:", tools.length);
for (const t of tools) {
  console.log("  *", JSON.stringify(t));
}

// Assertions matching the Slice E.1 contract (Slice D's 5 tools + the
// 4 `genomeclaw_pgs_*` tools added when the agent-driven PRS surface
// landed). The PRS bootstrap-meta cascade kept the count at 9.
const expected = [
  "genomeclaw_status",
  "genomeclaw_findings",
  "genomeclaw_variant",
  "genomeclaw_evidence",
  "genomeclaw_gene",
  "genomeclaw_pgs_list",
  "genomeclaw_pgs_get",
  "genomeclaw_pgs_compute",
  "genomeclaw_pgs_compute_status",
];
const actualNames = tools.map((t) => t.name).sort();
const expectedSorted = [...expected].sort();
if (JSON.stringify(actualNames) !== JSON.stringify(expectedSorted)) {
  console.error("FAIL: tool name set mismatch");
  console.error("  expected:", expectedSorted);
  console.error("  actual:  ", actualNames);
  process.exit(1);
}
for (const t of tools) {
  if (t.outputClass !== "summary") {
    console.error(`FAIL: ${t.name} outputClass is ${t.outputClass}, expected 'summary'`);
    process.exit(1);
  }
  if (!t.has_parameters || !t.has_execute) {
    console.error(`FAIL: ${t.name} missing parameters or execute`);
    process.exit(1);
  }
}
console.log("PASS: 9 tools registered with summary outputClass + TypeBox params + execute");
