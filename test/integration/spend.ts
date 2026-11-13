/**
 * Example: **persist both reasoning and usage in the database**.
 *
 * ```
 * bun test/integration/spend.ts
 * ```
 *
 * The snapshot once omitted **all per-call usage**. A real run averaged 174 seconds
 * from dispatch to response but only 350 visible output tokens, apparently two
 * tokens per second. No model was actually that slow: the long interval was spent
 * reasoning, but `reasoning_content` was **discarded after reading**. Whether the
 * deadline was sufficient could only be inferred, never measured directly.
 *
 * The existing decision to keep reasoning out of `body` remains: `body` is the
 * **replay representation**, and some gateways reject assistant messages containing
 * reasoning. These concerns are therefore stored separately:
 *
 * - `body`: unchanged, preserving replay behavior.
 * - `thought` and four counters: stored without being sent back.
 *
 * This test verifies both sides: usage is persisted, and reasoning does not leak into `body`.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** Mock the adapter: return both text and usage, using the same fields as the real adapter. */
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
  // Reasoning mixed into `body` would be replayed verbatim as model speech, which some gateways reject.
  // This assertion protects that replay path.
  ok("body is only what was spoken", said?.body === "the ground state energy is -U0/4", said?.body);
  ok("body carries no thinking", !(said?.body ?? "").includes("strong coupling"), said?.body);

  step("4. a row no model call produced keeps the columns empty");
  // **Missing usage is null, not 0**. Zero would make an unreported call indistinguishable from
  // a call that genuinely consumed no tokens.
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
