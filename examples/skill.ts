/**
 * 例子：**从外面加一个 skill**。
 *
 * ```
 * bun examples/skill.ts
 * ```
 *
 * skill 跟工具最大的分别：**模型不挑它**。工具是摆出来让模型自己决定调不调；
 * skill 是条件一命中就**塞进上下文**，模型只会看到已经塞好的结果。
 *
 * 两种写法：
 *
 * - `body` 写死 —— 固定的一段话
 * - `body` 留空 —— **动态生成**：触发那一刻去调同名句柄，它现给一段
 *
 * ## 要害在第二部分
 *
 * skill 塞没塞进去，看的是**上下文里那一行**。所以第二部分直接把这个执行单元的
 * 消息拉出来，看有没有 `kind = "skill"` 的那条、内容对不对、`who` 记的是不是它。
 * 光看「注册成功」什么也证明不了。
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/** 动态 skill 被喊到时，把它拿到的事实记下来 —— 用来验它确实是**现生成**的。 */
const 现给过: Record<string, unknown>[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "干完了" }),
  // 动态 skill：内核把这一轮的事实递过来，这儿现拼一段话回去。
  "/recap": (a) => {
    现给过.push(a);
    const f = (a.facts ?? {}) as { task?: { id?: string; description?: string } };
    return `【现生成的】这道题是 ${f.task?.id}：${f.task?.description}`;
  },
});

/** 拉这个任务这一轮的上下文。 */
async function ctx(id: string) {
  return (await m.api<{ rows: Record<string, unknown>[] }>("GET", `/tasks/${id}/messages`)).rows;
}

try {
  // ═══════════════ 第一部分：注册 ═══════════════
  part("第一部分：注册");

  step("① body 留空（说好要动态生成），却没有同名句柄");
  const 没人给 = await m.bad("POST", "/declare", {
    skills: [{ identity: "recap", does: "复述一下题目", params: {}, role: "user", when: [[{ dim: "task", key: "source", op: "eq", value: "user" }]] }],
  });
  show("回的是：", 没人给.problems);
  ok(
    "拦住了 —— 没人能把内容现给出来",
    JSON.stringify(没人给.problems).includes("没人能把内容现给出来"),
    没人给.problems,
  );

  step("② 一条触发条件都不给");
  const 没条件 = await m.bad("POST", "/declare", {
    skills: [{ identity: "fixed", does: "固定的一段", params: {}, role: "user", body: "写死的话" }],
  });
  show("回的是：", 没条件.problems);
  ok("**模型不挑它，所以没有条件 = 永远塞不进去**", JSON.stringify(没条件.problems).includes("永远不会被塞进去"), 没条件.problems);

  step("③ 灌三条对的：写死的、动态的、和一条登记了但停用的");
  const 灌好 = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/recap"), expectMs: 10_000 },
    ],
    skills: [
      {
        identity: "fixed", does: "固定的一段提醒", params: {}, role: "user",
        body: "【写死的】答完记得说清依据。",
        when: [[{ dim: "task", key: "source", op: "eq", value: "user" }]],
      },
      {
        // body 留空 = 动态生成，内容由这条句柄在触发那一刻现给。
        identity: out.url("/recap"), does: "把题目复述一遍", params: {}, role: "user",
        when: [[{ dim: "task", key: "description", op: "contains", value: "复述" }]],
      },
      {
        identity: "offline", does: "停用了的", params: {}, role: "user", body: "【不该出现】",
        usable: false,
        when: [[{ dim: "task", key: "source", op: "eq", value: "user" }]],
      },
    ],
    places: [{ place: "local" }],
    modes: [{ mode: "demo", cycles: [{ cycle: "ask", from: [], next: [], infer: out.url("/unit") }] }],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  ok("三条都进去了", (灌好.skills as string[]).length === 3, 灌好.skills);

  step("④ 查一下：哪条是写死的、哪条是现生成的");
  const { skills } = await m.api<{ skills: Record<string, unknown>[] }>("GET", "/skills");
  show("skill 清单：", skills.map((s) => ({ identity: s.identity, dynamic: s.dynamic, usable: s.usable })));
  ok("动态的那条标出来了", skills.find((s) => String(s.identity).endsWith("/recap"))?.dynamic === true, skills);
  ok("写死的那条不是动态的", skills.find((s) => s.identity === "fixed")?.dynamic === false, skills);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("第二部分：使用层次的校验");
  console.log("  塞没塞进去，看上下文里那一行 —— 注册成功什么也证明不了。");

  step("⑤ 发一个两条都该命中的任务（来源是 user，描述里有「复述」）");
  await m.api("POST", "/tasks", {
    id: "t-both", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "复述一下再回答我",
  });
  await until("t-both 跑完", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-both");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const 上下文 = await ctx("t-both");
  const 塞进去的 = 上下文.filter((r) => r.kind === "skill");
  show("上下文里 kind=skill 的那些：", 塞进去的.map((r) => r.body));

  ok("**写死那条真的塞进去了**", 塞进去的.some((r) => String(r.body).includes("【写死的】")), 塞进去的);
  ok(
    "**动态那条塞的是现生成的内容** —— 不是登记时写好的",
    塞进去的.some((r) => String(r.body).includes("这道题是 t-both：复述一下再回答我")),
    塞进去的,
  );
  ok("停用那条没进来", !塞进去的.some((r) => String(r.body).includes("【不该出现】")), 塞进去的);
  ok("塞进去的 role 是 user（模型看得见）", 塞进去的.every((r) => r.role === "user"), 塞进去的);

  step("⑥ 动态那条拿到的是**这一轮的事实**，不是空壳");
  show("它收到的 task：", (现给过.at(-1)?.facts as { task?: unknown })?.task);
  ok(
    "递过去的事实里有这个任务",
    ((现给过.at(-1)?.facts as { task?: { id?: string } })?.task?.id) === "t-both",
    现给过.at(-1),
  );

  step("⑦ 发一个只命中写死那条的任务（描述里没有「复述」）");
  await m.api("POST", "/tasks", {
    id: "t-one", mode: "demo", agent: "bot", place: "local",
    source: "user", description: "直接回答我就行",
  });
  await until("t-one 跑完", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-one");
    return d.state === "done" || d.state === "failed" ? d : null;
  });
  const 这次塞的 = (await ctx("t-one")).filter((r) => r.kind === "skill");
  show("这次塞进去的：", 这次塞的.map((r) => r.body));
  ok("写死那条还在", 这次塞的.some((r) => String(r.body).includes("【写死的】")), 这次塞的);
  ok(
    "**动态那条没进来** —— 条件真的在起作用",
    !这次塞的.some((r) => String(r.body).includes("这道题是")),
    这次塞的,
  );
} finally {
  out.stop();
  m.stop();
}

done();
