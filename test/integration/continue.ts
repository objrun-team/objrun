/**
 * 例子：**一句话没说完，接着说**（续写），以及**请求长成什么形状会被拒**。
 *
 * ```
 * bun test/integration/continue.ts
 * ```
 *
 * 模型把话说到一半就到 token 上限是常事 —— 它自己会说，`finish_reason = "length"`。
 * 这一层的做法是**把已经说出的那半截接在末尾，让它续**，而不是重问一遍：重问
 * 得到的是另一个开头，前面那半截白花。
 *
 * ## 为什么不直接打真端点
 *
 * 要验的是**被拒之后会怎样**，而真端点几乎不会在这一步拒绝你。所以这儿起一台
 * 假的 chat completions，照真网关那条规矩办事：
 *
 * > **请求以助手消息结尾 = 你在要求我续写。** 那属于「思考模式的前缀续写」，
 * > 得把 `reasoning_content` 一起带回来，不带就 400。
 *
 * 这条规矩把两种情况一网打尽，而它们的后果完全不同：
 *
 * | 谁让请求以助手消息结尾 | 后果 |
 * | --- | --- |
 * | **我们自己**（续写，把半截话接在末尾） | 该续，被拒了就把半截交出去 |
 * | **上一站说了句纯文本就走**（不是我们要续） | 纯属形状拼错了，得修 |
 *
 * 第二种真丢过一道题：`messagesOf` 原先把这一轮的问话放在**历史前面**，于是
 * 上一站要是说了句话（没调工具），整个请求就以那句话结尾 —— 网关当成续写，
 * 拒收，那一站挂到 `expect_ms`，一个字都没交（cmt-3，submit#14）。上一站调了
 * 工具的话最后一条是 tool 结果，形状是对的，所以这个毛病看着像随机。
 *
 * 假端点是**改一行数据**接进来的：`update api set base_url = ...`。以前这儿用的是
 * 一条环境变量，那意味着同一份库换个环境变量行为就不一样 —— 库也就当不成快照了。
 */

import { done, machine, ok, part, show, step, until } from "../_lib.ts";

interface Call {
  messages: { role: string; content: unknown }[];
}

/** 假端点每一次收到的东西，跑完拿来对形状。 */
const seen: Call[] = [];

/** 真端点拒收时说的那句话。 */
const REFUSED = "The reasoning_content in the thinking mode must be passed back to the API.";

/** 第一趟说到一半就断。**后面那半句它永远不会说出来** —— 那正是要验的。 */
const HALF = "The answer is 4 because ";

/** 说完一句整话。 */
const WHOLE = "Two plus two is four.";

/** 认得出是哪一道题：一道说了半句，另一道一个字都没说。 */
const CUT = "two plus two";
const MUTE = "hexagon";

/** 撞上限时它想了一堆，但可见文本一个字都没有。 */
const THINKING = "A hexagon has six corners, let me double check by counting the vertices ...";

const reply = (text: string, why: string, thinking = "") =>
  new Response(
    JSON.stringify({
      id: "fake-1",
      object: "chat.completion",
      created: 0,
      model: "deepseek-v4-flash",
      choices: [
        {
          index: 0,
          message: { role: "assistant", content: text, ...(thinking ? { reasoning_content: thinking } : {}) },
          finish_reason: why,
        },
      ],
      usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
    }),
    { headers: { "content-type": "application/json" } },
  );

/** 每道题都是两站：第一站走完去第二站，第二站走完收工。**按题数，不按总次数** —— 
 * 按总次数的话第二道题一进来就直接收工，走不到重放那一步。 */
const hops: Record<string, number> = {};

const fake = Bun.serve({
  port: 0,
  async fetch(req) {
    if (new URL(req.url).pathname === "/infer") {
      const who = JSON.stringify(await req.json()).includes("t-mute") ? "t-mute" : "t-cut";
      hops[who] = (hops[who] ?? 0) + 1;
      return new Response(JSON.stringify(hops[who] === 1 ? { to: "again" } : null), {
        headers: { "content-type": "application/json" },
      });
    }

    const body = (await req.json()) as Call;
    seen.push(body);
    const tail = body.messages[body.messages.length - 1] as { role: string; reasoning_content?: string } | undefined;
    /** 这一发是那道题的第一发么（刚 push 进去的这一条也算在内）。 */
    const first = (mark: string) => seen.filter((c) => JSON.stringify(c.messages).includes(mark)).length === 1;

    // **真网关那条规矩。** 谁让请求以助手消息结尾，谁就是在要求续写 —— 思考模式下
    // 得把 `reasoning_content` 一起带回来，不带就 400。带了就接着往下说。
    if (tail?.role === "assistant") {
      if (!tail.reasoning_content) {
        return new Response(JSON.stringify({ error: { message: REFUSED, type: "invalid_request_error" } }), {
          status: 400,
          headers: { "content-type": "application/json" },
        });
      }
      return reply(WHOLE, "stop");
    }
    // 第一发：一道题说了半句就断，另一道题**一个字可见文本都没有，光在想**。
    if (JSON.stringify(body.messages).includes(MUTE)) {
      return first(MUTE) ? reply("", "length", THINKING) : reply(WHOLE, "stop");
    }
    return first(CUT) ? reply(HALF, "length") : reply(WHOLE, "stop");
  },
});

// **`retryTimes` 故意开着。** 这个例子要验的一件事就是「400 不该被重打」——
// 关掉重试的话，不重打是因为压根没开重试，什么也没验到。
const m = await machine({ retryTimes: 3, continueTimes: 2, maxTokens: 64 });
const at = (path: string) => `http://127.0.0.1:${String(fake.port)}${path}`;

try {
  part("Continuing a half-finished answer, and the shape a request must not have");

  step("1. two stations, and an agent that really talks to a model");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [{ name: at("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "talk",
        cycles: [
          { cycle: "ask", apiMode: "chat", maxUnits: 2, from: [], next: ["again"], infer: at("/infer") },
          { cycle: "again", apiMode: "chat", maxUnits: 2, from: ["ask"], next: [], infer: at("/infer") },
        ],
      },
    ],
    agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }],
  });
  ok("the declaration went in", true);

  step("1b. point that model at the fake endpoint - by changing a row");
  // **改地址是改数据。** 这一步同时也验了那件事：`api.base_url` 说了算，
  // 代码里那份只是注册时的种子。
  await m.api("POST", "/exec", {
    sql: `update api set base_url = '${at("")}' where model = 'deepseek-v4-flash'`,
  });
  const where = (
    await m.api<{ rows: { base_url: string }[] }>("POST", "/query", {
      sql: "select base_url from api where model = 'deepseek-v4-flash'",
    })
  ).rows[0];
  show("where that model now points:", where.base_url);
  ok("the table says where the calls go", where.base_url === at(""), where);

  step("2. publish one task and let it run to the end");
  await m.api("POST", "/tasks", {
    id: "t-cut", mode: "talk", agent: "bot", place: "local", source: "user",
    description: "what is two plus two", solveSeconds: 60,
  });
  const t = await until(
    "t-cut to finish",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-cut");
      return d.state === "done" || d.state === "failed" ? d : null;
    },
    60_000,
  );
  show("how it ended:", t.state);
  ok("it finished instead of hanging until its handle timed out", t.state === "done", t.state);

  step("3. it really tried to continue, rather than settling for half a sentence");
  const tried = seen.find((c) => c.messages[c.messages.length - 1]?.role === "assistant");
  show("the tail of the call that asked for a continuation:", tried?.messages.slice(-1));
  ok("a continuation was attempted", tried !== undefined, seen.length);
  ok(
    "and the half it had already said went back as the tail of the conversation",
    JSON.stringify(tried?.messages.at(-1)?.content ?? "").includes(HALF.trim()),
    tried?.messages.at(-1),
  );

  step("4. being refused mid-continuation costs the half sentence, not the task");
  const said = await m.api<{ rows: { unit: number; body: string }[] }>("POST", "/query", {
    sql: "select unit, body from agent_bot_msg where instance = 't-cut#1' and role = 'assistant' order by seq",
  });
  show("what it handed back:", said.rows);
  ok("what it had managed to say was handed back", said.rows.some((r) => r.body.includes(HALF.trim())), said.rows);

  step("5. and the NEXT station is not poisoned by that half sentence");
  // 这一条焊的就是丢掉的那道题。上一站的最后一条是助手说的半句话；这一站要是
  // 把这一轮的问话摆在历史**前面**，整个请求就以那半句结尾 —— 网关当成续写请求，
  // 400，而这一次是 round 0，抛出去就是一整道题没了。
  const asks = seen.filter((c) => c.messages[c.messages.length - 1]?.role !== "assistant");
  const last = asks[asks.length - 1];
  show("the roles in the last real question we asked:", last.messages.map((mm) => mm.role));
  ok(
    "a fresh question ends with something addressed to the model, never with its own words",
    last.messages[last.messages.length - 1].role === "user",
    last.messages.map((mm) => mm.role),
  );
  ok(
    "and it carried the previous station's answer as history",
    last.messages.some((mm) => mm.role === "assistant"),
    last.messages.map((mm) => mm.role),
  );
  ok("so the second station ran and answered", said.rows.some((r) => r.body.includes(WHOLE)), said.rows);
  step("6. a request the other side calls invalid is not sent again");
  // 400 说的是「这个请求本身不合法」，再打一百次还是同一个 400 —— 重打只是把
  // 时间烧掉，然后以完全一样的方式失败。真跑里烧掉的是 30 秒（0+5+10+15 的退避），
  // 而那一站随后还要空挂到 expect_ms。哪些错值得再打，是 `api.retry_on` 那一列说了算。
  const refused = seen.filter((c) => c.messages[c.messages.length - 1]?.role === "assistant");
  show("how many times the refused shape went out:", refused.length);
  ok(
    "it went out once, not once per retry - retryTimes is 3 here",
    refused.length === 1,
    refused.length,
  );
  step("7. it hit the limit while still thinking - the thinking is what gets carried back");
  // **这一条焊的是「截断被当成断线」。** 撞上限时最常见的形态是一个字可见文本都
  // 还没写出来。门槛要是「说过话没有」，这一轮就退化成把原题原样再问一遍 ——
  // 那是断线的处理办法，而断线本来就有人管。实测重发出来的思维链**开头逐字等于
  // 丢掉的那份**：同样的输入，它走同样的路，再撞同一堵墙。
  await m.api("POST", "/tasks", {
    id: "t-mute", mode: "talk", agent: "bot", place: "local", source: "user",
    description: "how many corners has a hexagon", solveSeconds: 60,
  });
  const t2 = await until(
    "t-mute to finish",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-mute");
      return d.state === "done" || d.state === "failed" ? d : null;
    },
    60_000,
  );
  ok("it finished", t2.state === "done", t2.state);

  const carried = seen.filter(
    (c) =>
      JSON.stringify(c.messages).includes(MUTE) &&
      (c.messages[c.messages.length - 1] as { role: string }).role === "assistant",
  );
  const tail2 = carried[0]?.messages.at(-1) as { content?: unknown; reasoning_content?: string } | undefined;
  show("the tail of the continuation:", { content: tail2?.content, reasoning_content: tail2?.reasoning_content });
  ok("a continuation went out even though it had said nothing", carried.length > 0, seen.length);
  ok("and what it had been thinking went back with it", tail2?.reasoning_content === THINKING, tail2);
  ok("no words were invented to fill the gap", !JSON.stringify(tail2?.content ?? "").includes("hexagon"), tail2?.content);

  const asked = seen.filter((c) => JSON.stringify(c.messages).includes(MUTE));
  show("how many messages each call to that task carried:", asked.map((c) => c.messages.length));
  ok(
    "the second call is not the first one sent again",
    asked.length > 1 && asked[1].messages.length > asked[0].messages.length,
    asked.map((c) => c.messages.length),
  );

  step("8. and the next station hears what it was thinking, not just what it said");
  // 同一条规矩的另一半：厂商说带 `tools` 时历史轮次的 `reasoning_content` 都该回传。
  // 库里 `thought` 一直存着，以前只是重放时不发 —— 于是下一站接手的是一份被抹掉了
  // 推导过程的历史。
  const fresh = seen.filter(
    (c) =>
      JSON.stringify(c.messages).includes(MUTE) &&
      (c.messages[c.messages.length - 1] as { role: string }).role === "user" &&
      c.messages.length > 3,
  );
  const before = fresh[0]?.messages.find((mm) => mm.role === "assistant") as
    | { content?: unknown; reasoning_content?: string }
    | undefined;
  show("what the second station was handed about the first:", before);
  ok("the next station really is a fresh question with history", fresh.length > 0, seen.length);
  ok("and the earlier thinking came along", before?.reasoning_content === THINKING, before);
  ok("together with what was actually said", JSON.stringify(before?.content ?? "").includes(WHOLE), before?.content);

  const said2 = await m.api<{ rows: { body: string }[] }>("POST", "/query", {
    sql: "select body from agent_bot_msg where instance = 't-mute#1' and role = 'assistant' order by seq",
  });
  show("what it ended up saying:", said2.rows);
  ok("and it ended up answering, instead of handing back an empty row", said2.rows.some((r) => r.body.includes(WHOLE)), said2.rows);
} finally {
  await fake.stop(true);
  m.stop();
}

done();
