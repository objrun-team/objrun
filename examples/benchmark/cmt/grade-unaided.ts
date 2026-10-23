/**
 * CMT U 臂事后判分：读取原始库中最后一次按时交卷的候选，用实时评分的同一张 G。
 *
 *   bun examples/benchmark/cmt/grade-unaided.ts <run> [db 路径]
 *
 * 原始 SQLite 以 readonly 打开；输出 runs/<run>/unaided.csv，保留原六列，
 * 追加 valid、outcome、error，区分答错、未交卷和执行/评分故障。
 */
import { Database } from "bun:sqlite";
import { mkdirSync, writeFileSync } from "node:fs";
import type { Conn } from "../../../app/src/H2H/db.ts";
import { graderFetch, Registry } from "../../../app/src/engine/registry.ts";
import { tableNameOf } from "../../../app/src/install/index.ts";
import { finalCandidate } from "../../../app/src/objective/candidate.ts";
import { candidateInput, evaluate } from "../../../app/src/objective/run.ts";
import { parseObjective } from "../../../app/src/objective/spec.ts";

const RUN = process.argv[2];
if (!RUN) {
  console.error("usage: bun grade-unaided.ts <run> [db]");
  process.exit(1);
}
const DB = process.argv[3] ?? process.env.TGENGIN_DB ?? "data/h2h.sqlite";
const GRADER = process.env.TGENGIN_CMT_GRADER ?? "http://127.0.0.1:7901";
const OUT = process.env.TGENGIN_OUT ?? `runs/${RUN}`;
const objective = parseObjective({
  nodes: [
    { name: "parsed", moment: "task_done", domain: "bool", handle: `${GRADER}/parsed` },
    { name: "equiv", moment: "task_done", domain: "bool", handle: `${GRADER}/equiv` },
  ],
  edges: [{ src: "parsed", out: 0, dst: "equiv" }],
  sink: "equiv",
  checks: 1,
});
const registry = new Registry();
for (const node of objective.nodes) registry.adopt(node.handle, 1_200_000, async arg => {
  const response = await graderFetch(node.handle, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(arg), signal: AbortSignal.timeout(1_200_000) });
  if (!response.ok) throw new Error(`${node.name}: grader HTTP ${response.status}`);
  return await response.json();
});

const db = new Database(DB, { readonly: true });
const readOnly: Conn = {
  all: (sql, params) => db.query(sql).all(...((params ?? []) as never[])) as Record<string, unknown>[],
  exec() { throw new Error("read-only grading"); },
  run() { throw new Error("read-only grading"); },
  close() {},
};
const tasks = db.query("select * from task where run = ? order by id").all(RUN) as Record<string, unknown>[];
if (!tasks.length) {
  db.close();
  console.error(`no tasks in run ${RUN}`);
  process.exit(1);
}

function stats(task: Record<string, unknown>): { seconds: number; units: number } {
  const sub = tableNameOf("task_{}", String(task.mode));
  const row = db.query(`select count(*) n,min(at) a,max(at) b from "${sub}" where task = ?`).get(String(task.id)) as { n: number; a: number | null; b: number | null };
  return { units: Number(row.n), seconds: row.a !== null && row.b !== null ? Math.round((Number(row.b) - Number(row.a)) / 1000) : 0 };
}

function generationFailure(task: Record<string, unknown>) {
  let prior: { valid?: unknown; outcome?: unknown; why?: unknown } | null = null;
  try { prior = JSON.parse(String(task.result ?? "null")); } catch { /* old runs may lack a stored verdict */ }
  const outcome = String(prior?.outcome ?? "");
  if (prior?.valid === false && ["provider_error", "grader_error", "finalization_pending", "finalization_error"].includes(outcome)) return { pass: 0, valid: false, outcome, why: String(prior.why ?? "generation did not finish successfully"), trace: [] };
  if (!["done", "failed"].includes(String(task.state))) return { pass: 0, valid: false, outcome: "finalization_pending", why: "generation has not finished", trace: [] };
  return undefined;
}

const csv = (value: unknown) => `"${String(value).replaceAll('"', '""')}"`;
const lines = ["task,submitted,parsed,equiv,seconds,units,valid,outcome,error"];
let pass = 0, nothing = 0, invalid = 0;
try {
  for (const task of tasks) {
    const id = String(task.id);
    const candidate = finalCandidate(readOnly, id);
    const st = stats(task);
    if (!candidate) nothing++;
    const verdict = generationFailure(task) ?? (!candidate
      ? { pass: 0, valid: false, outcome: "no_candidate", why: "nothing submitted", trace: [] }
      : await evaluate(objective, registry, candidateInput(task, candidate.body)));
    const values = Object.fromEntries(verdict.trace.map(node => [node.node, node.value === true]));
    if (verdict.valid && verdict.pass === 1) pass++;
    if (!verdict.valid && verdict.outcome !== "no_candidate") invalid++;
    const error = !verdict.valid && verdict.outcome !== "no_candidate" ? verdict.why : "";
    lines.push([id, candidate ? 1 : 0, values.parsed ? 1 : 0, values.equiv ? 1 : 0, st.seconds, st.units, verdict.valid ? 1 : 0, verdict.outcome, error].map(csv).join(","));
    console.log(`${id}: ${error ? `${verdict.outcome}: ${error}` : !candidate ? "nothing submitted" : verdict.pass === 1 ? "PASS" : values.parsed ? "parsed, not equivalent" : "not parsed"}`);
  }
} finally { db.close(); }
mkdirSync(OUT, { recursive: true });
writeFileSync(`${OUT}/unaided.csv`, lines.join("\n") + "\n");
console.log(`\n${RUN}: pass@1 = ${pass}/${tasks.length}  (nothing submitted: ${nothing}; invalid: ${invalid})  -> ${OUT}/unaided.csv`);
