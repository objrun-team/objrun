/**
 * 一个 **MCP server**：操作一台已登录的浏览器，进一个已预约的会。
 *
 * ```
 * bun examples/tool/meetkit.ts          # stdio，被引擎当子进程起
 * PORT=7899 bun examples/tool/meetkit.ts --http   # 或者 HTTP
 * ```
 *
 * 说的是标准 MCP：`initialize` → `tools/list` → `tools/call`，JSON-RPC。
 * 所以它不只这台引擎能用 —— 任何 MCP 客户端都能。
 *
 * 浏览器和会议是假的（真的那套是 puppeteer + Google Meet），协议是真的。
 */

const TOOLS = [
  {
    name: "browser_status",
    description: "那台常驻浏览器连上没有、登录没有",
    inputSchema: { type: "object", additionalProperties: false },
    outputSchema: {
      type: "object",
      properties: { running: { type: "boolean" }, loggedIn: { type: "boolean" } },
    },
  },
  {
    name: "meet_join",
    description: "进一个已经预约好的会",
    inputSchema: {
      type: "object",
      properties: { meetUrl: { type: "string", description: "https://meet.google.com/xxx-xxxx-xxx" } },
      required: ["meetUrl"],
    },
    outputSchema: {
      type: "object",
      properties: { ok: { type: "boolean" }, meetId: { type: "string" } },
    },
  },
  {
    name: "share_open",
    description: "在会上共享一份材料，返回这份材料的操作契约",
    inputSchema: {
      type: "object",
      properties: { url: { type: "string" } },
      required: ["url"],
    },
    outputSchema: { type: "object", properties: { contract: { type: "object" } } },
  },
  {
    name: "meet_leave",
    description: "离开会议",
    inputSchema: { type: "object", additionalProperties: false },
    outputSchema: { type: "object", properties: { ok: { type: "boolean" } } },
  },
];

/** 现在在哪个会里。**活状态，不进库。** */
let inMeeting: string | null = null;

function call(name: string, args: Record<string, unknown>): { value: unknown; isError?: boolean } {
  if (name === "browser_status") {
    return { value: { running: true, profile: "meetkit-chrome", loggedIn: true } };
  }
  if (name === "meet_join") {
    const url = String(args.meetUrl ?? "");
    if (!/^https:\/\/meet\.google\.com\//.test(url)) {
      // MCP 里这叫**工具执行错**：模型看了能自己改，所以当结果回，不当协议错。
      return { value: "这不是一个 Meet 地址，形如 https://meet.google.com/xxx-xxxx-xxx", isError: true };
    }
    inMeeting = url.split("/").pop() ?? "?";
    return { value: { ok: true, meetId: inMeeting } };
  }
  if (name === "share_open") {
    if (!inMeeting) return { value: "还没进会，先调 meet_join", isError: true };
    // 每份材料自己声明一份操作契约：能做哪些操作、各自对应什么键鼠输入。
    // 操作工具包是格式无关的纯键鼠，认的就是这份契约。
    return {
      value: {
        contract: {
          type: "deck",
          state: { page: 1, total: 12, heading: "开场" },
          operations: [
            { name: "next", input: "press('ArrowRight')" },
            { name: "prev", input: "press('ArrowLeft')" },
            { name: "goto", input: "type('12')" },
          ],
        },
      },
    };
  }
  if (name === "meet_leave") {
    inMeeting = null;
    return { value: { ok: true } };
  }
  return { value: `没有这个工具：${name}`, isError: true };
}

/** 一条 JSON-RPC 进来，一条出去。回 `null` = 这是个通知，不用回。 */
function handle(m: { id?: number; method?: string; params?: unknown }): unknown | null {
  const reply = (result: unknown) => ({ jsonrpc: "2.0", id: m.id, result });

  if (m.method === "initialize") {
    return reply({
      protocolVersion: (m.params as { protocolVersion?: string })?.protocolVersion ?? "2026-07-28",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "meetkit", version: "0.1.0" },
    });
  }
  if (m.method === "tools/list") return reply({ tools: TOOLS });
  if (m.method === "tools/call") {
    const p = (m.params ?? {}) as { name?: string; arguments?: Record<string, unknown> };
    const r = call(String(p.name), p.arguments ?? {});
    process.stderr.write(`← ${p.name} ${JSON.stringify(p.arguments ?? {})}\n`);
    // 结构化的那一份对着 outputSchema；同时给一份文本，老客户端也读得了。
    return reply({
      content: [{ type: "text", text: typeof r.value === "string" ? r.value : JSON.stringify(r.value) }],
      ...(typeof r.value === "object" && r.value !== null ? { structuredContent: r.value } : {}),
      ...(r.isError ? { isError: true } : {}),
    });
  }
  if (m.method?.startsWith("notifications/")) return null;
  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `不认得这个方法：${m.method}` } };
}

if (process.argv.includes("--http")) {
  const port = Number(process.env.PORT ?? 7899);
  Bun.serve({
    port,
    async fetch(req) {
      const m = (await req.json()) as { id?: number; method?: string; params?: unknown };
      const out = handle(m);
      return out === null ? new Response(null, { status: 202 }) : Response.json(out);
    },
  });
  process.stderr.write(`meetkit（HTTP）听在 http://127.0.0.1:${port}\n`);
} else {
  // stdio：一行一条 JSON-RPC。**日志只能往 stderr 写** —— stdout 是协议本身，
  // 往里打一个字就把这条流搅了。
  process.stderr.write("meetkit（stdio）起来了\n");
  let buf = "";
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk: string) => {
    buf += chunk;
    let nl = buf.indexOf("\n");
    while (nl !== -1) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) {
        try {
          const out = handle(JSON.parse(line) as { id?: number; method?: string });
          if (out !== null) process.stdout.write(JSON.stringify(out) + "\n");
        } catch (e) {
          process.stderr.write(`解不开这一行：${e instanceof Error ? e.message : String(e)}\n`);
        }
      }
      nl = buf.indexOf("\n");
    }
  });
}
