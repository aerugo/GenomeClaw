#!/usr/bin/env node
/*
 * SSRF-runtime probe script (ssrf-runtime-probe Phase 1).
 *
 * Issues one outbound HTTP request via the policy-allowlisted Node
 * runtime and emits a single line of JSON to stdout classifying the
 * outcome. The pytest harness `docker exec`s this script per probe
 * tuple, parses the JSON, and asserts the rejection_class matches the
 * tuple's expected outcome.
 *
 * Usage:
 *   node probe_script.js --host <h> --port <p> --method <m> --path <P>
 *
 * Output (always exit 0 — the test interprets the JSON):
 *   {
 *     "status": <number|null>,         // HTTP status code, or null on conn fail
 *     "body_excerpt": <string>,        // first 500 chars of body (or error msg)
 *     "rejection_class": <string>,     // one of the classes below
 *     "openclaw_version_line": <string>,
 *     "elapsed_ms": <number>,
 *     "tuple": {host, port, method, path}
 *   }
 *
 * rejection_class values:
 *   - allow_ok                       — HTTP 2xx returned
 *   - deny_internal_address          — body contains "internal address" / RFC1918 guard
 *   - deny_host_not_allowlisted      — body contains "host not" / "not in policy"
 *   - deny_port_not_allowlisted      — body contains "port not"
 *   - deny_path_not_allowlisted      — body contains "path not" / "method not"
 *   - deny_other                     — any other non-2xx OR connection failure
 *
 * The classifier is intentionally body-fragment-based for Phase 1; Phase 2
 * promotes the fragments to a pinned golden baseline (tools/openshell/
 * probe-output.txt) backed by OpenShellConventions.verified_against_version.
 */

const { execSync } = require("node:child_process");

function parseArgs(argv) {
    const out = {};
    for (let i = 2; i < argv.length; i += 2) {
        const key = argv[i].replace(/^--/, "");
        out[key] = argv[i + 1];
    }
    if (!out.host || !out.port || !out.method) {
        throw new Error(
            `usage: probe_script.js --host <h> --port <p> --method <m> --path <P>; got ${JSON.stringify(out)}`
        );
    }
    out.port = parseInt(out.port, 10);
    out.path = out.path || "/";
    return out;
}

function classify(status, bodyExcerpt) {
    if (status >= 200 && status < 300) return "allow_ok";
    const b = (bodyExcerpt || "").toLowerCase();
    if (b.includes("internal address")) return "deny_internal_address";
    if (b.includes("host not") || b.includes("not in policy") || b.includes("host_not_allowed")) {
        return "deny_host_not_allowlisted";
    }
    if (b.includes("port not") || b.includes("port_not_allowed")) {
        return "deny_port_not_allowlisted";
    }
    if (b.includes("path not") || b.includes("method not") || b.includes("path_not_allowed")) {
        return "deny_path_not_allowlisted";
    }
    return "deny_other";
}

function getOpenclawVersionLine() {
    try {
        return execSync("openclaw --version 2>&1 | head -1", { encoding: "utf8" }).trim();
    } catch {
        return "<openclaw --version unavailable>";
    }
}

async function main() {
    const args = parseArgs(process.argv);
    const url = `http://${args.host}:${args.port}${args.path}`;
    const t0 = Date.now();
    let status = null;
    let bodyExcerpt = "";
    try {
        const ctrl = new AbortController();
        const tid = setTimeout(() => ctrl.abort(), 8000);
        const r = await fetch(url, { method: args.method, signal: ctrl.signal });
        clearTimeout(tid);
        status = r.status;
        const body = await r.text().catch(() => "");
        bodyExcerpt = body.slice(0, 500);
    } catch (e) {
        bodyExcerpt = `<fetch error: ${e && e.message ? e.message : String(e)}>`;
    }
    const elapsedMs = Date.now() - t0;
    const result = {
        status,
        body_excerpt: bodyExcerpt,
        rejection_class: classify(status, bodyExcerpt),
        openclaw_version_line: getOpenclawVersionLine(),
        elapsed_ms: elapsedMs,
        tuple: { host: args.host, port: args.port, method: args.method, path: args.path },
    };
    process.stdout.write(JSON.stringify(result) + "\n");
}

main().catch((e) => {
    process.stdout.write(JSON.stringify({
        status: null,
        body_excerpt: `<probe script crash: ${e && e.message ? e.message : String(e)}>`,
        rejection_class: "deny_other",
        openclaw_version_line: getOpenclawVersionLine(),
        elapsed_ms: 0,
        tuple: {},
    }) + "\n");
});
