import {randomUUID,timingSafeEqual} from 'node:crypto';
import {existsSync,mkdirSync,readFileSync,writeFileSync,renameSync,readdirSync} from 'node:fs';
import {join} from 'node:path';
import {Database} from 'bun:sqlite';
import {ROOT,OUT,save} from './prepare.ts';
import {fullFRunId,acquireFullFAdmission,fullFConnection} from '../shared/supplier-shared-admission.ts';
import {inspectFullFClosedCash} from '../shared/supplier-closed-run-cost.ts';
import {loadChemiqFPlan,chemiqObjective,ChemiqRouteSeal,CHEMIQ_F_SETTINGS} from '../../../benchmark-repair/chemiq-f-journal-contract-v3.ts';
import {BENCHMARK_PROVIDER,SUPPLIER} from './task39-supplier-profile.ts';
import {benchmarkProviderKey} from '../../../benchmark-repair/benchmark-provider.ts';
import {BENCHMARK_INFERENCE} from '../shared/supplier-inference.ts';
import {createCampaignJournal} from '../shared/supplier-journal.ts';
import {createBenchmarkCash} from '../shared/supplier-usd-cash.ts';
import {ScientificJournalProxy} from '../shared/supplier-proxy.ts';
import {ChemiqGradingRecorder} from '../../../benchmark-repair/chemiq-f-grading-recorder-v3.ts';
import {classifyGeneration,gradeFixedCandidate} from '../../../benchmark-repair/campaign-contract.ts';
import {actualPin,hash,verifyPin,type Pin} from '../../../benchmark-repair/paid-resource-proof-v2.ts';
import {machine} from './submission-reserve-control-machine.mjs';
import {finalCandidate} from '../../../../app/src/objective/candidate.ts';
import {observeDockerDisk,evaluateDockerDisk,GiB} from '../shared/docker-physical-disk-admission-staged.ts';

function createChemiqModelWitness(options:any){
  const tickets = new Map<number, any>(); let proxy: ScientificJournalProxy;
  proxy = new ScientificJournalProxy(options.journal, { inference: options.inference, provider: options.provider, routes: options.routes, failureDirectory: options.failureDirectory,
    beforeAdmission: options.beforeAdmission,
    beforeForward(admitted, startPrefix, raw, route) {
      const admission = options.cash.beforeForward({ id: options.runId + '/' + admitted.requestSeq, route, rawRequest: Buffer.from(raw), capturedRequest: actualPin(admitted.requestFile), journal: { admitted, startPrefix } });
      tickets.set(admitted.requestSeq, admission.ticket);
      if (!admission.admitted) { options.onFinancialStop(admission.reason!); throw Error('Cash admission denied:' + admission.reason); }
      // The route is checked after the durable ticket too, so queued work cannot pass a late seal.
      options.seal.check(route);
    },
    afterDurableFinish(receipt) {
      const status = options.cash.finish(tickets.get(receipt.requestSeq)!, { kind: 'journal-finish', journalRef: receipt.journalRef });
      if (status.poisoned) proxy.stop('cash:' + status.poisonReason);
    },
    afterFailedJournalCapture(request, _finish, evidence) {
      const seq = request?.requestSeq, ticket = seq === undefined ? undefined : tickets.get(seq);
      if (!ticket) {
        // This branch has not entered journal.admit. Other flights retain their real tickets.
        if (!request && evidence.requestSeq === undefined && evidence.stage === 'before_admission_guard' &&
            evidence.providerAttempted === false && evidence.confirmedNoForward === true &&
            !(evidence.journalSnapshot as any).error && !evidence.evidenceWriteError) return;
        options.cash.poison('unacknowledged_admission'); return;
      }
      if (evidence.journalRef) options.cash.finish(ticket, { kind: 'journal-finish', journalRef: evidence.journalRef as never });
      else {
        const files = evidence.files as Pin[];
        options.cash.finish(ticket, { kind: 'failed-capture', requestSeq: seq!, evidence: { files, responsePin: files.find(p => p.path.endsWith('response.json.gz')),
          rawResponseSha256: evidence.rawResponseSha256 as string, usage: evidence.usage, httpStatus: evidence.httpStatus as number, providerAttempted: evidence.providerAttempted as boolean,
          originalPrefix: (evidence.journalSnapshot as any).durablePrefix, reason: 'source_or_cash_capture_failure' } });
      }
    }, transport: options.transport,
  });
  return proxy;
}

const SEGMENT_SETTINGS=Object.freeze({...CHEMIQ_F_SETTINGS,providerName:BENCHMARK_PROVIDER.providerName,providerSlug:BENCHMARK_PROVIDER.providerSlug});
const utc=()=>new Date().toISOString(),PRIVATE='http://127.0.0.1:17918';
function diskAdmission(evidencePath:string){
  const dockerDataPath='E:/Docker/wsl/disk/docker_data.vhdx',observation=observeDockerDisk(dockerDataPath);
  const policy={nowMs:Date.now(),expectedDrive:'E:',minimumFreeBytes:8*GiB,plannedGrowthBytes:0,maximumAgeMs:30000};
  const result=evaluateDockerDisk(observation,policy);
  atomic(evidencePath,{protocol:'chemiq-docker-physical-disk-admission-v1',atUtc:utc(),dockerDataPath,observation,policy,result,plannedGrowthBasis:'Existing original ChemIQ grader reused; no Docker build, pull or new container; minimum8GiB physicalE reserve remains required',scoreCertificate:false});
  return result;
}
const realScore=(r:any)=>r.generationValid&&r.acceptance?.valid&&(r.index!==39||(r.candidateHow!=="none"&&r.acceptance?.nodes?.correct?.valid===true));
const terminalProtocolFailure=(r:any)=>['done','failed'].includes(r.state)&&(/RequiredToolCallMissing/.test(String(r.runtimeVerdict?.why??''))||r.runtimeVerdict?.outcome==='required_tool_call_missing');
function atomic(path:string,value:any){const temp=path+'.'+randomUUID()+'.tmp';writeFileSync(temp,JSON.stringify(value,null,2)+'\n');const until=Date.now()+3000;for(;;){try{renameSync(temp,path);break;}catch(error){if(Date.now()>=until)throw error;Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,10);}}}
function capture(directory:string,task:any,out:string){
  const db=new Database(join(directory,'data/h2h.sqlite'),{readonly:true});
  try{
    const all=(sql:string,params:any[]=[])=>db.query(sql).all(...params);
    const rows:any[]=all('select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like ? order by unit,seq',[task.taskId+'#%']);
    writeFileSync(join(out,'trace.jsonl'),rows.map(r=>JSON.stringify(r)).join('\n')+'\n');
    const boundaryPath=join(directory,'submission-reserve-boundaries.jsonl');if(existsSync(boundaryPath))writeFileSync(join(out,'submission-reserve-boundaries.jsonl'),readFileSync(boundaryPath));
    const candidate=finalCandidate({all,run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as never,task.taskId);
    const state:any=all('select state,result,created_at,solve_seconds from task where id=?',[task.taskId])[0];
    if(state?.solve_seconds!==900)throw Error('Frozen task deadline mismatch');
    return{candidate,state,trace:rows.filter(r=>r.role==='system'&&r.kind==='inject'),traceRows:rows.length,explicitVerifyCalls:rows.reduce((n,r)=>{try{return n+(r.kind==='call'?JSON.parse(r.body).calls?.filter((c:any)=>c.name==='verify').length??0:0)}catch{return n}},0),tracePin:actualPin(join(out,'trace.jsonl')),taskDatabasePin:actualPin(join(directory,'data/h2h.sqlite'))};
  }finally{db.close();}
}
export async function run(){
  if(SUPPLIER!=='relace')throw Error('Budget variant only Relace scope');
  const review=JSON.parse(readFileSync(join(OUT,'task39-reserve450-entry-approval.json'),'utf8'));
  if(review.approved!==true||review.authorizedByDirectUser!==true||review.onlyIndex!==39||review.retainedValid!==815)throw Error('Await root concrete entry review');
  for(const pin of review.sourcePins)verifyPin(pin);
  const once=join(OUT,'task39-reserve450-launch-issued.json');
  writeFileSync(once,JSON.stringify({atUtc:utc(),pid:process.pid,approvalPin:actualPin(join(OUT,'task39-reserve450-entry-approval.json'))}),{flag:'wx'});
  const env=JSON.parse(readFileSync(join(OUT,'environment-validation.json'),'utf8'));if(!env.valid||env.checked!==816)throw Error('Real grader environment not validated');
  const connection=fullFConnection(ROOT),runId=fullFRunId(ROOT,'chemiq');
  const manifest=JSON.parse(readFileSync(join(OUT,'manifest.json'),'utf8')),plan=loadChemiqFPlan(runId,'full816');
  const taskNamespace='repair-'+Date.now();for(const task of plan.tasks){task.taskId=`${taskNamespace}/chemiq/F0/${task.officialId}`;if(encodeURIComponent(task.taskId).length>100)throw Error('Task ID exceeds route parameter limit');}
  const control=JSON.parse(readFileSync(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/control.json'),'utf8'));
  if((control.provider?.slug??control.provider)!=='digitalocean'||control.dockerBenchResume?.chemiq!==true)throw Error('Await root scoped ChemIQ readiness');
  if(control.broker.runId!==review.connectionRunId||control.broker.pid!==review.connectionPid||!control.broker.sourcePins.some((p:Pin)=>p.path.endsWith('digitalocean-broker-parallel-lanes.next.ts')))throw Error('Reviewed current shared connection changed');
  for(const pin of review.commonSourcePins)verifyPin(pin);
  const immutableSolveSettings=(settings:any)=>{const {providerName,providerSlug,...fixed}=settings;return fixed;};
  if(hash(JSON.stringify(immutableSolveSettings(manifest.settings)))!==hash(JSON.stringify(immutableSolveSettings(SEGMENT_SETTINGS))))throw Error('Frozen solving parameters changed');
  const workerCount=Math.min(8,Number(control.concurrency?.chemicalWorkers??control.concurrency?.perBenchRequests??control.perBenchMaxInFlight??8));if(!Number.isSafeInteger(workerCount)||workerCount<1)throw Error('Invalid shared Bench concurrency');
  const output=join(OUT,'runs',runId),store=join(output,'journal');mkdirSync(output,{recursive:true});
  const diskStartPath=join(output,'disk-admission-start.json');
  if(!diskAdmission(diskStartPath).admissible)throw Error('Docker physicalE disk admission blocked before lane/model dispatch');
  const streamScopePath=join(output,'stream-task-scope.json');
  const scopeTemplate=join(OUT,'task39-supplier-scope-'+SUPPLIER+'.json');
  const scope=JSON.parse(readFileSync(scopeTemplate,'utf8'));
  if(scope.protocol!=='chemiq-task39-supplier-scope-v1'||JSON.stringify(scope.eligibleIndices)!=='[39]'||scope.officialId!=='chemiq-1b8804c1-d279-422a-ad63-755bb021b922'||scope.retainedValid!==815||scope.solveSeconds!==900||scope.maxTokens!==16384||scope.provider!==SUPPLIER||scope.reasoning!=='high'||scope.allowFallbacks!==false)throw Error('Task39 supplier scope changed');
  verifyPin(scope.authorizationPin);const authorization=JSON.parse(readFileSync(scope.authorizationPin.path,'utf8'));if(authorization.authorizedByUser!==true||JSON.stringify(authorization.eligibleIndices)!=='[39]'||authorization.retainedValid!==815||authorization.officialId!==scope.officialId||authorization.solveSeconds!==900||authorization.maxTokens!==16384||authorization.reasoning!=='high'||authorization.allowFallbacks!==false||!authorization.providerOrder.includes(SUPPLIER))throw Error('Human scoped supplier authorization mismatch');
  writeFileSync(streamScopePath,JSON.stringify(scope,null,2)+'\n',{flag:'wx'});
  const walk=(p:string):string[]=>readdirSync(p,{withFileTypes:true}).flatMap(e=>e.isDirectory()?walk(join(p,e.name)):[join(p,e.name)]);
  for(const sharedPin of control.broker.sourcePins)verifyPin(sharedPin);
  const sourcePins=[...walk(join(ROOT,'app/src')).filter(p=>/\.(ts|html)$/.test(p)),join(ROOT,'test/_lib.ts'),...walk(import.meta.dir).filter(p=>/\.(ts|py)$/.test(p)),...['chemiq-f-model-witness-v3.ts','chemiq-f-journal-contract-v3.ts','chemiq-f-grading-recorder-v3.ts','scientific-journal-proxy.ts','chemiq-f-provider-proxy-v3.ts','campaign-journal.ts','campaign-contract.ts','benchmark-inference.ts','benchmark-provider.ts','benchmark-usd-cash.ts','scientific-journal-plan.ts'].map(n=>join(ROOT,'scripts/benchmark-repair',n)),...['digitalocean-provider.ts','digitalocean-journal.ts','digitalocean-usd-cash.ts','digitalocean-proxy.ts','digitalocean-inference.ts','digitalocean-closed-run-cost.ts'].map(n=>join(ROOT,'scripts/benchmark-campaign/full-f/shared',n)),join(OUT,'manifest.json'),join(OUT,'grader-provenance.json'),join(OUT,'environment-validation.json'),join(OUT,'submit-retry-build-current.json'),...JSON.parse(readFileSync(join(OUT,'submit-retry-build-current.json'),'utf8')).files.map((p:Pin)=>p.path),...control.broker.sourcePins.map((p:Pin)=>p.path)].sort().map(actualPin);
  let recoveredDelivery:any=null;
  const deliveryReadyPath=join(OUT,'delivery-recovery-ready.json'),deliveryAuditPath=join(OUT,'delivery-recovery-audit.json');
  if(existsSync(deliveryReadyPath)){
    const ready=JSON.parse(readFileSync(deliveryReadyPath,'utf8')),audit=JSON.parse(readFileSync(deliveryAuditPath,'utf8'));verifyPin(ready.reportPin);
    if(!audit.valid||audit.reportPin.sha256!==ready.reportPin.sha256)throw Error('Delivery recovery audit mismatch');
    recoveredDelivery=JSON.parse(readFileSync(ready.reportPin.path,'utf8'));
    const pins=[actualPin(deliveryReadyPath),actualPin(deliveryAuditPath),ready.reportPin,...recoveredDelivery.retention.map((r:any)=>r.pin)];
    for(const r of recoveredDelivery.records){verifyPin(r.deliveryRecoveryPin);const proof=JSON.parse(readFileSync(r.deliveryRecoveryPin.path,'utf8'));pins.push(r.deliveryRecoveryPin,proof.originalResultPin,proof.databasePin,proof.grader.requestPin,proof.grader.responsePin,...proof.realProviderSubmit.flatMap((e:any)=>[e.candidateSourcePin,e.requestPin,e.responsePin]));}
    for(const pin of pins){verifyPin(pin);sourcePins.push(pin);}
  }
  sourcePins.push(scope.authorizationPin,...['supplier-shared-admission.ts','supplier-closed-run-cost.ts','supplier-inference.ts','supplier-journal.ts','supplier-usd-cash.ts','supplier-proxy.ts','chembench-supplier-profiles.ts'].map(n=>actualPin(join(ROOT,'scripts/benchmark-campaign/full-f/shared',n))),actualPin(streamScopePath),actualPin(scopeTemplate),actualPin(join(ROOT,'scripts/benchmark-campaign/full-f/shared/docker-physical-disk-admission-staged.ts')),actualPin(diskStartPath));
  if(!recoveredDelivery||recoveredDelivery.retainedValid+recoveredDelivery.records.length!==815)throw Error('Task39 entry requires independently audited815 retention');
  const privateBudget=JSON.parse(readFileSync(join(OUT,'task39-submission-reserve-build.json'),'utf8'));
  sourcePins.push(...privateBudget.sourcePins,...privateBudget.files,actualPin(privateBudget.proofPath),actualPin(privateBudget.machinePath),actualPin(join(OUT,'task39-submission-reserve-build.json')),...review.sourcePins);
  for(const pin of sourcePins)verifyPin(pin);
  const runManifest={schedulingVariant:{name:'completed ordinary length boundary / native prompt <=450s reserve submit',traceFile:'engine/submission-reserve-boundaries.jsonl',workingCompleteLengthCutoffSeconds:450,genericContinuationHint:false,submissionLengthReminder:false,idleTimeoutModified:false,paidOutcomeProven:false,noHeavyResourceClaim:true,authorizedOnce:true},...manifest,settings:SEGMENT_SETTINGS,sharedTransport:{brokerRunId:connection.runId,modelTransportTimeoutMs:control.transportTimeoutSwitch?.modelTransportTimeoutMs??300000,commonSourcePins:control.broker.sourcePins},providerSwitch:{from:manifest.settings.providerSlug,to:BENCHMARK_PROVIDER.providerSlug,authorizedBy:'Explicit human ChemIQ only39 Relace then DekaLLM then Wafer authorization',originalManifestPin:actualPin(join(OUT,'manifest.json'))},workerCount,runId,taskSchedule:plan.taskSchedule,taskIds:plan.tasks.map(t=>({index:t.index,officialId:t.officialId,taskId:t.taskId})),taskScheduleSha256:plan.taskScheduleSha256,startedAtUtc:utc(),sourcePins,sourceExecutionDigest:hash(JSON.stringify(sourcePins)),brokerRunId:connection.runId};
  atomic(join(output,'manifest.json'),runManifest);save('active-run.json',{runId,output,pid:process.pid,startedAtUtc:utc()});
  const admission=await acquireFullFAdmission({root:ROOT,output,runId,slug:'chemiq',sourcePins,providerSlug:SUPPLIER});
  const processPin=join(output,'process.json');atomic(processPin,{protocol:'paid-owned-process-v2',family:'chemiq-full-f',runId,pid:process.pid,ownerNonce:admission.owned.ownerNonce,role:'independent full816 coordinator',startedAtUtc:utc()});await admission.registerOwnedProcess(actualPin(processPin));
  const journal=createCampaignJournal({directory:store,campaign:runId,capUsd:admission.capUsd,pendingLimit:50,priorCampaignCostUpperBoundUsd:0,outputDirectory:output,provider:BENCHMARK_PROVIDER});
  const cash=createBenchmarkCash({directory:join(store,'currency'),runId,providerKind:'real-provider',admission,prices:admission.prices,journal:{directory:store,configPin:actualPin(join(store,'journal-config.json')),sourcePin:actualPin(join(ROOT,'scripts/benchmark-campaign/full-f/shared/supplier-journal.ts'))}},BENCHMARK_PROVIDER);
  const gate=new ChemiqRouteSeal(),records=new Map<number,any>(),engines=new Map<number,any>();let next=0,financialStop:string|undefined,fatal:string|undefined;
  let priorCostUsd=0,priorUnknownCostCount=0,priorUnknownReservationUsd=0;
  const attempts=new Map<number,{recordedAttempts:number;generationAttempts:number}>();for(const t of plan.tasks)attempts.set(t.index,{recordedAttempts:0,generationAttempts:0});
  for(const previous of readdirSync(join(OUT,'runs'),{withFileTypes:true}).filter(e=>e.isDirectory()&&e.name!==runId)){
    const base=join(OUT,'runs',previous.name),closedPath=join(base,'currency-close.json');
    const eventsPath=join(base,'journal/api-events.jsonl'),generated=new Set<number>();if(existsSync(eventsPath)){for(const line of readFileSync(eventsPath,'utf8').trim().split('\n').filter(Boolean)){const e=JSON.parse(line);if(e.kind==='start'){const t=plan.tasks.find(t=>String(e.record?.route??e.route??'').endsWith('/'+t.officialId));if(t)generated.add(t.index);}}}for(const index of generated)attempts.get(index)!.generationAttempts++;
    if(!existsSync(closedPath)){if(existsSync(join(base,'journal/currency/cash-config.json')))throw Error('Previous lane financial closure required before resuming');continue;}
    const closed=inspectFullFClosedCash(ROOT,actualPin(join(base,'journal/currency/cash-close.json')));priorCostUsd+=closed.billedUsd;priorUnknownCostCount+=closed.unknownCostCount;priorUnknownReservationUsd+=closed.unknownReservationUsd;
    for(const item of readdirSync(base,{withFileTypes:true}).filter(e=>e.isDirectory()&&/^task-\d+$/.test(e.name))){const path=join(base,item.name,'result.json');if(!existsSync(path))continue;const r=JSON.parse(readFileSync(path,'utf8'));if(plan.tasks[r.index]?.officialId!==r.officialId||r.arm!=='F')throw Error('Resume result identity mismatch');attempts.get(r.index)!.recordedAttempts++;if((realScore(r))||terminalProtocolFailure(r)){if(records.has(r.index))throw Error('Duplicate completed result');records.set(r.index,{...r,terminalProtocolFailure:terminalProtocolFailure(r),priorResultPin:actualPin(path)});}}
  }
  if(recoveredDelivery)for(const r of recoveredDelivery.records){
    if(plan.tasks[r.index]?.officialId!==r.officialId||r.arm!=='F'||!r.generationValid||!r.acceptance?.valid||hash(r.answer)!==r.candidateSha256)throw Error('Recovered delivery identity mismatch');
    if(records.has(r.index))throw Error('Recovered delivery duplicates existing effective score');
    records.set(r.index,{...r,deliveryRecovery:true});
  }
  if(records.size!==815||records.has(39)||plan.tasks[39].officialId!==scope.officialId)throw Error('Task39-only score retention mismatch');
  const executionOrder=[...plan.tasks].sort((a,b)=>{const aa=attempts.get(a.index)!,bb=attempts.get(b.index)!;return aa.generationAttempts-bb.generationAttempts||aa.recordedAttempts-bb.recordedAttempts||a.index-b.index;});
  const recoverySchedule={protocol:'chemiq-recovery-dispatch-order-v1',runId,denominator:816,originalTaskScheduleSha256:plan.taskScheduleSha256,policy:'unattempted generation first, then fewest generation attempts, then fewest recorded attempts, then original index',order:executionOrder.map(t=>({index:t.index,officialId:t.officialId,...attempts.get(t.index),skip:records.has(t.index)})),dispatched:[] as any[]};atomic(join(output,'recovery-dispatch-order.json'),recoverySchedule);
  const key=benchmarkProviderKey(ROOT);if(!key)throw Error('Inner backend key unavailable');
  const token=randomUUID()+randomUUID();process.env.TGENGIN_GRADER_TOKEN=token;process.env.TGENGIN_GRADER_ORIGINS=PRIVATE;process.env.BUN_JSC_forceRAMSize=String(512*1024**2);
  const proxy=createChemiqModelWitness({runId,inference:BENCHMARK_INFERENCE,provider:BENCHMARK_PROVIDER,journal,cash,seal:gate,routes:new Set(plan.tasks.map(t=>t.route)),failureDirectory:join(store,'failures'),beforeAdmission(){admission.validateForwardSource();},onFinancialStop(reason){financialStop=reason;},transport:raw=>admission.transport(raw)});
  const provider=Bun.serve({hostname:'127.0.0.1',port:0,idleTimeout:255,maxRequestBodySize:4*1024**2,async fetch(request){
    const got=Buffer.from(request.headers.get('authorization')??''),want=Buffer.from('Bearer '+key);
    if(got.length!==want.length||!timingSafeEqual(got,want))return Response.json({error:'unauthorized'},{status:401});
    const path=new URL(request.url).pathname;if(request.method!=='POST'||!path.endsWith('/v1/chat/completions'))return new Response('unplanned',{status:404});
    const route=path.slice(1,-'/v1/chat/completions'.length);try{gate.check(route);}catch{return Response.json({error:'route closed'},{status:409});}
    const result=await proxy.handle(route,await request.text());return new Response(result.rawResponse,{status:result.httpStatus,headers:{'content-type':'application/json'}});
  }});
  const progress=()=>{const c=cash.snapshot(),rows=[...records.values()];const status={protocol:'chemiq-full-f-status-v1',phase:fatal||financialStop?'stopped':next>=816&&!engines.size?'closing':'real-full-running',updatedAtUtc:utc(),denominator:816,workerCount,providerSlug:BENCHMARK_PROVIDER.providerSlug,attempted:next,recorded:rows.length,completed:rows.filter(r=>realScore(r)).length,passed:rows.filter(r=>realScore(r)&&r.acceptance.passed).length,budgetTerminalFailures:rows.filter(r=>r.index===39&&!realScore(r)&&r.generationClassification?.kind==="experimental_failure").length,infrastructureFailures:rows.filter(r=>!r.generationValid||!r.acceptance?.valid).length,knownCostUsd:priorCostUsd+c.billedUsd,priorCostUsd,unknownCostCount:priorUnknownCostCount+c.newUnknownCount,priorUnknownCostCount,priorUnknownReservationUsd,pendingRequests:c.pendingCount,modelRequests:journal.snapshot().acceptedRequestCount,cash:c,pid:process.pid,runId,output,activeTasks:[...engines.keys()],fatal:fatal??null,financialStop:financialStop??null,brokerHealthPath:connection.healthPath,session:{model:'gpt-6.1-sol',reasoningEffort:'medium',serviceTier:'default'}};atomic(join(OUT,'status.json'),status);};
  const timer=setInterval(()=>{try{progress();}catch(error){fatal='status_persistence_failure:'+String(error);}},15000);progress();
  let handoff:any=null;
  function yieldAtTaskBoundary(){const path=join(OUT,'round-handoff-request.json');if(!existsSync(path))return false;const request=JSON.parse(readFileSync(path,'utf8'));if(request.requested!==true)return false;const broker=JSON.parse(readFileSync(connection.healthPath,'utf8'));if(request.brokerRunId!==connection.runId||broker.round>request.round)return false;if(!handoff){handoff={protocol:'chemiq-natural-task-boundary-yield-v1',runId,brokerRunId:connection.runId,waitUntilRoundGreaterThan:request.round,requestPin:actualPin(path),noticedAtUtc:utc(),currentTasks:[...engines.keys()]};atomic(join(output,'handoff-request-observed.json'),handoff);}return true;}
  async function worker(){while(next<816&&!financialStop&&!fatal&&!proxy.state().stopReason){
    if(yieldAtTaskBoundary())break;
    const task=executionOrder[next++];if(records.has(task.index))continue;
    if(!diskAdmission(join(output,'disk-admission-task-'+task.index+'.json')).admissible){fatal='docker_physical_disk_new_dispatch_blocked';break;}
    const attempt=attempts.get(task.index)!;attempt.recordedAttempts++;recoverySchedule.dispatched.push({ordinal:recoverySchedule.dispatched.length,index:task.index,officialId:task.officialId,priorGenerationAttempts:attempt.generationAttempts,recordedAttemptNumber:attempt.recordedAttempts,atUtc:utc()});atomic(join(output,'recovery-dispatch-order.json'),recoverySchedule);
    const taskOut=join(output,'task-'+task.index),directory=join(taskOut,'engine');mkdirSync(directory,{recursive:true});
    let engine:any,gradeServer:any,recorder:ChemiqGradingRecorder|undefined,opened=false;
    try{
      for(const pin of sourcePins)verifyPin(pin);
      recorder=new ChemiqGradingRecorder(plan,join(taskOut,'physical-grading'),PRIVATE,token);
      gradeServer=Bun.serve({hostname:'127.0.0.1',port:0,idleTimeout:255,maxRequestBodySize:4*1024**2,fetch:r=>recorder!.handle(r)});
      const gradeOrigin='http://127.0.0.1:'+gradeServer.port;process.env.TGENGIN_GRADER_ORIGINS=[...(process.env.TGENGIN_GRADER_ORIGINS??'').split(','),gradeOrigin].join(',');
      const objective=chemiqObjective(gradeOrigin);engine=await machine(BENCHMARK_INFERENCE,{directory,keep:true});engines.set(task.index,engine);
      const registered=join(taskOut,'process.json');atomic(registered,{protocol:'paid-owned-process-v2',family:'chemiq-full-f',runId,ownerNonce:admission.owned.ownerNonce,pid:engine.pid,base:engine.base,taskIndex:task.index,startedAtUtc:utc(),role:'native Bun cold task engine'});await admission.registerOwnedProcess(actualPin(registered));
      await engine.api('POST','/declare',{handles:objective.nodes.map(n=>({name:n.handle,expectMs:120000})),places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',BENCHMARK_PROVIDER.model]],unit:'fn:unit.tools'}]});
      await engine.api('POST','/exec',{sql:"update tool set usable=case when name in ('submit','verify','task_tree','node_load') then 1 else 0 end"});
      await engine.api('POST','/exec',{sql:"delete from api where key_env!='OPENROUTER_API_KEY' or model!=:model",params:{model:BENCHMARK_PROVIDER.model}});
      await engine.api('POST','/exec',{sql:"update api set base_url=:endpoint,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model=:model",params:{model:BENCHMARK_PROVIDER.model,endpoint:`http://127.0.0.1:${provider.port}/${task.route}/v1`}});
      const toolRows=await engine.api('POST','/query',{sql:'select name,usable from tool order by name'});atomic(join(taskOut,'tool-boundary.json'),toolRows);
      const started=Date.now();gate.open(task.route,started);opened=true;
      await engine.api('POST','/tasks',{id:task.taskId,run:runId,mode:'repair',agent:'bot',place:'local',source:'user',description:task.prompt,objective,readable:false,solveSeconds:900,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
      let bound=false,terminal:any;while(Date.now()-started<2010000){if(proxy.state().stopReason||financialStop||fatal){gate.seal(task.route,'proxy_stopped');await proxy.drain(task.route);break;}const queried=await engine.api('POST','/query',{sql:'select state,result,created_at,solve_seconds from task where id=:id',params:{id:task.taskId}}),state=queried.rows[0];if(!state)throw Error('Created task missing');if(!bound){gate.bindCreation(task.route,state.created_at);bound=true;}const result=state.result?JSON.parse(state.result):null;if(['done','failed'].includes(state.state)&&result&&!['finalization_pending','finalization_error'].includes(result.outcome)){terminal=state;break;}if(Date.now()>=state.created_at+900000)gate.seal(task.route,'declared_deadline');await Bun.sleep(500);}
      gate.seal(task.route,terminal?'terminal':'hard_deadline');await proxy.drain(task.route);await engine.stop();engines.delete(task.index);
      const captured=capture(directory,task,taskOut),calls=proxy.takeTaskReceipts(task.route),runtime=captured.state.result?JSON.parse(captured.state.result):{outcome:'finalization_pending',valid:false};
      const generation=classifyGeneration({runtimeVerdict:runtime,state:captured.state.state,calls,trace:captured.trace,candidate:captured.candidate?.body});
      await recorder.drain();recorder.finalPhase();
      const acceptance=await gradeFixedCandidate({objective,task:{id:task.taskId},candidate:captured.candidate?.body,generation,expectedCandidateSha256:hash(captured.candidate?.body??'')});await recorder.drain();recorder.closeArtifact(join(taskOut,'grading-close.json'));
      const record={runId,index:task.index,officialId:task.officialId,benchmark:'chemiq',arm:'F',replica:0,category:task.category,subCategory:task.subCategory,promptSha256:task.promptSha256,settings:SEGMENT_SETTINGS,state:captured.state.state,runtimeVerdict:runtime,generationClassification:generation,generationValid:generation.valid,answer:captured.candidate?.body??'',candidateSha256:hash(captured.candidate?.body??''),candidateHow:captured.candidate?.how??'none',candidateDeadlinePolicy:'frozen-finalCandidate-at<=created+solve_seconds',declaredDeadlineAt:captured.state.created_at+900000,seconds:(Date.now()-started)/1000,tracePin:captured.tracePin,traceRows:captured.traceRows,explicitVerifyCalls:captured.explicitVerifyCalls,taskDatabasePin:captured.taskDatabasePin,calls,acceptance};atomic(join(taskOut,'result.json'),record);records.set(task.index,record);
    }catch(error){const record={runId,index:task.index,officialId:task.officialId,arm:'F',generationValid:false,acceptance:{valid:false,outcome:'infrastructure_error'},error:String(error),observedAtUtc:utc()};atomic(join(taskOut,'result.json'),record);records.set(task.index,record);fatal=cash.snapshot().poisoned?'cash_poisoned':'worker_setup_or_capture_failure:'+String(error);}
    finally{if(opened)gate.seal(task.route,'finally');await proxy.drain(task.route);if(engine&&engines.has(task.index)){await engine.stop();engines.delete(task.index);}await recorder?.drain();await gradeServer?.stop(true);progress();}
  }}
  try{await Promise.all(Array.from({length:workerCount},()=>worker()));proxy.stop('generation_closed');await proxy.drain();await provider.stop(true);journal.exportLegacyLedger();journal.close();const cashPin=cash.close();const closed=JSON.parse(readFileSync(cashPin.path,'utf8'));atomic(join(output,'currency-close.json'),closed);
    const laneClose=await admission.finishLightweight({cashPin});atomic(join(output,'lane-close.json'),laneClose);
    if(handoff)atomic(join(OUT,'round-handoff-wait.json'),{...handoff,closedAtUtc:utc(),cashPin,laneClosePin:actualPin(join(output,'lane-close.json')),pendingRequests:cash.snapshot().pendingCount,currentUnknownCostCount:cash.snapshot().newUnknownCount,originalUnknownRetained:true,onlyNewTaskDispatchStopped:true});
    const rows=[...records.values()].sort((a,b)=>a.index-b.index);atomic(join(output,'results.json'),rows);const complete=rows.length===816&&new Set(rows.map(r=>r.officialId)).size===816;
    atomic(join(output,'summary.json'),{denominator:816,recorded:rows.length,completeSchedule:complete,validScored:rows.filter(r=>realScore(r)).length,passed:rows.filter(r=>realScore(r)&&r.acceptance.passed).length,cash:cash.snapshot(),laneClose,financialStop:financialStop??null,fatal:fatal??null,endedAtUtc:utc()});progress();
    const last=JSON.parse(readFileSync(join(OUT,'status.json'),'utf8'));last.phase=complete&&rows.every(r=>(realScore(r))||terminalProtocolFailure(r))?'complete':'needs-attention';if(handoff&&last.phase!=='complete')last.phase='waiting-parent-round';last.roundHandoff=handoff;last.accountingClosed=true;last.financialClosed=closed.releasePermitted&&priorUnknownCostCount===0;last.terminalProtocolFailures=rows.filter(terminalProtocolFailure).length;last.pendingTasks=plan.tasks.filter(t=>{const r=records.get(t.index);return !r||(!(realScore(r))&&!terminalProtocolFailure(r));}).map(t=>t.officialId);atomic(join(OUT,'status.json'),last);
  }finally{clearInterval(timer);}
}
if(import.meta.main)try{await run();}catch(error){const status=existsSync(join(OUT,'status.json'))?JSON.parse(readFileSync(join(OUT,'status.json'),'utf8')):{};save('status.json',{...status,phase:'needs-attention',updatedAtUtc:utc(),error:String(error)});console.error(String(error));process.exitCode=1;}
