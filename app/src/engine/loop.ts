/**
 * 内核。
 *
 * **一个循环，每一步的依据都在表里。** 这个文件里不许出现任何一个具体的
 * 模式名、周期名、智能体名、工具名、规则名 —— 出现了就说明那件事该在表里
 * 而没在。
 *
 * 内核自带的只有这几样，其余全靠查表：
 *
 * 1. 循环本身：读 → 组装 → 落库 → 调 → 落库 → 推断 → 写
 * 2. 句柄注册表（在 `registry.ts`）：名字换出真东西
 * 3. 判死：`now - at > expect_ms`
 * 4. 落库顺序：**先落库再发，不许反**
 * 5. 从子表推主表的 `state`
 *
 * ## 一行现在处于哪一步，是从库里**算**出来的，不存在内存里
 *
 * | 出站那份落了没 | 返回落了没 | 那它就是 |
 * | --- | --- | --- |
 * | 没有 | —— | 还没开始 → 这一轮该动它 |
 * | 落了 | 没有 | 正在跑 → 不碰它，除非超时 |
 * | 落了 | 落了 | 跑完了 → 推断下一步 |
 *
 * 所以内核**不需要一份内存里的「在跑」名单**。崩了重启，读同一份库，
 * 算出来的还是这三档中的同一档。这就是快照能成立的原因。
 */

import type { Conn, Store } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";
import { chainOf, type Unit } from "./chain.ts";
import type { Registry } from "./registry.ts";
import { deliver } from "../msg/deliver.ts";
import { fire, type Facts } from "./trigger.ts";

type Row = Record<string, unknown>;

export interface Log {
  info(msg: string): void;
  warn(msg: string): void;
  error(msg: string): void;
}

interface Pending extends Unit {
  mode: string;
  sub: string;
  agent: string;
  instance: string;
  place: string;
  at: number;
}

function one(db: Conn, sql: string, params: unknown[] = []): Row | null {
  const rows = all(db, sql, params);
  return rows.length ? rows[0] : null;
}

/** 内核挂出来的钩子。**内核不认得钩子里干什么** —— 它只在那一刻喊一声。 */
export interface Hooks {
  /** 一个任务的执行单元全干完了。判它成没成是别人的事，内核只报告「跑完了」。 */
  onDone?(task: string): void;
}

export class Kernel {
  #store: Store;
  #log: Log;
  #reg: Registry;
  #hooks: Hooks;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #ticking = false;
  /** 已经报过的坏行，同一条不重复刷屏。 */
  #cried = new Set<string>();
  #again = false;
  #stopped = true;

  constructor(store: Store, log: Log, reg: Registry, hooks: Hooks = {}) {
    this.#store = store;
    this.#log = log;
    this.#reg = reg;
    this.#hooks = hooks;
  }

  /**
   * 醒一下。
   *
   * **信号里不带数据。** 一旦带上「要处理的是哪一行」，它就成了一份内存队列 ——
   * 信号丢一次那件事就永远没人做，而库里看不出来。信号可丢，库不可丢：
   * 丢了最坏是晚一点（被定时器兜住），不是丢活。
   */
  wake(): void {
    if (this.#stopped) return;
    if (this.#ticking) {
      this.#again = true;
      return;
    }
    void this.#tick();
  }

  start(): void {
    this.#stopped = false;
    this.wake();
  }

  stop(): void {
    this.#stopped = true;
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
  }

  async #tick(): Promise<void> {
    this.#ticking = true;
    try {
      this.#reg.sync(this.#store.rw);
      const rows = this.#scan();
      this.#reap(rows);
      for (const p of this.#ready(rows)) void this.#advance(p);
      this.#arm(rows);
    } catch (e) {
      this.#log.error(`内核这一圈没转完：${msg(e)}`);
    } finally {
      this.#ticking = false;
      if (this.#again) {
        this.#again = false;
        this.wake();
      }
    }
  }

  /** 哪些子表要看：任务周期表里有几个模式就有几张。不去猜表名。 */
  #subs(): { mode: string; sub: string }[] {
    const modes = all(this.#store.ro, `select distinct mode from cycle`) as { mode: string }[];
    return modes.map((m) => ({ mode: m.mode, sub: tableNameOf("task_{}", m.mode) }));
  }

  /** 每次从库里现算，不留名单。 */
  #scan(): Pending[] {
    const out: Pending[] = [];
    for (const { mode, sub } of this.#subs()) {
      const rows = all(
        this.#store.ro,
        `select task, cycle, unit, from_cycle, from_unit, agent, instance, place, at
           from "${sub}" where done = 0`,
      ) as unknown as Pending[];
      for (const r of rows) out.push({ ...r, mode, sub });
    }
    return out;
  }

  /**
   * 这一行该调哪个句柄。
   *
   * **这一站走哪条轨，由周期表上的 `api_mode` 说了算**：
   *
   * - 非空 → 从 `agent.apis` 里挑一个 `modes` 含它的，调那一行的 `api.handle`
   * - 留空 → 调 `agent.unit`（这一站不用模型，比如把上一步请求的工具跑掉）
   *
   * **挑在这儿挑，适配器只管调。** 适配器自己再挑一次的话，「这一站用哪条轨」
   * 就有两个地方说了算，早晚漂。
   */
  #handleOf(p: Pending): { handle: string; api: { key_env: string; model: string } | null } {
    const agent = one(this.#store.ro, `select unit, apis from agent where name = ?`, [p.agent]);
    if (!agent) throw new Error(`agent 表里没有 ${p.agent}`);

    const cyc = one(this.#store.ro, `select api_mode from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    const want = String(cyc?.api_mode ?? "").trim();
    if (!want) return { handle: String(agent.unit), api: null };

    let apis: [string, string][];
    try {
      apis = JSON.parse(String(agent.apis ?? "[]")) as [string, string][];
    } catch {
      throw new Error(`agent ${p.agent} 的 apis 不是一份能读的列表`);
    }
    for (const [keyEnv, model] of apis) {
      const row = one(this.#store.ro, `select key_env, model, handle, modes from api where key_env = ? and model = ?`, [
        keyEnv,
        model,
      ]);
      if (!row) continue;
      const modes = String(row.modes ?? "")
        .split(",")
        .map((x) => x.trim());
      if (modes.includes(want)) {
        return { handle: String(row.handle), api: { key_env: keyEnv, model } };
      }
    }
    throw new Error(`${p.mode}/${p.cycle} 要一条 ${want} 的轨，但 agent ${p.agent} 的 apis 里没有一项支持`);
  }

  /** 一行的时限来自它这一站真正要调的那个句柄。 */
  #expectOf(p: Pending): number {
    return this.#reg.get(this.#handleOf(p).handle).expectMs;
  }

  /**
   * 算不出时限的行（配错了轨、句柄没注册）报出来，别把整圈带停。
   *
   * **一行坏了只该坏那一行。** 让它往上抛的话，同一圈里别的任务一并不转，
   * 而日志上只看得见一条错 —— 那才是最难查的：明明别的任务好好的，就是不动。
   */
  #expectSafe(p: Pending): number | null {
    try {
      return this.#expectOf(p);
    } catch (e) {
      // 同一条坏行只喊一次。每圈都喊的话，一个配错的任务能把日志刷成噪音，
      // 真出事的那条反而看不见。
      const key = `${p.sub}\u0000${p.task}\u0000${p.cycle}\u0000${p.unit}`;
      if (!this.#cried.has(key)) {
        this.#cried.add(key);
        this.#log.error(`${p.sub} ${p.task} ${p.cycle}#${p.unit} 这一行走不了：${msg(e)}`);
      }
      return null;
    }
  }

  /**
   * 超时的报出来。**不写新列** —— 「死了」是算出来的，不是存着的。
   *
   * 两层时限，管的不是一件事：
   *
   * - **单元级**：`now - at > expect_ms`，这一步卡住了
   * - **任务级**：`now - created_at > solve_seconds`，整道题超时了 —— 树再怎么长
   *   也该收工。没有这一层的话，一棵不停开兄弟的树能一直长下去
   */
  #reap(rows: Pending[]): void {
    const now = Date.now();
    for (const t of all(
      this.#store.ro,
      `select id, created_at, solve_seconds from task where state not in ('done','failed')`,
    ) as { id: string; created_at: number; solve_seconds: number }[]) {
      if (now - Number(t.created_at) <= Number(t.solve_seconds) * 1000) continue;
      const key = `任务超时\u0000${t.id}`;
      if (this.#cried.has(key)) continue;
      this.#cried.add(key);
      this.#log.warn(`任务 ${t.id} 超时：跑了 ${Math.round((now - Number(t.created_at)) / 1000)}s，上限 ${t.solve_seconds}s`);
      run(this.#store.rw, `update task set state = 'failed', result = ? where id = ?`, [
        JSON.stringify({ pass: 0, why: `超过 solve_seconds=${t.solve_seconds}s` }),
        t.id,
      ]);
    }
    for (const r of rows) {
      const cap = this.#expectSafe(r);
      if (cap === null || now - r.at <= cap) continue;
      this.#log.warn(
        `判死：${r.sub} ${r.task} ${r.cycle}#${r.unit}（${r.agent}/${r.instance}）已经 ${now - r.at}ms，超过 ${cap}ms`,
      );
    }
  }

  /**
   * 三档里挑「还没开始」的那一档 —— **出站那一行还没落库**。
   *
   * 判据是那条 `kind = "inject"` 的行，不是「一条消息都没有」：一个单元可以
   * 预先压好要问的话（那是数据，谁都能往库里放），有话不等于出站过。
   * 按「有没有消息」判的话，预置了 prompt 的单元会被当成正在跑，永远轮不到它。
   */
  #ready(rows: Pending[]): Pending[] {
    return rows.filter((r) => !this.#sentOut(r));
  }

  /** 这个单元出站过没有。 */
  #sentOut(r: Pending): boolean {
    const t = this.#msgTable(r.agent);
    const got = one(
      this.#store.ro,
      `select count(*) as c from "${t}" where instance = ? and unit = ? and kind = 'inject'`,
      [r.instance, r.unit],
    );
    return Number(got?.c ?? 0) > 0;
  }

  #msgTable(agent: string): string {
    return tableNameOf("agent_{}_msg", agent);
  }

  #seqMax(r: Pending): number {
    const t = this.#msgTable(r.agent);
    const got = one(this.#store.ro, `select coalesce(max(seq), 0) as m from "${t}" where instance = ? and unit = ?`, [
      r.instance,
      r.unit,
    ]);
    return Number(got?.m ?? 0);
  }

  /**
   * 推一行。
   *
   * 顺序是死的：**塞进去的先落库 → 才发出去 → 回来再落一行**。反过来的话，
   * 崩在中间就有「已经发出去、库里没有」的调用，那种状态恢复不了。
   */
  async #advance(p: Pending): Promise<void> {
    try {
      const facts = this.#factsOf(p);
      await this.#atMoment(p, facts, "unit_start");

      // 这一轮该塞的 skill —— 先落库
      for (const identity of fire(this.#store.ro, "skill", facts)) {
        const s = one(this.#store.ro, `select body, role, usable from skill where identity = ?`, [identity]);
        if (!s || !Number(s.usable)) continue;
        const body = s.body ?? (await this.#reg.get(identity).call({ facts }));
        // **走那条唯一的投递管道** —— kind 和 role 都是推出来的，不在这儿填。
        deliver(this.#store.rw, {
          agent: p.agent,
          instance: p.instance,
          unit: p.unit,
          by: "skill",
          who: identity,
          body: text(body),
        });
      }

      // 这一轮挂上的工具 = **系统工具 ∪ trigger 命中的**。
      // 系统工具（读写那一组）谁一上来都有，不看条件 —— 不这么分的话，
      // 按「一条条件都没有 = 从不触发」那条语义，它们谁也拿不到。
      // 两边都是查出来的，内核仍然不认得任何一个工具名。
      const tools = new Map<string, Row>();
      for (const t of all(this.#store.ro, `select * from tool where system = 1 and usable = 1`)) {
        tools.set(String(t.name), t);
      }
      for (const n of fire(this.#store.ro, "tool", facts)) {
        const t = one(this.#store.ro, `select * from tool where name = ? and usable = 1`, [n]);
        if (t) tools.set(String(t.name), t);
      }
      const kit = [...tools.values()];
      const rules = fire(this.#store.ro, "rule", facts);

      // 出站那份：完整上下文 + 这一轮的家当。**先落库，再发**
      const context = all(
        this.#store.ro,
        `select seq, role, kind, body from "${this.#msgTable(p.agent)}" where instance = ? and unit = ? order by seq`,
        [p.instance, p.unit],
      );
      // 出站这一行是**快照里那次调用的凭据**：模型当时被告知有哪些工具、
      // 每个工具的用法约定是什么。不记的话，回头看这一步就说不清它为什么那么做。
      deliver(this.#store.rw, {
        agent: p.agent,
        instance: p.instance,
        unit: p.unit,
        by: "kernel",
        // 键名一律 ASCII：这一行**客户端读得到**（`/tasks/:id/messages` 会把它解开），
        // 中文键名等于逼着客户端写 `data["出站"]`，而且每过一层编码都可能烂。
        body: JSON.stringify({
          sent: true,
          tools: kit.map((t) => t.name),
          prompts: kit.map((t) => t.prompt).filter(Boolean),
          rules,
        }),
      });

      await this.#atMoment(p, facts, "pre_send");

      const pickd = this.#handleOf(p);
      const back = await this.#reg.get(pickd.handle).call({
        ...facts,
        place: p.place,
        instance: p.instance,
        unit: p.unit,
        // 这一站挑好的那条轨。适配器直接用，不用自己再挑一遍。
        api: pickd.api,
        context,
        tools: kit,
        rules,
      });

      // 回来再落一行
      // 模型自己说的那条**不走投递管道** —— 那是它自己的轨迹，直接落库；
      // 而且 kind 得由适配器说（prompt 还是 call），推不出来。
      const r = (back ?? {}) as { role?: string; kind?: string; body?: unknown };
      this.#push(p, r.role ?? "assistant", r.kind ?? "prompt", text(r.body ?? back));

      await this.#atMoment(p, facts, "post_send");
      await this.#infer(p, facts, back);
      // 成功推完才醒下一圈。**失败不醒** —— 醒了就是原地热循环：
      // 这一行还是「该动」的那一档，下一圈又挑到它，再失败，再醒。
      // 失败的那条留给下面那个 deadline 定时器，超时了按判死处理。
      this.wake();
    } catch (e) {
      this.#log.error(`${p.sub} ${p.task} ${p.cycle}#${p.unit} 走不下去：${msg(e)}`);
    }
  }

  /**
   * 到某个时刻了，喊一声：命中的规则跑一遍。**这就是钩子。**
   *
   * 内核不认得任何一条规则叫什么 —— 它只报「现在是哪一刻」，谁挂在这一刻上由
   * `trigger` 说了算（`dim=moment`）。老代码那边钩子是一个目录一个时刻；
   * 我们这儿时刻是数据里的一个值，不另开表。
   *
   * **一条规则炸了只炸它自己。** 钩子挂在主路上，让它把整步带停的话，
   * 一条写坏的规则能让所有任务都不动。
   */
  async #atMoment(p: Pending, facts: Facts, moment: string): Promise<void> {
    const at = { ...facts, moment };
    for (const identity of fire(this.#store.ro, "rule", at)) {
      try {
        await this.#reg.get(identity).call({ ...at, sub: p.sub, unit: p.unit, instance: p.instance });
      } catch (e) {
        this.#log.error(`规则 ${identity} 在 ${moment} 这一刻炸了：${msg(e)}`);
      }
    }
  }

  /** 往上下文里压一条。`seq` 在这个单元里连着排。 */
  #push(p: Pending, role: string, kind: string, body: string): void {
    const t = this.#msgTable(p.agent);
    const seq = this.#seqMax(p) + 1;
    run(this.#store.rw, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, ?, ?, ?, ?)`, [
      p.instance,
      p.unit,
      seq,
      role,
      kind,
      body,
      Date.now(),
    ]);
  }

  /** 比条件时手上的东西。链路串按 `chain.ts` 那个拼法 —— 那是协议。 */
  #factsOf(p: Pending): Facts {
    const agent = one(this.#store.ro, `select * from agent where name = ?`, [p.agent]);
    const task = one(this.#store.ro, `select * from task where id = ?`, [p.task]);
    const cycle = one(this.#store.ro, `select * from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    if (!agent) throw new Error(`agent 表里没有 ${p.agent}`);
    if (!task) throw new Error(`task 表里没有 ${p.task}`);
    if (!cycle) throw new Error(`cycle 表里没有 ${p.mode}/${p.cycle}`);
    return { agent, task, cycle, chain: chainOf(this.#store.ro, p.sub, p.mode, p) };
  }

  /**
   * 推断下一个周期，然后落新行。
   *
   * **候选（第 4、5 列）决定了用哪个推断函数**，推断函数只在候选里挑一个。
   * 挑出候选之外的东西 → 当场炸，不许它自由发挥。
   *
   * 推断函数可以回三种形状：
   *
   * | 回什么 | 意思 |
   * | --- | --- |
   * | `null` | 到此为止 |
   * | `"周期名"` | 走那个周期，**从当前这一行接** |
   * | `{to, from_cycle, from_unit, status}` | 走那个周期，**从指定那一行接**；顺带给当前这一行盖个终止状态 |
   *
   * 第三种是给树用的：判死之后要在**同一个父**底下开兄弟，回退时要接到**祖先**上 ——
   * 都不是「从当前行接」。内核只认这个形状，不认得「兄弟」「回退」是什么意思。
   */
  async #infer(p: Pending, facts: Facts, result: unknown): Promise<void> {
    const cyc = facts.cycle as { next: string; infer: string };
    const next = JSON.parse(String(cyc.next)) as string[];

    // 递给推断函数的除了 facts，还有「我是哪一行」—— 开兄弟和回退都要照着树走。
    const picked =
      next.length === 0
        ? null
        : await this.#reg.get(String(cyc.infer)).call({ ...facts, next, result, sub: p.sub, unit: p.unit });
    const said = picked !== null && typeof picked === "object" ? (picked as Record<string, unknown>) : null;
    const to = picked == null ? null : said ? (said.to == null ? null : String(said.to)) : String(picked);
    // **「没说」和「说了是根」是两回事**：没说 = 从当前这一行接；
    // 说了 `null` = 挂在根上（那一行没有父）。混成一个的话，根节点的兄弟会
    // 挂到根自己身上 —— 树看着长了，形状是错的，而且不报错。
    const saidFrom = said !== null && "from_cycle" in said;
    const fromCycle = saidFrom ? (said!.from_cycle == null ? null : String(said!.from_cycle)) : p.cycle;
    const fromUnit = saidFrom ? (said!.from_unit == null ? null : Number(said!.from_unit)) : p.unit;
    const status = said && said.status != null ? String(said.status) : null;

    run(this.#store.rw, `update "${p.sub}" set done = 1, status = ? where task = ? and cycle = ? and unit = ?`, [
      status,
      p.task,
      p.cycle,
      p.unit,
    ]);
    const ctx = tableNameOf("agent_{}_ctx", p.agent);
    run(this.#store.rw, `update "${ctx}" set done = 1 where instance = ? and unit = ?`, [p.instance, p.unit]);

    if (to !== null) {
      if (!next.includes(to)) {
        throw new Error(`${cyc.infer} 推出来的 ${to} 不在候选里（候选是 ${next.join("、")}）`);
      }
      const cap = one(this.#store.ro, `select max_units from cycle where mode = ? and cycle = ?`, [p.mode, to]);
      if (!cap) throw new Error(`cycle 表里没有 ${p.mode}/${to}`);
      const used = Number(
        one(this.#store.ro, `select count(*) as c from "${p.sub}" where task = ? and cycle = ?`, [p.task, to])!.c,
      );
      if (used >= Number(cap.max_units)) {
        this.#log.warn(`${p.task} 的 ${p.mode}/${to} 已经用满 ${cap.max_units} 个执行单位，不再开`);
      } else {
        // **编号在一个任务里单调递增，不按周期重新数。** 智能体那边的
        // ctx 表主键是 (instance, unit)，不带周期 —— 每个周期重数的话，
        // think#1 和 act#1 会在那张表里撞成一行。
        // max_units 限的是「这个周期名下有几行」，跟编号无关。
        const unit =
          Number(one(this.#store.ro, `select coalesce(max(unit), 0) as m from "${p.sub}" where task = ?`, [p.task])!.m) +
          1;
        run(
          this.#store.rw,
          `insert into "${p.sub}" (task, cycle, unit, from_cycle, from_unit, agent, instance, place, at, done)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
          [p.task, to, unit, fromCycle, fromUnit, p.agent, p.instance, p.place, Date.now()],
        );
        // 智能体那边同一件事的另一半，跟着开 —— 两边要能对咬
        run(
          this.#store.rw,
          `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, ?, ?, 0)`,
          [p.instance, p.task, unit, p.place],
        );
      }
    }

    this.#restate(p.task, p.sub);
  }

  /**
   * 主表那个大状态从子表推出来，不单独维护。取值是那四态：
   *
   * | 子表长什么样 | 那就是 |
   * | --- | --- |
   * | 一个执行单位都没有 | `open` —— 待领取 |
   * | 有没干完的 | `claimed` —— 有人在干 |
   * | 全干完了 | `done` |
   *
   * `failed` 推不出来 —— 它是**判定**的结果，不是数出来的。等验证函数那一块
   * 落地了由它显式写。现在硬凑一个的话，那一列就开始说谎。
   */
  #restate(task: string, sub: string): void {
    const got = one(this.#store.ro, `select count(*) as n, coalesce(sum(done), 0) as d from "${sub}" where task = ?`, [
      task,
    ])!;
    const n = Number(got.n);
    const d = Number(got.d);
    const now = one(this.#store.ro, `select state from task where id = ?`, [task]);
    const was = String(now?.state ?? "");
    if (was === "failed") return; // 判过失败的不许被数回去
    const next = n === 0 ? "open" : d === n ? "done" : "claimed";
    run(this.#store.rw, `update task set state = ? where id = ?`, [next, task]);
    // 跑完了喊一声。**内核不知道那边会干什么** —— 判成没成不是它的事。
    if (next === "done" && was !== "done") this.#hooks.onDone?.(task);
  }

  /**
   * 定时器设到**库里最近的那个 deadline**，不按固定间隔扫。
   *
   * 超时的本质是「没有人写」—— 没有写就没有信号，只能靠时钟发现。但也不用一直扫：
   * 没有新写就正好在该判死的那一刻醒，有新写就重算一次。
   */
  #arm(rows: Pending[]): void {
    if (this.#timer) clearTimeout(this.#timer);
    this.#timer = null;
    if (this.#stopped || rows.length === 0) return;
    const now = Date.now();
    const deadlines = rows.map((r) => {
      const cap = this.#expectSafe(r);
      return cap === null ? null : r.at + cap;
    }).filter((d): d is number => d !== null);
    if (deadlines.length === 0) return;
    const soonest = Math.min(...deadlines);
    this.#timer = setTimeout(() => this.wake(), Math.max(soonest - now, 50));
    this.#timer.unref?.();
  }
}

function text(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v ?? null);
}

function msg(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
