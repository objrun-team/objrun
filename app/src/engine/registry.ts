/**
 * Handle registry: resolve names to implementations.
 *
 * **Registration always passes through the kernel**, because only its process can hold function
 * objects. The database stores names only.
 *
 * **There is one distinction: in-process or out-of-process.** The name prefix specifies it:
 *
 * | Prefix | Implementation location |
 * | --- | --- |
 * | `fn:` | **Inside the kernel process** |
 * | `http://` / `https://` | Another process |
 *
 * Both use `expect_ms`: an invocation exceeding it is marked dead, **regardless of process location**.
 *
 * ## In-process does not mean compiled into the executable
 *
 * A function **object** cannot be transferred, but its **location** can. `fn:` implementations
 * therefore come from two sources:
 *
 * | `handle.module` | Source | Who registers the row | Location |
 * | --- | --- | --- | --- |
 * | Empty | Bundled with the executable | Code calls `register` | Main thread, direct function call |
 * | `path#export` | Runtime plugin | **External code can insert the row** | Its own Worker; see `plugin.ts` |
 *
 * Both remain within the process, without crossing an OS process boundary. The database row
 * has the same purpose in each case: **tell the kernel that the function exists**.
 *
 * Plugins use Workers because **a realm is the lifecycle unit**. Replacing the entire realm
 * allows actual upgrades and unloading, at the cost of a structured clone. JavaScript cannot
 * combine actual unloading with zero-overhead calls. Plugins choose unloading; bundled
 * functions choose direct calls.
 *
 * A `fn:` row with neither a registered in-process implementation nor `module` is invalid.
 * Report that immediately rather than waiting for an actual invocation.
 *
 * ## MCP is not a third kind
 *
 * MCP is **how these implementations communicate**, not another handle category. Both sides
 * support the protocol; transport determines the process boundary:
 *
 * ```
 * fn:      in-process     ←→ MCP in-memory transport
 * http://  out-of-process ←→ MCP stdio subprocess / HTTP
 * ```
 *
 * Tools advertised by an MCP server become rows in **these same two categories**.
 * A server declaration is merely a **batch source** of tool definitions that generates rows;
 * it neither replaces nor excludes registering individual tools.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { Plugins } from "./plugin.ts";

/** An invocation. Arguments and results must be JSON-compatible because the out-of-process path can transfer only such values. */
export type Handle = (arg: unknown) => Promise<unknown>;

export interface Entry {
  name: string;
  expectMs: number;
  call: Handle;
  /** An in-process function or an external endpoint. */
  where: "in" | "out";
  /**
   * A runtime-loaded plugin implemented in this module (`path#export`).
   *
   * Bundled functions omit this field: they should not be unloaded and have no unloadable realm.
   */
  plugin?: string;
}

const IN = /^fn:/;
const OUT = /^https?:\/\//;
const MCP = /^mcp:/;

/**
 * Whether an external caller may register this name.
 *
 * `fn:` **is allowed**, but must identify its implementation through `module`. Otherwise the
 * database would contain an unclaimed handle whose failure appears only at invocation time.
 */
export function registrable(name: string, module?: string | null): boolean {
  if (OUT.test(name) || MCP.test(name)) return true;
  return IN.test(name) && Boolean(module && module.trim());
}

export class Registry {
  #by = new Map<string, Entry>();

  /**
   * Runtime plugin hosts: one Worker per plugin.
   *
   * They belong here because the registry defines which functions exist. Plugin creation and
   * destruction are the corresponding lifecycle operations: a new row creates a host; removing
   * a row removes it.
   */
  readonly plugins = new Plugins();

  /**
   * Notify listeners before reconciling the table.
   *
   * MCP needs this when a server has just been registered but its tool handles have no invokers.
   * Give it a chance to install them **before reconciliation**, so `sync` does not incorrectly
   * report an unregistered handle simply because installation has not run yet.
   */
  beforeSync: (() => void) | null = null;

  /**
   * Register an **in-process** handle: retain its function and add a row to `handle`.
   *
   * The row exposes references and timeout information to others; the function exists only in this process.
   */
  register(db: Conn, name: string, expectMs: number, fn: Handle): void {
    if (!IN.test(name)) throw new Error(`an in-process handle name must start with fn: - got ${name}`);
    if (!Number.isFinite(expectMs) || expectMs <= 0) throw new Error(`expect_ms for ${name} must be a positive number`);
    this.#by.set(name, { name, expectMs, call: fn, where: "in" });
    run(db, `insert into handle (name, expect_ms, module) values (?, ?, null)
             on conflict(name) do update set expect_ms = excluded.expect_ms`, [name, expectMs]);
  }

  /**
   * Adopt an invoker for a handle **already registered in the database**.
   *
   * `register` means "register a row for this function"; `adopt` means "use this synthesized invoker
   * for an existing row." MCP uses the latter: the server advertised the tools, their rows already
   * exist, and only the invokers remain to be attached.
   */
  adopt(name: string, expectMs: number, fn: Handle): void {
    this.#by.set(name, { name, expectMs, call: fn, where: "out" });
  }

  /**
   * Reconcile the registry against the database's `handle` table. **This is the second validation layer.**
   *
   * - External endpoints: synthesize an invoker when absent from the registry, enabling external registration.
   * - In-process handles: a database row without a registered implementation **fails immediately**.
   *   Otherwise the problem would emerge only after a task reached that invocation.
   */
  sync(db: Conn): { added: string[]; missing: string[]; dropped: string[] } {
    this.beforeSync?.();
    const rows = all(db, `select name, expect_ms, module from handle`) as {
      name: string;
      expect_ms: number;
      module: string | null;
    }[];
    const added: string[] = [];
    const missing: string[] = [];
    for (const r of rows) {
      if (this.#by.has(r.name)) {
        this.#by.get(r.name)!.expectMs = r.expect_ms; // Update the timeout when its database value changes.
        continue;
      }
      if (OUT.test(r.name)) {
        this.#by.set(r.name, { name: r.name, expectMs: r.expect_ms, where: "out", call: remote(r.name) });
        added.push(r.name);
      } else if (IN.test(r.name) && r.module) {
        // In-process implementation stored on disk: host it in its own worker, started lazily on first
        // invocation. Installing tables must not fail simply because a plugin is broken.
        const spec = r.module;
        this.#by.set(r.name, {
          name: r.name,
          expectMs: r.expect_ms,
          where: "in",
          plugin: spec,
          call: (arg) => this.plugins.call(r.name, spec, arg),
        });
        added.push(r.name);
      } else {
        missing.push(r.name);
      }
    }

    // **Removing the database row actually unloads the plugin.** Terminate its worker and reclaim
    // code, memory, and timers. Removing only the registry entry would leave those resources
    // in the process indefinitely, with no visible owner.
    const inDb = new Set(rows.map((r) => r.name));
    const dropped: string[] = [];
    for (const [name, e] of this.#by) {
      if (e.plugin === undefined || inDb.has(name)) continue;
      this.plugins.drop(name);
      this.#by.delete(name);
      dropped.push(name);
    }

    if (missing.length) {
      throw new Error(`registered in the database but never registered in this process: ${missing.join(", ")}`);
    }
    return { added, missing, dropped };
  }

  get(name: string): Entry {
    const e = this.#by.get(name);
    if (!e) throw new Error(`no such handle: ${name}`);
    return e;
  }

  has(name: string): boolean {
    return this.#by.has(name);
  }

  names(): string[] {
    return [...this.#by.keys()].sort();
  }
}

/** Secrets stay in the host environment and are sent only to explicitly trusted grader origins. */
export async function graderFetch(url: string, init: RequestInit): Promise<Response> {
  const token = process.env.TGENGIN_GRADER_TOKEN;
  if (!token) return fetch(url, init);
  const raw = process.env.TGENGIN_GRADER_ORIGINS?.trim();
  if (!raw) throw new Error("TGENGIN_GRADER_ORIGINS is required when TGENGIN_GRADER_TOKEN is configured");
  let entries: unknown[];
  try { entries = raw.startsWith("[") ? JSON.parse(raw) as unknown[] : raw.split(","); }
  catch { throw new Error("TGENGIN_GRADER_ORIGINS must be a list of URL origins"); }
  if (!Array.isArray(entries) || entries.length === 0) throw new Error("TGENGIN_GRADER_ORIGINS must be a nonempty list of URL origins");
  const origins = new Set(entries.map(entry => {
    try {
      const parsed = new URL(String(entry).trim());
      if (!["http:", "https:"].includes(parsed.protocol) || parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) throw new Error();
      return parsed.origin;
    } catch { throw new Error("TGENGIN_GRADER_ORIGINS contains an invalid URL origin"); }
  }));
  const headers = new Headers(init.headers);
  // Even a caller-supplied header must not bypass origin scoping.
  headers.delete("X-ObjRun-Grader-Token");
  const trusted = origins.has(new URL(url).origin);
  if (trusted) headers.set("X-ObjRun-Grader-Token", token);
  return fetch(url, { ...init, headers, ...(trusted ? { redirect: "error" } : {}) });
}

/** Synthesize an invoker for an external endpoint. Its name is the address. */
function remote(url: string): Handle {
  return async (arg: unknown) => {
    const res = await graderFetch(url, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(arg ?? {}),
    });
    if (!res.ok) throw Object.assign(new Error(`${url} returned ${res.status}`), { statusCode: res.status });
    return await res.json();
  };
}
