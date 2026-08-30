/**
 * 例子：**给一道题绑一个目标（验证函数 G）**。
 *
 * ```
 * bun test/objective.ts
 * ```
 *
 * G 回答的是「**这道题算不算做成了**」。它跟别的注册不一样，有三条硬规矩：
 *
 * 1. **绑定发生在发布那一刻，是准入条件。** 不是发完再挂上去 —— 过不了定义期
 *    检测就**拒收整个任务**。与其让一道必然算不出结果的题混进系统，不如它根本
 *    别发布
 * 2. **定义存在单独一个库（封存区），主库够不着。** 主库是全接口开放的，G 存主库
 *    等于没有墙。红线靠「够不着」，不靠「规定不许」
 * 3. **智能体派生的任务不许带 G。** 放行的话，智能体就能给自己（或自己派生的
 *    下一层）设定成功标准 —— 那是自提权，判据不再是判据
 *
 * ## G 是一张 DAG
 *
 * 每个节点是一个句柄，值域封闭（`bool` / `bool[n]`）。这个例子里每个节点都是
 * 一条外部 `http://` 句柄，跑在例子自己那台小服务器上。
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/** G 的节点被调了几次、拿到什么 —— 用来验它是**真跑了**，不是摆设。 */
const graded: Record<string, unknown>[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "I say I am done" }),
  "/infer": () => null,

  // ── G 的节点。**回的必须落在声明的值域里** ────────────────────────────
  //
  // 值域是 `bool` 就回 `true` / `false`，不是回一个 `{pass: 1}` 对象。回错形状
  // 不会让 G 报错崩掉 —— 它**归 0，并且把原因带出来**：全函数，不引入第三个值。

  /** 观测节点：这一版看什么都说「成」。 */
  "/look-pass": (a) => {
    graded.push({ who: "look-pass", input: a.input });
    return true;
  },
  /** 观测节点：这一版看什么都说「不成」。 */
  "/look-fail": (a) => {
    graded.push({ who: "look-fail", input: a.input });
    return false;
  },
  /** 输出节点：把上游喂进来的那一位原样接出去。 */
  "/verdict": (a) => {
    const feed = (a.feed ?? []) as { value: unknown }[];
    graded.push({ who: "verdict", feed });
    return feed[0]?.value === true;
  },
});

/**
 * 一张最小的**合法** G：两个节点。
 *
 * ```
 *   look（直接观测世界，入度 0）──→ verdict（输出节点，值域 bool）
 * ```
 *
 * 为什么最小是两个而不是一个 —— 定义期那几条检测里有这么一条：
 * **输出节点没有任何入边 ⇒ 它的值跟候选无关 ⇒ G 恒定 ⇒ 无效目标**。
 * 一个节点自己当输出，就是那种恒定的 G：不管智能体干了什么它都回同一个答案，
 * 那不叫判据。
 *
 * 另外两条也体现在这儿：`sink` 的值域**必须是 bool**（成/不成，没有第三种）；
 * 除根之外每个输出端口都得被某条边消费，不许有悬空的输出。
 */
const G = (look: string) => ({
  nodes: [
    { name: "look", moment: "done", domain: { kind: "bool" }, handle: look },
    { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/verdict") },
  ],
  edges: [{ src: "look", out: 0, dst: "verdict" }],
  sink: "verdict",
});

try {
  // ═══════════════ 第一部分：注册（= 发布那一刻的准入） ═══════════════
  part("Part one: registration (a grading function is bound at publish time)");

  const base = {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
      { name: out.url("/look-pass"), expectMs: 10_000 },
      { name: out.url("/look-fail"), expectMs: 10_000 },
      { name: out.url("/verdict"), expectMs: 10_000 },
    ],
    places: [{ place: "local" }],
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  };
  await m.api("POST", "/declare", base);
  ok("the base declaration went in", true);

  step("1. carries a grading function but does not say whether the agent may read it");
  const unsaid = await m.bad("POST", "/tasks", {
    id: "t-1", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "compute something", objective: G(out.url("/look-pass")),
  });
  show("it answered:", unsaid.error);
  ok("carrying one makes readable mandatory - there is no default", String(unsaid.error).includes("readable"), unsaid);

  step("2. an agent-derived task carrying a grading function (self-granted authority)");
  const selfGrant = await m.bad("POST", "/tasks", {
    id: "t-2", mode: "demo", agent: "bot", place: "local", source: "agent",
    description: "I set my own bar", objective: G(out.url("/look-pass")), readable: true,
  });
  show("it answered:", selfGrant.error);
  ok("the gate judges on source, at the single entrance", String(selfGrant.error).length > 0, selfGrant);

  step("3. a constant grading function (the output node has no incoming edge)");
  const constant = await m.bad("POST", "/tasks", {
    id: "t-3", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "compute something", readable: false,
    objective: {
      nodes: [{ name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") }],
      edges: [],
      sink: "verdict",
    },
  });
  show("it answered:", constant.error);
  ok(
    "a value independent of the candidate is not a criterion - rejected at definition time, not after publishing",
    String(constant.error).includes("constant"),
    constant,
  );

  step("4. a cyclic grading function (evaluation would not terminate)");
  const cyclic = await m.bad("POST", "/tasks", {
    id: "t-4", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "compute something", readable: false,
    objective: {
      nodes: [
        { name: "a", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") },
        { name: "b", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") },
      ],
      edges: [{ src: "a", out: 0, dst: "b" }, { src: "b", out: 0, dst: "a" }],
      sink: "a",
    },
  });
  show("it answered:", cyclic.error);
  ok("a non-terminating one has no value, and is stopped at definition time too", String(cyclic.error).includes("cycle"), cyclic);

  step("5. confirm none of those tasks reached the database");
  const inDb = await m.api<{ total: number }>("GET", "/tasks");
  ok("a task that fails the gate is never published", inDb.total === 0, inDb);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("Part two: checks at the level of use");
  console.log("  Bound is not the same as actually judged. See whether it really ran and wrote the verdict back.");

  step("6. publish a task its grading function will pass");
  await m.api("POST", "/tasks", {
    id: "t-pass", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "this one passes", objective: G(out.url("/look-pass")), readable: false,
  });
  const passed = await until("a verdict for t-pass", async () => {
    const d = await m.api<{ state: string; objective: { verdict: unknown } }>("GET", "/tasks/t-pass");
    return d.objective.verdict !== null ? d : null;
  });
  show("verdict:", passed.objective);
  ok("the grading function really ran", graded.some((x) => x.who === "look-pass"), graded.length);
  ok("the verdict was written back to the main database", (passed.objective.verdict as { pass?: number })?.pass === 1, passed.objective);
  ok("state is done", passed.state === "done", passed.state);

  step("7. publish a task it will fail - the agent saying it is done does not count");
  await m.api("POST", "/tasks", {
    id: "t-fail", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "this one does not pass", objective: G(out.url("/look-fail")), readable: false,
  });
  const failed = await until("a verdict for t-fail", async () => {
    const d = await m.api<{ state: string; objective: { verdict: unknown } }>("GET", "/tasks/t-fail");
    return d.objective.verdict !== null ? d : null;
  });
  show("verdict:", failed.objective);
  ok(
    "the agent saying I am done does not count; the grading function has the last word",
    failed.state === "failed",
    { state: failed.state, verdict: failed.objective.verdict },
  );
  ok("and it can say why", String((failed.objective.verdict as { why?: string })?.why ?? "").length > 0, failed.objective);

  step("8. can the definition be reached from the main database");
  const row = await m.api<{ count: number; rows: Record<string, unknown>[] }>("POST", "/query", {
    sql: "select id, objective, readable from task where id = 't-pass'",
  });
  show("that row in the main database:", row.rows[0]);
  ok(
    "the main database records only whether there is one; the definition is elsewhere, in the sealed store, out of reach of the API",
    !JSON.stringify(row.rows[0]).includes("look-pass"),
    row.rows[0],
  );

  step("9. a task with no grading function: finishing is finishing, nothing is judged");
  await m.api("POST", "/tasks", {
    id: "t-none", mode: "demo", agent: "bot", place: "local", source: "user", description: "no grading function",
  });
  const noG = await until("t-none to finish", async () => {
    const d = await m.api<{ state: string; objective: Record<string, unknown> }>("GET", "/tasks/t-none");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  show("its objective:", noG.objective);
  ok("no grading function, no verdict", noG.objective.has === false && noG.objective.verdict === null, noG.objective);
  ok("finishing is done", noG.state === "done", noG.state);
} finally {
  out.stop();
  m.stop();
}

done();
