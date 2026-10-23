import { readFileSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";
import { Pilot } from "./harness.ts";
const root = resolve(import.meta.dir, "../..");
const grader = "http://127.0.0.1:17930";
const rows = await (await fetch(`${grader}/problems`)).json() as { id: string; task: string; variation: number }[];
if (rows.length !== 10 || new Set(rows.map(r => r.id)).size !== 10) throw new Error("Expected the ten predeclared distinct ScienceWorld episodes");
const source = JSON.parse(readFileSync(join(root, ".phase1-data/scienceworld/source.json"), "utf8"));
const nodes = [{ name: "parsed", handle: `${grader}/parsed`, domain: "bool", moment: "task_done" }, { name: "passed", handle: `${grader}/passed`, domain: "bool", moment: "task_done" }];
const g = { nodes, edges: [{ src: "parsed", out: 0, dst: "passed" }], sink: "passed", checks: 2, reuse: "never" };
const probeId = `preflight/${rows[0].id}`;
await post("prepare", { id: rows[0].id, task: probeId });
for (const name of ["parsed", "passed"]) {
  const value = await post(name, { input: { task: { id: probeId, result: "" } } });
  if (value.value !== false) throw new Error(`${name} preflight failed; no model calls sent`);
}
const observation = await post("action", { instance: `${probeId}#1`, args: { action: "look around" } });
if (Object.keys(observation).length !== 1 || typeof observation.observation !== "string") throw new Error("Action tool exposed fields other than observation");
const accepted = await post("accept", { input: { task: { id: probeId, result: "" } } });
if (accepted.valid !== true || accepted.passed !== false || accepted.actions !== 1) throw new Error("Independent acceptance route preflight failed");
const p = await Pilot.start("scienceworld", nodes, { benchmark: "scienceworld", source, taskUnit: "full interactive episode", simplifications: "none", selectedEpisodes: rows, endpointChecks: "prepare/action/parsed/passed/accept tested over HTTP before any model call; action response is observation-only", preparationLimitDifference: "120s and 100 actions; canonical longer episodes not claimed", nativeRewardPolicy: "tool returns observation only; native score/reward/done/gold actions remain in supervisor and acceptance logs", taskSeconds: 120 }, { cycleMaxUnits: 32, taskSeconds: 120, tools: [{ name: "world_action", identity: `${grader}/action`, does: "Take one ScienceWorld simulator action and observe the result", params: { type: "object", properties: { action: { type: "string" } }, required: ["action"], additionalProperties: false }, output: { type: "object", properties: { observation: { type: "string" } } }, concurrent: false, system: true }] });
const acceptance = [];
try {
  for (const row of rows) {
    const prepared = await post("prepare", { id: row.id, task: `${p.run}/${row.id}` }) as { prompt: string; initialStateSha256: string };
    const result = await p.task(row.id, prepared.prompt, g);
    const final = await post("accept", { input: { task: { id: result.id, result: result.answer } } });
    if (typeof final.valid !== "boolean" || typeof final.passed !== "boolean") throw new Error("Invalid acceptance verdict; retain the run as diagnostic");
    acceptance.push({ id: row.id, initialStateSha256: prepared.initialStateSha256, final });
    writeFileSync(join(p.output, "acceptance.json"), JSON.stringify({ separation: "Read-only final simulator state inspected after episode generation; result never enters solver context", episodes: acceptance }, null, 2) + "\n");
  }
  p.stop(true);
} catch (error) { p.stop(false); throw error; }
console.log(JSON.stringify({ output: p.output, episodes: acceptance.length }));
process.exit(0);

async function post(route: string, body: unknown): Promise<Record<string, unknown>> {
  const response = await fetch(`${grader}/${route}`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify(body) });
  if (!response.ok) throw new Error(`${route} HTTP ${response.status}`);
  return await response.json() as Record<string, unknown>;
}
