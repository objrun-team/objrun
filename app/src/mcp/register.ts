/**
 * 把一个 MCP server 接进来。
 *
 * ```
 * 声明一个 server ──→ 连上、握手 ──→ tools/list ──→ 每个工具长一行
 * ```
 *
 * **工具不用你一个个写。** 你写的是「有这么一个 server」，它有哪些工具是它自己
 * 说的 —— 名字、描述、参数 schema 全从 `tools/list` 来。你只补那几样 MCP 里没有、
 * 而这台机器需要的：
 *
 * | 我们加的 | |
 * | --- | --- |
 * | `when` | 什么时候把它摆给模型（MCP 里这件事由 client 自己定） |
 * | `expectMs` | 调多久算死 |
 * | `system` | 谁都有，不看 `when` |
 * | `usable` | 登记着但不挂 |
 *
 * 句柄名是 `mcp:<server>/<tool>` —— 一个工具一条，跟别的句柄一样能被判死、
 * 能在 `handle` 表里查得到。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { McpClient, transportOf, type McpTool, type ServerSpec, type Servers } from "./client.ts";

/** 句柄名的拼法。**改它等于改协议** —— 库里已有的行会对不上。 */
export const MCP = "mcp:";

export function handleName(server: string, tool: string): string {
  return `${MCP}${server}/${tool}`;
}

/** 从句柄名拆回来。不是 mcp 句柄就回 null。 */
export function splitHandle(name: string): { server: string; tool: string } | null {
  if (!name.startsWith(MCP)) return null;
  const rest = name.slice(MCP.length);
  const slash = rest.indexOf("/");
  if (slash <= 0) return null;
  return { server: rest.slice(0, slash), tool: rest.slice(slash + 1) };
}

/** 库里登记的一个 server。 */
export interface ServerRow extends ServerSpec {
  name: string;
}

/** 库里现在登记了哪些 server。存在 `mcp_server` 表里。 */
export function serversIn(db: Conn): ServerRow[] {
  return (all(db, `select name, spec from mcp_server order by name`) as { name: string; spec: string }[]).map((r) => {
    let spec: ServerSpec = {};
    try {
      spec = JSON.parse(r.spec) as ServerSpec;
    } catch {
      // 存坏了当没配 —— `checkData` 会把它报出来
    }
    return { name: r.name, ...spec };
  });
}

/**
 * 把进程内的调用器给这些 server 的工具装上。
 *
 * **每一圈都调一次**（跟 `Registry.sync` 一样）：库里新登记了一个 server，
 * 下一圈就有了，不用重启。
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
    // server 那一行没了而句柄还在 —— 让它留着「没注册」，`Registry.sync` 会喊。
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
 * 连上一个 server，把它报的工具全长出来。
 *
 * 回「长出了哪些工具」。连不上就抛 —— **声明一个连不上的 server 是错**，
 * 而且要当场说：留到某个任务真去调它才发现，那时候已经在半路上了。
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

    // **重名当场拒。** `tool.name` 是模型看见的那个名字，全系统唯一；两个 server
    // 都报 `deck_state` 的话，后来的那个会把前一个的 identity 顶掉 —— 库里还是
    // 一行，看着一切正常，可它已经指到另一个 server 上去了。模型照调，调到的是
    // 别人。这种错从外面一点都看不出来，所以只能在写进去之前拦。
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
        // MCP 的 description 就是我们的 does；title 更像给人看的，拼在后面。
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

/** 我们在 MCP 的工具之上补的那几样。**都是可选的**，一样不给也能跑。 */
export interface ToolOverlay {
  when?: unknown;
  expectMs?: number;
  prompt?: string | null;
  concurrent?: boolean;
  system?: boolean;
  usable?: boolean;
}

/** 一个 server 的声明：MCP 那份形状 + 每个工具的补充。 */
export interface ServerDecl extends ServerSpec {
  name: string;
  /** 按工具名给补充。没提到的工具照 MCP 报的原样收下。 */
  tools?: Record<string, ToolOverlay>;
}

/** 声明期就能看出来的毛病。连不连得上要真去连，那在 `pull` 里。 */
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
