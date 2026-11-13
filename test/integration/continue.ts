/**
 * Example: **continue an unfinished response**, and test **which request shapes are rejected**.
 *
 * ```
 * bun test/integration/continue.ts
 * ```
 *
 * A model often reaches its token limit mid-response and reports `finish_reason = "length"`.
 * This layer **appends the partial response and asks it to continue**, rather than asking
 * the original question again. A new answer starts from scratch and wastes the partial output.
 *
 * ## Why not call a real endpoint?
 *
 * The test concerns **what happens after rejection**, which a real endpoint rarely triggers
 * at this step. A mock chat-completions service enforces the real gateway's rule:
 *
 * > **A request ending in an assistant message asks for continuation.** Reasoning-mode
 * > prefix continuation must include `reasoning_content`; omitting it produces HTTP 400.
 *
 * This rule covers two cases with very different implications:
 *
 * | Why the request ends in an assistant message | Consequence |
 * | --- | --- |
 * | **We requested continuation** by appending partial output | Continue; if rejected, return the partial output |
 * | **The previous station ended with plain text**, without a continuation request | The assembled request shape is wrong and must be fixed |
 *
 * The second case lost a real task. `messagesOf` placed the current question **before
 * history**. If the previous station returned text without a tool call, its text ended
 * the request. The gateway treated it as continuation and rejected it; the station
 * waited until `expect_ms` and submitted nothing (cmt-3, submit#14). With a previous
 * tool call, the last message was a tool result and the shape was valid, making the
 * failure appear random.
 *
 * The mock endpoint is selected by **changing one data row**: `update api set base_url = ...`.
 * An environment variable was previously used here, allowing identical databases to behave
 * differently under different environments and preventing the database from being a snapshot.
 */

import { done, machine, ok, part, show, step, until } from "../_lib.ts";

interface Call {
  messages: { role: string; content: unknown }[];
}

/** Record every payload received by the mock endpoint for request-shape checks afterward. */
const seen: Call[] = [];

/** The actual endpoint's rejection message. */
const REFUSED = "The reasoning_content in the thinking mode must be passed back to the API.";

/** Truncate the first response halfway through. **The remaining half is never produced**, which is the case under test. */
const HALF = "The answer is 4 because ";

/** Return one complete sentence. */
const WHOLE = "Two plus two is four.";

/** Identify the task: one produced a partial sentence; the other produced no visible text. */
const CUT = "two plus two";
const MUTE = "hexagon";

/** The model used its limit on reasoning without producing any visible text. */
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

/** Each task has two stations: advance after the first, finish after the second. **Count per task, not globally**;
 * a global count would finish the second task immediately without reaching replay. */
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
    /** Is this the task's first request, including the entry just pushed? */
    const first = (mark: string) => seen.filter((c) => JSON.stringify(c.messages).includes(mark)).length === 1;

    // **The real gateway's rule:** an assistant message at the end requests continuation. In reasoning mode,
    // `reasoning_content` must accompany it; otherwise return 400. Continue if it is included.
    if (tail?.role === "assistant") {
      if (!tail.reasoning_content) {
        return new Response(JSON.stringify({ error: { message: REFUSED, type: "invalid_request_error" } }), {
          status: 400,
          headers: { "content-type": "application/json" },
        });
      }
      return reply(WHOLE, "stop");
    }
    // First request: one task is truncated mid-sentence; the other **only reasons and has no visible text**.
    if (JSON.stringify(body.messages).includes(MUTE)) {
      return first(MUTE) ? reply("", "length", THINKING) : reply(WHOLE, "stop");
    }
    return first(CUT) ? reply(HALF, "length") : reply(WHOLE, "stop");
  },
});

// **Leave `retryTimes` enabled deliberately.** The test must establish that HTTP 400 is not retried;
// disabling retries would prove nothing about error classification.
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
  // **Changing the address is a data change.** This also verifies that `api.base_url` controls the endpoint;
  // the code value is only the registration seed.
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
  // This regression covers the lost task. The previous station ends with a partial assistant response.
  // If this round's question is placed **before history**, that partial response ends the request,
  // the gateway interprets it as continuation and returns 400, and throwing at round 0 loses the whole task.
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
  // HTTP 400 means the request itself is invalid. Repeating it a hundred times yields the same 400;
  // retries only waste time before failing identically. A real run lost 30 seconds to 0+5+10+15 backoff,
  // then left the station idle until expect_ms. The `api.retry_on` column decides which errors merit retries.
  const refused = seen.filter((c) => c.messages[c.messages.length - 1]?.role === "assistant");
  show("how many times the refused shape went out:", refused.length);
  ok(
    "it went out once, not once per retry - retryTimes is 3 here",
    refused.length === 1,
    refused.length,
  );
  step("7. it hit the limit while still thinking - the thinking is what gets carried back");
  // **This regression distinguishes truncation from a dropped connection.** Often the token limit is reached
  // before any visible text is produced. Requiring visible output would repeat the original question unchanged,
  // which is connection-recovery behavior already handled elsewhere. In the observed retry, the reasoning
  // **began word-for-word identically** to the discarded reasoning: identical input followed the same path into the same limit.
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
  // The other half of the same rule: the provider requires historical `reasoning_content` whenever `tools` is supplied.
  // `thought` was always stored in the database but omitted from replay, so the next station inherited history
  // with its derivation removed.
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
