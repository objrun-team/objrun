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
import { candidateInput, evaluate } from "../objective/run.ts";
import { CANDIDATE, type Sealed } from "../objective/store.ts";

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
  /** 这一行属于哪个节点。一个节点是一次完整的尝试，它自己有一份额度。 */
  node: number;
  from_cycle: string | null;
  from_unit: number | null;
  status: string | null;
  done: number;
}

const DEAD = new Set(["dead_failed", "dead_below_bar"]);

/** 走树那套机制的推断函数。周期表里 `infer` 写这个名字，就是在选这套机制。 */
export const TREE_INFER = "fn:infer.dfs";

/** 这套机制自带的那一站：**交卷**。 */
/** 判据那个工具叫什么。**只有一个出处** —— 交卷这一步落判决时也用它。 */
export const VERIFY = "verify";

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

  // 交卷之后接**入口站** —— 机制里那个不从谁来的站（`from` 是空的）。
  //
  // 判 0 只说明这一次交的不成，接下来是**一次全新的尝试**，而一次尝试从想事情
  // 开始。上一版接的是动作站（跑工具的那个），理由是「把上一站请求的工具跑完，
  // 那一轮工作才完整」—— 那个理由在判死之后不成立：节点已经死了，补跑它的工具
  // 没有意义，而新节点上来就跑一遍自己从没请求过的工具，等于白花一格。
  //
  // 实测的样子是 `submit#8[dead_failed] → act#9 → submit#10`：新节点两步就又交了
  // 一次，中间一次都没想过。
  const entry = tree.filter((c) => (c.from ?? []).length === 0);
  const after = entry.length > 0 ? entry : tree;
  const names = new Set(tree.map((c) => c.cycle));

  return [
    // **每一站都能走到交卷。** 「干活的额度花完了就该交」是节点级的规矩，
    // 而这条规矩得写在表上：表说得出的边，才是内核准许走的边
    // （`loop.ts` 那道白名单：`if (!saidFrom && !next.includes(to))`）。
    //
    // 让推断函数带上父指针绕过白名单也能拐过去，但那样表上就看不出这条边 ——
    // 表说的和实际走的不一样，那才是把表整乱套。
    ...cycles.map((c) => (names.has(c.cycle) ? { ...c, next: [...new Set([...(c.next ?? []), SUBMIT])] } : c)),
    // **交卷只有这一行。** 它自己说全了：从哪来、到哪去、谁来判。
    {
      cycle: SUBMIT,
      mustCall: SUBMIT_TOOL.name,
      // **这一站只能干一件事，而且请求里就写死了。**
      //
      // 工具那边已经只摆了 `submit`（见 `tools/index.ts` 那条「不在交卷站」的条件），
      // 可只摆一件挡不住它去调一件没摆的：实测它在这一站请求过 `web_search`，那一格
      // 就这么白费了 —— 没人会去跑它，最后补一条「没跑成」。带上「必须调这一个」，
      // 它连「说一堆话然后什么都没交」都做不到。
      //
      // 以前不敢默认填，是因为**它跟思考互斥**：模型在思考时 `tool_choice` 一律 400。
      // 那道坎现在由适配器兜着 —— 这一站要求必调某个工具时，它把思考关掉再发
      // （见 `llm/index.ts`）。交卷本来也不需要想：要交的东西前面早就算完了。
      // 跟干活那几站同一种轨。硬写 chat 的话，一个不用模型的机制（`agent.unit`
      // 走外部句柄那种）会在这一站上卡死：它的智能体一条 chat 轨都没有。
      apiMode: tree.map((c) => (c.apiMode ?? "").trim()).find((x) => x !== "") ?? "",
      // **一个节点只交一次。** 交卷站每次都落一个终态（判活或判死），落了节点就
      // 结束 —— 结构上不可能有第二个。额度是按节点数的（见 `full`），所以这儿写 1
      // 才是这张表在说实话；写成「干活那几站之和」那种够大的数，读表的人会以为
      // 一个节点能交好多次。
      maxUnits: 1,
      from: tree.map((c) => c.cycle),
      // 交完接下一个节点的入口站 —— 判 0 只说明这一次交的不成，不说明这道题到头
      // 了。做成终点站（`next: []`）的那一版只能往回退，而退回去又立刻拐回交卷，
      // 交的还是同一份东西。
      next: after.map((c) => c.cycle),
      infer: TREE_INFER,
    },
  ];
}

function nodesOf(db: Conn, sub: string, task: string): Node[] {
  return all(db, `select cycle, unit, node, from_cycle, from_unit, status, done from "${sub}" where task = ?`, [
    task,
  ]) as unknown as Node[];
}

/**
 * 这一格（或它同一个节点里的上一格）交上来的那份答案。没交过就回 `null`。
 *
 * **答案在调用的参数里，不从它说的话里解析。** 解析是兜底：模型可能说三段话、
 * 每段里都有一个式子，挑哪一段都是猜。而猜错的表现是「答案明明写对了却判 0」——
 * 那种事查起来最费劲，因为看日志它确实答对了。
 *
 * ## 为什么要往回看一格，又为什么必须限在同一个节点里
 *
 * 在干活站上按交卷是允许的：那一次就是交，流转把它送到交卷站，交卷站不必再交
 * 一遍。所以交卷站得认得出上一格那次调用 —— 这就是往回看一格。
 *
 * **但上一格未必是同一个节点的。** 判死之后开的新节点，它第一站的上一格正好是
 * **前一个节点的交卷站**，那儿躺着一次 `submit`。不限节点的话，新节点一睁眼就
 * 被判成「已经交过了」，当场又拐去交卷 —— 它想先验一次、想读读上一次错在哪，
 * 那些调用连跑的机会都没有，最后闭着眼交一份没改过的答案。
 *
 * 实测：cmt-3 的 node2 就是这么烧掉的（`ask#5` 调了四次 `verify`，一次没跑成，
 * 一站就被拐去 `submit#6` 判死）。它的 node3 侥幸正常，是因为 node2 的交卷站
 * 压根没交出东西 —— 靠的是运气，不是规矩。
 */
/**
 * 这个实例交上来的最后一份答案。**「交了什么」只有这一个出处。**
 *
 * 交卷是调一次 `submit` 并把答案放进去。谁想知道「它交了什么」都从这儿问 ——
 * 各读各的话，同一份东西会有两个答案：交卷站按调用里的那份判，收尾按它随口说的
 * 那段判，两边判出不同结果，而成绩以后者为准。实测就这么丢过题。
 *
 * `units` 给了就只看那几格（交卷站用它把范围限在同一个节点里），不给就看整条实例。
 */
export function handedIn(
  db: Conn,
  agent: string,
  instance: string,
  units?: number[],
): string | null {
  const t = tableNameOf("agent_{}_msg", agent);
  const where = units ? ` and unit in (${units.map(() => "?").join(", ")})` : "";
  const rows = all(db, `select body from "${t}" where instance = ?${where} and kind = 'call' order by unit, seq`, [
    instance,
    ...(units ?? []),
  ]) as { body: string }[];
  let found: string | null = null;
  for (const r of rows) {
    try {
      const v = JSON.parse(r.body) as { calls?: { name?: string; input?: { answer?: unknown } }[] };
      for (const c of v.calls ?? []) {
        if (c.name !== SUBMIT) continue;
        // 交了一份空的也算交 —— 那是它的答案，判 0 是判卷台的事，不是这儿的事。
        found = typeof c.input?.answer === "string" ? c.input.answer : "";
      }
    } catch {
      // 读不出来就当这一行没交过
    }
  }
  return found;
}
function submitted(
  db: Conn,
  inst: { agent: string; instance: string } | undefined,
  unit: number,
  sameNode: (u: number) => boolean,
): string | null {
  if (!inst) return null;
  const look = [unit, unit - 1].filter((u) => u > 0 && sameNode(u));
  if (look.length === 0) return null;
  return handedIn(db, inst.agent, inst.instance, look);
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
): { pass: 0 | 1; why: string; note: string } | null {
  if (!inst || !said.trim()) return null;
  const t = tableNameOf("agent_{}_msg", inst.agent);
  const rows = all(db, `select unit, seq, kind, body from "${t}" where instance = ? order by unit, seq`, [
    inst.instance,
  ]) as { unit: number; seq: number; kind: string; body: string }[];
  const asked = new Map<string, string>(); // 调用 id → 问的是哪一份
  let hit: { pass: 0 | 1; why: string; note: string } | null = null;
  for (const r of rows) {
    let v: { calls?: { id?: string; name?: string; input?: { answer?: unknown } }[]; id?: string; name?: string; value?: { pass?: unknown; valid?: unknown; outcome?: unknown; why?: unknown; note?: unknown } };
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
      if (v.value?.valid === false || v.value?.outcome === "grader_error") continue;
      if (v.value?.pass !== 0 && v.value?.pass !== 1) continue;
      const pass = v.value.pass;
      hit = { pass, why: String(v.value?.why ?? ""), note: String(v.value?.note ?? "") };
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
 * 这个周期在**这一个节点里**的额度用完了没有。
 *
 * 按整道题数的话，第一个节点就把预算吃光了 —— 一道题只可能有一次提交，
 * 「判死 → 换条路」永远跑不起来。一个节点是一次尝试，它自己有一份预算。
 */
function full(db: Conn, a: Ask, nodes: Node[], cycle: string, node: number): boolean {
  const cap = all(db, `select max_units from cycle where mode = ? and cycle = ?`, [
    String(a.task.mode),
    cycle,
  ])[0] as { max_units?: number } | undefined;
  if (!cap) return false;
  return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);
}

/**
 * **交卷那个工具。答案写在入参里。**
 *
 * 它干两件事：把答案交上来，同时说一声「我做完了」—— 于是流转提前拐到交卷站。
 *
 * **答案在入参里，不从它说的话里解析。** 早先那一版不收参数，交上去的是它在交卷站
 * 说的那段话，还带一层从别的工具调用里翻 `answer` 字段的兜底。两层都是猜：它可能
 * 说三段话、每段里都有一个式子，挑哪一段都是猜，而猜错的表现是「答案明明写对了
 * 却判 0」—— 那种最难查，因为看日志它确实答对了。
 *
 * 参数表跟着 G 走（`objective.params`）：内核把 G 包装成 `verify`，交卷这一步内部
 * 问的又是同一个 G，两处要的东西当然一模一样。
 *
 * 不调它也会走到交卷站（干活那几站的额度用完）。调它的意义是**提前**：早点交，
 * 判 0 之后还剩着预算，够开个新节点再来一次。实测赢的那几道走的都是这条路。
 *
 * ## 跟 `verify` 的分工
 *
 * `verify` 是**验证**：干活途中拿一份候选去问「这样行不行」，随时能问、能问多次。
 * `submit` 是**交卷**：这件事我做完了，判这一份。两个时刻，两件事。
 *
 * 这道题有没有 G，不改这个工具的形状 —— 改的是**交卷站上多不多做一步**：
 * 有 G 就在那儿判一次，没有就直接收工。
 */
const SUBMIT_TOOL = {
  name: SUBMIT,
  does:
    "Hand the work in: the answer passed here is what gets graded, exactly as written. Text that is not " +
    "passed here is not read as an answer.",
  // **参数表跟 G 走**（`objective.params`）。内核把 G 包装成 `verify`，交卷这一步
  // 内部问的又是同一个 G —— 两处要的东西当然一模一样。抄成两份字面量的话，G 哪天
  // 多一个字段就只会改到一边，而那不报错：只表现为模型照着一边的说明填，另一边
  // 收到的少一样。
  params: CANDIDATE,
  output: { type: "object", properties: { handingIn: { type: "boolean" } } },
  prompt:
    "At the hand-in step no other tool is attached. The hand-in step is reached on its own once the working " +
    "budget runs out.",
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
      // 哪几格算这一个节点的 —— `node` 那一列说了算。
      const here_node = Number(me.node);
      const sameNode = (u: number) => nodes.some((n) => Number(n.unit) === u && Number(n.node) === here_node);
      const handedIn = submitted(db, inst, a.unit, sameNode) !== null;
      const spoke = r.kind === "prompt" && spokenAt(a.result).trim() !== "";

      // **拐去交卷是节点级的规矩，而这条规矩写在表上。** 每一站的 `next` 里都有
      // 交卷（`withSubmit` 补的），所以这儿平推过去就行 —— 表说得出的边，才是
      // 内核准许走的边。自己带父指针绕过白名单也能走通，但那样表上看不出这条边。
      const toSubmit = { to: SUBMIT } satisfies Said;

      // 它自己说完了 / 它按了交卷 —— 提前拐过去。
      if (handedIn || spoke) return toSubmit;

      // 干活那几站的额度花完了 —— 该交卷了。**这一条不看它想不想交。**
      const to = a.next.find((c) => c !== SUBMIT) ?? null;
      if (to === null || full(db, a, nodes, to, Number(me.node))) return toSubmit;

      // 还有额度：按候选往下走一格，从当前这一行接。
      return { to } satisfies Said;
    }

    // ── 交卷站 ────────────────────────────────────────────────────────────
    //
    // 交的就是这一站说的那段话。没有 G 的题到这儿就是收工；有 G 的题**在这儿多做
    // 一步**：判一次。「有没有验证过」不改交卷这件事的形状，只改这一步跑不跑得成。
    let status = "reached";
    if (sealed.has(task)) {
      // **交的是那次调用里的那一份，不解析它说了什么。**
      //
      // 上一版交的是「它在交卷站说的那段话」，还带一层从别的工具调用里翻 `answer`
      // 字段的兜底。两层都是猜：它可能说三段话、每段里都有一个式子，挑哪一段都是猜，
      // 而猜错的表现是「答案明明写对了却判 0」—— 那种最难查，因为看日志它确实答对了。
      //
      // 现在只有一条路：调一次 `submit`，把答案放进去。没调 = 什么都没交。
      // 哪几格算这一个节点的 —— `node` 那一列说了算。
      const here_node = Number(me.node);
      const sameNode = (u: number) => nodes.some((n) => Number(n.unit) === u && Number(n.node) === here_node);
      const said = submitted(db, inst, a.unit, sameNode);
      // **什么都没交。** 这一站只能干一件事，而它没干 —— 没得判，这个节点到此为止。
      //
      // 「交了一份错的」和「什么都没交」不是一回事，所以话要说清楚：前者的判决里带着
      // why，下一个节点看得见、改得动；后者只有这一句，而它说的是「你那一步没做」。
      if (said === null) {
        if (inst) {
          deliverVerdict(db, {
            agent: inst.agent,
            instance: inst.instance,
            unit: a.unit,
            name: VERIFY,
            input: { task, at: `${here}#${a.unit}` },
            value: { pass: 0, why: "nothing was handed in - this step takes an answer and none was given" },
          });
        }
        status = "dead_failed";
      } else {
        const g = sealed.open(task)!;

      // **验过就不必再判一次。** `verify` 是干活途中的验证，交卷是这一刻的提交；
      // 两个时刻，但问的是同一个 G。它刚验过的正是这一份的话，那次判决就是这一次
      // 的答案 —— 再打一遍判卷台只是多花一次钱，还多一次抖动的机会。
      const had = g.reuse === "text" ? verdictFor(db, inst, said) : null;
      // **递出去的是挖出来的那一份，不是原始 result。** 原样递的话，G 那一侧
      // 拿到的是 `{text, calls}` 整坨 JSON —— 上面那几行把答案挖出来就白挖了。
      // 形状跟收尾那一路对齐（`main.ts`：`result: {body}`），一个 G 脚本两处都能用。
      const v = had ?? (await evaluate(g, reg, candidateInput(a.task, said, a.chain)));

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
          name: VERIFY,
          input: { task, at: `${here}#${a.unit}` },
          // **`why` 一起给。** 只给 0/1 的话，模型只知道错了，不知道错在哪 ——
          // 那跟不给差不多，它下一条分支多半原样再来一遍。
          value: { pass: v.pass, valid: "valid" in v ? v.valid : true, outcome: "outcome" in v ? v.outcome : (v.pass === 1 ? "passed" : "rejected"), why: v.why, note: v.note, ...(had ? { reused: true } : {}) },
        });
      }

        if (v.pass !== 1) status = "dead_failed";
      }
    }

    // 判 1 = 这道题做成了，树到此为止。
    if (status === "reached") return { to: null, status } satisfies Said;

    // ── 判 0：换下一个节点再试一次 ────────────────────────────────────────
    //
    // **新节点挂在收口这一行底下。** 节点号是这么长的：
    //
    //   node(新行) = node(父) + (父.status 非空 ? 1 : 0)
    //
    // 收口那一行有终止状态，所以它的孩子就是下一个节点的头 —— 那一个节点自己
    // 有一份新的额度。走回退那一支的话，新行挂到的是一个**没有**终止状态的祖先
    // 底下，node 不涨、预算不重置，「换条路」就只是同一个节点里接着走。
    //
    // 去哪一站由表说了算（`submit.next` = 动作阶段）。
    //
    // 「一道题能试几个节点」是 `max_dead_siblings` 那根轴 —— 数的是**判死过的
    // 节点**，不是行：一个节点判死一次，不该按它有几行算成几次。
    {
      const tried = new Set(
        nodes.filter((n) => n.status !== null && DEAD.has(n.status)).map((n) => Number(n.node)),
      ).size;
      if (tried >= Number(a.task.max_dead_siblings ?? 3)) return { to: null, status } satisfies Said;
      const on = a.next.find((c) => c !== SUBMIT) ?? null;
      if (on !== null) return { to: on, status } satisfies Said;
      return { to: null, status } satisfies Said;
    }

    // 判 0 往下走的是**已经写好的那一套**：交卷站不开自己的兄弟（再交一遍同一份
    // 没意义），于是走回退那一支 —— `to: parent.cycle` 就是那个动作阶段，挂在
    // 祖父底下，正好是死掉那个动作阶段的兄弟。这就是「下一个节点的动作阶段」。
    //
    // 我一度在这儿加过一句「往前接一格」，那是错的：不带 `from_cycle` 的话新行
    // 挂在**死掉的交卷行**底下，树越长越深却一个分叉都没有。

    // ── 底下原来还有一段「开兄弟 / 回退」，删了 ──────────────────────────
    //
    // 那一套是给「干活的站被判死」准备的：在同一个父底下开个兄弟换条路，
    // 试够了就往上爬一层。可判决只在交卷站出，干活的站一个 status 都不产 ——
    // 于是那一段永远走不到。
    //
    // 换节点这件事上面已经做完了：新节点挂在收口那一行底下，node 自然涨一格，
    // 额度也就重置了。留着那段死代码只会让人以为树还有另一套长法。
  });

  // **交卷那个工具跟这套机制一起装上。** 它属于机制，不属于某一份声明 ——
  // 条件是「这一站的推断函数是不是走树的那个」，跟 `task_tree` / `node_load` 同一条。
  reg.register(db, `fn:tool.${SUBMIT_TOOL.name}`, SUBMIT_TOOL.expectMs, async () => ({ handingIn: true }));
  run(
    db,
    `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
     values (?, ?, ?, ?, ?, ?, 0, 0, null, 1, 'receipt')
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
