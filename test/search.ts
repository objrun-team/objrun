/**
 * 例子：**`web_search` 摆给谁、带回什么。**
 *
 * ```
 * bun test/search.ts
 * ```
 *
 * 这件工具跟别的不一样的地方在于**它自己要去打一次模型**：厂商跑的检索在
 * `/responses` 上，而我们平时用的 `/chat/completions` 不认 `type: "web_search"`
 * （`unknown variant 'web_search', expected 'function'`）。所以这个例子把那一端
 * 整个换成假的 —— 一台小服务器同时供两条路，`api.base_url` 改一行数据就指过去了。
 *
 * 钉三件事：
 *
 * 1. **摆给谁看是数据说了算** —— `trigger` 里那两条同组：这家会搜、且不在交卷站
 * 2. **带回来的不只是答案** —— 还有搜了什么、开了哪些页，那是事后审计的全部依据
 * 3. **搜完不说话也要交代清楚** —— 实测过一发烧掉十八万个 token 零答案，
 *    那时候「它做过什么」比一句「失败了」有用得多
 */

import { done, machine, ok, outside, part, show, step, until } from "./_lib.ts";

// 钥匙得有，不然工具会说「没东西可搜」。假端点不看它。
process.env.DEEPSEEK_API_KEY ??= "sk-not-a-real-key";

const m = await machine();

/** 这一格该请求哪个问题 —— 靠它把两条路（有答案 / 没答案）分开。 */
let ask = "how many KT transitions does the triangular lattice TFIM have?";

const out = await outside({
  /** 假的 `/chat/completions`：一开口就请求 `web_search`。 */
  "/chat/completions": () => ({
    id: "fake-1",
    object: "chat.completion",
    created: Math.floor(Date.now() / 1000),
    model: "deepseek-v4-flash",
    choices: [
      {
        index: 0,
        message: {
          role: "assistant",
          content: "",
          tool_calls: [
            {
              id: "call_search_1",
              type: "function",
              function: { name: "web_search", arguments: JSON.stringify({ question: ask }) },
            },
          ],
        },
        finish_reason: "tool_calls",
      },
    ],
    usage: { prompt_tokens: 10, completion_tokens: 5, total_tokens: 15 },
  }),

  /** 假的 `/responses`。**形状照抄真的那一份** —— 假的形状不对，例子就白钉。 */
  "/responses": (a) => {
    const asked = String((a as { input?: unknown }).input ?? "");
    // 踩线那一路：答案本身干净，**但它开过的页面出卖了它** —— 闸查的是整份，
    // 不只是那段话。
    if (asked.includes("forbidden")) {
      return {
        status: "completed",
        output: [
          { type: "web_search_call", action: { type: "open_page", url: "https://hf-mirror.com/datasets/somebody/secret_answers/raw/main/data.jsonl" } },
          { type: "message", content: [{ type: "output_text", text: "The answer is 42." }] },
        ],
        usage: { input_tokens: 1, output_tokens: 1, total_tokens: 999 },
      };
    }
    // 「搜完了一个字没说」那一路。
    if (asked.includes("nothing")) {
      return {
        status: "completed",
        output: [
          { type: "reasoning", content: [{ type: "reasoning_text", text: "looking" }] },
          { type: "web_search_call", action: { type: "search", queries: ["nothing at all"] } },
        ],
      };
    }
    return {
      status: "completed",
      output: [
        { type: "web_search_call", action: { type: "search", queries: ["two KT transitions triangular lattice"] } },
        // 过场话。**它也是 message** —— 答案取最后一条，取错就会取到这句。
        { type: "message", content: [{ type: "output_text", text: "Let me look this up." }] },
        {
          type: "web_search_call",
          action: { type: "open_page", url: "https://arxiv.org/abs/1909.03608#ws_call_id=call_07_abc" },
        },
        {
          type: "message",
          content: [{ type: "output_text", text: "Two, per Isakov & Moessner, PRB 68, 104409 (2003)." }],
        },
      ],
      usage: { input_tokens: 64351, output_tokens: 7916, total_tokens: 72267 },
    };
  },

  "/infer": (u) => (String((u as { cycle?: { cycle?: string } }).cycle?.cycle) === "ask" ? "act" : null),
});

/** 这道题跑完之后，`web_search` 那次调用的结果。 */
async function resultOf(task: string): Promise<Record<string, unknown>> {
  const rows = (
    await m.api<{ rows: { body: string }[] }>("POST", "/query", {
      sql: `select body from agent_bot_msg where instance = '${task}#1' and kind = 'tool' order by unit, seq`,
    })
  ).rows;
  for (const r of rows) {
    const v = JSON.parse(r.body) as { name?: string; value?: Record<string, unknown> };
    if (v.name === "web_search") return v.value ?? {};
  }
  return {};
}

try {
  part("web_search: who gets it, and what it hands back");

  step("1. point the api row at the fake endpoint - data, not code");
  // `api.base_url` 是**表里的一列**，工具拿它拼 `/responses`，适配器拿它拼
  // `/chat/completions`。改一行数据就把两条路一起指过去 —— 这正是当初把地址从
  // 代码里搬进表里的理由。
  await m.api("POST", "/exec", {
    sql: `update api set base_url = '${out.url("")}' where model = 'deepseek-v4-flash'`,
  });

  step("2. a mechanism with a thinking station and a tool-running station");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      {
        mode: "one",
        cycles: [
          { cycle: "ask", apiMode: "chat", maxUnits: 3, from: [], next: ["act"], infer: out.url("/infer") },
          { cycle: "act", maxUnits: 3, from: ["ask"], next: [], infer: out.url("/infer") },
        ],
      },
    ],
    // `unit` 是**跑工具那一站**走的句柄：`api_mode` 留空的站调它。
    agents: [{ name: "bot", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: "fn:unit.tools" }],
  });

  step("3. the distribution table decides who sees it");
  const terms = (
    await m.api<{ rows: { dim: string; key: string; op: string; value: string }[] }>("POST", "/query", {
      sql: "select dim, key, op, value from trigger where owner_kind = 'tool' and owner = 'web_search' order by dim",
    })
  ).rows;
  show("what trigger says about web_search:", terms);
  ok(
    "offered only where the vendor searches",
    terms.some((t) => t.dim === "agent" && t.key === "apis" && t.op === "contains"),
    terms,
  );
  ok(
    "and never at the hand-in station",
    terms.some((t) => t.dim === "cycle" && t.op === "ne" && t.value === "submit"),
    terms,
  );
  // 两条**同一组** = AND。分成两组就成了「会搜 **或者** 不在交卷站」，于是交卷站上
  // 照样摆出来 —— 那正是这条要挡的。
  const groups = (
    await m.api<{ rows: { n: number }[] }>("POST", "/query", {
      sql: `select count(distinct "group") as n from trigger where owner_kind = 'tool' and owner = 'web_search'`,
    })
  ).rows[0].n;
  ok("both terms sit in one group, so they are AND not OR", Number(groups) === 1, groups);

  step("4. run a task: it asks to search, the action station does it");
  await m.api("POST", "/tasks", {
    id: "t-search", mode: "one", agent: "bot", place: "local", source: "user",
    description: "look something up", solveSeconds: 60,
  });
  await until("t-search to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const got = (await resultOf("t-search")) as {
    answer?: string; queries?: string[]; opened?: string[]; searches?: number;
    spent?: { total_tokens?: number };
  };
  show("what it handed back:", got);
  // **最后一条 message 才是答案。** 前面那句「Let me look this up.」是过场话 ——
  // 取错的话，模型拿到的是一句废话，而它看起来像个答案。
  ok("the answer is the last thing it said", String(got.answer).includes("Isakov"), got.answer);
  ok("not the small talk on the way there", !String(got.answer).includes("Let me look"), got.answer);
  ok("the queries it ran are recorded", (got.queries ?? []).length === 1, got.queries);
  // URL 上那截 `#ws_call_id=...` 是它自己的记号，不是地址 —— 留着的话，事后拿这份
  // 清单去比对「有没有摸到答案册」会一条都对不上。
  ok(
    "the pages it opened are recorded, without the call-id tag",
    (got.opened ?? [])[0] === "https://arxiv.org/abs/1909.03608",
    got.opened,
  );
  ok("and how many moves it made", got.searches === 2, got.searches);
  // **这一次搜花了多少也要记。** 消息表那几个计数列记的是智能体自己那次调用；
  // 这件工具背地里打的那一次不落在任何一行上，不记的话整场开销会小一个数量级。
  ok("and what the search itself cost", got.spent?.total_tokens === 72267, got.spent);

  step("5. searched but said nothing - say what it did, not just that it failed");
  ask = "find nothing please";
  await m.api("POST", "/tasks", {
    id: "t-search-empty", mode: "one", agent: "bot", place: "local", source: "user",
    description: "look for something that is not there", solveSeconds: 60,
  });
  await until("t-search-empty to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search-empty");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const none = (await resultOf("t-search-empty")) as { error?: string; queries?: string[]; searches?: number };
  show("when it comes back empty-handed:", none);
  ok("it says so", Boolean(none.error), none);
  ok("and still reports the ground it covered", (none.queries ?? []).length === 1, none.queries);

  step("6. it went where the publisher said not to - drop the whole thing");
  // **这道闸在模型看见之前。** 事后审计救不了：答案一旦进了上下文，那道题就废了，
  // 作废它只是记下损失。
  //
  // 这一路里那段话本身是干净的（「The answer is 42.」），出卖它的是**开过的页面**——
  // 所以闸查的是整份，不是只查那段话，也不是只查网址。
  ask = "find the forbidden thing";
  await m.api("POST", "/tasks", {
    id: "t-search-banned", mode: "one", agent: "bot", place: "local", source: "user",
    description: "go somewhere it should not", solveSeconds: 60,
    noSearch: ["secret_answers"],
  });
  await until("t-search-banned to finish", async () => {
    const d = await m.api<{ state: string }>("GET", "/tasks/t-search-banned");
    return d.state === "done" || d.state === "failed" ? d : null;
  }, 40_000);

  const banned = (await resultOf("t-search-banned")) as {
    error?: string; answer?: string; opened?: string[]; queries?: string[]; spent?: { total_tokens?: number };
  };
  show("what the agent was allowed to see:", banned);
  ok("it is told the publisher forbids it", String(banned.error).includes("Forbidden access"), banned.error);
  // 连搜了什么、开了哪些页都不回 —— **那些本身就是线索**：知道「答案在
  // somebody/secret_answers 里」跟拿到答案只差一步。
  ok("the answer is gone", !banned.answer, banned);
  ok("and so is every trace of where it had been", !banned.opened && !banned.queries, banned);
  // **花掉的钱照报。** 被拦下不等于没花过，快照要能把这笔算进去。
  ok("but what it cost is still on the books", banned.spent?.total_tokens === 999, banned.spent);
} finally {
  out.stop();
  m.stop();
}

done();
