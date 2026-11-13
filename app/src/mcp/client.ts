/**
 * MCP client.
 *
 * **Do not invent another tool protocol.** MCP already provides one: register a **server**
 * using `command` for a subprocess or `url` for HTTP. The server advertises its tools through
 * `tools/list`; invoke them through `tools/call`. We add only the fields controlling when tools
 * are offered to the model. A proprietary protocol would make existing servers unusable and
 * force their authors to reimplement support for this engine.
 *
 * ## Two transports
 *
 * | Configuration | Transport |
 * | --- | --- |
 * | `{ command, args, env }` | Subprocess with line-delimited JSON-RPC over stdio |
 * | `{ url, headers }` | POST each JSON-RPC request over HTTP |
 *
 * This matches `mcpServers` in `claude_desktop_config.json`, so configurations can be reused.
 *
 * ## Connections are not stored in the database
 *
 * Running subprocesses and open connections are **live state**, like workspace connections.
 * The database records that a server is registered, not that it is currently connected.
 */

import { spawn, type ChildProcess } from "node:child_process";

/** How to start an MCP server. **The same shape used by MCP client configurations.** */
export interface ServerSpec {
  /** stdio: command to execute. */
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  /** HTTP: endpoint URL. Specify either this or `command`. */
  url?: string;
  headers?: Record<string, string>;
}

/** A tool returned by `tools/list`, using MCP field names. */
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

/** Determine the transport. Specifying both transports or neither is invalid. */
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

  /** Perform the handshake **once**. Every subsequent invocation awaits the same promise. */
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
    // Send this notification after the handshake; some servers otherwise wait indefinitely before accepting work.
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
    // stdio servers use stderr for routine logging, not only errors. Forward it unchanged to the
    // engine's stderr rather than treating it as failure; otherwise server diagnostics disappear.
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
      // A non-JSON line is usually a server log accidentally written to stdout. **Discard only that
      // line**; terminating the entire connection would let an unrelated println kill the server.
      return;
    }
    if (m.id === undefined) return; // A notification has no waiting caller.
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

  /** Tools provided by the server. */
  async tools(): Promise<McpTool[]> {
    await this.ready();
    const r = (await this.#send("tools/list", {})) as { tools?: McpTool[] };
    return r?.tools ?? [];
  }

  /**
   * Invoke a tool.
   *
   * MCP returns `content` blocks and optional `structuredContent`. **Prefer structured output**,
   * which conforms to `outputSchema`; otherwise concatenate text blocks. `isError: true` denotes
   * a **tool execution error** the model can correct, so return it as tool output rather than
   * failing the invocation itself.
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
 * Reuse servers that have already been started.
 *
 * Restarting a subprocess for every call would discard server state, such as open browsers or
 * database connections. It would no longer be the same server.
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
