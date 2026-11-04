/**
 * 例子：**从外面加一条规则**（挂在时刻上就是钩子）。
 *
 * ```
 * bun test/integration/rule.ts
 * ```
 *
 * 钩子在这台机器上**不另开表**：一条规则 + 一条 `dim: "moment"` 的条件，就是钩子。
 * 内核只喊「现在是哪一刻」，谁挂在这一刻上由触发条件说了算 —— 所以内核里没有
 * 任何一个规则名。
 *
 * 内核会喊到的时刻：`unit_start` / `pre_send` / `post_send` / `task_done`。
 *
 * ## 要害在第二部分
 *
 * 「挂上了」和「到点真被喊到了」是两件事。而且更要紧的是**它不该在别的时刻被喊**
 * —— 一条本该只在收尾时跑的规则，要是每一刻都跑，那不报错，只是行为完全不是
 * 你想的那样。所以第二部分要数：每条规则各被喊了几次、分别在哪一刻。
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

const m = await machine();

/** 每条规则被喊到时，把「这是哪一刻、哪个任务」记下来。 */
const seen: { who: string; moment: unknown; task: unknown }[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "finished" }),
  "/audit": (a) => {
    seen.push({ who: "audit", moment: a.moment, task: (a.task as { id?: string })?.id });
    return { ok: true };
  },
  "/wrapup": (a) => {
    seen.push({ who: "wrapup", moment: a.moment, task: (a.task as { id?: string })?.id });
    return { ok: true };
  },
});

const at = (who: string) => seen.filter((s) => s.who === who).map((s) => s.moment);

try {
  // ═══════════════ 第一部分：注册 ═══════════════
  part("Part one: registration");

  step("1. hung on a moment the kernel never raises");
  const fakeMoment = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/audit"), expectMs: 10_000 }],
    rules: [
      {
        identity: out.url("/audit"), does: "audit it", params: {}, writes: {}, scope: {},
        when: [[{ dim: "moment", key: "", op: "eq", value: "before_everything" }]],
      },
    ],
  });
  show("it answered:", fakeMoment.problems);
  ok(
    "stopped - and it lists the moments the kernel really raises",
    JSON.stringify(fakeMoment.problems).includes("unknown moment"),
    fakeMoment.problems,
  );

  step("2. a key written on the moment dimension");
  const extraKey = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/audit"), expectMs: 10_000 }],
    rules: [
      {
        identity: out.url("/audit"), does: "audit it", params: {}, writes: {}, scope: {},
        when: [[{ dim: "moment", key: "name", op: "eq", value: "pre_send" }]],
      },
    ],
  });
  show("it answered:", extraKey.problems);
  ok("it says this dimension has no attributes", JSON.stringify(extraKey.problems).includes("has no attributes"), extraKey.problems);

  step("3. not a single term");
  const noTerms = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/audit"), expectMs: 10_000 }],
    rules: [{ identity: out.url("/audit"), does: "audit it", params: {}, writes: {}, scope: {} }],
  });
  show("it answered:", noTerms.problems);
  ok(
    "no terms means never fires, not always fires",
    JSON.stringify(noTerms.problems).includes("never run"),
    noTerms.problems,
  );

  step("4. load two good ones: one only before sending, one only at task wrap-up");
  const loaded = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/audit"), expectMs: 10_000 },
      { name: out.url("/wrapup"), expectMs: 10_000 },
    ],
    rules: [
      {
        identity: out.url("/audit"), does: "audit once before sending", params: {}, writes: {},
        scope: { table: "agent_*_msg", readOnly: true },
        when: [[{ dim: "moment", key: "", op: "eq", value: "pre_send" }]],
      },
      {
        identity: out.url("/wrapup"), does: "archive at task wrap-up", params: {}, writes: {},
        scope: { table: "task", readOnly: true },
        when: [[{ dim: "moment", key: "", op: "eq", value: "task_done" }]],
      },
    ],
    places: [{ place: "local" }],
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  ok("both went in", (loaded.rules as string[]).length === 2, loaded.rules);

  step("5. read back how they were registered");
  const { rules } = await m.api<{ rules: Record<string, unknown>[] }>("GET", "/rules");
  show("the rule list:", rules.map((r) => ({ identity: r.identity, when: r.when, neverFires: r.neverFires })));
  ok("a hook hung on a moment lives in this same list; there is no separate table", rules.length === 2, rules.length);
  ok("neither is a never-fires rule", rules.every((r) => r.neverFires === false), rules);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("Part two: checks at the level of use");
  console.log("  Hung is not the same as raised on time. And more importantly: it must not be raised at other moments.");

  step("6. publish a task, let it finish, and count when each rule was raised");
  await m.api("POST", "/tasks", {
    id: "t-1", mode: "demo", agent: "bot", place: "local", source: "user", description: "do something, anything",
  });
  await until("t-1 to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-1");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  // 收尾那一刻是在任务推到 done 之后喊的，等它一下。
  await until("wrapup to be raised", async () => (at("wrapup").length > 0 ? true : null), 5_000);

  show("moments audit was raised at:", at("audit"));
  show("moments wrapup was raised at:", at("wrapup"));

  ok("audit was raised at pre_send", at("audit").includes("pre_send"), at("audit"));
  ok(
    "audit was raised ONLY at pre_send - it did not wander into other moments",
    at("audit").every((x) => x === "pre_send"),
    at("audit"),
  );
  ok("wrapup was raised at task_done", at("wrapup").includes("task_done"), at("wrapup"));
  ok(
    "wrapup was raised ONLY at task_done - it did not run once per unit",
    at("wrapup").every((x) => x === "task_done"),
    at("wrapup"),
  );
  ok("the two rules stayed in their own lanes", at("audit").length > 0 && at("wrapup").length > 0);

  step("7. what the rule receives carries which moment it is and which task");
  show("what wrapup received last:", seen.filter((s) => s.who === "wrapup").at(-1));
  ok(
    "it carries the task id - the rule knows who it is working for",
    seen.filter((s) => s.who === "wrapup").at(-1)?.task === "t-1",
    seen.at(-1),
  );
} finally {
  out.stop();
  m.stop();
}

done();
