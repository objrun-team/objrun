/**
 * 树的控制流：**派生 / 判死开兄弟 / 回退到更上层**。
 *
 * 这是一个**推断函数**（`cycle.infer` 指向它），不是内核的一部分 —— 内核只认
 * 「回什么形状」，不认得「兄弟」「回退」是什么意思。换一种搜索策略 = 换一个
 * `infer` 句柄，内核一个字不动。
 *
 * ## 节点的终止状态，出生即定不回改
 *
 * | 状态 | 意思 |
 * | --- | --- |
 * | `reached` | 到达终点，这条路成了 |
 * | `dead_failed` | 判死：这一步做砸了 |
 * | `dead_below_bar` | 判死：够不着标准 |
 * | 空 | 还在跑 |
 *
 * **判死是混合策略**：`dead_failed` 和 `dead_below_bar` 任一都算判死，都触发开兄弟。
 * 分两个值是为了事后查得出「是砸了还是不够好」，判定那一刻它们等价。
 *
 * ## 判死之后怎么走
 *
 * 1. 数同一个父底下判死了几个兄弟
 * 2. **没到上限** → 在同一个父底下开一个新兄弟，换个方向再试
 * 3. **到上限了** → 回退到**更上层**，从祖父那儿另开 —— 这一层的方向都试遍了
 * 4. **回到根还是没路** → 到此为止
 *
 * 还有一道并发闸：同一个父底下**没干完的**行数到了 `max_branches` 就不再开新的。
 * 那是「同时几条」，跟「判死几个」不是一回事。
 *
 * ## 走法必须在候选之内 —— 数据说了算
 *
 * 内核只让推断函数在 `cycle.next` 里挑，挑到候选之外当场炸。所以：
 *
 * - 要让这一层能**开兄弟**，这个周期的 `next` 里得**列上它自己**
 * - 要让它能**回退**，`next` 里得列上要退回去的那个周期
 *
 * 这不是限制，是把「这道题允许怎么走」写在数据里。周期表没说能开兄弟，
 * 那这棵树就不该开兄弟 —— 而不是让推断函数自己决定。
 *
 * ## ĝ 往下走，G 只在「自称到了」那一刻复核
 *
 * 两个判据管的不是一件事，混用会让树永远走不到第二层：
 *
 * - **ĝ（自评 / 启发式）**：这一步做完了没有。还在要工具 = 没完，接着往下派生。
 *   老代码那边说得明白：绿度、打分、信心分级都是 `F` 内部的搜索启发式，是模型对
 *   目标的**估计**，不属于样本格式。
 * - **G（验证函数）**：只回 0/1，**在节点自称到达终点那一刻才调**。说 1 → 真的
 *   `reached`；说 0 → 它以为到了其实没到 → `dead_failed`，开兄弟换个方向。
 *
 * 这才是 verifier-guided：不是每一步都问 G（那样中间步全被判死，树长不出来），
 * 而是**不许它自己说了算**。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { deliverVerdict } from "../msg/deliver.ts";
import { tableNameOf } from "../install/index.ts";
import { evaluate } from "../objective/run.ts";
import type { Sealed } from "../objective/store.ts";

type Row = Record<string, unknown>;

/** 推断函数拿到的那一份。 */
interface Ask {
  task: Row;
  cycle: Row;
  agent: Row;
  chain: string;
  next: string[];
  result: unknown;
  /** 我是哪张子表的哪一行。 */
  sub: string;
  unit: number;
}

/** 回给内核的形状。 */
interface Said {
  to: string | null;
  /** 新行挂在哪一行底下。**`null` = 挂在根上（没有父）**；不给这个键 = 从当前行接。 */
  from_cycle?: string | null;
  from_unit?: number | null;
  status?: string;
}

interface Node {
  cycle: string;
  unit: number;
  from_cycle: string | null;
  from_unit: number | null;
  status: string | null;
  done: number;
}

const DEAD = new Set(["dead_failed", "dead_below_bar"]);

/** 走树那套机制的推断函数。周期表里 `infer` 写这个名字，就是在选这套机制。 */
export const TREE_INFER = "fn:infer.dfs";

/** 这套机制自带的那一站：**交卷**。 */
export const SUBMIT = "submit";

/** 声明里一个周期的形状（`declare/index.ts` 收的那一份）。 */
export interface DeclaredCycle {
  cycle: string;
  apiMode?: string;
  maxUnits?: number;
  from?: string[];
  next?: string[];
  infer: string;
  [k: string]: unknown;
}

/**
 * **交卷那一站随机制一起装上，不用谁在声明里写。**
 *
 * 一个模式只要有周期选了走树这套机制，它就需要一个交卷站 —— 那不是这道题的
 * 特性，是这套机制的特性：判决要判**它交上来的那一份**，而「交上来」得有个
 * 落脚的站。让每份声明自己写一遍的话，写漏一个模式就退回「内核回头去消息表里
 * 猜哪句话像答案」，而猜是会猜错的。
 *
 * 干活那几站的 `next` 也跟着加上它 —— 内核只让推断函数在 `next` 里挑，
 * 不加的话推断函数指向交卷站会被当场拒。
 *
 * **声明里自己写了 `submit` 就不动。** 这是补默认，不是抢方向盘。
 *
 * 额度不另设闸：交卷站的上限取干活那几站之和，让它永远不是那个卡住的地方 ——
 * 该由「还能干几轮」说了算，不该由「还能交几次」说了算。
 */
export function withSubmit(cycles: DeclaredCycle[]): DeclaredCycle[] {
  const tree = cycles.filter((c) => c.infer === TREE_INFER);
  if (tree.length === 0) return cycles;
  if (cycles.some((c) => c.cycle === SUBMIT)) return cycles;

  // **交卷接在动作阶段后面。** 动作阶段是不叫模型的那一站（`api_mode` 为空）：
  // 它跑的是上一站请求的工具，跑完那一轮工作就完整了，该轮到「交不交」。
  // 思考站不直接接交卷 —— 刚开口说完就交，中间那一步工具还没跑。
  //
  // 一个动作阶段都没有的机制（每一站都叫模型），退回接在所有站后面。
  const acts = tree.filter((c) => (c.apiMode ?? "").trim() === "");
  const before = acts.length > 0 ? acts : tree;
  const names = new Set(before.map((c) => c.cycle));

  return [
    ...cycles.map((c) => (names.has(c.cycle) ? { ...c, next: [...new Set([...(c.next ?? []), SUBMIT])] } : c)),
    {
      cycle: SUBMIT,
      // **跟干活那几站同一种轨。** 硬写 chat 的话，一个不用模型的机制（`agent.unit`
      // 走外部句柄那种）会在这一站上卡死：它的智能体一条 chat 轨都没有。
      apiMode: tree.map((c) => (c.apiMode ?? "").trim()).find((x) => x !== "") ?? "",
      maxUnits: tree.reduce((n, c) => n + Number(c.maxUnits ?? 1), 0),
      from: before.map((c) => c.cycle),
      // **交完接下一个节点的动作阶段，不是走到头。** 判 0 之后该往前走进下一次
      // 尝试，而不是靠回退硬凑 —— 做成终点站的那一版只能退到父节点，而父节点
      // 又立刻拐回交卷，交的还是同一份东西（实测空转过三轮）。
      next: before.map((c) => c.cycle),
      infer: TREE_INFER,
    },
  ];
}

function nodesOf(db: Conn, sub: string, task: string): Node[] {
  return all(db, `select cycle, unit, from_cycle, from_unit, status, done from "${sub}" where task = ?`, [
    task,
  ]) as unknown as Node[];
}

/** 这一站（或它上一站）调过交卷工具没有。**只看这条链上刚发生的那一次**。 */
function calledSubmit(db: Conn, inst: { agent: string; instance: string } | undefined, unit: number): boolean {
  if (!inst) return false;
  const t = tableNameOf("agent_{}_msg", inst.agent);
  const rows = all(db, `select body from "${t}" where instance = ? and unit in (?, ?) and kind = 'call'`, [
    inst.instance,
    unit,
    unit - 1,
  ]) as { body: string }[];
  return rows.some((r) => {
    try {
      const v = JSON.parse(r.body) as { calls?: { name?: string }[] };
      return (v.calls ?? []).some((c) => c.name === SUBMIT);
    } catch {
      return false;
    }
  });
}

/**
 * 它是不是已经拿这一份问过 G 了（`verify`），问出来什么。
 *
 * 比的是**答复原文**：一字不差才算同一份。差一个字符就是另一份候选，
 * 上一次的判决对它不作数。
 */
function verdictFor(
  db: Conn,
  inst: { agent: string; instance: string } | undefined,
  said: string,
): { pass: 0 | 1; why: string } | null {
  if (!inst || !said.trim()) return null;
  const t = tableNameOf("agent_{}_msg", inst.agent);
  const rows = all(db, `select unit, seq, kind, body from "${t}" where instance = ? order by unit, seq`, [
    inst.instance,
  ]) as { unit: number; seq: number; kind: string; body: string }[];
  const asked = new Map<string, string>(); // 调用 id → 问的是哪一份
  let hit: { pass: 0 | 1; why: string } | null = null;
  for (const r of rows) {
    let v: { calls?: { id?: string; name?: string; input?: { answer?: unknown } }[]; id?: string; name?: string; value?: { pass?: unknown; why?: unknown } };
    try {
      v = JSON.parse(r.body) as typeof v;
    } catch {
      continue;
    }
    if (r.kind === "call") {
      for (const c of v.calls ?? []) {
        if (c.name === "verify" && typeof c.input?.answer === "string" && c.id) asked.set(c.id, c.input.answer);
      }
    } else if (r.kind === "tool" && v.name === "verify" && v.id && asked.get(v.id) === said) {
      const pass = Number(v.value?.pass) === 1 ? 1 : 0;
      hit = { pass, why: String(v.value?.why ?? "") };
    }
  }
  return hit;
}

/**
 * 这一站**开口说了什么**。
 *
 * `prompt` 行的 `body` 就是那段话；`call` 行的 `body` 是 `{text, calls}`，
 * 说的话在 `text` 里 —— 原样递出去的话，拿到的是一坨 JSON。
 */
function spokenAt(result: unknown): string {
  const r = (result ?? {}) as { kind?: string; body?: unknown };
  if (r.kind === "prompt") return String(r.body ?? "");
  if (r.kind === "call") {
    try {
      return String((JSON.parse(String(r.body ?? "")) as { text?: unknown }).text ?? "");
    } catch {
      return "";
    }
  }
  return "";
}

/**
 * 它这一站**想拿哪一份去问 G**。
 *
 * 只认带 `answer` 的那种调用（`verify`）。`submit` 是无参的，没有这一栏；
 * 内核自己投回去的判决也叫 `verify`，但它的入参是 `{task, at}` —— 一样没有。
 * 所以「有 `answer`」这一条就把三者分开了。
 */
function answerAsked(result: unknown): string {
  const r = (result ?? {}) as { kind?: string; body?: unknown };
  if (r.kind !== "call") return "";
  try {
    const v = JSON.parse(String(r.body ?? "")) as { calls?: { input?: { answer?: unknown } }[] };
    for (const c of [...(v.calls ?? [])].reverse()) {
      if (typeof c.input?.answer === "string" && c.input.answer.trim()) return c.input.answer;
    }
  } catch {
    /* 读不出来就当它没交 */
  }
  return "";
}

/**
 * 还有没有地方能**再想一遍**。
 *
 * 看的不是「哪个周期还没用满」，而是「哪个**会开口的**周期还没用满」：一个没有
 * `api_mode` 的站不叫模型（它跑的是上一站请求的工具），退到那儿产不出新答案，
 * 只会立刻再拐回交卷站 —— 交的还是同一份东西。
 *
 * 实测就这么空转过：ask 用满、act 还有额度，于是
 * submit[dead] → act → submit[dead] → act → submit[dead]，
 * 三次判一样的 0，中间一个新想法都没有。
 *
 * 一个会开口的站都没有的机制（`agent.unit` 走外部句柄那种），退回看所有站。
 */
function noRoomToRetry(db: Conn, a: Ask, nodes: Node[]): boolean {
  const cycles = all(db, `select cycle, api_mode, max_units from cycle where mode = ?`, [
    String(a.task.mode),
  ]) as { cycle: string; api_mode: string | null; max_units: number }[];
  const work = cycles.filter((c) => c.cycle !== SUBMIT);
  if (work.length === 0) return true;
  const speaks = work.filter((c) => (c.api_mode ?? "").trim() !== "");
  const room = speaks.length > 0 ? speaks : work;
  return room.every((c) => nodes.filter((n) => n.cycle === c.cycle).length >= Number(c.max_units));
}

/** 这个周期的额度用完了没有。 */
function full(db: Conn, a: Ask, nodes: Node[], cycle: string): boolean {
  const cap = all(db, `select max_units from cycle where mode = ? and cycle = ?`, [
    String(a.task.mode),
    cycle,
  ])[0] as { max_units?: number } | undefined;
  if (!cap) return false;
  return nodes.filter((n) => n.cycle === cycle).length >= Number(cap.max_units);
}

/** 同一个父底下的兄弟（不含自己）。 */
function siblings(nodes: Node[], me: Node): Node[] {
  return nodes.filter(
    (n) => !(n.cycle === me.cycle && n.unit === me.unit) && n.from_cycle === me.from_cycle && n.from_unit === me.from_unit,
  );
}

/**
 * **交卷那个工具。无参。**
 *
 * 它只干一件事：**说一声「我交了」**，于是流转提前拐到交卷站。不带参数是故意的 ——
 * 交的是什么，是交卷站上说的那段话，不是这次调用的入参。两处都能交的话，
 * 「到底判哪一份」就成了个得靠约定回答的问题。
 *
 * 不调它也会走到交卷站（干活那几站的额度用完，或者它自己说完了一段话）。
 * 调它的意义只有一个：**提前**。想早点收工就早点收工，不用把额度耗干。
 *
 * ## 跟 `verify` 的分工
 *
 * `verify` 是**验证**：干活途中拿一份候选去问「这样行不行」，随时能问、能问多次。
 * `submit` 是**交卷**：这件事我做完了。两个时刻，两件事。
 *
 * 这道题有没有 G，不改这个工具的形状 —— 改的是**交卷站上多不多做一步**：
 * 有 G 就在那儿判一次，没有就直接收工。
 */
const SUBMIT_TOOL = {
  name: SUBMIT,
  does:
    "Hand your work in. Takes no arguments: what gets handed in is what you say at the hand-in step, " +
    "not an argument here. You will reach that step anyway once the working budget runs out - " +
    "calling this only gets you there sooner.",
  params: { type: "object", properties: {} },
  output: { type: "object", properties: { handingIn: { type: "boolean" } } },
  prompt:
    "Call submit when the work is done. It takes no arguments: what gets handed in is what you say at the " +
    "hand-in step, which comes right after. You will reach that step anyway once the working budget runs " +
    "out - calling submit only gets you there sooner, while there is still room to be judged and try again.",
  expectMs: 10_000,
};

/**
 * 注册树的控制流。
 *
 * `sealed` 给进来是为了让判据来自 G —— 没有它就只能自评，而自评的树是瞎走的。
 */
export function registerTree(db: Conn, reg: Registry, sealed: Sealed): string[] {
  reg.register(db, "fn:infer.dfs", 900_000, async (arg) => {
    const a = arg as unknown as Ask;
    const task = String(a.task.id);
    const here = String(a.cycle.cycle);
    const nodes = nodesOf(db, a.sub, task);
    const me = nodes.find((n) => n.cycle === here && n.unit === a.unit);
    if (!me) throw new Error(`cannot find ${here}#${a.unit} of ${task} in ${a.sub}`);

    const inst = all(db, `select agent, instance from "${a.sub}" where task = ? and cycle = ? and unit = ?`, [
      task,
      here,
      a.unit,
    ])[0] as { agent: string; instance: string } | undefined;

    // ── 干活那几站：**这儿不判** ──────────────────────────────────────────
    //
    // 判决只在交卷站出。以前是「出现一条 `prompt` 就叫 G」—— 那等于内核替它交了
    // 一份它没交的东西，而且那条 `prompt` 是空的时候（模型这一发什么都没生成出来）
    // 也照判，白烧一次 G、白判死一条分支。实测两道题就这么没的。
    if (here !== SUBMIT) {
      const r = (a.result ?? {}) as { kind?: string; body?: unknown };

      // **拐去交卷站的两条路：**
      //
      // 1. 它调了 `submit` —— 那就是「我交了」，提前拐过去
      // 2. 它说出了一段有内容的话 —— 自称做完了，也拐过去（没调工具也走得到）
      //
      // 空话不算。一条什么都没生成出来的 `prompt` 不是「我做完了」，
      // 是这一发没出来 —— 按普通推进往下走，让它下一站接着说。
      const handedIn = calledSubmit(db, inst, a.unit);
      const spoke = r.kind === "prompt" && spokenAt(a.result).trim() !== "";
      if ((handedIn || spoke) && a.next.includes(SUBMIT)) return { to: SUBMIT } satisfies Said;

      // 还在跑：按候选往下走一格，从当前这一行接。
      const to = a.next.find((c) => c !== SUBMIT) ?? null;

      // **第三条到交卷站的路：干活这边走不动了。**
      //
      // 一直在调工具的题永远不会说出一段完整的话，也就永远不会走上面那两条 ——
      // 于是额度耗干，那条分支在 `#advance` 里被静静关掉，收尾一看「没交卷」。
      // 实测这么丢过整整一道题（cmt-3：12 个单元走满，一次都没到交卷站）。
      //
      // 「走不动」有两种：干活那一站的额度用完了，或者候选里除了交卷站就没别的了。
      // 两种都该交卷 —— 手上有什么交什么，总好过什么都不交。
      const stuck = to === null || full(db, a, nodes, to);
      if (stuck && a.next.includes(SUBMIT)) return { to: SUBMIT } satisfies Said;
      return { to } satisfies Said;
    }

    // ── 交卷站 ────────────────────────────────────────────────────────────
    //
    // 交的就是这一站说的那段话。没有 G 的题到这儿就是收工；有 G 的题**在这儿多做
    // 一步**：判一次。「有没有验证过」不改交卷这件事的形状，只改这一步跑不跑得成。
    let status = "reached";
    if (sealed.has(task)) {
      // 交的是**它说的那段话**。一条 `call` 行的 `body` 是 `{text, calls}` ——
      // 原样递过去的话，G 拿到的是一坨 JSON（实测就这么判过一次 0）。
      //
      // 一个字都没说的话，再看它**想拿什么去问 G**：交卷站上工具还挂着，而模型
      // 在那儿的第一反应常常是调 `verify`，答案就写在那次调用的 `answer` 里。
      // 那一次调用不会被执行（后面没有站了），但「它想交的是这一份」是明摆着的 ——
      // 因为一次不会被执行的调用就把答案丢掉，是我们读得不够，不是它没交。
      // 实测：cmt-3 在交卷站上调了 `verify {"answer": "\\boxed{4N_q^2}"}`。
      const said = spokenAt(a.result) || answerAsked(a.result);
      const g = sealed.open(task)!;

      // **验过就不必再判一次。** `verify` 是干活途中的验证，交卷是这一刻的提交；
      // 两个时刻，但问的是同一个 G。它刚验过的正是这一份的话，那次判决就是这一次
      // 的答案 —— 再打一遍判卷台只是多花一次钱，还多一次抖动的机会。
      const had = verdictFor(db, inst, said);
      // **递出去的是挖出来的那一份，不是原始 result。** 原样递的话，G 那一侧
      // 拿到的是 `{text, calls}` 整坨 JSON —— 上面那几行把答案挖出来就白挖了。
      // 形状跟收尾那一路对齐（`main.ts`：`result: {body}`），一个 G 脚本两处都能用。
      const v = had ?? (await evaluate(g, reg, { task: a.task, chain: a.chain, result: { kind: "prompt", body: said } }));

      // **判决要落进上下文**，不能只进日志。投成「一次带结果的工具调用」——
      // 它是外部的、这一次的观测，正好是 tool 结果的语义。
      //
      // 落在**交卷这一站**上：兄弟默认看不见它（那是故意的），要看得自己
      // `node_load` 去取 —— 「进度共享是能看、不是直接继承」。
      if (inst) {
        deliverVerdict(db, {
          agent: inst.agent,
          instance: inst.instance,
          unit: a.unit,
          name: "verify",
          input: { task, at: `${here}#${a.unit}` },
          // **`why` 一起给。** 只给 0/1 的话，模型只知道错了，不知道错在哪 ——
          // 那跟不给差不多，它下一条分支多半原样再来一遍。
          value: { pass: v.pass, why: v.why, ...(had ? { reused: true } : {}) },
        });
      }

      if (v.pass !== 1) status = "dead_failed";
    }

    // 判 1 = 这道题做成了，树到此为止。
    if (status === "reached") return { to: null, status } satisfies Said;

    // **判 0 只说明这一次交的不成，不说明这道题到头了。**
    //
    // 往前走进下一个节点的动作阶段：那一站把上一轮请求的工具跑掉，然后又是一次
    // 交卷的机会。做成终点站的那一版只能往回退，而退到父节点又立刻拐回交卷，
    // 交的还是同一份东西 —— 实测空转过三轮，三次判一样的 0。
    //
    // 走不动了（能开口的站都用满了）就到此为止，这一条在下面。
    if (!noRoomToRetry(db, a, nodes)) {
      const on = a.next.find((c) => c !== SUBMIT) ?? null;
      if (on !== null) return { to: on, status } satisfies Said;
    }

    // ── 判死了 ────────────────────────────────────────────────────────────

    // **干活的站全满了就到此为止。** 判死之后往回退是为了「换条路走」，而换路要有
    // 地方走：退回去的那一层还得能再想一遍。每一个能干活的周期都用满的时候，
    // 退到哪儿都只是立刻再拐回交卷站，交的还是同一份东西。
    //
    // 实测就这么空转过：submit[dead] → act → submit[dead] → act → submit[dead]，
    // 三次都判一样的 0，中间一个新想法都没有。
    if (noRoomToRetry(db, a, nodes)) return { to: null, status } satisfies Said;

    const maxBranches = Number(a.task.max_branches ?? 2);
    const maxDead = Number(a.task.max_dead_siblings ?? 3);
    const sibs = siblings(nodes, me);

    // 并发闸：同一个父底下没干完的到了上限就不再开。这是「同时几条」。
    const busy = sibs.filter((n) => !n.done).length;
    if (busy >= maxBranches) return { to: null, status } satisfies Said;

    // 判死闸：这一层试过的方向够多了 → 回退到更上层。
    //
    // **交卷站不开兄弟。** 在交卷站旁边再开一个交卷站，交的还是同一份东西 ——
    // 要换的是「怎么做」，那在干活那一层，所以交卷判死一律往上退。
    const dead = sibs.filter((n) => n.status !== null && DEAD.has(n.status)).length + 1;
    if (here !== SUBMIT && dead < maxDead) {
      // 还能试：在**同一个父**底下开一个兄弟。
      // 兄弟跟我挂在**同一个父**底下。我要是根（没有父），兄弟也是根。
      return { to: here, from_cycle: me.from_cycle, from_unit: me.from_unit, status } satisfies Said;
    }

    // 回退：往上爬一层，从**祖父**底下另开。爬到根还没路就到此为止。
    const parent =
      me.from_cycle === null || me.from_unit === null
        ? null
        : nodes.find((n) => n.cycle === me.from_cycle && n.unit === me.from_unit);
    if (!parent || parent.from_cycle === null || parent.from_unit === null) {
      return { to: null, status } satisfies Said;
    }
    return {
      to: parent.cycle,
      from_cycle: parent.from_cycle,
      from_unit: parent.from_unit,
      status,
    } satisfies Said;
  });

  // **交卷那个工具跟这套机制一起装上。** 它属于机制，不属于某一份声明 ——
  // 条件是「这一站的推断函数是不是走树的那个」，跟 `task_tree` / `node_load` 同一条。
  reg.register(db, `fn:tool.${SUBMIT_TOOL.name}`, SUBMIT_TOOL.expectMs, async () => ({ handingIn: true }));
  run(
    db,
    `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable)
     values (?, ?, ?, ?, ?, ?, 0, 0, null, 1)
     on conflict(name) do update set
       identity = excluded.identity, does = excluded.does, params = excluded.params,
       output = excluded.output, prompt = excluded.prompt, system = excluded.system`,
    [
      SUBMIT_TOOL.name,
      `fn:tool.${SUBMIT_TOOL.name}`,
      SUBMIT_TOOL.does,
      JSON.stringify(SUBMIT_TOOL.params),
      JSON.stringify(SUBMIT_TOOL.output),
      SUBMIT_TOOL.prompt,
    ],
  );
  run(db, `delete from trigger where owner_kind = 'tool' and owner = ?`, [SUBMIT_TOOL.name]);
  run(
    db,
    `insert into trigger (owner_kind, owner, "group", dim, "key", op, value)
     values ('tool', ?, 0, 'cycle', 'infer', 'eq', ?)`,
    [SUBMIT_TOOL.name, TREE_INFER],
  );

  return [TREE_INFER, SUBMIT_TOOL.name];
}
