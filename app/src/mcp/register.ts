/**
 * Connect an MCP server.
 *
 * ```
 * Declare a server → connect and handshake → tools/list → one row per tool
 * ```
 *
 * **Tools need not be declared individually.** Declare the server; its own `tools/list` supplies
 * names, descriptions, and parameter schemas. Add only the engine-specific fields MCP lacks:
 *
 * | Added field | Meaning |
 * | --- | --- |
 * | `when` | When the tool is offered to the model; MCP leaves this to clients |
 * | `expectMs` | Timeout after which the invocation is marked dead |
 * | `system` | Available to everyone, regardless of `when` |
 * | `usable` | Whether a registered tool is enabled |
 *
 * Handle names use `mcp:<server>/<tool>`, one per tool. Like other handles, they have timeouts
 * and appear in the `handle` table.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { McpClient, transportOf, type McpTool, type ServerSpec, type Servers } from "./client.ts";

/** Handle-name format. **Changing it changes the protocol** and invalidates existing database rows. */
export const MCP = "mcp:";

export function handleName(server: string, tool: string): string {
  return `${MCP}${server}/${tool}`;
}

/** Parse a handle name; return null if it is not an MCP handle. */
export function splitHandle(name: string): { server: string; tool: string } | null {
  if (!name.startsWith(MCP)) return null;
  const rest = name.slice(MCP.length);
  const slash = rest.indexOf("/");
  if (slash <= 0) return null;
  return { server: rest.slice(0, slash), tool: rest.slice(slash + 1) };
}

/** A server registered in the database. */
export interface ServerRow extends ServerSpec {
  name: string;
}

/** Currently registered servers, stored in `mcp_server`. */
export function serversIn(db: Conn): ServerRow[] {
  return (all(db, `select name, spec from mcp_server order by name`) as { name: string; spec: string }[]).map((r) => {
    let spec: ServerSpec = {};
    try {
      spec = JSON.parse(r.spec) as ServerSpec;
    } catch {
      // Treat corrupt configuration as missing; `checkData` reports it.
    }
    return { name: r.name, ...spec };
  });
}

/**
 * Attach in-process invokers for these servers' tools.
 *
 * **Call this every iteration**, like `Registry.sync`. A newly registered server becomes
 * available on the next iteration without restarting the engine.
 */
export function attach(db: Conn, reg: Registry, pool: Servers): string[] {
  const attached: string[] = [];
  const specs = new Map(serversIn(db).map((s) => [s.name, s]));

  for (const h of all(db, `select name, expect_ms from handle where name like 'mcp:%'`) as {
    name: string;
    expect_ms: number;
  }[]) {
    if (reg.has(h.name)) continue;
    const at = splitHandle(h.name);
    if (!at) continue;
    const spec = specs.get(at.server);
    // The server row is gone but its handle remains. Leave it unregistered so `Registry.sync` reports the inconsistency.
    if (!spec) continue;
    reg.adopt(h.name, h.expect_ms, async (arg) => {
      const a = (arg ?? {}) as { args?: unknown };
      return await pool.get(at.server, spec).call(at.tool, a.args ?? {});
    });
    attached.push(h.name);
  }
  return attached;
}

/**
 * Connect to a server and create rows for all advertised tools.
 *
 * Return the tools created. **An unreachable declared server is an error** and must fail now,
 * rather than halfway through a task's first invocation.
 */
export async function pull(
  db: Conn,
  pool: Servers,
  s: ServerRow,
  overlay: Record<string, ToolOverlay> | undefined,
  defaults: { expectMs: number },
): Promise<string[]> {
  const client = pool.get(s.name, s);
  let tools: McpTool[];
  try {
    tools = await client.tools();
  } catch (e) {
    throw new Error(`cannot reach server ${s.name}: ${e instanceof Error ? e.message : String(e)}`);
  }

  const names: string[] = [];
  for (const t of tools) {
    const o = overlay?.[t.name] ?? {};
    const identity = handleName(s.name, t.name);

    // **Reject name collisions immediately.** `tool.name` is the model-visible, globally unique
    // name. If two servers advertise `deck_state`, the later registration could overwrite the
    // first tool's identity while leaving one apparently valid row. The model would silently
    // invoke a different server. Prevent this before writing anything.
    const had = all(db, `select identity from tool where name = ?`, [t.name])[0] as
      | { identity: string }
      | undefined;
    if (had && had.identity !== identity) {
      throw new Error(
        `tool name collision: ${t.name} already belongs to ${had.identity}, and server ${s.name} reports one too` +
          ` (to replace it, delete the old row first - silently overriding is invisible to everyone)`,
      );
    }
    run(db, `insert into handle (name, expect_ms) values (?, ?) on conflict(name) do update set expect_ms = excluded.expect_ms`, [
      identity,
      o.expectMs ?? defaults.expectMs,
    ]);
    run(
      db,
      `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
       values (?, ?, ?, ?, ?, ?, ?, ?, null, ?, null)
       on conflict(name) do update set identity = excluded.identity, does = excluded.does,
         params = excluded.params, output = excluded.output, prompt = excluded.prompt,
         concurrent = excluded.concurrent, system = excluded.system, usable = excluded.usable`,
      [
        t.name,
        identity,
        // MCP description maps to `does`; title is more human-oriented and is appended.
        t.description ?? t.title ?? "",
        JSON.stringify(t.inputSchema ?? { type: "object" }),
        JSON.stringify(t.outputSchema ?? {}),
        o.prompt ?? null,
        o.concurrent ? 1 : 0,
        o.system ? 1 : 0,
        o.usable === false ? 0 : 1,
      ],
    );
    names.push(t.name);
  }
  return names;
}

/** Engine-specific additions to MCP tools. **All are optional**; defaults remain usable. */
export interface ToolOverlay {
  when?: unknown;
  expectMs?: number;
  prompt?: string | null;
  concurrent?: boolean;
  system?: boolean;
  usable?: boolean;
}

/** A server declaration combines the MCP configuration with per-tool additions. */
export interface ServerDecl extends ServerSpec {
  name: string;
  /** Additions keyed by tool name. Unmentioned tools retain their advertised MCP definitions. */
  tools?: Record<string, ToolOverlay>;
}

/** Problems detectable at declaration time. Actual connectivity is checked by `pull`. */
export function inspectServer(s: ServerDecl): string[] {
  const bad: string[] = [];
  const at = `server ${s.name || "(unnamed)"}`;
  if (!s.name || !s.name.trim()) bad.push(`a server has no name`);
  if (/[/]/.test(s.name ?? "")) bad.push(`${at}: the name cannot contain / (handle names are mcp:<server>/<tool> and would split wrong)`);
  const t = transportOf(s);
  if (t === null) {
    bad.push(`${at}: give either command (spawn a child process) or url (HTTP) - exactly one, not both and not neither`);
  }
  if (s.args !== undefined && !Array.isArray(s.args)) bad.push(`${at}: args must be a list of strings`);
  return bad;
}

export { McpClient };
