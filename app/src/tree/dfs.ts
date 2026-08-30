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
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { deliverVerdict } from "../msg/deliver.ts";
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

function nodesOf(db: Conn, sub: string, task: string): Node[] {
  return all(db, `select cycle, unit, from_cycle, from_unit, status, done from "${sub}" where task = ?`, [
    task,
  ]) as unknown as Node[];
}

/** 同一个父底下的兄弟（不含自己）。 */
function siblings(nodes: Node[], me: Node): Node[] {
  return nodes.filter(
    (n) => !(n.cycle === me.cycle && n.unit === me.unit) && n.from_cycle === me.from_cycle && n.from_unit === me.from_unit,
  );
}

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

    // ── 这一步到底算成了没有 ──────────────────────────────────────────────
    //
    // 先看自评（ĝ）：**只有模型自己说出一段话（`prompt`）才算自称到终点**，
    // 别的都是半路。
    //
    // 原先写的是「`call` 才算没完，其余算到了」—— 那条把跑工具那一站也算成了
    // 终点：它回的是一行记账（`inject`，说这一站跑了哪几个工具），不是答复。
    // 于是工具跑完就收工，模型永远看不到自己那次调用的结果。
    const r = (a.result ?? {}) as { kind?: string };
    let status = r.kind === "prompt" ? "reached" : "";

    // 自称到终点了 —— **这一刻才调 G 复核**。它说 0 就是「以为到了其实没到」，
    // 判死开兄弟。不许节点自己说了算，这就是 verifier-guided 的全部意思。
    if (status === "reached" && sealed.has(task)) {
      const g = sealed.open(task)!;
      const v = await evaluate(g, reg, { task: a.task, chain: a.chain, result: a.result });

      // **判决要落进上下文**，不能只进日志。以前只写 `task.result`，于是判死开兄弟
      // 是盲重试：新分支知道要换条路，不知道上一条错在哪。投成「一次带结果的工具
      // 调用」—— 它是外部的、这一次的观测，正好是 tool 结果的语义。
      //
      // 落在**被判的这一站**上：兄弟默认看不见它（那是故意的），要看得自己
      // `node_load` 去取 —— 「进度共享是能看、不是直接继承」。
      const inst = all(db, `select agent, instance from "${a.sub}" where task = ? and cycle = ? and unit = ?`, [
        task,
        here,
        a.unit,
      ])[0] as { agent: string; instance: string } | undefined;
      if (inst) {
        deliverVerdict(db, {
          agent: inst.agent,
          instance: inst.instance,
          unit: a.unit,
          name: "verify",
          input: { task, at: `${here}#${a.unit}` },
          // **`why` 一起给。** 只给 0/1 的话，模型只知道错了，不知道错在哪 ——
          // 那跟不给差不多，它下一条分支多半原样再来一遍。
          value: { pass: v.pass, why: v.why },
        });
      }

      if (v.pass !== 1) status = "dead_failed";
    }

    // 还在跑：按候选往下走一格，从当前这一行接。
    if (!status) return { to: a.next[0] ?? null } satisfies Said;
    if (status === "reached") return { to: null, status } satisfies Said;

    // ── 判死了 ────────────────────────────────────────────────────────────
    const maxBranches = Number(a.task.max_branches ?? 2);
    const maxDead = Number(a.task.max_dead_siblings ?? 3);
    const sibs = siblings(nodes, me);

    // 并发闸：同一个父底下没干完的到了上限就不再开。这是「同时几条」。
    const busy = sibs.filter((n) => !n.done).length;
    if (busy >= maxBranches) return { to: null, status } satisfies Said;

    // 判死闸：这一层试过的方向够多了 → 回退到更上层。
    const dead = sibs.filter((n) => n.status !== null && DEAD.has(n.status)).length + 1;
    if (dead < maxDead) {
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

  return ["fn:infer.dfs"];
}
