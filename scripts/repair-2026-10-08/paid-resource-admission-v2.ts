import {randomBytes} from 'node:crypto';
import {closeSync,existsSync,fsyncSync,ftruncateSync,mkdirSync,openSync,readFileSync,readdirSync,unlinkSync,writeFileSync} from 'node:fs';
import {spawn, type ChildProcess} from 'node:child_process';
import {basename,join,resolve} from 'node:path';
import {completionFault,validTokenUsage} from './campaign-contract.ts';
import {Pin,Clock,REAL_CLOCK,actualPin,cny,demand,fileHash,gzipProof,inside,jsonPin,nanoCny,requestValues,same,validatePrices,verifyPin} from './paid-resource-proof-v2.ts';
export type {Pin,Clock} from './paid-resource-proof-v2.ts';
export {createCnyCashShadow} from './cny-cash-shadow-v2.ts';
import {verifyCashClosure} from './cny-cash-shadow-v2.ts';
import {ZERO_STARTUP_RUN,verifySpecificStartupClosure} from './scientific-startup-proof.ts';
export const RESOURCE_MODE='carry-science-oom-2026-10-08-v2';
export const FAILED_RUN='repair-2026-10-08T11-00-41-864Z';
export const FAULT_SHA='b56760e02fc14725c7fede86457f6155cb3aa4fdeefa9001b2248282a1cb0357';
export const PRICE_SHA='8c7942c86ac6a768aa8e4ee4944570df91cb2648f700464294cf73a0e521c832';
export const PID_CERT_SHA='b682230ec671fe4294925715806d40ef9af86a32f4279731a3ea0b8093250853';
const PIDS=[50652,38176,87440,96080,96848];
const POSITIONS=[5470,5471,5473,5475];
const MODULE_ROOT=resolve(import.meta.dir,'../..'),SELF=actualPin(import.meta.path);
const INTRINSIC_SOURCES=[SELF,actualPin(join(import.meta.dir,'paid-resource-proof-v2.ts')),actualPin(join(import.meta.dir,'campaign-contract.ts'))];
const LEGACY_CLOSED=[
 {runId:'repair-2026-10-08T06-06-06-739Z',calls:4,sumUsd:0.002552148,pins:[
  ['api-ledger.json',3344,'b1db851f51501cdf180dcb987dcc87459b7077fdb14c71f1f546abc78a7a4e73'],
  ['summary.json',7309,'2c5294c4cc9052a03fc437cc9c22d0a388fe27d864072ea696eada9a37a63bd2'],
  ['source.json',42533,'984156a8a106af27838b432a2c520e269fb0e045d2d52339afc5880b68eb6264'],
  ['manifest.json',2068,'918991d3e458ac1494cac4c6f668b7bd9c720596e283ebf2fee1039899add0b1'],
  ['frozen-source.json',797462,'963536ce020a5e5f953343fa41844cba6c06d155a2420351c06bcb42eb8d34f6']]},
 {runId:'repair-2026-10-08T06-06-41-201Z',calls:847,sumUsd:1.255665252,pins:[
  ['api-ledger.json',654814,'588d4e11411a7850595b7954fbe80fe7efec6ac55783b2db3b27b9de407d2c7c'],
  ['summary.json',1027957,'d8bd0703becadfe4028e272ecf328202b62ab511e97b8d3ad6aff3042eaac810'],
  ['source.json',42533,'8c5c69ae47566af512fff72f431d96a450881d2400e07dacbae3e4da826bdb42'],
  ['manifest.json',12567,'497907eab8289021ef34ec3295d54331099b397378f6937b1aa271cc6f86b3f7'],
  ['frozen-source.json',797462,'bc0e614dd1b169bb7a4feb31a4cb8fd236063b4645d67afa75b1fb78d531dfb5']]}
]as const;
const LEGACY_FULL_RAW=[
 {runId:'repair-2026-10-08T06-51-16-840Z',calls:8,sumUsd:0.004142688,pins:[
  ['api-ledger.json',13041,'571851d820c2f37a041dbea1cbde3729c03612b969184dc7d8379074fce13d19'],
  ['summary.json',23403,'eccf4e05fc8cc76c223ca62ddac9a44daf22ee61bddd66f50afcce000b76091b'],
  ['source.json',43827,'0280e98da5bec93c3069968a036f7c0b33fbeba1b8760230e3e1f2027616f750'],
  ['manifest.json',4449,'652ea8e117b1ca9ec0b685eea9795ab99f9b930cf16700f77077f85b1f5ccff7'],
  ['frozen-source.json',797462,'e1ac8b3981a3d122eb2339aca0d178bc093e3a4adcc01d3594b8e19f8861ba9b']]},
 {runId:'repair-2026-10-08T06-54-55-267Z',calls:3204,sumUsd:8.376458328,pins:[
  ['api-ledger.json',5102993,'a7e0834d7b793dfaba26014e3da486734859341b508e605b71c67ce44f2bae39'],
  ['summary.json',9191082,'b147fb8d47336addd829c1c65ac6fa521a93322b17e0941c97126d51c547f679'],
  ['source.json',44029,'a897ab0e4b48486b3f63a0e41f16ad2f1c4c6694fddd5b47e9148d5d5f5e532d'],
  ['manifest.json',6323,'db6a5529eaf233c1599a0b65b21d1e44e1404b4504ec39ff68a74fb02e727dab'],
  ['frozen-source.json',797462,'784b931fdac9360a712547057a75ae9c81b6285db37cf6662ab8483cd87f0f68']]}
]as const;
const LEGACY_EMPTY_IDS=['repair-2026-10-08T06-06-34-295Z','repair-2026-10-08T06-50-06-821Z'];
export type PidObservation={pid:number;state:'absent'|'present'|'query_error'};
export type Carry={id:string;ledgerPosition:number;requestSha256:string;peakNanoCny:string;status:'unknown_original_provider_receipt';settled:false};
export interface AdmissionInput{
 root:string;runId:string;entry:string;mode:typeof RESOURCE_MODE;
 balance:Pin;prices:Pin;deferredFault:Pin;originalPidClosure:Pin;
 requestedNewEnvelopeCny:string;minimumHeadroomCny:string;
 executedSourcePins:readonly Pin[];
 expectedOwnedProcessCount:number;
}
export interface ReleaseInput{sourceClosed:Pin;ownedClosed:Pin;rawClosed:Pin;cashClosed:Pin;certification:Pin;}
export type AuditKind='scientific-original'|'scientific-journal';
export interface AuditWrapper{protocol:'paid-admission-audit-wrapper-v2';runId:string;auditorKind:AuditKind;auditorSourcePin:Pin;auditedSummarySha256:string;actualAuditorPins:readonly [Pin];}
export interface AdmissionLease{
 readonly protocol:'paid-resource-admission-v2';readonly root:string;readonly runId:string;readonly path:string;readonly proofPin:Pin;readonly owned:any;
 readonly envelopeNanoCny:bigint;readonly balanceNanoCny:bigint;readonly headroomNanoCny:bigint;readonly carryNanoCny:bigint;readonly carry:readonly Carry[];
 readonly clock:Clock;readonly scope:'production'|'f-fixture';readonly sourcePins:readonly Pin[];
 assertOwned():void;validateForwardSource():void;registerCash(pin:Pin):void;registerOwnedProcess(pin:Pin):void;release(proof:ReleaseInput):Promise<void>;
}
export interface FixtureRuntime{fixtureRoot:string;clock:Clock;pidProbe?:(pids:readonly number[])=>Promise<readonly PidObservation[]>;beforeIo?:(stage:string)=>void;}

function originalPidScript(pids:readonly number[]){
 const text=`$rows=@();foreach($n in @(${pids.join(',')})){try{$p=Get-Process -Id $n -ErrorAction Stop;$created=$null;try{$created=$p.StartTime.ToUniversalTime().ToString('o')}catch{};$rows+=[pscustomobject]@{pid=$n;state='present';name=$p.ProcessName;startedAtUtc=$created}}catch{if($_.FullyQualifiedErrorId -like 'NoProcessFoundForGivenId*'){$rows+=[pscustomobject]@{pid=$n;state='absent'}}else{$rows+=[pscustomobject]@{pid=$n;state='query_error'}}}};ConvertTo-Json -Compress -InputObject $rows`;
 return text;
}
type OwnedProbeResult={pid:number|null;status:number|null;signal:string|null;error:Error&{code?:string};stdout:Buffer;stderr:Buffer;stdoutBytes:number;stderrBytes:number;timedOut:boolean;closeObserved:boolean;exitObserved:boolean;elapsedMonotonicMs:number;killAttempts:unknown[]};
async function runOwnedPidChild(argv:string[]):Promise<Omit<OwnedProbeResult,'error'>&{error:OwnedProbeResult['error']|null}>{
 const started=performance.now(),deadline=started+10000,limit=1048576;
 return await new Promise(resolveResult=>{
  let child:ChildProcess|undefined,settled=false,closed=false,exited=false,timedOut=false,error:(Error&{code?:string})|null=null;
  let status:number|null=null,signal:string|null=null,stdoutBytes=0,stderrBytes=0,stdoutKept=0,stderrKept=0;
  const stdout:Buffer[]=[],stderr:Buffer[]=[],killAttempts:unknown[]=[];
  let deadlineTimer:ReturnType<typeof setTimeout>|undefined,cleanupTimer:ReturnType<typeof setTimeout>|undefined,lastCleanupTimer:ReturnType<typeof setTimeout>|undefined;
  const fault=(reason:string,code:string)=>{if(!error)error=Object.assign(new Error(reason),{code});};
  const finish=()=>{
   if(settled)return;settled=true;clearTimeout(deadlineTimer);clearTimeout(cleanupTimer);clearTimeout(lastCleanupTimer);
   resolveResult({pid:child?.pid??null,status,signal,error,stdout:Buffer.concat(stdout),stderr:Buffer.concat(stderr),stdoutBytes,stderrBytes,timedOut,
    closeObserved:closed,exitObserved:exited,elapsedMonotonicMs:performance.now()-started,killAttempts});
  };
  const stopOwned=(reason:string,requestedSignal:'SIGTERM'|'SIGKILL'='SIGTERM')=>{
   if(closed||!child||!Number.isSafeInteger(child.pid)||(child.pid??0)<=0)return;
   try{killAttempts.push({pid:child.pid,reason,signal:requestedSignal,elapsedMonotonicMs:performance.now()-started,returned:child.kill(requestedSignal)});}
   catch(cause){killAttempts.push({pid:child.pid,reason,signal:requestedSignal,error:String(cause).slice(0,2048)});}
  };
  const awaitOwnedClose=()=>{
   if(cleanupTimer||closed)return;
   cleanupTimer=setTimeout(()=>{
    if(closed)return;stopOwned('owned_child_close_grace_exceeded','SIGKILL');
    lastCleanupTimer=setTimeout(()=>{if(!closed){fault('Owned PID child closure not confirmed','EOWNEDCLOSE');finish();}},2000);
   },3000);
  };
  const armDeadline=()=>{
   const remaining=deadline-performance.now();
   if(remaining>0){deadlineTimer=setTimeout(armDeadline,Math.ceil(remaining));return;}
   if(closed)return;timedOut=true;fault('Owned PID child reached the monotonic10000ms deadline','ETIMEDOUT');
   stopOwned('monotonic_deadline');awaitOwnedClose();
  };
  const capture=(stream:'stdout'|'stderr',data:Buffer|string)=>{
   const raw=Buffer.isBuffer(data)?data:Buffer.from(data);
   if(stream==='stdout'){stdoutBytes+=raw.length;const keep=raw.subarray(0,Math.max(0,limit-stdoutKept));if(keep.length){stdout.push(Buffer.from(keep));stdoutKept+=keep.length;}}
   else{stderrBytes+=raw.length;const keep=raw.subarray(0,Math.max(0,limit-stderrKept));if(keep.length){stderr.push(Buffer.from(keep));stderrKept+=keep.length;}}
   if(stdoutBytes>limit||stderrBytes>limit){fault('PID query stream exceeds1048576bytes','ENOBUFS');stopOwned('bounded_stdio');awaitOwnedClose();}
  };
  try{
   // No runtime timeout option: the deadline is checked against a separate monotonic clock.
   child=spawn('powershell.exe',argv,{windowsHide:true,stdio:['ignore','pipe','pipe']});
   child.on('error',cause=>{if(!error)error=cause;stopOwned('child_error');awaitOwnedClose();});
   child.on('exit',(code,childSignal)=>{exited=true;status=code;signal=childSignal;});
   child.on('close',(code,childSignal)=>{
    closed=true;status=code;signal=childSignal;
    if(performance.now()>=deadline){timedOut=true;fault('PID query completed after the monotonic10000ms deadline','ETIMEDOUT');}
    finish();
   });
   if(!child.stdout||!child.stderr){fault('Owned PID stdio pipes unavailable','ESTDIO');stopOwned('stdio_unavailable');awaitOwnedClose();}
   else{
    child.stdout.on('data',data=>capture('stdout',data));child.stderr.on('data',data=>capture('stderr',data));
    for(const stream of [child.stdout,child.stderr])stream.on('error',cause=>{if(!error)error=cause;stopOwned('stdio_error');awaitOwnedClose();});
   }
   armDeadline();
  }catch(cause){if(!error)error=cause as Error;if(child){stopOwned('child_setup_error');awaitOwnedClose();armDeadline();}else finish();}
 });
}
async function capturedPidProbe(pids:readonly number[],text:string,fixtureScenario?:'timeout'|'invalid-json'):Promise<readonly PidObservation[]>{
 const started=Date.now(),base=fixtureScenario?'.scratch/paid-pid-probe-fixtures':'docs/repair-2026-10-08/pid-probe-records';
 const directory=join(MODULE_ROOT,base,`${started}-${process.pid}-${randomBytes(8).toString('hex')}`);
 const context={protocol:'paid-original-pid-probe-v1',pids:[...pids],hostPid:process.pid,hostExecutable:process.execPath,hostBunVersion:Bun.version,cwd:process.cwd(),sourcePin:SELF,
  startedAtUtc:new Date(started).toISOString(),command:'powershell.exe',argv:['-NoProfile','-NonInteractive','-Command',text],timeoutMs:10000,maxBufferBytes:1048576,
  backend:'asynchronous-owned-child-monotonic-deadline',fixtureScenario:fixtureScenario??null,productionLockAcquiredByProbe:false,modelCalls:0};
 const unknown=()=>pids.map(pid=>({pid,state:'query_error' as const}));
 let child:Awaited<ReturnType<typeof runOwnedPidChild>>|undefined,parsed:unknown,parseError:string|undefined;
 try{
  mkdirSync(directory,{recursive:true});writeOwned(join(directory,'context.json'),context);
  child=await runOwnedPidChild(context.argv);
  const stdout=child.stdout,stderr=child.stderr;
  const rawPin=(name:string,raw:Buffer,observedBytes:number)=>{
   const captured=raw.subarray(0,1048576),path=join(directory,name),fd=openSync(path,'wx',0o600);
   try{writeFileSync(fd,captured);fsyncSync(fd);}finally{closeSync(fd);}
   const pin=actualPin(path);demand(readFileSync(path).equals(captured),'pid_probe_raw_readback');
   return{...pin,observedBytes,truncated:observedBytes!==captured.length};
  };
  const stdoutPin=rawPin('stdout.bin',stdout,child.stdoutBytes),stderrPin=rawPin('stderr.bin',stderr,child.stderrBytes);
  let observed:readonly PidObservation[]=unknown();
  const error=child.error;
  if(!error&&!child.timedOut&&child.closeObserved&&child.status===0&&!stdoutPin.truncated&&!stderrPin.truncated){
   try{
    parsed=JSON.parse(stdout.toString('utf8'));
    if(!Array.isArray(parsed)||parsed.some(row=>!row||!Number.isSafeInteger(row.pid)||!['absent','present','query_error'].includes(row.state)))throw new Error('pid_probe_observation_schema');
    observed=parsed as PidObservation[];
   }catch(cause){parseError=String(cause).slice(0,2048);}
  }
  const e=error as {name?:string;code?:string;errno?:string|number;syscall?:string;message?:string}|undefined;
  writeOwned(join(directory,'result.json'),{...context,endedAtUtc:new Date().toISOString(),elapsedMs:Date.now()-started,elapsedMonotonicMs:child.elapsedMonotonicMs,childPid:child.pid,status:child.status,signal:child.signal,
   error:e?{name:e.name??null,code:e.code??null,errno:e.errno??null,syscall:e.syscall??null,message:String(e.message??error).slice(0,2048)}:null,
   timedOut:child.timedOut,ownedChildCloseObserved:child.closeObserved,ownedChildExitObserved:child.exitObserved,killAttempts:child.killAttempts,
   stdoutPin,stderrPin,parsed:parsed??null,parseError:parseError??null,observed,diagnosticFsyncReturned:true,diagnosticReadbackReturned:true});
  return observed;
 }catch(error){
  // An unavailable durable diagnostic is still an unknown PID state, never permission to continue.
  try{writeOwned(join(directory,'diagnostic-failure.json'),{...context,endedAtUtc:new Date().toISOString(),reason:String(error).slice(0,2048),observed:unknown(),guardDenied:true});}catch{}
  return unknown();
 }
}
async function pidProbe(pids:readonly number[]){return capturedPidProbe(pids,originalPidScript(pids));}
/** Read-only original five-PID diagnostic; this never acquires an admission or lock. */
export function observeOriginalPaidPids(){return pidProbe(PIDS);}
export async function observeSpecificUnstartedActor(){
 const base=join(MODULE_ROOT,'docs/repair-2026-10-08/pid-probe-records'),before=new Set(existsSync(base)?readdirSync(base):[]);
 const observed=await pidProbe([110336]),created=readdirSync(base).filter(name=>!before.has(name));demand(created.length===1,'startup_actor_record_count');
 return{observed,recordPin:actualPin(join(base,created[0],'result.json'))};
}
/** Fixed harmless F-only controls of the same child/diagnostic path; never an admission or alternative PID guard. */
export function exercisePidProbeFixture(scenario:'timeout'|'invalid-json'){
 demand(['timeout','invalid-json'].includes(scenario),'pid_fixture_scenario');
 const text=scenario==='timeout'?"Start-Sleep -Milliseconds 12000;Write-Output 'public timeout fixture'":"Write-Output 'public invalid PID JSON fixture'";
 return capturedPidProbe(PIDS,text,scenario);
}
export function assertPidsAbsent(expected:readonly number[],observed:readonly PidObservation[]){demand(observed.length===expected.length&&new Set(observed.map(x=>x.pid)).size===expected.length&&expected.every(pid=>observed.some(x=>x.pid===pid&&x.state==='absent')),'original_pid_present_or_unknown');}
function ttl(value:string,now:number,limit:number){const at=Date.parse(value);demand(Number.isFinite(at)&&at<=now&&now-at<=limit,'resource_pin_expired_or_clock_invalid');}
function writeOwned(path:string,value:any,hook?:FixtureRuntime['beforeIo']){
 const fd=openSync(path,'wx',0o600);try{writeFileSync(fd,JSON.stringify(value,null,2)+'\n');hook?.('admission_fsync');fsyncSync(fd);}finally{closeSync(fd);}demand(same(JSON.parse(readFileSync(path,'utf8')),value),'admission_readback');return actualPin(path);
}
function fixedInput(given:AdmissionInput):AdmissionInput{
 const pin=(p:Pin)=>Object.freeze({...p});
 return Object.freeze({...given,balance:pin(given.balance),prices:pin(given.prices),deferredFault:pin(given.deferredFault),originalPidClosure:pin(given.originalPidClosure),executedSourcePins:Object.freeze(given.executedSourcePins.map(pin))});
}

/** Read the actual auditor outputs and their input graph, not a wrapper bool. */
export function verifyPaidResourceCertification(pin:Pin,expectedRun:string,expectedBounds:Record<string,Pin>,expectedSourcePins:readonly Pin[],cashProof:any){
 const cert=jsonPin(pin);demand(cert.protocol==='paid-resource-final-certificate-v2'&&cert.runId===expectedRun&&same(cert.boundPins,expectedBounds)&&Array.isArray(cert.auditPins)&&cert.auditPins.length===2,'final_certification_binding');
 const summary=jsonPin(cert.summaryPin);demand(summary.campaign===expectedRun&&summary.completed===true&&!summary.fatal,'final_summary_binding');
 const kinds=new Set<AuditKind>();let originalReportPin:Pin|undefined;
 const artifacts=new Map<string,Pin>();
 for(const wrapperPin of cert.auditPins){
  const wrapper=jsonPin(wrapperPin);demand(wrapper.protocol==='paid-admission-audit-wrapper-v2'&&wrapper.runId===expectedRun&&wrapper.auditedSummarySha256===cert.summaryPin.sha256&&Array.isArray(wrapper.actualAuditorPins)&&wrapper.actualAuditorPins.length===1&&(wrapper.auditorKind==='scientific-original'||wrapper.auditorKind==='scientific-journal')&&!kinds.has(wrapper.auditorKind),'final_audit_binding');
  const kind:AuditKind=wrapper.auditorKind;kinds.add(kind);verifyPin(wrapper.auditorSourcePin);const sourceName=kind==='scientific-original'?'audit-scientific-campaign.py':'audit-scientific-journal.py';demand(basename(wrapper.auditorSourcePin.path)===sourceName&&expectedSourcePins.some(p=>same(p,wrapper.auditorSourcePin)),'audit_executed_source_binding');
  const reportPin=wrapper.actualAuditorPins[0],report=jsonPin(reportPin);demand(report.integrityValid===true&&report.scoreCertificateValid===true&&report.scriptSha256===wrapper.auditorSourcePin.sha256&&Array.isArray(report.errors)&&report.errors.length===0,'actual_auditor_failed');
  const inputs:Pin[]=kind==='scientific-original'?Object.values(report.inputArtifacts??{}):report.inputArtifacts;
  demand(Array.isArray(inputs)&&inputs.length>=5,'audit_actual_inputs_missing');
  for(const item of inputs){verifyPin(item);const name=basename(item.path),prior=artifacts.get(name);if(prior)demand(prior.sha256===item.sha256&&prior.bytes===item.bytes,'audit_input_disagreement');else artifacts.set(name,item);}
  const summaryInput=inputs.filter(item=>basename(item.path)==='summary.json');demand(summaryInput.length===1&&summaryInput[0].sha256===cert.summaryPin.sha256&&summaryInput[0].bytes===cert.summaryPin.bytes&&resolve(summaryInput[0].path)===resolve(cert.summaryPin.path),'audit_current_summary_binding');
  if(kind==='scientific-original'){
   demand(report.run===expectedRun&&report.originalCampaignCompleted===true&&!report.originalFatal&&Array.isArray(report.receiptErrors)&&report.receiptErrors.length===0&&Array.isArray(report.taskErrors)&&report.taskErrors.length===0,'actual_original_audit_failed');
   const source=report.source;demand(source&&['recorded_source_digest_matches_its_file_list','recorded_execution_digest_matches','execution_digest_agrees_across_source_frozen_manifest','all_dependency_paths_in_archive','dependency_manifest_digest_matches'].every(key=>source[key]===true)&&Array.isArray(source.executed_source_mismatches)&&source.executed_source_mismatches.length===0&&source.archive?.digest_matches===true&&source.archive?.bytes_match===true&&Array.isArray(source.archive.member_manifest_mismatches)&&source.archive.member_manifest_mismatches.length===0&&Array.isArray(source.archive.current_member_mismatches)&&source.archive.current_member_mismatches.length===0,'audit_source_graph_failed');
   demand(expectedSourcePins.some(p=>basename(p.path)==='full-gpqa-inflight-audit.py'&&p.sha256===report.helperScriptSha256),'audit_helper_source_binding');
   demand(report.runtime&&Object.values(report.runtime).every((r:any)=>r.present===true&&r.identityValid===true),'audit_runtime_identity_failed');for(const r of Object.values(report.runtime)as any[])verifyPin(r.artifact);
   originalReportPin=reportPin;
  }else{
   demand(report.campaign===expectedRun&&report.phase==='final'&&report.originalAuditorRequired===true&&report.originalIntegrityValid===true&&report.modelCalls===0&&same(report.journalPrefix,cashProof.journalPrefix),'actual_journal_audit_failed');
   const currentJournal=actualPin(join(cashProof.journalDirectory,'api-events.jsonl'));demand(report.journalFileSha256===currentJournal.sha256,'audit_current_journal_binding');
  }
 }
 demand(kinds.size===2&&originalReportPin,'both_actual_auditors_required');
 for(const name of ['manifest.json','source.json','frozen-source.json','summary.json','api-ledger.json','journal-export.json','worker-closure.json','paid-resource-closure.json','independent-closing-audit.json'])demand(artifacts.has(name),'audit_required_input_missing');
 demand(artifacts.get('independent-closing-audit.json')!.sha256===originalReportPin.sha256,'audit_original_report_reference');
 const ledger=jsonPin(artifacts.get('api-ledger.json')!);demand(ledger.campaign===expectedRun&&ledger.reservedUpperBoundUsd===0&&Object.values(ledger.pending??{}).every(n=>n===0)&&Array.isArray(ledger.calls)&&ledger.calls.every((c:any)=>c.finishedAt&&c.providerAttempted===true&&c.httpStatus===200&&!c.fault&&c.completionValid===true&&c.usage),'audit_closed_ledger_binding');
 return cert;
}
function readFault(input:AdmissionInput){
 demand(input.deferredFault.sha256===FAULT_SHA&&input.prices.sha256===PRICE_SHA&&input.originalPidClosure.sha256===PID_CERT_SHA,'unsupported_fault_or_price_policy');
 const fault=jsonPin(input.deferredFault,input.root);demand(fault.protocol==='saved-scientific-campaign-deferred-fault-v1'&&fault.validated===true&&fault.campaign===FAILED_RUN&&fault.type==='infrastructure_abort_with_unknown_provider_receipts','fault_profile');
 demand(fault.cost.ledgerCalls===5476&&fault.cost.finishedWithReportedUsage===5472&&fault.cost.unfinished===4&&same(fault.deferredCalls.map((x:any)=>x.ledgerPosition),POSITIONS),'fault_count_or_positions');
 const critical:Pin[]=[];
 for(const name of ['manifest.json','source.json','summary.json','api-ledger.json','frozen-source.json','frozen-source.zip']){
  const matches=fault.identity.originalEvidenceFiles.filter((x:any)=>basename(x.path)===name);demand(matches.length===1&&matches[0].unchanged&&same(matches[0].before,matches[0].after),'critical_evidence_missing');const item=matches[0];const pin={path:resolve(input.root,item.path),sha256:item.before.sha256,bytes:item.before.bytes};verifyPin(pin);critical.push(pin);
 }
 const ledger=jsonPin(critical.find(x=>basename(x.path)==='api-ledger.json')!);const summary=jsonPin(critical.find(x=>basename(x.path)==='summary.json')!);
 demand(ledger.campaign===FAILED_RUN&&ledger.calls.length===5476&&summary.completed===false&&!!summary.fatal,'original_ledger_state');
 const pending=ledger.calls.map((x:any,i:number)=>({x,i})).filter(({x}:any)=>!x.finishedAt);demand(same(pending.map(({i}:any)=>i),POSITIONS)&&Math.abs(ledger.reservedUpperBoundUsd-1.258827)<1e-9,'original_pending_changed');
 const carry:Carry[]=[];
 for(const row of fault.deferredCalls){
  const pin={path:resolve(input.root,row.requestGzip.path),sha256:row.requestGzip.sha256,bytes:row.requestGzip.bytes};const raw=gzipProof(pin,row.requestGzip.rawSha256,undefined,4*1024**2),v=requestValues(raw);
  demand(raw.length===row.rawRequestBytes&&v.data.messages.length===row.messageCount&&v.inputUpper===row.inputUpperBoundFromFrozenFormula&&v.output===row.outputLimit,'original_raw_counts');
  const call=ledger.calls[row.ledgerPosition];demand(call.requestSha256===row.requestGzip.rawSha256&&call.providerAttempted===true&&!call.finishedAt&&!call.usage&&!call.responseFile&&!existsSync(join(input.root,'.phase1-data/repair',FAILED_RUN,`provider-${row.ledgerPosition}-response.json.gz`)),'original_unknown_changed');
  critical.push(pin);carry.push({id:FAILED_RUN+'/'+row.ledgerPosition,ledgerPosition:row.ledgerPosition,requestSha256:row.requestGzip.rawSha256,peakNanoCny:v.peakNano.toString(),status:'unknown_original_provider_receipt',settled:false});
 }
 demand(carry.reduce((n,x)=>n+BigInt(x.peakNanoCny),0n)===8392180000n,'carry_cny_mismatch');
 const closed=jsonPin(input.originalPidClosure,input.root);demand(same(closed.processes.map((x:any)=>x.pid),PIDS)&&closed.processes.every((x:any)=>x.present===false),'original_pid_certificate');
 return{fault,critical,carry};
}
function fixedLegacyClosed(home:string,runId:string,ledger:any){
 const policy=LEGACY_CLOSED.find(p=>p.runId===runId);if(!policy)return false;
 for(const [name,bytes,sha256]of policy.pins)verifyPin({path:join(home,name),bytes,sha256});
 const summary=JSON.parse(readFileSync(join(home,'summary.json'),'utf8')),source=JSON.parse(readFileSync(join(home,'source.json'),'utf8')),manifest=JSON.parse(readFileSync(join(home,'manifest.json'),'utf8'));
 demand(ledger.campaign===runId&&summary.campaign===runId&&manifest.campaign===runId&&summary.completed===true&&!summary.fatal&&source.executionDigest===manifest.sourceExecutionDigest&&ledger.calls.length===policy.calls,'fixed_legacy_closure_changed');
 let sum=0;for(const call of ledger.calls){
  demand(typeof call.finishedAt==='string'&&Number.isFinite(Date.parse(call.finishedAt))&&call.httpStatus===200&&!call.fault&&validTokenUsage(call.usage)&&Number.isSafeInteger(call.usage.prompt_tokens)&&Number.isSafeInteger(call.usage.completion_tokens)&&typeof call.usdUpperBound==='number'&&Number.isFinite(call.usdUpperBound)&&call.usdUpperBound>=0,'fixed_legacy_call_unknown');sum+=call.usdUpperBound;
 }
 demand(Number.isFinite(ledger.recordedUsageUpperBoundUsd)&&Number.isFinite(summary.recordedUsageUpperBoundUsd)&&Math.abs(sum-policy.sumUsd)<1e-9&&Math.abs(sum-ledger.recordedUsageUpperBoundUsd)<1e-9&&Math.abs(sum-summary.recordedUsageUpperBoundUsd)<1e-9,'fixed_legacy_amount_changed');
 // Only these ten immutable metadata files permit old known fees; this branch
 // does not certify missing raw wire, body completeness or a CNY invoice.
 return true;
}
function fixedFullRawClosed(home:string,runId:string,ledger:any){
 const policy=LEGACY_FULL_RAW.find(p=>p.runId===runId);if(!policy)return false;
 for(const [name,bytes,sha256]of policy.pins)verifyPin({path:join(home,name),bytes,sha256});
 const summary=JSON.parse(readFileSync(join(home,'summary.json'),'utf8')),source=JSON.parse(readFileSync(join(home,'source.json'),'utf8')),manifest=JSON.parse(readFileSync(join(home,'manifest.json'),'utf8'));
 demand(ledger.campaign===runId&&summary.campaign===runId&&manifest.campaign===runId&&summary.completed===true&&!summary.fatal&&source.executionDigest===manifest.sourceExecutionDigest&&ledger.calls.length===policy.calls&&ledger.calls.every((c:any)=>c.providerAttempted===undefined),'fixed_fullraw_closure_changed');
 const sum=ledger.calls.reduce((n:number,c:any)=>{demand(typeof c.usdUpperBound==='number'&&Number.isFinite(c.usdUpperBound)&&c.usdUpperBound>=0,'fixed_fullraw_fee');return n+c.usdUpperBound;},0);
 demand(Math.abs(sum-policy.sumUsd)<1e-9&&Math.abs(sum-ledger.recordedUsageUpperBoundUsd)<1e-9&&Math.abs(sum-summary.recordedUsageUpperBoundUsd)<1e-9,'fixed_fullraw_amount_changed');return true;
}
function verifiedKnownResponse(call:any,allowedOldAbsentFlag=false){
 demand((call.providerAttempted===true||allowedOldAbsentFlag&&call.providerAttempted===undefined)&&call.responseFile&&call.responseSha256&&call.requestFile&&call.requestSha256,'other_known_raw_missing');
 const requestPin=actualPin(call.requestFile);if(call.requestCompressedSha256!==undefined)demand(requestPin.sha256===call.requestCompressedSha256,'other_known_request_compressed_sha');
 const request=requestValues(gzipProof(requestPin,call.requestSha256,undefined,4*1024**2));const wire=Object.fromEntries(['model','temperature','seed','reasoning_effort','thinking','max_tokens','max_completion_tokens','tool_choice','response_format','stream'].filter(k=>k in request.data).map(k=>[k,request.data[k]]));
 demand(call.requestedModel===request.data.model&&same(wire,call.wireParameters),'other_known_actual_wire');
 const pin=actualPin(call.responseFile);if(call.responseCompressedSha256!==undefined)demand(pin.sha256===call.responseCompressedSha256,'other_known_compressed_sha');
 const raw=gzipProof(pin,call.responseSha256),data=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(raw));
 demand(same(data.usage,call.usage)&&data.model===call.servedModel&&(!call.requestId||data.id===call.requestId)&&!completionFault(data)&&validTokenUsage(data.usage),'other_known_raw_usage_or_completion');
}
/** Scanner does not catch-and-ignore the legacy guard's first error. */
export function scanOtherPaidRuns(root:string,currentRun:string){
 const dir=join(root,'docs/repair-2026-10-08/campaigns');if(!existsSync(dir))return;
 for(const name of readdirSync(dir)){
  if(name===currentRun||name===FAILED_RUN)continue;
  if(name===ZERO_STARTUP_RUN){verifySpecificStartupClosure(root,name);continue;}
  const home=join(dir,name),summary=join(home,'summary.json'),ledger=join(home,'api-ledger.json'),registry=join(home,'paid-resource-v2-run.json');
  if(existsSync(ledger)){const x=JSON.parse(readFileSync(ledger,'utf8'));demand(typeof x.reservedUpperBoundUsd==='number'&&Number.isFinite(x.reservedUpperBoundUsd)&&x.reservedUpperBoundUsd>=-1e-9&&x.reservedUpperBoundUsd<=1e-9,'other_pending_or_invalid_ledger');demand(x.pending&&typeof x.pending==='object'&&Object.values(x.pending).every(n=>typeof n==='number'&&Number.isSafeInteger(n)&&n===0)&&Array.isArray(x.calls),'other_pending_or_invalid_ledger');const pinnedLegacy=fixedLegacyClosed(home,name,x),pinnedFullRaw=fixedFullRawClosed(home,name,x);if(!pinnedLegacy)for(const call of x.calls){demand(typeof call.finishedAt==='string'&&Number.isFinite(Date.parse(call.finishedAt)),'other_unfinished_call');const usage=call.usage;const known=call.httpStatus===200&&!call.fault&&call.completionValid===true&&usage&&Number.isSafeInteger(usage.prompt_tokens)&&usage.prompt_tokens>=0&&Number.isSafeInteger(usage.completion_tokens)&&usage.completion_tokens>=0&&call.responseFile;const noForward=call.providerAttempted===false&&call.costBasis==='known_uncharged'&&call.accountedUpperBoundUsd===0&&call.usdUpperBound===0&&!call.responseFile;let authRefused=false;if(known)verifiedKnownResponse(call,pinnedFullRaw);if(!known&&!noForward&&[401,402,403].includes(call.httpStatus)&&call.costBasis==='known_uncharged'&&call.responseFile&&call.responseSha256){const raw=gzipProof(actualPin(call.responseFile),call.responseSha256);const response=JSON.parse(raw.toString('utf8'));authRefused=!!response.error&&!response.usage&&call.accountedUpperBoundUsd===0&&call.usdUpperBound===0;}demand(known||noForward||authRefused,'other_unknown_provider_call');}}
  if(existsSync(registry)){const r=JSON.parse(readFileSync(registry,'utf8'));demand(r.protocol==='paid-resource-v2-run'&&r.runId===name&&r.closedPin&&r.released===true&&r.certificationPin&&r.releasePins,'other_v2_unclosed');const closed=jsonPin(r.closedPin);demand(closed.protocol==='cny-shadow-close-v2'&&closed.runId===name&&closed.releasePermitted===true&&closed.snapshot.newUnknownCount===0&&closed.snapshot.pendingCount===0,'other_v2_unknown_or_unclosed');verifyCashClosure(r.closedPin);const source=jsonPin(r.releasePins.sourceClosed);demand(source.protocol==='paid-source-close-v2'&&source.runId===name,'other_v2_source_unclosed');for(const p of source.pins)verifyPin(p);const bounds={sourceClosed:r.releasePins.sourceClosed,ownedClosed:r.releasePins.ownedClosed,rawClosed:r.releasePins.rawClosed,cashClosed:r.closedPin};verifyPaidResourceCertification(r.certificationPin,name,bounds,source.pins,closed);}
  if(!existsSync(summary)){const store=join(root,'.phase1-data/repair',name);demand(LEGACY_EMPTY_IDS.includes(name)&&readdirSync(home).length===0&&existsSync(store)&&readdirSync(store).length===0,'unfinished_other_campaign');continue;}
  const x=JSON.parse(readFileSync(summary,'utf8'));demand(x.completed===true||typeof x.fatal==='string'&&x.fatal.length>0,'unfinished_other_campaign');
 }
}

/** Explicit production path. No balance/pricing API is queried by this module. */
export async function acquirePaidResourceAdmissionV2(input:AdmissionInput):Promise<AdmissionLease>{return acquire(input);}
/** Dependency injection is confined to a non-production F fixture root. */
export async function acquirePaidResourceFixtureV2(input:AdmissionInput,runtime:FixtureRuntime):Promise<AdmissionLease>{
 const allowed=join(MODULE_ROOT,'.scratch/paid-resource-admission-v2');demand(inside(allowed,runtime.fixtureRoot)&&resolve(input.root)===resolve(runtime.fixtureRoot)&&resolve(input.root)!==allowed,'fixture_root_required');return acquire(input,runtime);
}
async function acquire(given:AdmissionInput,runtime?:FixtureRuntime):Promise<AdmissionLease>{
 const input=fixedInput(given);
 const root=resolve(input.root),clock=runtime?.clock??REAL_CLOCK;demand(input.mode===RESOURCE_MODE&&/^[a-zA-Z0-9][a-zA-Z0-9._-]{2,160}$/.test(input.runId)&&input.runId!==FAILED_RUN,'explicit_resource_mode_required');
 if(!runtime)demand(root===MODULE_ROOT,'production_root_required');
 const policy=readFault({...input,root}),balance=jsonPin(input.balance,root),prices=validatePrices(input.prices,root),now=clock.wallUnixMs();
 demand(balance.protocol==='deepseek-resource-readonly-v1'&&balance.provider==='https://api.deepseek.com'&&balance.endpoint==='/user/balance'&&balance.method==='GET'&&balance.httpStatus===200&&balance.isAvailable===true&&balance.modelCalls===0&&balance.credentialPrinted===false,'balance_profile');
 ttl(balance.observedAtUtc,now,30*60000);ttl(prices.observedAtUtc,now,24*3600000);
 const rows=balance.balances.filter((x:any)=>x.currency==='CNY');demand(rows.length===1,'balance_cny_missing_or_duplicate');const cash=nanoCny(rows[0].total_balance);demand(nanoCny(rows[0].granted_balance)+nanoCny(rows[0].topped_up_balance)===cash,'balance_components');
 const carry=policy.carry.reduce((n,x)=>n+BigInt(x.peakNanoCny),0n),headroom=nanoCny(input.minimumHeadroomCny),envelope=nanoCny(input.requestedNewEnvelopeCny);demand(headroom>=30000000000n&&envelope>0n&&carry+headroom+envelope<=cash,'cash_envelope_exceeds_fresh_resource');
 demand(Number.isSafeInteger(input.expectedOwnedProcessCount)&&input.expectedOwnedProcessCount>=(runtime?0:1),'expected_owned_process_count');
 const sourcePins=input.executedSourcePins.map(p=>Object.freeze({...p}));demand(sourcePins.length>=1&&sourcePins.some(x=>resolve(x.path)===resolve(input.entry)),'entry_source_pin_required');for(const p of [...INTRINSIC_SOURCES,...sourcePins])verifyPin(p);const executedPins=Object.freeze([...INTRINSIC_SOURCES,...sourcePins]);
 const probe=runtime?.pidProbe??pidProbe;assertPidsAbsent(PIDS,await probe(PIDS));scanOtherPaidRuns(root,input.runId);
 const directory=join(root,'.phase1-data');mkdirSync(directory,{recursive:true});const path=join(directory,'owned-paid-campaign.lock.json');
 const owned={pid:process.pid,startedAt:new Date(now).toISOString(),runId:input.runId,entry:input.entry,ownerNonce:randomBytes(24).toString('hex'),mode:RESOURCE_MODE,policyFaultSha256:FAULT_SHA};
 // wx is the same canonical exclusion namespace; no stale/unknown takeover.
 Object.freeze(owned);writeOwned(path,owned,runtime?.beforeIo);let released=false,cashPin:Pin|undefined;const ownedProcesses:Pin[]=[];
 const assertOwned=()=>{demand(!released&&same(JSON.parse(readFileSync(path,'utf8')),owned),'paid_lock_ownership_changed');};
 const initialPins=[...policy.critical,input.deferredFault,input.originalPidClosure];
 const finalOriginal=()=>{for(const p of initialPins)verifyPin(p,root);};
 try{assertOwned();assertPidsAbsent(PIDS,await probe(PIDS));scanOtherPaidRuns(root,input.runId);}catch(error){assertOwned();unlinkSync(path);throw error;}
 const output=join(root,'docs/repair-2026-10-08/campaigns',input.runId);mkdirSync(output,{recursive:true});
 const proofPath=join(output,'paid-resource-admission.json');const proof={protocol:'paid-resource-admission-v2',runId:input.runId,mode:RESOURCE_MODE,scope:runtime?'f-fixture':'production',createdAt:new Date(now).toISOString(),owned,originalCriticalPins:initialPins,balancePin:input.balance,pricePin:input.prices,entry:input.entry,sourcePins:executedPins,carry:policy.carry,carryNanoCny:carry.toString(),balanceNanoCny:cash.toString(),headroomNanoCny:headroom.toString(),availableNewEnvelopeNanoCny:(cash-carry-headroom).toString(),selectedNewEnvelopeNanoCny:envelope.toString(),selectedNewEnvelopeCny:cny(envelope),balanceTTL:'startup-only30min',priceTTL:'startup-and-real-beforeForward24h',invoice:false,foreignExchangeConversion:false};
 const proofPin=writeOwned(proofPath,proof,runtime?.beforeIo);const registry=join(output,'paid-resource-v2-run.json');writeOwned(registry,{protocol:'paid-resource-v2-run',runId:input.runId,admissionPin:proofPin,closedPin:null},runtime?.beforeIo);
 const validateForwardSource=()=>{assertOwned();for(const p of [...executedPins,input.balance,input.prices])verifyPin(p,root);ttl(prices.observedAtUtc,clock.wallUnixMs(),24*3600000);};
 const lease:AdmissionLease={protocol:'paid-resource-admission-v2',root,runId:input.runId,path,proofPin,owned,envelopeNanoCny:envelope,balanceNanoCny:cash,headroomNanoCny:headroom,carryNanoCny:carry,carry:policy.carry,clock,scope:runtime?'f-fixture':'production',sourcePins:executedPins,assertOwned,validateForwardSource,
  registerCash(pin){assertOwned();demand(!cashPin,'cash_already_registered');const config=jsonPin(pin);demand(config.protocol==='cny-shadow-config-v2'&&config.runId===input.runId&&config.ownerNonce===owned.ownerNonce&&config.envelopeNanoCny===envelope.toString()&&config.carryNanoCny===carry.toString()&&same(config.pricesPin,input.prices)&&same(config.admissionPin,proofPin)&&(runtime||config.providerKind==='real-provider'),'cash_config_binding');cashPin=Object.freeze({...pin});},
  registerOwnedProcess(pin){assertOwned();const p=jsonPin(pin);demand(p.protocol==='paid-owned-process-v2'&&p.runId===input.runId&&p.ownerNonce===owned.ownerNonce&&Number.isSafeInteger(p.pid)&&p.pid>0&&p.pid!==process.pid&&!ownedProcesses.some(x=>jsonPin(x).pid===p.pid),'owned_process_registration');ownedProcesses.push(Object.freeze({...pin}));},
  async release(release){
   assertOwned();demand(cashPin,'cash_not_registered');finalOriginal();for(const p of [...executedPins,input.balance,input.prices])verifyPin(p,root);
   const source=jsonPin(release.sourceClosed),ownedClosed=jsonPin(release.ownedClosed),rawClosed=jsonPin(release.rawClosed),cashClosed=jsonPin(release.cashClosed);
   demand(source.protocol==='paid-source-close-v2'&&source.runId===input.runId&&same(source.pins,executedPins),'source_close_binding');for(const p of source.pins)verifyPin(p);
   demand(ownedClosed.protocol==='paid-owned-close-v2'&&ownedClosed.runId===input.runId&&Array.isArray(ownedClosed.processes)&&Array.isArray(ownedClosed.evidencePins),'owned_close_binding');for(const p of ownedClosed.evidencePins)verifyPin(p);
   const registered=ownedProcesses.map(p=>jsonPin(p));const closePids=ownedClosed.processes.map((x:any)=>x.pid);demand(registered.length===input.expectedOwnedProcessCount&&same(closePids,registered.map(p=>p.pid))&&same(ownedClosed.registrationPins,ownedProcesses)&&closePids.every((x:any)=>Number.isSafeInteger(x)&&x>0&&x!==process.pid)&&new Set(closePids).size===closePids.length,'owned_close_pid_list');assertPidsAbsent(closePids,await probe(closePids));assertPidsAbsent(PIDS,await probe(PIDS));
   demand(rawClosed.protocol==='paid-raw-close-v2'&&rawClosed.runId===input.runId&&same(rawClosed.journalConfigPin,cashClosed.journalConfigPin)&&same(rawClosed.journalPrefix,cashClosed.journalPrefix),'raw_close_prefix_binding');verifyPin(rawClosed.journalConfigPin);for(const p of rawClosed.evidencePins??[])verifyPin(p);
   demand(cashClosed.protocol==='cny-shadow-close-v2'&&cashClosed.runId===input.runId&&cashClosed.ownerNonce===owned.ownerNonce&&cashClosed.releasePermitted===true&&cashClosed.snapshot.pendingCount===0&&cashClosed.snapshot.newUnknownCount===0&&same(cashClosed.configPin,cashPin),'cash_close_binding');
   // The independent reader checks current exact cash prefix and zero state;
   // the close document's boolean is not authority by itself.
   const {verifyCashClosure}=await import('./cny-cash-shadow-v2.ts');verifyCashClosure(release.cashClosed);
   verifyPaidResourceCertification(release.certification,input.runId,{sourceClosed:release.sourceClosed,ownedClosed:release.ownedClosed,rawClosed:release.rawClosed,cashClosed:release.cashClosed},executedPins,cashClosed);
   assertOwned();const record={protocol:'paid-resource-v2-run',runId:input.runId,admissionPin:proofPin,closedPin:release.cashClosed,certificationPin:release.certification,released:true,releasePins:release};const bytes=JSON.stringify(record,null,2)+'\n',fd=openSync(registry,'r+');try{writeFileSync(fd,bytes);ftruncateSync(fd,Buffer.byteLength(bytes));fsyncSync(fd);}finally{closeSync(fd);}demand(same(JSON.parse(readFileSync(registry,'utf8')),record),'release_registry_readback');
   assertOwned();unlinkSync(path);released=true;
  }};
 return Object.freeze(lease);
}
