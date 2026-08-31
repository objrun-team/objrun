/**
 * 往上下文里投一条消息 —— **写在一处，读在一处，来源不丢。**
 *
 * ## 为什么必须只有这一处
 *
 * 老代码那边曾经有两份一模一样的实现（智能体侧一份、内核侧一份），后者的注释
 * 自己写着「这段与那边是同一段代码的两份拷贝」。**两份拷贝意味着同一个 bug 有
 * 两份副本，而修的时候多半只修一份。** 所以这个文件是唯一的入口，内核、发布口、
 * 规则、skill 全走它。
 *
 * ## `kind` 是**推**出来的，不是填的
 *
 * 这是这一块最要紧的一条。老代码的原话：
 *
 * > 标记的**依据必须是系统已有的事实，不能是一条纪律** —— 靠人记得在消息前面加个
 * > 前缀，漏一次就静默失效，而且没人查得出来。
 *
 * 所以调用方说的是「**谁放的**」（`by`），`kind` 由它推出来。之前那版是调用方自己
 * 填 `kind`，那就是一条纪律：填错、忘填都不报错，而事后谁也分不出「这段是人写的」
 * 还是「这段是规则投的」。
 *
 * ## 人写的那些要看得出来
 *
 * 压给模型的时候，所有非 assistant 的东西最后都拼成一串 `user`。**人写的和系统
 * 注入的在拼完之后就分不开了** —— 除非在库里标着。`HUMAN_MARK` 是那个标记，
 * 定义在这一处，下游读的是**同一个常量**，不是各写各的字面量。
 */

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import { tableNameOf } from "../install/index.ts";

/** 人写的那些块的前缀。**一处定义** —— 下游读它，不各写各的字面量。 */
export const HUMAN_MARK = "[human] ";

/** 哪几种来源算「人给的」。**取值就是缀不缀 `HUMAN_MARK` 的判据本身。** */
const HUMAN = new Set<By>(["user", "voice"]);

/**
 * 谁放的。`kind` 从这儿推。
 *
 * - `user` —— 真人写的。**有意图、有责任**，压出去前缀 `HUMAN_MARK`
 * - `voice` —— 真人**说**的，实时轨转写来的。同样有意图有责任，同样缀 `HUMAN_MARK`；
 *   但跟 `user` **分开记**：转写是说的不是打的，混成一个的话，回放这段上下文会把
 *   它当成人敲进来的字重新发一遍，而那不报错
 * - `world` —— 机械的确定性产出（规则命中后投进来的知识）。**无意图无责任**
 * - `skill` —— skill 临时放的提示词
 * - `tool` —— 工具的返回
 * - `agent` —— 智能体自己说的。**它不进这条管道** —— 那是它自己的轨迹，
 *   由执行单元直接落库
 * - `kernel` —— 内核的记账（出站凭据那种）。给我们看的，不当内容发给模型
 */
export type By = "user" | "voice" | "world" | "skill" | "tool" | "agent" | "kernel";

/** 谁放的 → 落库时的 `kind` 和 `role`。**这张表就是那条推断规则本身。** */
const FROM: Record<By, { kind: string; role: string }> = {
  user: { kind: "user", role: "user" },
  voice: { kind: "voice", role: "user" },
  world: { kind: "inject", role: "user" },
  // **skill 自己就是一种身份。**
  //
  // 之前它落成 `role: "user"` —— 那等于告诉模型「有人在跟你说这段话」。实测的后果：
  // 一段方法注入被读成对话，模型开始接话反问（「请把本题的具体选项发出来」），
  // 不再作答。它不是人说的，也不是模型说的，更不是工具回的 —— 它是我们按条件塞进去
  // 的一段提示，那就该有自己的 role，怎么呈现给模型由适配器决定（见 `llm/index.ts`
  // 的 `sendable` / `instructionsOf`：它走 instructions，不进消息流）。
  skill: { kind: "skill", role: "skill" },
  tool: { kind: "tool", role: "tool" },
  agent: { kind: "prompt", role: "assistant" },
  kernel: { kind: "inject", role: "system" },
};

/**
 * 哪几种 `kind` 是人给的。**从上面那两张表推出来，不另列一份名单。**
 *
 * 下游（接口那一层）判「这条是不是人给的」只能靠它 —— **不许看 body 长什么样**：
 * 上下文里人写的那条带着 `HUMAN_MARK` 前缀，模型照着学、在回答开头复读一句，
 * 就被当成人写的了（实测它真会这么干）。`kind` 是投递那一刻推出来的，伪造不了。
 */
export const HUMAN_KINDS = new Set([...HUMAN].map((b) => FROM[b].kind));

export interface Put {
  agent: string;
  instance: string;
  unit: number;
  by: By;
  body: string;
  /** `skill` / `tool` 这类要说清是哪一个 —— 事后查得出是谁投的。 */
  who?: string;
}

/**
 * 投一条。返回它落在第几条。
 *
 * `role` 也是推出来的：模型只认那几个 role，而「这条实际是什么」得另外标着 ——
 * 压给模型的时候系统注入的也是一条 `user`，光看消息列表分不出它是不是真人讲的。
 */
/**
 * 这一行的 `body` 形状对不对。**入库那一刻就查。**
 *
 * 以前不查，代价很具体：库里能躺着一条 `call`，它的 `calls` 里某一次没有 `id`，
 * 而 `id` 正是工具结果配回来的钥匙 —— 没有它，那次调用永远配不上结果，整份
 * 上下文从此发不出去。这件事以前要等到发请求时才被发现。
 *
 * 能在这一刻查的只有「这一行自己说得通吗」。「这次调用后来有没有人答」是后话，
 * 归 `answerMissing` 管。
 */
export function checkBody(kind: string, body: string): void {
  if (kind !== "call" && kind !== "tool") return;
  let v: unknown;
  try {
    v = JSON.parse(body);
  } catch {
    throw new Error(`a ${kind} message must carry JSON in its body, and this one does not parse`);
  }
  if (kind === "call") {
    const calls = (v as { calls?: unknown }).calls;
    if (!Array.isArray(calls)) throw new Error("a call message must carry a calls array");
    for (const c of calls as { id?: unknown; name?: unknown }[]) {
      if (typeof c.id !== "string" || c.id === "") throw new Error("every call needs a non-empty id");
      if (typeof c.name !== "string" || c.name === "") throw new Error("every call needs a tool name");
    }
    return;
  }
  const id = (v as { id?: unknown }).id;
  if (typeof id !== "string" || id === "") throw new Error("a tool result needs the id of the call it answers");
}

/**
 * 把这一串行里**没人答的调用补齐**：给每一次没有结果的调用写一条结果，说明它
 * 从没跑过。返回补了几条。
 *
 * ## 为什么是补，不是摘
 *
 * 一条 `call` 没人答，是真发生过的事。**这一站有没有人真去跑工具，取决于机制
 * 怎么搭**：下一站走 `fn:unit.tools` 就有人跑，一条纯问答的轨就没人跑。而系统
 * 工具是无条件挂上去的，所以纯问答的多站机制里，模型迟早会请求一次没人跑的工具。
 *
 * 缺了结果，上下文就发不出去 —— 模型那边一律要求「有 tool_call 就得有对应的
 * tool result」。以前的解法是发之前把那一行**摘掉**，代价是两条：
 *
 * - 模型看到的历史里，那次调用**凭空消失**。它会以为自己没调过，再调一遍
 * - 库里存的和发出去的**不是一份东西**。出了事，拿着库复原不出模型看见了什么
 *
 * 补一条「没跑成」两样都解决：模型看得见自己调过、也看得见没结果；而库里存的
 * 就是发出去的那一份。
 */
export function answerMissing(
  db: Conn,
  agent: string,
  instance: string,
  rows: { unit: number; seq: number; kind: string; body: string }[],
): number {
  const answered = new Set<string>();
  for (const r of rows) {
    if (r.kind !== "tool") continue;
    try {
      const id = (JSON.parse(r.body) as { id?: string }).id;
      if (id) answered.add(id);
    } catch {
      // 读不出 id 的当它没答过 —— 这种行现在也进不了库了（见 checkBody）
    }
  }

  const t = tableNameOf("agent_{}_msg", agent);
  const tail = new Map<number, number>();
  for (const r of rows) tail.set(r.unit, Math.max(tail.get(r.unit) ?? 0, r.seq));

  let put = 0;
  for (const r of rows) {
    if (r.kind !== "call") continue;
    let calls: { id?: string; name?: string }[];
    try {
      calls = (JSON.parse(r.body) as { calls?: { id?: string; name?: string }[] }).calls ?? [];
    } catch {
      continue;
    }
    for (const c of calls) {
      if (!c.id || answered.has(c.id)) continue;
      // 补在**发起调用的那个单元**末尾 —— 排序是 (unit, seq)，所以它紧跟在那一行
      // 后面，读起来就是「调了，没跑成」。
      const seq = (tail.get(r.unit) ?? r.seq) + 1;
      tail.set(r.unit, seq);
      answered.add(c.id);
      run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, 'tool', 'tool', ?, ?)`, [
        instance,
        r.unit,
        seq,
        JSON.stringify({
          id: c.id,
          name: c.name ?? "",
          value: { ran: false, why: "this station ended before the call was run" },
        }),
        Date.now(),
      ]);
      put++;
    }
  }
  return put;
}

export function deliver(db: Conn, p: Put): number {
  const t = tableNameOf("agent_{}_msg", p.agent);
  const { kind, role } = FROM[p.by];
  if (!kind) throw new Error(`unknown delivery source: ${p.by}`);

  // 人给的缀上标记。**在这儿缀，不在调用方缀** —— 调用方缀就成了纪律。
  // 判据是 `HUMAN`（写的、说的都算），不是某一个具体的 by —— 加一种人类来源时
  // 漏改这一行的话，那一路就悄悄丢了标记，而压出去之后再也分不出来。
  const body = HUMAN.has(p.by) ? `${HUMAN_MARK}${p.body}` : p.body;
  checkBody(kind, body);

  const got = all(db, `select coalesce(max(seq), 0) as m from "${t}" where instance = ? and unit = ?`, [
    p.instance,
    p.unit,
  ])[0] as { m: number };
  const seq = Number(got.m) + 1;

  run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, ?, ?, ?, ?)`, [
    p.instance,
    p.unit,
    seq,
    role,
    kind,
    body,
    Date.now(),
  ]);
  return seq;
}

/**
 * 把一次**外部裁决**投成「一次工具调用 + 它的结果」两行。
 *
 * ## 为什么是这个形状
 *
 * G 判完之后，那个判决以前**只进日志和 `task.result`，从不进上下文**。于是判死开兄弟
 * 是**盲重试**：新分支知道要换条路，但不知道上一条错在哪。verifier-guided 的
 * verifier 那一半等于没接上。
 *
 * 要让模型看见，就得选一个身份。三种都试得出问题：
 *
 * | 当成 | 为什么不行 |
 * | --- | --- |
 * | `user` 说的 | 「有人在跟我说我错了」—— 模型会去接话、辩解 |
 * | `system` 指令 | 它不是交代，是**这一次的观测结果**；而且 instructions 每轮重发，判决会糊在一起 |
 * | `assistant` 自己说的 | 那是让它自己承认，等于伪造它的轨迹 |
 *
 * **一次带结果的工具调用**才对：它是外部的、这一次的、可核对的观测 —— 正好是
 * tool 结果的语义。而且这两种行内核本来就有（`call` / `tool`），`toMsg` 直接认，
 * 不用给模型那边加任何新概念。
 *
 * ## 那 `call` 那一半算不算伪造
 *
 * 上面刚说了「不当 `assistant`，那等于伪造它的轨迹」，可这一对里 `call` 那半确实
 * 写成了 `role: assistant`。这一条只有在 **`verify` 是个真工具**的前提下才立得住 ——
 * 否则上下文里躺着一条「我调用了 verify」，模型真去调却报「tool 表里没有 verify」，
 * 那才是伪造。所以 `objective/tool.ts` 把它注册了：有 G 的任务就挂得上，模型自己
 * 也能调。轨迹跟能力对得上，这一对就名副其实。
 *
 * ## 为什么放在这个文件里
 *
 * 它写的是两行消息，那就得走这条唯一的管道 —— seq 怎么排、`kind` 怎么定，
 * 只许有一处说了算。绕过去自己 insert 的话，就是这个文件开头警告的那件事。
 */
export function deliverVerdict(
  db: Conn,
  p: { agent: string; instance: string; unit: number; name: string; input: unknown; value: unknown },
): number {
  const t = tableNameOf("agent_{}_msg", p.agent);
  const got = all(db, `select coalesce(max(seq), 0) as m from "${t}" where instance = ? and unit = ?`, [
    p.instance,
    p.unit,
  ])[0] as { m: number };
  let seq = Number(got.m);
  // 调用 id 得对得上 —— 模型那边一律要求「有 tool_call 就得有对应的 tool result」，
  // 配不上的话整份上下文发不出去（见 `loop.ts` 的 `dropDangling`）。
  const id = `g-${p.instance}-${p.unit}-${seq + 1}`;
  const at = Date.now();

  run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, 'assistant', 'call', ?, ?)`, [
    p.instance,
    p.unit,
    ++seq,
    JSON.stringify({ text: "", calls: [{ id, name: p.name, input: p.input }] }),
    at,
  ]);
  run(db, `insert into "${t}" (instance, unit, seq, role, kind, body, at) values (?, ?, ?, 'tool', 'tool', ?, ?)`, [
    p.instance,
    p.unit,
    ++seq,
    JSON.stringify({ id, name: p.name, value: p.value }),
    at,
  ]);
  return seq;
}

/**
 * 认得的 `role` —— **取值就是上面那张推断表的 role 那一列**，不另列一份名单。
 *
 * 库里这一列不是「模型认得的那四个」：`skill` 就是一种独立身份。怎么把它送到模型
 * 那边去，是适配器的事（`llm/index.ts` 的 `ROLES`：`skill` 走 instructions，
 * 不进消息流）。**库先认得，再谈怎么呈现** —— 反过来的话，加一种身份就得同时改
 * 两处，而漏改的表现是那一路悄悄按别人的身份进了上下文。
 */
export const ROLES = [...new Set(Object.values(FROM).map((f) => f.role))].sort();

/** 认得的消息类型 —— `msg_kind` 表的种子。**取值就是上面那张推断表的值域。** */
export const KINDS: [string, string][] = [
  ["user", "Written by a person. Prefixed with " + HUMAN_MARK + " on the way out so it stays distinguishable from system injections"],
  ["voice", "Spoken by a person, transcribed from the realtime lane. Its role is also user; only kind tells speech apart from typing"],
  ["inject", "Injected by the system. Also goes out as role=user; only kind tells it apart"],
  ["skill", "A prompt placed by a skill"],
  ["tool", "A tool result"],
  ["prompt", "What the model itself said"],
  ["call", "The model requesting tools; the calls ride in body"],
  ["intervene", "A mark left by a user intervening while it runs"],
];

/** 把认得的消息类型灌进 `msg_kind`。幂等。 */
export function seedKinds(db: Conn): string[] {
  for (const [name, note] of KINDS) {
    run(db, `insert into msg_kind (name, note) values (?, ?) on conflict(name) do update set note = excluded.note`, [
      name,
      note,
    ]);
  }
  return KINDS.map(([n]) => n);
}
