/**
 * Example: **who sees `web_search`, and what it returns**.
 *
 * ```
 * bun test/integration/search.ts
 * ```
 *
 * Unlike other tools, this one **makes a model call itself**. Provider-side search
 * uses `/responses`; the usual `/chat/completions` endpoint rejects
 * `type: "web_search"` (`unknown variant 'web_search', expected 'function'`).
 * A small mock server therefore supplies both paths, selected by changing one
 * `api.base_url` data row.
 *
 * Three invariants:
 *
 * 1. **Tool exposure is data-controlled**: the two same-group trigger conditions
 *    require search support and a station other than submit.
 * 2. **The result contains more than an answer**: queries and visited pages provide
 *    the entire basis for subsequent auditing.
 * 3. **Search without an answer must still be explained**: a real request consumed
 *    180,000 tokens with no answer. Its actions were more useful than a generic failure message.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

// A credential must be present or the tool reports no available search service. The mock does not inspect it.
process.env.DEEPSEEK_API_KEY ??= "sk-not-a-real-key";

const m = await machine();

/** Which query this unit should request, distinguishing the answer and no-answer paths. */
let ask = "how many KT transitions does the triangular lattice TFIM have?";

/** Record each mock request's `input` and reasoning effort. */
const sent: { role?: string; content?: string }[][] = [];
const efforts: string[] = [];

const out = await outside({
  /** Mock `/chat/completions`: immediately request `web_search`. */
  "/chat/completions": () => ({
    id: "fake-1",
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: "deepseek-v4-flash",
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call_search_1",
              type: "function",
              function: { name: "web_search", arguments: JSON.stringify({ question: ask }) },
            },
          ],
        },
        finish_reason: "tool_calls",
      },
    ],
    usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
  }),

  /** Mock `/responses` in the **exact real response shape**; an incorrect mock shape would invalidate the regression. */
  "/responses": (a) => {
    // Record every request; step 8 checks whether the previous conversation was included.
    const raw = (a as { input?: unknown }).input;
    const input = (Array.isArray(raw) ? raw : [{ role: "user", content: String(raw ?? "") }]) as {
      role?: string;
      content?: string;
    }[];
    sent.push(input);
    const asked = input.map((x) => String(x.content ?? "")).join(" ");
    const effort = String((a as { reasoning_effort?: unknown }).reasoning_effort ?? "");
    efforts.push(effort);
    // Disallowed-source case: the answer text is clean, but **the visited pages reveal the violation**.
    // The gate inspects the whole response, not just the answer.
    if (asked.includes("forbidden")) {
      return {
        status: "completed",
        output: [
          { type: "web_search_call", action: { type: "open_page", url: "https://hf-mirror.com/datasets/somebody/secret_answers/raw/main/data.jsonl" } },
          { type: "message", content: [{ type: "output_text", text: "The answer is 42." }] },
        ],
        usage: { input_tokens: 1, output_tokens: 1, total_tokens: 999 },
      };
    }
    // The search-completed-without-an-answer case.
    if (asked.includes("nothing")) {
      return {
        status: "completed",
        output: [
          { type: "reasoning", content: [{ type: "reasoning_text", text: "looking" }] },
          { type: "web_search_call", action: { type: "search", queries: ["nothing at all"] } },
        ],
      };
    }
    return {
      status: "completed",
      output: [
        {
          type: "web_search_call",
          // The second entry is the provider's internal marker, not a search query. Real responses consistently included one.
          action: { type: "search", queries: ["two KT transitions triangular lattice", "ws_call_id=call_00_abc"] },
        },
        // Transitional text is **also a message**. The answer is the last message; selecting the wrong one returns this text.
        { type: "message", content: [{ type: "output_text", text: "Let me look this up." }] },
        {
          type: "web_search_call",
          action: { type: "open_page", url: "https://arxiv.org/abs/1909.03608#ws_call_id=call_07_abc" },
        },
        {
          type: "message",
          content: [{ type: "output_text", text: "Two, per Isakov & Moessner, PRB 68, 104409 (2003)." }],
        },
      ],
      usage: { input_tokens: 64351, output_tokens: 7916, total_tokens: 72267 },
    };
  },

  // ask -> act -> ask ..., stopping at the unit limit. **The second round is the point of step 7**:
  // with only one round, the over-limit rejection assertion is vacuously true for an empty array and proves nothing.
  "/infer": (u) => (String((u as { cycle?: { cycle?: string } }).cycle?.cycle) === "ask" ? "act" : "ask"),
});

/** Result of the task's `web_search` call after completion. */
async function resultOf(task: string): Promise<Record<string, unknown>> {
  const rows = (
    await m.api<{ rows: { body: string }[] }>("POST", "/query", {
      sql: `select body from agent_bot_msg where instance = '${task}#1' and kind = 'tool' order by unit, seq`,
    })
  ).rows;
  for (const r of rows) {
    const v = JSON.parse(r.body) as { name?: string; value?: Record<string, unknown> };
    if (v.name === "web_search") return v.value ?? {};
  }
  return {};
}

try {
  part("web_search: who gets it, and what it hands back");

  step("1. point the api row at the fake endpoint - data, not code");
  // `api.base_url` is **a table column**. The tool derives `/responses` from it, and the adapter derives
  // `/chat/completions`. Updating one data row redirects both paths together, which is precisely why
  // the endpoint moved from code into the table.
  await m.api("POST", "/exec", {
    sql: `update api set base_url = '${out.url("")}' where model = 'deepseek-v4-flash'`,
  });

  step("2. a mechanism with a thinking station and a tool-running station");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "one",
        cycles: [
          // **Exercise the loop**: ask -> act -> ask ..., stopping at the unit budget. Step 7 requires a second round;
          // one round would make the over-limit rejection assertion vacuously true for an empty array.
          { cycle: "ask", apiMode: "chat", maxUnits: 3, from: [], next: ["act"], infer: out.url("/infer") },
          { cycle: "act", maxUnits: 3, from: ["ask"], next: ["ask"], infer: out.url("/infer") },
        ],
      },
    ],
    agents: [
      // `unit` is the handle used by the **tool-execution station**, selected when `api_mode` is empty.
      { name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" },
      // **The agent behind this tool** controls its model, endpoint, and reasoning effort through its own row,
      // independently of the caller's row. Retrieval has a fixed job: find information and explain it, without additional reasoning.
      {
        name: "searcher",
        apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]],
        unit: "fn:unit.tools",
        knobs: { reasoningEffort: "none" },
      },
    ],
  });

  step("3. the distribution table decides who sees it");
  const terms = (
    await m.api<{ rows: { dim: string; key: string; op: string; value: string }[] }>("POST", "/query", {
      sql: "select dim, key, op, value from trigger where owner_kind = 'tool' and owner = 'web_search' order by dim",
    })
  ).rows;
  show("what trigger says about web_search:", terms);
  ok(
    "offered only where the vendor searches",
    terms.some((t) => t.dim === "agent" && t.key === "apis" && t.op === "contains"),
    terms,
  );
  ok(
    "and never at the hand-in station",
    terms.some((t) => t.dim === "cycle" && t.op === "ne" && t.value === "submit"),
    terms,
  );
  // Two conditions in the **same group** mean AND. Separate groups would mean search support **or** not being at submit,
  // exposing the tool at submit as well, which this condition must prevent.
  const groups = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: `select count(distinct "group") as n from trigger where owner_kind = 'tool' and owner = 'web_search'`,
    })
  ).rows[0].n;
  ok("both terms sit in one group, so they are AND not OR", Number(groups) === 1, groups);

  step("4. run a task: it asks to search, the action station does it");
  await m.api("POST", "/tasks", {
    id: "t-search", mode: "one", agent: "bot", place: "local", source: "user",
    description: "look something up", solveSeconds: 60,
  });
  await until("t-search to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const got = (await resultOf("t-search")) as {
    answer?: string; queries?: string[]; opened?: string[]; searches?: number;
    spent?: { total_tokens?: number };
  };
  show("what it handed back:", got);
  // **Only the last message is the answer**. The earlier "Let me look this up." is transitional text;
  // choosing it would return an uninformative phrase that superficially looks like an answer.
  ok("the answer is the last thing it said", String(got.answer).includes("Isakov"), got.answer);
  ok("not the small talk on the way there", !String(got.answer).includes("Let me look"), got.answer);
  ok("the queries it ran are recorded", (got.queries ?? []).length === 1, got.queries);
  // A provider-internal identifier is not a query. Retaining it would insert identifier rows throughout
  // the list used to audit what was searched.
  ok("and its call ids are not mistaken for queries", !(got.queries ?? []).some((q) => q.startsWith("ws_call_id")), got.queries);
  // The URL fragment `#ws_call_id=...` is the provider's marker, not part of the resource address.
  // Keeping it would prevent exact matching when auditing access to reference-answer sources.
  ok(
    "the pages it opened are recorded, without the call-id tag",
    (got.opened ?? [])[0] === "https://arxiv.org/abs/1909.03608",
    got.opened,
  );
  ok("and how many moves it made", got.searches === 2, got.searches);
  // **Record this search call's cost too.** Message-table counters describe the agent's own model call;
  // the tool's separate internal call belongs to no such row. Omitting it can undercount total costs by an order of magnitude.
  ok("and what the search itself cost", got.spent?.total_tokens === 72267, got.spent);

  step("5. searched but said nothing - say what it did, not just that it failed");
  ask = "find nothing please";
  await m.api("POST", "/tasks", {
    id: "t-search-empty", mode: "one", agent: "bot", place: "local", source: "user",
    description: "look for something that is not there", solveSeconds: 60,
  });
  await until("t-search-empty to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search-empty");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const none = (await resultOf("t-search-empty")) as { error?: string; queries?: string[]; searches?: number };
  show("when it comes back empty-handed:", none);
  ok("it says so", Boolean(none.error), none);
  ok("and still reports the ground it covered", (none.queries ?? []).length === 1, none.queries);

  step("6. it went where the publisher said not to - drop the whole thing");
  // **The gate runs before the model sees the result**. Later auditing cannot undo exposure: once a reference answer
  // enters context, the task is contaminated, and invalidation merely records that loss.
  //
  // In this path the answer text is clean ("The answer is 42."); **visited pages** reveal the violation.
  // The gate therefore checks the whole response, not only answer text or URLs.
  ask = "find the forbidden thing";
  await m.api("POST", "/tasks", {
    id: "t-search-banned", mode: "one", agent: "bot", place: "local", source: "user",
    description: "go somewhere it should not", solveSeconds: 60,
    noSearch: ["secret_answers"],
  });
  await until("t-search-banned to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search-banned");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const banned = (await resultOf("t-search-banned")) as {
    error?: string; answer?: string; opened?: string[]; queries?: string[]; spent?: { total_tokens?: number };
  };
  show("what the agent was allowed to see:", banned);
  ok("it is told the publisher forbids it", String(banned.error).includes("Forbidden access"), banned.error);
  // Do not return the queries or visited pages either: **they are clues themselves**. Knowing that the answer lives in
  // somebody/secret_answers is only one step away from obtaining it.
  ok("the answer is gone", !banned.answer, banned);
  ok("and so is every trace of where it had been", !banned.opened && !banned.queries, banned);
  // **Still report the cost incurred**. Blocking a result does not undo spending; the snapshot must account for it.
  ok("but what it cost is still on the books", banned.spent?.total_tokens === 999, banned.spent);

  step("7. the publisher capped how many searches one attempt gets");
  // **Limit search calls, not units**. In a real run, timed-out tasks spent half their hour on retrieval
  // without once reaching their station-unit limits. Retrieval consumes wall time; a larger unit budget cannot fix that.
  ask = "how many KT transitions does the triangular lattice TFIM have?";
  await m.api("POST", "/tasks", {
    id: "t-search-capped", mode: "one", agent: "bot", place: "local", source: "user",
    description: "search more than you are allowed to", solveSeconds: 60,
    maxSearches: 1,
  });
  await until("t-search-capped to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search-capped");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const capped = (
    await m.api<{ rows: { body: string }[] }>("POST", "/query", {
      sql: "select body from agent_bot_msg where instance = 't-search-capped#1' and kind = 'tool' order by unit, seq",
    })
  ).rows
    .map((r) => JSON.parse(r.body) as { name?: string; value?: { answer?: string; error?: string; left?: number } })
    .filter((v) => v.name === "web_search")
    .map((v) => v.value ?? {});
  show("what each search call got back:", capped.map((v) => (v.answer ? `answered (left ${String(v.left)})` : v.error)));
  ok("the first one went through", Boolean(capped[0]?.answer), capped[0]);
  ok("and it says nothing is left", capped[0]?.left === 0, capped[0]);
  ok("it did try again after the allowance ran out", capped.length >= 2, capped.length);
  ok(
    "and every later one is refused",
    capped.length >= 2 && capped.slice(1).every((v) => String(v.error).includes("for this attempt is spent")),
    capped.slice(1),
  );

  step("8. it is a plain question-and-answer agent, and it keeps its own conversation");
  // **This is not ReAct**. Provider-side queries and page visits are not tool calls in our conversation model,
  // so its table contains no call/result pairs, just one question and one answer.
  //
  // Avoiding repeated searches also does not require preserving provider search state:
  // **the previous answer itself is useful material** and can accompany the next question.
  sent.length = 0;
  ask = "how many KT transitions does the triangular lattice TFIM have?";
  await m.api("POST", "/tasks", {
    id: "t-search-again", mode: "one", agent: "bot", place: "local", source: "user",
    description: "search twice", solveSeconds: 60,
  });
  await until("t-search-again to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search-again");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const desk = (
    await m.api<{ rows: { role: string; kind: string; body: string }[] }>("POST", "/query", {
      sql: "select role, kind, body from agent_searcher_msg where instance = 't-search-again#searcher' order by unit, seq",
    })
  ).rows;
  show("what the searcher's own table holds:", desk.map((r) => `${r.role}/${r.kind}: ${r.body.slice(0, 40)}`));
  ok("two rows per search, one asked and one answered", desk.length >= 2 && desk.length % 2 === 0, desk.length);
  ok("the first is the question", desk[0]?.role === "user", desk[0]);
  ok("the second is what it answered", desk[1]?.role === "assistant", desk[1]);
  ok("nothing pretends to be a tool call", desk.every((r) => r.kind !== "call" && r.kind !== "tool"), desk.map((r) => r.kind));

  const turns = sent.map((inp) => inp.length);
  show("how many turns each request carried:", turns);
  ok("the first request carried only the question", turns[0] === 1, turns[0]);
  ok("the second carried the earlier exchange too", (turns[1] ?? 0) > 1, turns[1]);
  ok("and the question is still last", sent[1]?.[sent[1].length - 1]?.role === "user", sent[1]?.slice(-1));

  step("9. the searcher's own settings are what goes out, not the run's");
  // Increasing solver reasoning must not also slow retrieval; this is why `agent.knobs` exists.
  show("reasoning effort on each search request:", efforts.filter(Boolean));
  ok("it searches without reasoning", efforts.every((e) => e === "" || e === "none"), efforts);
} finally {
  out.stop();
  m.stop();
}

done();
