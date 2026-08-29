/**
 * 一个本机浏览器标签页上的那几个工具。
 *
 * ```
 * bun examples/place/tab-server.ts <那一页的链接> [调试端口]
 * ```
 *
 * 链接是**这个地方的身份**，所以要整条给，不是给一截让它去猜 —— 同时开着两个
 * deck 的时候，猜会连错一个，而且连错了看不出来。
 *
 * ## 它连的是什么
 *
 * Chrome 带 `--remote-debugging-port=9222` 起着的时候，`GET /json/list` 会列出
 * 所有开着的标签页，每一个带一个 `webSocketDebuggerUrl`。连上那条 WS 就是
 * CDP —— 这儿只用一个方法：`Runtime.evaluate`，在**那一个标签页**里求值。
 *
 * ## 为什么不做成通用的浏览器工具
 *
 * 这四个工具是**这一页**的操作面：`deck.html` 自己在 `window.deck` 上摆出了
 * `next / prev / goto / state`，工具照着调。换一页就是另一套工具 —— 页面定操作面，
 * 工具只负责把它接出来。做成 `browser_click(x, y)` 那种通用的，模型就得自己猜
 * 这一页长什么样。
 *
 * ## 跟 workplace 的关系
 *
 * 引擎那边这个地方叫 `tab:deck`（一行 `workplace`）；浏览器那边它是哪个标签页，
 * 由这个 server 的参数说了算。两边各自认各自的，中间靠**声明**对上：
 * 工具的 `when` 写 `dim: place, op: eq, value: tab:deck`。
 *
 * 这个地方 `forward` 是关的 —— 工具不用转发到别处去，它本来就在本机。
 */

const LINK = process.argv[2] ?? "";
const PORT = Number(process.argv[3] ?? 9222);
if (!LINK) {
  process.stderr.write("要给那一页的链接：bun tab-server.ts <url> [调试端口]\n");
  process.exit(1);
}

interface Target {
  id: string;
  type: string;
  url: string;
  title: string;
  webSocketDebuggerUrl?: string;
}

const TOOLS = [
  {
    name: "deck_state",
    description: "看这一页现在翻到第几张、一共几张、这张叫什么",
    inputSchema: { type: "object", properties: {} },
    outputSchema: {
      type: "object",
      properties: { page: { type: "integer" }, total: { type: "integer" }, title: { type: "string" } },
    },
  },
  {
    name: "deck_next",
    description: "往后翻一张",
    inputSchema: { type: "object", properties: {} },
    outputSchema: {
      type: "object",
      properties: { page: { type: "integer" }, total: { type: "integer" }, title: { type: "string" } },
    },
  },
  {
    name: "deck_prev",
    description: "往前翻一张",
    inputSchema: { type: "object", properties: {} },
    outputSchema: {
      type: "object",
      properties: { page: { type: "integer" }, total: { type: "integer" }, title: { type: "string" } },
    },
  },
  {
    name: "deck_goto",
    description: "直接翻到第几张",
    inputSchema: {
      type: "object",
      properties: { page: { type: "integer", description: "第几张，从 1 起" } },
      required: ["page"],
    },
    outputSchema: {
      type: "object",
      properties: { page: { type: "integer" }, total: { type: "integer" }, title: { type: "string" } },
    },
  },
];

// ── CDP ──────────────────────────────────────────────────────────────────

let ws: WebSocket | null = null;
let seq = 0;
const waiting = new Map<number, { ok(v: unknown): void; fail(e: Error): void }>();

async function target(): Promise<Target> {
  let list: Target[];
  try {
    list = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()) as Target[];
  } catch {
    throw new Error(`连不上 127.0.0.1:${PORT} —— 浏览器得带 --remote-debugging-port=${PORT} 起着`);
  }
  const pages = list.filter((t) => t.type === "page");
  const hit = pages.find((t) => t.url === LINK);
  if (!hit) {
    const open = pages.map((t) => t.url).join("、") || "（一个都没开）";
    throw new Error(`没有哪个标签页是 ${LINK}。现在开着的是：${open}`);
  }
  return hit;
}

let opening: Promise<WebSocket> | null = null;
let live: string | null = null;

/**
 * 连一条，**只连一条** —— 同时来三个调用不该开出三条 WS 各排各的队。
 *
 * 每次都先 `target()` 核一遍那条链接。**同一个标签页导航到别处，target id 不变、
 * WS 也不断**，缓存着直接用的话，求值会落在新页上：拿回来的是
 * 「window.deck 是 undefined」，看着像页面写坏了，其实是这个地方已经不在了。
 */
async function socket(): Promise<WebSocket> {
  const t = await target();
  if (ws && ws.readyState === WebSocket.OPEN && live === t.id) return ws;
  opening ??= open(t).finally(() => {
    opening = null;
  });
  return await opening;
}

async function open(t: Target): Promise<WebSocket> {
  if (!t.webSocketDebuggerUrl) throw new Error(`${t.url} 没给调试地址`);
  const s = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise<void>((ok, fail) => {
    s.onopen = () => ok();
    s.onerror = () => fail(new Error(`连不上那个标签页：${t.url}`));
  });
  s.onmessage = (e: MessageEvent) => {
    const m = JSON.parse(String(e.data)) as { id?: number; result?: unknown; error?: { message?: string } };
    if (m.id === undefined) return; // CDP 的事件，没人在等
    const w = waiting.get(m.id);
    if (!w) return;
    waiting.delete(m.id);
    if (m.error) w.fail(new Error(m.error.message ?? "CDP 报错"));
    else w.ok(m.result);
  };
  // 标签页关了、刷新了、浏览器退了 —— 在途的全得结掉，不然调用方挂到超时。
  s.onclose = () => {
    for (const w of waiting.values()) w.fail(new Error("那个标签页的连接断了"));
    waiting.clear();
    ws = null;
    live = null;
  };
  ws = s;
  live = t.id;
  process.stderr.write(`[tab] 接上了 ${t.title}｜${t.url}\n`);
  return s;
}

/** 在那个标签页里求值。**页面自己抛的错原样带回来** —— 不然只看到「没成」。 */
async function evaluate(expr: string): Promise<unknown> {
  const s = await socket();
  const id = ++seq;
  const res = (await new Promise((ok, fail) => {
    waiting.set(id, { ok, fail });
    s.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression: expr, returnByValue: true, awaitPromise: true } }));
  })) as { result?: { value?: unknown }; exceptionDetails?: { text?: string; exception?: { description?: string } } };
  if (res.exceptionDetails) {
    const d = res.exceptionDetails;
    throw new Error(`页面里报错：${d.exception?.description ?? d.text ?? "?"}`);
  }
  return res.result?.value;
}

async function call(name: string, a: Record<string, unknown>): Promise<unknown> {
  const expr =
    name === "deck_state" ? "window.deck.state()"
    : name === "deck_next" ? "window.deck.next()"
    : name === "deck_prev" ? "window.deck.prev()"
    : `window.deck.goto(${Number(a.page ?? 1)})`;
  const got = await evaluate(expr);
  if (got === undefined || got === null) {
    throw new Error("这一页上没有 window.deck —— 标签页对上了，但不是那份 deck");
  }
  process.stderr.write(`[tab] ${name} → ${JSON.stringify(got)}\n`);
  return got;
}

// ── MCP ──────────────────────────────────────────────────────────────────

async function handle(m: { id?: number; method?: string; params?: unknown }): Promise<unknown | null> {
  const reply = (result: unknown) => ({ jsonrpc: "2.0", id: m.id, result });

  if (m.method === "initialize") {
    return reply({
      protocolVersion: "2026-07-28",
      capabilities: { tools: { listChanged: false } },
      serverInfo: { name: "tab-server", version: "1.0.0" },
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
      // 标签页关了、页面换了 —— 是这一次没干成，不是协议错。走 isError，
      // 模型看得见原因，也就知道不该接着翻。
      const why = e instanceof Error ? e.message : String(e);
      process.stderr.write(`[tab] 没干成：${why}\n`);
      return reply({ content: [{ type: "text", text: why }], isError: true });
    }
  }

  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `不认得这个方法：${String(m.method)}` } };
}

process.stderr.write(`[tab] 起来了，认 ${LINK}，调试端口 ${PORT}\n`);
let buf = "";
// 在途几个。stdin 关了就该收摊，但**手上还有没答完的不能走** ——
// 那条 WS 会把进程一直吊着，所以收摊这件事得自己数着来。
let busy = 0;
let bye = false;
function maybeBye(): void {
  if (bye && busy === 0) {
    ws?.close();
    process.exit(0);
  }
}
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk: string) => {
  buf += chunk;
  let nl = buf.indexOf("\n");
  while (nl !== -1) {
    const line = buf.slice(0, nl).trim();
    buf = buf.slice(nl + 1);
    if (line) {
      busy++;
      void handle(JSON.parse(line) as { id?: number; method?: string }).then((out) => {
        if (out !== null) process.stdout.write(JSON.stringify(out) + "\n");
        busy--;
        maybeBye();
      });
    }
    nl = buf.indexOf("\n");
  }
});
process.stdin.on("end", () => {
  bye = true;
  maybeBye();
});
