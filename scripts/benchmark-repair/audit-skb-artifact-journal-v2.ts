/** Independent journal/cash/provider/task partition audit with actual native replay. */
import { spawn } from 'node:child_process';
import { randomBytes } from 'node:crypto';
import { existsSync,readFileSync } from 'node:fs';
import { join } from 'node:path';
import { actualPin,demand,gzipProof,hash,jsonPin,same,verifyPin,type Pin } from './paid-resource-proof-v2.ts';
import { inspectCampaignJournal } from './campaign-journal.ts';
import { verifyCashClosure } from './cny-cash-shadow-v2.ts';
import { verifyBenchmarkCashClosure } from './benchmark-usd-cash.ts';
import { validateSkbRecipe,type SkbRecipe } from './skb-artifact-recipe-v2.ts';
import { skbArtifactGeneration,artifactCollectionAcceptance } from './skb-artifact-journal-contract-v2.ts';
import { skbStoppedSnapshot } from './skb-artifact-runtime-v2.ts';
import { durableJpgJson } from './jpg-paid-resource-admission-v1.ts';
import { loadNativePython } from './skb-jpg-native-python.ts';

export async function auditSkbCampaign(recipePin:Pin,kind:'score'|'financial-abort'|'local-mock'){
  const r=jsonPin(recipePin) as SkbRecipe,{storage}=validateSkbRecipe(r);const inputArtifacts:Pin[]=[];
  const read=(name:string)=>{const p=actualPin(join(r.output,name));inputArtifacts.push(p);return jsonPin(p);};
  const raw=read('raw-close.json'),summary=read('summary.json'),source=read('source-close.json'),owned=read('owned-close.json'),accounting=jsonPin(raw.accountingPin);
  const secretRef=read('secret-audit-reference.json'),secret=jsonPin(secretRef.secretAuditPin),secretCaller=read('secret-audit-caller.json');
  inputArtifacts.push(secretRef.secretAuditPin);demand(secret.noActualSecretValueFound===true&&secret.noPrivateEngineConfigsRemain===true&&secret.actualSecretValueCount>0
    &&secret.secretValuesSerialized===false&&same(secret.storageDescriptorPin,r.storageDescriptorPin)&&secretCaller.exitCode===0&&secretCaller.directWaitReturned===true
    &&secretCaller.sourcePin.sha256===secret.sourcePin.sha256,'skb_audit_actual_secret_values');
  for(const p of secret.scannedFiles)verifyPin(p,undefined,1536*1024**2);
  inputArtifacts.push(raw.accountingPin,accounting.cashPin,r.freezePin,recipePin,...r.sourcePins);
  demand(same(source.pins,r.sourcePins)&&same(source.freezePin,r.freezePin),'skb_audit_frozen_source');
  const usd=r.currency==='USD',journal=inspectCampaignJournal(storage.directories.journal!),cash=usd?verifyBenchmarkCashClosure(accounting.cashPin):verifyCashClosure(accounting.cashPin);
  demand(journal.valid&&journal.accountingClosed&&cash.proof.snapshot.pendingCount===0&&(usd?cash.proof.snapshot.pendingReservationUsd===0:cash.proof.snapshot.newPendingPeakNanoCny==='0'),'skb_audit_cash_pending');
  demand(cash.config.runId===r.runId&&cash.config.providerKind===r.providerKind,'skb_audit_cash_family');
  if(r.providerKind==='real-provider'&&usd)demand(cash.config.currency==='USD'&&cash.config.scope==='production','skb_audit_openrouter_cash');
  if(r.providerKind==='real-provider'&&!usd)demand(cash.config.carryNanoCny==='8392180000'&&cash.config.envelopeNanoCny==='100000000000'
    &&jsonPin(cash.config.admissionPin).balanceOverride.balanceIsPrecondition===false,'skb_audit_human_override');
  const ledgerPath=join(storage.directories.taskmeta!,'api-ledger.json');
  let ledger:any;if(existsSync(ledgerPath)){const p=actualPin(ledgerPath);inputArtifacts.push(p);ledger=jsonPin(p);}
  const routes=new Set(r.taskSchedule.map(x=>x.route)),seen=new Set<number>(),records=raw.taskPins.map((p:Pin)=>{inputArtifacts.push(p);return jsonPin(p);});
  for(const record of records){
    const db=record.databasePins.find((p:Pin)=>p.path.endsWith('h2h.sqlite'));demand(db,'skb_audit_actual_database');
    const snapshot=skbStoppedSnapshot(db.path,record.id);
    demand(same(snapshot.trace,record.trace)&&same(snapshot.units,record.units)&&hash(snapshot.candidate?.body??'')===record.candidateSha256,'skb_audit_raw_trace');
    const classified=skbArtifactGeneration({runtimeVerdict:record.runtimeVerdict,state:record.state,calls:record.apiCalls,trace:record.trace,candidate:snapshot.candidate?.body,
      deadline:record.deadlineUnixMs,receipts:record.toolQuiescence.receipts,capture:record.artifactCapture});
    demand(same(classified,record.generationClassification),'skb_audit_generation_replay');
    let evaluation:any;
    if(record.finalGradeOwnerPin){
      const owner=jsonPin(record.finalGradeOwnerPin);evaluation=jsonPin(owner.resultPins['private-result.json']).evaluation;
      demand(same(evaluation,record.finalEvaluation)&&same(owner.capturePin,record.artifactCapture.capturePin),'skb_audit_final_grade_binding');
    }
    const dp=record.taskDescriptorPin,cp=record.artifactCapture.capturePin;
    const verdict=evaluation?.valid?{valid:true as const,ran:true as const,reward:evaluation.officialReward,allTestsPassed:evaluation.allTestsPassed,
      completedTests:evaluation.passedTests+evaluation.failedTests,passedTests:evaluation.passedTests,failedTests:evaluation.failedTests,collectionComplete:true as const,
      collectionPin:jsonPin(dp).expectedCollectionPin,taskDescriptorPin:dp,artifactSha256:record.artifactCapture.state==='regular'?jsonPin(cp).artifactPin.sha256:null,
      candidateExecutablesUsed:false as const,candidateSnapshotUsed:false as const,hostBinds:false as const,graderNetwork:'none' as const}:undefined;
    const acceptance=artifactCollectionAcceptance({generation:classified,candidateSha256:record.candidateSha256,capturePin:cp,taskDescriptorPin:dp,
      officialVerdict:verdict,rewardKind:record.officialId==='lab-unit-harmonization'?'fractional':'binary'});
    demand(same(acceptance,record.acceptance),'skb_audit_acceptance_replay');
    for(const call of record.apiCalls){
      demand(call.route===record.route&&routes.has(call.route)&&Number.isSafeInteger(call.requestSeq)&&!seen.has(call.requestSeq),'skb_audit_receipt_partition');seen.add(call.requestSeq);
      if(ledger){const {requestSeq,journalRef,...receipt}=call;demand(same(ledger.calls[call.requestSeq],receipt),'skb_audit_ledger_task_receipt');}
    }
  }
  if(kind==='score'||kind==='local-mock')demand(seen.size===journal.snapshot!.acceptedRequestCount,'skb_audit_complete_task_partition');
  // Re-read every raw request/response through the cash proof's journal binding.
  // verifyCashClosure has replayed all framed starts/finishes, including unknowns.
  demand(cash.proof.journalPrefix.bytes===journal.prefix!.bytes&&cash.proof.journalPrefix.lastSha256===journal.prefix!.lastSha256,'skb_audit_journal_cash_prefix');
  let nativeAuditPin:Pin;
  const saved=join(r.output,'independent-audit.json');
  if(existsSync(saved)){
    nativeAuditPin=JSON.parse(readFileSync(saved,'utf8')).nativeAuditPin;verifyPin(nativeAuditPin);
    // Fresh native replay returns its stdout; its observation is read-only.
  }else nativeAuditPin=actualPin(recipePin.path); // replaced after the actual first child
  const file=join(storage.directories.audit!,'final-native-'+randomBytes(16).toString('hex')+'.json'),n=loadNativePython();
  const script=join(import.meta.dir,'audit-skb-artifact-journal-v2.py'),argv=['-B','-X','utf8',script,'--recipe',recipePin.path,'--sha256',recipePin.sha256,'--kind',kind,'--output',file];
  const began=Date.now();let out=Buffer.alloc(0),err=Buffer.alloc(0),code:number|null=null,closed=false,timed=false;
  const child=spawn(n.executable,argv,{windowsHide:true,env:{...process.env,...storage.nativeEnvironment},stdio:['ignore','pipe','pipe']});demand(child.pid,'skb_audit_child');
  child.stdout.on('data',b=>{out=Buffer.concat([out,b]);if(out.length>1024**2)child.kill();});child.stderr.on('data',b=>{err=Buffer.concat([err,b]);if(err.length>1024**2)child.kill();});
  await new Promise<void>((ok,bad)=>{const t=setTimeout(()=>{timed=true;child.kill();},180000);child.once('error',e=>{clearTimeout(t);bad(e);});child.once('exit',c=>{code=c;});child.once('close',()=>{closed=true;clearTimeout(t);ok();});});
  const caller=durableJpgJson(join(storage.directories.audit!,'native-caller-'+randomBytes(16).toString('hex')+'.json'),{protocol:'skillsbench-native-independent-audit-caller-v2',argv,scriptPin:actualPin(script),nativeExecutablePin:actualPin(n.executable),parentPid:process.pid,childPid:child.pid,startedAtUnixMs:began,finishedAtUnixMs:Date.now(),exitCode:code,directChildClosed:closed,timedOut:timed,stdout:out.toString(),stderr:err.toString(),modelCalls:0});
  demand(code===0&&closed&&!timed,'skb_audit_native_replay_failed');const current=jsonPin(actualPin(file));
  if(existsSync(saved)){
    const original=jsonPin(nativeAuditPin);demand(original.recipePin.sha256===current.recipePin.sha256&&original.kind===current.kind&&same(original.taskPins,current.taskPins)
      &&current.ownedActorsClosed&&original.actualTaskRuns===current.actualTaskRuns,'skb_audit_native_current_graph');
  }else nativeAuditPin=actualPin(file);
  inputArtifacts.push(nativeAuditPin,actualPin(script),actualPin(import.meta.path));
  const scoreEligible=kind==='score'&&r.providerKind==='real-provider'&&current.actualDistinctRealTasks===10&&current.realInferenceTaskRuns===20
    &&records.length===20&&records.every((x:any)=>x.finalGradeOwnerPin&&x.finalEvaluation?.valid&&x.generationValid&&x.acceptance.valid)&&journal.eligibleForScoreCertification;
  if(kind==='score')demand(scoreEligible,'skb_audit_score_ineligible');
  demand(summary.actualTaskRuns===records.length&&same(summary.taskPins,raw.taskPins),'skb_audit_summary_inventory');
  // Deterministic certificate fields are replayed; fresh PID/port observations
  // remain in their actual separate native caller/result receipts.
  return {protocol:'skillsbench-ten-independent-audit-v2',family:r.family,runId:r.runId,kind,integrityValid:true,financialClosed:true,
    scoreCertificateValid:scoreEligible,modelCalls:0,actualTaskRuns:records.length,actualDistinctRealTasks:current.actualDistinctRealTasks,
    recordedUsageUpperBoundUsd:journal.snapshot!.recordedUsageUpperBoundUsd,currency:usd?'USD':'CNY',billedUsd:usd?cash.proof.snapshot.billedUsd:undefined,newKnownEstimatedNanoCny:cash.proof.snapshot.newKnownEstimatedNanoCny,
    newUnknownPeakNanoCny:cash.proof.snapshot.newUnknownPeakNanoCny,carriedHistoricalUnknownNanoCny:cash.config.carryNanoCny,originalUnknownSettled:false,
    nativeAuditPin,inputArtifacts,full87Authorized:false,historical85_1Certified:false};
}
