/**
 * 触发条件的两件工具：**不跑系统就校验**，和**没命中时说清为什么**。
 *
 * 老代码那边写着一句要命的话：
 *
 * > 写错的典型后果是**静默不生效**，跑一遍系统也看不出来。
 *
 * 条件写错了不会报错 —— 那条规则只是永远不触发，而系统照常跑。所以这两件工具
 * 不是「顺手加的调试功能」，它们是这张表能不能用的前提。
 *
 * ## check：不启动系统，把全部条件过一遍
 *
 * 认不得的维度 / 比法、指向不存在的东西、`in` 的值不是一份列表、关键词带空格 ——
 * 这些全是**加载期就能看出来**的错，没有理由留到某个任务真跑到那一步。
 *
 * ## explain：没命中的时候，逐条说清哪一条没过
 *
 * 老代码那边最常见的两个原因都在「候选」之前两步：**你写的词根本没在那段文本里**，
 * 和**维度上根本没有你说的那个属性**。所以 explain 要把「实际取到的是什么」一起
 * 摆出来，而不是只说「没匹配」。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import { compare, DIMS, OPS, pick, type Facts } from "../engine/trigger.ts";

export interface Term {
  owner_kind: string;
  owner: string;
  group: number;
  dim: string;
  key: string;
  op: string;
  value: string;
}

export interface Problem {
  owner_kind: string;
  owner: string;
  group: number;
  why: string;
}

/** 每一类 owner 到底存在不存在，去哪张表问。 */
const OWNER_TABLE: Record<string, { table: string; col: string }> = {
  rule: { table: "rule", col: "identity" },
  tool: { table: "tool", col: "name" },
  skill: { table: "skill", col: "identity" },
};

/** 每个维度上有哪些属性 —— 就是那张表的列。 */
function keysOf(db: Conn, dim: string): string[] {
  const table = dim === "cycle" ? "cycle" : dim === "task" ? "task" : dim === "agent" ? "agent" : "";
  if (!table) return [];
  return (all(db, `pragma table_info("${table}")`) as { name: string }[]).map((r) => r.name);
}

/**
 * 把全部触发条件过一遍。**不跑系统。**
 *
 * 返回问题列表；空 = 全通。
 */
export function check(db: Conn): Problem[] {
  const out: Problem[] = [];
  const terms = all(db, `select owner_kind, owner, "group", dim, "key", op, value from trigger`) as unknown as Term[];
  const keys = new Map(DIMS.map((d) => [d as string, keysOf(db, d)]));

  const say = (t: Term, why: string) =>
    out.push({ owner_kind: t.owner_kind, owner: t.owner, group: Number(t.group), why });

  for (const t of terms) {
    // 维度 / 比法：认不得就是永远不触发，而且一个字母的差别看不出来
    if (!(DIMS as readonly string[]).includes(t.dim)) {
      say(t, `不认得的维度 ${t.dim}（认得的是 ${DIMS.join(" / ")}）`);
      continue;
    }
    if (!(OPS as readonly string[]).includes(t.op)) {
      say(t, `不认得的比法 ${t.op}（认得的是 ${OPS.join(" / ")}）`);
      continue;
    }

    // 属性：`chain` 维度不看属性，别的维度得是那张表真有的列
    if (t.dim === "chain") {
      if (t.key.trim() !== "") say(t, `chain 维度不看属性，key 该留空，现在写着 ${t.key}`);
    } else {
      const ks = keys.get(t.dim) ?? [];
      if (!ks.includes(t.key)) {
        say(t, `${t.dim} 上没有 ${t.key} 这一项（有的是 ${ks.join(" / ")}）`);
      }
    }

    // `in` 的值得是一份能读的列表
    if (t.op === "in") {
      try {
        if (!Array.isArray(JSON.parse(t.value))) say(t, `in 的值得是一份列表，现在是 ${t.value}`);
      } catch {
        say(t, `in 的值不是能读的 JSON：${t.value}`);
      }
    }

    // 关键词不许带空格。**有空格说明把几个词写一起了** —— 系统不替你猜要的是
    // 相邻还是有序；拆开，写成同一组的两条。
    if (t.op !== "in" && /\s/.test(t.value) && t.dim !== "task") {
      say(t, `值里带空格：${JSON.stringify(t.value)} —— 拆成同一组的两条，别让系统猜`);
    }

    // owner 指的那个东西存在不存在
    const at = OWNER_TABLE[t.owner_kind];
    if (!at) {
      say(t, `不认得的 owner_kind ${t.owner_kind}（认得的是 ${Object.keys(OWNER_TABLE).join(" / ")}）`);
    } else if (all(db, `select 1 from "${at.table}" where "${at.col}" = ?`, [t.owner]).length === 0) {
      say(t, `${at.table} 表里没有 ${t.owner} —— 这条条件永远不会有人用`);
    }
  }

  // 一个 owner 一条条件都没有 = 从不触发。**这不是错**（系统工具就靠 tool.system），
  // 但值得说一声：多半是忘了写。
  for (const [kind, at] of Object.entries(OWNER_TABLE)) {
    const owners = (all(db, `select "${at.col}" as id from "${at.table}"`) as { id: string }[]).map((r) => r.id);
    for (const id of owners) {
      if (terms.some((t) => t.owner_kind === kind && t.owner === id)) continue;
      if (kind === "tool") {
        const sys = all(db, `select system from tool where name = ?`, [id])[0] as { system: number } | undefined;
        if (sys && Number(sys.system)) continue; // 系统工具不看 trigger，正常
      }
      out.push({ owner_kind: kind, owner: id, group: 0, why: "一条触发条件都没有 —— 它永远不会被挂上" });
    }
  }

  return out;
}

/** 一条条件在这份事实上过没过。 */
export interface Told {
  group: number;
  dim: string;
  key: string;
  op: string;
  value: string;
  /** **实际取到的是什么** —— 最常见的没命中原因就藏在这儿。 */
  got: string;
  hit: boolean;
  error?: string;
}

/**
 * 为什么没命中。
 *
 * 逐条摆出来，**带上实际取到的值** —— 只说「没匹配」的话，人得自己去猜是词写错了
 * 还是那段文本里根本没有。
 */
export function explain(db: Conn, kind: string, owner: string, f: Facts): { fired: boolean; groups: Told[][] } {
  const terms = all(
    db,
    `select owner_kind, owner, "group", dim, "key", op, value from trigger where owner_kind = ? and owner = ? order by "group"`,
    [kind, owner],
  ) as unknown as Term[];

  const byGroup = new Map<number, Term[]>();
  for (const t of terms) {
    const g = Number(t.group);
    byGroup.set(g, [...(byGroup.get(g) ?? []), t]);
  }

  const groups: Told[][] = [];
  let fired = false;
  for (const [g, ts] of [...byGroup].sort((a, b) => a[0] - b[0])) {
    const told: Told[] = ts.map((t) => {
      try {
        const got = pick(f, t.dim, t.key);
        return { group: g, dim: t.dim, key: t.key, op: t.op, value: t.value, got, hit: compare(t.op, got, t.value) };
      } catch (e) {
        return {
          group: g,
          dim: t.dim,
          key: t.key,
          op: t.op,
          value: t.value,
          got: "",
          hit: false,
          error: e instanceof Error ? e.message : String(e),
        };
      }
    });
    groups.push(told);
    if (told.length && told.every((x) => x.hit)) fired = true;
  }
  return { fired, groups };
}

// 取值和比法**直接用 `fire` 那两个函数**，不另写一份 —— 两份会漂，
// 而漂了之后 explain 说的就不是实际发生的事，那比没有 explain 还糟。
