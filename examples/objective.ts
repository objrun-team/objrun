/**
 * 例子：**给一道题绑一个目标（验证函数 G）**。
 *
 * ```
 * bun examples/objective.ts
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
const 判过: Record<string, unknown>[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "我说我做完了" }),
  "/infer": () => null,

  // ── G 的节点。**回的必须落在声明的值域里** ────────────────────────────
  //
  // 值域是 `bool` 就回 `true` / `false`，不是回一个 `{pass: 1}` 对象。回错形状
  // 不会让 G 报错崩掉 —— 它**归 0，并且把原因带出来**：全函数，不引入第三个值。

  /** 观测节点：这一版看什么都说「成」。 */
  "/look-pass": (a) => {
    判过.push({ who: "look-pass", input: a.input });
    return true;
  },
  /** 观测节点：这一版看什么都说「不成」。 */
  "/look-fail": (a) => {
    判过.push({ who: "look-fail", input: a.input });
    return false;
  },
  /** 输出节点：把上游喂进来的那一位原样接出去。 */
  "/verdict": (a) => {
    const feed = (a.feed ?? []) as { value: unknown }[];
    判过.push({ who: "verdict", feed });
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
  part("第一部分：注册（G 是在发布那一刻绑的）");

  const 底子 = {
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
  await m.api("POST", "/declare", 底子);
  ok("底子灌好了", true);

  step("① 带了 G 却没说智能体读不读得到");
  const 没说 = await m.bad("POST", "/tasks", {
    id: "t-1", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "算个东西", objective: G(out.url("/look-pass")),
  });
  show("回的是：", 没说.error);
  ok("**带 G 就必须显式给 readable，没有默认值**", String(没说.error).includes("readable"), 没说);

  step("② 智能体派生的任务带 G（自提权）");
  const 自提权 = await m.bad("POST", "/tasks", {
    id: "t-2", mode: "demo", agent: "bot", place: "local", source: "agent",
    description: "我给自己定个标准", objective: G(out.url("/look-pass")), readable: true,
  });
  show("回的是：", 自提权.error);
  ok("**闸按来源判，判在唯一入口上**", String(自提权.error).length > 0, 自提权);

  step("③ 一张恒定的 G（输出节点没有入边）");
  const 恒定 = await m.bad("POST", "/tasks", {
    id: "t-3", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "算个东西", readable: false,
    objective: {
      nodes: [{ name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") }],
      edges: [],
      sink: "verdict",
    },
  });
  show("回的是：", 恒定.error);
  ok(
    "**它的值跟候选无关，那不叫判据** —— 定义期就拒，不是发完再说",
    String(恒定.error).includes("G 恒定"),
    恒定,
  );

  step("④ 一张有回环的 G（求值不终止）");
  const 回环 = await m.bad("POST", "/tasks", {
    id: "t-4", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "算个东西", readable: false,
    objective: {
      nodes: [
        { name: "a", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") },
        { name: "b", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") },
      ],
      edges: [{ src: "a", out: 0, dst: "b" }, { src: "b", out: 0, dst: "a" }],
      sink: "a",
    },
  });
  show("回的是：", 回环.error);
  ok("**求值不终止的 G 算不出来**，也在定义期拦下", String(回环.error).includes("回环"), 回环);

  step("⑤ 确认前几道题一个都没进库");
  const 库里 = await m.api<{ total: number }>("GET", "/tasks");
  ok("**过不了闸的题根本没发布**", 库里.total === 0, 库里);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("第二部分：使用层次的校验");
  console.log("  绑上了 ≠ 真去判。看它跑完之后有没有真跑 G、判决有没有写回来。");

  step("⑥ 发一道 G 会说「成」的题");
  await m.api("POST", "/tasks", {
    id: "t-pass", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "这道会过", objective: G(out.url("/look-pass")), readable: false,
  });
  const 成了 = await until("t-pass 出判决", async () => {
    const d = await m.api<{ state: string; objective: { verdict: unknown } }>("GET", "/tasks/t-pass");
    return d.objective.verdict !== null ? d : null;
  });
  show("判决：", 成了.objective);
  ok("**G 真的被跑了**", 判过.some((x) => x.who === "look-pass"), 判过.length);
  ok("判决写回主库了", (成了.objective.verdict as { pass?: number })?.pass === 1, 成了.objective);
  ok("状态是 done", 成了.state === "done", 成了.state);

  step("⑦ 发一道 G 会说「不成」的题 —— 智能体自己说做完了也不算");
  await m.api("POST", "/tasks", {
    id: "t-fail", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "这道过不了", objective: G(out.url("/look-fail")), readable: false,
  });
  const 没成 = await until("t-fail 出判决", async () => {
    const d = await m.api<{ state: string; objective: { verdict: unknown } }>("GET", "/tasks/t-fail");
    return d.objective.verdict !== null ? d : null;
  });
  show("判决：", 没成.objective);
  ok(
    "**智能体说「我做完了」不算数，G 说了算**",
    没成.state === "failed",
    { state: 没成.state, verdict: 没成.objective.verdict },
  );
  ok("而且说得出为什么", String((没成.objective.verdict as { why?: string })?.why ?? "").length > 0, 没成.objective);

  step("⑧ 主库里够不够得着 G 的定义");
  const 那一行 = await m.api<{ count: number; rows: Record<string, unknown>[] }>("POST", "/query", {
    sql: "select id, objective, readable from task where id = 't-pass'",
  });
  show("主库里那一行：", 那一行.rows[0]);
  ok(
    "**主库只记「有没有 G」，定义不在这儿** —— 它在封存区，接口开不到",
    !JSON.stringify(那一行.rows[0]).includes("look-pass"),
    那一行.rows[0],
  );

  step("⑨ 没有 G 的题：跑完就是跑完，不判");
  await m.api("POST", "/tasks", {
    id: "t-none", mode: "demo", agent: "bot", place: "local", source: "user", description: "不带 G",
  });
  const 无G = await until("t-none 跑完", async () => {
    const d = await m.api<{ state: string; objective: Record<string, unknown> }>("GET", "/tasks/t-none");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  show("它的 objective：", 无G.objective);
  ok("没有 G 就没有判决", 无G.objective.has === false && 无G.objective.verdict === null, 无G.objective);
  ok("跑完就是 done", 无G.state === "done", 无G.state);
} finally {
  out.stop();
  m.stop();
}

done();
