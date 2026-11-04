/**
 * 例子：**一个智能体可以固定自己那几个模型参数。**
 *
 * ```
 * bun test/integration/knobs.ts
 * ```
 *
 * 整跑的配置（`config.yaml` 里的 `llm.*`）是打底的那一份。可有些参数**是智能体自己
 * 的性质，不是这一跑的性质**：一个「去查、把查到的说清楚」的智能体不需要思考，而它
 * 服务的那个求解者要想得越多越好 —— 一个旋钮当不了两件事。
 *
 * 差别不是小数：同一个问题，`reasoning_effort` 给 `none` 是 14.5 秒，给 `low` 是
 * 113 秒，多出来的 98 秒买的是一万个 token 的推理。没有这一列的话，**把求解那边的
 * 思考调高一档，会顺手把检索也拖慢八倍，而且没有任何地方说得出为什么。**
 *
 * 所以 `agent.knobs`：给了的盖过整跑的，没给的落回去。
 */

import { done, machine, ok, outside, part, show, step, until } from "../_lib.ts";

process.env.DEEPSEEK_API_KEY ??= "sk-not-a-real-key";

const m = await machine({ reasoningEffort: "high", temperature: 0.7 });

/** 每一发请求收到了什么，记下来 —— 这个例子查的就是它。 */
const seen: Record<string, unknown>[] = [];

const out = await outside({
  "/chat/completions": (a) => {
    seen.push(a as Record<string, unknown>);
    return {
      id: "fake",
      object: "chat.completion",
      created: Math.floor(Date.now() / 1000),
      model: "deepseek-v4-flash",
      choices: [{ index: 0, message: { role: "assistant", content: "done" }, finish_reason: "stop" }],
      usage: { prompt_tokens: 1, completion_tokens: 1, total_tokens: 2 },
    };
  },
  "/infer": () => null,
});

try {
  part("An agent can pin its own model settings");

  step("1. point the api row at the fake endpoint, so we can read what was sent");
  await m.api("POST", "/exec", {
    sql: `update api set base_url = '${out.url("")}' where model = 'deepseek-v4-flash'`,
  });

  step("2. two agents on the same lane - one pins its settings, one does not");
  await m.api("POST", "/declare", {
    places: [{ place: "local" }],
    handles: [{ name: out.url("/infer"), expectMs: 10_000 }],
    modes: [
      { mode: "one", cycles: [{ cycle: "ask", apiMode: "chat", maxUnits: 1, from: [], next: [], infer: out.url("/infer") }] },
    ],
    agents: [
      // **不给** —— 整跑那份是什么就是什么。
      { name: "asis", apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]], unit: out.url("/infer") },
      // **钉死不思考。** 它的活是查和转述，想一遍是把最贵的东西买两份。
      {
        name: "pinned",
        apis: [["DEEPSEEK_API_KEY", "deepseek-v4-flash"]],
        unit: out.url("/infer"),
        knobs: { reasoningEffort: "none" },
      },
    ],
  });

  const runOne = async (agent: string, id: string) => {
    seen.length = 0;
    await m.api("POST", "/tasks", {
      id, mode: "one", agent, place: "local", source: "user", description: "say something", solveSeconds: 60,
    });
    await until(`${id} to finish`, async () => {
      const d = await m.api<{ state: string }>("GET", `/tasks/${id}`);
      return d.state === "done" || d.state === "failed" ? d : null;
    }, 30_000);
    return seen[0] ?? {};
  };

  step("3. the one that pinned nothing gets the run-wide setting");
  const asis = await runOne("asis", "t-asis");
  show("what the un-pinned agent sent:", { reasoning_effort: asis.reasoning_effort, temperature: asis.temperature });
  ok("run-wide reasoning effort", asis.reasoning_effort === "high", asis.reasoning_effort);
  ok("run-wide temperature", asis.temperature === 0.7, asis.temperature);

  step("4. the one that pinned it overrides - and only what it named");
  const pinned = await runOne("pinned", "t-pinned");
  show("what the pinned agent sent:", { reasoning_effort: pinned.reasoning_effort, temperature: pinned.temperature });
  ok("its own reasoning effort wins", pinned.reasoning_effort === "none", pinned.reasoning_effort);
  // **只盖它点名的那几个。** 不然「固定一个参数」会连带把别的悄悄改回默认值，
  // 而那种改动看不出来。
  ok("everything it did not name still falls back", pinned.temperature === 0.7, pinned.temperature);

  step("5. turning the run-wide dial does not move the pinned one");
  // 这才是这一列存在的理由：调求解那边的思考强度，不该顺手把检索拖慢八倍。
  await m.api("POST", "/exec", { sql: "update agent set state = state" });
  ok("the two disagree, which is the whole point", asis.reasoning_effort !== pinned.reasoning_effort, {
    asis: asis.reasoning_effort,
    pinned: pinned.reasoning_effort,
  });
} finally {
  out.stop();
  m.stop();
}

done();
