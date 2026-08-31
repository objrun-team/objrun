/**
 * 例子：**一次调用，一条结果。** 不多也不少。
 *
 * ```
 * bun test/answer-once.ts
 * ```
 *
 * 模型请求工具，落一行 `call`；工具跑完落一行 `tool`，靠 `id` 配对。模型那边对这
 * 一对的要求是死的，而且**两个方向都会拒**：
 *
 * | 缺了 | 它说 |
 * | --- | --- |
 * | 有调用没结果 | `Tool result is missing for tool call …` |
 * | 有结果没调用 | `Messages with role 'tool' must be a response to a preceding message with 'tool_calls'` |
 *
 * 第二种是补齐补出来的：一次没人跑的调用会被补一条「没跑成」（见 `answerMissing`），
 * 而**给要跑工具的那一站拼上下文时，工具还没开始跑** —— 那时候的「没人答」是
 * 「还没轮到」。在那儿补一条，等它真跑完，同一个 id 就有了两条结果。
 *
 * 实测的后果是五道题**全部**卡在第三站上，一道都跑不动。
 *
 * 判据在表里：`api_mode` 为空的站调 `agent.unit`，那才是跑工具、写结果的那个，
 * 轮不到它补；有 `api_mode` 的站是去问模型的，它拼上下文时补才安全。
 *
 * ## 为什么要一台假端点
 *
 * 要复现就得有一条**真的从模型那儿来的**工具请求，再让下一站真去跑它。假端点
 * 只做一件事：第一次问它，它就要一次工具。
 */

import { done, machine, ok, part, show, step, until } from "./_lib.ts";

/** 假端点被问了几次。第一次要工具，之后说完就走。 */
let asked = 0;
/** 走到第几站了 —— 这个例子的流转就三步。 */
let hops = 0;

const CALL_ID = "call-run-me-once";

const answer = (message: Record<string, unknown>, why: string) =>
  new Response(
    JSON.stringify({
      id: "fake-1",
      object: "chat.completion",
      created: 0,
      model: "deepseek-v4-flash",
      choices: [{ index: 0, message, finish_reason: why }],
      usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
    }),
    { headers: { "content-type": "application/json" } },
  );

const fake = Bun.serve({
  port: 0,
  fetch(req) {
    const path = new URL(req.url).pathname;
    // 这一站走完去哪儿：ask → act → ask，第三站收工。
    if (path === "/infer") {
      const to = hops === 0 ? { to: "act" } : hops === 1 ? { to: "ask" } : null;
      hops++;
      return new Response(JSON.stringify(to), {
        headers: { "content-type": "application/json" },
      });
    }
    asked++;
    if (asked === 1) {
      return answer(
        {
          role: "assistant",
          content: "",
          tool_calls: [
            { id: CALL_ID, type: "function", function: { name: "glob", arguments: JSON.stringify({ pattern: "*.md" }) } },
          ],
        },
        "tool_calls",
      );
    }
    return answer({ role: "assistant", content: "done looking" }, "stop");
  },
});

const at = (path: string) => `http://127.0.0.1:${String(fake.port)}${path}`;

const m = await machine({ retryTimes: 0 });

try {
  part("One call, one result - the station that runs the tools is not the one that fills in blanks");

  step("1. ask talks to a model, act runs whatever it asked for");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [{ name: at("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "work",
        cycles: [
          { cycle: "ask", apiMode: "tools", maxUnits: 4, from: [], next: ["act"], infer: at("/infer") },
          { cycle: "act", maxUnits: 4, from: ["ask"], next: ["ask"], infer: at("/infer") },
        ],
      },
    ],
    // `fn:unit.tools` 就是真去跑工具的那一个 —— 这个例子的关键。
    agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }],
  });
  await m.api("POST", "/exec", {
    sql: `update api set base_url = '${at("")}' where model = 'deepseek-v4-flash'`,
  });
  ok("the declaration went in, pointed at the fake endpoint", true);

  step("2. run it to the end");
  await m.api("POST", "/tasks", {
    id: "t-once", mode: "work", agent: "bot", place: "local", source: "user",
    description: "ask for one tool", solveSeconds: 60,
  });
  const t = await until(
    "t-once to finish",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-once");
      return d.state === "done" || d.state === "failed" ? d : null;
    },
    50_000,
  );
  show("how it ended:", t.state);
  ok("it ran to the end instead of jamming on the third station", t.state === "done", t.state);

  step("3. the table holds exactly one result for that call");
  const rows = (
    await m.api<{ rows: { unit: number; seq: number; body: string }[] }>("POST", "/query", {
      sql: "select unit, seq, body from agent_bot_msg where instance = 't-once#1' and kind = 'tool' order by unit, seq",
    })
  ).rows;
  const mine = rows.filter((r) => String(r.body).includes(CALL_ID));
  show("results answering that call:", mine.map((r) => `u${String(r.unit)}.${String(r.seq)}`));
  ok("it was answered", mine.length >= 1, rows);
  ok("and answered once, not once by the runner and once by the repair", mine.length === 1, mine);

  step("4. and the answer is the real one, not a placeholder");
  // 补出来的那条写着 `ran: false`。真跑过的不该长这样 —— 长这样就说明补齐抢在了
  // 跑工具的前面，而那正是当初五道题一起卡住的原因。
  show("what it says:", String(mine[0]?.body ?? "").slice(0, 120));
  ok(
    "the runner's result is what survived",
    !String(mine[0]?.body ?? "").includes('"ran":false'),
    mine[0]?.body,
  );
} finally {
  await fake.stop(true);
  m.stop();
}

done();
