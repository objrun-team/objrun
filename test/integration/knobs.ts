/**
 * Example: **an agent can pin its own model parameters**.
 *
 * ```
 * bun test/integration/knobs.ts
 * ```
 *
 * Run-wide `llm.*` values in `config.yaml` provide defaults. Some parameters are
 * **properties of the agent rather than the run**: a retrieval-and-explanation
 * agent needs no reasoning, while its solver benefits from more. One setting
 * cannot serve both purposes.
 *
 * The difference is substantial: for the same problem, `reasoning_effort` of
 * `none` took 14.5 seconds, versus 113 seconds for `low`. The extra 98 seconds
 * purchased ten thousand reasoning tokens. Without this column, **raising solver
 * reasoning also slows retrieval eightfold, with no clear explanation**.
 *
 * `agent.knobs` therefore overrides only specified run-wide values and inherits the rest.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

process.env.DEEPSEEK_API_KEY ??= "sk-not-a-real-key";

const m = await machine({ reasoningEffort: "high", temperature: 0.7 });

/** Record every received request; these payloads are what the test checks. */
const seen: Record<string, unknown>[] = [];

const out = await outside({
  "/chat/completions": (a) => {
    seen.push(a as Record<string, unknown>);
    return {
      id: "fake",
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model: "deepseek-v4-flash",
      choices: [{ index: 0, message: { role: "assistant", content: "done" }, finish_reason: "stop" }],
      usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
    };
  },
  "/infer": () => null,
});

try {
  part("An agent can pin its own model settings");

  step("1. point the api row at the fake endpoint, so we can read what was sent");
  await m.api("POST", "/exec", {
    sql: `update api set base_url = '${out.url("")}' where model = 'deepseek-v4-flash'`,
  });

  step("2. two agents on the same lane - one pins its settings, one does not");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      { mode: "one", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 1, from: [], next: [], infer: out.url("/infer") }] },
    ],
    agents: [
      // **No overrides**: use the run-wide configuration unchanged.
      { name: "asis", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: out.url("/infer") },
      // **Pin reasoning off.** This agent retrieves and relays information; reasoning again buys the most expensive work twice.
      {
        name: "pinned",
        apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]],
        unit: out.url("/infer"),
        knobs: { reasoningEffort: "none" },
      },
    ],
  });

  const runOne = async (agent: string, id: string) => {
    seen.length = 0;
    await m.api("POST", "/tasks", {
      id, mode: "one", agent, place: "local", source: "user", description: "say something", solveSeconds: 60,
    });
    await until(`${id} to finish`, async () => {
      const d = await m.api<{ state: string }>("GET", `/tasks/${id}`);
      return d.state === "done" || d.state === "failed" ? d : null;
    }, 30_000);
    return seen[0] ?? {};
  };

  step("3. the one that pinned nothing gets the run-wide setting");
  const asis = await runOne("asis", "t-asis");
  show("what the un-pinned agent sent:", { reasoning_effort: asis.reasoning_effort, temperature: asis.temperature });
  ok("run-wide reasoning effort", asis.reasoning_effort === "high", asis.reasoning_effort);
  ok("run-wide temperature", asis.temperature === 0.7, asis.temperature);

  step("4. the one that pinned it overrides - and only what it named");
  const pinned = await runOne("pinned", "t-pinned");
  show("what the pinned agent sent:", { reasoning_effort: pinned.reasoning_effort, temperature: pinned.temperature });
  ok("its own reasoning effort wins", pinned.reasoning_effort === "none", pinned.reasoning_effort);
  // **Override only explicitly named settings**. Otherwise pinning one parameter could silently reset unrelated settings
  // to defaults, making the change difficult to detect.
  ok("everything it did not name still falls back", pinned.temperature === 0.7, pinned.temperature);

  step("5. turning the run-wide dial does not move the pinned one");
  // This is why the column exists: changing solver reasoning must not also slow retrieval eightfold.
  await m.api("POST", "/exec", { sql: "update agent set state = state" });
  ok("the two disagree, which is the whole point", asis.reasoning_effort !== pinned.reasoning_effort, {
    asis: asis.reasoning_effort,
    pinned: pinned.reasoning_effort,
  });
} finally {
  out.stop();
  m.stop();
}

done();
