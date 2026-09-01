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
 * ## 一次搜多深管不了，搜几次管得了
 *
 * **管不了的那半**：`/responses` 收 `max_tool_calls` 但不照办 —— 回执里那一栏原样是
 * `null`，给 2 搜 11 次，给 8 搜 13 次，一模一样。那个参数因此不发了：发一个不生效
 * 的参数比不发更坏，下一个人看见它会以为这儿有道闸。所以一次搜有多贵拦不住，实测
 * 中位 13 万 token、最多 25 万，还有**四成搜完一个字答案都没有**。
 *
 * **管得了的那半**：`task.max_searches` —— 一轮里准搜几次，跟 G 那个 `checks` 同一
 * 套规矩（一轮 = 一个节点，判死重来是新额度，被拒的不扣数）。
 *
 * 为什么闸在「次数」上而不在「格子」上，是量出来的：实测一跑，超时那批把一小时里
 * 的**一半**花在检索上，而每站的格子额度**一次都没碰到**（用得最多的一站 30 格，
 * 上限 35）。检索花的是钟，不是格子 —— 放宽格子治不了，限次数才治得了。
 *
 * 外加一道我们自己的钟：`SEARCH_WALL_MS`，单次到点就断。
 *
 * ## 留痕
 *
 * 它跑过的**查询串**和**开过的 URL** 一并回传。这些跟着工具结果落进
 * `agent_{}_msg`，不用新表 —— 事后查得出它到底摸到了什么。对评测尤其要紧：搜文献
 * 是本事，搜到这套题的答案册就不是了，而这两件事只有留了痕才分得开。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { declareTool } from "./register.ts";
import { whereAmI } from "../tasks/where.ts";
import { deliver } from "../msg/deliver.ts";
import { tableNameOf } from "../install/index.ts";
import { VENDORS } from "../llm/index.ts";

/**
 * **这件工具背后那个智能体的名字。**
 *
 * 模型、端点、思考强度都是它那一行说了算（`agent.apis` → `api.base_url`，
 * `agent.knobs`）—— 不是调用方那一行。检索是一份固定的活：去查、把查到的说清楚。
 * 跟着调用方走的话，求解那边换个模型、调一档思考强度，检索会跟着变，而没有任何
 * 地方说得出为什么。
 *
 * 库里没有这一行 = 这件工具没配好，当场说清楚，别去猜一个。
 */
export const SEARCHER = "searcher";

/**
 * 单次调用的硬墙。**管的是一次搜能拖多久**，不是能搜几次 —— 后者是
 * `task.max_searches`，见文件开头。
 *
 * 到点断掉，那一格拿一条错误继续走，不会挂到句柄的死期上。
 */
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
      searches: { type: "integer", description: "How many moves it made inside this one search" },
      left: { type: "integer", description: "Searches remaining in this attempt, when the publisher set a limit" },
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
  /** 它固定用的那几个模型参数（`agent.knobs`）。没有就是空的。 */
  knobs: Record<string, unknown>;
}

/**
 * 这个智能体拿哪一家去搜。**它自己那一家** —— `agent.apis` 第一行。
 *
 * 取不到就抛，而且把原因说全：这件工具没配好的时候，模型手上只有这一句话，
 * 说得含糊它就只能瞎试。
 */
function laneOf(db: Conn, agent: string): Lane {
  const row = all(db, `select apis, knobs from agent where name = ?`, [agent])[0] as
    | { apis?: string; knobs?: string | null }
    | undefined;
  if (!row) throw new Error(`no row in agent for ${agent} - declare it before using this tool`);
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
  let knobs: Record<string, unknown> = {};
  try {
    if (row.knobs) knobs = JSON.parse(row.knobs) as Record<string, unknown>;
  } catch {
    // 那一列写坏了不该让这件工具用不了 —— 落回那一家的默认档照样能跑
  }
  return { base: String(api.base_url).replace(/\/+$/, ""), model, keyEnv, knobs };
}

/**
 * 这道题的发布方不许搜什么。取不到就是不限制。
 *
 * 从 `task` 表读，不收调用方传的 —— 收的话，改一个参数就能把闸关掉。
 */
function forbidden(db: Conn, task: string): string[] {
  const row = all(db, `select no_search from task where id = ?`, [task])[0] as { no_search?: string } | undefined;
  if (!row?.no_search) return [];
  try {
    const v = JSON.parse(row.no_search) as unknown;
    return Array.isArray(v) ? v.map(String).filter(Boolean) : [];
  } catch {
    return [];
  }
}

/**
 * 这份检索结果里有没有踩到线。**整份都查，不只是网址。**
 *
 * ## 一条项 = 一组词，**全都出现**才算命中
 *
 * 不是拿它当一个连写的字面串去 `includes` —— 那样太松，实测漏得很具体：
 *
 * ```
 * huggingface.co/datasets/Infektyd/syntra-evals-dataset/…/cmt-physics.jsonl
 * ```
 *
 * 这是第三方把同一批题另存了一份，名字完全不一样。列 `cmt_benchmark` 挡得住原版，
 * 挡不住它 —— 而它照样是答案册。可 `cmt` 和 `benchmark` 这两个词**在那份返回里
 * 都出现过**。所以判据是「这一项里的每个词都出现过」，中间隔着什么、顺序如何、
 * 是连字符还是下划线，一概不管。
 *
 * ## 为什么整份查，不只查网址
 *
 * 同一跑里它绕了四条路：主站 → 镜像（`hf-mirror.com`）→ 文本代理（`r.jina.ai`）
 * → 存档站（`web.archive.org`），后来还试了两个跨域代理（`allorigins.win`、
 * `corsproxy.io`）。**按域名挡的话，每一条都得单列一遍，而下一条永远列不到。**
 * 查整份就没这问题：无论它从哪条路拿的，那份东西里总会出现那几个词。
 *
 * 大小写不敏感 —— 发布方没有义务把每种写法列一遍。
 */
function tripped(got: unknown, banned: string[]): string | null {
  if (banned.length === 0) return null;
  const flat = JSON.stringify(got).toLowerCase();
  for (const b of banned) {
    const terms = b.toLowerCase().split(/\s+/).filter(Boolean);
    if (terms.length && terms.every((t) => flat.includes(t))) return b;
  }
  return null;
}

/**
 * 这一轮已经搜了几次。**一轮 = 一个节点**，跟 G 那个 `checks` 是同一套规矩：
 * 判死重来是新的一轮、新的额度。
 *
 * 数的是**真搜过的次数** —— 被拦下的那几次不算，它们什么都没查到。
 *
 * 没有节点这一列的机制（不走树的那些）就按整条实例数：那种机制本来也只有一轮。
 */
function searchesIn(db: Conn, at: { sub: string; task: string }, agent: string, instance: string, unit: number): number {
  if (!agent || !instance) return 0;
  let units: number[];
  try {
    const me = all(db, `select node from "${at.sub}" where task = ? and unit = ?`, [at.task, unit])[0] as
      | { node?: number }
      | undefined;
    const rows =
      me?.node === undefined || me.node === null
        ? (all(db, `select unit from "${at.sub}" where task = ?`, [at.task]) as { unit: number }[])
        : (all(db, `select unit from "${at.sub}" where task = ? and node = ?`, [at.task, me.node]) as { unit: number }[]);
    units = rows.map((r) => Number(r.unit));
  } catch {
    return 0; // 子表还没长出来，那就还没搜过
  }
  if (units.length === 0) return 0;

  const rows = all(
    db,
    `select body from "${tableNameOf("agent_{}_msg", agent)}"
      where instance = ? and kind = 'tool' and unit in (${units.map(() => "?").join(", ")})`,
    [instance, ...units],
  ) as { body: string }[];

  let n = 0;
  for (const r of rows) {
    try {
      const v = JSON.parse(r.body) as { name?: string; value?: { error?: unknown; answer?: unknown } };
      if (v.name !== SEARCH_TOOL.name) continue;
      // 拦下的、以及超额被拒的，都没查到东西 —— 不扣数。
      if (typeof v.value?.answer !== "string") continue;
      n++;
    } catch {
      // 读不出来的行不算
    }
  }
  return n;
}

/**
 * 这道题的检索记在哪儿：**那个智能体自己的表，一道题一条实例。**
 *
 * 一道题一条，所以同一道题里的每一次检索都接得上，而不同的题互不相干。
 */
function deskOf(task: string): string {
  return `${task}#${SEARCHER}`;
}

/**
 * 把这一次的问和答**抄送一份回它自己的表**，顺带带上这边的任务信息。
 *
 * 形状就是一段普通对话，跟别的智能体没有两样：
 *
 * | 行 | 是什么 |
 * | --- | --- |
 * | `user` | 这次问它什么 |
 * | `call` | 它答了什么（`text`），外加它去搜过哪几次 |
 * | `tool` | 每一次搜的**原样记录**，一次一行 |
 *
 * 那几条原样记录是关键：**下一次把它们塞回请求，那一端会把搜到的内容恢复出来**
 * （实测：第一发搜 4 次、输入 14,543；接上之后再问，一次没重搜、输入 5,429）。
 * 内容留在那一端，这边存的只有查询串和网址，三百来个 token。
 *
 * 走 `deliver` 那条唯一的投递管道 —— seq 怎么排、身份怎么定，只许有一处说了算。
 */
function ccBack(db: Conn, task: string, question: string, answer: string): void {
  const desk = deskOf(task);
  const t = tableNameOf("agent_{}_msg", SEARCHER);
  const ctx = tableNameOf("agent_{}_ctx", SEARCHER);
  const unit =
    Number(
      (all(db, `select coalesce(max(unit), 0) as m from "${t}" where instance = ?`, [desk])[0] as { m: number }).m,
    ) + 1;

  // 这一格的账：**哪道题问的**。表里因此看得出这段对话是替谁查的。
  run(db, `insert into "${ctx}" (instance, task, unit, place, done) values (?, ?, ?, 'local', 1)`, [desk, task, unit]);

  // **一次两条：问它的那句，和它答的那句。** 都是纯文本 —— 它那一端怎么搜、翻了哪几页，
  // 在我们的对话模型里根本不是一次工具调用，所以这儿没有 call、没有工具结果行。
  //
  // 走 `deliver` 那条唯一的投递管道：身份、kind、seq 只许有一处说了算。
  deliver(db, { agent: SEARCHER, instance: desk, unit, by: "world", body: question });
  deliver(db, { agent: SEARCHER, instance: desk, unit, by: "agent", body: answer });
}

/**
 * 这道题此前问过它什么、它答过什么 —— **一段普通对话，按顺序取回来。**
 *
 * 带上它，下一次就不用把同一片地方再走一遍：**上一轮的答案本身就是材料**。
 * 不需要去保存那一端内部的检索状态 —— 它搜了什么是它自己的事，我们要的是它说了什么。
 *
 * 那张表还没长出来（这件工具从没用过）就当没有：那样这一次是全新一发，多花一点，
 * 但不会错；而在这儿抛的话，第一次检索就用不了。
 */
function deskTalk(db: Conn, task: string): { role: string; content: string }[] {
  const t = tableNameOf("agent_{}_msg", SEARCHER);
  let rows: { role: string; kind: string; body: string }[];
  try {
    rows = all(db, `select role, kind, body from "${t}" where instance = ? order by unit, seq`, [
      deskOf(task),
    ]) as { role: string; kind: string; body: string }[];
  } catch {
    return [];
  }
  return rows
    .filter((r) => r.role === "user" || r.role === "assistant")
    .map((r) => ({ role: r.role, content: r.body }));
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
      // **`ws_call_id=…` 不是它搜的东西，是那一端自己的记号。**
      //
      // 它两处都会冒出来：挂在网址后面，也会自己占一个「查询串」的位置。实测一跑
      // 里，每一次检索的 queries 末尾都多出这么一条 —— 留着的话，一份「它去查了
      // 什么」的清单里每隔几行就有一行是编号，而事后拿这份清单去比对有没有摸到
      // 不该摸的东西时，这些行只会碍事。
      for (const q of o.action?.queries ?? []) if (!/^ws_call_id=/.test(q)) queries.push(q);
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
export function registerSearchTool(db: Conn, reg: Registry, log?: { warn(msg: string): void }): string {
  reg.register(db, `fn:tool.${SEARCH_TOOL.name}`, SEARCH_TOOL.expectMs, async (arg) => {
    const a = (arg ?? {}) as { args?: { question?: unknown }; agent?: string; instance?: string; unit?: number };
    const question = String(a.args?.question ?? "").trim();
    if (!question) return { error: "question is required - there is nothing to search for" };
    if (!a.agent) return { error: "the kernel did not say which agent is searching, so there is no api to use" };

    // 哪道题**从库里问**，不收调用方传的 —— 收的话，改一个参数就能把闸关掉。
    // 跟 `verify` 那儿是同一条理由、同一个办法。
    const at = whereAmI(db, String(a.instance ?? ""));

    // ── 一轮里能搜几次 ──────────────────────────────────────────────────
    //
    // **这道闸管的是钟，不是格子。** 实测一跑：超时那批把一小时里的一半花在检索上，
    // 而每站的格子额度**一次都没碰到**（用得最多的一站 30 格，上限 35）。所以放宽
    // 格子治不了 —— 只有按次数限才治得了。
    //
    // 一轮 = 一个节点，判死重来是新的额度。超了当场回绝，**不扣数**（本来也没查到）。
    let left: number | undefined;
    if (at) {
      const cap = Number(
        (all(db, `select max_searches from task where id = ?`, [at.task])[0] as { max_searches?: number } | undefined)
          ?.max_searches ?? 0,
      );
      if (cap > 0) {
        const spent = searchesIn(db, at, String(a.agent), String(a.instance ?? ""), Number(a.unit ?? 0));
        left = cap - spent - 1;
        if (spent >= cap) {
          return {
            error:
              `the ${cap === 1 ? "one search" : `${String(cap)} searches`} for this attempt ${cap === 1 ? "is" : "are"} spent. Searching ` +
              `costs time you need for the problem itself - work with what you already found, and reason the rest out.`,
            left: 0,
          };
        }
      }
    }

    // **轨从那个智能体来，不从调用方来。** 模型、端点、思考强度都是它那一行说了算。
    const lane = laneOf(db, SEARCHER);
    const wall = AbortSignal.timeout(SEARCH_WALL_MS);
    const res = await fetch(`${lane.base}/responses`, {
      method: "POST",
      headers: { authorization: `Bearer ${keyOf(lane.keyEnv)}`, "content-type": "application/json" },
      body: JSON.stringify({
        model: lane.model,
        // **先看表里有没有现成的。** 有就接在问题前面 —— 那一端据此把先前搜到的内容
        // 恢复出来，同一片地方不用再走一遍。顺序是硬的：接在**问题前面**，反过来那一端
        // 直接拒（`The reasoning_text in the thinking mode must be passed back to the API`）。
        input: at ? [...deskTalk(db, at.task), { role: "user", content: question }] : question,
        tools: [{ type: "web_search" }],
        // 它固定的那几个参数原样带上 —— 键名照那一端的写法（`reasoning_effort`）。
        ...(lane.knobs.reasoningEffort ? { reasoning_effort: String(lane.knobs.reasoningEffort) } : {}),
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

    // **踩线的整份丢掉，一个字都不回。**
    //
    // 这道闸在模型看见之前 —— 事后审计救不了：答案一旦进了上下文，那道题就已经废了，
    // 作废它只是记下损失。所以连它搜了什么、开了哪些页都不回，那些本身就是线索。
    //
    // `spent` 还是要报的：这次调用真的花了钱，不因为被拦下就当没花过。
    const hit = tripped(got, at ? forbidden(db, at.task) : []);
    if (hit) {
      // **踩线要在日志里喊一声。** 库里留下的只有那句拒绝 —— 那是给模型看的，
      // 它说不出「踩的是哪一条、当时它在往哪儿去」。而这件事是运维要知道的：
      // 一道题反复撞同一条线，说明那道题的题面本身在把它往那边引。
      log?.warn(
        `${at ? at.task : "?"}: a search tripped the publisher's no_search rule on "${hit}" - ` +
          `the whole result was dropped. queries: ${got.queries.join(" | ").slice(0, 300)}`,
      );
      return {
        error:
          "Forbidden access: the publisher of this problem does not allow searching for related content. " +
          "The whole result has been discarded and none of it will be shown to you. Work the problem out " +
          "yourself - looking up what someone else answered is not what is being asked of you.",
        spent: got.spent,
      };
    }

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
    // **校验过了才抄送。** 走到这儿说明：那一端没报错、没踩黑名单、而且真给出了答案。
    // 抄一份回它自己的表，带上这边是哪道题 —— 下一次同一道题里的检索就接得上。
    // 这边照常把工具调用的结果写回去，一个字不改。
    if (at) ccBack(db, at.task, question, got.answer);
    return left === undefined ? got : { ...got, left };
  });

  declareTool(db, { ...SEARCH_TOOL, when: OFFERED_TO });
  return SEARCH_TOOL.name;
}
