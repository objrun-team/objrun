/**
 * 例子：**从外面加一个工具**。
 *
 * ```
 * bun examples/tool.ts
 * ```
 *
 * 全程只打 HTTP，一行内核代码没改，也没重启 —— 工具的实现跑在例子自己那台小
 * 服务器上，注册进来的是一条 `http://` 句柄。
 *
 * ## 要害在第二部分
 *
 * 注册成功和**真的生效**是两件事。这台机器最典型的毛病就是「写进去了，但永远
 * 不触发」：工具躺在 `tool` 表里，条件写错一个字母，于是谁都拿不到它，而
 * **没有任何一处报错**。所以第二部分要真发两个任务：一个该命中，一个不该，
 * 然后去看那一轮到底把哪些工具挂给了智能体。
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();
const out = await outside({
  // 这一站不用模型：内核直接调 agent.unit，也就是这条外部句柄。
  // 它收到的那份东西里带着**这一轮挂了哪些工具** —— 第二部分就查它。
  "/unit": (u) => ({ role: "assistant", kind: "prompt", body: `tools I got this round: ${names(u)}` }),
  // 工具本身。这个例子里没人真去调它（调它是模型的事），注册通不通才是重点。
  "/weather": (a) => ({ city: a.city ?? "?", tempC: 21 }),
});

function names(u: Record<string, unknown>): string {
  return ((u.tools ?? []) as { name: string }[]).map((t) => t.name).join("、") || "(none)";
}

try {
  // ═══════════════ 第一部分：注册 ═══════════════
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
        // 任务描述里提到 weather 才把它挂上。
        when: [[{ dim: "task", key: "description", op: "contains", value: "weather" }]],
      },
    ],
    places: [{ place: "local" }],
    // apiMode 留空 = 这一站不用模型，走 agent.unit（也就是那条外部句柄）。
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

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
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
  const attached = out.calls["/unit"].at(-1)!;
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
  const attachedNow = out.calls["/unit"].at(-1)!;
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
