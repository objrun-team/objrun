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
import { deliver } from "../msg/deliver.ts";
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
  /**
   * 这是哪一类问题（`physics` / `chem` / `coding` …）。**扩展按它分发。**
   *
   * 跟 `mode` 是两回事：`mode` 是推理机制（cot / tot / 树），`domain` 是问题属于哪个
   * 领域。一个 skill 说「我是给物理题用的」，写的是 `dim=task, key=domain`——
   * 换台机器、换一跑、换道题，只要还是物理题，它就在。
   */
  domain?: string;
  /** 属于哪一跑（bench）。空 = 不属于任何一跑。 */
  run?: string;
  maxBranches?: number;
  /** 同一个父底下判死几个兄弟就回退到更上层换方向。 */
  maxDeadSiblings?: number;
  solveSeconds?: number;
  /**
   * **发布方不许它搜的东西。** 命中任何一条，那次检索的结果整份丢掉。
   *
   * 判据是「返回内容里任何位置出现过这个串」—— 不只是网址。一次实测里，模型按名字
   * 去扒题库，主站不通就换镜像、换文本代理、换存档站，查询串直接写着「row 1 answer」；
   * 光按域名挡的话，三条备用路各绕各的。
   *
   * 而且必须挡在**模型看见之前**：答案一旦进了上下文，那道题就已经废了，事后作废它
   * 只是记下损失。
   */
  noSearch?: string[];
  /**
   * **一轮里能搜几次。** 不给 = 不限。
   *
   * 跟 G 那个 `checks` 是同一个形状：一轮 = 一次尝试（树上一个节点），判死重来是
   * 新的一轮、新的额度；被拦下的那次不扣数，因为它什么都没查到。
   *
   * 要这道闸是因为**检索花的是钟，不是格子**：实测一跑，超时那批把一小时里的一半
   * 花在检索上，而每站的格子额度**一次都没碰到**。格子放宽治不了这个，只有按次数
   * 限才治得了。
   */
  maxSearches?: number;
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
  if (rows.length === 0) throw new Error(`no mode named ${mode} in the cycle table`);
  const heads = rows.filter((r) => {
    try {
      return (JSON.parse(r.from) as unknown[]).length === 0;
    } catch {
      throw new Error(`the from of ${mode}/${r.cycle} is not a readable list`);
    }
  });
  if (heads.length === 0) throw new Error(`${mode} has no entry point (every cycle has a non-empty from)`);
  if (heads.length > 1) {
    throw new Error(`${mode} has ${heads.length} entry points (${heads.map((h) => h.cycle).join(", ")}), so the task must name a cycle`);
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
  // 先问「这是不是一份东西」，再问它里面缺什么。**这是从 HTTP 进来的第一道**，
  // 不挡的话空请求会在 `p.id` 上崩，回给人的是一句 JS 内部话（`undefined is not
  // an object`）—— 那句话既不告诉他该发什么，也让人以为是服务端坏了。
  if (p === null || typeof p !== "object") throw new Error("the request body must be a JSON object");
  if (!p.id || !p.id.trim()) throw new Error("the task id cannot be empty");
  if (!SOURCES.includes(p.source)) throw new Error(`unrecognised source: ${p.source} (must be one of ${SOURCES.join(" / ")})`);
  if (!p.description || !p.description.trim()) throw new Error("a task needs a description");
  if (one(db, `select id from task where id = ?`, [p.id])) throw new Error(`a task named ${p.id} already exists`);

  // ── G 那道闸 ──────────────────────────────────────────────────────────
  //
  // 智能体在树内派生出来的任务**不许带 G**：放行它 = 智能体可以给自己（或自己
  // 派生的下一层）设定成功标准，那是**自提权**，判据就不再是判据。
  //
  // 闸按【来源】判，判在**唯一入口**上 —— 不指望每条派生路径自觉。老代码那边
  // 原先靠「某个调用方恰好没传这个参数」，签名一改闸就没了。
  if (p.objective !== undefined && p.objective !== null) {
    if (p.source === "agent") {
      throw new Error(`task ${p.id} has source agent (derived inside the tree by the agent) and may not carry a grading function - only a person can bind one, at publish time`);
    }
    if (typeof p.readable !== "boolean") {
      throw new Error(`task ${p.id} carries a grading function, so readable (whether the agent may read its definition) must be given explicitly - this bit has no default`);
    }
    if (!sealed) throw new Error("there is no sealed store, so a grading function cannot be kept");
  } else if (p.readable !== undefined) {
    throw new Error(`task ${p.id} carries no grading function, so it must not set readable`);
  }

  const agent = one(db, `select name from agent where name = ?`, [p.agent]);
  if (!agent) throw new Error(`no row in agent for ${p.agent}`);
  const place = one(db, `select place from workplace where place = ?`, [p.place]);
  if (!place) throw new Error(`no row in workplace for ${p.place}`);

  const cycle = p.cycle ?? firstCycle(db, p.mode);
  if (!one(db, `select cycle from cycle where mode = ? and cycle = ?`, [p.mode, cycle])) {
    throw new Error(`no row in the cycle table for ${p.mode}/${cycle}`);
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
    if (still.length) throw new Error(`sub-tables could not be grown: ${still.join(", ")}`);
  }

  // 定义期检测跑在**建任何行之前**。靠事务回滚也能不留脏行，但那是「先做了再撤」；
  // 这道题既然必然算不出结果，就该在动库之前拒掉。
  const g = p.objective === undefined || p.objective === null ? null : parseObjective(p.objective);
  if (g) {
    const errs = validate(g);
    if (errs.length) {
      throw new Error(`the grading function of task ${p.id} failed definition-time checks and was rejected:\n  - ${errs.join("\n  - ")}`);
    }
  }

  const instance = p.instance ?? `${p.id}#1`;
  const now = Date.now();
  // readable=true 的 G 不用躲 —— 验收标准本来就是需求的一部分，
  // 直接并进任务描述，连「读 G」这个动作都不存在。benchmark 样本才需要封。
  const description =
    g && p.readable ? `${p.description}

## Acceptance criteria
${JSON.stringify(p.objective, null, 2)}` : p.description;

  // 要么全建，要么一行都不留。
  //
  // 用 savepoint 不用 begin：**发一批的时候外面已经开着一个事务**，
  // 再 begin 一次会当场报 "cannot start a transaction within a transaction"。
  // savepoint 能嵌，而且跟着外层一起回滚。
  db.exec("savepoint publish_one");
  try {
    run(
      db,
      `insert into task (id, mode, place, run, source, domain, description, created_at, workdir, objective, readable,
                         claimed_by, result, max_branches, max_dead_siblings, solve_seconds,
                         max_searches, no_search, state)
       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, null, null, ?, ?, ?, ?, ?, 'open')`,
      [
        p.id, p.mode, p.place, p.run ?? "", p.source, p.domain ?? "", description, now, p.workdir ?? "",
        g ? "sealed" : null, g ? (p.readable ? 1 : 0) : null,
        p.maxBranches ?? 2, p.maxDeadSiblings ?? 3, p.solveSeconds ?? 1800,
        // 不给就是不限。**0 和负数也当成不给** —— 「一次都不许搜」该用 `noSearch`
        // 那条路说，或者干脆别挂这件工具；一个额度字段表达不了「禁用」。
        Number.isFinite(Number(p.maxSearches)) && Number(p.maxSearches) > 0 ? Number(p.maxSearches) : null,
        // **发布方说不许搜什么，原样存着。** 不给就是不限制 —— 空列表和「没有这一栏」
        // 是同一件事，没必要让调用方在两种「没有」之间选。
        p.noSearch && p.noSearch.length ? JSON.stringify(p.noSearch) : null,
      ],
    );
    run(
      db,
      `insert into "${sub}" (task, cycle, unit, node, from_cycle, from_unit, agent, instance, place, at, done)
       values (?, ?, 1, 1, null, null, ?, ?, ?, ?, 0)`,
      [p.id, cycle, p.agent, instance, p.place, now],
    );
    run(db, `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, 1, ?, 0)`, [
      instance,
      p.id,
      p.place,
    ]);
    // 任务描述就是上下文的第一条。**内核不解读它** —— 它只是一条消息。
    // 走那条唯一的投递管道：`by` 说的是**谁放的**，kind / role / 人写的那个标记
    // 都是推出来的。`source=user` 的任务描述是真人写的，缀上标记；别的来源不缀。
    deliver(db, {
      agent: p.agent,
      instance,
      unit: 1,
      by: p.source === "user" ? "user" : "world",
      body: description,
    });
    // G 封存在**建行都成功之后** —— 建行失败就根本不会留下孤儿 G。
    if (g) sealed!.seal(p.id, g);
    db.exec("release publish_one");
  } catch (e) {
    db.exec("rollback to publish_one");
    db.exec("release publish_one");
    throw e;
  }

  return { id: p.id, mode: p.mode, cycle, instance, objective: g !== null };
}
