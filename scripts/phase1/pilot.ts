import { readFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { Pilot } from "./harness.ts";

const root = resolve(import.meta.dir, "../..");
const slug = process.argv[2] ?? "gpqa";
const count = Number(process.argv[3] ?? 10);
const ports: Record<string, number> = { gpqa: 17903, cmt: 17901, aime: 17905, chembench: 17906, chemiq: 17907, "atmossci-bench": 17924, "lab-bench": 17925, "humaneval-plus": 17926, "atomworld": 17927, "biocoder": 17928, "llm-srbench": 17929 };
if (!(slug in ports) || !Number.isInteger(count) || count < 1 || count > 20) throw new Error("Select a supported text benchmark and 1–20 official tasks");
const grader = process.env.TGENGIN_BENCH_GRADER ?? `http://127.0.0.1:${ports[slug]}`;
const second = slug === "cmt" ? "equiv" : "correct";
const nodes = [{ name: "parsed", handle: `${grader}/parsed`, domain: "bool", moment: "task_done" }, { name: second, handle: `${grader}/${second}`, domain: "bool", moment: "task_done" }];
const g = { nodes, edges: [{ src: "parsed", out: 0, dst: second }], sink: second, checks: 2, reuse: "text" };
const source = JSON.parse(readFileSync(join(root, `.phase1-data/${slug}/source.json`), "utf8"));
const response = await fetch(`${grader}/problems?n=${count}`);
if (!response.ok) throw new Error(`Problem service HTTP ${response.status}`);
const rows = await response.json() as Record<string, unknown>[];
if (rows.length !== count) throw new Error(`Requested ${count} official tasks but received ${rows.length}`);
const firstId = String(rows[0].id ?? `${slug}-${rows[0].index ?? 0}`);
const endpointChecks = [];
for (const node of nodes) {
  const probe = await fetch(node.handle, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ input: { task: { id: `preflight/${firstId}`, result: "" } } }) });
  if (!probe.ok) throw new Error(`${node.name} preflight HTTP ${probe.status}; no model calls sent`);
  const data = await probe.json();
  const value = typeof data === "object" && data !== null ? (data as { value?: unknown }).value : data;
  if (value !== false) throw new Error(`${node.name} did not reject an empty candidate with a valid boolean`);
  endpointChecks.push({ node: node.name, httpStatus: probe.status, namespacedEmptyCandidateRejected: true });
}
const protocol = slug === "lab-bench" ? { subset: "public ProtocolQA", choiceSeed: 0, imageInput: "Text-only subset; full image categories pending a vision provider", abstention: "official uncertainty option preserved; exact single-letter grading" } : slug === "atmossci-bench" ? { subset: "MCQ10", openEndedStatus: "pending separate validation", taskFamilySelection: "first ten official rows; small pilot does not measure family generalization" } : slug === "llm-srbench" ? { subset: "public author-release LSR-Transform", visibleData: "first 30 official training examples per task", feedbackData: "remaining training points", finalData: "all test points, only evaluated after generation", threshold: "official NMSE <= 0.01 with finite predictions for all points", canonicalProtocolDifference: "Preparation model sees a 30-example text view; no fitting/execution tools. Full discovery-protocol efficacy is not claimed." } : slug === "biocoder" ? { subset: "official BioCoder Rosalind", positiveControl: "Known-correct output replay; not claimed as an official reference implementation", deferredProtocol: "GitHub Python/Java fuzz/container queue not run" } : slug === "atomworld" ? { subset: "official bench/AddAtomAction", structureTolerance: "official defaults; stol=0.5, primitive_cell=false" } : {};
const p = await Pilot.start(slug, nodes, { benchmark: slug, source, ...protocol, endpointChecks, selectedTaskIds: rows.map((row, i) => String(row.id ?? `${slug}-${row.index ?? i}`)), taskSelection: "first N official tasks in grader order, fixed before generation", historicalModelDifference: "Old V4-Flash-0731/OpenRouter runs are not reproduced by this preparation model", taskSeconds: 300 });
try {
  for (const [index, row] of rows.entries()) {
    const officialId = String(row.id ?? `${slug}-${row.index ?? index}`);
    const choices = row.choices as Record<string, string> | undefined;
    const prompt = String(row.prompt ?? row.problem ?? row.question ?? "") + (choices ? "\n\n" + Object.entries(choices).map(([key, value]) => `${key}. ${value}`).join("\n") : "") + (slug === "cmt" ? `\nParameters: ${row.parameters ?? ""}\nFunctions: ${row.functions ?? ""}` : "");
    const suffix = slug === "gpqa" ? "\nEnd with exactly 'The correct answer is (X)', where X is A, B, C or D. Include the parentheses and submit that exact answer." : ["cmt", "aime"].includes(slug) ? "\nPut the final mathematical answer inside \\boxed{...}. Submit that exact answer." : "";
    await p.task(officialId, prompt + suffix, g);
  }
  p.stop(true);
} catch (error) { p.stop(false); throw error; }
console.log(JSON.stringify({ output: p.output, tasks: p.results.length }));
process.exit(0);
