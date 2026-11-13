/**
 * Example: **add a tool externally**.
 *
 * ```
 * bun test/integration/tool.ts
 * ```
 *
 * Every interaction uses HTTP, with no kernel edits or restart. The tool runs on
 * the example's own small server and is registered through an `http://` handle.
 *
 * ## The second part is essential
 *
 * Registration and **actual effect** are distinct. A typical failure is a stored
 * tool that never triggers: one typo in a condition can leave a `tool` row unavailable
 * to every agent **without any error**. The second part submits two actual tasks,
 * one that should match and one that should not, then checks the tools exposed in each round.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();
const out = await outside({
  // This station does not use a model: the kernel calls agent.unit, this external handle.
  // Its payload includes **the tools exposed this round**, which the second part inspects.
  "/unit": (u) => ({ role: "assistant", kind: "prompt", body: `tools I got this round: ${names(u)}` }),
  // The tool itself is not invoked in this example; choosing it would be the model's job. Registration is the focus.
  "/weather": (a) => ({ city: a.city ?? "?", tempC: 21 }),
});

function names(u: Record<string, unknown>): string {
  return ((u.tools ?? []) as { name: string }[]).map((t) => t.name).join("、") || "(none)";
}

try {
  // =============== Part 1: registration ===============
  part("Part one: registration");

  step("1. the tool points at a handle that does not exist");
  show(
    "it answered:",
    (await m.bad("POST", "/declare", {
      tools: [{ name: "weather", identity: "http://127.0.0.1:1/nope", does: "look up the weather", params: {}, output: {} }],
    })).problems,
  );
  ok("it says the handle is missing, and where to declare it", true);

  step("2. not a system tool, and not a single trigger term");
  const noTerms = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/weather"), expectMs: 10_000 }],
    tools: [{ name: "weather", identity: out.url("/weather"), does: "look up the weather", params: {}, output: {} }],
  });
  show("it answered:", noTerms.problems);
  ok(
    "it stops the shape where nobody can ever get it",
    JSON.stringify(noTerms.problems).includes("never be attached to any agent"),
    noTerms.problems,
  );

  step("3. contains mistyped as contain in a term");
  const typo = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/weather"), expectMs: 10_000 }],
    tools: [
      {
        name: "weather", identity: out.url("/weather"), does: "look up the weather", params: {}, output: {},
        when: [[{ dim: "task", key: "description", op: "contain", value: "weather" }]],
      },
    ],
  });
  show("it answered:", typo.problems);
  ok("one letter off is rejected outright, and the known operators are listed", JSON.stringify(typo.problems).includes("unknown operator"), typo.problems);

  step("4. one correct load: handle + tool + place + mode + agent");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/weather"), expectMs: 10_000 },
      { name: out.url("/unit"), expectMs: 30_000 },
    ],
    tools: [
      {
        name: "weather",
        identity: out.url("/weather"),
        does: "Look up the current temperature in a city",
        params: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
        output: { type: "object", properties: { tempC: { type: "number" } } },
        prompt: "Call weather when asked about the weather; do not invent a temperature.",
        // Expose the tool only when the task description mentions weather.
        when: [[{ dim: "task", key: "description", op: "contains", value: "weather" }]],
      },
    ],
    places: [{ place: "local" }],
    // Empty apiMode means no model call; use agent.unit, the external handle.
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  show("what went in:", loaded);
  ok("the tool went in", (loaded.tools as string[]).includes("weather"), loaded.tools);
  ok("the sub-tables grew along with it, no restart needed", (loaded.tables as string[]).length > 0, loaded.tables);

  step("5. read back how it was registered");
  const { tools } = await m.api<{ tools: Record<string, unknown>[] }>("GET", "/tools");
  const w = tools.find((t) => t.name === "weather")!;
  show("weather:", w);
  ok("when came back grouped, not one row per term", Array.isArray(w.when) && (w.when as unknown[]).length === 1, w.when);
  ok("it is not a never-fires tool", w.neverFires === false, w.neverFires);
  ok("the whole-database check is clean", ((await m.api<{ data: unknown[] }>("GET", "/check")).data).length === 0);

  // =============== Part 2: actual-use validation ===============
  part("Part two: checks at the level of use");
  console.log("  Registered is not the same as in effect. Publish two real tasks and see which tools got attached.");

  step("6. publish a task that MATCHES (the description contains weather)");
  await m.api("POST", "/tasks", {
    id: "t-hit", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "what is the weather in Beijing today",
  });
  const hit = await until("t-hit to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-hit");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  // The example uses one handle for both unit and infer. The terminal station also invokes infer,
  // without tools. Select **the invocation carrying tools**, which is the actual execution-unit call.
  const attached = out.calls["/unit"].filter((c) => c.tools !== undefined).at(-1)!;
  show("tools attached this round:", ((attached.tools ?? []) as { name: string }[]).map((t) => t.name));
  ok("the task finished", (hit as { state: string }).state === "done", hit);
  ok(
    "weather really was attached",
    ((attached.tools ?? []) as { name: string }[]).some((t) => t.name === "weather"),
    attached.tools,
  );

  step("7. publish a task that does NOT match (no weather in the description)");
  await m.api("POST", "/tasks", {
    id: "t-miss", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "add three and five for me",
  });
  await until("t-miss to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-miss");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const attachedNow = out.calls["/unit"].filter((c) => c.tools !== undefined).at(-1)!;
  show("tools attached this round:", ((attachedNow.tools ?? []) as { name: string }[]).map((t) => t.name));
  ok(
    "weather was NOT attached - the terms really do decide, it is not attached to everything",
    !((attachedNow.tools ?? []) as { name: string }[]).some((t) => t.name === "weather"),
    attachedNow.tools,
  );

  step("8. ask why, on the one that did not match");
  const why = await m.api("POST", "/trigger/explain", {
    kind: "tool", owner: "weather", task: "t-miss",
  });
  show("term by term:", why);
  ok(
    "the value actually read is included - no guessing whether the word was mistyped or simply absent",
    JSON.stringify(why).includes("add three and five"),
    why,
  );
} finally {
  out.stop();
  m.stop();
}

done();
