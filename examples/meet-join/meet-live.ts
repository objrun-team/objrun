/**
 * The two in-meeting tools. **They exist only after joining**: `meet_join` starts this server.
 *
 * ```
 * bun examples/meet-join/meet-live.ts <meeting-id>
 * ```
 */

const MEET = process.argv[2] ?? "?";

const TOOLS = [
  {
    name: "say",
    description: `Say a line in the meeting (${MEET})`,
    inputSchema: { type: "object", properties: { text: { type: "string" } }, required: ["text"] },
    outputSchema: { type: "object", properties: { ok: { type: "boolean" }, meet: { type: "string" } } },
  },
  {
    name: "screen",
    description: `Share a document and return its operating contract (${MEET})`,
    inputSchema: { type: "object", properties: { url: { type: "string" } }, required: ["url"] },
    outputSchema: { type: "object", properties: { contract: { type: "object" } } },
  },
];

function call(name: string, a: Record<string, unknown>): unknown {
  if (name === "say") {
    process.stderr.write(`[meet-live ${MEET}] say「${String(a.text ?? "")}」\n`);
    return { ok: true, meet: MEET, said: a.text };
  }
  process.stderr.write(`[meet-live ${MEET}] screen ${String(a.url ?? "")}\n`);
  return {
    meet: MEET,
    contract: {
      type: "deck",
      state: { page: 1, total: 12 },
      operations: [
        { name: "next", input: "press('ArrowRight')" },
        { name: "prev", input: "press('ArrowLeft')" },
        { name: "goto", input: "type('12')" },
      ],
    },
  };
}

function handle(m: { id?: number; method?: string; params?: unknown }): unknown | null {
  const reply = (result: unknown) => ({ jsonrpc: "2.0", id: m.id, result });
  if (m.method === "initialize") {
    return reply({
      protocolVersion: "2026-07-28",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "meet-live", version: "1.0.0" },
    });
  }
  if (m.method?.startsWith("notifications/")) return null;
  if (m.method === "tools/list") return reply({ tools: TOOLS });
  if (m.method === "tools/call") {
    const p = (m.params ?? {}) as { name?: string; arguments?: Record<string, unknown> };
    if (!TOOLS.some((t) => t.name === p.name)) {
      return { jsonrpc: "2.0", id: m.id, error: { code: -32602, message: `no such tool: ${String(p.name)}` } };
    }
    const out = call(String(p.name), p.arguments ?? {});
    return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out });
  }
  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `unknown method: ${String(m.method)}` } };
}

process.stderr.write(`[meet-live ${MEET}] up\n`);
let buf = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  buf += chunk;
  let nl = buf.indexOf("\n");
  while (nl !== -1) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (line) {
      const out = handle(JSON.parse(line) as { id?: number; method?: string });
      if (out !== null) process.stdout.write(JSON.stringify(out) + "\n");
    }
    nl = buf.indexOf("\n");
  }
});
