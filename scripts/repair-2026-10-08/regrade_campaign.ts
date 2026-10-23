import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { Database } from "bun:sqlite";
import { finalCandidate } from "../../app/src/objective/candidate.ts";
import { campaignComplete, classifyGeneration, gradeFixedCandidate } from "./campaign-contract.ts";

const root = resolve(import.meta.dir, "../..");
const name = process.argv[2];
if (!name || !/^repair-[0-9TZ-]+$/.test(name)) throw new Error("Pass a campaign directory name");
const directory = join(root, "docs/repair-2026-10-08/campaigns", name);
const sha = (raw: string | Buffer) => createHash("sha256").update(raw).digest("hex");
const read = (file: string) => JSON.parse(readFileSync(join(directory, file), "utf8"));
const manifest = read("manifest.json"), summary = read("summary.json"), source = read("source.json");
const ports: Record<string, number> = { gpqa: 17903, cmt: 17901, aime: 17905, chembench: 17906, chemiq: 17917 };
const graded: Record<string, unknown>[] = [];
const inputs = ["manifest.json", "summary.json", "source.json", "api-ledger.json", ...summary.records.map((r: {index: number}) => `task-${r.index}.json`)];
const baseInputs = inputs.map(path => ({ path, sha256: sha(readFileSync(join(directory, path))) }));
const usedGraders = manifest.benchmarks.map((slug: string) => `examples/benchmark/${slug}/${slug === "cmt" ? "grader.py" : "stand.py"}`);
for (const file of source.files.filter((f: {path: string}) => f.path.startsWith("app/src/") || f.path === "test/_lib.ts" || usedGraders.includes(f.path))) {
  if (sha(readFileSync(join(root, file.path))) !== file.sha256) throw new Error(`Original execution core/grader changed: ${file.path}`);
}
for (const original of summary.records) {
  const taskArtifact = read(`task-${original.index}.json`);
  const db = new Database(join(root, ".phase1-data/repair", name, `worker-${original.worker}/data/h2h.sqlite`), { readonly: true });
  let candidate: { body: string; how: string } | undefined;
  let task: Record<string, unknown>;
  try {
    task = db.query("select * from task where id = ?").get(original.taskId) as Record<string, unknown>;
    candidate = finalCandidate({ all: (sql: string, params?: unknown[]) => db.query(sql).all(...((params ?? []) as never[])), run() { throw new Error("read-only candidate check"); }, exec() { throw new Error("read-only candidate check"); }, close() {} } as never, original.taskId);
  } finally { db.close(); }
  if (!task! || sha(candidate?.body ?? "") !== original.candidateSha256 || (candidate?.how ?? "none") !== original.candidateHow) throw new Error(`Fixed candidate changed: ${original.index}`);
  const generation = classifyGeneration({ runtimeVerdict: original.runtimeVerdict, state: original.state, calls: original.apiCalls, trace: taskArtifact.trace, candidate: candidate?.body });
  const second = original.benchmark === "cmt" ? "equiv" : "correct";
  const objective = { nodes: [{ name: "parsed", domain: "bool", moment: "done", handle: `http://127.0.0.1:${ports[original.benchmark]}/parsed` }, { name: second, domain: "bool", moment: "done", handle: `http://127.0.0.1:${ports[original.benchmark]}/${second}` }], edges: [{ src: "parsed", out: 0, dst: second }], sink: second, checks: 5, reuse: "text" };
  const acceptance = await gradeFixedCandidate({ objective, task: task!, candidate: candidate?.body, generation, expectedCandidateSha256: original.candidateSha256 });
  graded.push({ ...original, originalAcceptance: original.acceptance, generationValid: generation.valid, generationClassification: generation, acceptance,
    actualCreatedAt: task!.created_at, actualDeadline: Number(task!.created_at) + Number(task!.solve_seconds) * 1000 });
}
for (const file of baseInputs) if (sha(readFileSync(join(directory, file.path))) !== file.sha256) throw new Error(`Original artifact modified: ${file.path}`);
const result = { schemaVersion: 1, campaign: name, gradedAt: new Date().toISOString(), llmCalls: 0, originalFilesUnchanged: true, baseInputs,
  acceptanceContract: { path: "scripts/repair-2026-10-08/campaign-contract.ts", sha256: sha(readFileSync(join(import.meta.dir, "campaign-contract.ts"))) },
  regradeScriptSha256: sha(readFileSync(new URL(import.meta.url))), sourceExecutionDigest: source.executionDigest,
  completed: campaignComplete(summary.plannedTaskRuns, graded as {index: unknown; acceptance?: {valid?: unknown; passed?: unknown; outcome?: unknown}}[]),
  plannedTaskRuns: summary.plannedTaskRuns, recordedTaskRuns: graded.length, records: graded,
  limits: ["This verifies the fixed candidate and all grader validity flags, not an extra model attempt or a selected better answer.", "Schema1 pilot receipts predate raw-response capture; actual successful SDK traces and usage are retained, but the later completion guard cannot be certified retroactively."] };
writeFileSync(join(directory, "contract-regrade.json"), JSON.stringify(result, null, 2) + "\n");
console.log(JSON.stringify({ campaign: name, completed: result.completed, tasks: graded.length, passed: graded.filter(r => (r.acceptance as {passed?:boolean}).passed).length, invalid: graded.filter(r => !(r.acceptance as {valid?:boolean}).valid).length, llmCalls: 0, originalFilesUnchanged: true }));
process.exitCode = result.completed ? 0 : 1;
