/**
 * 实时轨（duplex）—— 一条 WebSocket 会话。
 *
 * ## 跟 chat 那条轨差在哪
 *
 * chat 是「一次调用 = 一个执行单元」，调完连接就没了。duplex **不是一次调用，
 * 是一条会话**：一个执行单元对应会话里的**一个来回**，会话本身跨着好几个单元活着。
 *
 * 但**句柄签名跟 chat 一模一样** —— 内核递过来一个单元，还回去该落库的那一行。
 * 内核不认得「会话」这回事，也不该认得：认得了，`cycle.api_mode` 那一列就白设了。
 *
 * ## 会话是连接，不是状态
 *
 * 会话活在进程内的池子里，**不进库** —— 跟 `workplace.usable` 是登记不是探活同一个
 * 道理。写回去的话，崩了重启读到的那一列就是过期的谎话。
 *
 * 库里丢不了的是**每一个来回**：它讲了什么、谁说了什么、请求了哪个工具，全落
 * `agent_<name>_msg`。所以崩了重启，会话没了，账还在 —— 「库 = 快照」那条定理不破。
 *
 * ## DashScope 用的是 beta 事件名
 *
 * 这是这一块**最要紧的一件事**。Qwen 的实时端点走 OpenAI 的 *beta* 事件 schema，
 * 而现在通行的名字是 *GA* 的那套。名字对不上的后果不是报错，是**什么都收不到**：
 * 连接建着、事件在流、每一条都没人认领，于是一个来回永远等不到头。
 *
 * 所以入站事件名先过 {@link BETA2GA} 映射回 GA，再分派。**只映射入站** ——
 * 出站我们发的仍是 beta 名，那边只认这个。
 *
 * ## 收流那条路绝不许死
 *
 * 老代码在这儿踩了三次，每一次的表现都是「静默」，没有一次是报错：
 *
 * 1. beta 的 `response.done` 不带 usage，读 `usage.input_tokens` 当场 NoneType 崩 →
 *    **接收协程整个死掉** → 从那一刻起全静默
 * 2. 事件解不了被跳过 → 当前响应态不清 → 「还在讲」永远为真 → 讲一段就哑
 * 3. 参会者转写那条事件是 beta schema，解不了被跳过 → 拿不到「用户说了什么」
 *
 * 踩出来的通则就一条：**一条事件解不了，只丢这一条，绝不带倒整条连接**；而且
 * 要把丢掉的**数出来**。静默的表现是「什么都没发生」，不数的话，事件名哪天漂了
 * 也没人看得出来 —— 只会觉得「这模型今天不说话」。
 *
 * ## 这一轮到哪儿为止
 *
 * **只做协议层：文本进，文本 + 转写出。**
 *
 * 采音频、放音频是设备的事，而任何一个音频 IO 库都是 native 依赖 —— 那道闸不许过
 * （零 native、能交叉编译）。所以音频腿不在这一轮里，等它落地时接在这一层上面。
 *
 * 出站音频**收到就丢，只计数不落库**：音频是字节流，落进 `agent_<name>_msg` 会把
 * 快照撑成几百 MB，而且没有一个人读得懂那一列。**转写才是那条轨迹。**
 */

import type { Conn } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { deliver } from "../msg/deliver.ts";
import { instructionsOf, sendable, SERVES, VENDORS, type Unit } from "./index.ts";

/**
 * 入站事件名：beta → GA。**照抄老代码那张表，一条不改。**
 *
 * 少一条的后果是那一类事件永远没人认领 —— 不报错，只是收不到。多一条不会怎样，
 * 所以宁可全列着。
 */
export const BETA2GA: Record<string, string> = {
  "response.audio.delta": "response.output_audio.delta",
  "response.audio_transcript.delta": "response.output_audio_transcript.delta",
  "response.text.delta": "response.output_text.delta",
  "conversation.item.created": "conversation.item.added",
  "response.audio.done": "response.output_audio.done",
  "response.audio_transcript.done": "response.output_audio_transcript.done",
  "response.text.done": "response.output_text.done",
};

/**
 * 一个来回的硬墙。
 *
 * chat 那条是 15 分钟，因为它一次要出一整篇。duplex 一个来回只是「讲一小段」，
 * 拖到两分钟就说明那边已经不对了 —— 不设墙的话，会话挂在那儿而这一行永远
 * 不出结果，只能等 `expect_ms` 判死，而那时候日志上什么线索都没有。
 */
export const TURN_MS = 120_000;

/** 连上 + 等到 `session.created` 的上限。连不上要当场说，不能挂着。 */
export const OPEN_MS = 20_000;

/**
 * 会话闲多久回收。
 *
 * 会话跟着 `instance` 活，可 instance 干完了不会有人来说一声。**不回收就是泄漏**：
 * 一条挂着的 WebSocket 会一直占着那边的额度。回收是**算**出来的（上次用到现在多久），
 * 不另起定时器 —— 每次开会话的时候顺手扫一遍就够了。
 */
export const IDLE_MS = 300_000;

/** 这条句柄接得住的 mode。**只有 duplex** —— 它不会一问一答。 */
const SERVED = new Set(["duplex"]);

/**
 * 只要文本。
 *
 * 音频腿还没接（见文件头），要了也是收到就丢 —— 而那边的音频 token 照样算钱。
 * 等设备层落地，改这一处，别在调用点各写各的。
 */
const MODALITIES = ["text"];

/**
 * 一个来回攒下来的东西。
 *
 * `errors` 单独攒着，不是收到就炸：那边的 `error` 不一定致命（提交了个空音频缓冲
 * 也是一条 error）。**有产出就当没事发生，没产出才拿它当死因** —— 这样既不会因为
 * 一条无关的 error 把整个执行单元判掉，也不会在真出事时只留下一句「什么都没回来」。
 */
interface Turn {
  text: string[];
  calls: { id: string; name: string; input: unknown }[];
  /** 丢掉的音频块数。**只数不存**，见文件头。 */
  audio: number;
  errors: string[];
  settle(e: Error | null): void;
}

/** 一个来回走完，还回来的东西。 */
export interface TurnOut {
  /** 它讲的话。文本增量 + 语音转写增量，拼在一起。 */
  text: string;
  calls: { id: string; name: string; input: unknown }[];
  /** 丢掉的音频块数。 */
  audio: number;
  /** 那边报过的错。**有产出就不算死因**，只是记着。 */
  errors: string[];
  /** 这个来回里**别人说的话**（转写）。由句柄落库，会话自己不碰库。 */
  heard: string[];
  /** 这条会话累计跳过的事件数。**事件名漂了就是从这个数字开始涨的。** */
  skipped: number;
}

/** 会话要往里发的一条。`type` 用的是那边的 item 形状，不是我们的消息表。 */
type Item = Record<string, unknown>;

/**
 * Bun 的 `WebSocket` 第二个参数收选项（浏览器那个收的是 subprotocol）。
 *
 * **实时轨的钥匙只能走请求头** —— 没有这条就连不上，所以这个 cast 是必须的，
 * 不是图省事。写成一处，别在调用点各 cast 各的。
 */
type WithHeaders = new (url: string, opts: { headers: Record<string, string> }) => WebSocket;

/** 一条会话。**认协议，不认库** —— 落库是句柄那一层的事。 */
export class Session {
  readonly model: string;
  /** 上次用到的时刻。闲置回收照它算，不另起定时器。 */
  used = Date.now();
  /** 解不了、没人认领的事件条数。**静默漂移的唯一线索**，所以一定要往外报。 */
  skipped = 0;
  /** 见过的入站事件名。事件名哪天变了，这一串就是证据。 */
  readonly seen = new Set<string>();

  #ws: WebSocket;
  #turn: Turn | null = null;
  #dead: Error | null = null;
  /** 那边转写出来的、**别人说的话**。每个来回结束时由句柄取走落库。 */
  #heard: string[] = [];
  /** item_id → 这条工具调用是谁。有的实现只在 item 那条给名字，得先记着。 */
  #fn = new Map<string, { name: string; call: string }>();
  #ready: Promise<void>;

  constructor(url: string, key: string, model: string) {
    this.model = model;
    const Ws = WebSocket as unknown as WithHeaders;
    this.#ws = new Ws(`${url}?model=${encodeURIComponent(model)}`, {
      headers: { Authorization: `Bearer ${key}` },
    });

    this.#ready = new Promise<void>((ok, fail) => {
      const wall = setTimeout(() => fail(new Error(`开实时会话超过 ${OPEN_MS}ms 还没等到 session.created`)), OPEN_MS);
      this.#opened = () => {
        clearTimeout(wall);
        ok();
      };
      this.#ws.addEventListener("error", () => fail(this.#dead ?? new Error("实时会话连不上")));
      this.#ws.addEventListener("close", () => fail(this.#dead ?? new Error("实时会话还没开起来就被关了")));
    });

    this.#ws.addEventListener("message", (e: MessageEvent) => this.#take(String(e.data)));
    // 连接断了 = 在途的那个来回永远等不到 response.done。**当场把它结掉** ——
    // 不结的话它挂到 TURN_MS 才超时，而日志上看不出是断了还是那边不说话。
    this.#ws.addEventListener("close", () => this.#die(new Error("实时会话断了")));
    this.#ws.addEventListener("error", () => this.#die(new Error("实时会话出错断了")));
  }

  #opened: () => void = () => {};

  /** 会话开好了没有。开不起来在这儿炸，不会拖到发第一条。 */
  ready(): Promise<void> {
    return this.#ready;
  }

  get dead(): Error | null {
    return this.#dead;
  }

  #die(e: Error): void {
    if (!this.#dead) this.#dead = e;
    this.#turn?.settle(e);
  }

  #send(o: Record<string, unknown>): void {
    if (this.#dead) throw this.#dead;
    this.#ws.send(JSON.stringify(o));
  }

  /**
   * 收一条。**这个函数不许抛。**
   *
   * 老代码在这一层死过：一条事件的 payload 解不了，异常顺着冒上去，把接收协程
   * 整个带走 —— 之后连接还开着、事件还在流，但再没有一个字被处理。**表现是静默，
   * 不是报错**，所以查起来只能靠猜。
   *
   * 这儿的规矩：分派**只看 `type`**，payload 怎么坏都只坏这一条；而且哪怕分派炸了，
   * `response.done` 该收的尾照收 —— 收不了尾的话，这个来回就永远等不到头。
   */
  #take(raw: string): void {
    this.used = Date.now();
    let d: Record<string, unknown>;
    try {
      d = JSON.parse(raw) as Record<string, unknown>;
    } catch {
      this.skipped++;
      return;
    }
    const beta = String(d.type ?? "");
    this.seen.add(beta);
    // **只映射入站。** 出站发的仍是 beta 名 —— 那边只认那套。
    const type = BETA2GA[beta] ?? beta;
    try {
      this.#dispatch(type, d);
    } catch (e) {
      this.skipped++;
      this.#turn?.errors.push(`${beta} 这条处理不了：${e instanceof Error ? e.message : String(e)}`);
      if (type === "response.done") this.#turn?.settle(null);
    }
  }

  /** 认得的事件。**名字是 GA 的**，入站已经映射过了。 */
  #dispatch(type: string, d: Record<string, unknown>): void {
    switch (type) {
      case "session.created":
        this.#opened();
        return;

      // 收到了、没事干。**但必须列在这儿** —— 掉进 default 的话它会把 `skipped`
      // 顶高，而那个数字是事件名漂移的唯一线索：被正常事件污染了就等于没有。
      case "session.updated":
      case "response.created":
      case "response.output_item.added":
      case "response.output_item.done":
      case "response.content_part.added":
      case "response.content_part.done":
      case "response.output_text.done":
      case "response.output_audio.done":
      case "response.output_audio_transcript.done":
      case "conversation.item.done":
      case "input_audio_buffer.speech_started":
      case "input_audio_buffer.speech_stopped":
      case "input_audio_buffer.committed":
      case "rate_limits.updated":
        return;

      // 它讲的话。文本增量和语音转写增量是**同一条轨迹的两种来源**，都往一处攒 ——
      // 只收其中一种的话，换个 modalities 就什么都攒不到了。
      case "response.output_text.delta":
      case "response.output_audio_transcript.delta":
        this.#turn?.text.push(String(d.delta ?? ""));
        return;

      // 音频**收到就丢，只计数**。见文件头：字节流落库会把快照撑爆，转写才是轨迹。
      case "response.output_audio.delta":
        if (this.#turn) this.#turn.audio++;
        return;

      case "conversation.item.added": {
        const item = (d.item ?? {}) as Record<string, unknown>;
        if (item.type === "function_call" && item.id) {
          this.#fn.set(String(item.id), {
            name: String(item.name ?? ""),
            call: String(item.call_id ?? item.id),
          });
        }
        return;
      }

      case "response.function_call_arguments.done": {
        // 工具名不一定在这条事件里 —— 有的实现只在 item 那条给。两边都取一次；
        // 都没有就炸，别拿空名字往下走：那会变成「调了个没有的工具」。
        const itemId = String(d.item_id ?? "");
        const known = this.#fn.get(itemId);
        const name = String(d.name ?? known?.name ?? "");
        const call = String(d.call_id ?? known?.call ?? itemId);
        if (!name) throw new Error(`工具调用没说是哪个工具（item_id=${itemId}）`);
        this.#turn?.calls.push({ id: call, name, input: JSON.parse(String(d.arguments ?? "{}")) });
        return;
      }

      // 【老代码踩过】这条是 beta schema，通用解析器解不了会**整条跳过** ——
      // 于是「别人说了什么」永远拿不到，而系统一声不吭。所以手动接住。
      case "conversation.item.input_audio_transcription.completed": {
        const said = String(d.transcript ?? "").trim();
        if (said) this.#heard.push(said);
        return;
      }

      // 一个来回到头了。**只认这条**。
      // 【老代码踩过】beta 的这条不带 usage，读统计字段当场崩 —— 所以这儿一个
      // payload 字段都不读，收尾就是收尾。
      case "response.done":
        this.#turn?.settle(null);
        return;

      case "error":
        this.#turn?.errors.push(errText(d));
        return;

      default:
        // 认不得的不算错（那边随时会加新事件），但要数进去 —— 事件名漂了
        // 就是从这个数字开始涨的。
        this.skipped++;
    }
  }

  /**
   * 开场那一次：把 instructions 和工具告诉它。
   *
   * **只发一次** —— 会话记得住，这正是它跟 chat 的分界：chat 每个单元都要把
   * instructions 重发一遍，因为那边根本没有「上一轮」。
   */
  async update(instructions: string, tools: Item[]): Promise<void> {
    await this.ready();
    this.#send({
      type: "session.update",
      session: {
        modalities: MODALITIES,
        ...(instructions ? { instructions } : {}),
        ...(tools.length ? { tools, tool_choice: "auto" } : {}),
      },
    });
  }

  /**
   * 走一个来回：把这几条发进去，等它讲完。
   *
   * **一条会话是一根线，来回只能一个接一个。** 树开了兄弟之后，同一个 instance
   * 底下会有好几个执行单元同时是「该动」的那一档，内核会并排推它们 —— 直接并发
   * 发进同一条会话的话，两个来回的事件会混在一起，而**混了不报错**，只是两边
   * 都拿到对方的半句话。所以在这儿排队。
   */
  turn(items: Item[]): Promise<TurnOut> {
    const go = () => this.#one(items);
    const next = this.#queue.then(go, go);
    // 排队本身不该因为前一个来回失败就断掉 —— 那会让后面的单元全部连坐。
    this.#queue = next.then(
      () => {},
      () => {},
    );
    return next;
  }

  #queue: Promise<unknown> = Promise.resolve();

  async #one(items: Item[]): Promise<TurnOut> {
    await this.ready();
    if (this.#dead) throw this.#dead;

    const t: Turn = { text: [], calls: [], audio: 0, errors: [], settle: () => {} };
    const wait = new Promise<void>((ok, fail) => {
      // 硬墙。**不设的话这一行就挂在那儿**，只能等内核按 expect_ms 判死，
      // 而那时候日志上一条线索都没有 —— 连那边报过什么错都丢了。
      const wall = setTimeout(() => {
        const why = t.errors.length ? `；那边报过：${t.errors.join("；")}` : "";
        fail(new Error(`一个来回超过 ${TURN_MS}ms 还没等到 response.done${why}`));
      }, TURN_MS);
      let settled = false;
      t.settle = (e) => {
        if (settled) return; // response.done 来两条不算数
        settled = true;
        clearTimeout(wall);
        if (e) fail(e);
        else ok();
      };
    });

    this.#turn = t; // 先挂上再发，不然头几条事件没人接
    try {
      for (const it of items) this.#send({ type: "conversation.item.create", item: it });
      this.#send({ type: "response.create" });
      await wait;
    } finally {
      this.#turn = null;
    }

    // 转写取走就清空 —— 留着的话下一个来回会把同一句话再落一遍库。
    return {
      text: t.text.join(""),
      calls: t.calls,
      audio: t.audio,
      errors: t.errors,
      heard: this.#heard.splice(0),
      skipped: this.skipped,
    };
  }

  close(): void {
    this.#dead ??= new Error("会话已经关了");
    try {
      this.#ws.close();
    } catch {
      // 关一个已经断了的连接不算事
    }
  }
}

function errText(d: Record<string, unknown>): string {
  const e = d.error;
  if (e !== null && typeof e === "object" && "message" in e) return String((e as { message: unknown }).message);
  return JSON.stringify(e ?? d);
}

/**
 * 库里那一行 → 会话里的一条。取不出来的（不该发的）回 `null`。
 *
 * 跟 chat 那边的 `toMsg` 是同一件事的两种形状，**共用同一个 `sendable` 判据** ——
 * 各写一份的话，哪天改了「什么不该发给模型」就只会改到一边。
 */
function itemOf(r: { role: string; kind: string; body: string }): Item | null {
  if (!sendable(r)) return null;

  // 它自己上一轮请求工具的那一条。**会话记得住自己说过什么**，重发等于让它把
  // 自己的话又听一遍。chat 那边必须重发，因为那边压根没有「上一轮」——
  // 这是两条轨最实在的一处分别。
  if (r.kind === "call") return null;

  if (r.kind === "tool") {
    const v = JSON.parse(r.body) as { id?: string; value?: unknown };
    return { type: "function_call_output", call_id: v.id ?? "", output: JSON.stringify(v.value ?? null) };
  }
  if (r.role === "assistant") {
    return { type: "message", role: "assistant", content: [{ type: "text", text: r.body }] };
  }
  return { type: "message", role: "user", content: [{ type: "input_text", text: r.body }] };
}

/** `tool` 表那一行 → 会话认得的工具声明。**只声明不执行**，跟 chat 那边一样。 */
function toolOf(t: Record<string, unknown>): Item {
  return {
    type: "function",
    name: String(t.name),
    description: String(t.does ?? ""),
    parameters: JSON.parse(String(t.params)) as unknown,
  };
}

/**
 * 开过的会话留着复用 —— 跟 `Places` 一个形状，也是一个道理：每个执行单元重开一条
 * 会话的话，duplex 就退化成 chat 了，「会话记得住」这件事整个没了。
 *
 * **键是 `(vendor, instance)`**：会话跟着智能体实例走。同一个 instance 的第二个
 * 执行单元接着上一条讲，这才是「一条会话，好几个来回」。
 */
export class Sessions {
  #open = new Map<string, Promise<Session>>();

  /** 池子里现在开着几条 —— 给日志和检查看的。 */
  get size(): number {
    return this.#open.size;
  }

  get(vendor: string, instance: string, make: () => Promise<Session>): Promise<Session> {
    this.#reap();
    const k = `${vendor} ${instance}`;
    let s = this.#open.get(k);
    if (!s) {
      s = make();
      this.#open.set(k, s);
      // 开不起来就把这次的坑清掉，下次还能重试 —— 留着的话这个 instance 就永久废了
      s.catch(() => this.#open.delete(k));
    }
    return s;
  }

  /**
   * 闲太久的关掉。
   *
   * instance 干完了没有人会来说一声，**不回收就是泄漏**：一条挂着的 WebSocket
   * 一直占着那边的额度。回收是算出来的（上次用到现在多久），不另起定时器 ——
   * 定时器是内存里的状态，而这件事每次开会话时顺手扫一遍就够了。
   *
   * 断掉的那些一并清掉：留着的话下一个单元会拿到一条死会话，然后当场失败。
   */
  #reap(): void {
    const now = Date.now();
    for (const [k, p] of this.#open) {
      void p
        .then((s) => {
          if (s.dead !== null || now - s.used > IDLE_MS) {
            s.close();
            this.#open.delete(k);
          }
        })
        .catch(() => this.#open.delete(k));
    }
  }

  closeAll(): void {
    for (const p of this.#open.values()) void p.then((s) => s.close()).catch(() => {});
    this.#open.clear();
  }
}

/**
 * 注册实时轨。**只给有 `ws` 地址的那几家** —— 没有实时轨的家注册出一条来，
 * 库里就多了一条永远调不通的句柄，而错要等到真跑到那一站才冒出来。
 *
 * `seed` 里那几行 `api` 是**数据**，`modes` 一律是 `duplex`：这条句柄只接得住它，
 * 写成参数只会让人有机会写错。
 */
export function registerDuplex(db: Conn, reg: Registry, pool: Sessions, seed: [string, string][]): string[] {
  const names: string[] = [];

  for (const [vendor, v] of Object.entries(VENDORS)) {
    if (!v.ws) continue; // 这家没有实时轨
    const ws = v.ws;
    const name = `fn:api.${vendor}.duplex`;
    SERVES.set(name, SERVED);
    names.push(name);

    // 时限是**一个来回**的时限，不是一条会话的。会话能活很久，一个来回不该。
    reg.register(db, name, TURN_MS, async (arg) => {
      const u = arg as unknown as Unit;
      if (!u.api) throw new Error(`${name} 被调了，但内核没说这一站用哪个模型`);
      const keyEnv = u.api.key_env;
      const secret = process.env[keyEnv];
      if (!secret) throw new Error(`环境变量 ${keyEnv} 里没有钥匙 —— 见 .env`);
      const model = u.api.model;

      // 会话跟着 instance 走。头一个单元开会话、发 instructions；后面的直接接着讲。
      const s = await pool.get(vendor, u.instance, async () => {
        const fresh = new Session(ws, secret, model);
        await fresh.ready();
        await fresh.update(instructionsOf(u), u.tools.map(toolOf));
        return fresh;
      });

      const out = await s.turn(u.context.map(itemOf).filter((x): x is Item => x !== null));

      // 别人说的话先落库。**走那条唯一的投递管道** —— kind 和 role 都是推出来的，
      // 不在这儿填。`voice` 跟 `user` 分开：转写是说的，不是打的，混成一个的话
      // 回放这段上下文会把它当成人敲进来的字重新发一遍。
      for (const said of out.heard) {
        deliver(db, {
          agent: String(u.agent.name),
          instance: u.instance,
          unit: u.unit,
          by: "voice",
          body: said,
        });
      }

      // 形状跟 chat 那条轨**完全一致** —— 下游（内核落库、工具那一步）读的是同一份
      // 约定，两条轨回不一样的形状的话，下游就得认得「这是哪条轨回来的」。
      if (out.calls.length > 0) {
        return {
          role: "assistant",
          kind: "call",
          body: JSON.stringify({ text: out.text, calls: out.calls }),
        };
      }

      if (out.text.trim() === "") {
        // 一个来回走完了，一个字都没有。**这正是事件名漂了的样子** ——
        // 所以把线索一次说全：跳过了几条、见过哪些事件名、那边报过什么。
        // 只说「什么都没回来」的话，人得从头猜起。
        const why = [
          `${vendor}/${model} 走完一个来回但什么都没回来`,
          `跳过 ${out.skipped} 条事件`,
          out.audio ? `丢了 ${out.audio} 块音频` : "",
          out.errors.length ? `那边报过：${out.errors.join("；")}` : "",
          `见过的事件名：${[...s.seen].join("、") || "（一条都没有）"}`,
        ].filter(Boolean);
        throw new Error(why.join("；"));
      }

      return { role: "assistant", kind: "prompt", body: out.text };
    });
  }

  for (const [vendor, model] of seed) {
    const v = VENDORS[vendor];
    if (!v) throw new Error(`不认得这家：${vendor}`);
    if (!v.ws) throw new Error(`${vendor} 没有实时轨的地址，给不了 ${model} 一条 duplex 轨`);
    db.run(
      `insert into api (key_env, model, handle, modes) values (?, ?, ?, 'duplex')
       on conflict(key_env, model) do update set handle = excluded.handle, modes = excluded.modes`,
      [v.keyEnv, model, `fn:api.${vendor}.duplex`],
    );
  }

  return names;
}
