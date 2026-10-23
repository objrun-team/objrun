import { readFileSync, readdirSync, lstatSync } from "node:fs";
import { join, dirname, resolve } from "node:path";
import { actualPin, demand, fileHash, verifyPin, type Pin } from "./paid-resource-proof-v2.ts";
import { requirePaidJpgGate, TASK_ID, PROTOCOL, OFFICIAL_HASHES, ARTIFACT, SECONDS, VERIFY_SECONDS, CHECKS } from "./skb-jpg-contract.ts";
export { TASK_ID, PROTOCOL, ARTIFACT, SECONDS, VERIFY_SECONDS, CHECKS };
export const JPG_FAMILY = "jpg-journal-v1", SOURCE_TASK_COUNT = 87, SUPPORTED_TASK_COUNT = 1, UNSUPPORTED_TASK_COUNT = 86;
export const JPG_IMAGE = "sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced";
export const JPG_FROZEN = {
  "campaign-journal.ts": "139a28eadf4fd570c04796430a419bfbba6ec0cc8d14eb28c2a4ef480cc90a56",
  "cny-cash-shadow-v2.ts": "6ad11d7b32b8aee895e620306107cd7864fd35c5413ab5aa3e13b8966338f334",
  "paid-resource-proof-v2.ts": "b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe",
  "software-jpg-private-grader.py": "fd3a65ed2ee692daa2797a8f014ce2722dff1b66aa1db6d88870e04caa7776da",
  "tb-engine.ts": "8f7cc23e55917f6f23dc20ff236ba21cbff180ed56b086573ecba93cb33b994e",
  "tb-tool-gateway.ts": "416d87f04fc91a71b2d337cdaeb89adb4594485c024da28bfb27060adcd236b2",
};
export const JPG_EXECUTION_FILES = ["skb-jpg-journal-campaign.ts", "jpg-paid-resource-admission-v1.ts", "audit-jpg-journal-campaign.py", "jpg-journal-contract.ts",
  "campaign-journal.ts", "scientific-journal-proxy.ts", "campaign-contract.ts", "audit-journal-canonical.ts", "cny-cash-shadow-v2.ts", "paid-resource-proof-v2.ts", "paid-resource-admission-v2.ts", "scientific-startup-proof.ts", "scientific-journal-plan.ts",
  "skb-jpg-contract.ts", "skb-jpg-stand.py", "skb-jpg-host-ops.py", "skb-jpg-audit.ts", "skb-jpg-native-python.ts", "skb-jpg-native-bootstrap.py", "skb-jpg-native-python.json", "software-jpg-private-grader.py", "software-jpg-build.py", "tb-engine.ts", "tb-tool-gateway.ts", "tb-nginx-contract.ts"].map(name => `scripts/benchmark-repair/${name}`);
export type JpgRecipe = { protocol: "jpg-journal-recipe-v1"; family: typeof JPG_FAMILY; runId: string; createdAtUtc: string; mode: "real-provider" | "local-mock";
  output: string; store: string; balance?: Pin; prices: Pin; deferredFault: Pin; originalPidClosure: Pin; requestedNewEnvelopeCny?: string; headroomCny: string;
  capUsd: number; priorCampaignCostUpperBoundUsd: number; sourcePins: Pin[]; artifacts: { name: string; pin: Pin }[];
  gates: { controls: Pin; image: Pin; build: Pin; profile: Pin }; publicDependencyArchive: Pin; approvedNativeProfile: Pin; readinessPlan: Pin;
  hostRuntime: { bun: Pin; bunVersion: string; python: Pin; distributionArchived: false };
  coldMockCertificate?: Pin; formalPaidReady: false; sourceTaskCount: 87; supportedTaskIds: [typeof TASK_ID]; unsupportedTaskCount: 86; taskSeconds: 1800; verifierSeconds: 600; checks: 6 };
export function validateJpgRecipe(r: JpgRecipe) {
  demand(r.protocol === "jpg-journal-recipe-v1" && r.family === JPG_FAMILY && /^repair-[0-9TZ-]+$/.test(r.runId), "jpg_recipe_scope");
  demand(["real-provider", "local-mock"].includes(r.mode) && r.formalPaidReady === false && r.sourceTaskCount === 87 && r.supportedTaskIds.length === 1 && r.supportedTaskIds[0] === TASK_ID && r.unsupportedTaskCount === 86, "jpg_recipe_denominator");
  demand(r.taskSeconds === SECONDS && r.verifierSeconds === VERIFY_SECONDS && r.checks === CHECKS && Number.isFinite(r.capUsd) && r.capUsd > r.priorCampaignCostUpperBoundUsd && r.priorCampaignCostUpperBoundUsd >= 0, "jpg_recipe_limits");
  demand(r.sourcePins.length > 0 && new Set(r.sourcePins.map(pin => resolve(pin.path))).size === r.sourcePins.length, "jpg_source_set");
  const expected=jpgSourceFiles(resolve(import.meta.dir,'../..'));
  demand(expected.length===r.sourcePins.length&&expected.every(p=>r.sourcePins.some(q=>resolve(p.path)===resolve(q.path)&&p.sha256===q.sha256&&p.bytes===q.bytes)),"jpg_complete_execution_source_set");
  demand(r.artifacts.every(row=>/^(runtime|grader-dependencies|official|gates)\//.test(row.name)&&!row.name.split(/[\\/]/).includes('..')&&!row.name.includes('\\'))&&new Set(r.artifacts.map(row=>row.name)).size===r.artifacts.length,"jpg_public_artifact_name_set");
  for (const pin of [...r.sourcePins, ...r.artifacts.map(row => row.pin), ...Object.values(r.gates), r.publicDependencyArchive, r.approvedNativeProfile, r.readinessPlan, r.prices, r.deferredFault, r.originalPidClosure]) verifyPin(pin);
  demand(r.hostRuntime.bunVersion===Bun.version&&resolve(r.hostRuntime.bun.path)===resolve(process.execPath)&&r.hostRuntime.distributionArchived===false,"jpg_host_runtime_scope");verifyPin(r.hostRuntime.bun);verifyPin(r.hostRuntime.python);
  const plan=JSON.parse(readFileSync(r.readinessPlan.path,'utf8'));
  demand(plan.protocol==='jpg-journal-paid-readiness-plan-v1'&&plan.sourceTaskCount===87&&plan.unsupportedTaskCount===86&&plan.imageId===JPG_IMAGE&&r.gates.controls.sha256===plan.gradingControls.sha256,"jpg_reviewed_readiness_profile");
  verifyPin(plan.nativeSourceFreeze);verifyPin(plan.nativeReview);
  const native=JSON.parse(readFileSync(plan.nativeSourceFreeze.path,'utf8')),root=resolve(import.meta.dir,'../..');
  for(const p of native.sources)verifyPin({path:join(root,p.path),bytes:p.bytes,sha256:p.sha256});
  demand(r.approvedNativeProfile.sha256===native.sources.find((p:any)=>p.path==='scripts/benchmark-repair/skb-jpg-native-python.json')?.sha256,"jpg_reviewed_native_profile");
  if (r.mode === "real-provider") demand(r.balance && r.requestedNewEnvelopeCny && r.headroomCny === "30", "jpg_explicit_cash_recipe");
}
export function jpgSourceFiles(root: string) {
  const walk = (path: string): string[] => readdirSync(path, { withFileTypes: true }).flatMap(row => row.isDirectory() ? walk(join(path, row.name)) : row.isFile() && /\.(ts|html)$/.test(row.name) ? [join(path, row.name)] : []);
  return [...new Set([...walk(join(root, "app/src")), ...JPG_EXECUTION_FILES.map(path => join(root, path)), ...["test/_lib.ts", "app/package.json", "app/bun.lock", "app/tsconfig.json"].map(path => join(root, path))])].sort().map(actualPin);
}
export function loadJpgGates(root: string, inputs: JpgRecipe["gates"]) {
  for (const [name, sha256] of Object.entries(JPG_FROZEN)) verifyPin({ path: join(root, "scripts/benchmark-repair", name), sha256 });
  const data = Object.fromEntries(Object.entries(inputs).map(([name, pin]) => { verifyPin(pin); return [name, JSON.parse(readFileSync(pin.path, "utf8"))]; }));
  requirePaidJpgGate({ ...data, graderSha: JPG_FROZEN["software-jpg-private-grader.py"] } as never);
  demand(data.image.imageId === JPG_IMAGE, "jpg_latest_image");
  for (const asset of data.profile.assets) {
    const path = resolve(dirname(inputs.profile.path), asset.path); demand(path.startsWith(resolve(dirname(inputs.profile.path)) + "\\") || path.startsWith(resolve(dirname(inputs.profile.path)) + "/"), "jpg_dependency_path");
    verifyPin({ path, sha256: asset.sha256 });
  }
  for (const [name, sha256] of Object.entries(OFFICIAL_HASHES)) verifyPin({ path: join(root, ".phase1-data/skillsbench/vendor/skillsbench/tasks", TASK_ID, name), sha256 });
  return data as { controls: any; image: any; build: any; profile: any };
}
export function assertJpgClosureShape(value: any, runId: string, providerKind: string) {
  demand(value.protocol === "jpg-journal-final-certificate-v1" && value.family === JPG_FAMILY && value.runId === runId && value.providerKind === providerKind, "jpg_certificate_family");
  demand(value.completed === (providerKind === "real-provider") && value.mockWorkflowCompleted === (providerKind === "local-mock") && value.formalScoreCertified === (providerKind === "real-provider"), "jpg_certificate_kind");
  demand(value.auditor && value.cash && value.source && value.owned && value.summary && value.journal && value.grading && value.secrets && value.raw, "jpg_certificate_graph_missing");
}
export function ordinaryNewJpgStore(path: string, allowedRoot: string) {
  demand(resolve(path).startsWith(resolve(allowedRoot) + "\\") || resolve(path).startsWith(resolve(allowedRoot) + "/"), "jpg_store_scope");
  if (lstatSync(path).isSymbolicLink()) throw new Error("jpg_store_must_be_physical");
}
export function jpgAssetPin(path: string) { return { path: resolve(path), bytes: readFileSync(path).length, sha256: fileHash(path) }; }
