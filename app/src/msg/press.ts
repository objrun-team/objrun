/**
 * 把一个节点压成三份，以及内置的那几种压法。
 *
 * ## 什么时候压
 *
 * **节点收口那一刻**（那一站拿到了终止状态）。还在出的节点不压 —— 它的话正在被用，
 * 而且下一站可能还要接着说。所以**当前节点永远是原文**，压的只有已经收口的祖先。
 *
 * 压完写进库（`press` + `press_l1/l2/l3`，`task_{mode}.press` 指过去），不是发的时候
 * 现算：现算的话同一格每次请求压出来的都不一样，而一份在模型底下自己会变的上下文，
 * 出了问题谁也复现不了。
 *
 * ## 谁说了算
 *
 * 一条消息拆成哪几部分，只看**消息本来就得有的形状**（`thought` 那一列、`body.text`、
 * `body.calls[]`、`kind`、`role`）；工具返回是哪一类，看那件工具自己填的 `tool.gives`。
 * 每一部分在每一级怎么办，查 `msg_part`；怎么办由 `press_how.identity` 那个句柄去做。
 *
 * 所以这个文件里**没有一个工具名，也没有一句「哪种更要紧」** —— 那些全在表里。
 *
 * ## 内置的那几种压法
 *
 * `keep` / `drop` / `cut` / `sample` 是纯函数，随二进制发。`ask`（丢给模型换一段话）
 * 不在这儿：它得有个模型，而挑哪个模型是外面的事 —— 声明一个句柄进来就是了。
 */

import { createHash } from "node:crypto";

import type { Conn } from "../H2H/db.ts";
import { all, run } from "../H2H/db.ts";
import type { Registry } from "../engine/registry.ts";
import { tableNameOf } from "../install/index.ts";

/** 一次压缩请求。 */
export interface Press {
  part: string;
  name?: string;
  level: string;
  body: string;
  bytes?: number;
}

/** `cut` 留多少字节。 */
export const CUT_BYTES = 2_000;
/** `sample` 留几行头、几行尾。 */
export const SAMPLE_HEAD = 3;
export const SAMPLE_TAIL = 3;
/** `top` 留几行、`tail` 留几行。一屏 —— 一段栈、一次测试的结论，都在这个量级上。 */
export const TOP_LINES = 20;
export const TAIL_LINES = 20;

/**
 * 级别的列名。**顺序就是从轻到重**，选级别时按这个顺序往下降。
 *
 * 有四列，但**设好了的只算前三级** —— `l4` 在 `msg_part` 里还空着（见 `readyLevels`）。
 * 空着的那一级不写、也不发。先把列留出来，是因为下一级要来的那种压法（把一段丢给模型
 * 换一句话）是从外面声明进来的，而声明发生在一个正在跑的库上 —— 那时候再加列就是一次迁移。
 */
export const LEVELS = ["l1", "l2", "l3", "l4"] as const;
export type Level = (typeof LEVELS)[number];

/**
 * 哪几级是**真设好了的**：`msg_part` 里每一行都说了这一级拿它怎么办。
 *
 * 判据是「**每一行**都填了」，不是「有行填了」。填了一半的话，那一级里有的部分按策略走、
 * 有的部分不知道该怎么办 —— 而两种都说得通、都不报错。
 *
 * 一行都没有（表还没灌）时回空：那是「什么都没设」，不是「四级全设好了」。
 */
export function readyLevels(db: Conn): Level[] {
  const rows = all(db, `select ${LEVELS.map((l) => `"${l}"`).join(", ")} from msg_part`) as Record<string, string | null>[];
  if (rows.length === 0) return [];
  return LEVELS.filter((l) => rows.every((r) => String(r[l] ?? "").trim() !== ""));
}

const say = (v: unknown): string => (typeof v === "string" ? v : String(v ?? ""));
const B = (s: string) => Buffer.byteLength(s, "utf8");
const id = (s: string) => createHash("sha256").update(s).digest("hex").slice(0, 32);

/**
 * 头留一段，末尾记一句还剩多少。
 *
 * 记那一句是有代价的（几十字节），但**不记的话模型不知道自己看的是半截**，
 * 而它会照着半截往下判断 —— 那种错查起来最费劲，因为看上去它读到的是完整的。
 */
export function cut(body: string, keep = CUT_BYTES): string {
  const size = B(body);
  if (size <= keep) return body;
  return `${Buffer.from(body, "utf8").subarray(0, keep).toString("utf8")}\n... (${size - keep} more bytes)`;
}

/**
 * 前几行，末尾记一句还剩多少行。
 *
 * 跟 `cut` 是一件事的两种量法：`cut` 数字节，`top` 数行。**有行的东西按行留** ——
 * 按字节切会停在半行上，而半行读起来跟整行一样理直气壮。
 */
export function top(body: string, keep = TOP_LINES): string {
  const lines = body.split("\n");
  // 只多出一行就别留了：省下一行，却要花一行去说省了一行。
  if (lines.length <= keep + 1) return body;
  return [...lines.slice(0, keep), `... (${lines.length - keep} more lines)`].join("\n");
}

/**
 * 后几行，开头记一句前面还有多少行。
 *
 * `top` 的反面，给**结论在末尾**的那些东西：一次测试跑完的那几行、一段栈的最后一层、
 * 一份构建日志真正报错的地方。这类东西留头等于留了一堆铺垫，正好把要看的那段丢掉。
 */
export function tail(body: string, keep = TAIL_LINES): string {
  const lines = body.split("\n");
  if (lines.length <= keep + 1) return body;
  return [`... (${lines.length - keep} earlier lines)`, ...lines.slice(-keep)].join("\n");
}

/** 头几行 + 尾几行，中间记个数。按行抽，不按字节 —— 半行没有意义。 */
export function sample(body: string, head = SAMPLE_HEAD, foot = SAMPLE_TAIL): string {
  const lines = body.split("\n");
  if (lines.length <= head + foot + 1) return body;
  return [...lines.slice(0, head), `... (${lines.length - head - foot} more lines)`, ...lines.slice(-foot)].join("\n");
}

/** 把内置的那几种注册进去。**回注册了哪几个句柄名。** */
export function registerPress(db: Conn, reg: Registry): string[] {
  const names: string[] = [];
  const one = (name: string, f: (p: Press) => { body?: string }) => {
    const handle = `fn:press.${name}`;
    reg.register(db, handle, 10_000, async (arg) => f((arg ?? {}) as Press));
    names.push(handle);
  };
  one("keep", (p) => ({ body: say(p.body) }));
  // **回一个没有 body 的东西，不是回空串。** 两者在库里长得一样，但读的人分得出
  // 「这一部分不出现」和「它出现了，内容是空的」。
  one("drop", () => ({}));
  one("cut", (p) => ({ body: cut(say(p.body)) }));
  one("sample", (p) => ({ body: sample(say(p.body)) }));
  one("top", (p) => ({ body: top(say(p.body)) }));
  one("tail", (p) => ({ body: tail(say(p.body)) }));
  return names;
}

// ── 拆 ──────────────────────────────────────────────────────────────────────

/** 一条消息拆出来的一块。 */
export interface Piece {
  part: string;
  /** 属于哪件工具。不属于任何工具就是空。 */
  name: string;
  body: string;
}

interface Row {
  unit: number;
  seq: number;
  role: string;
  kind: string;
  body: string;
  thought: string | null;
}

/**
 * 一条消息拆成几块。**判据只有形状**，见文件头。
 *
 * `gives` 是「工具名 → 它的返回算哪一类」，调用方从 `tool` 表读一次传进来 ——
 * 每拆一行查一次库的话，一个节点就是几百次查询。
 */
export function piecesOf(r: Row, first: boolean, gives: Map<string, string>): Piece[] {
  const out: Piece[] = [];
  if (r.thought) out.push({ part: "thought", name: "", body: r.thought });

  if (r.kind === "call" || r.kind === "graded") {
    let v: { text?: unknown; calls?: { name?: unknown; input?: unknown }[] };
    try {
      v = JSON.parse(r.body) as typeof v;
    } catch {
      return out;
    }
    const text = say(v.text).trim();
    if (text) out.push({ part: "said", name: "", body: text });
    for (const c of v.calls ?? []) {
      // `graded` 是系统事后记下的一次裁决 —— 判据是 kind，不是那件工具叫什么。
      out.push({
        part: r.kind === "graded" ? "verdict" : "call",
        name: say(c.name),
        body: `${say(c.name)} ${JSON.stringify(c.input ?? {})}`,
      });
    }
    return out;
  }

  if (r.kind === "tool") {
    let v: { name?: unknown; value?: unknown };
    try {
      v = JSON.parse(r.body) as typeof v;
    } catch {
      return out;
    }
    const name = say(v.name);
    // 那件工具自己说它的返回算哪一类。**没说 = `event`** —— 把拿不回来的当成能再拿
    // 一次，是唯一赔不起的那个方向。
    out.push({ part: gives.get(name) || "event", name, body: JSON.stringify(v.value ?? null) });
    return out;
  }

  if (r.kind === "prompt") {
    if (r.body.trim()) out.push({ part: "said", name: "", body: r.body });
    return out;
  }
  // `inject` 一个值管两样：世界注入是 role=user，进消息流；内核记账是 role=system，
  // 走 instructions。**必须连 role 一起看。**
  if (r.kind === "inject") {
    out.push({ part: r.role === "system" ? "ledger" : "world", name: "", body: r.body });
    return out;
  }
  if (r.kind === "user" || r.kind === "voice") {
    // 题面跟人说话是同一个 kind，只有位置分得开：实例的第一条就是题面。
    out.push({ part: first ? "task" : "person", name: "", body: r.body });
    return out;
  }
  if (r.kind === "skill" || r.kind === "intervene") {
    out.push({ part: r.kind, name: "", body: r.body });
    return out;
  }
  out.push({ part: "person", name: "", body: r.body });
  return out;
}

// ── 压 ──────────────────────────────────────────────────────────────────────

interface Policy {
  /** 部分名 → 每一级各用哪种压法。没设的那一级是空串。 */
  part: Map<string, Record<Level, string>>;
  /** 哪几级是设好了的。**只有这几级会被写、被发。** */
  ready: Level[];
  /** 压法名 → 干这件事的句柄。空的那种（没实现）不在里面。 */
  how: Map<string, string>;
  /** 工具名 → 它的返回算哪一类。 */
  gives: Map<string, string>;
}

/** 把三张表读一次。**一个节点读一次，不是一块读一次。** */
export function policyOf(db: Conn): Policy {
  const part = new Map<string, Record<Level, string>>();
  for (const r of all(db, `select name, ${LEVELS.join(", ")} from msg_part`) as Record<string, string | null>[]) {
    const at = {} as Record<Level, string>;
    for (const l of LEVELS) at[l] = String(r[l] ?? "");
    part.set(String(r.name), at);
  }
  const how = new Map<string, string>();
  for (const r of all(db, `select name, identity from press_how where identity is not null and identity <> ''`) as {
    name: string;
    identity: string;
  }[]) {
    how.set(String(r.name), String(r.identity));
  }
  const gives = new Map<string, string>();
  for (const r of all(db, `select name, gives from tool where gives is not null and gives <> ''`) as {
    name: string;
    gives: string;
  }[]) {
    gives.set(String(r.name), String(r.gives));
  }
  return { part, ready: readyLevels(db), how, gives };
}

/**
 * 一格压成一段话。
 *
 * 每一块前面挂一个标记，不挂的话工具返回和模型说的话拼在一起分不出是谁说的。
 * 一块都没剩下就回空串 —— 那一格在这一级上整个不出现。
 */
export async function pressUnit(reg: Registry, pieces: Piece[], level: Level, p: Policy): Promise<string> {
  const out: string[] = [];
  for (const one of pieces) {
    const how = p.part.get(one.part)?.[level] ?? "keep";
    // 空 = 这一级 `msg_part` 里根本没填。压到这儿是调用方的错（该先看 `ready`），
    // 而按 keep 放过去的话，一个「压过的」级别里装的会是原文。
    if (!how) throw new Error(`msg_part says nothing about ${one.part} at ${level}`);
    const handle = p.how.get(how);
    // **没实现的压法当场炸。** 悄悄按 keep 放过去的话，说好要压的东西原样发了出去，
    // 而唯一的表现是「怎么还是这么大」。
    if (!handle) throw new Error(`msg_part says ${one.part} is ${how} at ${level}, but no handle implements ${how}`);
    const back = (await reg.get(handle).call({
      part: one.part,
      name: one.name,
      level,
      body: one.body,
      bytes: B(one.body),
    })) as { body?: unknown };
    const body = say(back?.body);
    if (!body) continue;
    out.push(one.name ? `[${one.part} ${one.name}] ${body}` : `[${one.part}] ${body}`);
  }
  return out.join("\n");
}

/**
 * 把一个节点的每一格都压成三份，落库。**回压了几格。**
 *
 * 已经压过的格子跳过：节点收口只有一次，但重装、重放都可能再走到这儿。
 */
export async function pressNode(
  db: Conn,
  reg: Registry,
  at: { sub: string; task: string; node: number; agent: string; instance: string },
): Promise<number> {
  const units = (all(db, `select unit, press from "${at.sub}" where task = ? and node = ? order by unit`, [
    at.task,
    at.node,
  ]) as { unit: number; press: string | null }[]).filter((u) => !u.press);
  if (units.length === 0) return 0;

  const t = tableNameOf("agent_{}_msg", at.agent);
  const holes = units.map(() => "?").join(", ");
  const rows = all(
    db,
    `select unit, seq, role, kind, body, thought from "${t}" where instance = ? and unit in (${holes}) order by unit, seq`,
    [at.instance, ...units.map((u) => u.unit)],
  ) as unknown as Row[];

  const p = policyOf(db);
  const byUnit = new Map<number, Row[]>();
  for (const r of rows) byUnit.set(Number(r.unit), [...(byUnit.get(Number(r.unit)) ?? []), r]);

  let done = 0;
  for (const u of units) {
    const mine = byUnit.get(Number(u.unit)) ?? [];
    if (mine.length === 0) continue;
    const pieces = mine.flatMap((r) => piecesOf(r, Number(r.unit) === 1 && Number(r.seq) === 1, p.gives));

    const at3: Record<string, string> = {};
    for (const level of p.ready) {
      const body = await pressUnit(reg, pieces, level, p);
      // **一段话一行，按内容做 id** —— 两格压出同样的东西就落在同一行上，不用谁去比对，
      // 「几格合起来只用这一段话表示」也就自然成立了。
      const rid = id(body);
      run(db, `insert into "press_${level}" (id, body, bytes) values (?, ?, ?) on conflict(id) do nothing`, [
        rid,
        body,
        B(body),
      ]);
      at3[level] = rid;
    }
    // id 按**所有**级别算，空着的那几级也算进去 —— 将来 `l4` 有了内容，同样两格就不该
    // 再落在同一行上，而那时候这个 id 自己会变。
    const pid = id(LEVELS.map((l) => at3[l] ?? "").join(" "));
    const cols = LEVELS.filter((l) => at3[l]);
    run(
      db,
      `insert into press (id, ${cols.join(", ")}) values (${["?", ...cols.map(() => "?")].join(", ")}) on conflict(id) do nothing`,
      [pid, ...cols.map((l) => at3[l])],
    );
    run(db, `update "${at.sub}" set press = ? where task = ? and unit = ?`, [pid, at.task, u.unit]);
    done++;
  }
  return done;
}

/** 一行消息，只用得上这几列。 */
export interface Line {
unit: number;
seq: number;
role: string;
kind: string;
body: string;
thought: string | null;
}

/**
 * 把**已经收口的那些节点**换成它们压过的那一份。当前节点原样不动 —— 它的话正被用着。
 *
 * 按**节点**换，不按格换：一次调用和它的结果落在相邻两格上，只换其中一格的话，
 * 上下文里会留下一个没有调用的结果，而模型那边直接拒收整份。
 *
 * 没压过的节点（`press` 是空的）照原文发 —— 压是收口那一刻做的，做不成不该让这一发
 * 也跟着完蛋。
 *
 * **发请求的那条路和事后重建那条路用的是这一个函数**（`engine/loop.ts` 和
 * `scripts/request.ts`）。各写一份的话，重建出来的那份量的是脚本，不是那次请求。
 */
export function swapClosed(
db: Conn,
at: { sub: string; task: string; unit: number },
rows: Line[],
line: number[],
level: Level,
): Line[] {
  const nodes = all(
    db,
    `select unit, node, status from "${at.sub}" where task = ? and unit in (${line.map(() => "?").join(", ")})`,
    [at.task, ...line],
  ) as unknown as { unit: number; node: number; status: string | null }[];
  const here = nodes.find((n) => Number(n.unit) === at.unit)?.node;
  const closed = new Set(
    nodes.filter((n) => Number(n.node) !== Number(here)).map((n) => Number(n.node)),
  );
  if (closed.size === 0) return rows;

  const nodeOf = new Map(nodes.map((n) => [Number(n.unit), Number(n.node)]));
  const swap = line.filter((u) => closed.has(nodeOf.get(u) ?? -1));
  const bodies = bodiesAt(db, at.sub, at.task, swap, level);

  const out: Line[] = [];
  for (const r of rows) {
    const u = Number(r.unit);
    if (!closed.has(nodeOf.get(u) ?? -1)) {
      out.push(r);
      continue;
    }
    // 这一格属于压过的节点：它自己那几行不出，取而代之的是那一段话 —— 而且**同一段
    // 只出一次**（几格合用一段是常态，`bodiesAt` 已经去过重）。
    const body = bodies.get(u);
    if (body === undefined) {
      // 没压过：`bodiesAt` 里根本没有这一格 → 照原文发。
      if (!bodies.size) out.push(r);
      continue;
    }
    if (out.some((x) => Number(x.unit) === u)) continue;
    // 压出来是空的（那一格里每一部分在这一级都被丢了）就整格不出。发一条空消息是
    // 白花一条：有的供应商直接拒收空 content，而拒的时候说的是「消息列表有问题」。
    if (!body.trim()) continue;
    out.push({ unit: u, seq: 1, role: "user", kind: "user", body, thought: null } as unknown as Line);
  }
  return out;
}

/**
 * 这几格在某一级上的正文。**同一行只出一次** —— 好几格指着同一段话是常态，
 * 每格都出一遍的话，省下来的又原样加回去了。
 */
export function bodiesAt(db: Conn, sub: string, task: string, units: number[], level: Level): Map<number, string> {
  if (units.length === 0) return new Map();
  const holes = units.map(() => "?").join(", ");
  const rows = all(
    db,
    `select s.unit as unit, l.body as body, s.press as press
       from "${sub}" s join press p on p.id = s.press join "press_${level}" l on l.id = p."${level}"
      where s.task = ? and s.unit in (${holes})`,
    [task, ...units],
  ) as { unit: number; body: string; press: string }[];
  const seen = new Set<string>();
  const out = new Map<number, string>();
  for (const r of rows.sort((a, b) => Number(a.unit) - Number(b.unit))) {
    const key = String(r.body);
    if (seen.has(key)) continue;
    seen.add(key);
    out.set(Number(r.unit), String(r.body));
  }
  return out;
}
