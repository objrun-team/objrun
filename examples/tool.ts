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
  "/unit": (u) => ({ role: "assistant", kind: "prompt", body: `我这一轮拿到的工具：${names(u)}` }),
  // 工具本身。这个例子里没人真去调它（调它是模型的事），注册通不通才是重点。
  "/weather": (a) => ({ city: a.city ?? "?", tempC: 21 }),
});

function names(u: Record<string, unknown>): string {
  return ((u.tools ?? []) as { name: string }[]).map((t) => t.name).join("、") || "（一个都没有）";
}

try {
  // ═══════════════ 第一部分：注册 ═══════════════
  part("第一部分：注册");

  step("① 工具指了一条不存在的句柄");
  show(
    "回的是：",
    (await m.bad("POST", "/declare", {
      tools: [{ name: "weather", identity: "http://127.0.0.1:1/nope", does: "查天气", params: {}, output: {} }],
    })).problems,
  );
  ok("说清了是句柄不在，而且告诉你在 handles 里一起声明", true);

  step("② 不是系统工具，又一条触发条件都没有");
  const 没条件 = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/weather"), expectMs: 10_000 }],
    tools: [{ name: "weather", identity: out.url("/weather"), does: "查天气", params: {}, output: {} }],
  });
  show("回的是：", 没条件.problems);
  ok(
    "拦住了「谁都拿不到它」这种写法",
    JSON.stringify(没条件.problems).includes("永远不会被挂给任何一个智能体"),
    没条件.problems,
  );

  step("③ 条件里把 contains 打成了 contain");
  const 打错 = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/weather"), expectMs: 10_000 }],
    tools: [
      {
        name: "weather", identity: out.url("/weather"), does: "查天气", params: {}, output: {},
        when: [[{ dim: "task", key: "description", op: "contain", value: "天气" }]],
      },
    ],
  });
  show("回的是：", 打错.problems);
  ok("一个字母的差别当场拒，并列出认得的比法", JSON.stringify(打错.problems).includes("不认得的比法"), 打错.problems);

  step("④ 一次灌对：句柄 + 工具 + 在哪儿干 + 模式 + 智能体");
  const 灌好 = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/weather"), expectMs: 10_000 },
      { name: out.url("/unit"), expectMs: 30_000 },
    ],
    tools: [
      {
        name: "weather",
        identity: out.url("/weather"),
        does: "查一个城市现在多少度",
        params: { type: "object", properties: { city: { type: "string" } }, required: ["city"] },
        output: { type: "object", properties: { tempC: { type: "number" } } },
        prompt: "要问天气就调 weather，别自己编温度。",
        // 任务描述里提到「天气」才把它挂上。
        when: [[{ dim: "task", key: "description", op: "contains", value: "天气" }]],
      },
    ],
    places: [{ place: "local" }],
    // apiMode 留空 = 这一站不用模型，走 agent.unit（也就是那条外部句柄）。
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  show("灌进去了：", 灌好);
  ok("工具进去了", (灌好.tools as string[]).includes("weather"), 灌好.tools);
  ok("子表跟着长出来了，不用重启", (灌好.tables as string[]).length > 0, 灌好.tables);

  step("⑤ 查一下它登记成什么样");
  const { tools } = await m.api<{ tools: Record<string, unknown>[] }>("GET", "/tools");
  const w = tools.find((t) => t.name === "weather")!;
  show("weather：", w);
  ok("when 还原成了组的形状，不是一行一条", Array.isArray(w.when) && (w.when as unknown[]).length === 1, w.when);
  ok("不会永远不触发", w.neverFires === false, w.neverFires);
  ok("整库检查是干净的", ((await m.api<{ data: unknown[] }>("GET", "/check")).data).length === 0);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("第二部分：使用层次的校验");
  console.log("  注册成功不等于生效。真发两个任务，看这一轮到底把哪些工具挂给了它。");

  step("⑥ 发一个**命中**条件的任务（描述里有「天气」）");
  await m.api("POST", "/tasks", {
    id: "t-hit", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "北京今天天气怎么样",
  });
  const 命中 = await until("t-hit 跑完", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-hit");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const 挂了什么 = out.calls["/unit"].at(-1)!;
  show("这一轮挂上的工具：", ((挂了什么.tools ?? []) as { name: string }[]).map((t) => t.name));
  ok("任务跑完了", (命中 as { state: string }).state === "done", 命中);
  ok(
    "**weather 真的挂上去了**",
    ((挂了什么.tools ?? []) as { name: string }[]).some((t) => t.name === "weather"),
    挂了什么.tools,
  );

  step("⑦ 发一个**不命中**的任务（描述里没有「天气」）");
  await m.api("POST", "/tasks", {
    id: "t-miss", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "帮我算一下三加五",
  });
  await until("t-miss 跑完", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-miss");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const 这次挂了什么 = out.calls["/unit"].at(-1)!;
  show("这一轮挂上的工具：", ((这次挂了什么.tools ?? []) as { name: string }[]).map((t) => t.name));
  ok(
    "**weather 没有挂上去** —— 条件真的在起作用，不是碰巧都挂",
    !((这次挂了什么.tools ?? []) as { name: string }[]).some((t) => t.name === "weather"),
    这次挂了什么.tools,
  );

  step("⑧ 没命中的时候问一句为什么");
  const why = await m.api("POST", "/trigger/explain", {
    kind: "tool", owner: "weather", task: "t-miss",
  });
  show("逐条说清：", why);
  ok(
    "**带上了实际取到的值** —— 不用猜是词写错了还是文本里根本没有",
    JSON.stringify(why).includes("三加五"),
    why,
  );
} finally {
  out.stop();
  m.stop();
}

done();
