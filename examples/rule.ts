/**
 * 例子：**从外面加一条规则**（挂在时刻上就是钩子）。
 *
 * ```
 * bun examples/rule.ts
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

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/** 每条规则被喊到时，把「这是哪一刻、哪个任务」记下来。 */
const seen: { who: string; moment: unknown; task: unknown }[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "干完了" }),
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
  part("第一部分：注册");

  step("① 挂到一个内核根本不会喊的时刻上");
  const 假时刻 = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/audit"), expectMs: 10_000 }],
    rules: [
      {
        identity: out.url("/audit"), does: "审一下", params: {}, writes: {}, scope: {},
        when: [[{ dim: "moment", key: "", op: "eq", value: "before_everything" }]],
      },
    ],
  });
  show("回的是：", 假时刻.problems);
  ok(
    "拦住了 —— 并且把内核真会喊的那几刻列出来",
    JSON.stringify(假时刻.problems).includes("不认得的时刻"),
    假时刻.problems,
  );

  step("② moment 维度上还写了 key");
  const 多写了 = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/audit"), expectMs: 10_000 }],
    rules: [
      {
        identity: out.url("/audit"), does: "审一下", params: {}, writes: {}, scope: {},
        when: [[{ dim: "moment", key: "name", op: "eq", value: "pre_send" }]],
      },
    ],
  });
  show("回的是：", 多写了.problems);
  ok("说清了这一维不看属性", JSON.stringify(多写了.problems).includes("不看属性"), 多写了.problems);

  step("③ 一条条件都不给");
  const 没条件 = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/audit"), expectMs: 10_000 }],
    rules: [{ identity: out.url("/audit"), does: "审一下", params: {}, writes: {}, scope: {} }],
  });
  show("回的是：", 没条件.problems);
  ok(
    "**一条都没有 = 永远不触发**，不是「总是触发」",
    JSON.stringify(没条件.problems).includes("永远不会被跑到"),
    没条件.problems,
  );

  step("④ 灌两条对的：一条只在出站前跑，一条只在任务收尾时跑");
  const 灌好 = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/audit"), expectMs: 10_000 },
      { name: out.url("/wrapup"), expectMs: 10_000 },
    ],
    rules: [
      {
        identity: out.url("/audit"), does: "出站前审一遍", params: {}, writes: {},
        scope: { table: "agent_*_msg", 只读: true },
        when: [[{ dim: "moment", key: "", op: "eq", value: "pre_send" }]],
      },
      {
        identity: out.url("/wrapup"), does: "任务收尾时归档", params: {}, writes: {},
        scope: { table: "task", 只读: true },
        when: [[{ dim: "moment", key: "", op: "eq", value: "task_done" }]],
      },
    ],
    places: [{ place: "local" }],
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  ok("两条都进去了", (灌好.rules as string[]).length === 2, 灌好.rules);

  step("⑤ 查一下登记成什么样");
  const { rules } = await m.api<{ rules: Record<string, unknown>[] }>("GET", "/rules");
  show("规则清单：", rules.map((r) => ({ identity: r.identity, when: r.when, neverFires: r.neverFires })));
  ok("挂在时刻上的钩子就在这张清单里，不另开表", rules.length === 2, rules.length);
  ok("都不会永远不触发", rules.every((r) => r.neverFires === false), rules);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("第二部分：使用层次的校验");
  console.log("  挂上了 ≠ 到点被喊到。而且更要紧的是：它不该在别的时刻被喊。");

  step("⑥ 发一个任务，跑完，数一数各条规则被喊了几次、在哪一刻");
  await m.api("POST", "/tasks", {
    id: "t-1", mode: "demo", agent: "bot", place: "local", source: "user", description: "随便干点什么",
  });
  await until("t-1 跑完", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-1");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  // 收尾那一刻是在任务推到 done 之后喊的，等它一下。
  await until("wrapup 被喊到", async () => (at("wrapup").length > 0 ? true : null), 5_000);

  show("audit 被喊到的时刻：", at("audit"));
  show("wrapup 被喊到的时刻：", at("wrapup"));

  ok("audit 在 pre_send 被喊到了", at("audit").includes("pre_send"), at("audit"));
  ok(
    "**audit 只在 pre_send 被喊** —— 没有在别的时刻乱跑",
    at("audit").every((x) => x === "pre_send"),
    at("audit"),
  );
  ok("wrapup 在 task_done 被喊到了", at("wrapup").includes("task_done"), at("wrapup"));
  ok(
    "**wrapup 只在 task_done 被喊** —— 它没在每个单元上都跑一遍",
    at("wrapup").every((x) => x === "task_done"),
    at("wrapup"),
  );
  ok("两条规则各管各的，没串", at("audit").length > 0 && at("wrapup").length > 0);

  step("⑦ 规则收到的那份东西里带着「现在是哪一刻」和这是哪个任务");
  show("wrapup 最后收到的：", seen.filter((s) => s.who === "wrapup").at(-1));
  ok(
    "带着任务 id —— 规则知道自己在给谁干活",
    seen.filter((s) => s.who === "wrapup").at(-1)?.task === "t-1",
    seen.at(-1),
  );
} finally {
  out.stop();
  m.stop();
}

done();
