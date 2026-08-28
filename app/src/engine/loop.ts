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

export class Kernel {
  #store: Store;
  #log: Log;
  #reg: Registry;
  #timer: ReturnType<typeof setTimeout> | null = null;
  #ticking = false;
  #again = false;
  #stopped = true;

  constructor(store: Store, log: Log, reg: Registry) {
    this.#store = store;
    this.#log = log;
    this.#reg = reg;
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

  /** 一行的时限来自它那个智能体的执行单元句柄。 */
  #expectOf(agent: string): number {
    const row = one(this.#store.ro, `select unit from agent where name = ?`, [agent]);
    if (!row) throw new Error(`agent 表里没有 ${agent}`);
    return this.#reg.get(String(row.unit)).expectMs;
  }

  /** 超时的报出来。**不写新列** —— 「死了」是算出来的，不是存着的。 */
  #reap(rows: Pending[]): void {
    const now = Date.now();
    for (const r of rows) {
      const cap = this.#expectOf(r.agent);
      if (now - r.at <= cap) continue;
      this.#log.warn(
        `判死：${r.sub} ${r.task} ${r.cycle}#${r.unit}（${r.agent}/${r.instance}）已经 ${now - r.at}ms，超过 ${cap}ms`,
      );
    }
  }

  /** 三档里挑「还没开始」的那一档 —— 出站那份都还没落库。 */
  #ready(rows: Pending[]): Pending[] {
    return rows.filter((r) => this.#seqMax(r) === 0);
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

      // 这一轮该塞的 skill —— 先落库
      for (const identity of fire(this.#store.ro, "skill", facts)) {
        const s = one(this.#store.ro, `select body, role, usable from skill where identity = ?`, [identity]);
        if (!s || !Number(s.usable)) continue;
        const body = s.body ?? (await this.#reg.get(identity).call({ facts }));
        this.#push(p, String(s.role), "skill", text(body));
      }

      // 这一轮挂上的工具、该让它知道的规则 —— 都是查出来的，内核不认得名字
      const tools = fire(this.#store.ro, "tool", facts)
        .map((n) => one(this.#store.ro, `select * from tool where name = ? and usable = 1`, [n]))
        .filter((t): t is Row => t !== null);
      const rules = fire(this.#store.ro, "rule", facts);

      // 出站那份：完整上下文 + 这一轮的家当。**先落库，再发**
      const context = all(
        this.#store.ro,
        `select seq, role, kind, body from "${this.#msgTable(p.agent)}" where instance = ? and unit = ? order by seq`,
        [p.instance, p.unit],
      );
      this.#push(p, "system", "inject", JSON.stringify({ 出站: true, tools: tools.map((t) => t.name), rules }));

      const agent = one(this.#store.ro, `select unit from agent where name = ?`, [p.agent]);
      const back = await this.#reg.get(String(agent!.unit)).call({
        ...facts,
        place: p.place,
        instance: p.instance,
        unit: p.unit,
        context,
        tools,
        rules,
      });

      // 回来再落一行
      const r = (back ?? {}) as { role?: string; kind?: string; body?: unknown };
      this.#push(p, r.role ?? "assistant", r.kind ?? "prompt", text(r.body ?? back));

      await this.#infer(p, facts, back);
    } catch (e) {
      this.#log.error(`${p.sub} ${p.task} ${p.cycle}#${p.unit} 走不下去：${msg(e)}`);
    } finally {
      this.wake();
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
   */
  async #infer(p: Pending, facts: Facts, result: unknown): Promise<void> {
    const cyc = facts.cycle as { next: string; infer: string };
    const next = JSON.parse(String(cyc.next)) as string[];

    const picked = next.length === 0 ? null : await this.#reg.get(String(cyc.infer)).call({ ...facts, next, result });
    const to = picked == null ? null : String(picked);

    run(this.#store.rw, `update "${p.sub}" set done = 1 where task = ? and cycle = ? and unit = ?`, [
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
          [p.task, to, unit, p.cycle, p.unit, p.agent, p.instance, p.place, Date.now()],
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

  /** 主表那个大状态从子表推出来，不单独维护。 */
  #restate(task: string, sub: string): void {
    const got = one(this.#store.ro, `select count(*) as n, coalesce(sum(done), 0) as d from "${sub}" where task = ?`, [
      task,
    ])!;
    const n = Number(got.n);
    const d = Number(got.d);
    run(this.#store.rw, `update task set state = ? where id = ?`, [n === 0 ? "空" : d === n ? "完了" : "跑着", task]);
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
    const soonest = Math.min(...rows.map((r) => r.at + this.#expectOf(r.agent)));
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
