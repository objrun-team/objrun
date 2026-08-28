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
import { parseObjective, validate } from "../objective/spec.ts";
import type { Sealed } from "../objective/store.ts";

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
  /** 同一个父底下判死几个兄弟就回退到更上层换方向。 */
  maxDeadSiblings?: number;
  solveSeconds?: number;
  /**
   * 验证函数 `G` —— 「这个任务算不算做成了」的标准。
   *
   * **绑定发生在发布这一刻，是准入条件。** 给了就当场检、当场封存；过不了
   * 定义期检测就**拒收整个任务** —— 与其让一个必然算不出结果的 G 混进系统，
   * 不如这道题根本别发布。
   */
  objective?: unknown;
  /**
   * 能不能直接读到 G 的定义。**带 G 就必须显式给，没有默认值。**
   *
   * 设定权在发布方，发布方本来就知道要不要给看。给个默认值等于替他决定，
   * 而且会长出「没人想过的隐式策略」。
   */
  readable?: boolean;
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
export function publish(
  db: Conn,
  p: Publish,
  sealed?: Sealed,
): { id: string; mode: string; cycle: string; instance: string; objective: boolean } {
  if (!p.id || !p.id.trim()) throw new Error("任务 id 不能是空的");
  if (!SOURCES.includes(p.source)) throw new Error(`不认得的来源：${p.source}（只能是 ${SOURCES.join(" / ")}）`);
  if (!p.description || !p.description.trim()) throw new Error("任务得有描述");
  if (one(db, `select id from task where id = ?`, [p.id])) throw new Error(`任务 ${p.id} 已经有了`);

  // ── G 那道闸 ──────────────────────────────────────────────────────────
  //
  // 智能体在树内派生出来的任务**不许带 G**：放行它 = 智能体可以给自己（或自己
  // 派生的下一层）设定成功标准，那是**自提权**，判据就不再是判据。
  //
  // 闸按【来源】判，判在**唯一入口**上 —— 不指望每条派生路径自觉。老代码那边
  // 原先靠「某个调用方恰好没传这个参数」，签名一改闸就没了。
  if (p.objective !== undefined && p.objective !== null) {
    if (p.source === "agent") {
      throw new Error(`任务 ${p.id} 的来源是 agent（智能体在树内派生），**不许带验证函数 G** —— G 只能由人在发布那一刻绑定`);
    }
    if (typeof p.readable !== "boolean") {
      throw new Error(`任务 ${p.id} 带了 G，就必须显式给 readable（能不能直接读到 G 的定义）—— 这一位没有默认值`);
    }
    if (!sealed) throw new Error("没有封存区，装不下 G");
  } else if (p.readable !== undefined) {
    throw new Error(`任务 ${p.id} 没带 G，就不该给 readable`);
  }

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

  // 定义期检测跑在**建任何行之前**。靠事务回滚也能不留脏行，但那是「先做了再撤」；
  // 这道题既然必然算不出结果，就该在动库之前拒掉。
  const g = p.objective === undefined || p.objective === null ? null : parseObjective(p.objective);
  if (g) {
    const errs = validate(g);
    if (errs.length) {
      throw new Error(`任务 ${p.id} 的 G 没通过定义期检测，拒收：\n  - ${errs.join("\n  - ")}`);
    }
  }

  const instance = p.instance ?? `${p.id}#1`;
  const now = Date.now();
  // readable=true 的 G 不用躲 —— 验收标准本来就是需求的一部分，
  // 直接并进任务描述，连「读 G」这个动作都不存在。benchmark 样本才需要封。
  const description =
    g && p.readable ? `${p.description}

【验收标准】
${JSON.stringify(p.objective, null, 2)}` : p.description;

  // 要么全建，要么一行都不留。
  db.exec("begin");
  try {
    run(
      db,
      `insert into task (id, mode, place, source, description, created_at, workdir, objective, readable,
                         claimed_by, result, max_branches, max_dead_siblings, solve_seconds, state)
       values (?, ?, ?, ?, ?, ?, ?, ?, ?, null, null, ?, ?, ?, 'open')`,
      [
        p.id, p.mode, p.place, p.source, description, now, p.workdir ?? "",
        g ? "sealed" : null, g ? (p.readable ? 1 : 0) : null,
        p.maxBranches ?? 2, p.maxDeadSiblings ?? 3, p.solveSeconds ?? 1800,
      ],
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
      [instance, description, now],
    );
    // G 封存在**建行都成功之后** —— 建行失败就根本不会留下孤儿 G。
    if (g) sealed!.seal(p.id, g);
    db.exec("commit");
  } catch (e) {
    db.exec("rollback");
    throw e;
  }

  return { id: p.id, mode: p.mode, cycle, instance, objective: g !== null };
}
