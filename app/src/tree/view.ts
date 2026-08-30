/**
 * 树自省的那两个工具：**看全树**，和**读某个节点**。
 *
 * ## 为什么是工具，不是默认塞进上下文
 *
 * 上下文默认只接**单链**（直系祖先 root→父）。兄弟分支、跨链节点**默认不接入** ——
 * 那是故意的：开兄弟正是为了换一条路走，把另一条分支的话直接塞进来，等于让两次
 * 尝试互相污染，δ 就不独立了。
 *
 * 但「不默认接入」不等于「看不见」。老仓库那句话是：**进度共享是能看、不是直接继承**。
 * 所以给工具，让它按需去取：判死的那几条多半是踩过的坑，接进来是为了绕开，不是为了抄。
 *
 * ## 为什么按 mode 分发
 *
 * 只有会分叉的机制才需要这两个。一条道走到黑的单链机制，上下文本来就是直接继承的，
 * 给它一个 `task_tree` 是纯粹的干扰。**分发靠 `trigger`，不靠代码里写死** ——
 * 条件是「这一站的推断函数是不是走树的那个」（`cycle.infer`）。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";
import { whereAmI } from "../tasks/where.ts";

type Row = Record<string, unknown>;

/** 内核递给工具的那一份（见 `tools/unit.ts` 的 `runOne`）。 */
interface At {
  args?: { unit?: number };
  agent?: string;
  instance?: string;
  unit?: number;
  task?: Row;
  sub?: string;
}

const TREE_TOOL = {
  name: "task_tree",
  does: "See the whole tree for this task: which paths were tried, which were ruled out, how far each got. What other branches actually said is NOT here - use node_load to read one.",
  params: { type: "object", properties: {} },
  output: {
    type: "object",
    properties: {
      task: { type: "string" },
      here: { type: "string" },
      nodes: { type: "array", items: { type: "object" } },
    },
  },
  prompt:
    "When a branch of yours was ruled out, task_tree shows which paths have already been tried and how far " +
    "each got. Read it before trying a direction again.",
  expectMs: 10_000,
};

const NODE_TOOL = {
  name: "node_load",
  does: "Read what one station said (unit number comes from task_tree). This is another branch content: the ruled-out ones are usually traps already stepped in - read them to avoid repeating, not to copy.",
  params: {
    type: "object",
    properties: { unit: { type: "integer", description: "Which station, as numbered by task_tree" } },
    required: ["unit"],
  },
  output: { type: "object", properties: { unit: { type: "integer" }, said: { type: "array" } } },
  prompt:
    "node_load reads what one earlier station said, together with the verdict it got. A ruled-out branch is " +
    "a trap someone already stepped in - read it to avoid repeating it, not to copy it.",
  expectMs: 10_000,
};

/**
 * 把这两个工具注册进去。
 *
 * `treeInfer` 是「走树的那个推断函数」的句柄名 —— 条件按它写，所以**换一种树策略
 * 只要换这个名字**，不用改代码。
 */
export function registerTreeView(db: Conn, reg: Registry, treeInfer: string): string[] {
  reg.register(db, `fn:tool.${TREE_TOOL.name}`, TREE_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as At;
    const at = whereAmI(db, String(a.instance));
    if (!at) return { error: `cannot tell which task ${String(a.instance)} belongs to` };
    const nodes = all(
      db,
      `select cycle, unit, from_cycle, from_unit, status, done from "${at.sub}" where task = ? order by unit`,
      [at.task],
    );
    return {
      task: at.task,
      here: `#${String(a.unit)}`,
      nodes: nodes.map((n) => ({
        unit: n.unit,
        at: `${String(n.cycle)}#${String(n.unit)}`,
        from: n.from_cycle === null ? null : `${String(n.from_cycle)}#${String(n.from_unit)}`,
        status: n.status,
        done: Number(n.done) === 1,
        mine: Number(n.unit) === Number(a.unit),
      })),
    };
  });

  reg.register(db, `fn:tool.${NODE_TOOL.name}`, NODE_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as At;
    const want = Number(a.args?.unit);
    if (!Number.isInteger(want)) return { error: "unit is required - take it from task_tree" };
    const t = tableNameOf("agent_{}_msg", String(a.agent));
    // **模型自己说过的话** + **G 判过什么**。别人那条分支的 skill、内核记账、
    // 普通工具的返回不给 —— 那些是那一站的家当，不是它的结论。
    //
    // 判决必须给：`task_tree` 报了「这一站 dead_failed」，来读却读不到死因的话，
    // 那跟不给差不多 —— 它下一条分支多半原样再来一遍。
    const rows = all(
      db,
      `select seq, kind, body from "${t}" where instance = ? and unit = ? and kind in ('prompt','call','tool') order by seq`,
      [String(a.instance), want],
    );
    if (rows.length === 0) return { unit: want, said: [], note: "that station said nothing, or does not exist" };
    const said: Row[] = [];
    for (const r of rows) {
      if (r.kind === "prompt") {
        said.push({ kind: "prompt", text: r.body });
        continue;
      }
      let v: { text?: string; calls?: { name?: string }[]; name?: string; value?: unknown };
      try {
        v = JSON.parse(String(r.body)) as typeof v;
      } catch {
        continue;
      }
      if (r.kind === "call") {
        // 调用本身不给参数，只给「它当时想干什么」—— 参数是那条分支的细节。
        said.push({ kind: "call", text: v.text ?? "", called: (v.calls ?? []).map((c) => c.name) });
      } else if (v.name === "verify") {
        said.push({ kind: "verdict", verdict: v.value });
      }
      // 别的工具返回跳过。
    }
    return { unit: want, said };
  });

  const names: string[] = [];
  for (const t of [TREE_TOOL, NODE_TOOL]) {
    run(
      db,
      `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable)
       values (?, ?, ?, ?, ?, ?, 0, 0, null, 1)
       on conflict(name) do update set
         identity = excluded.identity, does = excluded.does, params = excluded.params,
         output = excluded.output, prompt = excluded.prompt, system = excluded.system`,
      [t.name, `fn:tool.${t.name}`, t.does, JSON.stringify(t.params), JSON.stringify(t.output), t.prompt],
    );
    // **不是 system 工具** —— 按 mode 分发：只有走树的那种机制才挂得上。
    // 条件落进 `trigger`，跟别的工具走同一张表、同一套判据。
    run(db, `delete from trigger where owner_kind = 'tool' and owner = ?`, [t.name]);
    run(
      db,
      `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values ('tool', ?, 0, 'cycle', 'infer', 'eq', ?)`,
      [t.name, treeInfer],
    );
    names.push(t.name);
  }
  return names;
}
