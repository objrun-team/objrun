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
 * ## 一个节点是好几个周期拼起来的
 *
 * **不是一行。** 一次尝试从思考站起头，中间来回跑工具，最后落在交卷站上收口 ——
 * 这一整段才是一个节点：
 *
 * ```
 *   ask#1 → act#2 → ask#3 → … → act#12 → submit#13
 *   └──────────────── 一个节点 ────────────────┘
 * ```
 *
 * 所以这两个工具都按**节点**说话，不按行：`task_tree` 列的是节点，
 * `node_load` 读的是一整个节点拼起来的内容。
 *
 * 按行读的那一版是错的：读到一个动作站就是一片空白（那一站不说话，只跑工具），
 * 而那不是「它没说什么」，是问错了粒度。
 *
 * ## 为什么按 mode 分发
 *
 * 只有会分叉的机制才需要这两个。一条道走到黑的单链机制，上下文本来就是直接继承的，
 * 给它一个 `task_tree` 是纯粹的干扰。**分发靠 `trigger`，不靠代码里写死** ——
 * 条件是「这一站的推断函数是不是走树的那个」（`cycle.infer`）。
 */

import type { Conn } from "../H2H/db.ts";
import { SUBMIT } from "./dfs.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";
import { whereAmI } from "../tasks/where.ts";

type Row = Record<string, unknown>;

/** 内核递给工具的那一份（见 `tools/unit.ts` 的 `runOne`）。 */
interface At {
  args?: { node?: number };
  agent?: string;
  instance?: string;
  unit?: number;
  task?: Row;
  sub?: string;
}

interface Unit {
  cycle: string;
  unit: number;
  node: number;
  from_cycle: string | null;
  from_unit: number | null;
  status: string | null;
  done: number;
}

/** 按节点分组。**节点号是记在行上的**（`task_{mode}.node`），不用推。 */
function byNode(units: Unit[]): Unit[][] {
  const g = new Map<number, Unit[]>();
  for (const u of units) {
    const k = Number(u.node);
    const got = g.get(k) ?? [];
    got.push(u);
    g.set(k, got);
  }
  return [...g.entries()].sort((a, b) => a[0] - b[0]).map(([, v]) => v.sort((x, y) => x.unit - y.unit));
}

const TREE_TOOL = {
  name: "task_tree",
  does: "See the whole tree for this task: which attempts were made, which were ruled out, how far each got. One node is a whole attempt - it runs from thinking, through the tool work, to the hand-in that closes it. What a node actually said is NOT here: use node_load to read one.",
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
  does: "Read a whole attempt: everything the model said across that node, together with the verdict its hand-in got. Node numbers come from task_tree. A ruled-out attempt is a trap someone already stepped in - read it to avoid repeating it, not to copy it.",
  params: {
    type: "object",
    properties: { node: { type: "integer", description: "Which attempt to read, as numbered by task_tree" } },
    required: ["node"],
  },
  output: { type: "object", properties: { node: { type: "integer" }, at: { type: "string" }, status: { type: "string" }, said: { type: "array" } } },
  prompt:
    "node_load reads one whole earlier attempt - everything said across it, plus the verdict its hand-in got. " +
    "A ruled-out attempt is a trap someone already stepped in: read it to avoid repeating it, not to copy it.",
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
    const units = all(
      db,
      `select cycle, unit, node, from_cycle, from_unit, status, done from "${at.sub}" where task = ? order by unit`,
      [at.task],
    ) as unknown as Unit[];

    // **列的是节点，不是行。** 一个节点是一次完整的尝试：从思考站起头，来回跑
    // 工具，落在拿到终止状态的那一行上收口。
    return {
      task: at.task,
      nodes: byNode(units).map((g) => {
        const end = g[g.length - 1];
        return {
          node: Number(g[0].node),
          at: g.map((u) => `${u.cycle}#${u.unit}`).join(" > "),
          // 判决落在收口那一行上：reached = 这次尝试成了，dead_* = 被判不成，
          // 空 = 还没交到卷。
          status: end.status,
          done: g.every((u) => Number(u.done) === 1),
          mine: g.some((u) => Number(u.unit) === Number(a.unit)),
        };
      }),
    };
  });

  reg.register(db, `fn:tool.${NODE_TOOL.name}`, NODE_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as At;
    const want = Number(a.args?.node);
    if (!Number.isInteger(want)) return { error: "node is required - take it from task_tree" };
    const at = whereAmI(db, String(a.instance));
    if (!at) return { error: `cannot tell which task ${String(a.instance)} belongs to` };

    // **读的是一整个节点。** 按行读的那一版给一个动作站的号就回一片空白：
    // 那一站不说话，只跑工具 —— 而那不是「它没说什么」，是问错了粒度。
    const units = all(
      db,
      `select cycle, unit, node, status from "${at.sub}" where task = ? and node = ? order by unit`,
      [at.task, want],
    ) as unknown as Unit[];
    if (units.length === 0) return { node: want, said: [], note: "there is no such node in this task" };

    const t = tableNameOf("agent_{}_msg", String(a.agent));
    const holes = units.map(() => "?").join(",");
    // **模型自己说过的话** + **G 判过什么**。别的分支的 skill、内核记账、普通工具
    // 的返回不给 —— 那些是那一段的家当，不是它的结论。
    //
    // 判决必须给：`task_tree` 报了「这次尝试 dead_failed」，来读却读不到死因的话，
    // 那跟不给差不多 —— 下一次尝试多半原样再来一遍。
    const rows = all(
      db,
      `select unit, seq, kind, body from "${t}"
        where instance = ? and unit in (${holes}) and kind in ('prompt','call','tool')
        order by unit, seq`,
      [String(a.instance), ...units.map((u) => u.unit)],
    );
    const said: Row[] = [];
    for (const r of rows) {
      if (r.kind === "prompt") {
        if (String(r.body ?? "").trim()) said.push({ at: r.unit, kind: "prompt", text: r.body });
        continue;
      }
      let v: { text?: string; calls?: { name?: string }[]; name?: string; value?: unknown };
      try {
        v = JSON.parse(String(r.body)) as typeof v;
      } catch {
        continue;
      }
      if (r.kind === "call") {
        // 调用本身不给参数，只给「它当时想干什么」—— 参数是那一段的细节。
        said.push({ at: r.unit, kind: "call", text: v.text ?? "", called: (v.calls ?? []).map((c) => c.name) });
      } else if (v.name === "verify") {
        said.push({ at: r.unit, kind: "verdict", verdict: v.value });
      }
      // 别的工具返回跳过。
    }
    const end = units[units.length - 1];
    return {
      node: want,
      at: units.map((u) => `${u.cycle}#${u.unit}`).join(" > "),
      status: end.status,
      said,
      ...(said.length === 0 ? { note: "that attempt said nothing" } : {}),
    };
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
  // **交卷站不摆工具。** 跑工具的只有动作站（`api_mode` 为空、走 `agent.unit` 的
  // 那个），而交卷站是模型站、它的下一站也是模型站 —— 模型在那儿请求的任何工具
  // 都没有人会去跑，那次调用会一直挂着，直到补齐给它写一条「没跑成」。
  //
  // 实测的样子：模型在交卷站调 `submit`，拿回一句「没跑成」——它调了工具，没人
  // 给结果。而交卷本来就不需要工具：交的是它说的话。
  //
  // 这一条跟上面那条同一组（组内是 AND），所以是「命中原来那条**并且**这一站
  // 不是交卷站」。
    run(
      db,
      `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values ('tool', ?, 0, 'cycle', 'cycle', 'ne', ?)`,
      [t.name, SUBMIT],
    );
    names.push(t.name);
  }
  return names;
}
