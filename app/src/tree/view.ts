/**
 * Two tree introspection tools: **view the whole tree** and **read a node**.
 *
 * ## Why tools rather than automatic context injection?
 *
 * Context normally includes only **one chain**, the direct ancestors from root to parent. Sibling branches and nodes on other chains are **excluded by default**, deliberately: opening a sibling means trying another route. Directly injecting another branch's words would contaminate both attempts and make δ dependent.
 *
 * Excluded by default does not mean invisible. As the old repository said, **shared progress means visibility, not direct inheritance**. Provide tools for retrieval on demand. Dead branches often record pitfalls; retrieve them to avoid those mistakes, not to copy them.
 *
 * ## A node spans several cycles
 *
 * **It is not one row.** An attempt starts at a reasoning station, alternates with tool execution, and closes at a submission station. That entire stretch is one node:
 *
 * ```
 *   ask#1 → act#2 → ask#3 → … → act#12 → submit#13
 *   └──────────────── one node ────────────────┘
 * ```
 *
 * Both tools therefore operate on **nodes**, not rows: `task_tree` lists nodes; `node_load` reads the combined content of an entire node.
 *
 * The old row-based reader was wrong: an action station returned blank because it runs tools without speaking. That did not mean the attempt said nothing; the query used the wrong granularity.
 *
 * ## Each node also carries plain text
 *
 * `task_tree` includes a `summary` for each node, combining its message slots into plain text after removing **system-side content** (tool conventions, skills, kernel bookkeeping), **chain of thought**, and **written content** (truncated by line; see `WROTE_LINES`).
 *
 * Include this in the listing because **seeing what another branch did should not require an extra call**. Status alone would require `node_load` on every node to understand which paths failed. Use `node_load` when original text is needed.
 *
 * ## Why dispatch by mode?
 *
 * Only branching mechanisms need these tools. A single-chain mechanism already inherits context directly, so `task_tree` would only distract it. **Dispatch through `trigger`, not hard-coded branches**, based on whether this station uses the tree inference function (`cycle.infer`).
 */

import type { Conn } from "../H2H/db.ts";
import { SUBMIT } from "./dfs.ts";
import { all, run } from "../H2H/db.ts";
import { bodiesAt, readyLevels, type Level } from "../msg/press.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";
import { sendable } from "../llm/index.ts";
import { sentAsIn } from "../msg/deliver.ts";
import { whereAmI } from "../tasks/where.ts";

type Row = Record<string, unknown>;

/** The input passed from the kernel to a tool (see `runOne` in `tools/unit.ts`). */
interface At {
  args?: { node?: number; level?: string };
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

/** Group by node. **Node numbers are stored on rows** (`task_{mode}.node`), not inferred. */
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

/**
 * A node summary: **read the third-level version directly from the table**.
 *
 * Previously this function recompressed content itself. Two independent compression paths could give the model different content in `task_tree` and its own context, both plausible and error-free. Compression now happens only when a node closes (`msg/press.ts`); this function retrieves the strongest level.
 *
 * Return an empty string for an uncompressed node. An active node is in this state: its messages are still in use and it should not have a summary yet.
 *
 * **Emit each passage only once**. Several slots commonly share one passage (multiple `press` rows reference one subtable row); repeating it per slot would add back all the saved content.
 */
function summaryOf(db: Conn, sub: string, task: string, units: number[]): string {
  return [...bodiesAt(db, sub, task, units, "l3").values()].join("\n");
}

const TREE_TOOL = {
  name: "task_tree",
  does:
    "This task's context is a tree of attempts, and the conversation carries only the chain from the root down to the current attempt. " +
    "This lists every node of that tree, the current chain and the other branches alike. One node is a whole attempt: it spans the thinking, the tool work and the hand-in that closes it. " +
    "Takes no arguments. Returns task, and nodes - for each: node (its number), at (the cycles it spans), status, done, mine (true for the attempt running now), and summary - empty on that one, since its messages are already in this conversation. " +
    "summary is that node at the heaviest of the three compression levels - the same text the conversation itself would carry if it had to be squeezed that far. " +
    "It is empty for a node that has not been compressed, which is any node still being worked on. node_load reads a node at whatever level is asked for, and untouched by default. " +
    "What either tool hands back is not carried along: once this attempt closes it is dropped from the conversation at every level of compression, since it is a copy of what the tree already holds. Ask again when you need it - that is one call.",
  params: { type: "object", properties: {} },
  output: {
    type: "object",
    properties: {
      task: { type: "string" },
      nodes: {
        type: "array",
        items: {
          type: "object",
          properties: {
            node: { type: "integer", description: "Node number, as node_load takes it" },
            at: { type: "string", description: "The cycles this node spans, e.g. ask#1 > act#2 > submit#3" },
            status: { type: "string", description: "Empty while the attempt is still open, reached once its hand-in was accepted, dead_* once it was ruled out" },
            done: { type: "boolean" },
            mine: { type: "boolean", description: "True for the attempt running now" },
            summary: { type: "string", description: "That node's messages as plain text, compressed as the description says. Empty on the attempt running now - those messages are already in this conversation" },
          },
        },
      },
    },
  },
  prompt: "",
  expectMs: 10_000,
};

const NODE_TOOL = {
  name: "node_load",
  does:
    "Read one node of this task's tree, branches outside the current context included. " +
    "Takes node, a number from task_tree, and optionally level - l1, l2 or l3 - to get that node compressed to that degree instead: l1 keeps nearly everything, l3 is what task_tree already shows. Left out, the node comes back untouched. " +
    "Returns node, at (the cycles it spans), status, and said - the prompts of that attempt, its own text with the names of the tools it called, and every verdict its hand-in got. Tool results other than verdicts are not in it. " +
    "What either tool hands back is not carried along: once this attempt closes it is dropped from the conversation at every level of compression, since it is a copy of what the tree already holds. Ask again when you need it - that is one call.",
  params: {
    type: "object",
    properties: {
      node: { type: "integer", description: "Which node to read, as numbered by task_tree" },
      level: {
        type: "string",
        description: "l1, l2 or l3 to get it compressed to that degree. Left out, it comes back whole",
      },
    },
    required: ["node"],
  },
  output: {
    type: "object",
    properties: {
      node: { type: "integer" },
      at: { type: "string", description: "The cycles this node spans" },
      status: { type: "string", description: "Empty while the attempt is still open, reached once its hand-in was accepted, dead_* once it was ruled out" },
      said: {
        type: "array",
        description: "In order. kind prompt carries text; kind call carries the model's text and called, the names of the tools it asked for; kind verdict carries what the hand-in got back.",
        items: { type: "object" },
      },
    },
  },
  prompt: "",
  expectMs: 10_000,
};

/**
 * Register both tools.
 *
 * `treeInfer` is the handle name for the tree inference function. Conditions reference it, so **switching tree strategies requires only changing this name**, not the code.
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

    // **List nodes, not rows.** A node is a complete attempt: start at a reasoning station,
    // alternate with tools, and close at the row that reaches a terminal state.
    return {
      task: at.task,
      nodes: byNode(units).map((g) => {
        const end = g[g.length - 1];
        const mine = g.some((u) => Number(u.unit) === Number(a.unit));
        return {
          node: Number(g[0].node),
          at: g.map((u) => `${u.cycle}#${u.unit}`).join(" > "),
          // The closing row holds the verdict: reached = the attempt succeeded; dead_* = it was judged unsuccessful;
          // empty = no submission yet.
          status: end.status,
          done: g.every((u) => Number(u.done) === 1),
          mine,
          // **Do not summarize the active node**: its station messages are already in context.
          // Copying them would include the same content twice, with another copy on every `task_tree` call.
          summary: mine ? "" : summaryOf(db, at.sub, at.task, g.map((u) => Number(u.unit))),
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

    // **Read an entire node.** The old row-based version returned blank for an action-station id,
    // because that station runs tools without speaking. It was the wrong query granularity, not an absence of content.
    const units = all(
      db,
      `select cycle, unit, node, status from "${at.sub}" where task = ? and node = ? order by unit`,
      [at.task, want],
    ) as unknown as Unit[];
    if (units.length === 0) return { node: want, said: [], note: "there is no such node in this task" };

    // **Return the requested level, or original text if unspecified.** The three compressed versions were computed and stored at node closure (`msg/press.ts`); retrieve them here.
    // If absent, the node has not closed and no compressed version exists to return.
    const level = String(a.args?.level ?? "").trim();
    if (level) {
      const levels = readyLevels(db);
      if (!(levels as readonly string[]).includes(level)) {
        return { error: `level is ${level}; it can be ${levels.join(", ")}, or left out for the node untouched` };
      }
      const body = [...bodiesAt(db, at.sub, at.task, units.map((u) => Number(u.unit)), level as Level).values()].join("\n");
      const end = units[units.length - 1];
      return {
        node: want,
        at: units.map((u) => `${u.cycle}#${u.unit}`).join(" > "),
        status: end.status,
        level,
        said: body ? [{ kind: "pressed", text: body }] : [],
        ...(body ? {} : { note: "this node has not been compressed - it is still being worked on" }),
      };
    }

    const t = tableNameOf("agent_{}_msg", String(a.agent));
    const holes = units.map(() => "?").join(",");
    // **The model's own words** and **G's verdicts**. Exclude another branch's skills, kernel bookkeeping, and ordinary tool results: those are its working materials, not its conclusions.
    //
    // Verdicts are mandatory. If `task_tree` reports dead_failed but reading the node cannot reveal why, the information is barely useful; the next attempt will likely repeat the same path.
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
        // For calls, omit arguments and retain only what the model intended to do; arguments are details of that attempt.
        said.push({ at: r.unit, kind: "call", text: v.text ?? "", called: (v.calls ?? []).map((c) => c.name) });
      } else if (v.name === "verify") {
        said.push({ at: r.unit, kind: "verdict", verdict: v.value });
      }
      // Skip other tool results.
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
      `insert into tool (name, identity, does, params, output, prompt, concurrent, system, access, usable, gives)
       values (?, ?, ?, ?, ?, ?, 0, 0, null, 1, 'recall')
       on conflict(name) do update set
         identity = excluded.identity, does = excluded.does, params = excluded.params,
         output = excluded.output, prompt = excluded.prompt, system = excluded.system,
         gives = excluded.gives`,
      [t.name, `fn:tool.${t.name}`, t.does, JSON.stringify(t.params), JSON.stringify(t.output), t.prompt],
    );
    // **Not system tools**: dispatch by mode, only to tree mechanisms.
    // Conditions enter `trigger`, using the same table and matching rules as other tools.
    run(db, `delete from trigger where owner_kind = 'tool' and owner = ?`, [t.name]);
    run(
      db,
      `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values ('tool', ?, 0, 'cycle', 'infer', 'eq', ?)`,
      [t.name, treeInfer],
    );
  // **Do not offer tools at the submission station.** Only action stations execute tools (empty `api_mode`, using `agent.unit`). A submission station and its successor are both model stations, so nobody will execute tools requested there. Such calls hang until completion inserts a "not executed" result.
  //
  // Observed behavior: the model called `submit` at the submission station and received "not executed" because nobody supplied a result. Submission needs no tool in the first place: the model's words are the submission.
  //
  // This condition belongs to the same group as the earlier one (AND within a group): match the original condition **and** require a non-submission station.
    run(
      db,
      `insert into trigger (owner_kind, owner, "group", dim, "key", op, value) values ('tool', ?, 0, 'cycle', 'cycle', 'ne', ?)`,
      [t.name, SUBMIT],
    );
    names.push(t.name);
  }
  return names;
}
