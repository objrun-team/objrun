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
const generated: Record<string, unknown>[] = [];

const out = await outside({
  "/unit": () => ({ role: "assistant", kind: "prompt", body: "finished" }),
  // 动态 skill：内核把这一轮的事实递过来，这儿现拼一段话回去。
  "/recap": (a) => {
    generated.push(a);
    const f = (a.facts ?? {}) as { task?: { id?: string; description?: string } };
    return `[generated] this task is ${f.task?.id}: ${f.task?.description}`;
  },
});

/** 拉这个任务这一轮的上下文。 */
async function ctx(id: string) {
  return (await m.api<{ rows: Record<string, unknown>[] }>("GET", `/tasks/${id}/messages`)).rows;
}

try {
  // ═══════════════ 第一部分：注册 ═══════════════
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
        // body 留空 = 动态生成，内容由这条句柄在触发那一刻现给。
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

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
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
  // **skill 有自己的 role，不借 `user`。**
  //
  // 借 `user` 等于告诉模型「有人在跟你说这段话」，而它其实是我们按条件塞进去的一段
  // 提示。实测的后果：模型开始接话反问（「请把本题的具体选项发出来」），不再作答；
  // 不报错，只表现为分数低。它走 `instructions`，不进消息流（见 `llm/index.ts`
  // 的 `ROLES`）。
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
