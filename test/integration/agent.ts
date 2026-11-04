/**
 * 例子：**加一个智能体**。
 *
 * ```
 * bun test/integration/agent.ts
 * ```
 *
 * 一个智能体由两样东西定：
 *
 * - `apis` —— **挂哪几条轨**。每条是 `[环境变量名, 模型]`，得在 `api` 表里真有那一行。
 *   一个智能体可以同时挂两条不同形状的轨（比如一条 `chat` 想和写，一条 `duplex`
 *   实时听说）—— `apis` 是个列表就是为了这个
 * - `unit` —— **这一站不用模型时调谁**。周期的 `apiMode` 留空就走它
 *
 * 「这一站走哪条轨」是**内核挑的**：按周期表上的 `apiMode`，从 `apis` 里找一条
 * `modes` 含它的。适配器不再自己挑 —— 挑的地方只许有一个，两处说了算早晚漂。
 *
 * ## 要害在第二部分
 *
 * 注册成功不代表它接得住活。一个智能体挂的轨要是覆盖不了某个模式的每一站，
 * 那些任务会**躺在库里不动**，而且不报错。所以第二部分要问三件事：
 * 它接得住哪些模式、钥匙配没配、真发个任务它动不动。
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();
const out = await outside({
  "/unit": (u) => ({
    role: "assistant",
    kind: "prompt",
    // 把内核挑给这一站的轨回显出来 —— 第二部分要看它到底挑没挑对。
    body: JSON.stringify({ laneForThisStation: u.api ?? null }),
  }),
  "/infer": () => null,
});

try {
  // ═══════════════ 第一部分：注册 ═══════════════
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
      // 这个模式每一站都不用模型（apiMode 留空）→ 谁都接得住
      { mode: "plain", cycles: [{ cycle: "go", from: [], next: [], infer: out.url("/infer") }] },
      // 这个模式要一条 chat 轨 → 只有挂了 chat 轨的智能体接得住
      { mode: "thinky", cycles: [{ cycle: "think", apiMode: "chat", from: [], next: [], infer: out.url("/infer") }] },
    ],
    agents: [
      { name: "runner", apis: [], unit: out.url("/unit") },
      { name: "thinker", apis: [["DEEPSEEK_API_KEY", "deepseek-chat"]], unit: out.url("/unit") },
    ],
  });
  ok("both went in", (loaded.agents as string[]).length === 2, loaded.agents);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
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
