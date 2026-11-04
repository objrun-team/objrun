/**
 * 交卷：**一个工具 + 一站**，随走树那套机制一起装上。
 *
 * ```
 * bun test/integration/submit.ts
 * ```
 *
 * ## 两件事，两个时刻
 *
 * | | 什么时候 | 干什么 |
 * | --- | --- | --- |
 * | `verify` 工具 | 干活途中，随时，可以多次 | 拿一份候选去问 G「这样行不行」 |
 * | `submit` 工具 | 觉得做完了 | **无参**。只是说一声「我交了」，让流转提前拐到交卷站 |
 * | `submit` 那一站 | 流转到这儿 | **交的就是这一站说的那段话**，有 G 就在这儿判一次 |
 *
 * 不调那个工具也会走到交卷站 —— 干活那几站说完话就拐过去。调它的意义只有一个：
 * **提前**。
 *
 * ## 为什么这一站得随机制装，不能让声明自己写
 *
 * 它不是某道题的特性，是**走树这套机制**的特性：判决要判「它交上来的那一份」，
 * 而「交上来」得有个落脚的站。让每份声明自己写一遍的话，写漏一个模式就退回
 * 「内核回头去消息表里猜哪句话像答案」—— 猜是会猜错的，实测拿过开场白、拿过空串。
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** G 被真调了几次 —— 「验过就不再判一遍」靠数它。 */
const graded: unknown[] = [];

/** 这一轮挂给智能体的工具名。 */
let attached: string[] = [];
/** 每一站分别摆了哪些工具 —— 「在哪儿摆」正是要验的事之一。 */
const attachedAt: Record<string, string[]> = {};

const out = await outside({
  // 干活那一站：**调一次 `submit` 把答案交上去**。
  //
  // 交什么写在调用里，不写在它说的话里 —— 说的话是给人看的，答案是给判据看的，
  // 从前者里挑出后者只能靠猜。在干活站上按交卷是允许的：那一次就是交，流转会把它
  // 送到交卷站，交卷站直接判这一份。
  "/unit": (u) => {
    attached = ((u.tools ?? []) as { name: string }[]).map((t) => t.name);
    attachedAt[String((u.cycle as { cycle?: string } | undefined)?.cycle ?? "")] = attached;
    return {
      role: "assistant",
      kind: "call",
      body: JSON.stringify({
        text: "",
        calls: [{ id: `hand-in-${String(u.unit)}`, name: "submit", input: { answer: "the answer is 42" } }],
      }),
    };
  },
  // 干活那一站：**永远只调工具，一句完整的话都不说**。
  // 一直在调工具的题走不到「说完了」那条路，只能靠额度用完那条路拐去交卷。
  "/grind": () => ({ role: "assistant", kind: "call", body: JSON.stringify({ text: "", calls: [] }) }),
  // 一个永远说不成的观测节点 —— 用来验「判死之后换个节点再来」。
  "/nope": () => false,
  "/look": (a) => {
    graded.push(a);
    return true;
  },
  "/verdict": (a) => ((a.feed ?? []) as { value: unknown }[])[0]?.value === true,
});

const G = {
  nodes: [
    { name: "look", moment: "done", domain: { kind: "bool" }, handle: out.url("/look") },
    { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/verdict") },
  ],
  edges: [{ src: "look", out: 0, dst: "verdict" }],
  sink: "verdict",
};

try {
  // ═══════════════ 第一部分：注册 ═══════════════
  part("Part one: the hand-in step comes with the mechanism");

  step("1. declare a mode whose cycle uses the tree mechanism - and do not write a submit cycle");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/look"), expectMs: 10_000 },
      { name: out.url("/verdict"), expectMs: 10_000 },
    ],
    places: [{ place: "local" }],
    modes: [
      {
        mode: "tree",
        cycles: [{ cycle: "ask", maxUnits: 4, from: [], next: [], infer: "fn:infer.dfs" }],
      },
    ],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  show("cycles that went in:", loaded.cycles);

  const graph = await m.api<{ cycles: Record<string, unknown>[] }>("GET", "/modes/tree");
  show("the graph:", graph.cycles);
  const submit = graph.cycles.find((c) => c.cycle === "submit");
  ok("a submit cycle grew, though nobody declared one", submit !== undefined, graph.cycles);
  // **交卷不是终点。** 判 1 是这道题做成了；判 0 只说明这一次交的不成，
  // 该往前走进下一个节点的动作阶段再试，而不是收工。
  // **交卷不是终点。** 判 1 是这道题做成了；判 0 只说明这一次交的不成，
  // 该往前走进下一个节点的动作阶段再试，而不是收工。
  ok(
    "it feeds back into the action stage rather than ending the tree",
    JSON.stringify(submit?.next) === JSON.stringify(["ask"]),
    submit?.next,
  );
  ok("and the table records where it can be entered from", JSON.stringify(submit?.from) === JSON.stringify(["ask"]), submit?.from);
  ok("the working cycle can now route to it", JSON.stringify(graph.cycles.find((c) => c.cycle === "ask")?.next).includes("submit"), graph.cycles);
  // **一个节点只交一次。** 交卷站每次都落一个终态（判活或判死），落了节点就结束 ——
  // 结构上不可能有第二个。所以这一列写 1 才是这张表在说实话；写成「干活那几站之和」
  // 那种够大的数，读表的人会以为一个节点能交好多次。
  ok("a node hands in once, and the table says so", Number(submit?.maxUnits) === 1, submit?.maxUnits);
  ok("the whole-database check is clean", ((await m.api<{ data: unknown[] }>("GET", "/check")).data).length === 0);

  step("2. a mode that does not use the tree mechanism gets no submit cycle");
  await m.api("POST", "/declare", {
    modes: [{ mode: "flat", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
  });
  const flat = await m.api<{ cycles: Record<string, unknown>[] }>("GET", "/modes/flat");
  show("its graph:", flat.cycles.map((c) => c.cycle));
  ok("nothing was added", flat.cycles.length === 1, flat.cycles);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("Part two: checks at the level of use");
  console.log("  A cycle in the table proves nothing. Run a task and see where the verdict is taken.");

  step("3. run a task and watch it reach the hand-in step");
  await m.api("POST", "/tasks", {
    id: "t-1", mode: "tree", agent: "bot", place: "local", source: "user",
    description: "answer me", objective: G, readable: false,
  });
  const t = await until("t-1 to finish", async () => {
    const d = await m.api<{ state: string; units: Record<string, unknown>[] }>("GET", "/tasks/t-1");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  show("the stations it walked:", t.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`));
  ok("it reached the hand-in step", t.units.some((u) => u.cycle === "submit"), t.units);
  ok("and it passed", t.state === "done", t.state);
  // **G 收到的得是那段话本身。** 递原始 result 的话它拿到的是 `{text, calls}`
  // 整坨 JSON —— 判卷那一侧只会说「没找到答案」，而看日志像是模型没答。
  // 实测就这么判错过一整跑。
  show("what the grading function received as the answer:", (graded.at(-1) as { input?: { result?: unknown } })?.input?.result);
  ok(
    "the grading function received the words themselves, not a JSON blob",
    ((graded.at(-1) as { input?: { result?: { body?: unknown } } })?.input?.result?.body) === "the answer is 42",
    (graded.at(-1) as { input?: { result?: unknown } })?.input?.result,
  );
  ok(
    "the verdict was taken at the hand-in step, not at the working one",
    t.units.find((u) => u.status === "reached")?.cycle === "submit",
    t.units.map((u) => ({ at: `${String(u.cycle)}#${String(u.unit)}`, status: u.status })),
  );

  step("4. the hand-in tool is attached where calling it means something");
  show("what each station was given:", attachedAt);
  ok("submit is attached at the working station", (attachedAt.ask ?? []).includes("submit"), attachedAt);
  ok(
    "verify too, since this task has a grading function",
    (attachedAt.ask ?? []).includes("verify"),
    attachedAt,
  );
  // **交卷站只摆交卷这一个。** 跑工具的只有动作站；交卷站是模型站、下一站也是
  // 模型站，在那儿请求别的工具没有人会去跑 —— 那次调用会一直挂着，最后被补一条
  // 「没跑成」。而这一站要干的事只有一件：把答案交出来。
  // **别把普通推进站也一起关了。** 那几件基础工具为了「不在交卷站露面」从
  // `system` 那一档退了出来（system = 谁都有、不看条件，而条件正是要被看的）。
  // 退出来之后它们靠条件活着 —— 条件写错就是「哪儿都没有」，而那不报错，
  // 只表现为模型突然什么都干不了。
  const ordinary = ["read", "write", "edit", "glob", "grep", "bash", "python_exec"];
  const missing = ordinary.filter((t) => !(attachedAt.ask ?? []).includes(t));
  show("ordinary tools missing from the working station:", missing);
  ok("the ordinary tools are all still there at the working station", missing.length === 0, attachedAt.ask);
  ok(
    "at the hand-in station there is nothing else it can do",
    JSON.stringify(attachedAt.submit ?? []) === JSON.stringify(["submit"]),
    attachedAt.submit,
  );
  const row = (
    await m.api<{ rows: Record<string, unknown>[] }>("POST", "/query", {
      sql: "select name, params, system from tool where name = 'submit'",
    })
  ).rows[0];
  show("the row it registered:", row);
  // **交什么，写在调用里。** 上一版这个工具不收参数，交上去的是「它在交卷站说的
  // 那段话」—— 那是猜：它可能说三段话、每段里都有一个式子，挑哪一段都是猜，而猜错
  // 的表现是「答案明明写对了却判 0」。
  //
  // 参数表**跟着 G 走**（`objective.params`）：内核把 G 包装成 `verify`，交卷这一步
  // 内部问的又是同一个 G，两处当然要一样的东西。抄成两份字面量的话，G 哪天多一个
  // 字段就只会改到一边。
  const shape = JSON.parse(String(row?.params ?? "{}")) as { properties?: Record<string, unknown> };
  show("what it takes:", Object.keys(shape.properties ?? {}));
  ok(
    "it takes the answer itself, the same shape the grading function takes",
    Object.keys(shape.properties ?? {}).includes("answer"),
    row?.params,
  );
  ok("it is not a system tool - it is attached by a term, like the other tree tools", Number(row.system) === 0, row.system);
  step("5. a task that only ever calls tools still reaches the hand-in step");
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/grind"), expectMs: 30_000 }],
    modes: [{ mode: "grind", cycles: [{ cycle: "ask", maxUnits: 2, from: [], next: [], infer: "fn:infer.dfs" }] }],
    agents: [{ name: "tooler", apis: [], unit: out.url("/grind") }],
  });
  await m.api("POST", "/tasks", {
    id: "t-2", mode: "grind", agent: "tooler", place: "local", source: "user", description: "never speaks",
  });
  const g2 = await until("t-2 to finish", async () => {
    const d = await m.api<{ state: string; units: Record<string, unknown>[] }>("GET", "/tasks/t-2");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  show("the stations it walked:", g2.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`));
  ok(
    "running out of working budget routes it to the hand-in step, rather than dying quietly",
    g2.units.some((u) => u.cycle === "submit"),
    g2.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`),
  );
  // 这个模式除了交卷站没有别的候选，所以第一站之后就拐过去了 —— 一格都没浪费。
  ok(
    "it did not burn more than the declared working budget",
    g2.units.filter((u) => u.cycle === "ask").length <= 2,
    g2.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`),
  );
  step("6. a hand-in that fails opens a NEW node, with a fresh budget");
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/nope"), expectMs: 10_000 }],
    modes: [{ mode: "again", cycles: [{ cycle: "ask", maxUnits: 2, from: [], next: [], infer: "fn:infer.dfs" }] }],
  });
  await m.api("POST", "/tasks", {
    id: "t-3", mode: "again", agent: "bot", place: "local", source: "user",
    description: "never passes", readable: false,
    maxDeadSiblings: 2,
    objective: {
      nodes: [
        { name: "look", moment: "done", domain: { kind: "bool" }, handle: out.url("/nope") },
        { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/verdict") },
      ],
      edges: [{ src: "look", out: 0, dst: "verdict" }],
      sink: "verdict",
    },
  });
  await until("t-3 to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-3");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const rows = (
    await m.api<{ rows: Record<string, unknown>[] }>("POST", "/query", {
      sql: "select cycle, unit, node, status from task_again where task = 't-3' order by unit",
    })
  ).rows;
  show(
    "the stations it walked:",
    rows.map(
      (r) =>
        `${String(r.cycle)}#${String(r.unit)}@node${String(r.node)}${r.status ? "[" + String(r.status) + "]" : ""}`,
    ),
  );
  const seen = [...new Set(rows.map((r) => Number(r.node)))];
  ok("a failed hand-in starts a new node rather than ending the tree", seen.length > 1, seen);
  ok(
    "each node gets its own budget - the working station runs again in the new node",
    rows.filter((r) => r.cycle === "ask" && Number(r.node) === seen[1]).length > 0,
    rows.map((r) => `${String(r.cycle)}@node${String(r.node)}`),
  );
  ok("and it stops after maxDeadSiblings attempts, rather than going on forever", seen.length <= 3, seen);
} finally {
  out.stop();
  m.stop();
}

done();
