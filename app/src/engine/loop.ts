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
import { bodiesAt, pressNode, readyLevels, swapClosed, type Level, type Line } from "../msg/press.ts";
import { SUBMIT } from "../tree/dfs.ts";
import { chainOf, type Unit } from "./chain.ts";
import type { Registry } from "./registry.ts";
import { answerMissing, mendPairs, type Pair, checkBody, deliver, type Said, sentAsIn } from "../msg/deliver.ts";
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
/** 这一站之后还能去哪几站。**流转表上的事实**，不是判断。 */
function nextOf(db: Conn, mode: string, cycle: string): string[] {
  const r = all(db, `select next from cycle where mode = ? and cycle = ?`, [mode, cycle])[0] as
    | { next?: string }
    | undefined;
  try {
    const v = JSON.parse(String(r?.next ?? "[]")) as unknown;
    return Array.isArray(v) ? v.map(String) : [];
  } catch {
    return [];
  }
}

export interface Hooks {
  /** 一个任务的执行单元全干完了。判它成没成是别人的事，内核只报告「跑完了」。 */
  /** 这道题收工了。`expired` 有值 = 是被时限逼停的，不是自己走完的。 */
  onDone?(task: string, expired?: string): void | Promise<void>;
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
  /** Only deduplicate live finalization calls; the pending work itself remains in task.result. */
  #finalizing = new Set<string>();

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
      this.#resumeFinalization();
      const rows = this.#scan();
      this.#reap(rows);
      for (const p of this.#ready(rows)) void this.#advance(p);
      this.#arm(rows);
    } catch (e) {
      this.#log.error(`kernel tick did not finish: ${msg(e)}`);
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
      // **打完分的题，它的行就不该再被挑走。**
      //
      // 判死那一段的原话是「先落一个失败，让它别再被排上」—— 可这儿以前只问
      // 「这一行做完没有」，从不问「这道题还在不在」。于是超时收工之后，那道题
      // 底下没做完的行照样被扫出来、照样派给模型：实测一跑有 15 道题在死后又开了
      // 105 个执行单元，最狠的一道死后还跑了 33 分钟。花的是真钱，换回来的东西
      // 一分不进成绩单 —— 分是判死那一刻定的。
      //
      // 顺带堵掉一串报错：死掉那一刻在飞的调用回来之后，会在上下文尾巴上留一条
      // 没人应答的工具调用，而收工时的补齐早跑完了。再往下派，模型那边就拒收整份
      // 上下文（`An assistant message with 'tool_calls' must be followed by...`）。
      // 不派了，这条路自然就没了。
      //
      // 写成 `not in` 而不是跟 `task` 内联：主表里没有对应行的孤儿行，行为跟以前
      // 一模一样。内联的话它们会被悄悄丢掉，而「悄悄」是这儿最不该有的东西。
      const rows = all(
        this.#store.ro,
        `select task, cycle, unit, from_cycle, from_unit, agent, instance, place, at
           from "${sub}"
          where done = 0
            and task not in (select id from task where state in ('done', 'failed'))`,
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
  #handleOf(p: Pending): { handle: string; api: { key_env: string; model: string; base_url: string; retry_on: string; compress_at: number | null } | null } {
    const agent = one(this.#store.ro, `select unit, apis from agent where name = ?`, [p.agent]);
    if (!agent) throw new Error(`no row in agent for ${p.agent}`);

    const cyc = one(this.#store.ro, `select api_mode from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    const want = String(cyc?.api_mode ?? "").trim();
    if (!want) return { handle: String(agent.unit), api: null };

    let apis: [string, string][];
    try {
      apis = JSON.parse(String(agent.apis ?? "[]")) as [string, string][];
    } catch {
      throw new Error(`agent ${p.agent} has apis that is not a readable list`);
    }
    for (const [keyEnv, model] of apis) {
      const row = one(this.#store.ro, `select key_env, model, handle, modes, base_url, retry_on, compress_at from api where key_env = ? and model = ?`, [
        keyEnv,
        model,
      ]);
      if (!row) continue;
      const modes = String(row.modes ?? "")
        .split(",")
        .map((x) => x.trim());
      if (modes.includes(want)) {
        return {
          handle: String(row.handle),
          api: {
            key_env: keyEnv,
            model,
            base_url: String(row.base_url),
            retry_on: String(row.retry_on),
            // 空 = 从不压。**是这一行自己的天花板** —— 换把钥匙换个模型就是另一个数。
            compress_at: row.compress_at === null || row.compress_at === undefined ? null : Number(row.compress_at),
          },
        };
      }
    }
    throw new Error(`${p.mode}/${p.cycle} needs a ${want} lane, but none of agent ${p.agent} apis supports it`);
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
        this.#log.error(`${p.sub} ${p.task} ${p.cycle}#${p.unit} cannot run: ${msg(e)}`);
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
      `select id, created_at, solve_seconds, state from task where state not in ('done','failed')`,
    ) as { id: string; created_at: number; solve_seconds: number; state: string }[]) {
      if (now - Number(t.created_at) <= Number(t.solve_seconds) * 1000) continue;
      const key = `task expired\u0000${t.id}`;
      if (this.#cried.has(key)) continue;
      // **一道题出岔子不该带走整轮扫描。** 这个循环还要接着看别的任务和别的
      // 执行单元；这儿抛出去的话，后面那些一个都轮不到 —— 而且下一圈还会从头
      // 再抛一次，等于一道坏题把判死这件事整个停掉。
      this.#log.warn(`task ${t.id} expired: ran ${Math.round((now - Number(t.created_at)) / 1000)}s, limit ${t.solve_seconds}s`);
      const closing = JSON.stringify({ pass: 0, valid: false, outcome: "task_timeout", why: `over solve_seconds=${t.solve_seconds}s` });
      try {
        // 先落一个失败，让它别再被排上；有 G 的话下面那一声会按判决改写。
        run(this.#store.rw, `update task set state = 'failed', result = ? where id = ?`, [
          closing,
          t.id,
        ]);
        // **超时也要问 G。** 以前这条路直接写 failed 就完了，于是「时限内交对了、
        // 只是树没来得及收尾」跟「什么都没做出来」在成绩单上长得一模一样。
        this.#finalize(t.id, `over solve_seconds=${t.solve_seconds}s`, closing);
        this.#cried.add(key);
      } catch (e) {
        this.#cried.delete(key);
        this.#log.error(`task ${t.id} expired but could not be closed: ${msg(e)}`);
      }
    }
    for (const r of rows) {
      const cap = this.#expectSafe(r);
      if (cap === null || now - r.at <= cap) continue;

      // **判死得真的把这一行关掉，不能只打一条日志。**
      //
      // 只打日志的话它永远留在「待办」里：定时器算出「deadline 早就过了」，
      // 于是 50ms 后醒、再打一条、再排 50ms —— 一条卡住的行能把内核锁进空转。
      // 实测一跑打了 12732 条同样的警告，而那道题始终收不了尾。
      //
      // 关的方式跟正常走完那一路一样（`#infer` 结尾那两行）：盖上终止状态、
      // 两边的 done 一起落，然后**另起一个节点**：「这一次调用没回来」跟「这道题
      // 做不出来」是两回事，前者该重来 —— 就像交卷判 0 之后重来一样。
      this.#log.warn(
        `declared dead: ${r.sub} ${r.task} ${r.cycle}#${r.unit} (${r.agent}/${r.instance}) has been ${now - r.at}ms, over ${cap}ms`,
      );
      run(
        this.#store.rw,
        `update "${r.sub}" set done = 1, status = 'dead_failed' where task = ? and cycle = ? and unit = ?`,
        [r.task, r.cycle, r.unit],
      );
      run(this.#store.rw, `update "${tableNameOf("agent_{}_ctx", r.agent)}" set done = 1 where instance = ? and unit = ?`, [
        r.instance,
        r.unit,
      ]);
      // 上下文里也留一句 —— 只进日志的话，从接口上看这一行就是「不知为何没了」。
      try {
        deliver(this.#store.rw, {
          agent: r.agent,
          instance: r.instance,
          unit: r.unit,
          by: "kernel",
          body: JSON.stringify({ stuck: `over expect_ms (${cap}ms), the kernel closed this station` }),
        });
      } catch {
        // 连这一行都落不进去（多半是子表还没长出来），那就只剩日志了
      }
      this.#reopen(r);
      this.#restate(r.task, r.sub);
    }
  }

  /**
   * 一站到点也没回话 —— **判死这个节点，另起一个。**
   *
   * 以前到这儿就没了：这一行标成死的，链路断在这里，任务跟着收工。可「这一次调用
   * 没回来」跟「这道题做不出来」是两回事 —— 前者该重来，就像交卷判 0 之后重来一样。
   * 实测一次抖动就能让一道题颗粒无收，而它连第二次机会都没有。
   *
   * 新的一格接在死掉那一行后面，落在**入口站**上（`from` 是空的那个）：一次全新的
   * 尝试从想事情开始，而不是从跑工具开始。节点号自己会往前走一格 —— 规矩是
   * 「父行有终态就换节点」，而我们刚给它落了 `dead_failed`。
   *
   * **重来的次数由 `max_dead_siblings` 管**，跟交卷判死那条路共用同一个闸：不然一台
   * 抖得厉害的机器会让一道题无限重开，把时限全耗在重来上。
   */
  #reopen(r: Pending): void {
    const entry = all(this.#store.ro, `select cycle from cycle where mode = ? and "from" = '[]'`, [r.mode]) as {
      cycle: string;
    }[];
    const to = entry[0]?.cycle;
    if (!to) return; // 这个机制没有入口站的说法，那就没得重开

    const task = one(this.#store.ro, `select max_dead_siblings from task where id = ?`, [r.task]) as
      | { max_dead_siblings?: number }
      | undefined;
    const cap = Number(task?.max_dead_siblings ?? 3);
    const dead = all(
      this.#store.ro,
      `select distinct node from "${r.sub}" where task = ? and status is not null and status like 'dead%'`,
      [r.task],
    ).length;
    if (dead >= cap) {
      this.#log.warn(`${r.task}: ${String(dead)} attempts have died, at the limit of ${String(cap)} - not reopening`);
      return;
    }

    const node =
      Number(one(this.#store.ro, `select coalesce(max(node), 0) as m from "${r.sub}" where task = ?`, [r.task])!.m) + 1;
    const unit =
      Number(one(this.#store.ro, `select coalesce(max(unit), 0) as m from "${r.sub}" where task = ?`, [r.task])!.m) + 1;
    run(
      this.#store.rw,
      `insert into "${r.sub}" (task, cycle, unit, node, from_cycle, from_unit, agent, instance, place, at, done)
       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
      [r.task, to, unit, node, r.cycle, r.unit, r.agent, r.instance, r.place, Date.now()],
    );
    run(this.#store.rw, `insert into "${tableNameOf("agent_{}_ctx", r.agent)}" (instance, task, unit, place, done) values (?, ?, ?, ?, 0)`, [
      r.instance,
      r.task,
      unit,
      r.place,
    ]);
    this.#log.warn(`${r.task}: ${r.cycle}#${r.unit} never answered - opening attempt ${String(node)} at ${to}#${String(unit)}`);
  }

  /**
   * 三档里挑「还没开始」的那一档 —— **出站那一行还没落库**。
   *
   * 判据是内核那条出站行，不是「一条消息都没有」：一个单元可以预先压好要问的话
   * （那是数据，谁都能往库里放），有话不等于出站过。按「有没有消息」判的话，
   * 预置了 prompt 的单元会被当成正在跑，永远轮不到它。
   */
  #ready(rows: Pending[]): Pending[] {
    return rows.filter((r) => !this.#sentOut(r));
  }

  /**
   * 这个单元出站过没有。
   *
   * **光看 `kind = 'inject'` 不行。** `inject` 是两样东西共用的一个值：内核那条出站
   * 记账（`by: "kernel"` → role=system），和系统注入的用户侧消息（`by: "world"` →
   * role=user）。而**非真人发的任务，描述那一条正是后者** —— `source` 不是 `user`
   * 的时候发布口用 `by: "world"` 投它。于是任务一建出来就带着一条 `inject`，这一站
   * 被当成「已经出站了」，内核再也不碰它：`agent` / `world` / `eacn` 三种来源的任务
   * 全部躺在库里不动，不报错，只是永远轮不到。
   *
   * 所以判据要连 `role` 一起看 —— `inject` + `system` 只有内核那条出站行是。
   */
  #sentOut(r: Pending): boolean {
    const t = this.#msgTable(r.agent);
    const got = one(
      this.#store.ro,
      `select count(*) as c from "${t}" where instance = ? and unit = ? and kind = 'inject' and role = 'system'`,
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
    if (["done", "failed"].includes(String(one(this.#store.ro, "select state from task where id = ?", [p.task])?.state))) return;
    // **先占位，再干活。**「这一行已经派出去了」这件事必须在**任何 await 之前**
    // 就写进库 —— 挑活的人（`#ready`）看的就是这一行。
    //
    // 不占位的话窗口是这么开的：这一圈挑中它、`void` 掉不等；`#advance` 走到第一个
    // await 让出控制权，标记还没写；这中间任何一次写库都会 `wake()`，下一圈醒来去库里
    // 一看「没派过」，于是**又派一次**。同一格里就有了两条模型应答 —— 两条挨着的
    // 「我要调工具」中间没有结果，模型那边当场拒收整份上下文，这道题从此发不出去，
    // 只能空转到超时。实测五百多格里中了四格，每中一格废一道题。
    //
    // `#ticking` 挡不住这个：它挡的是「两圈同时跑」，而这里是「上一圈的活还在飞」——
    // 活是 `void` 掉的，一开始就不在那个开关的管辖里。
    const mark = deliver(this.#store.rw, {
      agent: p.agent,
      instance: p.instance,
      unit: p.unit,
      by: "kernel",
      // **带上预计到点。** 这一行是「已经派出去了」的凭据，那它也该说清楚等到什么
      // 时候算等不到 —— 到点还没回话，内核就判这一站死、另起一个节点（见 `#reap`）。
      body: JSON.stringify({ sent: true, deadline: Date.now() + (this.#expectSafe(p) ?? 0) }),
    });

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

      // 出站那份：**沿着链路把上下文拼齐** + 这一轮的家当。**先落库，再发**
      const context = this.#contextOf(p);
      // 出站这一行是**快照里那次调用的凭据**：模型当时被告知有哪些工具、
      // 每个工具的用法约定是什么。不记的话，回头看这一步就说不清它为什么那么做。
      // 占位那一行现在补全 —— 它是**快照里那次调用的凭据**：模型当时被告知有哪些
      // 工具、每个工具的用法约定是什么。不记的话，回头看这一步就说不清它为什么那么做。
      //
      // 补的是同一行，不是再落一行：那一行的身份（`kind` / `role` / `seq`）是投递管道
      // 定的，这儿只把内容填进去。
      //
      // 键名一律 ASCII：这一行**客户端读得到**（`/tasks/:id/messages` 会把它解开），
      // 中文键名等于逼着客户端写 `data["出站"]`，而且每过一层编码都可能烂。
      run(
        this.#store.rw,
        `update "${this.#msgTable(p.agent)}" set body = ? where instance = ? and unit = ? and seq = ?`,
        [
          JSON.stringify({
            sent: true,
            tools: kit.map((t) => t.name),
            prompts: kit.map((t) => t.prompt).filter(Boolean),
            rules,
          }),
          p.instance,
          p.unit,
          mark,
        ],
      );

      // 出站那一行落了 = 这一站真的动起来了，主表那个大状态这时候就该是 `claimed`。
      // 只在一步走完之后才推的话，模型这一次调用有多慢，`state` 就有多久还写着
      // `open`（待领取）—— 客户端照着它轮询，看到的是「没人接」，而它其实正在跑。
      this.#restate(p.task, p.sub);

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
        // 哪种 role 去消息流、哪种去交代 —— **表说了算**，适配器不再自己留一份。
        sentAs: sentAsIn(this.#store.ro),
        // 这一站非调不可的那个工具（`cycle.must_call`）。空 = 它自己挑。
        mustCall: String(facts.cycle.must_call ?? "") || null,
        // 这一轮的任务视图。**每轮现算**，不是库里存着的一条消息 ——
        // 存成消息的话，兄弟分支爬不到它（见 `#viewOf`）。
        view: this.#viewOf(p, facts.task),
        tools: kit,
        rules,
      });

      // 回来再落一行
      // 模型自己说的那条**不走投递管道** —— 那是它自己的轨迹，直接落库；
      // 而且 kind 得由适配器说（prompt 还是 call），推不出来。
      const r = (back ?? {}) as { role?: string; kind?: string; body?: unknown } & Partial<Said>;
      this.#push(p, r.role ?? "assistant", r.kind ?? "prompt", text(r.body ?? back), r);

      // A late HTTP/model response may be recorded, but cannot reopen a closed task or unit.
      const taskState = String(one(this.#store.ro, "select state from task where id = ?", [p.task])?.state);
      const unitDone = Number(one(this.#store.ro, `select done from "${p.sub}" where task = ? and unit = ?`, [p.task, p.unit])?.done) === 1;
      if (["done", "failed"].includes(taskState) || unitDone) {
        run(this.#store.rw, `update "${p.sub}" set done = 1 where task = ? and unit = ?`, [p.task, p.unit]);
        run(this.#store.rw, `update "${tableNameOf("agent_{}_ctx", p.agent)}" set done = 1 where instance = ? and unit = ?`, [p.instance, p.unit]);
        this.#answerAll(p.task, p.sub);
        this.wake();
        return;
      }

      // Tool units can receive an account fault from a nested searcher even though their own handle succeeds.
      for (const receipt of all(this.#store.ro, `select body from "${this.#msgTable(p.agent)}" where instance = ? and unit = ? and kind = 'tool'`, [p.instance, p.unit])) {
        let value: { valid?: unknown; outcome?: unknown; httpStatus?: unknown; error?: unknown } | undefined;
        try { value = (JSON.parse(String(receipt.body)) as { value?: typeof value }).value; } catch { continue; }
        const status = Number(value?.httpStatus);
        if (value?.valid === false && value.outcome === "provider_error" && [401, 402, 403].includes(status)) {
          this.#providerFault(p, status, String(value.error ?? "provider refused the nested request"));
          return;
        }
      }

      await this.#atMoment(p, facts, "post_send");
      await this.#infer(p, facts, back);
      // 成功推完才醒下一圈。**失败不醒** —— 醒了就是原地热循环：
      // 这一行还是「该动」的那一档，下一圈又挑到它，再失败，再醒。
      // 失败的那条留给下面那个 deadline 定时器，超时了按判死处理。
      this.wake();
    } catch (e) {
      const why = msg(e);
      const serviceError = e as { statusCode?: unknown; cause?: { statusCode?: unknown }; lastError?: { statusCode?: unknown } };
      const httpStatus = Number(serviceError?.statusCode ?? serviceError?.cause?.statusCode ?? serviceError?.lastError?.statusCode);
      if ([401, 402, 403].includes(httpStatus)) {
        this.#providerFault(p, httpStatus, why);
        return;
      }
      this.#log.error(`${p.sub} ${p.task} ${p.cycle}#${p.unit} is stuck: ${why}`);
      // **也落进库。** 只进日志的话，从接口上看这一行就是「不知为何不动」——
      // 而客户端手里只有接口。日志在服务器上，看日志的人和被卡住的人不是同一个。
      //
      // 同一行的同一句只落一次：走不下去的行多半每一圈都会再试一次，
      // 每次都落的话，一个配错的任务能把上下文表撑满。
      const key = `stuck ${p.sub} ${p.task} ${p.cycle} ${p.unit} ${why}`;
      if (!this.#cried.has(key)) {
        this.#cried.add(key);
        try {
          deliver(this.#store.rw, {
            agent: p.agent,
            instance: p.instance,
            unit: p.unit,
            by: "kernel",
            body: JSON.stringify({ stuck: why }),
          });
        } catch {
          // 连这一行都落不进去（多半是子表还没长出来），那就只剩日志了
        }
      }
    }
  }

  #providerFault(p: Pending, httpStatus: number, why: string): void {
    run(this.#store.rw, `update task set state = 'failed', result = ? where id = ?`, [JSON.stringify({ pass: 0, valid: false, outcome: "provider_error", httpStatus, why }), p.task]);
    run(this.#store.rw, `update "${p.sub}" set done = 1, status = 'dead_service' where task = ? and done = 0`, [p.task]);
    run(this.#store.rw, `update "${tableNameOf("agent_{}_ctx", p.agent)}" set done = 1 where instance = ?`, [p.instance]);
    this.#answerAll(p.task, p.sub);
    this.#log.error(`${p.task} stopped after provider ${httpStatus}: ${why}`);
    this.wake();
  }

  #pendingFinalizations(): { id: string; result: string }[] {
    return all(this.#store.ro, `select id,result from task where state in ('done','failed') and json_valid(result) and json_extract(result,'$.outcome') in ('finalization_pending','finalization_error')`) as { id: string; result: string }[];
  }

  #resumeFinalization(): void {
    for (const row of this.#pendingFinalizations()) {
      if (this.#finalizing.has(row.id)) continue;
      const prior = JSON.parse(row.result) as { expired?: string; retryAt?: number };
      if (Number(prior.retryAt ?? 0) > Date.now()) continue;
      this.#finalize(row.id, prior.expired);
    }
  }

  #finalize(task: string, expired?: string, fallback: string | null = null): void {
    if (!this.#hooks.onDone || this.#finalizing.has(task)) return;
    const pending = JSON.stringify({ pass: 0, valid: false, outcome: "finalization_pending", ...(expired ? { expired, why: expired } : {}) });
    run(this.#store.rw, "update task set result = ? where id = ?", [pending, task]);
    this.#finalizing.add(task);
    const finish = () => {
      if (this.#stopped) return; // Persist the marker if shutdown interrupts finalization.
      run(this.#store.rw, "update task set result = ? where id = ? and result = ?", [fallback, task, pending]);
    };
    const fail = (e: unknown) => {
      if (this.#stopped) return;
      const failure = JSON.stringify({ pass: 0, valid: false, outcome: "finalization_error", why: msg(e), retryAt: Date.now() + 1000, ...(expired ? { expired } : {}) });
      run(this.#store.rw, "update task set state = 'failed', result = ? where id = ? and result = ?", [failure, task, pending]);
      this.#log.error(`task ${task} could not be finalized: ${msg(e)}`);
    };
    try {
      const closed = this.#hooks.onDone(task, expired);
      if (closed) {
        void closed.then(finish).catch(fail).finally(() => { this.#finalizing.delete(task); this.wake(); });
      } else {
        finish();
        this.#finalizing.delete(task);
      }
    } catch (e) {
      try { fail(e); } finally { this.#finalizing.delete(task); }
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
        this.#log.error(`rule ${identity} threw at moment ${moment}: ${msg(e)}`);
      }
    }
  }

  /**
   * 这一站看得见的上下文：**从根一路到自己那一串执行单元的消息，按顺序接起来。**
   *
   * 不是只看自己那一格。只看自己的话，第二个执行单元开口时手上什么都没有 ——
   * 原来的问题、上一站请求的工具、工具跑出来的结果，一样都看不到，于是它对着
   * 空气说话。整棵树的多站流程都建立在这条上。
   *
   * 走的是 `from_unit` 指针，跟链路串同一条血缘：
   *
   * - **看得见祖先，看不见兄弟。** 开兄弟正是为了换一条路走，让它看见另一条
   *   分支上的话，等于把两次尝试搅在一起
   * - 带环的话当场炸 —— 顺着 from 走回自己，那是数据坏了，静静转下去只会挂死
   */
  /**
   * 这一轮的**任务视图**：这道题是什么、我在树的哪儿、别的路试过没有。
   *
   * ## 为什么必须有这么一份
   *
   * 上下文是**沿着单链往上爬**拼的（祖先看得见，兄弟看不见 —— 那是故意的）。
   * 而任务描述是发布那一刻**当成一条消息**投给第一站的。两条合起来的后果：
   * 判死之后在根上开的兄弟**没有祖先**，于是它看不到题目 —— 上下文里只剩这一站
   * 自己的 skill 和记账。实测就是这样：模型拿着一段方法注入，回了句「我已理解
   * 这个通用方法」，然后开始反问「请把本题的具体选项发出来」。它是真没看见题。
   *
   * 根子在于**任务的事实被当成了某一站的一条消息**。事实该是每一轮现算的一份视图，
   * 跟成绩单一样「数出来的，不是存着的」—— 存成消息就会跟着链路走丢。
   *
   * ## 只给事实，不替它拼话
   *
   * 这儿回的是结构化的一份，怎么念给模型听是适配器的事（`llm/index.ts`）。
   * 内核不认得「提示词」长什么样。
   *
   * ## 树只给梗概
   *
   * 别的分支**默认不接入**（老仓库那条：「进度共享是能看、不是直接继承」）。
   * 所以这儿只报「试过哪几条、死没死」，要看详情、要把别人的上下文接进来，
   * 那是工具的事。
   */
  #viewOf(p: Pending, task: Row): Row {
    const rows = all(
      this.#store.ro,
      `select cycle, unit, node, status, done from "${p.sub}" where task = ? order by unit`,
      [p.task],
    ) as { cycle: string; unit: number; node: number; status: string | null; done: number }[];

    // **按节点报，不按行。** `task_tree` / `node_load` 说的都是节点，视图却报行号的话，
    // 模型会把行号当节点号喂给 `node_load` —— 实测就这么白花过一次调用
    // （`node_load(8)` 拿到 "there is no such node in this task"）。
    const byNode = new Map<number, typeof rows>();
    for (const r of rows) {
      const k = Number(r.node);
      const got = byNode.get(k) ?? [];
      got.push(r);
      byNode.set(k, got);
    }
    return {
      task: {
        id: task.id,
        description: task.description,
        domain: task.domain,
        source: task.source,
        place: task.place,
        workdir: task.workdir,
        objective: task.objective !== null,
      },
      // **你在哪一站、这一站之后还有没有下一站。** 都是流转表上的事实。
      //
      // 不给的话，模型不知道自己站在终点站上 —— 实测它在交卷站上调了 `bash`，
      // 那一站之后没有跑工具的站，于是那次调用永远不会被执行，而它也就没说出
      // 任何一句能交的话。它不是不听话，是**看不见自己在哪儿**。
      here: {
        cycle: p.cycle,
        unit: p.unit,
        chain: chainOf(this.#store.ro, p.sub, p.mode, p),
        next: nextOf(this.#store.ro, p.mode, p.cycle),
      },
      budget: this.#budgetOf(p, task),
      tried: [...byNode.entries()]
        .sort((x, y) => x[0] - y[0])
        .map(([node, g]) => ({
          node,
          at: g.map((r) => `${r.cycle}#${r.unit}`).join(" > "),
          status: g[g.length - 1].status,
          done: g.every((r) => Number(r.done) === 1),
          mine: g.some((r) => Number(r.unit) === p.unit),
        })),
    };
  }

  /**
   * **还剩多少额度。** 摆进视图里，不让它自己猜。
   *
   * 以前不给，后果是实测出来的：模型把额度全花在探环境上（`cmt-0`：12 个执行
   * 单元查了一圈 python/node，一个字答案都没写），到收尾那一刻手上什么都没有。
   * 它不是不会安排，是**看不见还剩多少**。
   *
   * **只报事实，不报口径。** 每一站用了几个、还剩几个、还剩多少秒 —— 这些是内核
   * 手上的账。至于「该在哪一站交卷、交卷用哪个工具」，那是**声明层**说的事：
   * 流转表上摆着有哪几站，skill / 任务描述里写着规矩。内核往上下文里塞策略文案
   * 就是越位 —— 换一套模式那段话就成了谎话，而且没人改得着它。
   */
  #budgetOf(p: Pending, task: Row): Row {
    const caps = all(this.#store.ro, `select cycle, max_units from cycle where mode = ?`, [p.mode]) as {
      cycle: string;
      max_units: number;
    }[];
    const used = new Map(
      (
        // 报的是**这一个节点**的额度 —— 那才是它现在花得起多少。
        all(
          this.#store.ro,
          `select cycle, count(*) as n from "${p.sub}"
            where task = ? and node = (select node from "${p.sub}" where task = ? and cycle = ? and unit = ?)
            group by cycle`,
          [p.task, p.task, p.cycle, p.unit],
        ) as { cycle: string; n: number }[]
      ).map((r) => [r.cycle, Number(r.n)]),
    );
    const left = Math.max(
      0,
      Math.round(Number(task.solve_seconds ?? 0) - (Date.now() - Number(task.created_at ?? Date.now())) / 1000),
    );
    const hasG = task.objective !== null;
    const handed =
      hasG &&
      all(this.#store.ro, `select unit from "${p.sub}" where task = ? and cycle = ? limit 1`, [p.task, SUBMIT])
        .length > 0;
    return {
      units: caps.map((c) => ({
        cycle: c.cycle,
        used: used.get(c.cycle) ?? 0,
        cap: Number(c.max_units),
        left: Math.max(0, Number(c.max_units) - (used.get(c.cycle) ?? 0)),
      })),
      secondsLeft: left,
      ...(hasG ? { submitted: handed } : {}),
    };
  }

  /** 这一份要发出去的东西有多大，按 token 估。**内核没有分词器**，数字节再除 4 —— 量过一道题：4234989 字节对模型报的 1033906 token。 */
  #tokensOf(rows: Row[]): number {
    let n = 0;
    for (const r of rows) {
      n += Buffer.byteLength(String(r.body ?? ""), "utf8") + Buffer.byteLength(String(r.thought ?? ""), "utf8");
    }
    return Math.round(n / 4);
  }

  /**
   * 把**已经收口的那些节点**换成它们压过的那一份。当前节点原样不动 —— 它的话正被用着。
   *
   * 按**节点**换，不按格换：一次调用和它的结果可能落在相邻两格上，只换其中一格的话，
   * 上下文里会留下一个没有调用的结果，而模型那边直接拒收整份。
   *
   * 没压过的节点（`press` 是空的）照原文发。压是收口那一刻做的，做不成不该让这一发
   * 也跟着完蛋。
   */
  /**
   * 按阈值降级，降到装得下为止。**默认一级都不降。**
   *
   * 阈值是 `api.compress_at`（这把钥匙这个模型的天花板），空 = 从不压。装不下就降一级，
   * 还装不下再降 —— 降到**设好了的**最后一级为止（`readyLevels`：`msg_part` 里那一列
   * 每行都填了才算设好。`l4` 现在还空着，所以现在就是三级）。最后一级还超就把它发出去，
   * 让模型那边拒 —— 到那一步已经没有更狠的了，而在这儿假装没事更糟。
   */
  #fit(p: Pending, rows: Row[], line: number[]): Row[] {
    const api = this.#handleOf(p).api;
    const cap = Number(api?.compress_at ?? 0);
    if (!cap || this.#tokensOf(rows) <= cap) return rows;
    let out = rows;
    const levels = readyLevels(this.#store.ro);
    for (const level of levels) {
      out = swapClosed(this.#store.ro, p, rows as unknown as Line[], line, level) as unknown as Row[];
      const now = this.#tokensOf(out);
      if (now <= cap) {
        this.#log.info(`${p.task} ${p.cycle}#${p.unit}: context ${String(this.#tokensOf(rows))} tok > ${String(cap)}, sent at ${level} (${String(now)} tok)`);
        return out;
      }
    }
    this.#log.warn(`${p.task} ${p.cycle}#${p.unit}: still ${String(this.#tokensOf(out))} tok at ${levels.at(-1) ?? "l0"}, over ${String(cap)}`);
    return out;
  }

  #contextOf(p: Pending): Row[] {
    const line: number[] = [];
    const seen = new Set<string>();
    let cur: Unit = p;
    for (;;) {
      const key = `${cur.cycle}#${cur.unit}`;
      if (seen.has(key)) throw new Error(`chain for ${p.task} in ${p.sub} is cyclic, at ${key}`);
      seen.add(key);
      line.unshift(cur.unit);
      if (cur.from_cycle === null || cur.from_unit === null) break;
      const up = one(
        this.#store.ro,
        `select task, cycle, unit, from_cycle, from_unit from "${p.sub}" where task = ? and cycle = ? and unit = ?`,
        [p.task, cur.from_cycle, cur.from_unit],
      ) as unknown as Unit | null;
      if (!up) {
        throw new Error(`${p.sub} ${p.task} ${cur.cycle}#${cur.unit} says it came from ${cur.from_cycle}#${cur.from_unit}, but that row is missing`);
      }
      cur = up;
    }

    const t = this.#msgTable(p.agent);
    const holes = line.map(() => "?").join(", ");
    // 按 unit 的先后、再按 seq 排 —— unit 编号在一个任务里单调递增，所以它就是时间序。
    let rows = all(
      this.#store.ro,
      `select unit, seq, role, kind, body, thought from "${t}"
        where instance = ? and unit in (${holes}) order by unit, seq`,
      [p.instance, ...line],
    );
    // **缺的补上，不摘** —— 但只在这一站不可能是答题的那个人的时候补。
    //
    // 谁答，表里写着：`api_mode` 为空的站调 `agent.unit`，那才是跑工具、写结果的
    // 那个；有 `api_mode` 的站是去问模型的，轮不到它答。给前者拼上下文时工具**还
    // 没开始跑**，那时候的「没人答」是「还没轮到」，不是「永远没有」—— 在那儿补
    // 一条，等它真跑完就成了同一个 id 两条结果，模型那边一样拒收（反过来的那句：
    // `Messages with role 'tool' must be a response to a preceding message with
    // 'tool_calls'`）。实测五道题全卡在第三站上。
    //
    // 剩下的那一笔归收工时那次补齐（见 `#answerAll`）：真到最后还没人答，那才是
    // 永远没人答。
    const cyc = one(this.#store.ro, `select api_mode from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    if (String(cyc?.api_mode ?? "").trim() === "") return rows;

    // **先补齐，再压。** 顺序反过来会出事，撞过：补齐靠 `kind='tool'` 认「这个调用
    // 答过了」，而压过的那份里，收口节点的调用和结果都已经是一段文字 —— 它一个都
    // 认不出来，该补的漏掉。漏掉之后原文里那个悬空的调用还在，一路发到那一端，
    // SDK 本地就拒：`Tool result is missing for tool call …`。八站栽在这儿，全是交卷站。
    const typed = rows as unknown as { unit: number; seq: number; kind: string; body: string }[];
    if (answerMissing(this.#store.rw, p.agent, p.instance, typed) > 0) {
      rows = all(
        this.#store.ro,
        `select unit, seq, role, kind, body, thought from "${t}"
          where instance = ? and unit in (${holes}) order by unit, seq`,
        [p.instance, ...line],
      );
    }
    return this.#mend(p, this.#fit(p, rows, line));
  }

  /**
   * 发出去之前最后看一眼：调用和结果还配得上吗。配不上就摘掉那一小段，**不回退**。
   *
   * 正常情况下这儿什么都不会做 —— 真动了手就说明前面漏了一条结果，所以动手必留一条
   * warn，带上是哪一格哪个调用。悄悄摘掉的话，这个洞下次还在，而表现只是「模型好像
   * 少看见了点什么」。
   */
  #mend(p: Pending, rows: Row[]): Row[] {
    const got = mendPairs(rows as unknown as Pair[]);
    if (got.dropped.length === 0) return rows;
    this.#log.warn(
      `${p.task} ${p.cycle}#${p.unit}: context did not hold together, dropped ${String(got.dropped.length)}: ${got.dropped.slice(0, 3).join("; ")}`,
    );
    return got.rows as unknown as Row[];
  }

  /** 往上下文里压一条。`seq` 在这个单元里连着排。 */
  #push(p: Pending, role: string, kind: string, body: string, said?: Said): void {
    // **这一行也得过同一道校验。** 它绕开 `deliver()` 直接 insert，而形状约束要是
    // 只有一条路上有，另一条路就是坏行漏进来的那个口子。
    checkBody(kind, body);
    const t = this.#msgTable(p.agent);
    const seq = this.#seqMax(p) + 1;
    // 账目跟着这一行走 —— **不另开一张表**：它说的就是这一行是怎么来的，
    // 拆出去就得靠三个键接回来，而接错了没人报错。适配器没报的那几家，
    // 这几列是 null，看得出来是「没报」，不是「零」。
    run(
      this.#store.rw,
      `insert into "${t}" (instance, unit, seq, role, kind, body, at,
                           thought, prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens)
       values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)`,
      [
        p.instance,
        p.unit,
        seq,
        role,
        kind,
        body,
        Date.now(),
        said?.thought || null,
        said?.prompt_tokens ?? null,
        said?.completion_tokens ?? null,
        said?.reasoning_tokens ?? null,
        said?.cached_tokens ?? null,
      ],
    );
  }

  /** 比条件时手上的东西。链路串按 `chain.ts` 那个拼法 —— 那是协议。 */
  #factsOf(p: Pending): Facts {
    const agent = one(this.#store.ro, `select * from agent where name = ?`, [p.agent]);
    const task = one(this.#store.ro, `select * from task where id = ?`, [p.task]);
    const cycle = one(this.#store.ro, `select * from cycle where mode = ? and cycle = ?`, [p.mode, p.cycle]);
    if (!agent) throw new Error(`no row in agent for ${p.agent}`);
    if (!task) throw new Error(`no row in task for ${p.task}`);
    if (!cycle) throw new Error(`no row in cycle for ${p.mode}/${p.cycle}`);
    return { agent, task, cycle, place: p.place, chain: chainOf(this.#store.ro, p.sub, p.mode, p) };
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
    // **终点站也要问。** `next` 为空只说明「没有下一站可去」，不说明「不用问这一站
    // 算成了没有」—— 终止状态（reached / dead_*）正是推断函数说的那一栏。
    // 以前这儿短路成 null，于是任何终点站的 status 永远是空：树上看不出它是走到了
    // 还是被判死了。交卷站就是终点站，短路的话它那一次判决根本不会发生。
    const picked = await this.#reg
      .get(String(cyc.infer))
      .call({ ...facts, next, result, sub: p.sub, unit: p.unit });
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
    // **节点收口了，就把它压好。** 收口 = 这一站拿到了终止状态（`status` 非空）。
    // 压的是已经出完的那个节点：还在出的节点不压，它的话正被用着。
    //
    // 压不成不该带走这一站 —— 那一站是真做完了。压不成的表现是这个节点的 `press`
    // 还是空的，而拼上下文那边见到空的就照原文发（见 `#contextOf`）。
    if (status !== null) {
      const node = one(this.#store.ro, `select node from "${p.sub}" where task = ? and cycle = ? and unit = ?`, [
        p.task,
        p.cycle,
        p.unit,
      ]);
      if (node) {
        try {
          const n = await pressNode(this.#store.rw, this.#reg, {
            sub: p.sub,
            task: p.task,
            node: Number(node.node),
            agent: p.agent,
            instance: p.instance,
          });
          if (n > 0) this.#log.info(`${p.task} node ${String(node.node)}: pressed ${String(n)} unit(s)`);
        } catch (e) {
          this.#log.warn(`${p.task} node ${String(node.node)}: could not be pressed: ${msg(e)}`);
        }
      }
    }
    const ctx = tableNameOf("agent_{}_ctx", p.agent);
    run(this.#store.rw, `update "${ctx}" set done = 1 where instance = ? and unit = ?`, [p.instance, p.unit]);

    if (to !== null) {
      // **`next` 白名单只管「往下走」那一种。**
      //
      // 开兄弟和回退回的是第三种形状（带 `from_cycle`：接到指定那一行上），它们的
      // `to` 是**当前这个周期**（兄弟）或**祖先的周期**（回退）—— 本来就不在
      // `next` 里。一律拿 next 卡的话，判死之后一个兄弟都开不出来：
      // 「fn:infer.dfs 推出来的 ask 不在候选里（候选是 act）」。
      //
      // 这条以前撞不上，是因为模型每一站都先请求工具，`ask` 那站从不算「到终点」，
      // 也就从来没judge过、没判死过。换个直接给答案的模型就炸。
      //
      // 不查白名单不等于不查：下面那句 `no row in cycle for ${p.mode}/${to}` 仍然拦着
      // 推断函数瞎编一个周期名出来。
      if (!saidFrom && !next.includes(to)) {
        throw new Error(`${cyc.infer} returned ${to}, which is not among the candidates (${next.join(", ")})`);
      }
      // **这一行属于哪个节点。**
      //
      // 一个节点是一次完整的尝试：好几个执行单元拼起来，由拿到终止状态的那一行
      // 收口（`status` 非空 = reached / dead_*，出生即定不回改）。所以：
      //
      //   父亲还没收口 → 跟父亲同一个节点
      //   父亲收口了   → 从这一行起是下一个节点
      //
      // **记下来，不要每次去推。** 推的话得走一遍父链，还得知道「哪一个周期收口
      // 一个节点」—— 那件事一旦写进代码，换套机制就全读错，而且不报错。
      const parent =
        fromCycle === null || fromUnit === null
          ? undefined
          : (one(this.#store.ro, `select node, status from "${p.sub}" where task = ? and cycle = ? and unit = ?`, [
              p.task,
              fromCycle,
              fromUnit,
            ]) as { node?: number; status?: string | null } | undefined);
      const node = parent === undefined ? 1 : Number(parent.node ?? 1) + (parent.status == null ? 0 : 1);

      const cap = one(this.#store.ro, `select max_units from cycle where mode = ? and cycle = ?`, [p.mode, to]);
      if (!cap) throw new Error(`no row in cycle for ${p.mode}/${to}`);

      // **额度在【这一个节点】里数，不是整道题。**
      //
      // 一个节点是一次完整的尝试，它自己有一份预算：花完了就该交卷，交完判死就换
      // 下一个节点，那个节点又有自己的一份。按整道题数的话，第一个节点就把预算吃
      // 光了 —— 于是一道题只可能有一次提交，「判死 → 换条路」永远跑不起来。
      //
      // 「一道题能试几个节点」是另一根轴，由 `max_dead_siblings` 和 `solve_seconds` 管。
      const used = Number(
        one(this.#store.ro, `select count(*) as c from "${p.sub}" where task = ? and cycle = ? and node = ?`, [
          p.task,
          to,
          node,
        ])!.c,
      );
      if (used >= Number(cap.max_units)) {
        this.#log.warn(
          `${p.task}: ${p.mode}/${to} has used all ${cap.max_units} units of node ${node}, not opening more`,
        );
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
          `insert into "${p.sub}" (task, cycle, unit, node, from_cycle, from_unit, agent, instance, place, at, done)
           values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)`,
          [p.task, to, unit, node, fromCycle, fromUnit, p.agent, p.instance, p.place, Date.now()],
        );
        // 智能体那边同一件事的另一半，跟着开 —— 两边要能对咬
        run(
          this.#store.rw,
          `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, ?, ?, 0)`,
          [p.instance, p.task, unit, p.place],
        );
      }
    }

    // 这一下把任务推到「全干完了」→ 喊 `task_done` 那一刻。
    //
    // **`MOMENTS` 里列了它，就必须真喊。** 列着不喊的话，挂在这一刻上的规则永远
    // 不跑，而 `check` 看不出问题（条件合法）、日志上也没有一个字 —— 正是这台机器
    // 最不该有的那种失败。
    if (this.#restate(p.task, p.sub)) await this.#atMoment(p, facts, "task_done");
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
   *
   * 回「这一下是不是刚好推到了 `done`」—— 上面那层据它喊 `task_done` 那一刻。
   * 由这儿说而不是让上面自己再数一遍：数两遍就会漂，而漂了的表现是那一刻
   * 要么不喊、要么喊两回。
   */
  /**
   * 这道题所有实例里没人答的调用，一次补完。
   *
   * 一个任务可能有好几个实例（每个智能体一份上下文），所以先问执行单元表都有谁。
   */
  #answerAll(task: string, sub: string): void {
    const who = all(this.#store.ro, `select distinct agent, instance from "${sub}" where task = ?`, [task]) as {
      agent: string;
      instance: string;
    }[];
    for (const w of who) {
      try {
        const t = this.#msgTable(w.agent);
        const rows = all(
          this.#store.ro,
          `select unit, seq, kind, body from "${t}" where instance = ? order by unit, seq`,
          [w.instance],
        ) as unknown as { unit: number; seq: number; kind: string; body: string }[];
        const put = answerMissing(this.#store.rw, w.agent, w.instance, rows);
        if (put > 0) this.#log.info(`${w.instance}: answered ${put} call(s) that nobody ever ran`);
      } catch (e) {
        // 补不上不该拦着任务收工 —— 那只是这张表少了几行，不是这道题没做完。
        this.#log.warn(`${w.instance}: could not answer the calls left open: ${msg(e)}`);
      }
    }
  }
  #restate(task: string, sub: string): boolean {
    const got = one(this.#store.ro, `select count(*) as n, coalesce(sum(done), 0) as d from "${sub}" where task = ?`, [
      task,
    ])!;
    const n = Number(got.n);
    const d = Number(got.d);
    const now = one(this.#store.ro, `select state from task where id = ?`, [task]);
    const was = String(now?.state ?? "");
    if (was === "failed") return false; // 判过失败的不许被数回去
    const next = n === 0 ? "open" : d === n ? "done" : "claimed";
    run(this.#store.rw, `update task set state = ? where id = ?`, [next, task]);
    const justDone = next === "done" && was !== "done";
    // **收工前把没人答的调用补齐。** 补齐平时是在拼上下文那一刻做的，可最后一站
    // 之后再没有人来读上下文了 —— 那一站要是请求了工具而没人跑，那笔账就永远
    // 挂在表里，这张表也就当不成一份完整的快照。
    if (justDone) this.#answerAll(task, sub);
    // 跑完了喊一声。**内核不知道那边会干什么** —— 判成没成不是它的事。
    if (justDone) {
      this.#finalize(task);
    }
    return justDone;
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
    if (this.#stopped) return;
    const now = Date.now();

    // 执行单元那一层：这一步卡住了没有。
    const deadlines = rows
      .map((r) => {
        const cap = this.#expectSafe(r);
        return cap === null ? null : r.at + cap;
      })
      .filter((d): d is number => d !== null);

    // **任务那一层也得算进来。** 只按执行单元的 deadline 设表的话，一道题可以
    // 无限期超过它自己的 `solve_seconds`：两边的时限差着量级（一步 15 分钟、
    // 整道题 5 分钟），而没有新写入就没有别的信号能把内核叫醒。
    //
    // 实测：两道 `solve_seconds=300` 的题跑到 1306 秒还挂在 claimed —— 它们
    // 卡在长模型调用里，没人写库，于是没人去看它们超没超时。
    for (const t of all(
      this.#store.ro,
      `select created_at, solve_seconds from task where state not in ('done','failed')`,
    ) as { created_at: number; solve_seconds: number }[]) {
      deadlines.push(Number(t.created_at) + Number(t.solve_seconds) * 1000);
    }
    for (const row of this.#pendingFinalizations()) {
      if (!this.#finalizing.has(row.id)) deadlines.push(Number((JSON.parse(row.result) as { retryAt?: number }).retryAt ?? now));
    }

    if (deadlines.length === 0) return;
    const soonest = Math.min(...deadlines);
    this.#timer = setTimeout(() => this.wake(), Math.max(soonest - now, 50));
    this.#timer.unref?.();
  }
}

function text(v: unknown): string {
  return typeof v === "string" ? v : JSON.stringify(v ?? null);
}

/**
 * 一个错误变成一行话。**连 `cause` 一起说。**
 *
 * 只打最外面那一句是不够的，撞过：AI SDK 收到 200 之后把返回体映射成自己的结构，
 * 那一步失败就包一句 `Failed to process successful response`，**真正的原因挂在
 * `cause` 上**（`@ai-sdk/provider-utils` 的 `postToApi`）。日志里只有外面那句的话，
 * 「body 收到一半断了」「某个字段的形状对不上」「回了个空壳」这三种分不开 ——
 * 而分不开就查不下去，一整趟只留下十几条一模一样的话。
 *
 * 顺带把那一端说了什么也带上（`statusCode` / `responseBody`）：400 的时候那句话
 * 就是答案本身（`Thinking mode does not support this tool_choice` 就是这么找到的）。
 */
export function msg(e: unknown): string {
  const out: string[] = [];
  let cur: unknown = e;
  for (let i = 0; cur && i < 5; i++) {
    const x = cur as { message?: unknown; name?: unknown; statusCode?: unknown; responseBody?: unknown; cause?: unknown };
    const one = typeof x.message === "string" ? x.message : String(cur);
    const extra: string[] = [];
    if (x.statusCode) extra.push(`status ${String(x.statusCode)}`);
    if (typeof x.responseBody === "string" && x.responseBody) extra.push(`body ${x.responseBody.slice(0, 300)}`);
    out.push(one + (extra.length ? ` (${extra.join(", ")})` : ""));
    cur = x.cause;
    // 同一句重复挂两层的时候不重复说 —— 有的包装层原样透传 message。
    if (typeof (cur as { message?: unknown } | null)?.message === "string" && (cur as { message: string }).message === one) {
      cur = (cur as { cause?: unknown }).cause;
    }
  }
  return out.join(" <- ");
}
