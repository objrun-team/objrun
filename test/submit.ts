/**
 * 交卷：**一个工具 + 一站**，随走树那套机制一起装上。
 *
 * ```
 * bun test/submit.ts
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

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/** G 被真调了几次 —— 「验过就不再判一遍」靠数它。 */
const graded: unknown[] = [];

/** 这一轮挂给智能体的工具名。 */
let attached: string[] = [];

const out = await outside({
  // 干活那一站：第一次说一句话就算做完了。
  "/unit": (u) => {
    attached = ((u.tools ?? []) as { name: string }[]).map((t) => t.name);
    return { role: "assistant", kind: "prompt", body: "the answer is 42" };
  },
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
  ok("it is terminal (next is empty)", JSON.stringify(submit?.next) === "[]", submit?.next);
  ok("the working cycle can now route to it", JSON.stringify(graph.cycles.find((c) => c.cycle === "ask")?.next).includes("submit"), graph.cycles);
  ok(
    "its budget is not the binding one - it takes the sum of the working cycles",
    Number(submit?.maxUnits) === 4,
    submit?.maxUnits,
  );
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
  ok(
    "the verdict was taken at the hand-in step, not at the working one",
    t.units.find((u) => u.status === "reached")?.cycle === "submit",
    t.units.map((u) => ({ at: `${String(u.cycle)}#${String(u.unit)}`, status: u.status })),
  );

  step("4. the hand-in tool is attached, and it takes no arguments");
  show("tools attached this round:", attached);
  ok("submit is attached", attached.includes("submit"), attached);
  ok("verify is attached too (this task has a grading function)", attached.includes("verify"), attached);
  const row = (
    await m.api<{ rows: Record<string, unknown>[] }>("POST", "/query", {
      sql: "select name, params, system from tool where name = 'submit'",
    })
  ).rows[0];
  show("the row it registered:", row);
  ok(
    "it takes no arguments - what gets handed in is what is said at that step",
    JSON.stringify(JSON.parse(String(row.params)).properties ?? {}) === "{}",
    row.params,
  );
  ok("it is not a system tool - it is attached by a term, like the other tree tools", Number(row.system) === 0, row.system);
} finally {
  out.stop();
  m.stop();
}

done();
