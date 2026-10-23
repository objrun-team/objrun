import { classifyGeneration, type ApiReceipt, type GenerationClassification } from "./campaign-contract.ts";

export const TASK_ID = "nginx-request-logging";
export const IMAGE_ID = "sha256:41217bae6667f04a767dc1b2c5c12b034dfc51a18226202003313aaf86832055";
export const PROTOCOL = "tb-live-nginx-io-v1";
export const PRESEEDED_PROTOCOL = "tb-live-nginx-io-v2-preseed";
export const SIX_TOOLS = ["bash", "read", "write", "edit", "glob", "grep"] as const;
export const OFFICIAL_HASHES = {
  "task.toml": "b7a78d00be13656f75069197100b7b8c4fd268decf6f78929c853b3222a2729d",
  "tests/test.sh": "27761195f53cbfe5941fe39b573631f6c926869e64b7c43220377e1e116528e7",
  "tests/test_outputs.py": "045cc716c14efde3b0dcff5fc7c85ec5d18bfc6ce66f8b40a418fa2a3a4acda0",
};

export function requireSafeHealth(health: Record<string, unknown>) {
  const ids = health.supportedTaskIds as unknown[] | undefined, tools = health.supportedTools as string[] | undefined;
  if (health.isolationReady !== true || health.authenticated !== true || health.unsafeDiagnostic !== false || health.runtimeReady !== true || health.backend !== "docker" || ![PROTOCOL,PRESEEDED_PROTOCOL].includes(String(health.protocol)) || health.maxLiveCandidates !== 1 || health.graders !== 1 || health.tasks !== 89 || health.unsupportedTaskCount !== 88 || health.level !== 2 || ids?.length !== 1 || ids[0] !== TASK_ID || tools?.length !== SIX_TOOLS.length || SIX_TOOLS.some(tool => !tools.includes(tool))) throw new Error("Only the audited one-task authenticated nginx stand may run this protocol");
}
export function nginxObjective(stand: string) {
  return { nodes: [{ name: "ran", domain: "bool", moment: "done", handle: `${stand}/ran` }, { name: "passed", domain: "bool", moment: "done", handle: `${stand}/passed` }], edges: [{ src: "ran", out: 0, dst: "passed" }], sink: "passed", checks: 4, reuse: "never" };
}
export function requireNginxPreflight(proof: Record<string, any>, hashes: Record<string,string>, runtimeSha: string) {
  if (proof.validated !== true || proof.officialGradingValid !== true || ![PROTOCOL,PRESEEDED_PROTOCOL].includes(proof.protocol) || proof.imageId !== IMAGE_ID || !proof.dependencyProfile || proof.runtimeManifestSha256 !== runtimeSha) throw new Error("TB paid run requires current valid empty/oracle grading and a frozen dependency profile");
  for (const [path, expected] of Object.entries(hashes)) if (proof.sourceHashes?.[path] !== expected) throw new Error("TB preflight does not match current grader source: " + path);
  for (const [phase, reward] of [["empty",0],["oracle",1]] as const) {
    const control = proof.phases?.[phase];
    if (control?.valid !== true || control.ran !== true || control.reward !== reward || control.completedTests !== 8) throw new Error("TB preflight official control is incomplete: " + phase);
  }
}
export function nginxGeneration(input: { runtimeVerdict: unknown; state: string; calls: ApiReceipt[]; trace: { role?: unknown; kind?: unknown; body?: unknown; at?: unknown }[]; candidate?: string; deadline: number }): GenerationClassification {
  const classified = classifyGeneration(input);
  if (!classified.valid) return classified;
  const late = input.trace.some(row => {
    if (row.kind !== "tool" || Number(row.at) <= input.deadline) return false;
    try { return ["bash", "write", "edit"].includes(JSON.parse(String(row.body)).name); } catch { return false; }
  });
  if (late) return { ...classified, kind: "experimental_failure", outcome: "budget_exhausted", why: "a live-state mutation finished after the declared deadline; its state cannot earn a pass" };
  return classified;
}
export function mockCall(index: number, arm: string) {
  const actions = [
    { name: "bash", args: { command: "printf 'before\\n' > /app/objrun-smoke.txt", timeout_ms: 10000 } },
    { name: "read", args: { file_path: "/app/objrun-smoke.txt" } },
    { name: "write", args: { file_path: "/app/objrun-smoke.txt", content: "written\n" } },
    { name: "edit", args: { file_path: "/app/objrun-smoke.txt", old_string: "written", new_string: "edited" } },
    { name: "glob", args: { pattern: "objrun-smoke.txt", path: "/app" } },
    { name: "grep", args: { pattern: "edited", path: "/app/objrun-smoke.txt" } },
    ...(arm === "F" ? [{ name: "verify", args: { answer: "smoke-final" } }] : []),
    { name: "submit", args: { answer: "smoke-final" } },
  ];
  return actions[Math.min(index, actions.length - 1)]!;
}
