/**
 * Example: **a scored task must not spend more money**.
 *
 * ```
 * bun test/integration/dead-quiet.ts
 * ```
 *
 * Timeout handling intended to "record failure first so it is no longer scheduled".
 * But work selection checked only whether the row was unfinished (`where done = 0`),
 * never whether the task was still active:
 *
 * 1. A task times out; `#reap` sets `state` to `failed` and fixes its score.
 * 2. Its unfinished rows **still have `done = 0`**.
 * 3. The next loop finds and dispatches those rows to the model again.
 *
 * In one real run, 15 dead tasks launched another 105 execution units; one continued
 * for 33 minutes after death. Every unit was a real model call, but none could affect
 * the score fixed at timeout. Further errors arose because a call still in flight at
 * timeout later appended an unanswered tool request after final repair had already run.
 *
 * This example expires a task while it is working, then checks that **it does not resume**.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/**
 * **One unit takes longer than the entire task deadline.** This is essential to the test.
 *
 * A call must be in flight when time expires. The task has already been scored when
 * the call returns, but its result still creates a successor. **That successor is the
 * unit that must not be dispatched after death.** A faster call would leave no pending
 * work at timeout, making the test pass without exercising the bug.
 */
let served = 0;
const out = await outside({
  "/step": async () => {
    served++;
    await Bun.sleep(4000);
    return { role: "assistant", kind: "prompt", body: `unit ${String(served)}` };
  },
  // Continue indefinitely: **this task never stops on its own**, only at its deadline. To test activity after stopping,
  // it must not simply reach the end of its workflow.
  "/infer": () => "ask",
});

try {
  part("A task that has been scored does not spend any more");

  step("1. a station that loops, so it would keep going forever if nobody stopped it");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [
      { name: out.url("/step"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    modes: [
      {
        mode: "loop",
        cycles: [{ cycle: "ask", maxUnits: 500, from: [], next: ["ask"], infer: out.url("/infer") }],
      },
    ],
    agents: [{ name: "bot", apis: [], unit: out.url("/step") }],
  });

  step("2. give it three seconds to live");
  await m.api("POST", "/tasks", {
    id: "t-dead-quiet",
    mode: "loop",
    agent: "bot",
    place: "local",
    source: "user",
    description: "keep going until the clock runs out",
    solveSeconds: 3,
  });

  const state = await until(
    "t-dead-quiet to be scored",
    async () => {
      const d = await m.api<{ state: string }>("GET", "/tasks/t-dead-quiet");
      return d.state === "failed" || d.state === "done" ? d : null;
    },
    30_000,
  );
  show("how it ended:", state);

  const atDeath = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: "select count(*) as n from task_loop where task = 't-dead-quiet'",
    })
  ).rows[0].n;
  show("units at the moment it was scored:", atDeath);

  step("3. keep waking the kernel for a while, then look again");
  // **Every database write wakes the kernel.** Keep triggering it; if work selection still ignores task state,
  // these seconds are enough to dispatch several additional units.
  const until_ = Date.now() + 6000;
  while (Date.now() < until_) {
    await m.api("POST", "/exec", { sql: "update task set domain = domain where id = 't-dead-quiet'" });
    await Bun.sleep(250);
  }

  const after = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: "select count(*) as n from task_loop where task = 't-dead-quiet'",
    })
  ).rows[0].n;
  show("units six seconds later:", after);

  // The in-flight call may create **one** successor when it returns. It was dispatched before task death,
  // so its result must be accepted. The invariant is **no new dispatches**, not abrupt termination.
  ok("a scored task opens no new units", after <= atDeath + 1, { atDeath, after });

  step("4. and no call was made beyond the ones already out when the score was final");
  // Compare with the unit count **at task death**, not merely a few seconds earlier. The latter only proves it has stopped now,
  // after it may already have spent money during those seconds. This check bounds total spending.
  await Bun.sleep(2500);
  show("units at death vs calls served:", { atDeath, served });
  ok("the model was asked no more times than that", served <= atDeath, { atDeath, served });
} finally {
  out.stop();
  m.stop();
}

done();
