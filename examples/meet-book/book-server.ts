/** 写法二：进程外的 MCP server。stdio 上的 JSON-RPC。两个工具体跟写法一是同一份代码。 */

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
    description: `${LOGIN_DOES}（进程外）`,
    inputSchema: LOGIN_PARAMS,
    outputSchema: LOGIN_OUTPUT,
  },
  {
    name: "meet_book_out",
    description: `${BOOK_DOES}（进程外）`,
    inputSchema: BOOK_PARAMS,
    outputSchema: BOOK_OUTPUT,
  },
];

async function call(name: string, a: Record<string, unknown>): Promise<unknown> {
  if (name === "google_login_out") {
    const got = await authStart();
    process.stderr.write(`[book-server] 授权：${got.note}\n`);
    return { ...got, from: "mcp" };
  }
  process.stderr.write(`[book-server] 开会 ${JSON.stringify(a)}\n`);
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
      return { jsonrpc: "2.0", id: m.id, error: { code: -32602, message: `没有这个工具：${String(p.name)}` } };
    }
    try {
      const out = await call(String(p.name), p.arguments ?? {});
      return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out });
    } catch (e) {
      // 工具自己没干成，不是协议错 —— 走 isError，让模型看得见原因、自己换个招。
      const why = e instanceof Error ? e.message : String(e);
      process.stderr.write(`[book-server] 没干成：${why}\n`);
      return reply({ content: [{ type: "text", text: why }], isError: true });
    }
  }

  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `不认得这个方法：${String(m.method)}` } };
}

process.stderr.write("[book-server] 起来了\n");
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
