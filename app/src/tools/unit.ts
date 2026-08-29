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
 *   模型说「我要调 bash」        真去跑，把结果落回上下文
 * ```
 *
 * ## 上一站在哪儿
 *
 * **每个执行单元的上下文是独立的**（`agent_<名字>_msg` 主键是 `instance,unit`），
 * 所以「模型刚才请求了什么」不在这一站的上下文里，在**上一站**。上一站是谁由
 * 子表的 `from_unit` 说了算 —— 不是「当前 unit 减一」：树开了兄弟之后编号是
 * 单调递增的，减一会指到别人身上。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";
import { deliver } from "../msg/deliver.ts";

/** 这个句柄的名字。周期表上 `api_mode` 留空的那一站把 `agent.unit` 指向它。 */
export const UNIT_TOOLS = "fn:unit.tools";

/** 一次工具调用跑多久算死。跟工具本身那条时限是两回事：这一站可能跑好几个。 */
export const EXPECT_MS = 600_000;

type Row = Record<string, unknown>;

interface Call {
  id: string;
  name: string;
  input: unknown;
}

/** 上一站那条 `call` 里有哪些调用。没有就回空。 */
function callsOf(db: Conn, agent: string, instance: string, unit: number): { text: string; calls: Call[] } {
  const t = tableNameOf("agent_{}_msg", agent);
  const rows = all(db, `select body from "${t}" where instance = ? and unit = ? and kind = 'call' order by seq desc limit 1`, [
    instance,
    unit,
  ]) as { body: string }[];
  if (rows.length === 0) return { text: "", calls: [] };
  try {
    const v = JSON.parse(rows[0].body) as { text?: string; calls?: Call[] };
    return { text: v.text ?? "", calls: v.calls ?? [] };
  } catch {
    return { text: "", calls: [] };
  }
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
    const mode = String(u.task.mode);
    const sub = tableNameOf("task_{}", mode);

    // 上一站是谁 —— 子表说了算。
    const me = all(db, `select from_unit from "${sub}" where task = ? and cycle = ? and unit = ?`, [
      u.task.id,
      u.cycle.cycle,
      u.unit,
    ])[0] as { from_unit: number | null } | undefined;

    if (!me || me.from_unit === null) {
      return { role: "system", kind: "inject", body: JSON.stringify({ ran: [], why: "这一站没有上一站，没什么可跑的" }) };
    }

    const { calls } = callsOf(db, agent, u.instance, Number(me.from_unit));
    if (calls.length === 0) {
      return { role: "system", kind: "inject", body: JSON.stringify({ ran: [], why: "上一站没请求任何工具" }) };
    }

    const ran: string[] = [];
    for (const c of calls) {
      const identity = `fn:tool.${c.name}`;
      let value: unknown;
      try {
        // 工具句柄自己按 `workplace` 决定这一次在哪儿跑 —— 这一层不管转发。
        value = await reg.get(identity).call({
          args: c.input,
          place: u.place,
          agent,
          instance: u.instance,
          unit: u.unit,
        });
      } catch (e) {
        // **跑失败也要落一行。** 不落的话模型下一站看不到自己那次调用的下场，
        // 只会以为它成了。错的内容当结果给它 —— 它看得见才改得了。
        value = { error: e instanceof Error ? e.message : String(e) };
      }
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
    // 回一条 assistant 的话会凭空多出一句模型没说过的话。
    return { role: "system", kind: "inject", body: JSON.stringify({ ran }) };
  });

  return UNIT_TOOLS;
}
