/**
 * 例子：**它想了什么、花了多少，都得留在库里。**
 *
 * ```
 * bun test/integration/spend.ts
 * ```
 *
 * 快照里以前有一个洞：**一次调用的开销一个字都没记。** 实测一跑量出来「派发到应答」
 * 平均 174 秒，而可见输出平均才 350 个 token —— 每秒两个 token，没有哪个模型慢成
 * 这样。那两百多秒是它在想，可 `reasoning_content` 当时是**读完就扔**的，于是「时限
 * 够不够」这个问题永远只能靠反推，答不出读数。
 *
 * 思考不进 `body` 的那条老决定照旧成立，理由没变：`body` 是**重放要用的那一份**，
 * 而有的网关不认得带思考的助手消息。所以这两件事分开办 ——
 *
 * - `body`：一个字不动，重放照旧
 * - `thought` + 四个计数列：只进库、不回传
 *
 * 这个例子把两边都钉住：账进了库，而 `body` 里没有混进思考。
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** 冒充适配器：既说话，也报账。真适配器报的是同样这几个字段。 */
const out = await outside({
  "/say": () => ({
    role: "assistant",
    kind: "prompt",
    body: "the ground state energy is -U0/4",
    thought: "start from the strong coupling limit, then count neighbours",
    prompt_tokens: 1200,
    completion_tokens: 900,
    reasoning_tokens: 850,
    cached_tokens: 300,
  }),
  "/infer": () => null,
});

try {
  part("What a call cost stays in the database");

  step("1. one station, one agent");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [
      { name: out.url("/say"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    modes: [{ mode: "one", cycles: [{ cycle: "ask", maxUnits: 1, from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/say") }],
  });
  await m.api("POST", "/tasks", {
    id: "t-spend",
    mode: "one",
    agent: "bot",
    place: "local",
    source: "user",
    description: "say something and report what it cost",
    solveSeconds: 60,
  });

  await until(
    "t-spend to finish",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-spend");
      return d.state === "done" || d.state === "failed" ? d : null;
    },
    30_000,
  );

  step("2. the account landed on the row the model wrote");
  const rows = (
    await m.api<{
      rows: {
        body: string;
        thought: string | null;
        prompt_tokens: number | null;
        completion_tokens: number | null;
        reasoning_tokens: number | null;
        cached_tokens: number | null;
      }[];
    }>("POST", "/query", {
      sql:
        "select body, thought, prompt_tokens, completion_tokens, reasoning_tokens, cached_tokens " +
        "from agent_bot_msg where instance = 't-spend#1' and role = 'assistant'",
    })
  ).rows;
  show("what the assistant row holds:", rows);
  const said = rows[0];
  ok("there is exactly one assistant row", rows.length === 1, rows.length);
  ok("the thinking is recorded", (said?.thought ?? "").includes("strong coupling"), said?.thought);
  ok("tokens sent are recorded", Number(said?.prompt_tokens) === 1200, said?.prompt_tokens);
  ok("tokens produced are recorded", Number(said?.completion_tokens) === 900, said?.completion_tokens);
  ok("tokens thought are recorded", Number(said?.reasoning_tokens) === 850, said?.reasoning_tokens);
  ok("cached tokens are recorded", Number(said?.cached_tokens) === 300, said?.cached_tokens);

  step("3. and none of it leaked into body - that is the half that gets replayed");
  // 思考混进 `body` 的话，重放时它会被当成模型说过的话原样发回去，而那正是有的
  // 网关要拒的东西。这一条守的就是那条路。
  ok("body is only what was spoken", said?.body === "the ground state energy is -U0/4", said?.body);
  ok("body carries no thinking", !(said?.body ?? "").includes("strong coupling"), said?.body);

  step("4. a row no model call produced keeps the columns empty");
  // **不报的记 null，不记 0。** 记成 0 的话，它跟「真的一个 token 都没花」长得
  // 一模一样，而那两件事差着一次调用。
  const others = (
    await m.api<{ rows: { kind: string; prompt_tokens: number | null; thought: string | null }[] }>("POST", "/query", {
      sql: "select kind, prompt_tokens, thought from agent_bot_msg where instance = 't-spend#1' and role <> 'assistant'",
    })
  ).rows;
  show("rows nobody billed:", others);
  ok(
    "no model call, no numbers",
    others.every((r) => r.prompt_tokens === null && r.thought === null),
    others,
  );
} finally {
  out.stop();
  m.stop();
}

done();
