/** TB-specific canonical wx ownership and typed, durable financial lifecycle. */
import { randomBytes } from "node:crypto";
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, renameSync, statfsSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { freemem } from "node:os";
import { Database } from "bun:sqlite";
import type { AdmissionLease } from "../../repair-2026-10-08/paid-resource-admission-v2.ts";
import { scanOtherPaidRuns, observeOriginalPaidPids, assertPidsAbsent } from "../../repair-2026-10-08/paid-resource-admission-v2.ts";
import { scanJpgPaidRuns } from "../../repair-2026-10-08/jpg-paid-resource-admission-v1.ts";
import { jpgCarry } from "../../repair-2026-10-08/jpg-D-paid-resource-admission-v1.ts";
import { FINANCIAL_RUN } from "../../repair-2026-10-08/financial-interruption-release.ts";
import { actualPin, demand, hash, jsonPin, nanoCny, REAL_CLOCK, same, validatePrices, verifyPin, type Pin } from "../../repair-2026-10-08/paid-resource-proof-v2.ts";
import { verifyCashClosure } from "./peak_cash_shadow.ts";

export const TB12_FAMILY = "terminal-bench-twelve-journal-v2";
const ROOT = resolve(import.meta.dir, "../../..");
export function durable(path:string,value:unknown,replace=false):Pin {
  mkdirSync(dirname(path),{recursive:true});
  const raw=Buffer.from(JSON.stringify(value,null,2)+"\n");
  const target=replace?path+".tmp-"+randomBytes(8).toString("hex"):path;
  const fd=openSync(target,"wx",0o600);
  try { writeFileSync(fd,raw); fsyncSync(fd); } finally { closeSync(fd); }
  demand(readFileSync(target).equals(raw),"tb12_durable_readback");
  if(replace)renameSync(target,path);
  demand(readFileSync(path).equals(raw),"tb12_durable_commit_readback");
  return actualPin(path);
}
function recent(timestamp:string,maximumMs:number) {
  const time=Date.parse(timestamp),now=Date.now();
  demand(Number.isFinite(time)&&time<=now&&now-time<=maximumMs,"tb12_resource_observation_expired");
}
export function resourceGuard() {
  const free=(path:string)=>{const s=statfsSync(path);return Number(s.bavail)*Number(s.bsize);};
  const measured={CFreeBytes:free("C:/"),FFreeBytes:free("F:/"),availableMemoryBytes:freemem(),observedAtUtc:new Date().toISOString()};
  demand(measured.CFreeBytes>=1024**3&&measured.FFreeBytes>=4*1024**3&&measured.availableMemoryBytes>=6*1024**3,"tb12_actual_resource_floor");
  return measured;
}

export interface TbAdmissionInput {
  runId:string;output:string;balance:Pin;prices:Pin;crossFamily:Pin;
  sourcePins:readonly Pin[];entry:Pin;requestedEnvelopeCny:string;
  /** Retained operational headroom unless directly authorized otherwise. */
  headroomCny:string;headroomDirective?:Pin;readiness:Pin;
}

export async function acquireTb12Admission(input:TbAdmissionInput):Promise<AdmissionLease> {
  const output=resolve(input.output);
  demand(output.startsWith(join(ROOT,"docs/repair-2026-10-09/tb12-runs-v1")+"\\")&&/^repair-[0-9TZ-]+$/.test(input.runId),"tb12_admission_scope");
  const ready=jsonPin(input.readiness);
  demand(ready.protocol==="tb12-frozen-execution-readiness-v1"&&ready.family===TB12_FAMILY&&ready.validated===true&&ready.modelCalls===0&&ready.distinctTaskCount===12&&ready.plannedTaskRuns===24,"tb12_actual_readiness_required");
  for(const pin of input.sourcePins)verifyPin(pin);
  verifyPin(input.entry);verifyPin(input.balance);verifyPin(input.prices);
  const crossed=jsonPin(input.crossFamily);
  demand(crossed.protocol==="tb12-readonly-cross-family-preflight-v1"&&crossed.passed===true&&crossed.modelCalls===0&&crossed.lockMutations===0,"tb12_cross_family_proof");
  recent(crossed.observedAtUtc,30*60000);
  const balance=jsonPin(input.balance),prices=validatePrices(input.prices);
  demand(balance.protocol==="deepseek-resource-readonly-v1"&&balance.modelCalls===0&&balance.httpStatus===200&&balance.isAvailable===true,"tb12_actual_balance");
  recent(balance.observedAtUtc,30*60000);recent(prices.observedAtUtc,24*3600000);
  const rows=balance.balances.filter((row:any)=>row.currency==="CNY");
  demand(rows.length===1,"tb12_cny_balance");
  const cash=nanoCny(rows[0].total_balance),envelope=nanoCny(input.requestedEnvelopeCny),headroom=nanoCny(input.headroomCny);
  demand(envelope>0n,"tb12_positive_envelope");
  if(headroom<30_000_000_000n) {
    demand(input.headroomDirective,"tb12_headroom_direct_authorization_required");
    const directive=jsonPin(input.headroomDirective);
    demand(directive.protocol==="tb12-human-resource-directive-v1"&&directive.authorRole==="user"&&directive.headroomCny===input.headroomCny&&directive.scopeIncludesTerminalBench===true&&typeof directive.verbatimAnswer==="string"&&directive.verbatimAnswer.length>0&&envelope<=nanoCny(directive.requestedEnvelopeCny),"tb12_headroom_authorization_binding");
  }
  const carryProof=jpgCarry({
    deferredFault:actualPin(join(ROOT,"docs/repair-2026-10-08/scientific-campaign-deferred-fault.json")),
    originalPidClosure:actualPin(join(ROOT,"docs/repair-2026-10-08/science1220-oom-original-process-closure.json")),
  } as Parameters<typeof jpgCarry>[0]);
  const carry=carryProof.carry,carryNano=carry.reduce((sum:bigint,row:any)=>sum+BigInt(row.peakNanoCny),0n);
  demand(carryNano===8_392_180_000n&&cash>=carryNano+headroom+envelope,"tb12_insufficient_current_cash");
  const resource=resourceGuard();
  assertPidsAbsent([50652,38176,87440,96080,96848],await observeOriginalPaidPids([50652,38176,87440,96080,96848]));
  scanOtherPaidRuns(ROOT,FINANCIAL_RUN);scanJpgPaidRuns(ROOT,input.runId);
  const path=join(ROOT,".phase1-data/owned-paid-campaign.lock.json");
  const owned=Object.freeze({pid:process.pid,startedAt:new Date().toISOString(),runId:input.runId,
    entry:input.entry.path,ownerNonce:randomBytes(24).toString("hex"),family:TB12_FAMILY,mode:"tb12-real-provider",sourceExecutionDigest:hash(JSON.stringify(input.sourcePins))});
  // No takeover, stale-owner deletion, exit handler, or unconditional release.
  mkdirSync(output,{recursive:true});
  durable(path,owned);
  let released=false,cashPin:Pin|undefined;
  const registry=join(output,"tb12-paid-resource-run.json");
  const database=new Database(join(output,"paid-registry.sqlite"));
  database.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL; CREATE TABLE event(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,json TEXT NOT NULL);");
  const record=(kind:string,value:unknown)=>database.query("INSERT INTO event(kind,json) VALUES(?,?)").run(kind,JSON.stringify(value));
  const assertOwned=()=>{demand(!released&&same(JSON.parse(readFileSync(path,"utf8")),owned),"tb12_canonical_owner_changed");};
  const proofPin=durable(join(output,"paid-admission.json"),{
    protocol:"paid-resource-admission-v2",tb12Protocol:"tb12-paid-resource-admission-v1",family:TB12_FAMILY,runId:input.runId,owned,
    balancePin:input.balance,pricesPin:input.prices,crossFamilyPin:input.crossFamily,readinessPin:input.readiness,
    sourcePins:input.sourcePins,entryPin:input.entry,resource,carry,carryNanoCny:carryNano.toString(),
    headroomNanoCny:headroom.toString(),headroomDirective:input.headroomDirective??null,
    balanceNanoCny:cash.toString(),envelopeNanoCny:envelope.toString(),selectedNewEnvelopeNanoCny:envelope.toString(),
    noHistoricalKnownFeesSubtractedAgain:true,invoice:false,foreignExchangeConversion:false,
  });
  durable(registry,{protocol:"tb12-paid-resource-run-v1",family:TB12_FAMILY,runId:input.runId,admissionPin:proofPin,closedPin:null,released:false});
  record("acquired",{owned,proofPin});
  const validateForwardSource=()=>{
    assertOwned();resourceGuard();recent(prices.observedAtUtc,24*3600000);
    for(const pin of [...input.sourcePins,...carryProof.critical,input.balance,input.prices,input.readiness])verifyPin(pin);
  };
  const lease:AdmissionLease={
    protocol:"paid-resource-admission-v2",root:ROOT,runId:input.runId,path,proofPin,owned,
    envelopeNanoCny:envelope,balanceNanoCny:cash,headroomNanoCny:headroom,carryNanoCny:carryNano,carry,
    clock:REAL_CLOCK,scope:"production",sourcePins:input.sourcePins,
    assertOwned,validateForwardSource,
    registerCash(pin){assertOwned();demand(!cashPin,"tb12_duplicate_cash");const config=jsonPin(pin);
      demand(config.protocol==="cny-shadow-config-v2"&&config.runId===input.runId&&config.ownerNonce===owned.ownerNonce&&config.providerKind==="real-provider"&&same(config.admissionPin,proofPin)&&config.envelopeNanoCny===envelope.toString()&&config.carryNanoCny===carryNano.toString()&&same(config.pricesPin,input.prices),"tb12_cash_config_binding");
      cashPin=pin;record("cash",pin);},
    registerOwnedProcess(pin){assertOwned();verifyPin(pin);record("owned-process",pin);},
    async release(proof:any) {
      assertOwned();demand(proof?.tb12CertificatePin,"tb12_exact_certificate_required");
      const certificate=jsonPin(proof.tb12CertificatePin);
      demand(certificate.protocol==="tb12-independent-close-certificate-v1"&&certificate.family===TB12_FAMILY&&certificate.runId===input.runId&&certificate.ownerNonce===owned.ownerNonce,"tb12_certificate_binding");
      demand(certificate.modelCallsByAuditor===0&&certificate.sourceVerified===true&&certificate.rawFinancialVerified===true&&certificate.ownedCloseVerified===true&&certificate.tokenSecretScanPassed===true,"tb12_close_not_actual");
      demand(["score-and-financial","financial-only"].includes(certificate.kind),"tb12_close_kind");
      if(certificate.kind==="score-and-financial")demand(certificate.distinctTaskCount===12&&certificate.realTaskRuns===24&&certificate.operationalComplete===true,"tb12_score_scope");
      for(const pin of certificate.inputPins)verifyPin(pin);
      demand(cashPin&&same(cashPin,jsonPin(certificate.cashClosePin).configPin),"tb12_cash_config_binding");
      const cashClose=verifyCashClosure(certificate.cashClosePin);
      demand(cashClose.config.ownerNonce===owned.ownerNonce&&cashClose.config.admissionPin.sha256===proofPin.sha256&&cashClose.config.carryNanoCny===carryNano.toString()&&BigInt(cashClose.proof.snapshot.newExposureNanoCny)<=envelope,"tb12_cash_owner_and_envelope");
      demand(cashClose.proof.snapshot.pendingCount===0&&cashClose.proof.snapshot.newUnknownCount===0,"tb12_unknown_cash_cannot_release");
      validateForwardSource();
      // Fresh exact owned PIDs/ports/CIDs must be independently re-observed by
      // the parent controller immediately before this bounded release step.
      const fresh=jsonPin(proof.freshOwnedObservationPin);
      demand(fresh.protocol==="tb12-fresh-owned-absence-v1"&&fresh.family===TB12_FAMILY&&fresh.runId===input.runId&&fresh.allAbsent===true&&fresh.ownerNonce===owned.ownerNonce,"tb12_fresh_absence_binding");
      recent(fresh.observedAtUtc,30000);
      for(const pin of fresh.nativeReceiptPins)verifyPin(pin);
      record("closed",{certificatePin:proof.tb12CertificatePin,freshOwnedObservationPin:proof.freshOwnedObservationPin});
      database.exec("PRAGMA wal_checkpoint(TRUNCATE)");database.close();
      durable(registry,{protocol:"tb12-paid-resource-run-v1",family:TB12_FAMILY,runId:input.runId,admissionPin:proofPin,
        closedPin:proof.tb12CertificatePin,freshOwnedObservationPin:proof.freshOwnedObservationPin,released:false},true);
      assertOwned();unlinkSync(path);released=true;
      durable(join(output,"paid-release-ack.json"),{protocol:"tb12-paid-release-ack-v1",family:TB12_FAMILY,runId:input.runId,owned,
        certificatePin:proof.tb12CertificatePin,freshOwnedObservationPin:proof.freshOwnedObservationPin,
        exactCanonicalOwnerRemoved:true,observedAtUtc:new Date().toISOString()});
      durable(registry,{protocol:"tb12-paid-resource-run-v1",family:TB12_FAMILY,runId:input.runId,admissionPin:proofPin,
        closedPin:proof.tb12CertificatePin,released:true,releaseAckPin:actualPin(join(output,"paid-release-ack.json"))},true);
    },
  };
  return lease;
}
