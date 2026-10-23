/** New-account USD admission. The original DeepSeek CNY account is never used here. */
import { randomBytes } from "node:crypto";
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { actualPin, demand, jsonPin, same, verifyPin, REAL_CLOCK, type Pin } from "../../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { benchmarkProviderKey, observeBenchmarkBalance, observeBenchmarkPrices } from "./digitalocean-provider.ts";
import { verifyBenchmarkCashClosure, type UsdAdmission } from "./digitalocean-usd-cash.ts";

function save(path: string, value: any) {
  const fd = openSync(path, "wx", 0o600); try { writeFileSync(fd, JSON.stringify(value, null, 2) + "\n"); fsyncSync(fd); } finally { closeSync(fd); }
  return actualPin(path);
}
export function cashClosureAllowsContinuation(proof:any,allowUnsettledCash=false) {
  return proof.releasePermitted===true || allowUnsettledCash===true&&proof.snapshot.newUnknownCount>0&&proof.snapshot.pendingCount===0;
}
export async function prepareOpenRouterFunding(root: string, output: string, requestedCapUsd?: number) {
  const key = benchmarkProviderKey(root), directory = join(output, "openrouter-funding");
  mkdirSync(directory, { recursive: true });
  const prices = await observeBenchmarkPrices(directory), balance = await observeBenchmarkBalance(directory, key);
  const available = jsonPin(balance).remainingUsd;
  const capUsd = requestedCapUsd === undefined ? available : Math.min(requestedCapUsd, available);
  demand(Number.isFinite(capUsd) && capUsd > 0, "openrouter_positive_usd_envelope_required");
  return { prices, balance, capUsd };
}
export async function acquireOpenRouterAdmission(input: { root: string; output: string; runId: string; family: string; entry: string;
  sourcePins: Pin[]; prices?: Pin; balance?: Pin; capUsd?: number; lockPath?: string; allowUnsettledCash?: boolean }) {
  demand(!input.allowUnsettledCash || input.family === 'four-bench-full-f-v1', 'unsettled_cash_policy_scope');
  mkdirSync(input.output, { recursive: true });
  const funding = input.prices && input.balance ? { prices: input.prices, balance: input.balance,
    capUsd: Math.min(input.capUsd ?? Infinity, jsonPin(input.balance).remainingUsd) } : await prepareOpenRouterFunding(input.root, input.output, input.capUsd);
  const balance = jsonPin(funding.balance), prices = jsonPin(funding.prices), now = Date.now();
  demand(balance.protocol === "openrouter-usd-balance-readonly-v1" && balance.currency === "USD" && balance.modelCalls === 0 && balance.httpStatus === 200 && Number.isFinite(balance.remainingUsd), "openrouter_balance_source");
  demand(now >= Date.parse(balance.observedAtUtc) && now - Date.parse(balance.observedAtUtc) <= 30 * 60000, "openrouter_balance_expired");
  demand(prices.protocol === "openrouter-usd-pricing-source-snapshot-v1" && prices.currency === "USD" && prices.modelCalls === 0 && now >= Date.parse(prices.observedAtUtc) && now - Date.parse(prices.observedAtUtc) <= 86400000, "openrouter_price_source");
  demand(Number.isFinite(funding.capUsd) && funding.capUsd > 0 && funding.capUsd <= balance.remainingUsd, "openrouter_available_usd_envelope");
  for (const pin of input.sourcePins) verifyPin(pin);
  const path = input.lockPath ?? join(input.root, ".phase1-data/owned-paid-campaign.lock.json"); mkdirSync(join(input.root, ".phase1-data"), { recursive: true });
  demand(!existsSync(path), "another_paid_owner_is_active");
  const owned = Object.freeze({ pid: process.pid, startedAt: new Date().toISOString(), runId: input.runId,
    entry: input.entry, ownerNonce: randomBytes(24).toString("hex"), family: input.family, currency: "USD", provider: "openrouter-deepseek" });
  save(path, owned); let released = false; const cash = new Map<string, {pin:Pin;admissionPin:Pin;capUsd:number;retired?:Pin;closedExposureUsd?:number}>(); const processes: Pin[] = [];
  let allocatedUsd=0;
  const assertOwned = () => demand(!released && same(JSON.parse(readFileSync(path, "utf8")), owned), "openrouter_paid_owner_changed");
  const proofPin = save(join(input.output, "openrouter-admission.json"), { protocol: "openrouter-usd-admission-v1",
    runId: input.runId, family: input.family, currency: "USD", capUsd: funding.capUsd, pricesPin: funding.prices,
    balancePin: funding.balance, owned, sourcePins: input.sourcePins, priorOpenRouterCostUsd: 0,
    costPolicy:input.allowUnsettledCash?'record_and_continue':'strict',
    originalDeepSeekCnyLedgerReused: false, invoice: false, foreignExchangeConversion: false });
  const close = (result: any) => {
    assertOwned(); demand(result.ownedGenerationClosed === true && result.pendingRequests === 0 && cash.size>0, "openrouter_owned_generation_not_closed");
    const closures=[...cash.values()].map(record=>{
      const directory=record.pin.path.replace(/[\\/]cash-config\.json$/, ""), pin=actualPin(join(directory,"cash-close.json")), verified=verifyBenchmarkCashClosure(pin);
      const unresolved = verified.proof.snapshot.newUnknownCount;
      demand(cashClosureAllowsContinuation(verified.proof,input.allowUnsettledCash)
        && verified.config.ownerNonce===owned.ownerNonce&&same(verified.config.admissionPin,record.admissionPin)&&verified.config.capUsd===record.capUsd,"openrouter_cash_cannot_release");
      return{pin,billedUsd:verified.proof.snapshot.billedUsd,unknownCostCount:unresolved,unknownReservationUsd:verified.proof.snapshot.unknownReservationUsd,
        originalReleasePermitted:verified.proof.releasePermitted};
    });
    const receipt = save(join(input.output, "openrouter-owned-release.json"), { protocol: "openrouter-owned-release-v1", runId: input.runId,
      owned, cashClosures:closures, registeredProcesses: processes, ...result, currency: "USD", billedUsd: closures.reduce((sum,row)=>sum+row.billedUsd,0),
      costPolicy:input.allowUnsettledCash?'record_and_continue':'strict',
      unknownCostCount:closures.reduce((sum,row)=>sum+row.unknownCostCount,0),unknownReservationUsd:closures.reduce((sum,row)=>sum+row.unknownReservationUsd,0),
      scoreCertificate: false, originalDeepSeekUnknownSettled: false, invoice: false });
    assertOwned(); unlinkSync(path); released = true; return receipt;
  };
  const lease: UsdAdmission & { root: string; path: string; prices: Pin; balance: Pin; sourcePins: Pin[]; clock: typeof REAL_CLOCK;
    registerOwnedProcess(pin: Pin): void; finishLightweight(result: any): Pin; release(proof: any): Promise<void>;
    retireClosedLane(pin:Pin):void; allocation():{allocatedUsd:number;capUsd:number};
    forkLane(runId:string,output:string,capUsd:number):UsdAdmission&{registerOwnedProcess(pin:Pin):void} } = {
    currency: "USD", root: input.root, path, runId: input.runId, capUsd: funding.capUsd, owned, proofPin,
    prices: funding.prices, balance: funding.balance, sourcePins: input.sourcePins, clock: REAL_CLOCK, scope: "production", assertOwned,
    validateForwardSource() { assertOwned(); for (const pin of [...input.sourcePins, funding.prices, funding.balance]) verifyPin(pin);
      demand(Date.now() >= Date.parse(prices.observedAtUtc) && Date.now() - Date.parse(prices.observedAtUtc) <= 86400000, "openrouter_price_expired"); },
    registerCash(pin) { assertOwned(); const config = jsonPin(pin);
      demand(cash.size===0&&allocatedUsd===0&&config.currency === "USD" && config.runId === input.runId && config.ownerNonce === owned.ownerNonce && same(config.admissionPin, proofPin)&&config.capUsd===funding.capUsd, "openrouter_cash_registration"); cash.set(input.runId,{pin,admissionPin:proofPin,capUsd:funding.capUsd}); },
    registerOwnedProcess(pin) { assertOwned(); verifyPin(pin); processes.push(pin); },
    finishLightweight: close,
    async release(proof) { close(proof); },
    allocation(){assertOwned();return{allocatedUsd,capUsd:funding.capUsd};},
    retireClosedLane(pin){
      assertOwned();const verified=verifyBenchmarkCashClosure(pin),record=cash.get(verified.config.runId);
      demand(record&&!record.retired&&cashClosureAllowsContinuation(verified.proof,input.allowUnsettledCash)
        &&same(record.pin,verified.proof.configPin)&&same(record.admissionPin,verified.config.admissionPin)
        &&verified.config.ownerNonce===owned.ownerNonce&&verified.config.capUsd===record.capUsd,'closed_lane_exposure_binding');
      const exposure=verified.proof.snapshot.exposureUpperBoundUsd;
      demand(Number.isFinite(exposure)&&exposure>=0&&exposure<=record.capUsd+1e-9,'closed_lane_exposure_bound');
      record.retired=pin;record.closedExposureUsd=exposure;allocatedUsd-=record.capUsd-exposure;
      save(join(input.output,'closed-exposure-'+verified.config.runId+'.json'),{protocol:'closed-lane-exposure-retirement-v1',
        runId:verified.config.runId,parentAdmissionPin:proofPin,originalLaneCapUsd:record.capUsd,originalCashClosePin:pin,
        retainedExposureUsd:exposure,knownUsd:verified.proof.snapshot.billedUsd,unknownReservationUsd:verified.proof.snapshot.unknownReservationUsd,
        rawCashUnchanged:true,allocatedUsd,scoreCertificate:false});
    },
    forkLane(runId,output,capUsd){
      assertOwned();demand(runId.startsWith(input.runId+'-')&&Number.isFinite(capUsd)&&capUsd>0&&allocatedUsd+capUsd<=funding.capUsd+1e-9&&!cash.has(input.runId),'openrouter_lane_budget');
      mkdirSync(output,{recursive:true});allocatedUsd+=capUsd;
      const lanePin=save(join(output,'openrouter-lane-admission.json'),{protocol:'openrouter-usd-lane-admission-v1',runId,capUsd,currency:'USD',parentAdmissionPin:proofPin,ownerNonce:owned.ownerNonce});
      return{currency:'USD',runId,capUsd,owned:{...owned,runId},proofPin:lanePin,scope:'production',assertOwned,validateForwardSource:lease.validateForwardSource,
        registerOwnedProcess:lease.registerOwnedProcess,
        registerCash(pin){assertOwned();const config=jsonPin(pin);demand(!cash.has(runId)&&config.runId===runId&&config.ownerNonce===owned.ownerNonce&&config.currency==='USD'&&config.capUsd===capUsd&&same(config.admissionPin,lanePin),'openrouter_lane_cash_binding');cash.set(runId,{pin,admissionPin:lanePin,capUsd});}};
    },
  };
  return lease;
}
