/**
 * 执行单元：**把上一站模型请求的工具真跑掉。**
 *
 * 少了这一步，工具那条链是断的：摆给模型看 → 它请求 → 落一行 `call` → 没了。
 * 请求永远不被执行，而且不报错 —— 任务照样往下走，只是它以为自己调过的东西
 * 其实没跑。
 *
 * ## 挂在哪儿
 *
 * 它是一个 `agent.unit` 句柄。周期表上 `api_mode` 留空的那一站走它：
 *
 * ```
 *   ask（apiMode: chat）  ──→  act（apiMode 留空，走这个）  ──→ ask ──→ …
 *   模型说「我要调 dice」        真去跑，把结果落回上下文
 * ```
 *
 * ## 上一站在哪儿
 *
 * **每个执行单元的上下文是独立的**（`agent_<名字>_msg` 主键是 `instance,unit`），
 * 所以「模型刚才请求了什么」不在这一站里，在**上一站**。上一站是谁由子表的
 * `from_unit` 说了算 —— 不是「当前 unit 减一」：树开了兄弟之后编号单调递增，
 * 减一会指到别人身上。
 *
 * ## 实现是哪一条，去表里读
 *
 * **别照名字拼句柄名。** 拼 `fn:tool.<名字>` 只有内置那几个恰好对得上；进程外的
 * （`http://`）和 MCP server 报来的一律拼不出来，于是「工具挂上了、模型也调了、
 * 就是跑不动」，而错只藏在那一行工具结果里。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";
import { deliver } from "../msg/deliver.ts";

/** 这个句柄的名字。周期表上 `api_mode` 留空的那一站把 `agent.unit` 指向它。 */
export const UNIT_TOOLS = "fn:unit.tools";

/** 这一站多久算死。跟单个工具那条时限是两回事：这一站可能连着跑好几个。 */
export const EXPECT_MS = 600_000;

type Row = Record<string, unknown>;

interface Call {
  id: string;
  name: string;
  input: unknown;
}

/** 上一站那条 `call` 里有哪些调用。没有就回空。 */
function callsOf(db: Conn, agent: string, instance: string, unit: number): Call[] {
  const t = tableNameOf("agent_{}_msg", agent);
  const rows = all(
    db,
    `select body from "${t}" where instance = ? and unit = ? and kind = 'call' order by seq desc limit 1`,
    [instance, unit],
  ) as { body: string }[];
  if (rows.length === 0) return [];
  try {
    return (JSON.parse(rows[0].body) as { calls?: Call[] }).calls ?? [];
  } catch {
    return [];
  }
}

/** 一次调用的结果。**跑失败也回一个值** —— 见调用处。 */
async function runOne(db: Conn, reg: Registry, c: Call, at: At): Promise<unknown> {
  const row = all(db, `select identity, usable from tool where name = ?`, [c.name])[0] as
    | { identity: string; usable: number }
    | undefined;
  if (!row) return { error: `tool 表里没有 ${c.name} —— 模型请求了一个没登记的工具` };
  if (!Number(row.usable)) return { error: `${c.name} 登记着但 usable = 0，这一次没跑` };

  try {
    // 工具句柄自己按 `workplace` 决定这一次在哪儿跑 —— 这一层不管转发。
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

    // 上一站是谁 —— 子表说了算。
    const me = all(db, `select from_unit from "${sub}" where task = ? and cycle = ? and unit = ?`, [
      u.task.id,
      u.cycle.cycle,
      u.unit,
    ])[0] as { from_unit: number | null } | undefined;
    if (!me || me.from_unit === null) return bookkeeping([], "这一站没有上一站，没什么可跑的");

    const calls = callsOf(db, agent, u.instance, Number(me.from_unit));
    if (calls.length === 0) return bookkeeping([], "上一站没请求任何工具");

    const at: At = { place: u.place, agent, instance: u.instance, unit: u.unit };
    const ran: string[] = [];
    for (const c of calls) {
      const value = await runOne(db, reg, c, at);
      // **跑失败也要落一行。** 不落的话模型下一站看不到自己那次调用的下场，
      // 只会以为它成了。错的内容当结果给它 —— 看得见才改得了。
      //
      // 走那条唯一的投递管道。形状跟 `llm/index.ts` 的 `toMsg` 对着：
      // `{id, name, value}` —— 那边靠 `id` 把结果配回模型的那次调用。
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

    // 结果已经一条条落进去了，这儿回的是**记账**：这一站跑了哪几个。
    // 回一条 assistant 的话，会凭空多出一句模型没说过的话。
    return bookkeeping(ran);
  });

  return UNIT_TOOLS;
}
