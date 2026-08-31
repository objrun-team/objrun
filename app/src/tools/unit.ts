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

/**
 * 上一站请求了、而**还没有结果**的那些调用。
 *
 * ## 两条都是踩出来的
 *
 * **一，不是「最后一条 `call` 行」。** 一个执行单元里可以有不止一条 `call` ——
 * 判决那一对（`deliverVerdict` 写的「调用 + 结果」）就是另一条。只看最后一条的话，
 * 模型自己请求的那次工具被跳过，跑的反而是判决那条。
 *
 * **二，已经有结果的不许再跑。** 判决那一对写进来的时候结果就配好了；再跑一遍
 * 就是同一个 `id` 两条结果，而模型那边对这一对的要求是死的：
 * `An assistant message with 'tool_calls' must be followed by tool messages
 * responding to each of them`。整条链路从此发不出去，任务卡到超时。
 *
 * 说到底是同一条规矩：**一次调用，一条结果。** 谁来答不重要，答过了就别再答。
 */
function callsOf(db: Conn, agent: string, instance: string, unit: number): Call[] {
  const t = tableNameOf("agent_{}_msg", agent);
  const rows = all(db, `select kind, body from "${t}" where instance = ? and unit = ? order by seq`, [
    instance,
    unit,
  ]) as { kind: string; body: string }[];

  // 这一站里已经答过的那些 id。
  const answered = new Set<string>();
  for (const r of rows) {
    if (r.kind !== "tool") continue;
    try {
      const id = (JSON.parse(r.body) as { id?: string }).id;
      if (id) answered.add(id);
    } catch {
      // 读不出 id 的当它没答过 —— 这种行进不了库（见 `msg/deliver.ts` 的 checkBody）
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
      // 同上
    }
  }
  return want;
}

/** 一次调用的结果。**跑失败也回一个值** —— 见调用处。 */
async function runOne(db: Conn, reg: Registry, c: Call, at: At): Promise<unknown> {
  const row = all(db, `select identity, usable from tool where name = ?`, [c.name])[0] as
    | { identity: string; usable: number }
    | undefined;
  if (!row) return { error: `no tool named ${c.name} is registered` };
  if (!Number(row.usable)) return { error: `${c.name} is registered but usable = 0, so it was not run` };

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
    if (!me || me.from_unit === null) return bookkeeping([], "this station has no previous station, nothing to run");

    const calls = callsOf(db, agent, u.instance, Number(me.from_unit));
    if (calls.length === 0) return bookkeeping([], "the previous station left no tool call unanswered");

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
