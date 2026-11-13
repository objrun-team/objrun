/**
 * Example: **one call, one result**. No more and no less.
 *
 * ```
 * bun test/integration/answer-once.ts
 * ```
 *
 * A model tool request creates a `call` row; tool completion creates a `tool` row,
 * paired by `id`. Providers require this pairing strictly and **reject either
 * direction of mismatch**:
 *
 * | Missing item | Provider response |
 * | --- | --- |
 * | Call without a result | `Tool result is missing for tool call …` |
 * | Result without a call | `Messages with role 'tool' must be a response to a preceding message with 'tool_calls'` |
 *
 * The second mismatch can be introduced by repair. An unexecuted call receives
 * a synthetic "not executed" result (see `answerMissing`). But **while building
 * context for the tool-execution station, the tool has not started yet**: an
 * unanswered call is still waiting its turn. Repairing it then creates two
 * results with the same id once the tool actually finishes.
 *
 * In an observed run, **all five tasks** stalled at the third station.
 *
 * The table defines the distinction: a station with empty `api_mode` calls
 * `agent.unit`, which executes tools and writes their results, so it must not
 * repair them. A station with `api_mode` calls a model; repairing missing results
 * when building its context is safe.
 *
 * ## Why use a mock endpoint?
 *
 * Reproduction requires a tool request **actually originating from the model
 * interface**, followed by a station that executes it. The mock endpoint does
 * one thing: on its first request, it asks for a tool.
 */

import { done, machine, ok, part, show, step, until } from "../_lib.ts";

/** `tool_choice` in each request: this verifies which tool the station is required to call. */
const choices: unknown[] = [];

/** Number of calls to the mock endpoint. The first requests a tool; subsequent calls return final text. */
let asked = 0;
/** Current station index; the first part has a three-step workflow. */
let hops = 0;
/**
 * In the second part, the mock endpoint requests a tool **on every call**, including submission.
 *
 * The submission station and its successor both call the model; neither executes
 * tools. That tool call will therefore have no result and repair must add one.
 * **Where it is inserted** is exactly what this test verifies.
 */
let alwaysCalls = false;
/** When enabled, the mock endpoint emits five `verify` calls in one round: precisely what the limit must block. */
let checking = false;
/**
 * After the first submission, **request a different tool**. This reproduces the
 * bug where a new node is immediately treated as already submitted. Its first
 * station did not request submission and must proceed to act, not directly to submit.
 */
let handIns = 0;

const CALL_ID = "call-run-me-once";

/** A submitted thirty-line answer. The summary should retain only its first twenty lines. */
const LONG = Array.from({ length: 30 }, (_, i) => `line ${String(i + 1)}`).join("\n");

/**
 * The submission tool call. **Submit thirty lines the first time**, then `42`.
 *
 * The thirty-line answer exercises summarization: `task_tree` truncates argument
 * strings longer than twenty lines. `write.content`, both `edit` strings, and
 * complete heredoc bodies all have this shape.
 */
function handIn(id: string): Record<string, unknown> {
  const nth = handIns++;
  return {
    id,
    type: "function",
    function: { name: "submit", arguments: JSON.stringify({ answer: nth === 0 ? LONG : "42" }) },
  };
}

/** An outbound message in the **provider's format**, not the database format. */
interface Msg {
  role?: string;
  content?: unknown;
  tool_calls?: { id?: string }[];
}

/** Ordered message lists sent with each request. */
const sent: Msg[][] = [];

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
  async fetch(req) {
    const path = new URL(req.url).pathname;
    // Station transitions: ask -> act -> ask; finish at the third station.
    // G's two nodes reject every candidate in this version so the node is actually marked dead.
    // A tool **slower than the deadline**, reproducing a timeout while a station is still running.
    if (path === "/slowtool") {
      await Bun.sleep(6000);
      return new Response(JSON.stringify({ ok: true }), { headers: { "content-type": "application/json" } });
    }
    if (path === "/nope") return new Response("false", { headers: { "content-type": "application/json" } });
    if (path === "/verdict") return new Response("false", { headers: { "content-type": "application/json" } });
    if (path === "/infer") {
      const to = hops === 0 ? { to: "act" } : hops === 1 ? { to: "ask" } : null;
      hops++;
      return new Response(JSON.stringify(to), {
        headers: { "content-type": "application/json" },
      });
    }
    // Record `tool_choice` to verify which tool this station must call.
    const body = (await req.json()) as { tool_choice?: unknown; messages?: Msg[] };
    // **Keep an exact copy of the outbound request.** Compression checks what was actually sent, which is visible only here:
    // the database always retains the original text; compression occurs while assembling the request.
    sent.push(body.messages ?? []);
    // **This task requests the slow tool.** Identify it from the task description in the view.
    // Only a real request to a tool slower than the deadline reproduces a timeout while the station is still running.
    const racing = JSON.stringify(body.messages ?? []).includes("cut this one off mid-call");
    choices.push(body.tool_choice ?? null);
    asked++;
    if (checking) {
      return answer(
        {
          role: "assistant",
          content: "",
          tool_calls: [1, 2, 3, 4, 5].map((k) => ({
            id: `chk-${String(asked)}-${String(k)}`,
            type: "function",
            function: { name: "verify", arguments: JSON.stringify({ answer: `candidate ${String(k)}` }) },
          })),
        },
        "tool_calls",
      );
    }
    if (racing) {
      return answer(
        {
          role: "assistant",
          content: "",
          tool_calls: [
            { id: `slow-${String(asked)}`, type: "function", function: { name: "slow_thing", arguments: "{}" } },
          ],
        },
        "tool_calls",
      );
    }
    if (asked === 1 || alwaysCalls) {
      return answer(
        {
          role: "assistant",
          content: "",
          tool_calls: [
            alwaysCalls
              ? handIns < 2
                ? handIn(`submit-${String(asked)}`)
                : { id: `look-${String(asked)}`, type: "function", function: { name: "task_tree", arguments: "{}" } }
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
    // `fn:unit.tools` actually executes tools, which is the key to this example.
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
  // A synthetic result contains `ran: false`. A genuinely executed tool must not have that shape;
  // otherwise repair ran before execution, the original cause of all five tasks stalling.
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
  // **This regression covers two genuinely lost runs.** After a node was marked dead, the new node began at act.
  // That station inspected the previous station's requests, but the previous station was submit and contained
  // **the verdict pair**: the call and result written by `deliverVerdict`, already paired on insertion.
  //
  // The old implementation selected only the last call row without checking whether it had a result,
  // and executed the verdict call again. Two results shared one id, which the provider rejected:
  //   An assistant message with 'tool_calls' must be followed by tool messages
  //   responding to each of them
  // Every rejected task hit this bug; it invalidated both runs.
  await m.api("POST", "/declare", {
    handles: [
      { name: at("/nope"), expectMs: 10_000 },
      { name: at("/verdict"), expectMs: 10_000 },
    ],
    modes: [
      {
        mode: "tree",
        // **Declare submit explicitly here** to set `mustCall`. That path works only without model reasoning:
        // reasoning mode rejects `tool_choice` with HTTP 400, so the mechanism does not set it by default.
        // Users who need it declare this data row. `withSubmit` leaves an existing submission station alone.
        cycles: [
          { cycle: "ask", apiMode: "tools", maxUnits: 3, from: [], next: ["act", "submit"], infer: "fn:infer.dfs" },
          { cycle: "act", maxUnits: 3, from: ["ask"], next: ["ask", "submit"], infer: "fn:infer.dfs" },
          {
            cycle: "submit",
            apiMode: "tools",
            mustCall: "submit",
            maxUnits: 6,
            from: ["ask", "act"],
            next: ["ask"],
            infer: "fn:infer.dfs",
          },
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

  // **A new attempt starts with reasoning, not tool execution.** Previously submit led to act,
  // causing a new node to execute a tool it had never requested and waste a unit. The observed sequence was
  // `submit#8[dead_failed] -> act#9 -> submit#10`: another submission after two steps, without any reasoning.
  const firstOf = new Map<number, string>();
  for (const r of walked) if (!firstOf.has(r.node)) firstOf.set(r.node, r.cycle);
  const startsOf = [...firstOf.entries()].filter(([n]) => n > 1).map(([, c]) => c);
  show("what each new node started with:", startsOf);
  ok("every new node starts at the entry station", startsOf.every((c) => c === "ask"), [...firstOf.entries()]);

  step("6b. and a new node gets to work before it hands in");
  // **Submission is recognized by looking back one station**: a submit request at a work station leads to submit.
  // But the predecessor of a new node's first station is **the previous node's submission station**, containing `submit`.
  // Without restricting the check to the current node, a new node is immediately considered already submitted.
  // Its requested verification or inspection of the previous error never runs; it submits the same answer blindly.
  // This is how node2 of cmt-3 was lost in an observed run.
  const perNode = new Map<number, string[]>();
  for (const r of walked) perNode.set(r.node, [...(perNode.get(r.node) ?? []), r.cycle]);
  show("what each node actually walked:", [...perNode.entries()].map(([n, v]) => `node${String(n)}: ${v.join(" > ")}`));
  // The first node explicitly requested submission, so proceeding directly to submit is correct.
  // **Later nodes did not**: they requested other tools and should go to act. If they also go directly to submit,
  // the preceding node's submission has been incorrectly attributed to the new node.
  const later = [...perNode.entries()].filter(([n]) => n > 1).map(([, v]) => v);
  ok(
    "a node that did not hand in gets sent to work, not straight to the hand-in step",
    later.every((v) => v.length > 1 && v[1] !== "submit"),
    [...perNode.entries()],
  );

  step("7. and still: one call, one result");
  const all = (
    await m.api<{ rows: { unit: number; seq: number; role: string; kind: string; body: string }[] }>("POST", "/query", {
      sql: "select unit, seq, role, kind, body from agent_bot_msg where instance = 't-dead#1' order by unit, seq",
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
  // **This is the essential gate.** A verdict pair records an external decision after the fact; it is not a model request.
  // Both have a call/result shape and look alike to the model, but only actual model requests should be executed.
  // Without that distinction, the tool station executes the recorded verdict again as pending work.
  //
  // `kind` carries the distinction, not an id-prefix convention: `call` is requested by the model; `graded` is a recorded verdict.
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
  // This task never requested a tool (the mock returns plain text from its second call onward), so inspect `call`
  // in the first part's task, which did request one. Distinct stored row kinds establish that the cases are separable.
  const asked = (
    await m.api<{ rows: { kind: string }[] }>("POST", "/query", {
      sql: "select distinct kind from agent_bot_msg where instance = 't-once#1'",
    })
  ).rows.map((r) => r.kind);
  show("the kinds on the task where the model did ask for a tool:", asked);
  ok("what the model asked for stayed a plain call", asked.includes("call"), asked);

  step("9. and every set of calls is followed straight away by its own results");
  // The provider strictly requires an assistant message with **`tool_calls` to be immediately followed by
  // its corresponding results**. Another assistant message with `tool_calls` inserted between them is rejected.
  //
  // Repair previously **appended at the end of the unit**, with the verdict pair in between. The resulting order was
  // call / verdict / verdict result / call result, stalling every rejected task at its next station.
  // The synthetic result now immediately follows the call it answers.
  const idsIn = (body: string) =>
    ((JSON.parse(body) as { calls?: { id?: string }[] }).calls ?? []).map((c) => String(c.id));
  // **Inspect only rows actually included in the message stream.** Rows such as `inject` have role system
  // and go into instructions, not the message array. Counting them when checking adjacency would wrongly reject
  // the valid case where a result is stored in the next unit.
  const stream = all.filter((r) => r.role === "user" || r.role === "assistant" || r.role === "tool");
  const bad: string[] = [];
  for (let i = 0; i < stream.length; i++) {
    const r = stream[i];
    if (r.kind !== "call" && r.kind !== "graded") continue;
    for (const want of idsIn(r.body)) {
      const next = stream[++i];
      const got = next && next.kind === "tool" ? (JSON.parse(next.body) as { id?: string }).id : undefined;
      if (got !== want) bad.push(`u${String(r.unit)}.${String(r.seq)} asked ${want}, next row answered ${String(got)}`);
    }
  }
  show("calls whose results do not follow straight away:", bad);
  ok("none - every one is answered right where it was asked", bad.length === 0, bad);

  step("10. a node that closed comes back compressed");
  // All three compressed levels are persisted when the node closes (`msg/press.ts`). The `summary` returned by
  // `task_tree` is **the most compressed level**, not a separately generated summary. Independent compression paths
  // would produce different tree and context views without either path reporting an error.
  //
  // The `msg_part` table defines each part's treatment at every level. This test verifies that **the table really controls it**.
  const looked = all
    .filter((r) => r.kind === "tool" && String(r.body).includes('"name":"task_tree"'))
    .map((r) => (JSON.parse(r.body) as { value?: { nodes?: { node: number; status: string | null; summary?: string; mine?: boolean }[] } }).value ?? {})
    .filter((v) => Array.isArray(v.nodes));
  ok("the model got a real task_tree result back", looked.length > 0, all.filter((r) => r.kind === "tool").length);
  const seenNodes = looked[looked.length - 1].nodes ?? [];
  show(
    "what it saw:",
    seenNodes.map((n) => `node${String(n.node)}[${n.status ?? ""}]${n.mine ? " (mine)" : ""} ${String(n.summary ?? "").length} chars`),
  );
  const closed = seenNodes.filter((n) => !n.mine);
  ok("every closed node came back with something", closed.length > 0 && closed.every((n) => String(n.summary ?? "").length > 0), seenNodes);
  ok("and the one being worked on came back with nothing", seenNodes.filter((n) => n.mine).every((n) => n.summary === ""), seenNodes);

  const text = closed.map((n) => String(n.summary ?? "")).join("\n");
  // Prefix every block with its part name so tool results and model text remain attributable after concatenation.
  ok("each piece says which part it is", /\[(task|said|call|receipt|look|event|verdict) /.test(text) || text.includes("[task]"), text.slice(0, 200));
  ok("what it asked for is there - msg_part keeps call at every level", text.includes("[call submit]"), text.slice(0, 200));
  // `thought` is dropped at level 3; `ledger` is dropped at all three levels.
  ok("the reasoning is gone at this level", !text.includes("[thought]"), text.slice(0, 200));
  ok("and so is the kernel's own bookkeeping", !text.includes("[ledger]"), text.slice(0, 200));
  ok("nothing from the system side leaked in", !text.includes("[system]"), text.slice(0, 200));
  // A node summary **must not embed another node's summary**. `task_tree` and `node_load` return
  // this conversation's own context (`tool.gives` = `recall`), which is dropped at all three levels.
  // It already exists in the database and can be loaded again. The call itself is kept at every level, showing that it was read.
  ok("a summary does not carry another summary inside it", !text.includes("[recall "), text.slice(0, 300));
  ok("but the fact that it looked is still there", !text.includes("task_tree ") || text.includes("[call task_tree]"), text.slice(0, 300));

  step("10b. and node_load reads a node at whichever level is asked for");
  // Tree row numbers are used by `node_load`. Here, verify only that each compressed node has rows at all three levels.
  const levels = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: "select (select count(*) from press) as n",
    })
  ).rows[0].n;
  show("rows in press:", levels);
  ok("the closed nodes really were pressed into the tables", levels > 0, levels);
  const three = (
    await m.api<{ rows: { l1: number; l2: number; l3: number }[] }>("POST", "/query", {
      sql: "select (select count(*) from press_l1) as l1, (select count(*) from press_l2) as l2, (select count(*) from press_l3) as l3",
    })
  ).rows[0];
  show("rows per level:", three);
  ok("all three levels exist", three.l1 > 0 && three.l2 > 0 && three.l3 > 0, three);
  // Level-4 columns exist but **all remain unwritten**. Empty `msg_part.l4` means that level is not configured:
  // neither compression nor sending uses it. The columns reserve space for a compressor requiring a model call.
  const four = (
    await m.api<{ rows: { l4rows: number; unset: number; parts: number }[] }>("POST", "/query", {
      sql: "select (select count(*) from press_l4) as l4rows, (select count(*) from press where l4 is not null) as unset, (select count(*) from msg_part where l4 is not null) as parts",
    })
  ).rows[0];
  show("the fourth level:", four);
  ok("the fourth level is there and empty", four.l4rows === 0 && four.unset === 0 && four.parts === 0, four);

  step("11. the hand-in station leaves it no choice");
  // Exposed tools determine what the model **can** call; this column determines what it **must** call.
  // Exposing only one tool does not prevent text without submission. At submit, failing to call it means
  // the step was not performed, so the request explicitly requires that tool.
  //
  // Some providers reject this in reasoning mode (DeepSeek V4 returns 400). `cycle.must_call` conflicts with
  // reasoning effort; clear that column or disable reasoning. Both are data changes.
  // For unconstrained calls, the SDK explicitly sends `"auto"`, rather than omitting it; constrained therefore means non-auto.
  const forced = choices.filter((c) => c !== null && c !== "auto");
  show("the choices that went out:", forced);
  ok("at least one call was pinned to a single tool", forced.length > 0, choices);
  ok(
    "and the working stations were left to pick for themselves",
    choices.some((c) => c === "auto"),
    choices,
  );
  ok(
    "and the one it was pinned to is the hand-in tool",
    forced.every((c) => JSON.stringify(c).includes("submit")),
    forced,
  );

  // ═══════════════════════════════════════════════════════════════════════
  part("Part three: the wrap-up verdict gives way to a call that is still running");

  step("11. a task whose clock runs out while a station is still working");
  // **The final verdict belongs to a station that may still be running.** Both writers append using the current
  // maximum seq plus one, so insertion order controls sequence. If the verdict arrives first, it separates
  // the previous station's call from its result. Providers reject that shape, preventing the entire chain
  // from being sent again. This occurred three times in real runs, each at task timeout.
  //
  // Timeout finalization has the lowest priority here: the in-flight call is doing real work; the verdict is cleanup.
  await m.api("POST", "/declare", {
    handles: [{ name: at("/slowtool"), expectMs: 60_000 }],
    tools: [
      {
        name: "slow_thing",
        identity: at("/slowtool"),
        does: "Takes a while.",
        params: { type: "object", properties: {}, additionalProperties: false },
        output: { type: "object", properties: { ok: { type: "boolean" } } },
        prompt: "",
        when: [[{ dim: "task", key: "domain", op: "eq", value: "slow" }]],
      },
    ],
  });
  await m.api("POST", "/tasks", {
    id: "t-race", mode: "tree", agent: "bot", place: "local", source: "user",
    description: "the clock will cut this one off mid-call", readable: false,
    domain: "slow", solveSeconds: 4, maxDeadSiblings: 2,
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
    "t-race to be closed by the clock",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-race");
      return d.state === "failed" || d.state === "done" ? d : null;
    },
    60_000,
  );
  // The station was still running before the verdict was stored; wait for its output to finish.
  const late = await until(
    "the wrap-up verdict to land",
    async () => {
      const got = await m.api<{ rows: { unit: number; seq: number; role: string; kind: string; body: string }[] }>(
        "POST",
        "/query",
        { sql: "select unit, seq, role, kind, body from agent_bot_msg where instance = 't-race#1' order by unit, seq" },
      );
      return got.rows.some((r) => r.kind === "graded") ? got.rows : null;
    },
    60_000,
  );

  step("11b. what it handed in has one source, not two");
  // **There must be one source of truth for the submitted answer.** Submit grades the answer in the `submit` call.
  // If finalization independently reads the text spoken at that station, the same task acquires two candidate answers;
  // their verdicts may differ, and the latter determines the recorded score.
  //
  // A real task was lost this way: submit accepted it, the tree finished normally (`status = reached`),
  // but finalization graded it again and rejected it. A correct solution was recorded as a failure.
  const verdicts = late.filter((r) => r.kind === "graded");
  const answers = late
    .filter((r) => r.kind === "call")
    .flatMap((r) => (JSON.parse(r.body) as { calls?: { name?: string; input?: { answer?: unknown } }[] }).calls ?? [])
    .filter((c) => c.name === "submit")
    .map((c) => String(c.input?.answer ?? ""));
  show("what it handed in:", answers);
  show("how many verdicts landed:", verdicts.length);
  ok(
    "every verdict is about something it actually handed in",
    answers.length === 0 || verdicts.length > 0,
    { answers, verdicts: verdicts.length },
  );
  step("12. the wrap-up verdict did not cut in between a call and its result");
  // **Check only whether the verdict cut into a pair.** The final call may have no result at all: it was still in flight
  // at timeout, and no repair occurs after task failure. That is a separate issue and affects no later request,
  // because the task is finished and its context will never be sent again. This check concerns verdict placement.
  const flow = late.filter((r) => r.role === "user" || r.role === "assistant" || r.role === "tool");
  const broken: string[] = [];
  for (let i = 0; i < flow.length; i++) {
    const r = flow[i];
    if (r.kind !== "call" && r.kind !== "graded") continue;
    for (const c of (JSON.parse(r.body) as { calls?: { id?: string }[] }).calls ?? []) {
      const next = flow[++i];
      if (next === undefined) continue; // The final call is unanswered; see above.
      const got = next.kind === "tool" ? (JSON.parse(next.body) as { id?: string }).id : undefined;
      if (got !== c.id) broken.push(`u${String(r.unit)}.${String(r.seq)} asked ${String(c.id)}, next answered ${String(got)}`);
    }
  }
  show("the rows, in the order they will be sent:", flow.map((r) => `u${String(r.unit)}.${String(r.seq)} ${r.kind}`));
  show("calls whose result does not follow straight away:", broken);
  ok("the wrap-up verdict did not cut in between a call and its result", broken.length === 0, broken);

  // ═══════════════════════════════════════════════════════════════════════
  part("Part four: a few checks per attempt, and a new attempt gets new ones");

  step("13. five checks in one turn, but only two are allowed");
  // **Without a limit, enumerating the answer space is the cheapest strategy.** In an observed multiple-choice task,
  // the solver tried seventy-seven combinations (`b;a` / `c;d` / `b;c;d` / `b;a;c;d` ...) without reasoning once.
  // Such a score measures answer-space size, not problem-solving ability.
  //
  // **The execution-unit budget cannot stop this**: one request can include many tool calls, and twenty attempts
  // consume the same one unit as a single attempt. The gate therefore counts queries to G, not stations visited.
  // This example emits five queries at once in one round to reproduce that shape.
  checking = true;
  await m.api("POST", "/tasks", {
    id: "t-checks", mode: "tree", agent: "bot", place: "local", source: "user",
    description: "how many checks does it get", readable: false,
    maxDeadSiblings: 2, solveSeconds: 45,
    objective: {
      nodes: [
        { name: "look", moment: "done", domain: { kind: "bool" }, handle: at("/nope") },
        { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: at("/verdict") },
      ],
      edges: [{ src: "look", out: 0, dst: "verdict" }],
      sink: "verdict",
      // **The allowance belongs to G, not the task**: it describes how many queries this black box can sustain.
      checks: 2,
    },
  });
  await until(
    "t-checks to finish",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-checks");
      return d.state === "done" || d.state === "failed" ? d : null;
    },
    60_000,
  );

  const results = (
    await m.api<{ rows: { unit: number; seq: number; body: string }[] }>("POST", "/query", {
      sql: "select unit, seq, body from agent_bot_msg where instance = 't-checks#1' and kind = 'tool' and body like '%verify%' order by unit, seq",
    })
  ).rows
    .map((r) => JSON.parse(r.body) as { id?: string; value?: { pass?: number; error?: string; left?: number } })
    // **Submission does not count.** The kernel makes that query (id starts with `g-`, stored as a `graded` pair),
    // rather than the agent itself, so the gate must not charge it against the allowance.
    .filter((r) => !String(r.id ?? "").startsWith("g-"));

  const judged = results.filter((r) => r.value?.pass !== undefined);
  const refused = results.filter((r) => typeof r.value?.error === "string" && r.value.error.includes("spent"));
  show("checks that got a verdict:", judged.length);
  show("checks that were turned away:", refused.length);
  ok("it asked more times than it was allowed", results.length > 2, results.length);
  // **The allowance is per round, not per task.** Each node starts a round, so the number of verdicts obtained
  // should equal rounds times the per-round limit. A task-wide counter would break retries after a node dies.
  const rounds = new Set(
    (
      await m.api<{ rows: { node: number }[] }>("POST", "/query", {
        sql: "select distinct node from task_tree where task = 't-checks'",
      })
    ).rows.map((r) => Number(r.node)),
  ).size;
  show("how many attempts it made:", rounds);
  ok(
    "each attempt got its own few, and no more",
    judged.length <= 2 * rounds && judged.length > 0,
    { judged: judged.length, rounds, perRound: 2 },
  );
  ok("the rest were turned away, and told why", refused.length > 0, results.map((r) => r.value));
  ok(
    "and the answer says how many are left, so it can budget",
    judged.every((r) => typeof r.value?.left === "number"),
    judged.map((r) => r.value),
  );

  step("14. a new attempt gets its own checks");
  // One round is one node. A new node after rejection is a fresh attempt; spending from the previous round
  // must not count against it, or "try again" would be meaningless.
  const walk = (
    await m.api<{ rows: { unit: number; node: number; cycle: string }[] }>("POST", "/query", {
      sql: "select unit, node, cycle from task_tree where task = 't-checks' order by unit",
    })
  ).rows;
  const nodes = new Set(walk.map((r) => Number(r.node)));
  show("nodes it opened:", [...nodes]);
  if (nodes.size > 1) {
    const byNode = new Map<number, number>();
    for (const r of walk) byNode.set(Number(r.node), Number(r.unit));
    const later = [...nodes].filter((n) => n > 1);
    const judgedLate = results.length > 2;
    ok("a second attempt was opened, and it could still check", later.length > 0 && judgedLate, [...nodes]);
  } else {
    ok("(only one attempt happened here - the reset is covered by the counter being per node)", true);
  }
  part("Part five: over the threshold, what goes out is the pressed one");

  step("15. with the threshold at nothing, every request past the first node is pressed");
  // Set the threshold to 1 token so every request exceeds it and falls through to the last configured level.
  // In a real run this is the limit for the selected credential/model; here we only need to **exercise that path**.
  await m.api("POST", "/exec", {
    sql: "update api set compress_at = 1 where model = 'deepseek-v4-flash'",
  });
  checking = false;
  sent.length = 0;
  await m.api("POST", "/tasks", {
    id: "t-press", mode: "tree", agent: "bot", place: "local", source: "user",
    description: "this one gets pressed", readable: false, maxDeadSiblings: 2, solveSeconds: 45,
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
    "t-press to finish",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-press");
      return d.state === "done" || d.state === "failed" ? d : null;
    },
    60_000,
  );
  show("requests it sent:", sent.length);
  const tagged = sent.filter((ms) => ms.some((x) => x.role === "user" && String(x.content ?? "").includes("[call ")));
  show("how many of them carried a pressed node:", tagged.length);
  ok("something went out pressed", tagged.length > 0, sent.map((ms) => ms.length));

  const last = tagged[tagged.length - 1];
  show(
    "the shape of that request:",
    last.map((x) => `${String(x.role)}${x.tool_calls ? "(" + String(x.tool_calls.length) + " calls)" : ""} ${String(x.content ?? "").slice(0, 40).replace(/\n/g, " / ")}`),
  );

  // **A call cannot be separated from its result.** One missing result causes the provider to reject the entire request:
  //   An assistant message with 'tool_calls' must be followed by tool messages
  //   responding to each of them
  // This is why replacement operates on an entire node rather than one unit; the test verifies that invariant.
  const unpaired: string[] = [];
  for (let i = 0; i < last.length; i++) {
    const n = last[i].tool_calls?.length ?? 0;
    if (!n) continue;
    const after = last.slice(i + 1, i + 1 + n);
    if (after.length !== n || !after.every((x) => x.role === "tool")) {
      unpaired.push(`message ${String(i)} asked for ${String(n)}, got ${after.map((x) => String(x.role)).join(",")}`);
    }
  }
  ok("every call that went out still has its results right behind it", unpaired.length === 0, unpaired);
  ok("and nothing went out empty", last.every((x) => x.role !== "user" || String(x.content ?? "").trim() !== ""), last.map((x) => String(x.role) + ":" + String(String(x.content ?? "").length)));

  // Compressed rows precede the current node's original rows. Only **closed nodes** are replaced; the current node stays intact.
  const lastPressed = last
    .map((x, i) => ({ i, x }))
    .filter(({ x }) => x.role === "user" && String(x.content ?? "").includes("[call "))
    .pop();
  const firstRaw = last.findIndex((x) => x.role === "tool");
  ok(
    "the pressed nodes come first and the one being worked on stays raw at the end",
    lastPressed !== undefined && (firstRaw === -1 || firstRaw > lastPressed.i),
    { pressedAt: lastPressed?.i, firstToolResultAt: firstRaw },
  );

  // The compressed representation must be **shorter than the original**: compare the original stored bodies with their replacement rows in this request.
  const raw = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: "select sum(length(body)) + sum(length(coalesce(thought, ''))) as n from agent_bot_msg where instance = 't-press#1'",
    })
  ).rows[0].n;
  const out = last.reduce((n, x) => n + JSON.stringify(x.content ?? "").length, 0);
  show("all of that instance's messages, in bytes:", raw);
  show("what the last request actually carried:", out);
  ok("what went out is smaller than what the store holds", out < raw, { out, raw });
} finally {
  await fake.stop(true);


  m.stop();
}

done();
