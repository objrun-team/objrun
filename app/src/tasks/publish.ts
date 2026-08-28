/**
 * 发任务。
 *
 * **这是任务从外面进系统的唯一入口动作。** 唯一 —— 所以准入的闸设在这儿，
 * 不指望每个调用方自觉。老代码那边的原话是：闸按【来源】判，「原先这条只靠
 * 某个调用方恰好没传那个参数，是『恰好没传』而非『不可能传』：签名一改、
 * 或多一条派生路径，闸就没了」。
 *
 * 一次调用把该建的都建了：
 *
 * 1. `task` 一行 —— 身份（出生即定，永不重写）+ 状态
 * 2. 首个执行单元 —— `task_<mode>` 一行
 * 3. 智能体那边对应的一行 —— `agent_<name>_ctx`，两边要能对咬
 * 4. 任务描述压进上下文 —— `agent_<name>_msg` 的第一条
 *
 * **要么全建，要么一行都不留。** 中间断了会留下建了行没建单元的任务，
 * 那种任务库里看着存在、永远不动，而且不报错。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { install, tableNameOf } from "../install/index.ts";

/** 谁发的。**这是准入判据** —— 不同来源能做的事不一样。 */
export const SOURCES = ["user", "agent", "world", "eacn"] as const;
export type Source = (typeof SOURCES)[number];

/** 任务的四态。最薄的一套；blocked / cancelled / paused 之类按需再扩，不预设。 */
export const STATES = ["open", "claimed", "done", "failed"] as const;

export interface Publish {
  id: string;
  /** 走哪种执行模式 → 任务周期表第 1 列。 */
  mode: string;
  /** 从这个模式的哪个周期起步。不给就取 `from` 为空的那一个。 */
  cycle?: string;
  /** 交给哪个智能体。 */
  agent: string;
  /** 哪个实例。不给就按任务 id 生一个。 */
  instance?: string;
  /** 在哪儿干 → `workplace.place`。 */
  place: string;
  /** 那个场所里的落脚路径。 */
  workdir?: string;
  source: Source;
  description: string;
  maxBranches?: number;
  solveSeconds?: number;
}

function one(db: Conn, sql: string, params: unknown[] = []): Record<string, unknown> | null {
  const rows = all(db, sql, params);
  return rows.length ? rows[0] : null;
}

/**
 * 起步的那个周期：`from` 是空列表的那一个。
 *
 * **不许猜**：有多个起点或者一个都没有，都当场炸。猜一个的话，任务会从一个
 * 谁也没想到的地方开始跑，而且跑起来了，不报错。
 */
function firstCycle(db: Conn, mode: string): string {
  const rows = all(db, `select cycle, "from" from cycle where mode = ?`, [mode]) as {
    cycle: string;
    from: string;
  }[];
  if (rows.length === 0) throw new Error(`任务周期表里没有 ${mode} 这个模式`);
  const heads = rows.filter((r) => {
    try {
      return (JSON.parse(r.from) as unknown[]).length === 0;
    } catch {
      throw new Error(`${mode}/${r.cycle} 的 from 不是一份能读的列表`);
    }
  });
  if (heads.length === 0) throw new Error(`${mode} 一个起点都没有（每个周期的 from 都非空）`);
  if (heads.length > 1) {
    throw new Error(`${mode} 有 ${heads.length} 个起点（${heads.map((h) => h.cycle).join("、")}），发任务时得指定 cycle`);
  }
  return heads[0].cycle;
}

/**
 * 发一个任务。
 *
 * 每一条检查失败都是**拒收整个任务** —— 与其让一个必然跑不动的任务混进系统，
 * 不如这道题根本别发布。
 */
export function publish(db: Conn, p: Publish): { id: string; mode: string; cycle: string; instance: string } {
  if (!p.id || !p.id.trim()) throw new Error("任务 id 不能是空的");
  if (!SOURCES.includes(p.source)) throw new Error(`不认得的来源：${p.source}（只能是 ${SOURCES.join(" / ")}）`);
  if (!p.description || !p.description.trim()) throw new Error("任务得有描述");
  if (one(db, `select id from task where id = ?`, [p.id])) throw new Error(`任务 ${p.id} 已经有了`);

  const agent = one(db, `select name from agent where name = ?`, [p.agent]);
  if (!agent) throw new Error(`agent 表里没有 ${p.agent}`);
  const place = one(db, `select place from workplace where place = ?`, [p.place]);
  if (!place) throw new Error(`workplace 表里没有 ${p.place}`);

  const cycle = p.cycle ?? firstCycle(db, p.mode);
  if (!one(db, `select cycle from cycle where mode = ? and cycle = ?`, [p.mode, cycle])) {
    throw new Error(`任务周期表里没有 ${p.mode}/${cycle}`);
  }

  const sub = tableNameOf("task_{}", p.mode);
  const ctx = tableNameOf("agent_{}_ctx", p.agent);
  const msg = tableNameOf("agent_{}_msg", p.agent);
  const missing = [sub, ctx, msg].filter(
    (t) => all(db, `select name from sqlite_master where type='table' and name = ?`, [t]).length === 0,
  );
  if (missing.length) {
    // 子表是照着 cycle / agent 的行长出来的。刚从 HTTP 灌进来一个新模式或新智能体，
    // 那几张子表还不存在 —— **这儿现长一次**，装表是幂等的。
    // 不长的话，「外面纯用 HTTP 发任务」就断在这儿：灌完声明还得重启一趟。
    install(db);
    const still = missing.filter(
      (t) => all(db, `select name from sqlite_master where type='table' and name = ?`, [t]).length === 0,
    );
    if (still.length) throw new Error(`子表长不出来：${still.join("、")}`);
  }

  const instance = p.instance ?? `${p.id}#1`;
  const now = Date.now();

  // 要么全建，要么一行都不留。
  db.exec("begin");
  try {
    run(
      db,
      `insert into task (id, mode, place, source, description, created_at, workdir, claimed_by, result,
                         max_branches, solve_seconds, state)
       values (?, ?, ?, ?, ?, ?, ?, null, null, ?, ?, 'open')`,
      [p.id, p.mode, p.place, p.source, p.description, now, p.workdir ?? "", p.maxBranches ?? 2, p.solveSeconds ?? 1800],
    );
    run(
      db,
      `insert into "${sub}" (task, cycle, unit, from_cycle, from_unit, agent, instance, place, at, done)
       values (?, ?, 1, null, null, ?, ?, ?, ?, 0)`,
      [p.id, cycle, p.agent, instance, p.place, now],
    );
    run(db, `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, 1, ?, 0)`, [
      instance,
      p.id,
      p.place,
    ]);
    // 任务描述就是上下文的第一条。**内核不解读它** —— 它只是一条消息。
    run(
      db,
      `insert into "${msg}" (instance, unit, seq, role, kind, body, at) values (?, 1, 1, 'user', 'user', ?, ?)`,
      [instance, p.description, now],
    );
    db.exec("commit");
  } catch (e) {
    db.exec("rollback");
    throw e;
  }

  return { id: p.id, mode: p.mode, cycle, instance };
}
