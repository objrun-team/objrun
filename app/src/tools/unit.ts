/**
 * Execution unit that **actually runs tools requested by the model in the preceding station**.
 *
 * Without it, the chain stops at offering a tool → model request → `call` row. The request
 * never executes, while the task advances as if its presumed tool invocation had happened.
 *
 * ## Where it is attached
 *
 * This is an `agent.unit` handle selected by a cycle with empty `api_mode`:
 *
 * ```
 * ask (apiMode: chat) → act (empty apiMode, this handle) → ask → …
 * model requests dice   execute it and record the result in context
 * ```
 *
 * ## Locate the preceding station
 *
 * **Every execution unit has independent context**, keyed by `instance,unit` in
 * `agent_<name>_msg`. The tool request lives in the **preceding station**, identified by the
 * subtable's `from_unit`, not current unit minus one. After sibling branches are created,
 * monotonically increasing ids mean subtraction can point to another branch.
 *
 * ## Read the implementation from the table
 *
 * **Do not construct handle names from tool names.** `fn:tool.<name>` happens to work for
 * built-ins but not HTTP or MCP tools. Those tools would be offered and requested yet fail
 * to execute, with the error visible only in the tool-result row.
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";
import { deliver } from "../msg/deliver.ts";

/** Handle name. A cycle with empty `api_mode` selects it through `agent.unit`. */
export const UNIT_TOOLS = "fn:unit.tools";

/** Execution-unit timeout, distinct from a single tool timeout because one unit may run several tools. */
export const EXPECT_MS = 600_000;

type Row = Record<string, unknown>;

interface Call {
  id: string;
  name: string;
  input: unknown;
}

/**
 * Calls requested by the preceding station that **have no result yet**.
 *
 * ## Two lessons from observed failures
 *
 * **First, inspect more than the last `call` row.** A unit can contain multiple call rows;
 * `deliverVerdict` adds its own call/result pair. Looking only at the last one would skip the
 * model's request and select the verdict call instead.
 *
 * **Second, never rerun calls with results.** Verdict pairs already include their answer.
 * Executing them again creates two results for one id, violating the model protocol:
 * `An assistant message with 'tool_calls' must be followed by tool messages
 * responding to each of them`. The entire chain becomes unsendable and stalls until timeout.
 *
 * Both follow one invariant: **one call, one result**. Whoever answered it, do not answer again.
 */
function callsOf(db: Conn, agent: string, instance: string, unit: number): Call[] {
  const t = tableNameOf("agent_{}_msg", agent);
  const rows = all(db, `select kind, body from "${t}" where instance = ? and unit = ? order by seq`, [
    instance,
    unit,
  ]) as { kind: string; body: string }[];

  // Ids already answered in this execution unit.
  const answered = new Set<string>();
  for (const r of rows) {
    if (r.kind !== "tool") continue;
    try {
      const id = (JSON.parse(r.body) as { id?: string }).id;
      if (id) answered.add(id);
    } catch {
      // Treat an unreadable id as unanswered. Such rows cannot be persisted; see checkBody in `msg/deliver.ts`.
    }
  }

  const want: Call[] = [];
  for (const r of rows) {
    if (r.kind !== "call") continue;
    try {
      for (const c of (JSON.parse(r.body) as { calls?: Call[] }).calls ?? []) {
        if (!answered.has(c.id)) want.push(c);
      }
    } catch {
      // Same reasoning as above.
    }
  }
  return want;
}

/** Result of one invocation. **Failures return a value too**; see the caller. */
async function runOne(db: Conn, reg: Registry, c: Call, at: At): Promise<unknown> {
  const row = all(db, `select identity, usable from tool where name = ?`, [c.name])[0] as
    | { identity: string; usable: number }
    | undefined;
  if (!row) return { error: `no tool named ${c.name} is registered` };
  if (!Number(row.usable)) return { error: `${c.name} is registered but usable = 0, so it was not run` };

  try {
    // Tool handles choose their execution location through `workplace`; forwarding is not this layer's responsibility.
    return await reg.get(row.identity).call({
      args: c.input,
      place: at.place,
      agent: at.agent,
      instance: at.instance,
      unit: at.unit,
    });
  } catch (e) {
    return { error: e instanceof Error ? e.message : String(e) };
  }
}

interface At {
  place: string;
  agent: string;
  instance: string;
  unit: number;
}

export function registerToolUnit(db: Conn, reg: Registry): string {
  reg.register(db, UNIT_TOOLS, EXPECT_MS, async (arg) => {
    const u = (arg ?? {}) as {
      agent: Row;
      task: Row;
      cycle: Row;
      place: string;
      instance: string;
      unit: number;
    };
    const agent = String(u.agent.name);
    const sub = tableNameOf("task_{}", String(u.task.mode));
    const bookkeeping = (ran: string[], why?: string) => ({
      role: "system",
      kind: "inject",
      body: JSON.stringify({ ran, ...(why ? { why } : {}) }),
    });

    // The subtable identifies the preceding station.
    const me = all(db, `select from_unit from "${sub}" where task = ? and cycle = ? and unit = ?`, [
      u.task.id,
      u.cycle.cycle,
      u.unit,
    ])[0] as { from_unit: number | null } | undefined;
    if (!me || me.from_unit === null) return bookkeeping([], "this station has no previous station, nothing to run");

    const calls = callsOf(db, agent, u.instance, Number(me.from_unit));
    if (calls.length === 0) return bookkeeping([], "the previous station left no tool call unanswered");

    const at: At = { place: u.place, agent, instance: u.instance, unit: u.unit };
    const ran: string[] = [];
    for (const c of calls) {
      const value = await runOne(db, reg, c, at);
      // **Persist failures too.** Without a result row, the model cannot see its call failed and may
      // assume success. Expose the error as a result so it can be corrected.
      //
      // Use the sole delivery pipeline and the shape expected by `toMsg` in `llm/index.ts`:
      // `{id, name, value}`. The adapter pairs it to the original call using `id`.
      deliver(db, {
        agent,
        instance: u.instance,
        unit: u.unit,
        by: "tool",
        who: c.name,
        body: JSON.stringify({ id: c.id, name: c.name, value }),
      });
      ran.push(c.name);
    }

    // Results have already been persisted individually. Return only **accounting** here: which tools
    // this unit ran. An assistant message would invent words the model never said.
    return bookkeeping(ran);
  });

  return UNIT_TOOLS;
}
