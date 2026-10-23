/** Isolated user-authorized relace attempt for index277 only. Original run.ts remains immutable. */
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { Database } from 'bun:sqlite';
import { ROOT, OUT, makePlan, save } from './prepare.ts';
import { machine, type Machine } from '../../../../test/_lib.ts';
import { finalCandidate } from '../../../../app/src/objective/candidate.ts';
import { CHEMBENCH_SUPPLIERS } from '../shared/chembench-supplier-profiles.ts';
const BENCHMARK_PROVIDER=CHEMBENCH_SUPPLIERS['relace'];
import { BENCHMARK_INFERENCE } from '../shared/supplier-inference.ts';
import { createCampaignJournal } from '../shared/supplier-journal.ts';
import { inspectAnyJournal as inspectCampaignJournal, inspectAnyClosedCash as inspectFullFClosedCash } from './supplier-accounting.ts';
import { ScientificJournalProxy } from '../shared/supplier-proxy.ts';
import { classifyGeneration, gradeFixedCandidate } from '../../../repair-2026-10-08/campaign-contract.ts';
import { createBenchmarkCash, verifyBenchmarkCashClosure, type BenchmarkCashTicket } from '../shared/supplier-usd-cash.ts';
import { actualPin, jsonPin, verifyPin } from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import { digest, scientificPrompt } from '../../../repair-2026-10-08/scientific-journal-plan.ts';
import { acquireFullFAdmission, fullFRunId } from '../shared/supplier-shared-admission.ts';
import { submissionFault } from './runtime-health.ts';
import { recoveryHistory, recoveryOrder } from './recovery-schedule.ts';
import { readRoundHandoff, roundHandoffPending, type RoundHandoff } from './round-yield.ts';
const json=(path:string)=>JSON.parse(readFileSync(path,'utf8'));
const objective={nodes:[{name:'parsed',domain:'bool',moment:'done',handle:'http://127.0.0.1:17906/parsed'},
  {name:'correct',domain:'bool',moment:'done',handle:'http://127.0.0.1:17906/correct'}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5,reuse:'text'};
const tree=(dir:string):string[]=>readdirSync(dir,{withFileTypes:true}).flatMap(e=>e.isDirectory()?tree(join(dir,e.name)):e.isFile()&&/\.(ts|py|json|yaml)$/.test(e.name)?[join(dir,e.name)]:[]);
const status=(v:any)=>save('status.json',{protocol:'chembench-full-f-status-v1',planned:500,...v,updatedAt:new Date().toISOString()});
const recordsDir=join(OUT,'results');
function records(){return existsSync(recordsDir)?readdirSync(recordsDir).filter(n=>/^task-\d+\.json$/.test(n)).map(n=>json(join(recordsDir,n))):[];}
async function main(){
  const control=json(join(ROOT,'docs/repair-2026-10-10/full-f-rerun/control.json'));
  const lastAuthorization=json(join(OUT,'relace-last-authorization.json'));
  if(lastAuthorization.armed!==true||lastAuthorization.index!==277||lastAuthorization.providerSlug!==BENCHMARK_PROVIDER.providerSlug||lastAuthorization.brokerRunId!==control.broker?.runId)throw Error('Supplier last-task entry is not explicitly armed for current material shared broker');
  if(control.paidReady!==true){const prev=existsSync(join(OUT,'status.json'))?json(join(OUT,'status.json')):{};status({...prev,stage:'queued',completed:records().filter(r=>r.acceptance?.valid).length,modelCalls:prev.modelCalls??0,actualCostUsd:prev.actualCostUsd??0,
    reason:'Shared paidReady=false; next heartbeat will advance, no own canonical owner acquired'});return;}
  if(json(join(OUT,'official-controls.json')).allPassed!==true)throw Error('Full official controls must pass');
  const runId=fullFRunId(ROOT,'chembench'), plan=makePlan('repair-'+new Date().toISOString().replace(/[:.]/g,'-'));
  // Shared run IDs have an owner prefix; task namespaces are explicitly rebuilt without changing official IDs/prompts.
  plan.tasks=plan.tasks.map(t=>({...t,route:`${runId}/chembench/F/0/${encodeURIComponent(t.officialId)}`,taskId:`chbf-${digest(runId).slice(0,12)}/F0/${t.officialId}`}));
  if(plan.tasks.some(t=>encodeURIComponent(t.taskId).length>100))throw Error('Encoded task ID exceeds production limit');
  mkdirSync(recordsDir,{recursive:true});const runOut=join(OUT,'runs',runId);mkdirSync(runOut,{recursive:true});
  const priorRuns=readdirSync(join(OUT,'runs')).filter(n=>n!==runId).map(n=>join(OUT,'runs',n));
  if(priorRuns.some(p=>existsSync(join(p,'currency/cash-config.json'))&&!existsSync(join(p,'currency/cash-close.json'))))throw Error('Previous run has not closed its writer; drain before resuming');
  const priorCash=priorRuns.filter(p=>existsSync(join(p,'currency/cash-close.json'))).map(p=>inspectFullFClosedCash(ROOT,actualPin(join(p,'currency/cash-close.json'))));
  const priorCost=priorCash.reduce((n,p)=>n+p.billedUsd,0),priorUnknownUsd=priorCash.reduce((n,p)=>n+p.unknownReservationUsd,0),priorUnknownCount=priorCash.reduce((n,p)=>n+p.unknownCostCount,0);
  const priorCalls=priorRuns.reduce((n,p)=>n+(existsSync(join(p,'journal/journal-config.json'))?inspectCampaignJournal(join(p,'journal')).snapshot?.acceptedRequestCount??0:0),0);
  const persist=(name:string,v:any)=>writeFileSync(join(runOut,name),JSON.stringify(v,null,2)+'\n');
  const live=await (await fetch('http://127.0.0.1:17906/problems?n=500&seed=0',{signal:AbortSignal.timeout(120000)})).json() as any[];
  if(live.length!==500||new Set(live.map(r=>r.id)).size!==500)throw Error('Live book denominator changed');
  const byId=new Map(live.map(r=>[r.id,r]));for(const t of plan.tasks)if(!byId.has(t.officialId)||digest(scientificPrompt('chembench',byId.get(t.officialId)!))!==t.promptSha256)throw Error('Live prompt changed');
  const history=recoveryHistory(priorRuns,records());
  const lastEligible=recoveryOrder(plan.tasks,records(),history.attempts);
  if(lastEligible.length!==1||lastEligible[0].index!==277)throw Error('Supplier isolated entry requires exactly unfinished277; preserve all existing terminal results');
  const sourcePins=[...new Set([...tree(join(ROOT,'app/src')),...tree(join(ROOT,'scripts/repair-2026-10-08')),
    ...readdirSync(import.meta.dir).filter(n=>/\.(ts|py|ps1)$/.test(n)).map(n=>join(import.meta.dir,n)),join(ROOT,'test/_lib.ts'),
    join(ROOT,'examples/benchmark/chembench/stand.py'),join(OUT,'official-controls.json'),join(OUT,'manifest.json'),
    ...['shared-admission.ts','closed-run-cost.ts','cash-reconciliation.ts','digitalocean-provider.ts','digitalocean-journal.ts','digitalocean-usd-cash.ts','digitalocean-proxy.ts','digitalocean-inference.ts','digitalocean-closed-run-cost.ts','chembench-supplier-profiles.ts','supplier-admission.ts','supplier-inference.ts','supplier-journal.ts','supplier-proxy.ts','supplier-usd-cash.ts','supplier-shared-admission.ts','supplier-closed-run-cost.ts'].map(n=>join(ROOT,'scripts/repair-2026-10-10/full-f/shared',n))])].sort().map(actualPin);
  persist('source-pins.json',sourcePins);
  const admission=await acquireFullFAdmission({root:ROOT,output:runOut,runId,slug:'chembench',sourcePins,providerSlug:BENCHMARK_PROVIDER.providerSlug});
  const journalDir=join(runOut,'journal'),journal=createCampaignJournal({directory:journalDir,campaign:runId,capUsd:admission.capUsd,priorCampaignCostUpperBoundUsd:0,outputDirectory:runOut,provider:BENCHMARK_PROVIDER});
  const cash=createBenchmarkCash({directory:join(runOut,'currency'),runId,providerKind:'real-provider',admission,prices:admission.prices,
    journal:{directory:journalDir,configPin:actualPin(join(journalDir,'journal-config.json')),sourcePin:actualPin(join(ROOT,'scripts/repair-2026-10-10/full-f/shared/supplier-journal.ts'))}},BENCHMARK_PROVIDER);
  const tickets=new Map<number,BenchmarkCashTicket>();
  const proxy=new ScientificJournalProxy(journal,{inference:BENCHMARK_INFERENCE,provider:BENCHMARK_PROVIDER,routes:new Set(plan.tasks.map(t=>t.route)),failureDirectory:join(journalDir,'failures'),
    transport:raw=>admission.transport(raw),beforeAdmission(){admission.validateForwardSource();},
    beforeForward(call,prefix,raw,route){const funded=cash.beforeForward({id:runId+'/'+call.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(call.requestFile),journal:{admitted:call,startPrefix:prefix as any}});tickets.set(call.requestSeq,funded.ticket);if(!funded.admitted)throw Error(funded.reason);},
    afterDurableFinish(receipt){const result=cash.finish(tickets.get(receipt.requestSeq)!,{kind:'journal-finish',journalRef:receipt.journalRef});if(result.poisoned&&control.costPolicy?.mode!=='record_and_continue')throw Error('Unknown charge retained');},
    afterFailedJournalCapture(call:any,_finish,evidence:any){if(call&&tickets.has(call.requestSeq))cash.finish(tickets.get(call.requestSeq)!,evidence.journalRef?{kind:'journal-finish',journalRef:evidence.journalRef}:{kind:'failed-capture',requestSeq:call.requestSeq,evidence});}});
  const server=Bun.serve({hostname:'127.0.0.1',port:0,maxRequestBodySize:4*1024**2,async fetch(req){const path=new URL(req.url).pathname;if(req.method!=='POST'||!path.endsWith('/v1/chat/completions'))return new Response('unsupported',{status:404});
    const route=path.slice(1,-'/v1/chat/completions'.length);const result=await proxy.handle(route,await req.text());return new Response(result.rawResponse,{status:result.httpStatus,headers:{'content-type':'application/json'}});}});
  const finished=new Set(records().filter(r=>r.acceptance?.valid===true).map(r=>r.index));
  const terminalProtocolFailures=new Set(records().filter(r=>r.terminalProtocolFailure===true).map(r=>r.index));
  const terminalTimeoutFailures=new Set(records().filter(r=>r.terminalTimeoutFailure===true).map(r=>r.index));
  const pending=recoveryOrder(plan.tasks,records(),history.attempts);let next=0;const engines:Machine[]=[];let fatal:string|undefined;
  persist('recovery-schedule.json',{protocol:'chembench-recovery-order-v1',createdAtUtc:new Date().toISOString(),policy:'unattempted first; infrastructure retries by increasing attempt count then frozen index',frozenTaskScheduleUnmodified:true,denominator:500,evidence:history.evidence,attemptCounts:plan.tasks.map(t=>({index:t.index,officialId:t.officialId,attempts:history.attempts.get(t.index)?.size??0})),
    order:pending.map((t,position)=>({position,index:t.index,officialId:t.officialId,previousAttempts:history.attempts.get(t.index)?.size??0,nextAttempt:(history.attempts.get(t.index)?.size??0)+1}))});
  const dispatches:any[]=[];
  let yieldRequest:RoundHandoff|undefined;
  const yieldAtQuestionBoundary=(worker:number)=>{
    const request=readRoundHandoff(OUT),broker=json(control.broker.healthPath);
    if(!roundHandoffPending(request,{brokerRunId:broker.runId,round:broker.round,runId}))return false;
    yieldRequest=request;persist(`round-yield-worker-${worker}.json`,{atUtc:new Date().toISOString(),worker,request,startedNewQuestion:false,previousQuestionNaturallyFinished:true});return true;
  };
  persist('manifest.json',{...json(join(OUT,'manifest.json')),providerSlug:BENCHMARK_PROVIDER.providerSlug,providerRouting:BENCHMARK_PROVIDER.routing,providerVersion:'supplier-last-task-user-authorized-v1',perBenchMaxInFlight:8,campaign:runId,taskSchedule:plan.taskSchedule,tasks:plan.tasks,providerForwardingEnabled:true,capUsd:admission.capUsd,skippedCompletedIndices:[...finished]});
  const update=()=>{const all=records(),s=cash.snapshot();status({stage:fatal?'interrupted':'running',runId,runnerPid:process.pid,runOut,completed:all.filter(r=>r.acceptance?.valid).length,recorded:all.length,graded:all.filter(r=>r.acceptance?.valid&&r.candidateHow!=='none').length,passed:all.filter(r=>r.acceptance?.passed).length,
    modelCalls:priorCalls+journal.snapshot().acceptedRequestCount,actualCostUsd:priorCost+s.billedUsd,currentRunCostUsd:s.billedUsd,priorRunsCostUsd:priorCost,pendingReservationUsd:s.pendingReservationUsd,unknownReservationUsd:priorUnknownUsd+s.unknownReservationUsd,unknownCostCount:priorUnknownCount+s.newUnknownCount,feePolicy:control.costPolicy?.mode,cash:s,journal:journal.snapshot(),fatal});};
  const interval=setInterval(update,15000);update();
  async function worker(worker:number){
    while(next<pending.length&&!proxy.state().stopReason){if(yieldAtQuestionBoundary(worker))break;const position=next,task=pending[next++],attemptNumber=(history.attempts.get(task.index)?.size??0)+1;
    dispatches.push({position,index:task.index,officialId:task.officialId,worker,attemptNumber,atUtc:new Date().toISOString()});persist('recovery-dispatches.json',dispatches);
    const dir=join(runOut,`worker-${worker}`,`task-${task.index}`);mkdirSync(dir,{recursive:true});const engine=await machine(BENCHMARK_INFERENCE,{directory:dir,keep:true});engines.push(engine);
    persist(`engine-${worker}-${task.index}.json`,{runId,pid:engine.pid,worker,taskIndex:task.index,base:engine.base});await admission.registerOwnedProcess(actualPin(join(runOut,`engine-${worker}-${task.index}.json`)));
    await engine.api('POST','/declare',{handles:objective.nodes.map(n=>({name:n.handle,expectMs:120000})),places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',BENCHMARK_PROVIDER.model]],unit:'fn:unit.tools'}]});
    await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
    const started=Date.now();let record:any={...task,worker,workerPid:engine.pid,runId,attemptNumber,recoveryPosition:position,startedAt:new Date(started).toISOString()};
      try{await engine.api('POST','/exec',{sql:"update api set base_url=:endpoint,retry_on='[]' where key_env=:key and model=:model",params:{key:'OPENROUTER_API_KEY',model:BENCHMARK_PROVIDER.model,endpoint:`http://127.0.0.1:${server.port}/${task.route}/v1`}});
        await engine.api('POST','/tasks',{id:task.taskId,run:runId,mode:'repair',agent:'bot',place:'local',source:'user',description:task.prompt,objective,readable:false,solveSeconds:600,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
        let terminal:any,terminalAt=0,lastProbe=0;while(Date.now()-started<750000){
          if(proxy.state().stopReason&&!proxy.pending(task.route))throw Error('Model transport segment stopped after requests drained: '+proxy.state().stopReason);
          const st=await engine.api<any>('GET',`/tasks/${encodeURIComponent(task.taskId)}/status`),outcome=st.result?JSON.parse(st.result).outcome:undefined;
          if(Date.now()-lastProbe>=3000){lastProbe=Date.now();const fault=await submissionFault(engine,task.taskId);if(fault&&!proxy.pending(task.route)){record.submissionFault=fault;const e=new Error('The required submit tool was not called exactly once');e.name='RequiredToolCallMissing';throw e;}}
          if(['done','failed'].includes(st.state)&&st.result&&!['finalization_pending','finalization_error'].includes(outcome)){terminal=st;terminalAt||=Date.now();if(!proxy.pending(task.route)&&Date.now()-terminalAt>2000)break;}else{terminal=undefined;terminalAt=0;}await Bun.sleep(250);}
        if(!terminal)throw Error('No complete terminal state before hard deadline');await proxy.drain(task.route);
        const trace=await engine.api<any>('POST','/query',{sql:'select instance,unit,seq,role,kind,body,at,thought,prompt_tokens,completion_tokens,reasoning_tokens,cached_tokens from agent_bot_msg where instance like :prefix order by unit,seq',params:{prefix:`${task.taskId}#%`}});
        const db=new Database(join(dir,'data/h2h.sqlite'),{readonly:true});let candidate;try{candidate=finalCandidate({all:(sql:string,params:any[]=[])=>{const stmt=db.prepare(sql);try{return stmt.all(...params);}finally{stmt.finalize();}},run(){throw Error('readonly');},exec(){throw Error('readonly');},close(){}} as any,task.taskId);}finally{db.close();}
        const calls=proxy.takeTaskReceipts(task.route),verdict=JSON.parse(terminal.result),generation=classifyGeneration({runtimeVerdict:verdict,state:terminal.state,calls,trace:trace.rows,candidate:candidate?.body});
        record={...record,state:terminal.state,runtimeVerdict:verdict,generationClassification:generation,answer:candidate?.body??'',candidateHow:candidate?.how??'none',candidateSha256:digest(candidate?.body??''),apiCalls:calls,trace:trace.rows,
          acceptance:await gradeFixedCandidate({objective,task:{id:task.taskId},candidate:candidate?.body,generation,expectedCandidateSha256:digest(candidate?.body??'')})};
      }catch(error){await proxy.drain(task.route);const protocol=error instanceof Error&&error.name==='RequiredToolCallMissing';
        const timeout=error instanceof Error&&error.message==='No complete terminal state before hard deadline'&&!proxy.state().stopReason&&cash.snapshot().newUnknownCount===0;
        record={...record,state:protocol?'submission_protocol_failure':timeout?'terminal_timeout_failure':'infrastructure_failure',terminalProtocolFailure:protocol,terminalTimeoutFailure:timeout,error:String(error),apiCalls:proxy.takeTaskReceipts(task.route),acceptance:{valid:false,passed:false,outcome:protocol?'submission_protocol_failure':timeout?'terminal_timeout_failure':'infrastructure_failure'}};
        if(!protocol&&!timeout){fatal=String(error);proxy.stop('worker_infrastructure_failure');}}
      await engine.stop();engines.splice(engines.indexOf(engine),1);
      record.seconds=(Date.now()-started)/1000;persist(`task-${task.index}.json`,record);writeFileSync(join(recordsDir,`task-${task.index}.json`),JSON.stringify(record,null,2)+'\n');update();if(fatal)break;
    }
  }
  try{const guarded=(w:number)=>worker(w).catch(e=>{fatal=String(e);proxy.stop('worker_setup_failure');throw e;});const settled=await Promise.allSettled(Array.from({length:8},(_,worker)=>guarded(worker)));for(const item of settled)if(item.status==='rejected')fatal=String(item.reason);}
  finally{proxy.stop('closing');await proxy.drain();await Promise.allSettled(engines.map(e=>e.stop()));await server.stop(false);clearInterval(interval);
    persist('journal-export.json',journal.exportLegacyLedger());journal.close();const inspected=inspectCampaignJournal(journalDir);persist('journal-inspection.json',inspected);
    const cashPin=cash.close();const financial=verifyBenchmarkCashClosure(cashPin);persist('financial-verification.json',financial);
    if(financial.proof.snapshot.pendingCount===0)persist('lane-close.json',await admission.finishLightweight({cashPin,ownedGenerationClosed:true,pendingRequests:0}));
    if(yieldRequest)persist('round-yield-closure.json',{atUtc:new Date().toISOString(),request:yieldRequest,cashClosePin:cashPin,journalIntegrityValid:inspected.valid,pendingRequests:financial.proof.snapshot.pendingCount,laneClose:json(join(runOut,'lane-close.json')),nativeFinallyCompleted:true});
    const all=records(),completed=all.length===500&&all.every(r=>r.acceptance?.valid===true),exhausted=all.length===500&&all.every(r=>r.acceptance?.valid===true||r.terminalProtocolFailure===true||r.terminalTimeoutFailure===true);update();status({...json(join(OUT,'status.json')),stage:completed?'complete':exhausted?'complete_with_protocol_failures':yieldRequest&&!fatal?'waiting_round_handoff':'interrupted',fullScheduleExhausted:exhausted,terminalProtocolFailures:all.filter(r=>r.terminalProtocolFailure).length,terminalTimeoutFailures:all.filter(r=>r.terminalTimeoutFailure).length,completed:all.filter(r=>r.acceptance?.valid).length,financeClosed:financial.proof.releasePermitted===true,fatal,roundYieldRequest:yieldRequest,
      denominator:500,remainingIndices:plan.tasks.filter(t=>!all.some(r=>r.index===t.index&&r.acceptance?.valid)).map(t=>t.index)});
  }
}
main().catch(error=>{const prev=existsSync(join(OUT,'status.json'))?json(join(OUT,'status.json')):{};status({...prev,stage:'interrupted',runnerPid:process.pid,error:String(error)});console.error(String(error));process.exitCode=1;});
