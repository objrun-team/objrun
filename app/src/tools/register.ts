/**
 * Register basic tools with the kernel.
 *
 * **Registration belongs to the kernel**, which alone can hold function objects. Each tool adds:
 *
 * - A `handle` row containing its name and timeout, used for references and liveness decisions.
 * - A `tool` row containing model-facing `does` / `params` / `output` / `prompt` metadata.
 *
 * The registered function **only forwards**: choose the execution location through `workplace`
 * and dispatch the invocation there. Actual implementations live in `./index.ts` and are shared
 * by local execution and the remote runtime.
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { openLocal } from "../place/index.ts";
import { TOOLS } from "./index.ts";

interface Policy {
  tool: string;
  policy: string;
}

/** Execution location and **the handle responsible for forwarding**. */
export interface Where {
  /** Location string. `local` means this process. */
  place: string;
  /** Forwarding handle, from `workplace.identity`. Empty for local execution. */
  identity: string;
}

/**
 * Choose the execution location for this invocation.
 *
 * `workplace.forward` enables forwarding; each allowlisted tool's `policy` refines it:
 * `always` forwards unconditionally, `agent` follows the agent's choice for this call, and
 * unlisted tools remain local.
 *
 * If no policy applies, run locally: **this is not an error**. A place declares where work
 * may be forwarded, not where it must run.
 *
 * When forwarding is selected, **also identify its forwarding handle**. Reaching the destination
 * belongs to that handle, not this file. Declaration validation guarantees `identity` whenever
 * `forward = 1`; if missing anyway, fail here. Continuing could **silently execute locally**,
 * such as running container-intended bash on the host without reporting an error.
 */
export function placeFor(db: Conn, tool: string, place: string, agentWants: boolean | undefined): Where {
  const HERE: Where = { place: "local", identity: "" };
  if (!place || place === "local") return HERE;
  const w = all(db, `select forward, tools, identity from workplace where place = ?`, [place])[0] as
    | { forward: number; tools: string; identity: string | null }
    | undefined;
  if (!w) throw new Error(`no row in workplace for ${place}`);
  if (!Number(w.forward)) return HERE;

  let list: Policy[];
  try {
    list = JSON.parse(w.tools) as Policy[];
  } catch {
    throw new Error(`workplace ${place} has tools that is not a readable list`);
  }
  const hit = list.find((x) => x.tool === tool);
  if (!hit) return HERE;

  const there = (): Where => {
    const identity = String(w.identity ?? "").trim();
    if (!identity) throw new Error(`workplace ${place} forwards, but no handle is registered to carry the call there`);
    return { place, identity };
  };
  if (hit.policy === "always") return there();
  if (hit.policy === "agent") return agentWants === false ? HERE : there();
  throw new Error(`unknown policy for ${tool} on workplace ${place}: ${hit.policy}`);
}

/** Run tools here when not forwarding. **The implementation is shared with the runtime**, preserving behavior. */
const here = openLocal();

/** Dispatch one tool call through its forwarding handle or execute it locally. */
type Send = (tool: string, args: Record<string, unknown>) => Promise<unknown>;

/** File-modifying tools subject to the read-before-write guard. */
const MUTATES = new Set(["edit", "write"]);

/**
 * Whether this execution unit has read the file.
 *
 * The **database** is authoritative: look for a read result at this path in the unit's messages.
 * Do not consult the tool or in-memory state. Tools may run elsewhere, memory is lost on crashes,
 * and only the database is authoritative on both sides.
 */
/**
 * Whether the agent **has actually read the file's contents**.
 *
 * Two earlier mistakes made this guard impossible to satisfy:
 *
 * - It looked for `v.tool`, but result rows use `{id, name, value}` (`tools/unit.ts`), causing
 *   every write or edit to return "read first" forever.
 * - It searched only the current unit. The guard returns an **operation unit**, so its requested
 *   read occurs in the **next station**. Search the entire instance instead.
 */
function hasRead(db: Conn, agent: string, instance: string, path: string): boolean {
  const t = `agent_${agent.replace(/[^A-Za-z0-9_]/g, "_")}_msg`;
  const rows = all(db, `select body from "${t}" where instance = ? and kind = 'tool'`, [
    instance,
  ]) as { body: string }[];
  return rows.some((r) => {
    try {
      const v = JSON.parse(r.body) as { name?: string; value?: { path?: string } };
      return v.name === "read" && v.value?.path === path;
    } catch {
      return false;
    }
  });
}

/**
 * Check file existence **at the execution location**, not on the engine's host. Local stat
 * would give the wrong answer for forwarded tools.
 *
 * Read failures include permission errors and directories as well as missing files. Only ENOENT
 * means absent; treat other failures as existence so unreadability cannot bypass the guard.
 */
async function existsAt(send: Send, path: string): Promise<boolean> {
  try {
    await send("read", { file_path: path, limit: 1 });
    return true;
  } catch (e) {
    return !/ENOENT|no such file/i.test(e instanceof Error ? e.message : String(e));
  }
}

/** Tool metadata stored in the database. The implementation function belongs to its handle, not this table. */
export interface Declared {
  name: string;
  does: string;
  params: Record<string, unknown>;
  output: Record<string, unknown>;
  prompt: string;
  concurrent: boolean;
  /** Result category, referencing `msg_part.name`; default to `event`. */
  gives?: string;
  when?: { dim: string; key: string; op: string; value: string }[][];
}

/**
 * Persist a tool and its trigger conditions. **This is the sole implementation.**
 *
 * Previously both this file and `objective/tool.ts` implemented registration, with verify writing
 * two trigger inserts manually. Their upserts silently drifted: a changed column set on one
 * side left the other's values fixed at first insertion. `concurrent` had already diverged.
 *
 * `when` controls both trigger rows and **system-tool classification**. System tools are available
 * unconditionally, so conditional tools must leave that category. Combining both would silently
 * make their conditions ineffective.
 *
 * **Delete conditions before replacing them**, or reinstalling a tool would retain stale rules.
 */
export function declareTool(db: Conn, t: Declared, identity = `fn:tool.${t.name}`): void {
  const conditional = (t.when ?? []).length > 0;
  run(
    db,
    `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
     values (?, ?, ?, ?, ?, ?, ?, ?, null, 1, ?)
     on conflict(name) do update set
       identity = excluded.identity, does = excluded.does, params = excluded.params,
       output = excluded.output, prompt = excluded.prompt,
       concurrent = excluded.concurrent, system = excluded.system, gives = excluded.gives`,
    [
      t.name,
      identity,
      t.does,
      JSON.stringify(t.params),
      JSON.stringify(t.output),
      t.prompt,
      t.concurrent ? 1 : 0,
      conditional ? 0 : 1,
      t.gives ?? null,
    ],
  );
  run(db, `delete from trigger where owner_kind = 'tool' and owner = ?`, [t.name]);
  (t.when ?? []).forEach((group, i) => {
    for (const term of group) {
      run(
        db,
        `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values ('tool', ?, ?, ?, ?, ?, ?)`,
        [t.name, i, term.dim, term.key, term.op, term.value],
      );
    }
  });
}

/**
 * Register all basic tools with upserts, avoiding duplicate rows on repeated installation.
 *
 * **Use `system = 1`** for universally available file tools. Without it, "no conditions = never
 * triggers" would prevent every agent from receiving them.
 */
export function registerTools(db: Conn, reg: Registry): string[] {
  const names: string[] = [];
  for (const t of TOOLS) {
    const identity = `fn:tool.${t.name}`;

    reg.register(db, identity, t.expectMs, async (arg) => {
      const a = (arg ?? {}) as {
        place?: string;
        forward?: boolean;
        args?: Record<string, unknown>;
        agent?: string;
        instance?: string;
        unit?: number;
      };
      const args = a.args ?? {};

      // Choose the location and forwarder. **Forward through the registry**, just like G nodes and
      // inference functions. This file has no knowledge of wsl, ssh, or docker.
      const where = placeFor(db, t.name, a.place ?? "local", a.forward);
      const send: Send = where.identity
        ? (tool, args) => reg.get(where.identity).call({ place: where.place, op: "call", tool, args })
        : (tool, args) => here.call(tool, args);

      // An unread file modification **returns an operation unit instead of rejection**: perform the
      // read first, then retry the edit.
      //
      // dsh rejects this at the policy layer. Here an execution unit can express the corrective action.
      // Rejection says only "no"; returning a unit says "do this", which the model can act on.
      //
      // **New files bypass this guard** because they contain nothing to overwrite. Otherwise write
      // would demand a read while read returned ENOENT, producing an endless loop. One observed
      // cmt-0 task spent all 12 units on that loop without producing an answer.
      const path = typeof args.file_path === "string" ? args.file_path : "";
      if (MUTATES.has(t.name) && a.agent && a.instance && path && (await existsAt(send, path))) {
        if (!hasRead(db, a.agent, a.instance, path)) {
          return {
            unit: { tool: "read", args: { file_path: path } },
            why: `read ${path} first, then call ${t.name} again`,
          };
        }
      }

      return await send(t.name, args);
    });

    declareTool(db, t, identity);
    names.push(t.name);
  }
  return names;
}
