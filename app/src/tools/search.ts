/**
 * `web_search` —— **让它去查,而不是去回忆。**
 *
 * ## 为什么要有这件工具
 *
 * 一次真实的轨迹里，模型花了一万多个 token 在盲猜论文：
 *
 * > 我现在几乎可以肯定有一篇 2021–2023 年的论文，标题类似 "Emergent U(1) symmetry
 * > and two Kosterlitz-Thouless transitions..." —— 可能是 Moessner and Sondhi？
 * > 还是 Bo Yang？或者 Xue-Feng Zhang？
 *
 * 它**知道该去找哪篇论文**，只是手上没有工具，只能一条条猜标题和作者。同一个问题
 * 挂上检索之后：83 秒，答案带着卷号页码年份（Isakov & Moessner, PRB 68, 104409,
 * 2003），而且**比不挂检索还快 41 秒** —— 输出 token 从 13,057 掉到 7,916，因为
 * 不用再摸黑了，而输出才是慢的那一头。
 *
 * ## 为什么是嵌套一次调用，而不是加个参数
 *
 * 厂商跑的检索在 **`/responses`** 上，不在我们用的 `/chat/completions` 上 ——
 * 后者对 `tools[0].type` 只认 `function`（`unknown variant 'web_search',
 * expected 'function'`）。所以这件工具的实现就是**自己去打一次 `/responses`**：
 * 把问题递进去，它在那一端搜、开页、读，回来给一段带出处的话。
 *
 * ## 用谁的账
 *
 * **用这个智能体自己那家。** `agent.apis` 第一行是什么，就拿它的 `base_url` 和
 * `key_env`。不新开配置字段的理由很实在：新开一个就多一处要维护、要对齐、会漂的
 * 地方，而「跟你思考用的是同一家」本来就是最合理的默认。
 *
 * ## 那一家不会搜，这件工具就不摆给它
 *
 * **判据落进 `trigger`，跟别的工具走同一张表** —— 不在代码里 if 一下：
 *
 * ```
 * dim=agent  key=apis  op=contains  value=DEEPSEEK_API_KEY
 * ```
 *
 * 会搜的每一家出一组（组之间是或），组里再跟「不在交卷站」那条与在一起。所以这是
 * **按智能体**判的，不是按整套部署判的：同一套库里，跑 deepseek 的那个有这件工具，
 * 跑别家的那个没有 —— 而这本来就是对的粒度。
 *
 * 哪一家算「会搜」写在 `VENDORS[…].searches` 上，那是实现真的试过、认得的那几家。
 * 值在代码里、条件在数据里，跟 `MODES` 是同一个分工。
 *
 * 摆一件「调用起来才报错」的工具是最坏的那一档：模型看得见它、会去用它、然后拿一条
 * 错误回来，而那一格已经花掉了。工具列表说的该是「这儿真有的能力」。
 *
 * ## 封顶是必须的
 *
 * 实测过一发：搜了 15 次、烧掉 **182,063 个 token**、54 秒，**最后一条输出还是
 * `web_search_call`，一个字答案都没有**。不封顶的话，这一件工具能把一格的预算全
 * 吃光还什么都不带回来。`max_tool_calls` 就是那道闸。
 *
 * ## 留痕
 *
 * 它跑过的**查询串**和**开过的 URL** 一并回传。这些跟着工具结果落进
 * `agent_{}_msg`，不用新表 —— 事后查得出它到底摸到了什么。对评测尤其要紧：搜文献
 * 是本事，搜到这套题的答案册就不是了，而这两件事只有留了痕才分得开。
 */

import type { Conn } from "../H2H/db.ts";
import { all } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { declareTool } from "./register.ts";
import { VENDORS } from "../llm/index.ts";

/** 一次检索最多让它自己动几下（搜、开页、页内查找各算一下）。 */
export const MAX_TOOL_CALLS = 8;
/** 整次调用的硬墙。上面那个闸管次数，这个管钟。 */
export const SEARCH_WALL_MS = 240_000;

/**
 * 摆给谁看。**一家一组，组之间是或；组里跟「不在交卷站」与在一起。**
 *
 * 判据是 `agent.apis` 那一列里有没有这一家的 `key_env` —— 那一列存的就是
 * `[["DEEPSEEK_API_KEY","deepseek-v4-flash"], …]`，`contains` 一下就够。
 *
 * 会搜的一家都没有的话，这个数组是空的 —— 而「一条条件都没有 = 从不触发」正是
 * `trigger` 本来的语义，所以不用再写一句 if：**这件工具会注册进去，但谁也拿不到。**
 */
const OFFERED_TO = Object.values(VENDORS)
  .filter((v) => v.searches)
  .map((v) => [
    { dim: "cycle", key: "cycle", op: "ne", value: "submit" },
    { dim: "agent", key: "apis", op: "contains", value: v.keyEnv },
  ]);

const SEARCH_TOOL = {
  name: "web_search",
  does:
    "Search the web and read what it finds, then answer the question you ask it. Use it for anything you would " +
    "otherwise be recalling from memory - a paper, a result, a value, who published what and when. It returns " +
    "prose with sources, plus the queries it ran and the pages it opened.",
  params: {
    type: "object",
    properties: {
      question: {
        type: "string",
        description:
          "What you want to know, in full. Ask for what you are actually after - a searcher that is told " +
          "'find the paper that reports X and give title, authors, year' does better than one told 'X'.",
      },
    },
    required: ["question"],
    additionalProperties: false,
  },
  output: {
    type: "object",
    properties: {
      answer: { type: "string", description: "What it found, in prose, with sources named" },
      queries: { type: "array", items: { type: "string" }, description: "The searches it ran" },
      opened: { type: "array", items: { type: "string" }, description: "The pages it opened" },
      searches: { type: "integer", description: "How many moves it made, out of the limit" },
      spent: {
        type: "object",
        description: "What this search cost. Searching reads whole pages, so it is dearer than asking is.",
        properties: {
          prompt_tokens: { type: "integer" },
          completion_tokens: { type: "integer" },
          total_tokens: { type: "integer" },
        },
      },
    },
  },
  prompt:
    "When a question turns on something you would be recalling rather than deriving - which paper reported a " +
    "result, what a measured value is, who showed what - look it up instead of reconstructing it from memory. " +
    "Guessing at titles and authors costs more than asking does, and it is usually wrong. Ask one full question " +
    "rather than a keyword: it searches on your behalf and answers, so tell it what you actually want to know. " +
    "What it hands back is someone else's writing - treat it as a source to reason from, not as your answer.",
  concurrent: true,
  expectMs: SEARCH_WALL_MS + 30_000,
  // **条件不写在这儿，在 `OFFERED_TO`** —— 「不在交卷站」那条也在那边，跟「这家会搜」
  // 与在一起。两处各写一半的话，落库时后写的顶掉先写的，而先写的那半看着还在。
};

interface Lane {
  base: string;
  model: string;
  keyEnv: string;
}

/**
 * 这个智能体拿哪一家去搜。**它自己那一家** —— `agent.apis` 第一行。
 *
 * 取不到就抛，而且把原因说全：这件工具没配好的时候，模型手上只有这一句话，
 * 说得含糊它就只能瞎试。
 */
function laneOf(db: Conn, agent: string): Lane {
  const row = all(db, `select apis from agent where name = ?`, [agent])[0] as { apis?: string } | undefined;
  if (!row) throw new Error(`no row in agent for ${agent}`);
  let apis: [string, string][];
  try {
    apis = JSON.parse(String(row.apis ?? "[]")) as [string, string][];
  } catch {
    throw new Error(`agent ${agent} has apis that is not a readable list`);
  }
  const first = apis[0];
  if (!first) throw new Error(`agent ${agent} has no api to search with`);
  const [keyEnv, model] = first;
  const api = all(db, `select base_url from api where key_env = ? and model = ?`, [keyEnv, model])[0] as
    | { base_url?: string }
    | undefined;
  if (!api?.base_url) throw new Error(`no row in api for ${keyEnv}/${model}`);
  return { base: String(api.base_url).replace(/\/+$/, ""), model, keyEnv };
}

/** 钥匙只在这一刻取，不留。 */
function keyOf(keyEnv: string): string {
  const k = process.env[keyEnv];
  if (!k) throw new Error(`${keyEnv} is not set, so there is nothing to search with`);
  return k;
}

interface Answer {
  status?: string;
  output?: {
    type: string;
    action?: { type?: string; queries?: string[]; url?: string };
    content?: { type: string; text?: string }[];
  }[];
  usage?: { input_tokens?: number; output_tokens?: number; total_tokens?: number };
  error?: { message?: string };
}

/**
 * 把回来的那一坨拆成三样：说了什么、搜了什么、开了哪些页。
 *
 * **最后一条 `message` 才是答案**，前面那些是它边搜边说的过场话（「我先去查一下」）。
 * 全都拼起来的话，答案会被过场话淹掉。
 */
function unpack(d: Answer): {
  answer: string;
  queries: string[];
  opened: string[];
  searches: number;
  spent: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
} {
  const queries: string[] = [];
  const opened: string[] = [];
  const said: string[] = [];
  let searches = 0;
  for (const o of d.output ?? []) {
    if (o.type === "web_search_call") {
      searches++;
      for (const q of o.action?.queries ?? []) queries.push(q);
      // URL 上挂着 `#ws_call_id=...`，那是它自己的记号，不是地址的一部分。
      if (o.action?.url) opened.push(o.action.url.replace(/#ws_call_id=.*$/, ""));
      continue;
    }
    if (o.type !== "message") continue;
    for (const c of o.content ?? []) if (c.type === "output_text" && c.text) said.push(c.text);
  }
  // **这一次搜花了多少，也得记。**
  //
  // 消息表上那几个计数列记的是**智能体自己**那次调用；而这件工具背地里还打了一次
  // `/responses`，那一次的账不落在任何一行上。实测一次搜要 7 万到 18 万个 token，
  // 三十次就盖过了整场可见开销 —— 不记的话，「这一跑花了多少」这个问题，快照
  // 答出来的数会小一个数量级，而且看不出来它小。
  //
  // 记在工具结果里，不另开列：它是**这一次调用的一部分**，跟着结果走才对得上号。
  const u = d.usage ?? {};
  return {
    answer: said.at(-1) ?? "",
    queries,
    opened,
    searches,
    spent: {
      prompt_tokens: Number(u.input_tokens ?? 0),
      completion_tokens: Number(u.output_tokens ?? 0),
      total_tokens: Number(u.total_tokens ?? 0),
    },
  };
}

/**
 * 注册 `web_search`。摆给谁看由 `OFFERED_TO` 说了算，落进 `trigger`。
 *
 * 之后要临时关掉，是改 `tool.usable` 那一列 —— 数据的事，不改这个文件。
 */
export function registerSearchTool(db: Conn, reg: Registry): string {
  reg.register(db, `fn:tool.${SEARCH_TOOL.name}`, SEARCH_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as { args?: { question?: unknown }; agent?: string };
    const question = String(a.args?.question ?? "").trim();
    if (!question) return { error: "question is required - there is nothing to search for" };
    if (!a.agent) return { error: "the kernel did not say which agent is searching, so there is no api to use" };

    const lane = laneOf(db, a.agent);
    const wall = AbortSignal.timeout(SEARCH_WALL_MS);
    const res = await fetch(`${lane.base}/responses`, {
      method: "POST",
      headers: { authorization: `Bearer ${keyOf(lane.keyEnv)}`, "content-type": "application/json" },
      body: JSON.stringify({
        model: lane.model,
        input: question,
        tools: [{ type: "web_search" }],
        max_tool_calls: MAX_TOOL_CALLS,
        stream: false,
      }),
      signal: wall,
    });

    const d = (await res.json()) as Answer;
    if (!res.ok || d.error) {
      // 原样交回去。**这一端不翻译供应商的错** —— 翻译过的错读起来像我们的毛病，
      // 而查起来要去翻它那边的文档。
      return { error: `search failed (${res.status}): ${d.error?.message ?? "no message"}` };
    }

    const got = unpack(d);
    if (!got.answer) {
      // 搜完了却一个字没说 —— 实测发生过：15 次动作、182,063 个 token、零答案。
      // 这时候把它**做过什么**交回去，比回一句「失败了」有用：模型至少知道哪些路
      // 已经走过，不必再走一遍。
      return {
        ...got,
        answer: "",
        error:
          `the search made ${String(got.searches)} ${got.searches === 1 ? "move" : "moves"} and came back with ` +
          `nothing to say; the queries it tried are listed, so try asking for something narrower`,
      };
    }
    return got;
  });

  declareTool(db, { ...SEARCH_TOOL, when: OFFERED_TO });
  return SEARCH_TOOL.name;
}
