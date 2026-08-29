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
import type { Registry } from "../engine/registry.ts";

type Row = Record<string, unknown>;

/**
 * 认得的几家。**地址在这儿，不在库里** —— 加一家 = 这儿加一行，表结构不动。
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
  ["chat", "一问一答。一次调用 = 一个执行单元"],
  ["tools", "这条轨挂得了工具"],
  ["vision", "看得了图"],
  ["duplex", "实时双向。不是一次调用，是一条会话；一个执行单元 = 会话里的一个来回"],
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
  api: { key_env: string; model: string } | null;
  context: { seq: number; role: string; kind: string; body: string }[];
  tools: Row[];
  rules: string[];
}

function key(keyEnv: string): string {
  const v = process.env[keyEnv];
  if (!v) throw new Error(`环境变量 ${keyEnv} 里没有钥匙 —— 见 .env`);
  return v;
}

/**
 * 这一行该不该发给模型。**一处定义，两条轨读同一个判据。**
 *
 * `inject` 是**我们的记账**（这一轮告诉了模型有哪些工具），不是给模型的内容 ——
 * 发过去等于把账本念给它听。`system` 那几条走各自的 instructions 通道，不进消息流。
 *
 * chat 和 duplex 各写一份的话，就是 `deliver.ts` 开头警告的那件事：同一个 bug
 * 有两份副本，而修的时候多半只修一份。
 */
export function sendable(r: { role: string; kind: string }): boolean {
  return r.kind !== "inject" && r.role !== "system";
}

/**
 * 库里那一行怎么变回一条模型消息。
 *
 * `kind = "call"` 那条的 `body` 是个 JSON（文本 + 它请求的调用），`kind = "tool"`
 * 那条是工具的返回 —— 消息表只有一列 `body`，这两样没有自己的列，所以塞在里面。
 * 两头都是我们，约定一致就行；哪天觉得该有一列再补。
 */
function toMsg(r: { role: string; kind: string; body: string }): ModelMessage | null {
  if (r.kind === "call") {
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
  if (!sendable(r)) return null;
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
    ...u.context.filter((r) => r.role === "system" && r.kind !== "inject").map((r) => r.body),
  ]
    .filter(Boolean)
    .join("\n\n");
}

/**
 * 注册每家一个适配器。**这个句柄同时是 `api.handle` 和 `agent.unit`** ——
 * 一次调用就是一个执行单元，两者本来就是一回事，不该分成两层。
 *
 * `seed` 里那几行 `api` 是**数据**，给几个能直接用的；改它不用动代码。
 */
export function registerVendors(db: Conn, reg: Registry, seed: [string, string, string][]): string[] {
  for (const [vendor, v] of Object.entries(VENDORS)) {
    // 这条句柄接得住哪几种 mode。**duplex 不在里面** —— 它是另一条句柄。
    SERVES.set(`fn:api.${vendor}`, new Set(["chat", "tools", "vision"]));
    reg.register(db, `fn:api.${vendor}`, HARD_WALL_MS, async (arg) => {
      const u = arg as unknown as Unit;
      // 内核按周期表的 `api_mode` 已经挑好了这一站走哪条轨，这儿直接用。
      if (!u.api) throw new Error(`fn:api.${vendor} 被调了，但内核没说这一站用哪个模型`);
      const { model, key_env: keyEnv } = u.api;
      const provider = createOpenAICompatible({ name: vendor, baseURL: v.baseURL, apiKey: key(keyEnv) });

      const instructions = instructionsOf(u);
      const messages = u.context.map(toMsg).filter((m): m is ModelMessage => m !== null);

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
        const out = await generateText({
          model: provider(model),
          messages,
          ...(instructions ? { instructions } : {}),
          ...(Object.keys(tools).length ? { tools } : {}),
          maxRetries: RETRIES,
          abortSignal: wall.signal,
        });

        if (out.toolCalls.length > 0) {
          return {
            role: "assistant",
            kind: "call",
            body: JSON.stringify({
              text: out.text,
              calls: out.toolCalls.map((c) => ({ id: c.toolCallId, name: c.toolName, input: c.input })),
            }),
          };
        }
        return { role: "assistant", kind: "prompt", body: out.text };
      } finally {
        clearTimeout(timer);
      }
    });
  }

  for (const [vendor, model, modes] of seed) {
    if (!VENDORS[vendor]) throw new Error(`不认得这家：${vendor}`);
    db.run(
      `insert into api (key_env, model, handle, modes) values (?, ?, ?, ?)
       on conflict(key_env, model) do update set handle = excluded.handle, modes = excluded.modes`,
      [VENDORS[vendor].keyEnv, model, `fn:api.${vendor}`, modes],
    );
  }

  return Object.keys(VENDORS).map((v) => `fn:api.${v}`);
}
