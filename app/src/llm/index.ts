/**
 * 模型适配层。
 *
 * **一次调用刚好是一个执行单元** —— 不是一次 HTTP。内核递过来这个单元的全部
 * 家当（上下文、挂上的工具、在哪儿干），适配器还回来该落库的那一行。中间怎么
 * 拼消息、怎么给工具、各家字段叫什么，都在适配器里面，上面那层不认得。
 *
 * ## 不自己搓
 *
 * HTTP、消息格式、工具格式、重试，用 [AI SDK](https://ai-sdk.dev)（`ai` +
 * `@ai-sdk/openai-compatible`）。纯 JS，没有 native，能打进单文件包 —— 那两道闸
 * 还在。自己搓的那版已经删了。
 *
 * ## 按 mode 分，不是按供应商分
 *
 * `api.modes` 那一列（`chat` / `tools` / `vision` / `duplex`）分的才是**调用形状**：
 *
 * - `chat`：一问一答。**一次 `generateText` = 一个执行单元**，这个文件做的就是它。
 * - `duplex`：实时双向（语音那种）。它不是「一次调用」，是一条会话；一个执行单元
 *   对应会话里的一个来回，会话本身活在那条不结束的生命周期上。在 `./duplex.ts`，
 *   **签名跟这儿一模一样** —— 内核不认得「会话」这回事。
 *
 * 一个智能体可以同时挂两条轨 —— `agent.apis` 是个列表就是为了这个。
 *
 * ## 密钥
 *
 * 库里只有环境变量的**名字**（`api.key_env`），值从 `process.env` 现取。
 * 密钥不进库、不进日志、不进上下文。
 */

import { createOpenAICompatible } from "@ai-sdk/openai-compatible";
import { dynamicTool, generateText, jsonSchema, type ModelMessage } from "ai";

import type { Conn } from "../H2H/db.ts";
import type { Log } from "../engine/loop.ts";
import type { Registry } from "../engine/registry.ts";
import { ROLES as DELIVER_ROLES } from "../msg/deliver.ts";

type Row = Record<string, unknown>;

/**
 * 认得的几家。**这儿是种子，地址的家在 `api.base_url`** —— 注册时把这份默认值写
 * 进那一行，之后以表为准。改地址是改数据，不用动代码，也不用重新编译。
 *
 * `ws` 是这家实时轨的地址。**没有就是这家没有实时轨** —— 不填一个假的，
 * 填了的话 `duplex` 那条句柄会给它注册出来，而真调的时候才发现连不上。
 */
export const VENDORS: Record<string, { baseURL: string; keyEnv: string; ws?: string }> = {
  deepseek: { baseURL: "https://api.deepseek.com/v1", keyEnv: "DEEPSEEK_API_KEY" },
  dashscope: {
    baseURL: "https://dashscope.aliyuncs.com/compatible-mode/v1",
    keyEnv: "DASHSCOPE_API_KEY",
    ws: "wss://dashscope.aliyuncs.com/api-ws/v1/realtime",
  },
};

/**
 * `api.modes` 那一列的**全部合法取值** —— 也就是「调用形状」有哪几种。
 *
 * **取值就是实现认得的这几个**，跟 `msg_kind` 那张表一个套路：值在代码里（实现
 * 认得什么就是什么），`mode` 表是**灌进去给人和 `check` 查的**，不是让谁去填的。
 * 反过来的话，往 `mode` 表里手插一行 `duplx` 就成了「合法」，而实现照样不认 ——
 * 那条轨永远挑不中，系统照常跑，零报错。
 */
export const MODES: [string, string][] = [
  ["chat", "One question, one answer. One call = one execution unit"],
  ["tools", "This lane can carry tools"],
  ["vision", "This lane can see images"],
  ["duplex", "Realtime, both directions. Not a call but a session; one execution unit = one turn in it"],
];

/** 光是名字，比对用。 */
export const MODE_NAMES = new Set(MODES.map(([n]) => n));

/** 把认得的调用形状灌进 `mode` 表。幂等 —— 跟 `seedKinds` 是同一件事。 */
export function seedModes(db: Conn): string[] {
  for (const [name, note] of MODES) {
    db.run(`insert into mode (name, note) values (?, ?) on conflict(name) do update set note = excluded.note`, [
      name,
      note,
    ]);
  }
  return MODES.map(([n]) => n);
}

/**
 * 哪个句柄接得住哪几种 mode。**注册的那一刻填，`checkData` 照它核对。**
 *
 * `api` 的主键是 `(key_env, model)`，一行只有一个 `handle` —— 所以一行的 `modes`
 * 必须全都是那个句柄接得住的。手写一行 `modes = "chat,duplex"` 而 `handle` 是
 * chat 那个，内核会照 `duplex` 挑中它、然后调进 chat 适配器：**不报错，只是那一站
 * 的行为完全不是你想的那样**。这张表就是拿来在检查里把它抓出来的。
 *
 * 外面注册进来的 `http://` 句柄不在这儿 —— 它接得住什么我们不知道，跳过不查。
 */
export const SERVES = new Map<string, Set<string>>();

/**
 * 断连重试几次。
 *
 * **不是保守起见**：老代码注释里写着，DeepSeek 那个端点常瞬时断连
 * （ServerDisconnected / 500），只试一次的话一次抖动就把整趟求解带崩。
 */
export const RETRIES = 6;

/**
 * `api.retry_on` 的默认值 —— 新注册一行时给的那份。**只是默认值，不是规矩**：
 * 库里改成什么就是什么，改它不用动代码。
 *
 * 里头是「对面暂时不行」那一类：限流、网关抖、连接根本没建起来。
 * **4xx 一个都不在**（429 除外）—— 那一类说的是「你发的东西有问题」，
 * 重试改变不了任何事。
 */
export const RETRY_ON = JSON.stringify([408, 409, 425, 429, 500, 502, 503, 504, "network"]);

/** 把那一列读成一个集合。读不动就当空的 —— 空 = 一律不重试，比乱重试安全。 */
function retrySet(raw: string): Set<string> {
  try {
    const v = JSON.parse(raw) as unknown;
    return new Set(Array.isArray(v) ? v.map(String) : []);
  } catch {
    return new Set();
  }
}

/**
 * 这个错在不在名单里。
 *
 * **没有状态码 = 根本没打通**（DNS、连接被掐、读超时）。那属于「对面暂时不行」，
 * 跟「对面收到了，说你发错了」是两回事，所以它在名单里有自己的名字：`network`。
 */
function listed(e: unknown, on: Set<string>): boolean {
  const code = (e as { statusCode?: number } | null)?.statusCode;
  return on.has(code === undefined ? "network" : String(code));
}

/** 整次调用的硬墙。老代码里这条端点挂死过 27~31 分钟，只能从外面掐。 */
export const HARD_WALL_MS = 900_000;

/** 内核递过来的那一份。**两条轨收的是同一份** —— duplex 那边 import 的就是它。 */
export interface Unit {
  agent: Row;
  task: Row;
  cycle: Row;
  chain: string;
  place: string;
  instance: string;
  unit: number;
  /** 内核挑好的那条轨。**适配器不再自己挑** —— 挑的地方只许有一个。 */
  api: { key_env: string; model: string; base_url: string; retry_on: string } | null;
  context: { seq: number; role: string; kind: string; body: string }[];
  /**
   * 哪种 role 出站时去哪儿 —— **从 `msg_role` 表读的，内核给过来。**
   *
   * 以前这份对照只活在这个文件的一个常量里。那意味着「一份库取出来就能打给
   * 模型」这句话不成立：还得同时拿着那一版代码，才知道哪几行该进消息流。
   */
  sentAs: Record<string, string>;
  /**
   * 这一轮的任务视图。**内核每轮现算的事实**，不是上下文里的一条消息 ——
   * 消息跟着单链走，兄弟分支爬不到；视图人人有份。
   */
  view?: {
    task: Row;
    here: { cycle: string; unit: number; chain: string; next?: string[] };
    tried: { node: number; at: string; status: string | null; done: boolean; mine?: boolean }[];
    /**
     * 还剩多少额度。**只有事实** —— 该在哪一站交卷、用哪个工具交，是声明层说的事
     * （流转表上摆着有哪几站，规矩写在 skill / 任务描述里）。
     */
    budget?: {
      units?: { cycle: string; used: number; cap: number; left: number }[];
      secondsLeft?: number;
      submitted?: boolean;
    };
  };
  tools: Row[];
  rules: string[];
}

function key(keyEnv: string): string {
  const v = process.env[keyEnv];
  if (!v) throw new Error(`no key in environment variable ${keyEnv} - see .env`);
  return v;
}

/**
 * 这一行该不该发给模型。**一处定义，两条轨读同一个判据。**
 *
 * 不发的是内核那条记账（这一轮告诉了模型有哪些工具）—— 发过去等于把账本念给它听。
 * `system` 那几条走各自的 instructions 通道，不进消息流。
 *
 * **判据得连 `role` 一起看，不能只看 `kind = 'inject'`。** `inject` 是两样东西共用
 * 的一个值（见 `deliver.ts` 那张推断表）：内核的记账是 `inject` + `role=system`，
 * 系统注入的用户侧消息是 `inject` + `role=user`。而**非真人发的任务，描述那一条正是
 * 后者** —— 一刀切掉 `inject` 的话，`source` 不是 `user` 的任务出站时消息是空的，
 * 模型那边直接回「messages must not be empty」。
 *
 * chat 和 duplex 各写一份的话，就是 `deliver.ts` 开头警告的那件事：同一个 bug
 * 有两份副本，而修的时候多半只修一份。
 */
export function sendable(r: { role: string; kind: string }, sentAs: Record<string, string>): boolean {
  return sentAs[r.role] === "messages";
}

/**
 * 认得的 role。**取值就是 `msg_role` 表里的行** —— 那张表说了每种 role 出站时
 * 去哪儿（`sent_as`），种子在 `msg/deliver.ts`。这个文件里以前有一份同样的对照，
 * 删掉了：两处各存一份的话，改了一处漏了另一处不报错，只表现为某一路悄悄按
 * 错误的身份进了上下文。
 */
/**
 * 库里那一行怎么变回一条模型消息。
 *
 * `kind = "call"` 那条的 `body` 是个 JSON（文本 + 它请求的调用），`kind = "tool"`
 * 那条是工具的返回 —— 消息表只有一列 `body`，这两样没有自己的列，所以塞在里面。
 * 两头都是我们，约定一致就行；哪天觉得该有一列再补。
 */
function toMsg(r: { role: string; kind: string; body: string }, sentAs: Record<string, string>): ModelMessage | null {
  // `graded` 跟 `call` 长得一样、也照样念给模型听 —— 差别只在**谁写的**：
  // `call` 是模型要的，得有人去跑；`graded` 是系统事后记下的一次外部裁决，
  // 结果当场就配好了，没有人该去跑它。分不开的话，跑工具那一站会把判决当成
  // 一次待办的请求又执行一遍 —— 同一个 id 两条结果，整条链路发不出去。
  if (r.kind === "call" || r.kind === "graded") {
    const v = JSON.parse(r.body) as { text?: string; calls?: { id: string; name: string; input: unknown }[] };
    return {
      role: "assistant",
      content: [
        ...(v.text ? [{ type: "text" as const, text: v.text }] : []),
        ...(v.calls ?? []).map((c) => ({
          type: "tool-call" as const,
          toolCallId: c.id,
          toolName: c.name,
          input: c.input,
        })),
      ],
    };
  }
  if (r.kind === "tool") {
    const v = JSON.parse(r.body) as { id?: string; name?: string; value?: unknown };
    return {
      role: "tool",
      content: [
        {
          type: "tool-result" as const,
          toolCallId: v.id ?? "",
          toolName: v.name ?? "",
          output: { type: "json" as const, value: v.value as never },
        },
      ],
    };
  }
  if (!sendable(r, sentAs)) return null;
  if (r.role === "assistant") return { role: "assistant", content: r.body };
  return { role: "user", content: r.body };
}

/**
 * 这一次要告诉模型的那段 `instructions`：工具的用法约定 + 上下文里那几条 system。
 *
 * **chat 每个单元都重发一遍** —— 一个执行单元就是一次调用，它没有「上一轮说过」
 * 这回事。duplex 那边不一样：会话记得住，所以只在**开会话那一刻**发一次。
 * 两边拼法相同，所以在这儿只拼一次。
 *
 * （AI SDK 7 不许 system 混在 messages 里，混进去当场拒 —— 不是悄悄丢，这点很好。）
 */
export function instructionsOf(u: Unit): string {
  return [
    ...u.tools.map((t) => String(t.prompt ?? "")),
    // 走 instructions 那一档的都收进来 —— `system` 和 `skill`。
    // 内核那条记账（`kind: "inject"`）除外：那是给我们看的账本，不念给模型听。
    ...u.context.filter((r) => u.sentAs[r.role] === "instructions" && r.kind !== "inject").map((r) => r.body),
  ]
    .filter(Boolean)
    .join("\n\n");
}

/**
 * 把内核算好的那份任务视图念成一段话。**内核只给事实，这儿才拼词。**
 *
 * ## 它进消息流，不进 instructions
 *
 * 一开始放在 `instructions` 里，错了：**根级兄弟的消息流是空的**（它没有祖先，
 * 自己那站还没说过话），于是 `messages: []`，模型那边直接拒
 * （`Invalid prompt: messages must not be empty`）。视图有内容也救不了 ——
 * instructions 不是消息。
 *
 * 而且从意思上它本来就该是消息：老仓库那句是「你所在**单链的完整上下文**已默认
 * 接入」——**上下文**，不是系统交代。它是这一轮摆在模型面前的东西（题目、你在树的
 * 哪儿、别人试过哪几条），跟「工具怎么用」那种交代不是一回事。
 *
 * 树那一段**只在真分叉了才写**：单链的机制（一条道走到黑）本来就是直接继承上下文，
 * 给它一张只有一个节点的树，除了占地方没有别的作用。
 */
export function viewOf(u: Unit): string {
  const v = u.view;
  if (!v) return "";
  const t = v.task;
  const lines = [
    "## The task",
    `${String(t.description ?? "")}`,
    "",
    `id ${String(t.id)} | domain ${String(t.domain) || "(none)"} | at ${String(t.place)}${
      t.workdir ? `:${String(t.workdir)}` : ""
    }${t.objective ? " | this task is graded by a verification function" : ""}`,
  ];

  // **你在哪一站。** 流转表上的事实：站名，以及这一站之后还能去哪几站。
  // 「没有下一站」是这里唯一多说的一句 —— 那也是事实（`next` 是空的），
  // 而它决定了这一站说的话有没有下一站接得住。
  const next = v.here.next;
  lines.push(
    "",
    "## Where you are",
    `station ${v.here.cycle}#${v.here.unit}` +
      (next === undefined
        ? ""
        : next.length === 0
          ? " - this is the last station: nothing runs after it, so anything you ask for here will not happen"
          : ` - after this comes one of: ${next.join(", ")}`),
  );

  // 额度只报事实。**该在哪一站交卷、用哪个工具交，是声明层说的事** ——
  // 流转表上摆着有哪几站，规矩写在 skill / 任务描述里。内核不在这儿塞口径。
  const b = v.budget;
  if (b) {
    const units = (b.units ?? []).map((x) => `${x.cycle} ${x.used}/${x.cap}`).join(", ");
    lines.push(
      "",
      "## Budget",
      `units used: ${units || "(none)"}` +
        (b.secondsLeft === undefined ? "" : ` | ${b.secondsLeft}s left`) +
        (b.submitted === undefined ? "" : ` | submitted: ${b.submitted ? "yes" : "not yet"}`),
    );
  }

  // 只有一个节点 = 还没分叉，那就是单链，树这一段没有意义。
  if (v.tried.length > 1) {
    lines.push(
      "",
      "## This tree",
      // 说的是**节点**：一个节点是一次完整的尝试，好几个执行单元拼起来。
      // `node_load` 认的也是节点号 —— 两处得说同一种话，不然它会拿行号去问。
      `You are at ${v.here.chain}. Attempts so far:`,
      ...v.tried.map(
        (n) =>
          `- node ${n.node}${n.mine ? " (this one)" : ""}: ${n.at}` +
          (n.status ? ` - **${n.status}**` : n.done ? " - finished" : " - still running"),
      ),
      "",
      "The ones marked dead were attempts that did not pass. Do not walk them again. " +
        "What they said is not shown by default - fetch one with node_load, by its node number.",
    );
  }
  return lines.join("\n");
}

/**
 * 拼这一轮发出去的消息：**任务视图打头，然后是上下文里该发的那些。**
 *
 * 视图排在最前是因为它是「这道题是什么」——上下文是接着它往下说的。
 * 而且它保证消息流不空：根级兄弟没有祖先，不给它这一条就是 `messages: []`，
 * 模型那边直接拒。
 *
 * 两条轨共用（duplex 那边 import 的就是它）—— 一份判据不许有两处实现。
 */
/**
 * 这一次发过去的消息流：**历史在前，这一轮的问话在最后。**
 *
 * 视图（任务是什么、走到哪儿了、还剩多少预算、这棵树长什么样）是**每个执行
 * 单元现生成一份**的，它就是这一轮的问话。放在历史前面有两个坏处：
 *
 * 1. 最新的信息落在最旧的位置，后面几十条历史把它埋掉
 * 2. **整个请求会以助手消息结尾** —— 上一站要是说了句纯文本（没调工具），
 *    那条就是最后一条。有的网关把这种形状当成「续写前缀」，于是要求把
 *    `reasoning_content` 一起带回来，不带就直接拒收：
 *    `The reasoning_content in the thinking mode must be passed back to the API.`
 *    一道题就这么整个卡死在交卷站上（cmt-3，submit#14）。
 *
 * 上一站调了工具的话，最后一条是 tool 结果，形状是对的 —— 所以这个毛病只在
 * 「上一站说了句话就走」的时候犯，看着像随机。
 */
export function messagesOf(u: Unit): ModelMessage[] {
  const view = viewOf(u);
  return [
    ...u.context.map((r) => toMsg(r, u.sentAs)).filter((m): m is ModelMessage => m !== null),
    ...(view ? [{ role: "user" as const, content: view }] : []),
  ];
}

/**
 * 注册每家一个适配器。**这个句柄同时是 `api.handle` 和 `agent.unit`** ——
 * 一次调用就是一个执行单元，两者本来就是一回事，不该分成两层。
 *
 * `seed` 里那几行 `api` 是**数据**，给几个能直接用的；改它不用动代码。
 */
export function registerVendors(
  db: Conn,
  reg: Registry,
  log: Log,
  seed: [string, string, string][],
  knobs: {
    maxTokens: number;
    retryTimes: number;
    continueTimes: number;
    reasoningEffort: string;
    temperature: number;
    seed: number;
  },
): string[] {
  for (const [vendor, v] of Object.entries(VENDORS)) {
    // 这条句柄接得住哪几种 mode。**duplex 不在里面** —— 它是另一条句柄。
    SERVES.set(`fn:api.${vendor}`, new Set(["chat", "tools", "vision"]));
    reg.register(db, `fn:api.${vendor}`, HARD_WALL_MS, async (arg) => {
      const u = arg as unknown as Unit;
      // 内核按周期表的 `api_mode` 已经挑好了这一站走哪条轨，这儿直接用。
      if (!u.api) throw new Error(`fn:api.${vendor} was called, but the kernel did not say which model this station uses`);
      const { model, key_env: keyEnv } = u.api;
      const retryOn = retrySet(u.api.retry_on);
      // **地址从表里来。** 以前它写死在 `VENDORS` 里，后来我又加了一条环境变量去顶
      // 它 —— 那条更糟：同一份库，换个环境变量行为就不一样，而库里、代码里都看不
      // 出来。库要能当一份跟内核无关的快照用，这种东西一个都不能有。
      //
      // 进了表就顺带解决了另一件事：假端点不用再靠环境变量接进来，改一行数据就行。
      const provider = createOpenAICompatible({ name: vendor, baseURL: u.api.base_url, apiKey: key(keyEnv) });

      const instructions = instructionsOf(u);
      const messages = messagesOf(u);

      // 工具**只声明不执行**：没有 execute，SDK 就只把调用请求还回来。
      // 真去跑它是下一个执行单元的事 —— 在这儿跑掉的话，那一步就从库里消失了。
      const tools = Object.fromEntries(
        u.tools.map((t) => [
          String(t.name),
          dynamicTool({
            description: String(t.does ?? ""),
            inputSchema: jsonSchema(JSON.parse(String(t.params)) as never),
          }),
        ]),
      );

      const wall = new AbortController();
      const timer = setTimeout(() => wall.abort(), HARD_WALL_MS);
      try {
        // ── 一次调用 = 一个执行单元；但**一个执行单元不等于一次 HTTP** ─────────
        //
        // 没说完就接着说，最多续 `continueTimes` 次。
        //
        // 为什么要这一档：思考型模型的输出预算是**思考和可见文本共用**的。额度一刀切
        // 的话，它把预算全花在思考上，最后可见文本是空的 —— 实测 19 条答复里 12 条
        // 全空，三道题一个字都没答，而成绩单上只表现为「答错」。
        //
        // **「没答」和「没答完」是两回事**：前者该判错，后者该让它说完。判据是
        // `finishReason === "length"` —— 那是模型自己说的「我被截断了」，不是我们猜的。
        //
        // 续的时候把已经说出来的那半截当成 assistant 的话接在最后，它会顺着往下写。
        /**
         * 打一发，炸了就重打，每次多等 5 秒。
         *
         * SDK 自己那层 `maxRetries` 管的是 HTTP（连不上、5xx、429），管不了
         * **「200 回来了但读不懂」**（`Failed to process successful response`）——
         * 那是它把返回体映射成自己的结构时失败，重试逻辑够不着。
         *
         * 而炸在这儿之后内核按设计不重试（醒了就是原地热循环），那一站只能挂着等
         * `expect_ms` —— 一次偶发抖动烧掉 15 分钟。所以这一层得自己扛。
         *
         * **递增等待**：抖动多半自己会过去，等一等比立刻再打有用。
         */
        const ask = async (msgs: ModelMessage[]) => {
          let boom: unknown;
          for (let n = 0; n <= knobs.retryTimes; n++) {
            if (n > 0) await new Promise((r) => setTimeout(r, 5000 * n));
            try {
              return await generateText({
                model: provider(model),
                messages: msgs,
                ...(instructions ? { instructions } : {}),
                ...(Object.keys(tools).length ? { tools } : {}),
                maxOutputTokens: knobs.maxTokens,
                // A benchmark run has to be reproducible: without a fixed temperature
                // there is no telling how much of a score change came from an edit and
                // how much from sampling noise.
                temperature: knobs.temperature,
                seed: knobs.seed,
                // 思考强度**原样塞进那家的请求体**（openai-compatible 会把不认得的键
                // 直接带过去）。不认得这个参数的模型会忽略它 —— 我们不替它翻译，
                // 也不按模型名去猜该发哪个字段名，猜错了不报错，只是那一档没生效。
                providerOptions: { [vendor]: { reasoning_effort: knobs.reasoningEffort } },
                maxRetries: RETRIES,
                abortSignal: wall.signal,
              });
            } catch (e) {
              // 整次调用的硬墙到了就别再重打了 —— 那不是抖动，是这一站超时了。
              if (wall.signal.aborted) throw e;
              // **白名单说了才重打。** 不在名单里的原样抛出去。400 说的是「这个请求
              // 本身不合法」—— 再打一百次还是同一个 400，重试只是把时间烧掉，然后
              // 以完全一样的方式失败。实测烧掉的是 30 秒（0+5+10+15 的退避）。
              if (!listed(e, retryOn)) throw e;
              boom = e;
            }
          }
          throw boom;
        };

        let text = "";
        let thought = "";
        let calls: { id: string; name: string; input: unknown }[] = [];
        let this_broke = "";
        for (let round = 0; ; round++) {
          // 已经说出来的那半截接在末尾 —— 让它续，而不是重来一遍。
          //
          // **思考那半截也得带回去。** 思考型模型把上一轮的思考当成这一轮的前提，
          // 只回传可见文本的话，有的厂商直接拒收：
          //   The `reasoning_content` in the thinking mode must be passed back to the API.
          // 实测一整道题就这么卡死在续写的第一轮上。
          const so_far: ModelMessage[] = text
            ? [
                ...messages,
                {
                  role: "assistant",
                  content: [
                    ...(thought ? [{ type: "reasoning" as const, text: thought }] : []),
                    { type: "text" as const, text },
                  ],
                },
              ]
            : messages;
          // **续写这一轮炸了，不该把整道题带走。** 已经说出半截了，那半截就是答案的
          // 一部分；这儿抛出去的话，这一站挂到 expect_ms，一道题直接没了。截断着交
          // 比什么都没有强 —— 第一轮除外，那时候手上一个字都没有。
          let out;
          try {
            out = await ask(so_far);
          } catch (e) {
            if (round === 0) throw e;
            this_broke = e instanceof Error ? e.message : String(e);
            break;
          }
          text += out.text;
          // `reasoningText` 不是每家都填得上 —— openai-compatible 认不认得那家的
          // `reasoning_content`，取决于版本。两处都捞一下，捞不到就当没有。
          thought +=
            out.reasoningText ||
            (out.reasoning ?? []).map((r) => ("text" in r ? String(r.text) : "")).join("");
          calls = out.toolCalls.map((c) => ({ id: c.toolCallId, name: c.toolName, input: c.input }));

          // 要工具了就停：那是一次完整的表态，续不下去也不该续。
          if (calls.length > 0) break;
          // 它自己说完了，或者续满了。
          if (out.finishReason !== "length" || round >= knobs.continueTimes) break;
        }

        if (this_broke) log.warn(`${model} could not continue; handing back what it had said. ${this_broke}`);
        // 思考**不落库**：它只在这一次调用里有用（续写要拿它当前提）。跨执行单元
        // 重放时，有的网关反过来不认得带思考的助手消息 —— 而重放这条路一直是好的。
        if (calls.length > 0) {
          return { role: "assistant", kind: "call", body: JSON.stringify({ text, calls }) };
        }
        return { role: "assistant", kind: "prompt", body: text };
      } finally {
        clearTimeout(timer);
      }
    });
  }

  for (const [vendor, model, modes] of seed) {
    if (!VENDORS[vendor]) throw new Error(`unknown vendor: ${vendor}`);
    db.run(
      `insert into api (key_env, model, handle, modes, base_url, retry_on) values (?, ?, ?, ?, ?, ?)
       on conflict(key_env, model) do update set handle = excluded.handle, modes = excluded.modes`,
      [VENDORS[vendor].keyEnv, model, `fn:api.${vendor}`, modes, VENDORS[vendor].baseURL, RETRY_ON],
    );
  }

  return Object.keys(VENDORS).map((v) => `fn:api.${v}`);
}
