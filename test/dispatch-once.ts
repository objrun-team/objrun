/**
 * 例子：**一行只许派一次。**
 *
 * ```
 * bun test/dispatch-once.ts
 * ```
 *
 * 内核挑活是这么挑的：库里那些「还没出站过」的行，全部当场发出去，`void` 掉不等。
 * 而「已经出站了」这个事实**也在库里** —— 于是有个窗口：
 *
 * 1. 这一圈挑中某一行，`void this.#advance(p)`，不等
 * 2. `#advance` 走到第一个 `await` 让出控制权，出站标记还没写
 * 3. 这中间任何一次写库都会把内核叫醒，下一圈开始
 * 4. 下一圈去库里一看「这行没派过」，于是**又派一次**
 *
 * 后果是同一格里落了两条模型应答：两条挨着的「我要调工具」，中间没有结果。模型那边
 * 不许这个形状，**整条对话从此发不出去**，那道题只能空转到超时。实测五百多格里中了
 * 四格，每中一格废一道题。
 *
 * 修法是「先占位再干活」：派发的**第一件事**就是把出站标记落库，任何 await 之前。
 * 内容（挂了哪些工具、哪些用法约定）等算出来再补进同一行。
 *
 * 这个例子把那个窗口撑开：一个慢句柄让 `#advance` 停在半路，同时不停地写库把内核
 * 叫醒 —— 没占位的话，这一格会被派好几次。
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/** 这一站故意慢：`#advance` 会停在这儿，窗口就撑开了。 */
const out = await outside({
  "/slow": async () => {
    await Bun.sleep(4000);
    return { role: "assistant", kind: "prompt", body: "took a while" };
  },
  "/infer": () => null,
  /** 这一站**永远不回话** —— 用来验「到点判死、另起一个节点」。 */
  "/never": async () => {
    await Bun.sleep(600_000);
    return { role: "assistant", kind: "prompt", body: "unreachable" };
  },
});

try {
  part("One row, one dispatch");

  step("1. a station that takes a while to answer");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [
      { name: out.url("/slow"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    modes: [{ mode: "one", cycles: [{ cycle: "ask", maxUnits: 2, from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/slow") }],
  });
  await m.api("POST", "/tasks", {
    id: "t-once-only", mode: "one", agent: "bot", place: "local", source: "user",
    description: "one dispatch please", solveSeconds: 60,
  });

  step("2. keep the kernel waking up while that station is still out");
  // **每次写库都会把内核叫醒。** 这儿一直戳它，正是要它在上一次派发还没落地的时候
  // 再挑一次 —— 没占位的话，这一格就会被派好几次。
  const until_ = Date.now() + 4000;
  while (Date.now() < until_) {
    await m.api("POST", "/exec", { sql: "update task set domain = domain where id = 't-once-only'" });
    await Bun.sleep(120);
  }

  await until("t-once-only to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-once-only");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  step("3. that row went out exactly once");
  const marks = (
    await m.api<{ rows: { unit: number; n: number }[] }>("POST", "/query", {
      sql:
        "select unit, count(*) as n from agent_bot_msg where instance = 't-once-only#1' " +
        "and kind = 'inject' and body like '%\"sent\":true%' group by unit",
    })
  ).rows;
  show("dispatch marks per unit:", marks.map((r) => `u${String(r.unit)}: ${String(r.n)}`));
  ok("no unit was dispatched twice", marks.every((r) => Number(r.n) === 1), marks);

  step("4. and the model was asked once, so the conversation still holds");
  const said = (
    await m.api<{ rows: { unit: number; n: number }[] }>("POST", "/query", {
      sql:
        "select unit, count(*) as n from agent_bot_msg where instance = 't-once-only#1' " +
        "and role = 'assistant' group by unit",
    })
  ).rows;
  show("answers per unit:", said.map((r) => `u${String(r.unit)}: ${String(r.n)}`));
  ok("one dispatch, one answer", said.every((r) => Number(r.n) === 1), said);

  step("5. a station that never answers kills the attempt, and a new one starts");
  // 「这一次调用没回来」跟「这道题做不出来」是两回事。以前到点就把这一行标成死的、
  // 链路断在那儿、任务跟着收工 —— 一次抖动就让一道题颗粒无收，连第二次机会都没有。
  // 现在判死之后另起一个节点，跟交卷判 0 之后重来是同一条路。
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/never"), expectMs: 4000 }],
    agents: [{ name: "ghost", apis: [], unit: out.url("/never") }],
    modes: [{ mode: "gone", cycles: [{ cycle: "ask", maxUnits: 4, from: [], next: [], infer: out.url("/infer") }] }],
  });
  await m.api("POST", "/tasks", {
    id: "t-silent", mode: "gone", agent: "ghost", place: "local", source: "user",
    description: "nobody will answer", solveSeconds: 40, maxDeadSiblings: 2,
  });
  const walked = await until(
    "a second attempt to open after the first one went silent",
    async () => {
      const got = await m.api<{ rows: { unit: number; node: number; status: string | null }[] }>("POST", "/query", {
        sql: "select unit, node, status from task_gone where task = 't-silent' order by unit",
      });
      return got.rows.some((r) => Number(r.node) > 1) ? got.rows : null;
    },
    45_000,
  );
  show("what it walked:", walked.map((r) => `u${String(r.unit)}@node${String(r.node)}${r.status ? "[" + r.status + "]" : ""}`));
  ok("the silent station was declared dead", walked.some((r) => r.status === "dead_failed"), walked);
  ok("and a fresh attempt was opened instead of ending the task", new Set(walked.map((r) => Number(r.node))).size > 1, walked);
} finally {
  out.stop();
  m.stop();
}

done();
