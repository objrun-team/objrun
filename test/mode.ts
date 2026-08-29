/**
 * 例子：**从外面加一种任务机制**（跟 dfs 同级别的那种）。
 *
 * ```
 * bun examples/mode.ts
 * ```
 *
 * 一种机制 = 一张图（几个周期，靠 `from`/`next` 连起来）+ 一个**推断函数**
 * （`infer`，决定这一站走完之后去哪儿）。
 *
 * 这个例子里那张图和那个推断函数**全在进程外**，一行内核代码没改：
 *
 * ```
 *   plan ──→ work ──→ wrap
 *              ↑         │
 *              └─────────┘   （work 可以自己转自己，wrap 收尾）
 * ```
 *
 * ## 内核只认三种回答
 *
 * 推断函数回：
 *
 * - `null` —— 到此为止
 * - `"周期名"` —— 走那个周期，**从当前这一行接**
 * - `{to, from_cycle, from_unit, status}` —— 走那个周期，**从指定那一行接**，
 *   顺带给当前这一行盖个终止状态（树要开兄弟、要回退，全靠这一种）
 *
 * **挑出候选（`next`）之外的东西 → 当场炸**，不许它自由发挥。第二部分会验这条。
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

const m = await machine();

/** 这台机器每一站都调它 —— 记下走过的路，好在第二部分对。 */
const 走过: string[] = [];

const out = await outside({
  "/unit": (u) => {
    走过.push(`${u.chain}`);
    return { role: "assistant", kind: "prompt", body: `${(u.cycle as { cycle?: string })?.cycle} 干完了` };
  },
  /**
   * 推断函数。**内核只把候选递过来，它在候选里挑一个。**
   *
   * 这儿的走法：plan → work → work → wrap → 停。第二个 work 特意用
   * `{to, from_cycle, from_unit}` 那种写法，好验「从指定那一行接」也管用。
   */
  "/infer": (a) => {
    const cyc = (a.cycle as { cycle?: string })?.cycle;
    const next = (a.next ?? []) as string[];
    const unit = Number(a.unit);
    if (cyc === "plan") return "work";
    if (cyc === "work") {
      // 第一个 work 再开一个 work（挂在自己底下），第二个就收尾。
      const 第几个 = 走过.filter((c) => c.includes("/work#")).length;
      if (第几个 <= 1) return { to: "work", from_cycle: "work", from_unit: unit };
      return "wrap";
    }
    if (cyc === "wrap") return null; // 到此为止
    return next[0] ?? null;
  },
  /** 故意挑一个候选之外的周期 —— 用来验内核不许它自由发挥。 */
  "/infer-wild": () => "根本没有这个周期",
});

try {
  // ═══════════════ 第一部分：注册 ═══════════════
  part("第一部分：注册");

  step("① next 指到这个模式外面去");
  const 指歪了 = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "flow",
        cycles: [
          { cycle: "plan", from: [], next: ["work"], infer: out.url("/infer") },
          { cycle: "work", from: ["plan"], next: ["收尾"], infer: out.url("/infer") },
        ],
      },
    ],
  });
  show("回的是：", 指歪了.problems);
  ok("拦住了 —— 不然流程走到那儿会**停住，不报错**", JSON.stringify(指歪了.problems).includes("不在这个模式里"), 指歪了.problems);

  step("② 有个周期谁都指不到（声明里的一段死代码）");
  const island = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "flow",
        cycles: [
          { cycle: "plan", from: [], next: ["work"], infer: out.url("/infer") },
          { cycle: "work", from: ["plan"], next: [], infer: out.url("/infer") },
          { cycle: "island", from: ["plan"], next: [], infer: out.url("/infer") },
        ],
      },
    ],
  });
  show("回的是：", island.problems);
  ok("从起点走不到的周期被指出来了", JSON.stringify(island.problems).includes("从起点走不到它"), island.problems);

  step("③ 一个起点都没有（每个周期的 from 都非空）");
  const 没起点 = await m.bad("POST", "/declare", {
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "flow",
        cycles: [
          { cycle: "a", from: ["b"], next: ["b"], infer: out.url("/infer") },
          { cycle: "b", from: ["a"], next: ["a"], infer: out.url("/infer") },
        ],
      },
    ],
  });
  show("回的是：", 没起点.problems);
  ok("这个模式根本进不去，当场说", JSON.stringify(没起点.problems).includes("进不去"), 没起点.problems);

  step("④ 灌一张对的图");
  const 灌好 = await m.api<Record<string, unknown>>("POST", "/declare", {
    handles: [
      { name: out.url("/unit"), expectMs: 30_000 },
      { name: out.url("/infer"), expectMs: 10_000 },
      { name: out.url("/infer-wild"), expectMs: 10_000 },
    ],
    places: [{ place: "local" }],
    modes: [
      {
        mode: "flow",
        note: "先想，再干几轮，最后收尾",
        cycles: [
          { cycle: "plan", from: [], next: ["work"], maxUnits: 1, infer: out.url("/infer") },
          { cycle: "work", from: ["plan", "work"], next: ["work", "wrap"], maxUnits: 5, infer: out.url("/infer") },
          { cycle: "wrap", from: ["work"], next: [], maxUnits: 1, infer: out.url("/infer") },
        ],
      },
      {
        mode: "wild",
        cycles: [
          { cycle: "one", from: [], next: ["two"], infer: out.url("/infer-wild") },
          { cycle: "two", from: ["one"], next: [], infer: out.url("/infer") },
        ],
      },
    ],
    agents: [{ name: "bot", apis: [], unit: out.url("/unit") }],
  });
  show("灌进去了：", { modes: 灌好.modes, cycles: 灌好.cycles, tables: 灌好.tables, entries: 灌好.entries });
  ok("两种机制都进去了", (灌好.modes as string[]).length === 2, 灌好.modes);
  ok("**起点也一并告诉你了** —— 不止一个的话发任务得指定 cycle", JSON.stringify(灌好.entries).includes("plan"), 灌好.entries);

  step("⑤ 看一眼这张图");
  const g = await m.api<Record<string, unknown>>("GET", "/modes/flow");
  show("flow：", { entries: g.entries, walkable: g.walkable, agents: g.agents, cycles: (g.cycles as unknown[]).length });
  ok("走得通", g.walkable === true, g);
  ok("bot 接得住它", (g.agents as string[]).includes("bot"), g.agents);

  // ═══════════════ 第二部分：使用层次的校验 ═══════════════
  part("第二部分：使用层次的校验");
  console.log("  图画对了 ≠ 真按它走。发个任务，看它到底走了哪条路。");

  step("⑥ 发一个任务，让它按 plan → work → work → wrap 走完");
  await m.api("POST", "/tasks", {
    id: "t-flow", mode: "flow", agent: "bot", place: "local", source: "user", description: "走一遍",
  });
  await until("t-flow 跑完", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-flow");
    return d.state === "done" ? d : null;
  });
  show("每一站的链路串：", 走过);
  ok("**走的正是声明里那条路**", 走过.length === 4, 走过);
  ok("第一站是 plan", 走过[0] === "flow/plan#1", 走过[0]);
  ok(
    "链路串是从头拼到当前，一段不落",
    走过.at(-1) === "flow/plan#1 > flow/work#2 > flow/work#3 > flow/wrap#4",
    走过.at(-1),
  );

  step("⑦ 树的形状：`{to, from_cycle, from_unit}` 那种回答真的把节点挂到了指定那一行下");
  const tree = await m.api<{ roots: Record<string, unknown>[]; orphans: unknown[] }>("GET", "/tasks/t-flow/tree");
  const 摊平 = (n: Record<string, unknown>): string[] => [
    `${n.cycle}#${n.unit}`,
    ...((n.children ?? []) as Record<string, unknown>[]).flatMap(摊平),
  ];
  show("树：", tree.roots.map(摊平));
  ok("一棵树，不是四个各自为政的根", tree.roots.length === 1, tree.roots.length);
  ok("没有孤儿（父指的那一行都在）", tree.orphans.length === 0, tree.orphans);

  step("⑧ 推断函数挑了一个**候选之外**的周期");
  await m.api("POST", "/tasks", {
    id: "t-wild", mode: "wild", agent: "bot", place: "local", source: "user", description: "看它敢不敢乱挑",
  });
  const 卡住 = await until("内核把「走不下去」写进库", async () => {
    const w = await m.api<{ problems: string[] }>("GET", "/tasks/t-wild/why");
    return w.problems.some((p) => p.includes("不在候选里")) ? w : null;
  });
  show("为什么不动：", 卡住.problems);
  ok("**内核不许它自由发挥**，而且把候选是什么一起说了", JSON.stringify(卡住.problems).includes("不在候选里"), 卡住.problems);
  ok(
    "这句话是从接口上问出来的，不用去翻服务器日志",
    卡住.problems.some((p) => p.includes("内核推它的时候炸了")),
    卡住.problems,
  );
} finally {
  out.stop();
  m.stop();
}

done();
