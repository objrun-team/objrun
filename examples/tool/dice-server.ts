/** 写法二：进程外的 MCP server。stdio 上的 JSON-RPC。 */
const TOOL = {
  name: "dice_out",
  description: "Roll an n-sided die (out of process)",
  inputSchema: {
    type: "object",
    properties: { sides: { type: "integer", description: "How many sides" } },
    required: ["sides"],
  },
  outputSchema: {
    type: "object",
    properties: { sides: { type: "integer" }, value: { type: "integer" } },
  },
};

function handle(m: { id?: number; method?: string; params?: unknown }): unknown | null {
  const reply = (result: unknown) => ({ jsonrpc: "2.0", id: m.id, result });

  if (m.method === "initialize") {
    return reply({
      protocolVersion: "2026-07-28",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "dice-server", version: "1.0.0" },
    });
  }
  if (m.method?.startsWith("notifications/")) return null;
  if (m.method === "tools/list") return reply({ tools: [TOOL] });

  if (m.method === "tools/call") {
    const p = (m.params ?? {}) as { name?: string; arguments?: { sides?: number } };
    if (p.name !== TOOL.name) {
      return { jsonrpc: "2.0", id: m.id, error: { code: -32602, message: `no such tool: ${String(p.name)}` } };
    }
    const sides = Number(p.arguments?.sides ?? 6);
    const value = 1 + Math.floor(Math.random() * sides);
    process.stderr.write(`[dice-server] sides=${sides} → ${value}\n`);
    const out = { sides, value, from: "mcp" };
    return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out });
  }

  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `unknown method: ${String(m.method)}` } };
}

process.stderr.write("[dice-server] up\n");
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
