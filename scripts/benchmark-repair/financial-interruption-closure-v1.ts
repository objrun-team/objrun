/** Read-only historical financial boundary. A partial science batch is never a score certificate. */
import { createReadStream, existsSync, lstatSync, readFileSync, realpathSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { createGunzip } from 'node:zlib';
import { actualPin, demand, gzipProof, hash, inside, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { assertFixedFinancialReport, assertNativeOwnerClosure, FINANCIAL_RUN } from './financial-interruption-release.ts';

const ROOT = resolve(import.meta.dir, '../..'), META = join(ROOT, 'docs/repair-2026-10-08/campaigns', FINANCIAL_RUN);
const STORE = resolve('D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6/scientific-journal-v2-' + FINANCIAL_RUN);
const HOME = join(ROOT, 'docs/repair-2026-10-08/scientific-financial-releases');
const ACTUAL_HOME = join(HOME, FINANCIAL_RUN + '-root-v1');
const ACK: Pin = { path: join(ACTUAL_HOME, 'release-ack.json'), bytes: 3385, sha256: '948bd64de553bd67809fc9247a33b213889e8cb9333ebbb870b44ec8f7471027' };
const INTENT: Pin = { path: join(ACTUAL_HOME, 'release-intent.json'), bytes: 3467, sha256: '1b6c529ae4bacc8d25538db2d3d5c52eade287f46a0e03f1ebbeb132e054c5d3' };
const INSPECTION: Pin = { path: join(ACTUAL_HOME, 'inspection.json'), bytes: 3232, sha256: '485c4f2b9cfea712b19d3e5bce8a264fbcb8ecf9328a25a567ecddedbc5ac61c' };
const LOCK_ARCHIVE: Pin = { path: join(ACTUAL_HOME, 'root-original-lock-bytes.json'), bytes: 432, sha256: '31fa74df0ee0d7c32d1832a4eec3fc2f89e61efe3c4cf54ebe862dd0d488dd53' };
const ROOT_REVIEW: Pin = { path: join(ACTUAL_HOME, 'root-independent-release-review.json'), bytes: 2686, sha256: 'bdb3dae453dc20481dfa6c47983010d82fffd5790a284e3ad4ac87c1d0fe9fb5' };
export const FINANCIAL_KNOWN_USD = 74.31931532400054;
const REPORT: Pin = { path: join(ROOT, 'docs/repair-2026-10-08/scientific-financial-interruptions', FINANCIAL_RUN + '-audit-v2/audit.json'), bytes: 10661, sha256: '4722f1e9d25ed2f2ed061cf6d37fa89d4c5816625f15809b8309cccfdbcbc4d4' };
const INDEX: Pin = { path: join(dirname(REPORT.path), 'request-evidence.jsonl.gz'), bytes: 6693036, sha256: 'cc1b832b6f59001de8bf3ba4a2d31e7a0dcdeb704f276e1f55bfb4ec9c4f956e' };
const SOURCE: Pin = { path: join(import.meta.dir, 'financial-interruption-release.ts'), bytes: 41248, sha256: '4f2f2aad2bcc0857b4cf73120bc48fb70b9632df408ed8f06c6b5ae5dfe2dd41' };
const REGISTRY: Pin = { path: join(META, 'paid-resource-v2-run.json'), bytes: 393, sha256: 'b635eef60fd169d6133c39f5bcfd4f0f50d3d46b00d26723f7f08e6ce8c47d8a' };
const LOCK: Pin = { path: join(ROOT, '.phase1-data/owned-paid-campaign.lock.json'), bytes: 432, sha256: '31fa74df0ee0d7c32d1832a4eec3fc2f89e61efe3c4cf54ebe862dd0d488dd53' };
const FIRST: Pin = { path: join(ROOT, 'docs/repair-2026-10-08/scientific-interruption-' + FINANCIAL_RUN, 'first-pass.json'), bytes: 35517, sha256: '204cc6a0bfa793934b4abdfd78534a57ee606295feffe24a6878c76732652758' };
const IDENTITY: Pin = { path: join(ROOT, 'test/fixtures/repair/science-db-snapshots/root-proxy-identity-routed-v2/proxy-port-identity.json'), bytes: 9977, sha256: '66f88e99a6d63aa2ab92c4146611d6e5cc11729c03077d629a2b81d629cad1d8' };
const ACTORS = { pids: [104376,111992,13948,102088,27504], ports: [59388,59989,59990,59991,59387] };
const BASE = 'financial-interruption-release-v1';
export type FinancialInterruptedBoundary = Readonly<{ acknowledgementPin: Pin; originalLockArchivePin: Pin }>;
export const ACTUAL_FINANCIAL_INTERRUPTED_BOUNDARY: FinancialInterruptedBoundary = Object.freeze({ acknowledgementPin: ACK, originalLockArchivePin: LOCK_ARCHIVE });

const pinEqual = (a: Pin, b: Pin) => !!a && resolve(a.path) === resolve(b.path) && a.bytes === b.bytes && a.sha256 === b.sha256;
function regular(path: string, root: string) { const p=resolve(path); demand(inside(root,p),'financial_boundary_path_scope'); let at=p; while(true){demand(!lstatSync(at).isSymbolicLink()&&realpathSync(at).toLowerCase()===at.toLowerCase(),'financial_boundary_reparse');if(at===resolve(root))break;at=dirname(at);}demand(lstatSync(p).isFile(),'financial_boundary_not_regular');return p; }
function record(pin:Pin, home:string){regular(pin.path,home);return jsonPin(pin);}
/** Pins, source, actor and owner links are checked here; every real file is verified by the entry below. */
export function assertFinancialReleaseGraph(graph: {ack:any;intent:any;inspection:any;archiveOwner:any;originalOwner:any}) {
  const {ack,intent,inspection,archiveOwner,originalOwner}=graph;
  demand(ack?.protocol===BASE+'-ack'&&intent?.protocol===BASE+'-intent'&&inspection?.protocol===BASE+'-inspection','financial_boundary_protocol');
  for(const r of [ack,intent,inspection]){
    demand(r.runId===FINANCIAL_RUN&&r.fixture===false&&r.financialOnly===true&&r.scoreCertificate===false&&r.oldUnknownSettled===false&&pinEqual(r.sourcePin,SOURCE)&&pinEqual(r.financialAuditPin,REPORT)&&pinEqual(r.identityPin,IDENTITY)&&pinEqual(r.originalRegistryPin,REGISTRY)&&pinEqual(r.originalLockPin,LOCK)&&same(r.actors,ACTORS)&&same(r.owner,originalOwner),'financial_boundary_binding');
  }
  demand(same(archiveOwner,originalOwner)&&originalOwner.pid===104376&&originalOwner.runId===FINANCIAL_RUN&&originalOwner.ownerNonce==='a324165d98aa2edcca6aee98d1ef2099ba6defaac020e4c4'&&resolve(originalOwner.entry)===join(import.meta.dir,'scientific-journal-campaign.ts'),'financial_boundary_owner_nonce');
  demand(ack.exactOriginalLockRemoved===true&&ack.originalRegistryReleased===false&&ack.plannedScoreCompletion===false&&ack.originalUnknownCarryNanoCny==='8392180000'&&inspection.originalRegistryReleased===false&&inspection.releasePerformed===false,'financial_boundary_not_financial_only');
  demand(pinEqual(ack.inspectionPin,intent.inspectionPin)&&pinEqual(ack.freshActorObservationPin,intent.freshActorObservationPin),'financial_boundary_intent_links');
  for(const r of [intent,inspection]) demand(r.rawCurrentProof?.rows===23504&&r.rawCurrentProof.files===47010&&r.rawCurrentProof.copies===3&&r.rawCurrentProof.knownEstimatedNanoCny==='247731051080'&&pinEqual(r.rawCurrentProof.indexPin,INDEX)&&r.rawCurrentProof.lastRowSha256==='5c270ffe85caa3a8bf31f648aceb160ab14ca699c9398e331ed05b64688498c0','financial_boundary_full_index_claim');
  demand(Date.parse(ack.observedAtUtc)>=Date.parse(intent.observedAtUtc)&&Date.parse(intent.observedAtUtc)>=Date.parse(inspection.observedAtUtc),'financial_boundary_time_order');
  return {fixedRun:FINANCIAL_RUN,financialOnly:true,scoreCertificate:false,oldUnknownSettled:false};
}
function nativeEvidence(pin:Pin,home:string){
  const r=record(pin,home);assertNativeOwnerClosure(r,ACTORS);demand(r.fixture===false&&pinEqual(r.sourcePin,SOURCE),'historical_native_source');
  const q=record(r.requestPin,home);for(const p of [r.stdoutPin,r.stderrPin]){regular(p.path,home);verifyPin(p);}verifyPin(q.hostBun);verifyPin(q.queryExecutablePin);
  demand(q.protocol==='financial-owner-native-request-v1'&&q.fixture===false&&q.timeoutMs===10000&&pinEqual(q.sourcePin,SOURCE)&&same(q.actors,ACTORS)&&q.hostPid===r.hostPid&&resolve(q.queryExecutablePin.path)==='C:\\Windows\\System32\\WindowsPowerShell\\v1.0\\powershell.exe','historical_native_request');
  const command=`$ErrorActionPreference='Stop'; $ProgressPreference='SilentlyContinue'; [Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); $rows=@(); foreach($idValue in @(${ACTORS.pids.join(',')})){ try { $p=[System.Diagnostics.Process]::GetProcessById([int]$idValue); $rows+=@{pid=[int]$idValue;state='present';name=$p.ProcessName;startTimeUtc=$p.StartTime.ToUniversalTime().ToString('o')} } catch [System.ArgumentException] { $rows+=@{pid=[int]$idValue;state='absent';name=$null;startTimeUtc=$null} } catch { $rows+=@{pid=[int]$idValue;state='unknown';error=$_.Exception.GetType().FullName} } }; $native=@([System.Net.NetworkInformation.IPGlobalProperties]::GetIPGlobalProperties().GetActiveTcpListeners()); $ports=@(); foreach($portValue in @(${ACTORS.ports.join(',')})){ $hits=@($native|Where-Object {$_.Port -eq $portValue}); $ports+=@{port=[int]$portValue;nativeListening=($hits.Count -gt 0);listeners=@($hits|ForEach-Object {@{address=[string]$_.Address;port=[int]$_.Port}})} }; @{protocol='financial-owner-native-query-v1';queryHostPid=$PID;portQuery='IPGlobalProperties.GetActiveTcpListeners';processes=@($rows);ports=@($ports)}|ConvertTo-Json -Depth 7 -Compress;`;
  demand(q.command===command&&same(JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(readFileSync(r.stdoutPin.path))),r.parsed),'historical_native_raw_not_same_query');return r;
}
async function fullIndex(report:any){
  verifyPin(INDEX);let carry=Buffer.alloc(0),expanded=0,rows=0,files=0,copies=0,known=0n,usd=0,chain='58686eaecd47e1f86c89eef544ad72966afc2abf420b5fccca2706fb9c35d244';const seqs=new Set<number>();
  for await(const chunk of createReadStream(INDEX.path).pipe(createGunzip())){expanded+=chunk.length;demand(expanded<=96*1024**2,'historical_index_expansion');carry=Buffer.concat([carry,Buffer.from(chunk)]);let nl:number;
    while((nl=carry.indexOf(10))>=0){const line=carry.subarray(0,nl+1);demand(line.length<=65536,'historical_index_line');const r=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(line.subarray(0,-1)));demand(Buffer.from(JSON.stringify(r)+'\n').equals(line)&&r.previousRowSha256===chain&&Number.isSafeInteger(r.requestSeq)&&r.requestSeq>=0&&r.requestSeq<23504&&!seqs.has(r.requestSeq),'historical_index_chain_duplicate');seqs.add(r.requestSeq);chain=hash(line);rows++;
      regular(join(STORE,`provider-${r.requestSeq}-request.json.gz`),STORE);gzipProof({path:join(STORE,`provider-${r.requestSeq}-request.json.gz`),bytes:r.request.bytes,sha256:r.request.sha256},r.request.rawSha256,undefined,4*1024**2);files++;
      if(r.requestSeq===23503)demand(r.providerAttempted===false&&r.response===null&&r.usage===null&&r.servedModel===null&&r.knownEstimatedNanoCny==='0'&&r.usdUpperBound===0&&r.fallbackCopies.length===0,'historical_denial_not_zero');
      else{demand(r.providerAttempted===true&&r.servedModel==='deepseek-flash'&&r.response&&r.usage,'historical_response_unknown');const path=join(STORE,`provider-${r.requestSeq}-response.json.gz`);regular(path,STORE);const raw=gzipProof({path,bytes:r.response.bytes,sha256:r.response.sha256},r.response.rawSha256),data=JSON.parse(raw.toString('utf8'));demand(data.model===r.servedModel&&same(data.usage,r.usage),'historical_usage_model');files++;
        for(const c of r.fallbackCopies){const seq:Record<number,number>={1:23500,2:23502,3:23482};demand(seq[c.receiptIndex]===r.requestSeq&&resolve(c.pin.path)===join(STORE,'journal-failures',`failure-${c.receiptIndex}-response.json.gz`)&&c.rawSha256===r.response.rawSha256,'historical_copy_identity');regular(c.pin.path,STORE);demand(gzipProof(c.pin,c.rawSha256).equals(raw),'historical_copy_raw');files++;copies++;}
      }demand(typeof r.knownEstimatedNanoCny==='string'&&/^\d+$/.test(r.knownEstimatedNanoCny)&&Number.isFinite(r.usdUpperBound)&&r.usdUpperBound>=0,'historical_cost_unknown');known+=BigInt(r.knownEstimatedNanoCny);usd+=r.usdUpperBound;carry=carry.subarray(nl+1);
    }demand(carry.length<=65536,'historical_index_line');
  }
  demand(!carry.length&&rows===23504&&seqs.size===rows&&files===47010&&copies===3&&known.toString()==='247731051080'&&Math.abs(usd-FINANCIAL_KNOWN_USD)<1e-9&&chain===report.compressedRequestEvidence.lastRowSha256,'historical_index_incomplete');verifyPin(INDEX);return{rows,files,copies,indexPin:INDEX,lastRowSha256:chain};
}

/** No canonical lock is read or deleted. A later different owner is handled by that owner's wx/assertOwned guard. */
export async function verifyFinancialInterruptedBoundary(input:FinancialInterruptedBoundary){
  demand(pinEqual(input.acknowledgementPin,ACK)&&pinEqual(input.originalLockArchivePin,LOCK_ARCHIVE),'actual_financial_boundary_pins_required');
  verifyPin(SOURCE);verifyPin(REPORT);verifyPin(FIRST);verifyPin(REGISTRY);const report=jsonPin(REPORT);assertFixedFinancialReport(report);const first=jsonPin(FIRST),registry=jsonPin(REGISTRY);
  demand(same(first.lock.pin,LOCK)&&registry.protocol==='paid-resource-v2-run'&&registry.runId===FINANCIAL_RUN&&registry.closedPin===null&&registry.released===undefined,'historical_registry_not_original');
  regular(input.originalLockArchivePin.path,ROOT);verifyPin(input.originalLockArchivePin);demand(input.originalLockArchivePin.bytes===432&&input.originalLockArchivePin.sha256===LOCK.sha256&&resolve(input.originalLockArchivePin.path)!==resolve(LOCK.path),'immutable_original_lock_archive_required');
  demand(lstatSync(input.originalLockArchivePin.path).nlink===1,'independent_original_lock_archive_required');
  const ack=record(input.acknowledgementPin,HOME),home=dirname(resolve(input.acknowledgementPin.path));demand(home===ACTUAL_HOME&&pinEqual(ack.releaseIntentPin,INTENT)&&pinEqual(ack.inspectionPin,INSPECTION),'historical_graph_exact_paths');
  const intent=record(ack.releaseIntentPin,home),inspection=record(ack.inspectionPin,home),review=record(ROOT_REVIEW,home);
  demand(review.protocol==='financial-owner-release-root-reviewed-v1'&&review.allowExactLockRelease===true&&pinEqual(review.source,SOURCE)&&pinEqual(review.inspection,INSPECTION)&&pinEqual(review.originalLockArchive,LOCK_ARCHIVE)&&same(review.owner,first.lock.record)&&same(review.actors,ACTORS)&&review.scoreCertificate===false&&review.futurePaidLaunchAuthorizedByThisReview===false&&review.originalRegistryMayBeRewritten===false&&review.oldUnknownMayBeSettled===false&&review.fullScienceContinuationAuthorized===false&&review.models===0,'root_release_review_binding');verifyPin(review.peer);
  assertFinancialReleaseGraph({ack,intent,inspection,archiveOwner:jsonPin(input.originalLockArchivePin),originalOwner:first.lock.record});
  nativeEvidence(inspection.actorObservationPin,home);const fresh=nativeEvidence(ack.freshActorObservationPin,home);demand(Date.parse(fresh.completedAtUtc)<=Date.parse(intent.observedAtUtc)&&Date.parse(intent.observedAtUtc)-Date.parse(fresh.completedAtUtc)<=30000,'historical_fresh_owner_expired');
  demand(!existsSync(join(home,'release-failure.json')),'historical_release_failed');verifyPin(IDENTITY);const identity=jsonPin(IDENTITY);for(const p of [identity.rawQueryPin,identity.extractorSourcePin,identity.readerReviewPin,identity.snapshotReceiptPin,...identity.snapshotPins,...identity.originalSourcePins])verifyPin(p,undefined,512*1024**2);
  for(const p of [...report.metadataInputPins,...report.inputPins,...report.observations,report.archivePin,report.auditSourcePin])verifyPin(p);
  const source=jsonPin(actualPin(join(META,'source.json'))),frozen=jsonPin(actualPin(join(META,'frozen-source.json')));demand(source.files.length+source.repairFiles.length===81&&frozen.dependencyFiles.length===4100,'historical_source_count');for(const p of [...source.files,...source.repairFiles,...frozen.dependencyFiles])verifyPin({...p,path:resolve(ROOT,p.path)});
  demand(!existsSync(join(META,'api-ledger.json'))&&!existsSync(join(META,'summary.json'))&&!existsSync(join(STORE,'currency/cash-close.json')),'historical_partial_fabricated_close');const raw=await fullIndex(report);
  for(const p of [SOURCE,REPORT,INDEX,FIRST,REGISTRY,ROOT_REVIEW,input.acknowledgementPin,input.originalLockArchivePin,ack.releaseIntentPin,ack.inspectionPin,ack.freshActorObservationPin])verifyPin(p);
  return Object.freeze({protocol:'financial-interruption-historical-boundary-v1',fixedRun:FINANCIAL_RUN,financialOnly:true as const,scoreCertificate:false as const,originalRegistryReleased:false as const,originalUnknownSettled:false as const,carriedOriginalUnknownNanoCny:'8392180000',knownEstimatedNanoCny:'247731051080',knownRecordedUsageUpperBoundUsd:FINANCIAL_KNOWN_USD,acknowledgementPin:input.acknowledgementPin,originalLockArchivePin:input.originalLockArchivePin,originalRegistryPin:REGISTRY,financialReportPin:REPORT,raw});
}
