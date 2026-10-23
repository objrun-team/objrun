import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, join } from "node:path";
import { Pilot } from "./harness.ts";

const root = resolve(import.meta.dir, "../..");
const grader = "http://127.0.0.1:17921";
const count = Number(process.argv[2] ?? 10);
if (!Number.isInteger(count) || count < 1 || count > 10) throw new Error("Select 1–10 fixed whole SciCode problems");
const health = await (await fetch(`${grader}/health`)).json() as { pilotIds: string[] };
const ids = health.pilotIds.slice(0, count);
const nodes = [{ name: "parsed", handle: `${grader}/parsed`, domain: "bool", moment: "task_done" }, { name: "passed", handle: `${grader}/passed`, domain: "bool", moment: "task_done" }];
const g = { nodes, edges: [{ src: "parsed", out: 0, dst: "passed" }], sink: "passed", checks: 2, reuse: "text" };
const source = JSON.parse(readFileSync(join(root, ".phase1-data/scicode-verified/source.json"), "utf8"));
const targets = JSON.parse(readFileSync(join(root, ".phase1-data/scicode-verified/test_data_cleaned.source.json"), "utf8"));
const p = await Pilot.start("scicode-verified", nodes, { benchmarkFamily: "SciCode", variant: "SciCode-Verified v2", source, targets, pilotProblemIds: ids, selectionRule: "first ten release-order problems excluding the class/preprovided-helper-dependent problem 13; fixed before model generation", withBackground: true, previousCode: "all previous actual model hand-ins; no reference code", scoringEnvironment: "Python3.12/numpy1.26.4/scipy1.14.1", gradingSeconds: 90, canonicalProtocolDifference: "Single scientific-Python environment and a preparation grading timeout of90s; canonical multi-environment OR/1800s scores are not claimed", originalSciCodeStatus: "official Google Drive numeric-target download quota exceeded" });
const problems = await (await fetch(`${grader}/problems`)).json() as { id: string; steps: number }[];
const whole: Record<string, unknown>[] = [];
const pending: { problem: { id: string; steps: number }; codes: string[]; stepResults: Record<string, unknown>[] }[] = [];
const sha = (text: string) => createHash("sha256").update(text).digest("hex");
try {
  for (const problem of problems.filter(problem => ids.includes(problem.id))) {
    const codes: string[] = [];
    const stepResults: Record<string, unknown>[] = [];
    for (let step = 0; step < problem.steps; step++) {
      const officialId = `scicode-${problem.id}.${step + 1}`;
      const prepared = await (await fetch(`${grader}/prepare`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ problem: problem.id, step, previous: codes, task: `${p.run}/${officialId}` }) })).json() as { prompt: string };
      const result = await p.task(officialId, prepared.prompt, g);
      const match = /```(?:python)?\s*\n([\s\S]*?)```/.exec(result.answer);
      codes.push((match?.[1] ?? result.answer).trim());
      stepResults.push(result);
    }
    pending.push({ problem, codes, stepResults });
  }
  // Finish all model generation before final acceptance. Final verdicts never
  // determine candidate selection, revision, or generation stopping.
  for (const { problem, codes, stepResults } of pending) {
    const acceptance = await (await fetch(`${grader}/accept`, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ problem: problem.id, codes }) })).json() as { valid?: boolean; passed?: boolean; candidateCodeSha256?: string[]; cumulativeCodeSha256?: string };
    const identities = stepResults.map((result, i) => {
      if (typeof result.answer !== "string") throw new Error("Missing delivered candidate");
      return { officialId: result.officialId, answerSha256: sha(result.answer), extractedCodeSha256: sha(codes[i]!) };
    });
    if (acceptance.valid === true && (acceptance.candidateCodeSha256?.length !== codes.length || codes.some((code, i) => acceptance.candidateCodeSha256?.[i] !== sha(code)))) {
      throw new Error("Acceptance candidate identity mismatch");
    }
    whole.push({ problem: problem.id, substeps: problem.steps, candidateIdentities: identities, cumulativeCodeSha256: acceptance.cumulativeCodeSha256, processAllPassed: stepResults.every(r => r.state === "done"), finalAcceptance: acceptance });
    writeFileSync(join(p.output, "whole-problems.json"), JSON.stringify({ variant: "SciCode-Verified v2", taskUnit: "whole problem", completedProblems: whole.length, results: whole }, null, 2) + "\n");
  }
  p.stop(true);
} catch (error) { p.stop(false); throw error; }
console.log(JSON.stringify({ output: p.output, wholeProblems: whole.length }));
process.exit(0);
