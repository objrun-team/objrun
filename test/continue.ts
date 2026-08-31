/**
 * 例子：**一句话没说完，接着说**（续写），以及**接不下去了怎么办**。
 *
 * ```
 * bun test/continue.ts
 * ```
 *
 * 模型把话说到一半就到 token 上限（`finish_reason = "length"`）是常事。这一层
 * 的做法是**把已经说出的那半截接在末尾，让它续**，而不是重问一遍 —— 重问一遍
 * 得到的是另一个开头，前面那半截白花。
 *
 * ## 为什么不直接打真端点
 *
 * 要验的是**续不下去的时候会怎样**，而真端点几乎不会在这一步拒绝你。所以这儿
 * 起一台假的 chat completions：第一趟给半截话加一个 `length`，第二趟直接拒收。
 * 一道题就是这么没的 —— 拒收的那一下抛到句柄外面，那一站挂到 `expect_ms`，
 * 前面说了多少个字都不算数。
 *
 * 地址靠 `TGENGIN_DEEPSEEK_BASE_URL` 顶掉，这条环境变量就是为了这个留的。
 */

import { done, machine, ok, part, show, step, until } from "./_lib.ts";

/** 假端点被打了几次、每次收到的最后一条助手消息长什么样。 */
const seen: { messages: { role: string; content: unknown }[] }[] = [];

/** 第二趟起就拒收，用的是真端点拒收时说的那句话。 */
const REFUSED = "The reasoning_content in the thinking mode must be passed back to the API.";

/** 第一趟说到一半就断。**后面那半句它永远不会说出来** —— 那正是要验的。 */
const HALF = "The answer is 4 because ";

const fake = Bun.serve({
  port: 0,
  async fetch(req) {
    // 同一台小服务器顺便当一下「下一站去哪」：这个例子只有一站，回 null = 收工。
    if (new URL(req.url).pathname === "/infer") {
      return new Response("null", { headers: { "content-type": "application/json" } });
    }
    const body = (await req.json()) as { messages: { role: string; content: unknown }[] };
    seen.push(body);
    if (seen.length > 1) {
      return new Response(JSON.stringify({ error: { message: REFUSED, type: "invalid_request_error" } }), {
        status: 400,
        headers: { "content-type": "application/json" },
      });
    }
    return new Response(
      JSON.stringify({
        id: "fake-1",
        object: "chat.completion",
        created: 0,
        model: "deepseek-v4-flash",
        choices: [{ index: 0, message: { role: "assistant", content: HALF }, finish_reason: "length" }],
        usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
      }),
      { headers: { "content-type": "application/json" } },
    );
  },
});

process.env.TGENGIN_DEEPSEEK_BASE_URL = `http://127.0.0.1:${String(fake.port)}`;

// `retryTimes: 0` —— 假端点是铁了心拒收，退避三轮只是让这个例子多跑半分钟。
const m = await machine({ retryTimes: 0, continueTimes: 2, maxTokens: 64 });
const at = (path: string) => `http://127.0.0.1:${String(fake.port)}${path}`;

try {
  part("Continuing a half-finished sentence, and what happens when it cannot be continued");

  step("1. one chat cycle, one agent that really talks to a model");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [{ name: at("/infer"), expectMs: 10_000 }],
    modes: [
      { mode: "talk", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 2, from: [], next: [], infer: at("/infer") }] },
    ],
    agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }],
  });
  ok("the declaration went in", true);

  step("2. publish one task and let it run");
  await m.api("POST", "/tasks", {
    id: "t-cut", mode: "talk", agent: "bot", place: "local", source: "user",
    description: "what is two plus two", solveSeconds: 60,
  });
  const t = await until("t-cut to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-cut");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 60_000);
  show("how it ended:", t.state);

  step("3. it really tried to continue, rather than settling for half a sentence");
  ok("the endpoint was called more than once", seen.length > 1, seen.length);
  const second = seen[1].messages;
  const last = second[second.length - 1];
  show("the last message of the second call:", last);
  ok(
    "and the half it had already said went back as the tail of the conversation",
    last.role === "assistant" && JSON.stringify(last.content).includes(HALF.trim()),
    last,
  );

  step("4. being refused mid-continuation does not cost the whole task");
  // 这一条焊的是一道真丢过的题：拒收那一下抛出句柄，那一站挂到 expect_ms，
  // 一个字都没交。半截答案也是答案 —— 交出去，比什么都没有强。
  const said = await m.api<{ rows: { body: string }[] }>("POST", "/query", {
    sql: "select body from agent_bot_msg where instance = 't-cut#1' and role = 'assistant' order by seq",
  });
  show("what it handed back:", said.rows.map((r) => r.body));
  ok("the task closed instead of hanging until its handle timed out", t.state === "done", t.state);
  ok(
    "and what it had managed to say was handed back",
    said.rows.some((r) => r.body.includes(HALF.trim())),
    said.rows,
  );
} finally {
  await fake.stop(true);
  m.stop();
}

done();
