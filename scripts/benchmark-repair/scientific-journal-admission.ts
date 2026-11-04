import { openRouterScientificAdmission } from "./openrouter-scientific-admission.ts";
/** Explicit production binding. This module never queries balance/pricing or invokes a model. */
import { closeSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, statSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { dirname, join, resolve } from "node:path";
import { freemem } from "node:os";
import { acquirePaidResourceAdmissionV2, RESOURCE_MODE, type AdmissionLease, type ReleaseInput } from "./paid-resource-admission-v2.ts";
import { createCnyCashShadow, verifyCashClosure, type CashTicket } from "./cny-cash-shadow-v2.ts";
import { actualPin, verifyPin, type Pin } from "./paid-resource-proof-v2.ts";
import { inspectCampaignJournal } from "./campaign-journal.ts";
import { scientificWorkerResources } from "./scientific-journal-resources.ts";
import { requestedWorkers } from "./campaign-workers.ts";
import { SCIENTIFIC_STORE_SETUP_SHA, validateScientificStore } from "./scientific-journal-storage.ts";
import type { ScientificPaidAdmission } from "./scientific-journal-campaign.ts";

const root = resolve(import.meta.dir, "../.."), python = join(root, ".phase1-data/venv/Scripts/python.exe");
// PowerShell 7's inherited module path can hide Windows PowerShell's native Get-FileHash/JSON cmdlets.
function windowsPowerShellEnv() {
  const env = { ...process.env }; for (const key of Object.keys(env)) if (key.toLowerCase() === "psmodulepath") delete env[key];
  env.PSModulePath = join(process.env.SystemRoot ?? "C:/Windows", "System32/WindowsPowerShell/v1.0/Modules"); return env;
}
const fixed = {
  "paid-resource-admission-v2.ts": "0b752576bd37235140a7b97dafee16741ebaadd9cafda3370e20317d9fdddb0e",
  "cny-cash-shadow-v2.ts": "6ad11d7b32b8aee895e620306107cd7864fd35c5413ab5aa3e13b8966338f334",
  "paid-resource-proof-v2.ts": "b1bacd465d2a76ca166e8048ac8ee83f152f6b9f21600770b39ec6a9864813fe",
  "campaign-journal.ts": "139a28eadf4fd570c04796430a419bfbba6ec0cc8d14eb28c2a4ef480cc90a56",
  "prepare-scientific-journal-store.ps1": SCIENTIFIC_STORE_SETUP_SHA,
};
function save(path: string, value: unknown, exclusive = true) {
  mkdirSync(dirname(path), { recursive: true }); const fd = openSync(path, exclusive ? "wx" : "w", 0o600);
  try { writeFileSync(fd, JSON.stringify(value, null, 2) + "\n"); fsyncSync(fd); } finally { closeSync(fd); } return actualPin(path);
}
function walk(path: string): string[] { return readdirSync(path, { withFileTypes: true }).flatMap(item => item.isDirectory() ? walk(join(path, item.name)) : item.isFile() ? [join(path, item.name)] : []); }
function verifyFixed() { for (const [name, sha256] of Object.entries(fixed)) verifyPin({ path: join(import.meta.dir, name), sha256 }); }
export type ScientificRecipe = {
  protocol: "scientific-journal-paid-recipe-v1"; runId: string; profile: "full"; benchmarks: ["chembench", "aime", "cmt"];
  createdAt: string; requestedNewEnvelopeCny: "250"; minimumHeadroomCny: "30"; capUsd: 130; priorCampaignCostUpperBoundUsd: 47.531307588;
  balance: Pin; prices: Pin; deferredFault: Pin; originalPidClosure: Pin; executedSourcePins: Pin[]; inspectPlan: Pin;
  workers: ReturnType<typeof scientificWorkerResources>; taskScheduleSha256: string; modelForwardedByRecipePreparation: false;
};
/** F-only: actual pins, source recipe and D read-only Inspect. Caller supplies a genuine fresh GET-only balance receipt. */
export function prepareScientificRecipe(balanceFile: string, executionFiles: readonly string[], runId = `repair-${new Date().toISOString().replace(/[:.]/g, "-")}`) {
  verifyFixed();
  if (!/^repair-[0-9TZ-]+$/.test(runId)) throw new Error("Invalid prospective run identity");
  const balance = actualPin(resolve(balanceFile));
  const value = JSON.parse(readFileSync(balance.path, "utf8"));
  if (value.protocol !== "deepseek-resource-readonly-v1" || value.modelCalls !== 0 || value.httpStatus !== 200 || value.credentialPrinted !== false || Date.now() - Date.parse(value.observedAtUtc) > 30 * 60000 || Date.now() < Date.parse(value.observedAtUtc)) throw new Error("Supply a genuine actual fresh30min GET-only balance receipt");
  const names = [...walk(join(root, "app/src")).filter(path => /\.(ts|html)$/.test(path)), ...["test/_lib.ts", "app/package.json", "app/bun.lock", "app/tsconfig.json", "examples/benchmark/_lib/gradelib.py",
    "examples/benchmark/chembench/stand.py", "examples/benchmark/aime/stand.py", "examples/benchmark/cmt/grader.py", ...executionFiles,
    ...["scientific-journal-admission.ts", ...Object.keys(fixed), "paid-campaign-lock.ts"].map(name => `scripts/benchmark-repair/${name}`)].map(path => join(root, path))];
  const executedSourcePins = [...new Set(names)].sort().map(actualPin);
  const workers = scientificWorkerResources({ requested: requestedWorkers(process.env.OBJRUN_REPAIR_WORKERS), freeMemoryBytes: freemem() });
  execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", join(import.meta.dir, "prepare-scientific-journal-store.ps1"), "-Mode", "Inspect", "-RunId", runId], { windowsHide: true, timeout: 20000, env: windowsPowerShellEnv() });
  const inspectPlan = actualPin(join(root, "docs/repair-2026-10-08/storage-preparations", runId, "plan.json"));
  const recipe: ScientificRecipe = { protocol: "scientific-journal-paid-recipe-v1", runId, profile: "full", benchmarks: ["chembench", "aime", "cmt"], createdAt: new Date().toISOString(),
    requestedNewEnvelopeCny: "250", minimumHeadroomCny: "30", capUsd: 130, priorCampaignCostUpperBoundUsd: 47.531307588,
    balance, prices: actualPin(join(root, "test/fixtures/repair/deepseek-cny-price-readonly.json")), deferredFault: actualPin(join(root, "test/fixtures/repair/scientific-campaign-deferred-fault.json")),
    originalPidClosure: actualPin(join(root, "test/fixtures/repair/science1220-oom-original-process-closure.json")), executedSourcePins, inspectPlan, workers,
    taskScheduleSha256: "1ae6590140a51e9c48c656e92e482dd684843f8ae0e1dfc4e8f8ebad0e738bf8", modelForwardedByRecipePreparation: false };
  return save(join(root, "docs/repair-2026-10-08/scientific-journal-recipes", runId, "recipe.json"), recipe);
}
export function scientificPaidAdmission(recipeFile: string): ScientificPaidAdmission {
  if(JSON.parse(readFileSync(recipeFile,"utf8")).protocol==="openrouter-scientific-recipe-v1")return openRouterScientificAdmission(recipeFile);
  verifyFixed(); const recipePin = actualPin(resolve(recipeFile)), recipe = JSON.parse(readFileSync(recipePin.path, "utf8")) as ScientificRecipe;
  if (recipe.protocol !== "scientific-journal-paid-recipe-v1" || recipe.profile !== "full" || recipe.benchmarks.join(",") !== "chembench,aime,cmt" || recipe.capUsd !== 130 || recipe.priorCampaignCostUpperBoundUsd !== 47.531307588 || recipe.requestedNewEnvelopeCny !== "250" || recipe.minimumHeadroomCny !== "30" || recipe.modelForwardedByRecipePreparation !== false || recipe.taskScheduleSha256 !== "1ae6590140a51e9c48c656e92e482dd684843f8ae0e1dfc4e8f8ebad0e738bf8") throw new Error("Only the reviewed independent whole1220 recipe is implemented");
  for (const p of [...recipe.executedSourcePins, recipe.balance, recipe.prices, recipe.inspectPlan]) verifyPin(p);
  let lease: AdmissionLease | undefined, cash: ReturnType<typeof createCnyCashShadow> | undefined, state: { output: string; store: string } | undefined;
  let bounds: Omit<ReleaseInput, "certification"> | undefined;
  const registered: Pin[] = [], tickets = new Map<number, CashTicket>();
  const ensureCash = () => cash ??= createCnyCashShadow({ directory: join(state!.store, "currency"), runId: recipe.runId, providerKind: "real-provider", admission: lease!, prices: recipe.prices,
    journal: { directory: state!.store, configPin: actualPin(join(state!.store, "journal-config.json")), sourcePin: actualPin(join(import.meta.dir, "campaign-journal.ts")) } });
  return {
    capUsd: recipe.capUsd, priorCampaignCostUpperBoundUsd: recipe.priorCampaignCostUpperBoundUsd,
    metadata: { protocol: recipe.protocol, prospectiveRunId: recipe.runId, recipePin, taskScheduleSha256: recipe.taskScheduleSha256, providerKind: "real-provider", selectedCnyEnvelope: "250", minimumHeadroomCny: "30", frozenWorkers: recipe.workers.selected, invoice: false, foreignExchangeConversion: false },
    executionFiles: ["scientific-journal-admission.ts", ...Object.keys(fixed), "paid-campaign-lock.ts"].map(name => `scripts/benchmark-repair/${name}`),
    async acquireLock(input) {
      verifyPin(recipePin); if (input.root !== root || input.runId !== recipe.runId) throw new Error("Paid recipe run/root identity mismatch");
      const memory = scientificWorkerResources({ requested: recipe.workers.selected, freeMemoryBytes: freemem() }); if (memory.selected !== recipe.workers.selected) throw new Error("Actual memory no longer supports frozen workers");
      lease = await acquirePaidResourceAdmissionV2({ root, runId: recipe.runId, entry: join(import.meta.dir, "scientific-journal-campaign.ts"), mode: RESOURCE_MODE,
        balance: recipe.balance, prices: recipe.prices, deferredFault: recipe.deferredFault, originalPidClosure: recipe.originalPidClosure,
        requestedNewEnvelopeCny: "250", minimumHeadroomCny: "30", executedSourcePins: recipe.executedSourcePins, expectedOwnedProcessCount: recipe.workers.selected });
      return { path: lease.path, async release(proof) {
        if (!bounds) throw new Error("Actual closure Pins are absent");
        const certificatePin = proof.certificate as Pin; verifyPin(certificatePin);
        const certificate = JSON.parse(readFileSync(certificatePin.path, "utf8"));
        const auditPins = (["originalAuditor", "extraAuditor"] as const).map((key, index) => save(join(state!.output, `paid-audit-wrapper-${index}.json`), {
          protocol: "paid-admission-audit-wrapper-v2", runId: recipe.runId, auditorKind: index ? "scientific-journal" : "scientific-original",
          auditorSourcePin: recipe.executedSourcePins.find(pin => pin.path === join(import.meta.dir, index ? "audit-scientific-journal.py" : "audit-scientific-campaign.py")),
          auditedSummarySha256: certificate.auditedSummary.sha256, actualAuditorPins: [certificate.auditors[key]] }));
        const certification = save(join(state!.output, "paid-resource-final-certificate.json"), { protocol: "paid-resource-final-certificate-v2", runId: recipe.runId, boundPins: bounds, summaryPin: certificate.auditedSummary, auditPins });
        await lease!.release({ ...bounds, certification });
      } };
    },
    async prepareStore(input) {
      lease!.assertOwned(); verifyPin(recipe.inspectPlan); verifyFixed();
      const inspection = JSON.parse(readFileSync(recipe.inspectPlan.path, "utf8"));
      if (inspection.runId !== recipe.runId || inspection.mode !== "Inspect" || inspection.scriptPin.sha256 !== SCIENTIFIC_STORE_SETUP_SHA || inspection.newStoreOnly !== true || inspection.outsideProjectWrites !== false) throw new Error("Reviewed store Inspect binding differs");
      execFileSync("powershell.exe", ["-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass", "-File", join(import.meta.dir, "prepare-scientific-journal-store.ps1"), "-Mode", "Apply", "-RunId", recipe.runId, "-OwnedPid", String(lease!.owned.pid), "-OwnerNonce", lease!.owned.ownerNonce], { windowsHide: true, timeout: 30000, env: windowsPowerShellEnv() });
      const p = actualPin(join(input.output, "storage-layout.json")), layout = validateScientificStore(root, recipe.runId, p); state = { output: input.output, store: layout.physicalStore }; return p;
    },
    registerWorker(input) {
      lease!.assertOwned(); const p = save(join(input.output, `paid-process-${input.worker}.json`), { protocol: "paid-owned-process-v2", runId: recipe.runId, ownerNonce: lease!.owned.ownerNonce,
        pid: input.pid, worker: input.worker, role: "owned Bun engine", observedAt: new Date().toISOString(), base: input.base });
      lease!.registerOwnedProcess(p); registered.push(p);
    },
    beforeForward(admitted, prefix, raw, route) {
      verifyPin(recipePin); const result = ensureCash().beforeForward({ id: `${recipe.runId}/${admitted.requestSeq}`, route, rawRequest: Buffer.from(raw), capturedRequest: actualPin(admitted.requestFile), journal: { admitted, startPrefix: prefix as never } });
      tickets.set(admitted.requestSeq, result.ticket); if (!result.admitted) throw new Error("Cash admission denied: " + result.reason);
    },
    afterDurableFinish(receipt) { const state = ensureCash().finish(tickets.get(receipt.requestSeq)!, { kind: "journal-finish", journalRef: receipt.journalRef as never }); if (state.poisoned) throw new Error("Cash stopped: " + state.poisonReason); },
    afterFailedJournalCapture(request, _finish, evidence) {
      const seq = (request as { requestSeq?: number } | undefined)?.requestSeq, ticket = seq === undefined ? undefined : tickets.get(seq);
      if (!ticket) { cash?.poison("unacknowledged_source_or_cash_admission"); return; }
      if (evidence.journalRef) ensureCash().finish(ticket, { kind: "journal-finish", journalRef: evidence.journalRef as never });
      else {
        const files = evidence.files as Pin[], responsePin = files.find(file => file.path.endsWith("response.json.gz"));
        ensureCash().finish(ticket, { kind: "failed-capture", requestSeq: seq!, evidence: { files, responsePin, rawResponseSha256: evidence.rawResponseSha256 as string | undefined,
          usage: evidence.usage, httpStatus: evidence.httpStatus as number | undefined, providerAttempted: evidence.providerAttempted as boolean,
          originalPrefix: (evidence.journalSnapshot as { durablePrefix: never }).durablePrefix, reason: "source_finish_or_capture_invalid" } });
      }
      cash?.poison("source_or_cash_post_finish_failure");
    },
    certify(input) {
      const inspection = inspectCampaignJournal(state!.store); if (!inspection.valid || !inspection.accountingClosed) throw new Error("Source journal not actually closed");
      const cashClosed = ensureCash().close(); const c = JSON.parse(readFileSync(cashClosed.path, "utf8")); if (c.releasePermitted) verifyCashClosure(cashClosed);
      const sourceClosed = save(join(state!.output, "paid-source-close.json"), { protocol: "paid-source-close-v2", runId: recipe.runId, pins: lease!.sourcePins });
      const ownedClosed = save(join(state!.output, "paid-owned-close.json"), { protocol: "paid-owned-close-v2", runId: recipe.runId,
        processes: registered.map(pin => ({ pid: JSON.parse(readFileSync(pin.path, "utf8")).pid })), registrationPins: registered, evidencePins: [actualPin(join(state!.output, "worker-closure.json"))] });
      const rawClosed = save(join(state!.output, "paid-raw-close.json"), { protocol: "paid-raw-close-v2", runId: recipe.runId, journalConfigPin: c.journalConfigPin, journalPrefix: c.journalPrefix,
        evidencePins: [actualPin(join(state!.output, "api-ledger.json")), actualPin(join(state!.output, "journal-export.json")), actualPin(join(state!.store, "api-events.jsonl"))] });
      bounds = { sourceClosed, ownedClosed, rawClosed, cashClosed };
      return { valid: c.releasePermitted === true, accountingClosed: c.snapshot.pendingCount === 0 && c.snapshot.newUnknownCount === 0, bounds, providerKind: "real-provider",
        actualCashClosePin: cashClosed, journalPrefix: inspection.prefix, inputWorkerCount: (input.workers as unknown[]).length };
    },
    failed(input) { try { cash?.poison("scientific_campaign_failed"); } finally { const output = String(input.output ?? state?.output ?? join(root, "docs/repair-2026-10-08/campaigns", recipe.runId));
      save(join(output, "paid-admission-failure.json"), { runId: recipe.runId, observedAt: new Date().toISOString(), source: input, cash: cash?.snapshot() ?? null, lockRetained: true }, false); } },
  };
}
