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
export const HUMAN_MARK = "【人】";

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
  skill: { kind: "skill", role: "user" },
  tool: { kind: "tool", role: "tool" },
  agent: { kind: "prompt", role: "assistant" },
  kernel: { kind: "inject", role: "system" },
};

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
export function deliver(db: Conn, p: Put): number {
  const t = tableNameOf("agent_{}_msg", p.agent);
  const { kind, role } = FROM[p.by];
  if (!kind) throw new Error(`不认得的投递来源：${p.by}`);

  // 人给的缀上标记。**在这儿缀，不在调用方缀** —— 调用方缀就成了纪律。
  // 判据是 `HUMAN`（写的、说的都算），不是某一个具体的 by —— 加一种人类来源时
  // 漏改这一行的话，那一路就悄悄丢了标记，而压出去之后再也分不出来。
  const body = HUMAN.has(p.by) ? `${HUMAN_MARK}${p.body}` : p.body;

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

/** 认得的消息类型 —— `msg_kind` 表的种子。**取值就是上面那张推断表的值域。** */
export const KINDS: [string, string][] = [
  ["user", "真人写的。压出去前缀 " + HUMAN_MARK + "，好跟系统注入分开"],
  ["voice", "真人说的，实时轨转写来的。role 也是 user，靠 kind 才分得出它是说的不是打的"],
  ["inject", "系统注入的。压出去也是 role=user，靠 kind 才分得出来"],
  ["skill", "skill 临时放的提示词"],
  ["tool", "工具的返回结果"],
  ["prompt", "模型自己说的"],
  ["call", "模型请求工具那一条，body 里带着调用"],
  ["intervene", "用户看着它执行时施加的干预标记"],
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
