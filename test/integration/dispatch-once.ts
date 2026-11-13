/**
 * Example: **dispatch each row only once**.
 *
 * ```
 * bun test/integration/dispatch-once.ts
 * ```
 *
 * The kernel dispatches every row that has not yet been sent, using `void` without
 * waiting. The sent marker is **also stored in the database**, creating this race:
 *
 * 1. This iteration selects a row and calls `void this.#advance(p)` without waiting.
 * 2. `#advance` yields at its first `await` before writing the sent marker.
 * 3. A database write in this interval wakes the kernel and starts another iteration.
 * 4. The next iteration sees the row as unsent and **dispatches it again**.
 *
 * Two model responses then occupy the same unit: adjacent tool-request messages
 * without intervening results. Providers reject that shape, making **the entire
 * conversation unsendable** until task timeout. Four of more than five hundred units
 * hit this race in an observed run, each losing a task.
 *
 * The fix is to reserve before working: **the first dispatch operation** persists
 * the sent marker before any await. Tools and usage conventions are added to the
 * same row once computed.
 *
 * This example widens the race window with a slow handle inside `#advance` while
 * repeatedly writing to the database. Without reservation, the unit is sent repeatedly.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** Deliberately slow station: `#advance` pauses here, widening the race window. */
const out = await outside({
  "/slow": async () => {
    await Bun.sleep(4000);
    return { role: "assistant", kind: "prompt", body: "took a while" };
  },
  "/infer": () => null,
  /** This station **never responds**, testing timeout death followed by a new node. */
  "/never": async () => {
    await Bun.sleep(600_000);
    return { role: "assistant", kind: "prompt", body: "unreachable" };
  },
});

try {
  part("One row, one dispatch");

  step("1. a station that takes a while to answer");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [
      { name: out.url("/slow"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    modes: [{ mode: "one", cycles: [{ cycle: "ask", maxUnits: 2, from: [], next: [], infer: out.url("/infer") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/slow") }],
  });
  await m.api("POST", "/tasks", {
    id: "t-once-only", mode: "one", agent: "bot", place: "local", source: "user",
    description: "one dispatch please", solveSeconds: 60,
  });

  step("2. keep the kernel waking up while that station is still out");
  // **Every database write wakes the kernel.** Keep waking it while the previous dispatch is incomplete;
  // without a reservation, the same unit would be dispatched repeatedly.
  const until_ = Date.now() + 4000;
  while (Date.now() < until_) {
    await m.api("POST", "/exec", { sql: "update task set domain = domain where id = 't-once-only'" });
    await Bun.sleep(120);
  }

  await until("t-once-only to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-once-only");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  step("3. that row went out exactly once");
  const marks = (
    await m.api<{ rows: { unit: number; n: number }[] }>("POST", "/query", {
      sql:
        "select unit, count(*) as n from agent_bot_msg where instance = 't-once-only#1' " +
        "and kind = 'inject' and body like '%\"sent\":true%' group by unit",
    })
  ).rows;
  show("dispatch marks per unit:", marks.map((r) => `u${String(r.unit)}: ${String(r.n)}`));
  ok("no unit was dispatched twice", marks.every((r) => Number(r.n) === 1), marks);

  step("4. and the model was asked once, so the conversation still holds");
  const said = (
    await m.api<{ rows: { unit: number; n: number }[] }>("POST", "/query", {
      sql:
        "select unit, count(*) as n from agent_bot_msg where instance = 't-once-only#1' " +
        "and role = 'assistant' group by unit",
    })
  ).rows;
  show("answers per unit:", said.map((r) => `u${String(r.unit)}: ${String(r.n)}`));
  ok("one dispatch, one answer", said.every((r) => Number(r.n) === 1), said);

  step("5. a station that never answers kills the attempt, and a new one starts");
  // "This call never returned" differs from "this task cannot be solved". Previously, timeout marked the row dead,
  // broke the chain, and ended the task. One transient failure lost the task without a second chance.
  // Now timeout death starts another node through the same path used after a rejected submission.
  await m.api("POST", "/declare", {
    handles: [{ name: out.url("/never"), expectMs: 4000 }],
    agents: [{ name: "ghost", apis: [], unit: out.url("/never") }],
    modes: [{ mode: "gone", cycles: [{ cycle: "ask", maxUnits: 4, from: [], next: [], infer: out.url("/infer") }] }],
  });
  await m.api("POST", "/tasks", {
    id: "t-silent", mode: "gone", agent: "ghost", place: "local", source: "user",
    description: "nobody will answer", solveSeconds: 40, maxDeadSiblings: 2,
  });
  const walked = await until(
    "a second attempt to open after the first one went silent",
    async () => {
      const got = await m.api<{ rows: { unit: number; node: number; status: string | null }[] }>("POST", "/query", {
        sql: "select unit, node, status from task_gone where task = 't-silent' order by unit",
      });
      return got.rows.some((r) => Number(r.node) > 1) ? got.rows : null;
    },
    45_000,
  );
  show("what it walked:", walked.map((r) => `u${String(r.unit)}@node${String(r.node)}${r.status ? "[" + r.status + "]" : ""}`));
  ok("the silent station was declared dead", walked.some((r) => r.status === "dead_failed"), walked);
  ok("and a fresh attempt was opened instead of ending the task", new Set(walked.map((r) => Number(r.node))).size > 1, walked);
} finally {
  out.stop();
  m.stop();
}

done();
