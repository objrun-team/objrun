/**
 * Reconstruct **the request originally sent to the model** for an execution unit from the database.
 *
 * ```
 * bun scripts/request.ts <database> <instance> <unit> [--json]
 * bun scripts/request.ts ../data/h2h.sqlite dsw-full/anko-typed-variable-bindings#1 775
 * ```
 *
 * ## Why reconstruction is possible
 *
 * The **database = snapshot** invariant rests on two facts:
 *
 * - Message rows store the actual material sent, not an event log describing what happened
 *   (see the introduction to `msg/deliver.ts`). Thinking occupies a separate column and is
 *   reattached when sending the message (`toMsg` in `llm/index.ts`).
 * - Each execution unit stores an **outbound accounting row** (`kind=inject`, `role=system`):
 *   the tools offered to the model, each tool's usage instructions, and the rules that matched.
 *   Without it, a later inspection could not explain the model's behavior.
 *
 * This script therefore does not assemble messages independently. It reconstructs the kernel's
 * `Unit` from database rows and calls **the kernel's own** `messagesOf`. A separate implementation
 * would measure this script's request rather than the original request.
 *
 * ## Two things are not stored in the database
 *
 * - **The task view for this iteration** (`view`): the kernel recomputes it each iteration rather
 *   than recording it as a message. Messages follow a single ancestor chain, which sibling
 *   branches cannot traverse, whereas the view is available to all branches. Its `secondsLeft`
 *   also depends on wall-clock time, so recomputing it later would not reproduce the original
 *   value. **Do not fabricate this missing view.**
 * - **Sampling parameters** (`maxTokens` / `temperature` / `seed` / `reasoningEffort`) live in
 *   `config.yaml`, not in the database.
 *
 * The reconstruction therefore includes **the message list and instructions**. These account
 * for almost all of the request size; the remaining fields are a few numbers.
 */

import { all, open } from "../src/H2H/db.ts";
import { tableNameOf } from "../src/install/index.ts";
import { instructionsOf, messagesOf, type Unit } from "../src/llm/index.ts";
import { sentAsIn } from "../src/msg/deliver.ts";
import { swapClosed, type Level, type Line } from "../src/msg/press.ts";

/** One row or none. `db.ts` only provides `all`. */
const one = (db: Parameters<typeof all>[0], sql: string, params?: Parameters<typeof all>[2]) =>
  (all(db, sql, params)[0] ?? null) as Record<string, unknown> | null;

const [file, instance, unitArg] = process.argv.slice(2);
if (!file || !instance || !unitArg) {
  console.error("bun scripts/request.ts <db> <instance> <unit> [--json] [--level l1|l2|l3|l4]");
  process.exit(1);
}
/**
 * **If the request was compressed, which level was used?** The engine log records it
 * (`… sent at l2 (…)`). No such entry means no compression.
 *
 * Replace nodes through the kernel's own `swapClosed`, not a second implementation here.
 * Otherwise the reconstruction would measure this script rather than the original request.
 */
const level = ((process.argv.find((a) => a.startsWith("--level")) ?? "").split("=")[1] ??
  (process.argv.includes("--level") ? process.argv[process.argv.indexOf("--level") + 1] : "")) as Level | "";
const want = Number(unitArg);

const store = open({ db: { file, pragmas: { journal_mode: "wal" } } } as never);
const db = store.ro;

/** Which subtable and task this instance belongs to. */
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

// ── Chain: follow `from` to the root, exactly as `#contextOf` does ──
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
  // **Select `unit` too.** `swapClosed` replaces complete units. Without this column,
  // rows cannot be assigned to a unit, so nothing is replaced and no error is reported.
  `select unit, seq, role, kind, body, thought from "${msgTable}"
    where instance = ? and unit in (${holes}) order by unit, seq`,
  [instance, ...line],
) as unknown as Unit["context"];

const context2 = level
  ? (swapClosed(db, { sub, task, unit: want }, context as unknown as Line[], line, level) as unknown as typeof context)
  : context;

// ── Tools offered in that iteration: recorded by the outbound accounting row ──
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
  // **Do not invent a view.** It is absent from the database; inventing one would change the request.
  tools,
  rules: kit.rules ?? [],
};

const messages = messagesOf(u);
const instructions = instructionsOf(u);

const bytes = (v: unknown) => Buffer.byteLength(JSON.stringify(v), "utf8");
const kb = (n: number) => `${(n / 1024).toFixed(0)}k`;

console.log(`${instance}  ${at.cycle}#${String(want)}  (${mode}, ${line.length} slots in chain)\n`);
console.log(`  Messages  ${String(messages.length).padStart(5)} items   ${kb(bytes(messages)).padStart(7)}  ≈${String(Math.round(bytes(messages) / 4 / 1000))}k tok`);
console.log(`  Instructions ${String(instructions.split("\n\n").length).padStart(5)} sections   ${kb(Buffer.byteLength(instructions, "utf8")).padStart(7)}`);
console.log(`  Tools     ${String(tools.length).padStart(5)} tools   ${kb(bytes(tools.map((t) => ({ name: t.name, does: t.does, params: t.params })))).padStart(7)}`);
console.log(`  Required call ${u.mustCall ?? "(model chooses)"}`);
console.log(`  Model     ${api ? `${String(api.model)} @ ${String(api.base_url)}` : "(no model at this station)"}`);

// Size by message category: identify the most worthwhile compression targets first.
const per = new Map<string, { n: number; b: number }>();
for (const r of context2) {
  const g = per.get(r.kind) ?? { n: 0, b: 0 };
  g.n++;
  g.b += Buffer.byteLength(String(r.body ?? ""), "utf8") + Buffer.byteLength(String(r.thought ?? ""), "utf8");
  per.set(r.kind, g);
}
console.log(`\n  By kind:`);
for (const [k, g] of [...per.entries()].sort((a, b) => b[1].b - a[1].b)) {
  console.log(`    ${k.padEnd(10)} ${String(g.n).padStart(5)} rows  ${kb(g.b).padStart(7)}`);
}
const think = context2.reduce((n, r) => n + Buffer.byteLength(String(r.thought ?? ""), "utf8"), 0);
const body = context2.reduce((n, r) => n + Buffer.byteLength(String(r.body ?? ""), "utf8"), 0);
console.log(`\n  Reasoning ${kb(think)} / body ${kb(body)} — reasoning accounts for ${String(Math.round((think / (think + body)) * 100))}%`);
console.log(`\n  Not stored in the database or reconstructed here: this round’s task view (computed each round, including wall-clock secondsLeft),`);
console.log(`  and sampling parameters from config.yaml.`);

if (process.argv.includes("--json")) {
  console.log(`\n${JSON.stringify({ instructions, messages }, null, 2)}`);
}

store.rw.close();
store.ro.close();
