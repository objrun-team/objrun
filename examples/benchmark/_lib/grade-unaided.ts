/**
 * 通用 U 臂事后判分：每道题最后一次 `submit` 的答案 → 问判卷台的每个节点（按 G.json 的边从源到 sink）。
 *
 *   cd app && TGENGIN_BENCH_DIR=... bun ../examples/benchmark/_lib/grade-unaided.ts <run> <db 路径>
 * 输出 $TGENGIN_OUT/unaided.csv：task,submitted,<node1>,<node2>,...,seconds,units
 */
import { Database } from "bun:sqlite";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import { finalCandidate } from "../../../app/src/objective/candidate.ts";
import type { Conn } from "../../../app/src/H2H/db.ts";
import { graderFetch, Registry } from "../../../app/src/engine/registry.ts";
import { candidateInput, evaluate } from "../../../app/src/objective/run.ts";
import { parseObjective } from "../../../app/src/objective/spec.ts";

const RUN = process.argv[2];
const DB = process.argv[3];
const DIR = process.env.TGENGIN_BENCH_DIR;
if (!RUN || !DB || !DIR) {
  console.error("usage: TGENGIN_BENCH_DIR=... bun grade-unaided.ts <run> <db>");
  process.exit(1);
}
const G = JSON.parse(readFileSync(`${DIR}/G.json`, "utf8")) as { grader_port: number; nodes: { name: string; moment: string; domain: unknown; handle: string }[]; edges: { src: string; out: number; dst: string }[]; sink: string; checks?: number };
const GRADER = process.env.TGENGIN_BENCH_GRADER ?? `http://127.0.0.1:${G.grader_port}`;
const OUT = process.env.TGENGIN_OUT ?? `runs/${RUN}`;
// Use the same graph, output contracts, fault semantics and candidate shape as live grading.
const objective = parseObjective({ ...G, checks: G.checks ?? 1, nodes: G.nodes.map(node => ({ ...node, handle: node.handle.replaceAll("{GRADER}", GRADER) })) });
const order = objective.nodes.map(node => node.name);
const registry = new Registry();
for (const node of objective.nodes) registry.adopt(node.handle, 1_200_000, async arg => {
  const response = await graderFetch(node.handle, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(arg), signal: AbortSignal.timeout(1_200_000) });
  if (!response.ok) throw new Error(`${node.name}: grader HTTP ${response.status}`);
  return await response.json();
});

const db = new Database(DB, { readonly: true });
const tasks = db.query(`select id from task where run = ? order by id`).all(RUN) as { id: string }[];

function submitted(task: string): string | null {
  const readOnly: Conn = { all: (sql, params) => db.query(sql).all(...((params ?? []) as never[])) as Record<string, unknown>[], exec() { throw new Error("read-only grading"); }, run() { throw new Error("read-only grading"); }, close() {} };
  return finalCandidate(readOnly, task)?.body ?? null;
}
function stats(task: string) {
  const mode = String((db.query(`select mode from task where id = ?`).get(task) as { mode: string }).mode);
  if (!/^[a-zA-Z_][a-zA-Z0-9_]*$/.test(mode)) throw new Error("Invalid task mode identifier");
  const r = db.query(`select count(*) n, min(at) a, max(at) b from "task_${mode}" where task = ?`).get(task) as { n: number; a: number | null; b: number | null };
  return { units: Number(r.n), seconds: r.a && r.b ? Math.round((Number(r.b) - Number(r.a)) / 1000) : 0 };
}
// 并发判分：Lean 这类判卷台一次几十秒、后面有 REPL 池，串行问会把池子闲着。TGENGIN_GRADE_PAR 定并发（默认 16）。
const PAR = Number(process.env.TGENGIN_GRADE_PAR ?? 16);
const rowsOut: Map<string, string> = new Map();
let pass = 0, nothing = 0;
async function gradeOne(t: { id: string }) {
  const said = submitted(t.id);
  const st = stats(t.id);
  if (said === null) nothing++;
  const task = db.query("select * from task where id = ?").get(t.id) as Record<string, unknown>;
  let generationFailure: { pass: number; valid: boolean; outcome: string; why: string; trace: { node: string; value: unknown }[] } | undefined;
  try {
    const prior = JSON.parse(String(task.result ?? "null")) as { valid?: unknown; outcome?: string; why?: unknown } | null;
    if (prior?.valid === false && ["provider_error", "finalization_pending", "finalization_error"].includes(String(prior.outcome))) {
      generationFailure = { pass: 0, valid: false, outcome: String(prior.outcome), why: String(prior.why ?? "generation did not finish successfully"), trace: [] };
    }
  } catch { /* a missing stored receipt does not manufacture a fault */ }
  const verdict = generationFailure ?? (said === null
    ? { pass: 0, valid: false, outcome: "no_candidate", why: "nothing submitted", trace: [] }
    : await evaluate(objective, registry, candidateInput(task, said)));
  const res = Object.fromEntries(verdict.trace.map(node => [node.node, node.value === true]));
  const { valid, outcome } = verdict;
  const error = !valid && outcome !== "no_candidate" ? verdict.why : "";
  if (valid && verdict.pass === 1) pass++;
  const csv = (value: unknown) => `"${String(value).replaceAll('"', '""')}"`;
  rowsOut.set(t.id, [t.id, said === null ? 0 : 1, ...order.map((n) => (res[n] ? 1 : 0)), st.seconds, st.units, valid ? 1 : 0, outcome, error].map(csv).join(","));
  console.log(`${t.id}: ${error ? outcome + ": " + error : said === null ? "nothing submitted" : verdict.pass === 1 ? "PASS" : "rejected (" + order.map((n) => n + "=" + (res[n] ? 1 : 0)).join(" ") + ")"}`);
}
{
  let i = 0;
  const workers = Array.from({ length: Math.min(PAR, tasks.length) }, async () => {
    while (i < tasks.length) { const t = tasks[i++]; await gradeOne(t); }
  });
  await Promise.all(workers);
}
const lines = [["task", "submitted", ...order, "seconds", "units", "valid", "outcome", "error"].join(","), ...tasks.map((t) => rowsOut.get(t.id)!)];
mkdirSync(OUT, { recursive: true });
writeFileSync(`${OUT}/unaided.csv`, lines.join("\n") + "\n");
console.log(`\n${RUN}: pass@1 = ${pass}/${tasks.length}  (nothing submitted: ${nothing})  -> ${OUT}/unaided.csv`);
