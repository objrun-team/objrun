/**
 * Example: **add an agent**.
 *
 * ```
 * bun test/integration/agent.ts
 * ```
 *
 * An agent is defined by two things:
 *
 * - `apis`: **which lanes it supports**. Each entry is `[environment-variable name, model]`
 *   and must exist in the `api` table. An agent can support differently shaped lanes
 *   simultaneously, such as `chat` for reasoning/writing and `duplex` for real-time
 *   listening/speaking. This is why `apis` is a list.
 * - `unit`: **what to call when this station does not use a model**. An empty
 *   cycle `apiMode` selects it.
 *
 * **The kernel selects the station's lane**: it reads `apiMode` from the cycle
 * table and chooses an `apis` entry whose `modes` includes it. The adapter does
 * not choose again; two independent selectors would eventually diverge.
 *
 * ## The second part is essential
 *
 * Successful registration does not prove that the agent can execute tasks. If
 * its lanes do not cover every station in a mode, tasks can **remain idle in the
 * database** without an error. The second part therefore checks supported modes,
 * configured credentials, and whether a real submitted task actually runs.
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();
const out = await outside({
  "/unit": (u) => ({
    role: "assistant",
    kind: "prompt",
    // Echo the lane selected by the kernel so the second part can verify the choice.
    body: JSON.stringify({ laneForThisStation: u.api ?? null }),
  }),
  "/infer": () => null,
});

try {
  // =============== Part 1: registration ===============
  part("Part one: registration");

  step("1. carry a lane that is not in the api table");
  const noLane = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/unit"), expectMs: 30_000 }],
    agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v99"]], unit: out.url("/unit") }],
  });
  show("it answered:", noLane.problems);
  ok("stopped - otherwise the lane could never be selected", JSON.stringify(noLane.problems).includes("never be selected"), noLane.problems);

  step("2. unit points at a handle that does not exist");
  const noHandle = await m.bad("POST", "/declare", {
    agents: [{ name: "bot", apis: [], unit: "http://127.0.0.1:1/nope" }],
  });
  show("it answered:", noHandle.problems);
  ok("stopped", JSON.stringify(noHandle.problems).includes("there is no handle named http://127.0.0.1:1/nope"), noHandle.problems);

  step("3. load two: one on a local handle only, one that also carries a real model lane");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
    ],
    places: [{ place: "local" }],
    modes: [
      // No station in this mode uses a model (empty apiMode), so any agent can handle it.
      { mode: "plain", cycles: [{ cycle: "go", from: [], next: [], infer: out.url("/infer") }] },
      // This mode requires a chat lane, so only agents with that lane can handle it.
      { mode: "thinky", cycles: [{ cycle: "think", apiMode: "chat", from: [], next: [], infer: out.url("/infer") }] },
    ],
    agents: [
      { name: "runner", apis: [], unit: out.url("/unit") },
      { name: "thinker", apis: [["DEEPSEEK_API_KEY", "deepseek-chat"]], unit: out.url("/unit") },
    ],
  });
  ok("both went in", (loaded.agents as string[]).length === 2, loaded.agents);

  // =============== Part 2: actual-use validation ===============
  part("Part two: checks at the level of use");
  console.log("  Registered is not the same as able to take work. For a mode the lanes do not cover, the task just sits in the database, unmoving and unreported.");

  step("4. which modes each can serve - computed on this side");
  const runner = await m.api<Record<string, unknown>>("GET", "/agents/runner");
  const thinker = await m.api<Record<string, unknown>>("GET", "/agents/thinker");
  show("runner：", { modes: runner.modes, tracks: runner.tracks });
  show("thinker：", { modes: thinker.modes, tracks: thinker.tracks });

  ok("runner can serve plain (that mode needs no model)", (runner.modes as string[]).includes("plain"), runner.modes);
  ok(
    "runner cannot serve thinky - it carries no chat lane at all",
    !(runner.modes as string[]).includes("thinky"),
    runner.modes,
  );
  ok("thinker can serve both", (thinker.modes as string[]).length === 2, thinker.modes);

  step("5. whether the key is set - only presence is returned; the value never leaves the API");
  const lane = (thinker.tracks as Record<string, unknown>[])[0];
  show("that lane of thinker:", lane);
  ok("it says the lane is registered in the api table", lane.registered === true, lane);
  ok("it says whether the key is set", typeof lane.keySet === "boolean", lane);
  ok(
    "the whole answer contains no secret",
    !JSON.stringify(thinker).includes(process.env.DEEPSEEK_API_KEY ?? "no such environment variable"),
    "(nothing leaked)",
  );

  step("6. hand runner the mode it cannot serve");
  await m.api("POST", "/tasks", {
    id: "t-bad", mode: "thinky", agent: "runner", place: "local", source: "user", description: "it cannot serve this",
  });
  const stuck = await until("the API to explain why", async () => {
    const w = await m.api<{ movable: boolean; problems: string[] }>("GET", "/tasks/t-bad/why");
    return w.problems.length > 0 ? w : null;
  });
  show("why it is not moving:", stuck.problems);
  ok("it is not lying there silently - the API states the reason", stuck.movable === false, stuck);
  ok(
    "and it points at the root cause: this agent has no lane of that shape",
    JSON.stringify(stuck.problems).includes("cannot select a handle for this station"),
    stuck.problems,
  );

  step("7. hand runner the mode it can serve");
  await m.api("POST", "/tasks", {
    id: "t-ok", mode: "plain", agent: "runner", place: "local", source: "user", description: "it can serve this one",
  });
  const finished = await until("t-ok to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-ok");
    return d.state === "done" ? d : null;
  });
  ok("it finished", (finished as { state: string }).state === "done", finished);

  const echoed = (await m.api<{ rows: Record<string, unknown>[] }>("GET", "/tasks/t-ok/messages")).rows
    .filter((r) => r.kind === "prompt")
    .at(-1);
  show("the lane the kernel picked for this station:", JSON.parse(String(echoed?.body)));
  ok(
    "an empty apiMode means no lane is picked and it goes straight to the unit handle",
    JSON.parse(String(echoed?.body))["laneForThisStation"] === null,
    echoed?.body,
  );
} finally {
  out.stop();
  m.stop();
}

done();
