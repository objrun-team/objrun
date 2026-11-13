/**
 * The runtime **shipped to and executed at a destination**.
 *
 * It is an **MCP server** using JSON-RPC over stdio: `initialize` → `tools/list` → `tools/call`.
 * It loads the same `../tools/` implementations as local execution, preventing discrepancies
 * between local and forwarded behavior.
 *
 * ## Why MCP instead of a custom protocol
 *
 * Shipping a binary, starting it, and exchanging one JSON message per stdin/stdout line is
 * exactly MCP stdio. A custom protocol duplicates that work and excludes other clients.
 * This previously happened: the runtime used `{id,tool,args}` and required a dedicated engine client.
 *
 * With MCP, **any MCP client can use this binary**, not just this engine.
 *
 * ## Only protocol messages belong on stdout
 *
 * Capture tool output rather than inheriting child stdout. One stray line can desynchronize
 * the peer's parsing, producing mismatched replies rather than an obvious error. Log to stderr.
 */

import { TOOLS } from "../tools/index.ts";

const by = new Map(TOOLS.map((t) => [t.name, t]));

/** Convert a tool to MCP format using MCP field names. */
const DEFS = TOOLS.map((t) => ({
  name: t.name,
  description: t.does,
  inputSchema: t.params,
  outputSchema: t.output,
}));

const PROTOCOL = "2026-07-28";

async function handle(m: { id?: number; method?: string; params?: unknown }): Promise<unknown | null> {
  const id = m.id;
  const reply = (result: unknown) => ({ jsonrpc: "2.0", id, result });

  if (m.method === "initialize") {
    return reply({
      protocolVersion: String((m.params as { protocolVersion?: string })?.protocolVersion ?? PROTOCOL),
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "tgengin-runtime", version: "1.0.0" },
    });
  }
  if (m.method?.startsWith("notifications/")) return null;
  if (m.method === "tools/list") return reply({ tools: DEFS });

  if (m.method === "tools/call") {
    const p = (m.params ?? {}) as { name?: string; arguments?: Record<string, unknown> };
    const t = by.get(String(p.name));
    // An unknown tool is a **protocol error**; changing arguments cannot fix it.
    if (!t) return { jsonrpc: "2.0", id, error: { code: -32602, message: `this runtime has no tool named ${String(p.name)}` } };
    try {
      const value = await t.run(p.arguments ?? {});
      return reply({
        content: [{ type: "text", text: JSON.stringify(value) }],
        ...(value !== null && typeof value === "object" ? { structuredContent: value } : {}),
      });
    } catch (e) {
      // Return tool failures as **tool execution errors** so callers, usually models, can inspect
      // and correct them. A protocol error would expose only a failed invocation.
      return reply({
        content: [{ type: "text", text: e instanceof Error ? e.message : String(e) }],
        isError: true,
      });
    }
  }

  return { jsonrpc: "2.0", id, error: { code: -32601, message: `unknown method: ${String(m.method)}` } };
}

let buf = "";
/** In-flight calls. **Wait for them even after stdin closes**, or their answers will be lost. */
let inflight = 0;
let ended = false;

function bye(): void {
  if (ended && inflight === 0) process.exit(0);
}

process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  buf += chunk;
  let nl = buf.indexOf("\n");
  while (nl !== -1) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (line) {
      inflight++;
      void (async () => {
        try {
          const out = await handle(JSON.parse(line) as { id?: number; method?: string });
          if (out !== null) process.stdout.write(JSON.stringify(out) + "\n");
        } catch (e) {
          process.stderr.write(`cannot parse this line: ${e instanceof Error ? e.message : String(e)}\n`);
        } finally {
          inflight--;
          bye();
        }
      })();
    }
    nl = buf.indexOf("\n");
  }
});
// Shut down when the pipe closes, but **finish in-flight replies first**. The final request is
// often the slowest, such as bash. Exiting immediately would discard its result and leave the
// caller observing only a missing response.
process.stdin.on("end", () => {
  ended = true;
  bye();
});
