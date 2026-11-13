/**
 * Example: **attach an objective (verification function G) to a task**.
 *
 * ```
 * bun test/integration/objective.ts
 * ```
 *
 * G decides **whether the task has been accomplished**. Unlike other registrations,
 * it has three strict rules:
 *
 * 1. **Binding occurs at publication and is an admission requirement**. It cannot be
 *    added later. Failed definition-time validation **rejects the whole task** rather
 *    than admitting a task whose result could never be evaluated.
 * 2. **The definition lives in a separate sealed database, unreachable from the main
 *    database**. The main database API is unrestricted; storing G there would remove
 *    the boundary. Enforcement depends on inaccessibility, not a rule forbidding access.
 * 3. **Agent-derived tasks cannot carry G**. Otherwise an agent could set its own
 *    success criteria, or those of a derived task: self-escalation would invalidate
 *    the grading criteria.
 *
 * ## G is a DAG
 *
 * Each node is a handle with a closed domain (`bool` / `bool[n]`). Every node in
 * this example is an external `http://` handle hosted by the example's small server.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** Record how often G's nodes were called and what they received, proving they **actually executed**. */
const graded: Record<string, unknown>[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "I say I am done" }),
  "/infer": () => null,
  // A **consistently slow** execution unit verifies that timeout really finalizes the task.
  "/slow": async () => {
    await Bun.sleep(30_000);
    return { role: "assistant", kind: "prompt", body: "too late" };
  },

  // -- G nodes: **returns must belong to the declared domain** ------------------
  //
  // A `bool` domain returns `true` / `false`, not an object such as `{pass: 1}`. An invalid shape
  // does not crash G: it **becomes 0 with an explanation**, keeping evaluation total without a third value.

  /** Observation node: this version accepts every candidate. */
  "/look-pass": (a) => {
    graded.push({ who: "look-pass", input: a.input });
    return true;
  },
  /** Observation node: this version rejects every candidate. */
  "/look-fail": (a) => {
    graded.push({ who: "look-fail", input: a.input });
    return false;
  },
  /**
   * Observation node: reject **and explain why**.
   *
   * Return `{ value, note }`. The grader often has a complete report of failed
   * checks and errors. Returning only `false` would discard it, leaving the model
   * with "evaluated to false" and encouraging the same attempt again. `why` is
   * unchanged: it describes failure to evaluate a node, distinct from a successfully
   * evaluated false result.
   */
  "/look-fail-loud": (a) => {
    graded.push({ who: "look-fail-loud", input: a.input });
    return { value: false, note: { failed: ["shape", "units"], hint: "two of the three parts are missing" } };
  },
  /** Output node: pass through the upstream boolean unchanged. */
  "/verdict": (a) => {
    const feed = (a.feed ?? []) as { value: unknown }[];
    graded.push({ who: "verdict", feed });
    return feed[0]?.value === true;
  },
});

/**
 * A minimal **valid** G has two nodes.
 *
 * ```
 *   look (observes the world directly; indegree 0) --> verdict (output node; bool domain)
 * ```
 *
 * Why two rather than one? Definition-time validation requires:
 * **No incoming edge at the output -> candidate-independent value -> constant G -> invalid objective**.
 * A single node acting as its own output is such a constant G: it returns the same
 * answer regardless of the agent's work, so it is not a grading criterion.
 *
 * Two other constraints are represented here: `sink` **must have domain bool**
 * (success/failure, no third value), and every output port except the root's must
 * be consumed by an edge; dangling outputs are forbidden.
 */
const G = (look: string) => ({
  nodes: [
    { name: "look", moment: "done", domain: { kind: "bool" }, handle: look },
    { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/verdict") },
  ],
  edges: [{ src: "look", out: 0, dst: "verdict" }],
  sink: "verdict",
});

try {
  // =============== Part 1: registration (publication-time admission) ===============
  part("Part one: registration (a grading function is bound at publish time)");

  const base = {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
      { name: out.url("/look-pass"), expectMs: 10_000 },
      { name: out.url("/look-fail"), expectMs: 10_000 },
      { name: out.url("/look-fail-loud"), expectMs: 10_000 },
      { name: out.url("/verdict"), expectMs: 10_000 },
    ],
    places: [{ place: "local" }],
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  };
  await m.api("POST", "/declare", base);
  ok("the base declaration went in", true);

  step("1. carries a grading function but does not say whether the agent may read it");
  const unsaid = await m.bad("POST", "/tasks", {
    id: "t-1", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "compute something", objective: G(out.url("/look-pass")),
  });
  show("it answered:", unsaid.error);
  ok("carrying one makes readable mandatory - there is no default", String(unsaid.error).includes("readable"), unsaid);

  step("2. an agent-derived task carrying a grading function (self-granted authority)");
  const selfGrant = await m.bad("POST", "/tasks", {
    id: "t-2", mode: "demo", agent: "bot", place: "local", source: "agent",
    description: "I set my own bar", objective: G(out.url("/look-pass")), readable: true,
  });
  show("it answered:", selfGrant.error);
  ok("the gate judges on source, at the single entrance", String(selfGrant.error).length > 0, selfGrant);

  step("3. a constant grading function (the output node has no incoming edge)");
  const constant = await m.bad("POST", "/tasks", {
    id: "t-3", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "compute something", readable: false,
    objective: {
      nodes: [{ name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") }],
      edges: [],
      sink: "verdict",
    },
  });
  show("it answered:", constant.error);
  ok(
    "a value independent of the candidate is not a criterion - rejected at definition time, not after publishing",
    String(constant.error).includes("constant"),
    constant,
  );

  step("4. a cyclic grading function (evaluation would not terminate)");
  const cyclic = await m.bad("POST", "/tasks", {
    id: "t-4", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "compute something", readable: false,
    objective: {
      nodes: [
        { name: "a", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") },
        { name: "b", moment: "done", domain: { kind: "bool" }, handle: out.url("/look-pass") },
      ],
      edges: [{ src: "a", out: 0, dst: "b" }, { src: "b", out: 0, dst: "a" }],
      sink: "a",
    },
  });
  show("it answered:", cyclic.error);
  ok("a non-terminating one has no value, and is stopped at definition time too", String(cyclic.error).includes("cycle"), cyclic);

  step("5. confirm none of those tasks reached the database");
  const inDb = await m.api<{ total: number }>("GET", "/tasks");
  ok("a task that fails the gate is never published", inDb.total === 0, inDb);

  // =============== Part 2: actual-use validation ===============
  part("Part two: checks at the level of use");
  console.log("  Bound is not the same as actually judged. See whether it really ran and wrote the verdict back.");

  step("6. publish a task its grading function will pass");
  await m.api("POST", "/tasks", {
    id: "t-pass", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "this one passes", objective: G(out.url("/look-pass")), readable: false,
  });
  const passed = await until("a verdict for t-pass", async () => {
    const d = await m.api<{ state: string; objective: { verdict: unknown } }>("GET", "/tasks/t-pass");
    return d.objective.verdict !== null ? d : null;
  });
  show("verdict:", passed.objective);
  ok("the grading function really ran", graded.some((x) => x.who === "look-pass"), graded.length);
  ok("the verdict was written back to the main database", (passed.objective.verdict as { pass?: number })?.pass === 1, passed.objective);
  ok("state is done", passed.state === "done", passed.state);

  step("7. publish a task it will fail - the agent saying it is done does not count");
  await m.api("POST", "/tasks", {
    id: "t-fail", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "this one does not pass", objective: G(out.url("/look-fail")), readable: false,
  });
  const failed = await until("a verdict for t-fail", async () => {
    const d = await m.api<{ state: string; objective: { verdict: unknown } }>("GET", "/tasks/t-fail");
    return d.objective.verdict !== null ? d : null;
  });
  show("verdict:", failed.objective);
  ok(
    "the agent saying I am done does not count; the grading function has the last word",
    failed.state === "failed",
    { state: failed.state, verdict: failed.objective.verdict },
  );
  ok("and it can say why", String((failed.objective.verdict as { why?: string })?.why ?? "").length > 0, failed.objective);

  step("7b. a node that judges false can add a note of its own");
  await m.api("POST", "/tasks", {
    id: "t-loud", mode: "demo", agent: "bot", place: "local", source: "user",
    description: "this one fails and explains itself", objective: G(out.url("/look-fail-loud")), readable: false,
  });
  const loud = await until("a verdict for t-loud", async () => {
    const d = await m.api<{ state: string; objective: { verdict: unknown } }>("GET", "/tasks/t-loud");
    return d.objective.verdict !== null ? d : null;
  });
  const loudNote = String((loud.objective.verdict as { note?: string })?.note ?? "");
  show("note:", loudNote);
  ok(
    "what the node said came through - a bare false leaves nothing but 'evaluated to false', and that teaches the next attempt nothing",
    loudNote.includes("two of the three parts are missing") && loudNote.includes("units"),
    loudNote,
  );

  step("8. can the definition be reached from the main database");
  const row = await m.api<{ count: number; rows: Record<string, unknown>[] }>("POST", "/query", {
    sql: "select id, objective, readable from task where id = 't-pass'",
  });
  show("that row in the main database:", row.rows[0]);
  ok(
    "the main database records only whether there is one; the definition is elsewhere, in the sealed store, out of reach of the API",
    !JSON.stringify(row.rows[0]).includes("look-pass"),
    row.rows[0],
  );

  step("9. a task with no grading function: finishing is finishing, nothing is judged");
  await m.api("POST", "/tasks", {
    id: "t-none", mode: "demo", agent: "bot", place: "local", source: "user", description: "no grading function",
  });
  const noG = await until("t-none to finish", async () => {
    const d = await m.api<{ state: string; objective: Record<string, unknown> }>("GET", "/tasks/t-none");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  show("its objective:", noG.objective);
  ok("no grading function, no verdict", noG.objective.has === false && noG.objective.verdict === null, noG.objective);
  ok("finishing is done", noG.state === "done", noG.state);
  step("10. a task that runs past solveSeconds really gets marked failed");
  // This gate failed twice, losing an entire run each time. First, task-level deadlines were never added to the timer;
  // second, SQL omitted quotes (`state = failed` treated failed as a column name), causing run to throw
  // before G was called. Both failures logged expired while the database remained claimed indefinitely.
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/slow"), expectMs: 60_000 }],
    agents: [{ name: "slowbot", apis: [], unit: out.url("/slow") }],
  });
  await m.api("POST", "/tasks", {
    id: "t-slow", mode: "demo", agent: "slowbot", place: "local", source: "user",
    description: "never finishes in time", solveSeconds: 1,
  });
  const late = await until(
    "t-slow to be closed by the clock",
    async () => {
      const d = await m.api<{ state: string; result: unknown }>("GET", "/tasks/t-slow");
      return d.state === "failed" ? d : null;
    },
    15_000,
  );
  show("how it was closed:", { state: late.state, result: late.result });
  ok("the clock closes it - it does not sit in claimed forever", late.state === "failed", late.state);
  ok(
    "and the result says it was the clock, not a verdict",
    String(JSON.stringify(late.result)).includes("solve_seconds"),
    late.result,
  );
} finally {
  out.stop();
  m.stop();
}

done();
