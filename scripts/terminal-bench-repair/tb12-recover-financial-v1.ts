/** Bounded release of this known-closed TB owner, never a stale-lock takeover. */
import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { join, resolve } from "node:path";
import { Database } from "bun:sqlite";
import { actualPin, demand, hash, jsonPin, same, verifyPin } from "./../benchmark-repair/paid-resource-proof-v2.ts";
import { verifyCashClosure } from "./../benchmark-repair/cny-cash-shadow-v2.ts";
import { durable, resourceGuard } from "./tb12-v1/paid_admission.ts";
import { nativePython } from "./tb12-v2/close_certificate.ts";

const ROOT=resolve(import.meta.dir,"../.."),home=resolve(process.argv[2]??"");
demand(home.startsWith(join(ROOT,"docs/repair-2026-10-09/tb12-runs-v1")+"\\"),"tb12_recovery_output_scope");
const admissionPin=actualPin(join(home,"paid-admission.json")),admission=jsonPin(admissionPin);
demand(admission.protocol==="paid-resource-admission-v2"&&admission.family==="terminal-bench-twelve-journal-v1"&&admission.runId===home.split("\\").at(-1),"tb12_recovery_original_scope");
const canonical=join(ROOT,".phase1-data/owned-paid-campaign.lock.json");
const assertOwned=()=>demand(same(JSON.parse(readFileSync(canonical,"utf8")),admission.owned),"tb12_recovery_owner_changed");
assertOwned();
demand(!existsSync(join(home,"paid-release-ack.json")),"tb12_recovery_already_released");
const certificatePin=actualPin(join(home,"independent/close-certificate.json")),certificate=jsonPin(certificatePin);
demand(certificate.protocol==="tb12-independent-close-certificate-v1"&&certificate.family===admission.family&&certificate.runId===admission.runId&&certificate.ownerNonce===admission.owned.ownerNonce&&certificate.kind==="financial-only"&&certificate.rawFinancialVerified&&certificate.sourceVerified&&certificate.ownedCloseVerified&&certificate.tokenSecretScanPassed&&certificate.modelCallsByAuditor===0,"tb12_recovery_exact_financial_certificate");
for(const pin of certificate.inputPins)verifyPin(pin);
for(const pin of admission.sourcePins)verifyPin(pin);
demand(hash(JSON.stringify(admission.sourcePins))===admission.owned.sourceExecutionDigest,"tb12_recovery_executed_source_digest");
const cash=verifyCashClosure(certificate.cashClosePin);
demand(cash.config.ownerNonce===admission.owned.ownerNonce&&cash.config.admissionPin.sha256===admissionPin.sha256&&cash.config.carryNanoCny==="8392180000"&&cash.config.envelopeNanoCny==="9000000000"&&cash.proof.snapshot.pendingCount===0&&cash.proof.snapshot.newUnknownCount===0&&BigInt(cash.proof.snapshot.newExposureNanoCny)<=9000000000n,"tb12_recovery_cash_binding");
const start=new Date().toISOString();Bun.gc(true);const resources=resourceGuard();
const native=await nativePython(join(import.meta.dir,"tb12-v2/fresh_absence.py"),["--run-directory",home,"--run-id",admission.runId,
  "--owner-nonce",admission.owned.ownerNonce,"--include-closed-owner"],join(home,"financial-recovery/fresh-observer-native-close.json"));
const result=JSON.parse(native.stdout.trim().split(/\r?\n/).at(-1)!);
demand(result.allAbsent,"tb12_recovery_fresh_failed");const freshPin=actualPin(result.observation),fresh=jsonPin(freshPin);
demand(fresh.family===admission.family&&fresh.runId===admission.runId&&fresh.ownerNonce===admission.owned.ownerNonce&&fresh.allOriginalOwnedProcessInstancesAbsent===true&&Date.now()-Date.parse(fresh.observedAtUtc)<=30000,"tb12_recovery_fresh_binding");
for(const pin of fresh.nativeReceiptPins)verifyPin(pin);
assertOwned();
const recoveryPin=durable(join(home,"financial-recovery/reconciliation.json"),{protocol:"tb12-known-financial-close-recovery-v1",family:admission.family,
  runId:admission.runId,originalOwner:admission.owned,originalAdmissionPin:admissionPin,originalCertificatePin:certificatePin,
  freshOwnedObservationPin:freshPin,nativeObserverClosePin:native.receipt,controllerPid:process.pid,controllerSource:actualPin(import.meta.path),
  modelCalls:0,providerRequests:0,newUnknownCount:0,startedAtUtc:start,resourceObservation:resources,
  sourceDigestVerified:true,allOriginalOwnedInstancesAbsent:true,noOwnerTakeover:true,noNewFinancialAdmission:true,
  previousNumericPidTimeoutPreserved:true,knownNewNanoCny:cash.proof.snapshot.newKnownEstimatedNanoCny});
const registryPath=join(home,"tb12-paid-resource-run.json"),registry=jsonPin(actualPin(registryPath));
demand(registry.released===false&&registry.closedPin===null&&registry.admissionPin.sha256===admissionPin.sha256,"tb12_recovery_registry_binding");
const db=new Database(join(home,"paid-registry.sqlite"));
db.exec("PRAGMA journal_mode=WAL; PRAGMA synchronous=FULL");
const acquired=db.query("SELECT json FROM event WHERE kind='acquired' ORDER BY seq LIMIT 1").get() as any;
demand(acquired&&same(JSON.parse(acquired.json).owned,admission.owned),"tb12_recovery_native_registry_owner");
db.query("INSERT INTO event(kind,json) VALUES(?,?)").run("financial-close-recovered",JSON.stringify({certificatePin,freshPin,recoveryPin}));
db.exec("PRAGMA wal_checkpoint(TRUNCATE)");db.close();
durable(registryPath,{...registry,closedPin:certificatePin,freshOwnedObservationPin:freshPin,recoveryPin,released:false},true);
assertOwned();unlinkSync(canonical);
const ackPin=durable(join(home,"paid-release-ack.json"),{protocol:"tb12-paid-release-ack-v1",family:admission.family,runId:admission.runId,
  owned:admission.owned,certificatePin,freshOwnedObservationPin:freshPin,recoveryPin,exactCanonicalOwnerRemoved:true,
  observedAtUtc:new Date().toISOString(),modelCalls:0});
durable(registryPath,{...registry,closedPin:certificatePin,freshOwnedObservationPin:freshPin,recoveryPin,released:true,releaseAckPin:ackPin},true);
durable(join(home,"entry-closed.json"),{protocol:"tb12-owned-paid-entry-closed-v1",family:admission.family,runId:admission.runId,mode:"run",
  realOperationalComplete:false,certificatePin,canonicalOwnerReleased:true,originalUnknownCarrySettled:false,recoveryPin,
  qualification:"premature F unit submit sealing; resource floor interrupted at 17 records; not final paired trial"});
console.log(JSON.stringify({home,canonicalOwnerReleased:true,knownEstimatedNanoCny:cash.proof.snapshot.newKnownEstimatedNanoCny,modelCalls:0}));
