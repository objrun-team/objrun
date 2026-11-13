/**
 * Join a meeting. An MCP server with one tool: `meet_join`.
 *
 * After joining successfully, it **registers another server** (`meet-live`) to expose the two tools available only inside the meeting. It uses `/declare`, the same endpoint used from the terminal.
 */

const BASE = process.env.TGENGIN_BASE ?? "http://127.0.0.1:7801/api";
const LIVE = "examples/meet-join/meet-live.ts";

const TOOL = {
  name: "meet_join",
  description: "Join a meeting that is already booked. The in-meeting tools appear only once you are in",
  inputSchema: {
    type: "object",
    properties: { meetUrl: { type: "string", description: "https://meet.google.com/xxx-xxxx-xxx" } },
    required: ["meetUrl"],
  },
  outputSchema: {
    type: "object",
    properties: {
      ok: { type: "boolean" },
      meetId: { type: "string" },
      handles: { type: "array", items: { type: "string" } },
    },
  },
};

async function join(meetUrl: string): Promise<unknown> {
  if (!/^https:\/\/meet\.google\.com\//.test(meetUrl)) {
    return { isError: true, text: "that is not a Meet address; it looks like https://meet.google.com/xxx-xxxx-xxx" };
  }
  const meetId = meetUrl.split("/").pop() ?? "?";
  process.stderr.write(`[meet] joining ${meetId}\n`);

  const res = await fetch(`${BASE}/declare`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      servers: [
        {
          name: "meet-live",
          command: "bun",
          args: [LIVE, meetId],
          tools: {
            say: { when: [[{ dim: "task", key: "description", op: "contains", value: "meeting" }]] },
            screen: { when: [[{ dim: "task", key: "description", op: "contains", value: "meeting" }]] },
          },
        },
      ],
    }),
  });
  const got = (await res.json()) as { servers?: Record<string, string[]>; problems?: string[] };
  if (got.problems) {
    process.stderr.write(`[meet] cannot attach them: ${got.problems.join("; ")}\n`);
    return { isError: true, text: `joined, but the in-meeting tools cannot be attached: ${got.problems.join("; ")}` };
  }

  const handles = (got.servers?.["meet-live"] ?? []).map((t) => `mcp:meet-live/${t}`);
  process.stderr.write(`[meet] grew ${handles.join(", ")}\n`);
  return { ok: true, meetId, handles };
}

function reply(id: number | undefined, result: unknown) {
  return { jsonrpc: "2.0", id, result };
}

async function handle(m: { id?: number; method?: string; params?: unknown }): Promise<unknown | null> {
  if (m.method === "initialize") {
    return reply(m.id, {
      protocolVersion: "2026-07-28",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "meet", version: "1.0.0" },
    });
  }
  if (m.method?.startsWith("notifications/")) return null;
  if (m.method === "tools/list") return reply(m.id, { tools: [TOOL] });

  if (m.method === "tools/call") {
    const p = (m.params ?? {}) as { name?: string; arguments?: { meetUrl?: string } };
    if (p.name !== TOOL.name) {
      return { jsonrpc: "2.0", id: m.id, error: { code: -32602, message: `no such tool: ${String(p.name)}` } };
    }
    const out = (await join(String(p.arguments?.meetUrl ?? ""))) as { isError?: boolean; text?: string };
    if (out.isError) {
      return reply(m.id, { content: [{ type: "text", text: String(out.text) }], isError: true });
    }
    return reply(m.id, {
      content: [{ type: "text", text: JSON.stringify(out) }],
      structuredContent: out,
    });
  }
  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `unknown method: ${String(m.method)}` } };
}

process.stderr.write("[meet] up\n");
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
