/**
 * 把某一站**当时发给模型的那份请求**，从库里重建出来。
 *
 * ```
 * bun scripts/request.ts <库文件> <实例> <单元> [--json]
 * bun scripts/request.ts ../data/h2h.sqlite dsw-full/anko-typed-variable-bindings#1 775
 * ```
 *
 * ## 为什么能重建
 *
 * 「**库 = 快照**」这条定理落在两个地方：
 *
 * - 消息表存的就是发出去的那份材料，不是「发生了什么事」的流水（`msg/deliver.ts` 开头
 *   那段说的正是这件事）；思考另占一列，出站时拼回消息里（`llm/index.ts` 的 `toMsg`）
 * - 每一站落一行**出站记账**（`kind=inject`、`role=system`）：那一轮模型被告知有哪些
 *   工具、每件工具的用法约定是什么、命中了哪些规则。没有它，回头看这一步就说不清
 *   它为什么那么做
 *
 * 所以这个脚本不自己拼消息 —— 它拿库里的行凑出内核那份 `Unit`，再调**内核自己那个**
 * `messagesOf`。自己拼一份的话，量的是这个脚本，不是那次请求。
 *
 * ## 有两样不在库里
 *
 * - **这一轮的任务视图**（`view`）：内核每轮现算，不落成消息 —— 因为消息跟着单链走，
 *   兄弟分支爬不到，而视图人人有份。里头的 `secondsLeft` 还跟着墙上的钟，事后重算
 *   本来也不会是当时那个数。这儿**不补**：补了就是编。
 * - **采样参数**（`maxTokens` / `temperature` / `seed` / `reasoningEffort`）在
 *   `config.yaml`，不在库里。
 *
 * 所以重建出来的是**消息列表和交代**，那也正是大小的来源：一份请求里除了它俩，剩下
 * 的是几个数。
 */

import { all, open } from "../src/H2H/db.ts";
import { tableNameOf } from "../src/install/index.ts";
import { instructionsOf, messagesOf, type Unit } from "../src/llm/index.ts";
import { sentAsIn } from "../src/msg/deliver.ts";
import { swapClosed, type Level, type Line } from "../src/msg/press.ts";

/** 一行或者没有。`db.ts` 只给了 `all`。 */
const one = (db: Parameters<typeof all>[0], sql: string, params?: Parameters<typeof all>[2]) =>
  (all(db, sql, params)[0] ?? null) as Record<string, unknown> | null;

const [file, instance, unitArg] = process.argv.slice(2);
if (!file || !instance || !unitArg) {
  console.error("bun scripts/request.ts <db> <instance> <unit> [--json] [--level l1|l2|l3|l4]");
  process.exit(1);
}
/**
 * **那一发是压过的话，压到哪一级。** 引擎的日志会说（`… sent at l2 (…)`）——
 * 不说就是没压。
 *
 * 换节点用的是内核那条路自己在用的 `swapClosed`，不是这儿另写一份：另写一份的话，
 * 重建出来的那份量的是这个脚本，不是那次请求。
 */
const level = ((process.argv.find((a) => a.startsWith("--level")) ?? "").split("=")[1] ??
  (process.argv.includes("--level") ? process.argv[process.argv.indexOf("--level") + 1] : "")) as Level | "";
const want = Number(unitArg);

const store = open({ db: { file, pragmas: { journal_mode: "wal" } } } as never);
const db = store.ro;

/** 这个实例在哪张子表上、是哪道题。 */
function whereIs(): { sub: string; task: string; mode: string } {
  for (const m of all(db, `select distinct mode from cycle`) as { mode: string }[]) {
    const sub = tableNameOf("task_{}", m.mode);
    const r = one(db, `select task from "${sub}" where instance = ? limit 1`, [instance]);
    if (r) return { sub, task: String(r.task), mode: m.mode };
  }
  throw new Error(`no station anywhere belongs to ${instance}`);
}

const { sub, task, mode } = whereIs();

interface Stat {
  task: string;
  cycle: string;
  unit: number;
  from_cycle: string | null;
  from_unit: number | null;
  agent: string;
  place: string;
}
const at = one(db, `select * from "${sub}" where instance = ? and unit = ?`, [instance, want]) as unknown as Stat | null;
if (!at) throw new Error(`${instance} has no unit ${String(want)}`);

// ── 链：顺着 from 一路走到根，跟 `#contextOf` 同一条走法 ──
const line: number[] = [];
const seen = new Set<string>();
let cur: Stat = at;
for (;;) {
  const key = `${cur.cycle}#${String(cur.unit)}`;
  if (seen.has(key)) throw new Error(`the chain of ${instance} is cyclic at ${key}`);
  seen.add(key);
  line.unshift(cur.unit);
  if (cur.from_cycle === null || cur.from_unit === null) break;
  const up = one(db, `select * from "${sub}" where task = ? and cycle = ? and unit = ?`, [
    task,
    cur.from_cycle,
    cur.from_unit,
  ]) as unknown as Stat | null;
  if (!up) throw new Error(`${cur.cycle}#${String(cur.unit)} came from a row that is not there`);
  cur = up;
}

const msgTable = tableNameOf("agent_{}_msg", at.agent);
const holes = line.map(() => "?").join(", ");
const context = all(
  db,
  // **`unit` 也要选出来** —— 换节点那一步是按格换的（`swapClosed`），
  // 少了这一列，每一行都不知道自己属于哪一格，于是一格都换不掉、而且不报错。
  `select unit, seq, role, kind, body, thought from "${msgTable}"
    where instance = ? and unit in (${holes}) order by unit, seq`,
  [instance, ...line],
) as unknown as Unit["context"];

const context2 = level
  ? (swapClosed(db, { sub, task, unit: want }, context as unknown as Line[], line, level) as unknown as typeof context)
  : context;

// ── 那一轮摆了哪几件工具：出站记账那一行说了 ──
const ledger = all(
  db,
  `select body from "${msgTable}" where instance = ? and unit = ? and kind = 'inject' and body like '%"sent":true%'`,
  [instance, want],
)[0] as { body: string } | undefined;
const kit = ledger ? (JSON.parse(ledger.body) as { tools?: string[]; rules?: string[] }) : {};
const tools = (kit.tools ?? []).map((n) => one(db, `select * from tool where name = ?`, [n])).filter(Boolean) as Unit["tools"];

const cycle = one(db, `select * from cycle where mode = ? and cycle = ?`, [mode, at.cycle])!;
const taskRow = one(db, `select * from task where id = ?`, [task])!;
const agentRow = one(db, `select * from agent where name = ?`, [at.agent])!;
const api = one(db, `select key_env, model, base_url, retry_on from api where handle = (select unit from agent where name = ?) or 1 = 1 limit 1`, [
  at.agent,
]) as Unit["api"];

const u: Unit = {
  agent: agentRow,
  task: taskRow,
  cycle,
  chain: line.map((n) => `${mode}/#${String(n)}`).join(" > "),
  place: at.place,
  instance,
  unit: want,
  api,
  context: context2,
  sentAs: sentAsIn(db),
  mustCall: String(cycle.must_call ?? "") || null,
  // **视图不补** —— 它不在库里，编一个出来就不是那次请求了。
  tools,
  rules: kit.rules ?? [],
};

const messages = messagesOf(u);
const instructions = instructionsOf(u);

const bytes = (v: unknown) => Buffer.byteLength(JSON.stringify(v), "utf8");
const kb = (n: number) => `${(n / 1024).toFixed(0)}k`;

console.log(`${instance}  ${at.cycle}#${String(want)}  （${mode}，链上 ${line.length} 格）\n`);
console.log(`  消息      ${String(messages.length).padStart(5)} 条   ${kb(bytes(messages)).padStart(7)}  ≈${String(Math.round(bytes(messages) / 4 / 1000))}k tok`);
console.log(`  交代      ${String(instructions.split("\n\n").length).padStart(5)} 段   ${kb(Buffer.byteLength(instructions, "utf8")).padStart(7)}`);
console.log(`  工具      ${String(tools.length).padStart(5)} 件   ${kb(bytes(tools.map((t) => ({ name: t.name, does: t.does, params: t.params })))).padStart(7)}`);
console.log(`  必须调用  ${u.mustCall ?? "（它自己挑）"}`);
console.log(`  模型      ${api ? `${String(api.model)} @ ${String(api.base_url)}` : "（这一站不问模型）"}`);

// 每种消息各占多少 —— 压缩要先知道砍哪儿最值
const per = new Map<string, { n: number; b: number }>();
for (const r of context2) {
  const g = per.get(r.kind) ?? { n: 0, b: 0 };
  g.n++;
  g.b += Buffer.byteLength(String(r.body ?? ""), "utf8") + Buffer.byteLength(String(r.thought ?? ""), "utf8");
  per.set(r.kind, g);
}
console.log(`\n  按 kind 分：`);
for (const [k, g] of [...per.entries()].sort((a, b) => b[1].b - a[1].b)) {
  console.log(`    ${k.padEnd(10)} ${String(g.n).padStart(5)} 行  ${kb(g.b).padStart(7)}`);
}
const think = context2.reduce((n, r) => n + Buffer.byteLength(String(r.thought ?? ""), "utf8"), 0);
const body = context2.reduce((n, r) => n + Buffer.byteLength(String(r.body ?? ""), "utf8"), 0);
console.log(`\n  其中思考 ${kb(think)} / 正文 ${kb(body)} —— 思考占 ${String(Math.round((think / (think + body)) * 100))}%`);
console.log(`\n  不在库里、这儿没补的：这一轮的任务视图（每轮现算，含跟墙上钟走的 secondsLeft）、`);
console.log(`  以及 config.yaml 里的采样参数。`);

if (process.argv.includes("--json")) {
  console.log(`\n${JSON.stringify({ instructions, messages }, null, 2)}`);
}

store.rw.close();
store.ro.close();
