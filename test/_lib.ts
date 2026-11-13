/**
 * Scaffolding shared by the examples.
 *
 * ## Each example starts its own engine
 *
 * A single `bun examples/xxx.ts` command starts a **temporary** engine with temporary
 * configuration and database, then removes both when finished. It never touches
 * the database you are using: an example corrupting that database is harder to
 * diagnose than an example that fails to start.
 *
 * ## Examples **do not call a model**
 *
 * When a cycle's `apiMode` is empty, the kernel calls `agent.unit`, which can be
 * an **external `http://` handle**. The example's own small server therefore
 * controls the entire workflow:
 *
 * - No cost, no dependency on network availability, and identical results each time.
 * - It also verifies something more fundamental: **external extensions really work**.
 *   Every registration enters from outside the process, without changing kernel code.
 *
 * ## Two parts
 *
 * Each example checks both **registration** and **actual use**:
 *
 * - Registration: can it be declared, and are invalid declarations explained clearly?
 * - Use: **run a real task** after registration and verify that it actually takes effect.
 *
 * The first part alone is insufficient. A common failure in this system is
 * "stored successfully but never triggered": registration and actual effect are distinct.
 */

import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawn, type ChildProcess } from "node:child_process";

const ROOT = join(import.meta.dir, "..");

/** Find an unused port: open a listener, record its port, then close it. */
async function freePort(): Promise<number> {
  const s = Bun.serve({ port: 0, fetch: () => new Response("") });
  const p = s.port;
  await s.stop(true);
  if (p === undefined) throw new Error("cannot obtain a free port");
  return p;
}

export interface Machine {
  /** PID of the actual Bun engine, rather than a package-manager shim. */
  pid: number;
  /** Call an endpoint. On 4xx/5xx, throw the server message verbatim; it is the most useful diagnostic in these examples. */
  api<T = unknown>(method: string, path: string, body?: unknown): Promise<T>;
  /** Call an endpoint, **expecting failure**, and return the server's JSON response. */
  bad(method: string, path: string, body?: unknown): Promise<Record<string, unknown>>;
  base: string;
  directory: string;
  stop(): Promise<void>;
}

/** Start a temporary engine. */
export async function machine(llm: Record<string, string | number> = {}, options: { directory?: string; keep?: boolean } = {}): Promise<Machine> {
  const dir = options.directory ?? mkdtempSync(join(tmpdir(), "tgengin-example-"));
  const port = await freePort();
  writeFileSync(
    join(dir, "config.yaml"),
    [
      `server: { host: 127.0.0.1, port: ${port}, bodyLimit: 1048576, shutdownTimeout: 2000 }`,
      `log: { level: warn }`,
      `db: { file: ./data/h2h.sqlite, sealed: ./data/sealed.sqlite,`,
      `      pragmas: { journal_mode: WAL, synchronous: NORMAL, foreign_keys: ON, busy_timeout: 5000 } }`,
      `api: { prefix: /api, token: , allowQuery: true, allowWrite: true, maxRows: 500, defaultLimit: 100 }`,
      // A missing `config.yaml` key fails immediately by design, so this must track Config.
      // A missing key prevents startup, while `machine()` keeps waiting and looks like a hung test.
      // Examples can override individual settings, such as setting `retryTimes` to 0 so that
      // connection-failure scenarios finish in seconds instead of waiting through three backoffs.
      `llm: { ${Object.entries({
        maxTokens: 16384,
        retryTimes: 3,
        continueTimes: 3,
        reasoningEffort: "high",
        temperature: 0,
        seed: 42,
        ...llm,
      })
        .map(([k, v]) => `${k}: ${String(v)}`)
        .join(", ")} }`,
      `cors: { enabled: false, origin: "*" }`,
      "",
    ].join("\n"),
    "utf8",
  );

  const proc: ChildProcess = spawn(
    process.execPath,
    [`--env-file=${join(ROOT, ".env")}`, join(ROOT, "app", "src", "main.ts")],
    { env: { ...process.env, TGENGIN_CONFIG: join(dir, "config.yaml") }, stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
  );
  const enginePid = proc.pid;
  if (enginePid === undefined) throw new Error("the test engine did not obtain a process ID");
  let log = "";
  proc.stdout?.on("data", (d: Buffer) => (log += d.toString()));
  proc.stderr?.on("data", (d: Buffer) => (log += d.toString()));

  const base = `http://127.0.0.1:${port}/api`;
  for (let i = 0; i < 100; i++) {
    try {
      if ((await fetch(`${base}/health`)).ok) break;
    } catch {
      // Not ready yet; keep waiting.
    }
    if (i === 99) {
      proc.kill();
      throw new Error(`the engine did not come up. It said:\n${log}`);
    }
    await Bun.sleep(100);
  }

  const call = async (method: string, path: string, body?: unknown) => {
    const res = await fetch(base + path, {
      method,
      ...(body === undefined ? {} : { headers: { "content-type": "application/json" }, body: JSON.stringify(body) }),
    });
    const text = await res.text();
    let json: unknown;
    try {
      json = JSON.parse(text);
    } catch {
      json = text;
    }
    return { res, json };
  };

  return {
    pid: enginePid,
    base,
    directory: dir,
    async api<T>(method: string, path: string, body?: unknown): Promise<T> {
      const { res, json } = await call(method, path, body);
      if (!res.ok) throw new Error(`${method} ${path} → ${res.status}\n${JSON.stringify(json, null, 2)}`);
      return json as T;
    },
    async bad(method: string, path: string, body?: unknown) {
      const { res, json } = await call(method, path, body);
      if (res.ok) throw new Error(`${method} ${path} should have been rejected, but returned ${res.status}`);
      return json as Record<string, unknown>;
    },
    async stop() {
      if (proc.exitCode === null && proc.signalCode === null) {
        await new Promise<void>(resolve => {
          const hard = setTimeout(() => { proc.kill("SIGKILL"); }, 3000);
          proc.once("exit", () => { clearTimeout(hard); resolve(); });
          proc.kill();
        });
      }
      if (options.keep) return;
      try {
        rmSync(dir, { recursive: true, force: true });
      } catch {
        // Windows may still hold the database file open; leave it in the temporary directory.
      }
    },
  };
}

// -- The example's small server: register external handles --------------------

/** An external handle: the kernel POSTs JSON and receives JSON. */
export type Impl = (arg: Record<string, unknown>) => unknown | Promise<unknown>;

export interface Outside {
  /** Address prefix of this small server; append a path to obtain a handle name. */
  url(path: string): string;
  /** Call count and last payload for each handle: these establish whether it actually took effect. */
  calls: Record<string, Record<string, unknown>[]>;
  stop(): void;
}

/**
 * Start a small server and expose several handles.
 *
 * **This is the external extension path**: register an `http://` handle and insert
 * a database row. On its next wake-up, the kernel constructs the caller itself;
 * no kernel edits or restart are needed.
 */
export async function outside(impls: Record<string, Impl>): Promise<Outside> {
  const calls: Record<string, Record<string, unknown>[]> = {};
  for (const k of Object.keys(impls)) calls[k] = [];

  const server = Bun.serve({
    port: 0,
    async fetch(req) {
      const path = new URL(req.url).pathname;
      const impl = impls[path];
      if (!impl) return new Response(JSON.stringify({ error: `this little server has no ${path}` }), { status: 404 });
      let arg: Record<string, unknown> = {};
      try {
        arg = (await req.json()) as Record<string, unknown>;
      } catch {
        // An empty body still counts as a call.
      }
      calls[path].push(arg);
      const out = await impl(arg);
      return new Response(JSON.stringify(out ?? null), { headers: { "content-type": "application/json" } });
    },
  });

  return {
    url: (path) => `http://127.0.0.1:${server.port}${path}`,
    calls,
    stop: () => void server.stop(true),
  };
}

// -- Output and scoring ------------------------------------------------------

let bad = 0;
let total = 0;

export function part(title: string): void {
  console.log(`\n━━ ${title} ━━`);
}

export function step(title: string): void {
  console.log(`\n${title}`);
}

export function ok(what: string, cond: boolean, saw?: unknown): void {
  total++;
  if (cond) {
    console.log(`  ✓ ${what}`);
    return;
  }
  bad++;
  console.log(`  ✗ ${what}${saw === undefined ? "" : `\n      actually got: ${JSON.stringify(saw)}`}`);
}

/** Print an indented passage, usually an error message; it is often the example's most useful output. */
export function show(label: string, v: unknown): void {
  const s = typeof v === "string" ? v : JSON.stringify(v, null, 2);
  console.log(`  ${label}\n${s.split("\n").map((l) => "      " + l).join("\n")}`);
}

export function done(): never {
  console.log(bad === 0 ? `\nall ${total} passed.` : `\n${bad} of ${total} failed.`);
  process.exit(bad === 0 ? 0 : 1);
}

/** Wait until a condition holds. On timeout, throw with the last observed value. */
export async function until<T>(what: string, f: () => Promise<T | null>, ms = 20_000): Promise<T> {
  const t0 = Date.now();
  let last: unknown = null;
  while (Date.now() - t0 < ms) {
    const v = await f();
    if (v !== null) return v;
    last = v;
    await Bun.sleep(200);
  }
  throw new Error(`waited ${ms}ms for ${what} without success; last seen was ${JSON.stringify(last)}`);
}
