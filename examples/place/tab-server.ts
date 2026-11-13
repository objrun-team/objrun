/**
 * Tools for one tab in the local browser.
 *
 * ```
 * bun examples/place/tab-server.ts <page-url> [debug-port]
 * ```
 *
 * The URL is **the place’s identity**, so provide it in full, not a fragment to guess from. With two decks open, guessing can connect to the wrong one without making the error apparent.
 *
 * ## What it connects to
 *
 * When Chrome runs with `--remote-debugging-port=9222`, `GET /json/list` lists all open tabs, each with a `webSocketDebuggerUrl`. Connecting to that WebSocket gives CDP. This server uses only `Runtime.evaluate`, evaluating code in **that specific tab**.
 *
 * ## Why not generic browser tools?
 *
 * These four tools are **this page’s interface**: `deck.html` exposes `next / prev / goto / state` on `window.deck`, and tools call those methods. A different page supplies a different tool set: the page defines the interface, and tools expose it. Generic `browser_click(x, y)` tools would make the model guess the page’s layout.
 *
 * ## Relationship to workplace
 *
 * The engine calls this place `tab:deck` (one `workplace` row); this server’s arguments identify its browser tab. Each side uses its own identity, joined by **declaration**: tools specify `dim: place, op: eq, value: tab:deck` in `when`.
 *
 * `forward` is disabled for this place: the tools already run locally and need no remote forwarding.
 */

const LINK = process.argv[2] ?? "";
const PORT = Number(process.argv[3] ?? 9222);
if (!LINK) {
  process.stderr.write("the page link is required: bun tab-server.ts <url> [debug port]\n");
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
    description: "Which slide this page is on, how many there are, and what this one is called",
    inputSchema: { type: "object", properties: {} },
    outputSchema: {
      type: "object",
      properties: { page: { type: "integer" }, total: { type: "integer" }, title: { type: "string" } },
    },
  },
  {
    name: "deck_next",
    description: "Go one slide forward",
    inputSchema: { type: "object", properties: {} },
    outputSchema: {
      type: "object",
      properties: { page: { type: "integer" }, total: { type: "integer" }, title: { type: "string" } },
    },
  },
  {
    name: "deck_prev",
    description: "Go one slide back",
    inputSchema: { type: "object", properties: {} },
    outputSchema: {
      type: "object",
      properties: { page: { type: "integer" }, total: { type: "integer" }, title: { type: "string" } },
    },
  },
  {
    name: "deck_goto",
    description: "Jump straight to a slide",
    inputSchema: {
      type: "object",
      properties: { page: { type: "integer", description: "Which slide, counting from 1" } },
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
    throw new Error(`cannot reach 127.0.0.1:${PORT} - the browser must be started with --remote-debugging-port=${PORT}`);
  }
  const pages = list.filter((t) => t.type === "page");
  const hit = pages.find((t) => t.url === LINK);
  if (!hit) {
    const open = pages.map((t) => t.url).join(", ") || "(nothing open)";
    throw new Error(`no tab is at ${LINK}. Currently open: ${open}`);
  }
  return hit;
}

let opening: Promise<WebSocket> | null = null;
let live: string | null = null;

/**
 * Open one connection, **only one**: three concurrent calls should not create three WebSockets with separate queues.
 *
 * First recheck the URL with `target()` every time. **Navigating the same tab keeps its target ID and WebSocket alive**. Reusing the cache directly would evaluate on the new page and return “window.deck is undefined”, resembling a broken page when the original place no longer exists.
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
  if (!t.webSocketDebuggerUrl) throw new Error(`${t.url} gave no debugger address`);
  const s = new WebSocket(t.webSocketDebuggerUrl);
  await new Promise<void>((ok, fail) => {
    s.onopen = () => ok();
    s.onerror = () => fail(new Error(`cannot reach that tab: ${t.url}`));
  });
  s.onmessage = (e: MessageEvent) => {
    const m = JSON.parse(String(e.data)) as { id?: number; result?: unknown; error?: { message?: string } };
    if (m.id === undefined) return; // A CDP event; no caller is waiting for it.
    const w = waiting.get(m.id);
    if (!w) return;
    waiting.delete(m.id);
    if (m.error) w.fail(new Error(m.error.message ?? "CDP reported an error"));
    else w.ok(m.result);
  };
  // Tab closed, refreshed, or browser exited: settle every pending request so callers do not wait until timeout.
  s.onclose = () => {
    for (const w of waiting.values()) w.fail(new Error("the connection to that tab dropped"));
    waiting.clear();
    ws = null;
    live = null;
  };
  ws = s;
  live = t.id;
  process.stderr.write(`[tab] attached to ${t.title} | ${t.url}\n`);
  return s;
}

/** Evaluate in the selected tab. **Return page-thrown errors unchanged**, rather than reporting only failure. */
async function evaluate(expr: string): Promise<unknown> {
  const s = await socket();
  const id = ++seq;
  const res = (await new Promise((ok, fail) => {
    waiting.set(id, { ok, fail });
    s.send(JSON.stringify({ id, method: "Runtime.evaluate", params: { expression: expr, returnByValue: true, awaitPromise: true } }));
  })) as { result?: { value?: unknown }; exceptionDetails?: { text?: string; exception?: { description?: string } } };
  if (res.exceptionDetails) {
    const d = res.exceptionDetails;
    throw new Error(`the page reported an error: ${d.exception?.description ?? d.text ?? "?"}`);
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
    throw new Error("this page has no window.deck - the tab matched, but it is not that deck");
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
      return { jsonrpc: "2.0", id: m.id, error: { code: -32602, message: `no such tool: ${String(p.name)}` } };
    }
    try {
      const out = await call(String(p.name), p.arguments ?? {});
      return reply({ content: [{ type: "text", text: JSON.stringify(out) }], structuredContent: out });
    } catch (e) {
      // A closed tab or changed page is a failed operation, not a protocol error. Use isError so the model
      // sees the cause and knows not to keep advancing slides.
      const why = e instanceof Error ? e.message : String(e);
      process.stderr.write(`[tab] failed: ${why}\n`);
      return reply({ content: [{ type: "text", text: why }], isError: true });
    }
  }

  return { jsonrpc: "2.0", id: m.id, error: { code: -32601, message: `unknown method: ${String(m.method)}` } };
}

process.stderr.write(`[tab] up, bound to ${LINK}, debug port ${PORT}\n`);
let buf = "";
// Count in-flight requests. Close after stdin ends, but **not while responses remain outstanding**.
// The WebSocket keeps the process alive, so track shutdown explicitly.
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
