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
/** 走到第几站了 —— 第一部分的流转就三步。 */
let hops = 0;
/**
 * 第二部分开始之后，假端点**每一次都要一次工具**（交卷那一次也要）。
 *
 * 交卷站是模型站，它的下一站也是模型站 —— 没有人跑工具。所以那次调用注定没有
 * 结果，补齐会给它补一条。**补在哪儿**正是要验的事。
 */
let alwaysCalls = false;

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
    // G 的两个节点：这一版看什么都说「不成」，好让节点真的被判死。
    if (path === "/nope") return new Response("false", { headers: { "content-type": "application/json" } });
    if (path === "/verdict") return new Response("false", { headers: { "content-type": "application/json" } });
    if (path === "/infer") {
      const to = hops === 0 ? { to: "act" } : hops === 1 ? { to: "ask" } : null;
      hops++;
      return new Response(JSON.stringify(to), {
        headers: { "content-type": "application/json" },
      });
    }
    asked++;
    if (asked === 1 || alwaysCalls) {
      return answer(
        {
          role: "assistant",
          content: "",
          tool_calls: [
            alwaysCalls
              ? { id: `submit-${String(asked)}`, type: "function", function: { name: "submit", arguments: "{}" } }
              : { id: CALL_ID, type: "function", function: { name: "glob", arguments: JSON.stringify({ pattern: "*.md" }) } },
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

  // ═══════════════════════════════════════════════════════════════════════
  part("Part two: the verdict is a call that already has its answer - nobody re-runs it");

  step("5. a tree whose grading function always says no, so a node really dies");
  alwaysCalls = true;
  // **这一条焊的是真丢过的两跑。** 判死之后开新节点，新节点的第一站是动作站
  // （跑工具的那个）。它去看上一站请求了什么 —— 而上一站是交卷站，那儿躺着
  // **判决那一对**：`deliverVerdict` 写的「调用 + 结果」，结果当场就配好了。
  //
  // 原先那一版只看「最后一条 call 行」、也不管答没答过，于是把判决那次调用又跑了
  // 一遍。同一个 id 两条结果，模型那边直接拒：
  //   An assistant message with 'tool_calls' must be followed by tool messages
  //   responding to each of them
  // 每一道判死的题都会中招，两跑都是这么废的。
  await m.api("POST", "/declare", {
    handles: [
      { name: at("/nope"), expectMs: 10_000 },
      { name: at("/verdict"), expectMs: 10_000 },
    ],
    modes: [
      {
        mode: "tree",
        cycles: [
          { cycle: "ask", apiMode: "tools", maxUnits: 3, from: [], next: ["act"], infer: "fn:infer.dfs" },
          { cycle: "act", maxUnits: 3, from: ["ask"], next: ["ask"], infer: "fn:infer.dfs" },
        ],
      },
    ],
  });
  await m.api("POST", "/tasks", {
    id: "t-dead", mode: "tree", agent: "bot", place: "local", source: "user",
    description: "this one never passes", readable: false, maxDeadSiblings: 2, solveSeconds: 60,
    objective: {
      nodes: [
        { name: "look", moment: "done", domain: { kind: "bool" }, handle: at("/nope") },
        { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: at("/verdict") },
      ],
      edges: [{ src: "look", out: 0, dst: "verdict" }],
      sink: "verdict",
    },
  });
  await until(
    "t-dead to finish",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-dead");
      return d.state === "done" || d.state === "failed" ? d : null;
    },
    50_000,
  );

  step("6. a node really died, so the situation actually happened");
  const walked = (
    await m.api<{ rows: { cycle: string; unit: number; node: number; status: string | null }[] }>("POST", "/query", {
      sql: "select cycle, unit, node, status from task_tree where task = 't-dead' order by unit",
    })
  ).rows;
  show(
    "the stations it walked:",
    walked.map((r) => `${r.cycle}#${String(r.unit)}@node${String(r.node)}${r.status ? "[" + r.status + "]" : ""}`),
  );
  ok("one of them was declared dead", walked.some((r) => r.status === "dead_failed"), walked);
  ok("and a second node was opened after it", new Set(walked.map((r) => r.node)).size > 1, walked);

  // **一次新的尝试从想事情开始，不从跑工具开始。** 上一版交卷之后接的是动作站，
  // 于是新节点上来就去跑一遍自己从没请求过的工具，白花一格 —— 实测的样子是
  // `submit#8[dead_failed] → act#9 → submit#10`：两步就又交了一次，中间一次都没想过。
  const firstOf = new Map<number, string>();
  for (const r of walked) if (!firstOf.has(r.node)) firstOf.set(r.node, r.cycle);
  const later = [...firstOf.entries()].filter(([n]) => n > 1).map(([, c]) => c);
  show("what each new node started with:", later);
  ok("every new node starts at the entry station", later.every((c) => c === "ask"), [...firstOf.entries()]);

  step("7. and still: one call, one result");
  const all = (
    await m.api<{ rows: { unit: number; seq: number; kind: string; body: string }[] }>("POST", "/query", {
      sql: "select unit, seq, kind, body from agent_bot_msg where instance = 't-dead#1' order by unit, seq",
    })
  ).rows;
  const seen = new Map<string, number>();
  for (const r of all) {
    if (r.kind !== "tool") continue;
    const id = (JSON.parse(r.body) as { id?: string }).id ?? "";
    seen.set(id, (seen.get(id) ?? 0) + 1);
  }
  const twice = [...seen.entries()].filter(([, n]) => n > 1);
  show("results per call:", [...seen.entries()].map(([id, n]) => `${id.slice(0, 24)}: ${String(n)}`));
  ok("no call was answered twice - the verdict's own call was left alone", twice.length === 0, twice);

  step("8. and that is because the two are different kinds of row");
  // **这才是那道闸。** 判决那一对是系统事后记下的一次外部裁决，不是模型的请求 ——
  // 两者都长成「调用 + 结果」，模型读起来也一样，但只有前者该被人去跑。分不开的
  // 话，跑工具那一站会把判决当成一次待办的请求又执行一遍。
  //
  // 分法写在 `kind` 上，不靠 id 前缀那种约定：`call` 是模型要的，`graded` 是记下的。
  const byKind = new Map<string, number>();
  for (const r of all) byKind.set(r.kind, (byKind.get(r.kind) ?? 0) + 1);
  show("the kinds in that instance:", [...byKind.entries()].map(([k, n]) => `${k}: ${String(n)}`));
  ok("the verdict went in as its own kind", (byKind.get("graded") ?? 0) > 0, [...byKind.keys()]);
  const graded = all.filter((r) => r.kind === "graded");
  ok(
    "and every one of them names the grading tool",
    graded.every((r) => String(r.body).includes('"name":"verify"')),
    graded.map((r) => String(r.body).slice(0, 60)),
  );
  // 这道题里模型一次工具都没要（假端点第二次起就说白话），所以 `call` 得去第一
  // 部分那个任务里看 —— 那儿模型真要过一次。两种行分别存在，才叫分得开。
  const asked = (
    await m.api<{ rows: { kind: string }[] }>("POST", "/query", {
      sql: "select distinct kind from agent_bot_msg where instance = 't-once#1'",
    })
  ).rows.map((r) => r.kind);
  show("the kinds on the task where the model did ask for a tool:", asked);
  ok("what the model asked for stayed a plain call", asked.includes("call"), asked);

  step("9. and every set of calls is followed straight away by its own results");
  // 模型那边这条规矩是死的：**带 `tool_calls` 的那条助手消息，后面紧接着就得是
  // 它那几条结果**。中间夹一条别的带 `tool_calls` 的助手消息就直接拒。
  //
  // 补齐原先是**追加到这一格末尾**的，而判决那一对正好插在中间，于是顺序成了
  // 「调用 / 判决 / 判决的结果 / 调用的结果」—— 每一道判死的题都在下一站卡住。
  // 现在补的那条紧跟在它答的那次调用后面。
  const idsIn = (body: string) =>
    ((JSON.parse(body) as { calls?: { id?: string }[] }).calls ?? []).map((c) => String(c.id));
  const bad: string[] = [];
  for (let i = 0; i < all.length; i++) {
    const r = all[i];
    if (r.kind !== "call" && r.kind !== "graded") continue;
    for (const want of idsIn(r.body)) {
      const next = all[++i];
      const got = next && next.kind === "tool" ? (JSON.parse(next.body) as { id?: string }).id : undefined;
      if (got !== want) bad.push(`u${String(r.unit)}.${String(r.seq)} asked ${want}, next row answered ${String(got)}`);
    }
  }
  show("calls whose results do not follow straight away:", bad);
  ok("none - every one is answered right where it was asked", bad.length === 0, bad);
} finally {
  await fake.stop(true);

  m.stop();
}

done();
