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
import { SUBMIT } from "../tree/dfs.ts";
import { chainOf, type Unit } from "./chain.ts";
import type { Registry } from "./registry.ts";
import { deliver } from "../msg/deliver.ts";
import { fire, type Facts } from "./trigger.ts";

type Row = Record<string, unknown>;

/**
 * 没人接的那次工具请求，别往外发。
 *
 * 模型请求了工具，落一行 `call`；工具跑完落一行 `tool`，靠 `id` 配对。但**这一站有没有
 * 人真去跑，取决于机制怎么搭**：下一站走 `fn:unit.tools` 就有人跑，一条纯问答的轨就没有。
 * 而系统工具（读写那一组）是无条件挂上去的 —— 于是一条纯问答的多站机制里，模型迟早
 * 会请求一次工具，没人跑，那一行 `call` 就永远配不上 `tool`。
 *
 * 这时候上下文**再也发不出去了**：模型那边一律要求「有 tool_call 就得有对应的
 * tool result」，缺了直接拒（`Tool result is missing for tool call …`）。整条链路从此
 * 每一站都发不出去，任务卡到超时，而错看着像模型那边的毛病 —— 跟真正的原因隔着十万八千里。
 *
 * 所以配不上的那一行在这儿摘掉：**没人跑，等于没发生过**。库里那一行不动
 * （它是那一刻的真相），摘的只是发出去的这一份。
 */
function dropDangling(rows: Row[]): Row[] {
  const answered = new Set<string>();
  for (const r of rows) {
    if (r.kind !== "tool") continue;
    try {
      const id = (JSON.parse(String(r.body)) as { id?: string }).id;
      if (id) answered.add(id);
    } catch {
      // 读不出 id 的当它没答过 —— 宁可多摘一行，也不要发一份发不出去的
    }
  }
  return rows.filter((r) => {
    if (r.kind !== "call") return true;
    let calls: { id?: string }[];
    try {
      calls = (JSON.parse(String(r.body)) as { calls?: { id?: string }[] }).calls ?? [];
    } catch {
      return true;
    }
    // 一行 `call` 里可能有好几次调用；**只要有一次没人答，整行就发不出去**。
    return calls.every((c) => c.id === undefined || answered.has(c.id));
  });
}

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
  onDone?(task: string, expired?: string): void;
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
      `select id, created_at, solve_seconds from task where state not in ('done','failed')`,
    ) as { id: string; created_at: number; solve_seconds: number }[]) {
      if (now - Number(t.created_at) <= Number(t.solve_seconds) * 1000) continue;
      const key = `task expired\u0000${t.id}`;
      if (this.#cried.has(key)) continue;
      this.#cried.add(key);
      this.#log.warn(`task ${t.id} expired: ran ${Math.round((now - Number(t.created_at)) / 1000)}s, limit ${t.solve_seconds}s`);
      // 先落一个失败，让它别再被排上；有 G 的话下面那一声会按判决改写。
      run(this.#store.rw, `update task set state = failed, result = ? where id = ?`, [
        JSON.stringify({ pass: 0, why: `over solve_seconds=${t.solve_seconds}s` }),
        t.id,
      ]);
      // **超时也要问 G。** 以前这条路直接写 failed 就完了，于是「时限内交对了、
      // 只是树没来得及收尾」跟「什么都没做出来」在成绩单上长得一模一样。
      this.#hooks.onDone?.(t.id, `over solve_seconds=${t.solve_seconds}s`);
    }
    for (const r of rows) {
      const cap = this.#expectSafe(r);
      if (cap === null || now - r.at <= cap) continue;
      this.#log.warn(
        `declared dead: ${r.sub} ${r.task} ${r.cycle}#${r.unit} (${r.agent}/${r.instance}) has been ${now - r.at}ms, over ${cap}ms`,
      );
    }
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
        // 这一轮的任务视图。**每轮现算**，不是库里存着的一条消息 ——
        // 存成消息的话，兄弟分支爬不到它（见 `#viewOf`）。
        view: this.#viewOf(p, facts.task),
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
      const why = msg(e);
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
    const nodes = all(
      this.#store.ro,
      `select cycle, unit, from_cycle, from_unit, status, done from "${p.sub}" where task = ? order by unit`,
      [p.task],
    );
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
      tried: nodes.map((n) => ({
        at: `${String(n.cycle)}#${String(n.unit)}`,
        from: n.from_cycle === null ? null : `${String(n.from_cycle)}#${String(n.from_unit)}`,
        status: n.status,
        done: Number(n.done) === 1,
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
        all(this.#store.ro, `select cycle, count(*) as n from "${p.sub}" where task = ? group by cycle`, [
          p.task,
        ]) as { cycle: string; n: number }[]
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
    const rows = all(
      this.#store.ro,
      `select unit, seq, role, kind, body from "${t}"
        where instance = ? and unit in (${holes}) order by unit, seq`,
      [p.instance, ...line],
    );
    return dropDangling(rows);
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
      const cap = one(this.#store.ro, `select max_units from cycle where mode = ? and cycle = ?`, [p.mode, to]);
      if (!cap) throw new Error(`no row in cycle for ${p.mode}/${to}`);
      const used = Number(
        one(this.#store.ro, `select count(*) as c from "${p.sub}" where task = ? and cycle = ?`, [p.task, to])!.c,
      );
      if (used >= Number(cap.max_units)) {
        this.#log.warn(`${p.task}: ${p.mode}/${to} has used all ${cap.max_units} units, not opening more`);
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
    // 跑完了喊一声。**内核不知道那边会干什么** —— 判成没成不是它的事。
    if (justDone) this.#hooks.onDone?.(task);
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
