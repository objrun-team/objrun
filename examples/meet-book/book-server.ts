/** Approach 2: an out-of-process MCP server using JSON-RPC over stdio. Both tool bodies share the code used by approach 1. */

import {
  authStart,
  book,
  LOGIN_DOES,
  LOGIN_PARAMS,
  LOGIN_OUTPUT,
  BOOK_DOES,
  BOOK_PARAMS,
  BOOK_OUTPUT,
} from "./google.ts";

const TOOLS = [
  {
    name: "google_login_out",
    description: `${LOGIN_DOES} (out of process)`,
    inputSchema: LOGIN_PARAMS,
    outputSchema: LOGIN_OUTPUT,
  },
  {
    name: "meet_book_out",
    description: `${BOOK_DOES} (out of process)`,
    inputSchema: BOOK_PARAMS,
    outputSchema: BOOK_OUTPUT,
  },
];

async function call(name: string, a: Record<string, unknown>): Promise<unknown> {
  if (name === "google_login_out") {
    const got = await authStart();
    process.stderr.write(`[book-server] authorisation: ${got.note}\n`);
    return { ...got, from: "mcp" };
  }
  process.stderr.write(`[book-server] booking ${JSON.stringify(a)}\n`);
  const got = await book(a as Parameters<typeof book>[0]);
  process.stderr.write(`[book-server] → ${got.meetUrl}\n`);
  return { ...got, from: "mcp" };
}

async function handle(m: { id?: number; method?: string; params?: unknown }): Promise<unknown | null> {
  const reply = (result: unknown) => ({ jsonrpc: "2.0", id: m.id, result });

  if (m.method === "initialize") {
    return reply({
      protocolVersion: "2026-07-28",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "book-server", version: "1.0.0" },
    });
  }
  if (m.method?.startsWith("notifications/")) return null;
  if (m.method === "tools/list") return reply({ tools: TOOLS });

  if (m.method === "tools/call") {
    const p = (m.params ?? {}) as { name?: string; arguments?: Record<string, unknown> };
    if (!TOOLS.some((t) => t.name === p.name)) {
      return { jsonrpc: "2.0", id: m.id, error: { code: -32602, message: `no such tool: ${String(p.name)}` } };
    }
    try {
      const out = await call(String(p.name), p.arguments ?? {});
      return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out });
    } catch (e) {
      // A tool failure is not a protocol error. Use isError so the model sees the cause and can try another approach.
      const why = e instanceof Error ? e.message : String(e);
      process.stderr.write(`[book-server] failed: ${why}\n`);
      return reply({ content: [{ type: "text", text: why }], isError: true });
    }
  }

  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `unknown method: ${String(m.method)}` } };
}

process.stderr.write("[book-server] up\n");
let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  buf += chunk;
  let nl = buf.indexOf("\n");
  while (nl !== -1) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (line) {
      void handle(JSON.parse(line) as { id?: number; method?: string }).then((out) => {
        if (out !== null) process.stdout.write(JSON.stringify(out) + "\n");
      });
    }
    nl = buf.indexOf("\n");
  }
});
