/**
 * Example: **add a skill externally**.
 *
 * ```
 * bun test/integration/skill.ts
 * ```
 *
 * The key distinction from a tool is that **the model does not select a skill**.
 * Tools are exposed for the model to choose. A skill is **inserted into context**
 * when its conditions match; the model sees the resulting content already present.
 *
 * Two forms:
 *
 * - A specified `body`: fixed text.
 * - An empty `body`: **dynamic generation** by calling the same-named handle when triggered.
 *
 * ## The second part is essential
 *
 * Skill insertion is established by **its context row**. The second part reads
 * the execution unit's messages and checks for `kind = "skill"`, correct content,
 * and the correct `who`. Registration success alone proves none of this.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** Record the facts supplied to a dynamic skill, verifying that it is **generated at invocation time**. */
const generated: Record<string, unknown>[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "finished" }),
  // Dynamic skill: the kernel supplies this round's facts; construct the returned text now.
  "/recap": (a) => {
    generated.push(a);
    const f = (a.facts ?? {}) as { task?: { id?: string; description?: string } };
    return `[generated] this task is ${f.task?.id}: ${f.task?.description}`;
  },
});

/** Fetch this task's context for the current round. */
async function ctx(id: string) {
  return (await m.api<{ rows: Record<string, unknown>[] }>("GET", `/tasks/${id}/messages`)).rows;
}

try {
  // =============== Part 1: registration ===============
  part("Part one: registration");

  step("1. body left empty (so, dynamically generated), but there is no handle of that name");
  const nobody = await m.bad("POST", "/declare", {
    skills: [{ identity: "recap", does: "restate the task", params: {}, role: "user", when: [[{ dim: "task", key: "source", op: "eq", value: "user" }]] }],
  });
  show("it answered:", nobody.problems);
  ok(
    "stopped - nobody can produce the content on demand",
    JSON.stringify(nobody.problems).includes("nobody can produce the content on demand"),
    nobody.problems,
  );

  step("2. not a single trigger term");
  const noTerms = await m.bad("POST", "/declare", {
    skills: [{ identity: "fixed", does: "a fixed passage", params: {}, role: "user", body: "hard-coded words" }],
  });
  show("it answered:", noTerms.problems);
  ok("the model does not pick it, so no terms means it is never injected", JSON.stringify(noTerms.problems).includes("never be injected"), noTerms.problems);

  step("3. load three good ones: fixed, dynamic, and one registered but disabled");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/recap"), expectMs: 10_000 },
    ],
    skills: [
      {
        identity: "fixed", does: "a fixed reminder", params: {}, role: "user",
        body: "[fixed] state your grounds when you answer.",
        when: [[{ dim: "task", key: "source", op: "eq", value: "user" }]],
      },
      {
        // Empty body means dynamic generation by this handle at trigger time.
        identity: out.url("/recap"), does: "restate the task once", params: {}, role: "user",
        when: [[{ dim: "task", key: "description", op: "contains", value: "restate" }]],
      },
      {
        identity: "offline", does: "a disabled one", params: {}, role: "user", body: "[should not appear]",
        usable: false,
        when: [[{ dim: "task", key: "source", op: "eq", value: "user" }]],
      },
    ],
    places: [{ place: "local" }],
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  ok("all three went in", (loaded.skills as string[]).length === 3, loaded.skills);

  step("4. read back which is fixed and which is generated");
  const { skills } = await m.api<{ skills: Record<string, unknown>[] }>("GET", "/skills");
  show("the skill list:", skills.map((s) => ({ identity: s.identity, dynamic: s.dynamic, usable: s.usable })));
  ok("the dynamic one is marked", skills.find((s) => String(s.identity).endsWith("/recap"))?.dynamic === true, skills);
  ok("the fixed one is not marked dynamic", skills.find((s) => s.identity === "fixed")?.dynamic === false, skills);

  // =============== Part 2: actual-use validation ===============
  part("Part two: checks at the level of use");
  console.log("  Whether it was injected shows in the context row. Registering proves nothing.");

  step("5. publish a task both should match (source user, description contains restate)");
  await m.api("POST", "/tasks", {
    id: "t-both", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "restate it, then answer me",
  });
  await until("t-both to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-both");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const context = await ctx("t-both");
  const injected = context.filter((r) => r.kind === "skill");
  show("the kind=skill rows in the context:", injected.map((r) => r.body));

  ok("the fixed one really was injected", injected.some((r) => String(r.body).includes("[fixed]")), injected);
  ok(
    "the dynamic one injected freshly generated content, not something written at registration time",
    injected.some((r) => String(r.body).includes("this task is t-both: restate it, then answer me")),
    injected,
  );
  ok("the disabled one stayed out", !injected.some((r) => String(r.body).includes("[should not appear]")), injected);
  // **Skills have their own role rather than borrowing `user`.**
  //
  // Using `user` tells the model that a person said this text, although it is a conditionally inserted instruction.
  // In an observed run, the model started asking follow-up questions ("Please provide this problem's specific choices") instead of answering.
  // No error was raised; only the score fell. Skill content goes into `instructions`, not the message stream
  // (see `ROLES` in `llm/index.ts`).
  ok("what was injected carries role skill - an identity of its own, not impersonating a person", injected.every((r) => r.role === "skill"), injected);

  step("6. the dynamic one received this round facts, not an empty shell");
  show("the task it received:", (generated.at(-1)?.facts as { task?: unknown })?.task);
  ok(
    "the facts handed over carry this task",
    ((generated.at(-1)?.facts as { task?: { id?: string } })?.task?.id) === "t-both",
    generated.at(-1),
  );

  step("7. publish a task only the fixed one should match (no restate in the description)");
  await m.api("POST", "/tasks", {
    id: "t-one", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "just answer me directly",
  });
  await until("t-one to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-one");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const injectedNow = (await ctx("t-one")).filter((r) => r.kind === "skill");
  show("what was injected this time:", injectedNow.map((r) => r.body));
  ok("the fixed one is still there", injectedNow.some((r) => String(r.body).includes("[fixed]")), injectedNow);
  ok(
    "the dynamic one stayed out - the terms really do decide",
    !injectedNow.some((r) => String(r.body).includes("this task is")),
    injectedNow,
  );
} finally {
  out.stop();
  m.stop();
}

done();
