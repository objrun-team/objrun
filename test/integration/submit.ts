/**
 * Submission: **one tool plus one station**, installed with the tree mechanism.
 *
 * ```
 * bun test/integration/submit.ts
 * ```
 *
 * ## Separate operations at separate moments
 *
 * | Operation | When | Purpose |
 * | --- | --- | --- |
 * | `verify` tool | During work, at any time, potentially repeatedly | Ask G whether a candidate is acceptable |
 * | `submit` tool | When the agent considers its work complete | **No arguments** in the original design; signal submission and transition to submit early |
 * | `submit` station | When execution reaches it | **Submit the text produced at this station**, evaluating it once if G exists |
 *
 * Execution also reaches submit without that tool call: completed text from a work
 * station leads there. The tool's original purpose is to arrive **early**.
 *
 * ## Why install this station with the mechanism?
 *
 * Submission is a property of **tree execution**, not an individual task. The verdict
 * must grade what was submitted, and submission needs a defined station. Requiring
 * every declaration to repeat it would let an omitted mode fall back to guessing an
 * answer from message history. Real runs have selected opening remarks or empty strings this way.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** Count real G invocations to verify that previously checked candidates are not graded again. */
const graded: unknown[] = [];

/** Tool names exposed to the agent in this round. */
let attached: string[] = [];
/** Tools exposed at each station; exposure location is one of the tested properties. */
const attachedAt: Record<string, string[]> = {};

const out = await outside({
  // Work station: **call `submit` once with the answer**.
  //
  // Put the candidate in the call, not in surrounding speech. Speech is for people; the answer is for the grader.
  // Extracting the latter from the former requires guessing. Submission is allowed at a work station:
  // the transition leads to submit, which grades that exact candidate.
  "/unit": (u) => {
    attached = ((u.tools ?? []) as { name: string }[]).map((t) => t.name);
    attachedAt[String((u.cycle as { cycle?: string } | undefined)?.cycle ?? "")] = attached;
    return {
      role: "assistant",
      kind: "call",
      body: JSON.stringify({
        text: "",
        calls: [{ id: `hand-in-${String(u.unit)}`, name: "submit", input: { answer: "the answer is 42" } }],
      }),
    };
  },
  // Work station: **only request tools, never produce complete text**.
  // A task that only calls tools cannot take the text-completed path; exhausting its budget must move it to submit.
  "/grind": () => ({ role: "assistant", kind: "call", body: JSON.stringify({ text: "", calls: [] }) }),
  // An observation node that always rejects, testing a fresh node after rejection.
  "/nope": () => false,
  "/look": (a) => {
    graded.push(a);
    return true;
  },
  "/verdict": (a) => ((a.feed ?? []) as { value: unknown }[])[0]?.value === true,
});

const G = {
  nodes: [
    { name: "look", moment: "done", domain: { kind: "bool" }, handle: out.url("/look") },
    { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/verdict") },
  ],
  edges: [{ src: "look", out: 0, dst: "verdict" }],
  sink: "verdict",
};

try {
  // =============== Part 1: registration ===============
  part("Part one: the hand-in step comes with the mechanism");

  step("1. declare a mode whose cycle uses the tree mechanism - and do not write a submit cycle");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/look"), expectMs: 10_000 },
      { name: out.url("/verdict"), expectMs: 10_000 },
    ],
    places: [{ place: "local" }],
    modes: [
      {
        mode: "tree",
        cycles: [{ cycle: "ask", maxUnits: 4, from: [], next: [], infer: "fn:infer.dfs" }],
      },
    ],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  show("cycles that went in:", loaded.cycles);

  const graph = await m.api<{ cycles: Record<string, unknown>[] }>("GET", "/modes/tree");
  show("the graph:", graph.cycles);
  const submit = graph.cycles.find((c) => c.cycle === "submit");
  ok("a submit cycle grew, though nobody declared one", submit !== undefined, graph.cycles);
  // **Submission is not necessarily the end**. Acceptance means the task is solved; rejection only means this candidate failed,
  // so proceed into the next node's action phase for another attempt rather than finishing.
  // **Submission is not necessarily the end**. Acceptance means the task is solved; rejection only means this candidate failed,
  // so proceed into the next node's action phase for another attempt rather than finishing.
  ok(
    "it feeds back into the action stage rather than ending the tree",
    JSON.stringify(submit?.next) === JSON.stringify(["ask"]),
    submit?.next,
  );
  ok("and the table records where it can be entered from", JSON.stringify(submit?.from) === JSON.stringify(["ask"]), submit?.from);
  ok("the working cycle can now route to it", JSON.stringify(graph.cycles.find((c) => c.cycle === "ask")?.next).includes("submit"), graph.cycles);
  // **A node submits only once**. Submit always writes a terminal status, accepted or dead, which ends the node.
  // A second submission within that node is structurally impossible. This column should therefore be 1;
  // a large value such as the sum of work-station budgets would misleadingly suggest multiple submissions per node.
  ok("a node hands in once, and the table says so", Number(submit?.maxUnits) === 1, submit?.maxUnits);
  ok("the whole-database check is clean", ((await m.api<{ data: unknown[] }>("GET", "/check")).data).length === 0);

  step("2. a mode that does not use the tree mechanism gets no submit cycle");
  await m.api("POST", "/declare", {
    modes: [{ mode: "flat", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
  });
  const flat = await m.api<{ cycles: Record<string, unknown>[] }>("GET", "/modes/flat");
  show("its graph:", flat.cycles.map((c) => c.cycle));
  ok("nothing was added", flat.cycles.length === 1, flat.cycles);

  // =============== Part 2: actual-use validation ===============
  part("Part two: checks at the level of use");
  console.log("  A cycle in the table proves nothing. Run a task and see where the verdict is taken.");

  step("3. run a task and watch it reach the hand-in step");
  await m.api("POST", "/tasks", {
    id: "t-1", mode: "tree", agent: "bot", place: "local", source: "user",
    description: "answer me", objective: G, readable: false,
  });
  const t = await until("t-1 to finish", async () => {
    const d = await m.api<{ state: string; units: Record<string, unknown>[] }>("GET", "/tasks/t-1");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  show("the stations it walked:", t.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`));
  ok("it reached the hand-in step", t.units.some((u) => u.cycle === "submit"), t.units);
  ok("and it passed", t.state === "done", t.state);
  // **G must receive the answer text itself**. Passing raw result would send the whole `{text, calls}`
  // JSON object, which the grader would reject as "answer not found", making logs look as if the model never answered.
  // This caused incorrect grading of an entire observed run.
  show("what the grading function received as the answer:", (graded.at(-1) as { input?: { result?: unknown } })?.input?.result);
  ok(
    "the grading function received the words themselves, not a JSON blob",
    ((graded.at(-1) as { input?: { result?: { body?: unknown } } })?.input?.result?.body) === "the answer is 42",
    (graded.at(-1) as { input?: { result?: unknown } })?.input?.result,
  );
  ok(
    "the verdict was taken at the hand-in step, not at the working one",
    t.units.find((u) => u.status === "reached")?.cycle === "submit",
    t.units.map((u) => ({ at: `${String(u.cycle)}#${String(u.unit)}`, status: u.status })),
  );

  step("4. the hand-in tool is attached where calling it means something");
  show("what each station was given:", attachedAt);
  ok("submit is attached at the working station", (attachedAt.ask ?? []).includes("submit"), attachedAt);
  ok(
    "verify too, since this task has a grading function",
    (attachedAt.ask ?? []).includes("verify"),
    attachedAt,
  );
  // **Expose only submit at the submission station**. Only act executes tools. Submit and its successor are model stations,
  // so other tool requests there have no executor; they would remain pending until repaired with
  // a synthetic "not executed" result. This station has one job: submit the answer.
  // **Do not also disable tools at ordinary work stations**. Basic tools left the `system` category to avoid
  // appearing at submit: system tools are universal and bypass the very conditions needed here.
  // They now depend on conditions. Incorrect conditions silently make the tools unavailable everywhere,
  // appearing only as a model that can no longer do anything.
  const ordinary = ["read", "write", "edit", "glob", "grep", "bash", "python_exec"];
  const missing = ordinary.filter((t) => !(attachedAt.ask ?? []).includes(t));
  show("ordinary tools missing from the working station:", missing);
  ok("the ordinary tools are all still there at the working station", missing.length === 0, attachedAt.ask);
  ok(
    "at the hand-in station there is nothing else it can do",
    JSON.stringify(attachedAt.submit ?? []) === JSON.stringify(["submit"]),
    attachedAt.submit,
  );
  const row = (
    await m.api<{ rows: Record<string, unknown>[] }>("POST", "/query", {
      sql: "select name, params, system from tool where name = 'submit'",
    })
  ).rows[0];
  show("the row it registered:", row);
  // **The candidate belongs in the tool call**. Previously, submit took no arguments and graded the text
  // spoken at the submission station. Choosing among several paragraphs, each with an expression, was guessing;
  // an incorrect guess appeared as rejection despite a correctly written answer.
  //
  // The parameter schema **comes from G** (`objective.params`). The kernel wraps G as `verify`, and submission
  // internally queries the same G, so both must accept the same inputs. Duplicated literal schemas would diverge
  // as soon as a new G field was updated in only one copy.
  const shape = JSON.parse(String(row?.params ?? "{}")) as { properties?: Record<string, unknown> };
  show("what it takes:", Object.keys(shape.properties ?? {}));
  ok(
    "it takes the answer itself, the same shape the grading function takes",
    Object.keys(shape.properties ?? {}).includes("answer"),
    row?.params,
  );
  ok("it is not a system tool - it is attached by a term, like the other tree tools", Number(row.system) === 0, row.system);
  step("5. a task that only ever calls tools still reaches the hand-in step");
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/grind"), expectMs: 30_000 }],
    modes: [{ mode: "grind", cycles: [{ cycle: "ask", maxUnits: 2, from: [], next: [], infer: "fn:infer.dfs" }] }],
    agents: [{ name: "tooler", apis: [], unit: out.url("/grind") }],
  });
  await m.api("POST", "/tasks", {
    id: "t-2", mode: "grind", agent: "tooler", place: "local", source: "user", description: "never speaks",
  });
  const g2 = await until("t-2 to finish", async () => {
    const d = await m.api<{ state: string; units: Record<string, unknown>[] }>("GET", "/tasks/t-2");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  show("the stations it walked:", g2.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`));
  ok(
    "running out of working budget routes it to the hand-in step, rather than dying quietly",
    g2.units.some((u) => u.cycle === "submit"),
    g2.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`),
  );
  // This mode has no successor candidate other than submit, so it transitions there after the first station without wasting a unit.
  ok(
    "it did not burn more than the declared working budget",
    g2.units.filter((u) => u.cycle === "ask").length <= 2,
    g2.units.map((u) => `${String(u.cycle)}#${String(u.unit)}`),
  );
  step("6. a hand-in that fails opens a NEW node, with a fresh budget");
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/nope"), expectMs: 10_000 }],
    modes: [{ mode: "again", cycles: [{ cycle: "ask", maxUnits: 2, from: [], next: [], infer: "fn:infer.dfs" }] }],
  });
  await m.api("POST", "/tasks", {
    id: "t-3", mode: "again", agent: "bot", place: "local", source: "user",
    description: "never passes", readable: false,
    maxDeadSiblings: 2,
    objective: {
      nodes: [
        { name: "look", moment: "done", domain: { kind: "bool" }, handle: out.url("/nope") },
        { name: "verdict", moment: "done", domain: { kind: "bool" }, handle: out.url("/verdict") },
      ],
      edges: [{ src: "look", out: 0, dst: "verdict" }],
      sink: "verdict",
    },
  });
  await until("t-3 to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-3");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const rows = (
    await m.api<{ rows: Record<string, unknown>[] }>("POST", "/query", {
      sql: "select cycle, unit, node, status from task_again where task = 't-3' order by unit",
    })
  ).rows;
  show(
    "the stations it walked:",
    rows.map(
      (r) =>
        `${String(r.cycle)}#${String(r.unit)}@node${String(r.node)}${r.status ? "[" + String(r.status) + "]" : ""}`,
    ),
  );
  const seen = [...new Set(rows.map((r) => Number(r.node)))];
  ok("a failed hand-in starts a new node rather than ending the tree", seen.length > 1, seen);
  ok(
    "each node gets its own budget - the working station runs again in the new node",
    rows.filter((r) => r.cycle === "ask" && Number(r.node) === seen[1]).length > 0,
    rows.map((r) => `${String(r.cycle)}@node${String(r.node)}`),
  );
  ok("and it stops after maxDeadSiblings attempts, rather than going on forever", seen.length <= 3, seen);
} finally {
  out.stop();
  m.stop();
}

done();
