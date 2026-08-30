/**
 * MCP 客户端。
 *
 * **工具这一块不自己定协议。** 外面已经有 MCP 了：注册的是一个 **server**
 * （`command` 起个子进程，或者 `url` 走 HTTP），server 自己用 `tools/list` 报
 * 它有哪些工具，调用走 `tools/call`。我们要加的只是「什么时候把它摆给模型」
 * 那几个字段。
 *
 * 自己定一套的代价很具体：别人写好的 server 一个都用不了，而写 server 的人
 * 得为我们再写一遍。
 *
 * ## 两种传输
 *
 * | 怎么写 | 传输 |
 * | --- | --- |
 * | `{ command, args, env }` | 起个子进程，JSON-RPC 走 stdio，一行一条 |
 * | `{ url, headers }` | POST 一条 JSON-RPC 过去 |
 *
 * 跟 `claude_desktop_config.json` 里那个 `mcpServers` 是同一个形状 —— 抄过来就能用。
 *
 * ## 连接不进库
 *
 * 起着的子进程、开着的连接是**活状态**，跟位置那一层一个道理：不写回库。
 * 库里存的是「登记了这么一个 server」，不是「它现在连着」。
 */

import { spawn, type ChildProcess } from "node:child_process";

/** 一个 MCP server 怎么起。**跟 MCP 客户端配置里那个形状一样。** */
export interface ServerSpec {
  /** stdio：要跑的命令。 */
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  /** HTTP：地址。跟 `command` 二选一。 */
  url?: string;
  headers?: Record<string, string>;
}

/** `tools/list` 报回来的一个工具。字段名就是 MCP 的。 */
export interface McpTool {
  name: string;
  title?: string;
  description?: string;
  inputSchema?: unknown;
  outputSchema?: unknown;
}

interface Rpc {
  jsonrpc: "2.0";
  id?: number;
  method?: string;
  params?: unknown;
  result?: unknown;
  error?: { code: number; message: string };
}

/** 这个 spec 是哪一种传输。两样都给或都不给都是错。 */
export function transportOf(s: ServerSpec): "stdio" | "http" | null {
  const hasCmd = Boolean(s.command && s.command.trim());
  const hasUrl = Boolean(s.url && s.url.trim());
  if (hasCmd === hasUrl) return null;
  return hasCmd ? "stdio" : "http";
}

const PROTOCOL = "2026-07-28";
const CLIENT = { name: "tgengin", version: "1.0.0" };

export class McpClient {
  readonly name: string;
  #spec: ServerSpec;
  #proc: ChildProcess | null = null;
  #buf = "";
  #id = 0;
  #waiting = new Map<number, { ok(v: unknown): void; fail(e: Error): void }>();
  #dead: Error | null = null;
  #ready: Promise<void> | null = null;

  constructor(name: string, spec: ServerSpec) {
    this.name = name;
    this.#spec = spec;
  }

  /** 握手。**只做一次** —— 后面每次调用都等这同一个 promise。 */
  ready(): Promise<void> {
    this.#ready ??= this.#open();
    return this.#ready;
  }

  async #open(): Promise<void> {
    if (transportOf(this.#spec) === "stdio") this.#spawn();
    const init = (await this.#send("initialize", {
      protocolVersion: PROTOCOL,
      capabilities: {},
      clientInfo: CLIENT,
    })) as { protocolVersion?: string; serverInfo?: { name?: string } };
    // 握完手要发这条通知，server 才认为可以干活了。不发的话有的 server 一直挂着。
    await this.#notify("notifications/initialized", {});
    void init;
  }

  #spawn(): void {
    const s = this.#spec;
    this.#proc = spawn(s.command!, s.args ?? [], {
      env: { ...process.env, ...(s.env ?? {}) },
      stdio: ["pipe", "pipe", "pipe"],
      windowsHide: true,
    });
    this.#proc.stdout?.setEncoding("utf8");
    this.#proc.stdout?.on("data", (c: string) => this.#feed(c));
    // stdio 的 server 拿 stderr 当日志用，不是只有出错才写 —— 所以不当错处理，
    // 原样转到引擎的 stderr。不转的话 server 自己说的话全丢，出事没处看。
    this.#proc.stderr?.setEncoding("utf8");
    this.#proc.stderr?.on("data", (c: string) => process.stderr.write(c));
    this.#proc.on("exit", (code) => this.#die(new Error(`${this.name} exited (${code})`)));
    this.#proc.on("error", (e) => this.#die(e));
  }

  #feed(chunk: string): void {
    this.#buf += chunk;
    let nl = this.#buf.indexOf("\n");
    while (nl !== -1) {
      const line = this.#buf.slice(0, nl).trim();
      this.#buf = this.#buf.slice(nl + 1);
      if (line) this.#take(line);
      nl = this.#buf.indexOf("\n");
    }
  }

  #take(line: string): void {
    let m: Rpc;
    try {
      m = JSON.parse(line) as Rpc;
    } catch {
      // 不是 JSON 的一行多半是 server 往 stdout 打了日志。**只丢这一行** ——
      // 当成协议错把整条连接掐掉的话，一句无关的 println 就能弄死一个 server。
      return;
    }
    if (m.id === undefined) return; // 通知，没人在等
    const w = this.#waiting.get(m.id);
    if (!w) return;
    this.#waiting.delete(m.id);
    if (m.error) w.fail(new Error(`${this.name}: ${m.error.message}`));
    else w.ok(m.result);
  }

  #die(e: Error): void {
    this.#dead ??= e;
    for (const w of this.#waiting.values()) w.fail(e);
    this.#waiting.clear();
  }

  async #notify(method: string, params: unknown): Promise<void> {
    const body = JSON.stringify({ jsonrpc: "2.0", method, params });
    if (transportOf(this.#spec) === "stdio") this.#proc?.stdin?.write(body + "\n");
    else await this.#post(body);
  }

  #send(method: string, params: unknown): Promise<unknown> {
    if (this.#dead) return Promise.reject(this.#dead);
    const id = ++this.#id;
    const body = JSON.stringify({ jsonrpc: "2.0", id, method, params });

    if (transportOf(this.#spec) === "http") {
      return this.#post(body).then((text) => {
        const m = JSON.parse(text) as Rpc;
        if (m.error) throw new Error(`${this.name}: ${m.error.message}`);
        return m.result;
      });
    }
    return new Promise((ok, fail) => {
      this.#waiting.set(id, { ok, fail });
      this.#proc?.stdin?.write(body + "\n");
    });
  }

  async #post(body: string): Promise<string> {
    const res = await fetch(this.#spec.url!, {
      method: "POST",
      headers: {
        "content-type": "application/json",
        accept: "application/json, text/event-stream",
        ...(this.#spec.headers ?? {}),
      },
      body,
    });
    if (!res.ok) throw new Error(`${this.name} returned ${res.status}`);
    return await res.text();
  }

  /** 它有哪些工具。 */
  async tools(): Promise<McpTool[]> {
    await this.ready();
    const r = (await this.#send("tools/list", {})) as { tools?: McpTool[] };
    return r?.tools ?? [];
  }

  /**
   * 调一个。
   *
   * MCP 回的是 `content`（一串块）加可选的 `structuredContent`。
   * **有结构化的就用结构化的** —— 那是对着 `outputSchema` 的那一份；没有就把
   * 文本块拼起来。`isError: true` 是**工具执行错**（模型看了能自己改），
   * 所以当结果回给模型，不当成调用失败。
   */
  async call(tool: string, args: unknown): Promise<unknown> {
    await this.ready();
    const r = (await this.#send("tools/call", { name: tool, arguments: args ?? {} })) as {
      content?: { type?: string; text?: string }[];
      structuredContent?: unknown;
      isError?: boolean;
    };
    const text = (r?.content ?? [])
      .filter((c) => c.type === "text" && typeof c.text === "string")
      .map((c) => c.text)
      .join("\n");
    const value = r?.structuredContent !== undefined ? r.structuredContent : text;
    return r?.isError ? { isError: true, value } : value;
  }

  close(): void {
    this.#dead ??= new Error(`${this.name} is already closed`);
    this.#proc?.stdin?.end();
    this.#proc?.kill();
  }
}

/**
 * 开过的 server 留着复用。
 *
 * 每次调用重起一个子进程的话，server 里的状态（打开的浏览器、连着的库）每次都
 * 从头来 —— 那就不是同一个 server 了。
 */
export class Servers {
  #open = new Map<string, McpClient>();

  get(name: string, spec: ServerSpec): McpClient {
    let c = this.#open.get(name);
    if (!c) {
      c = new McpClient(name, spec);
      this.#open.set(name, c);
    }
    return c;
  }

  closeAll(): void {
    for (const c of this.#open.values()) c.close();
    this.#open.clear();
  }
}
