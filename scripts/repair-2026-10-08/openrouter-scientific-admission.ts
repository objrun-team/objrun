/** OpenRouter funding adapter for the existing scientific task/worker runner. */
import { mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { join, resolve } from "node:path";
import type { ScientificPaidAdmission } from "./scientific-journal-campaign.ts";
import { actualPin, demand, jsonPin, verifyPin, type Pin } from "./paid-resource-proof-v2.ts";
import { BENCHMARK_PROVIDER } from "./benchmark-provider.ts";
import { createBenchmarkCash, verifyBenchmarkCashClosure, type BenchmarkCash, type BenchmarkCashTicket } from "./benchmark-usd-cash.ts";
import { acquireOpenRouterAdmission, prepareOpenRouterFunding } from "./openrouter-paid-admission.ts";
import { fixedScientificPlan } from "./scientific-journal-plan.ts";
import { validateScientificStore } from "./scientific-journal-storage.ts";

const ROOT=resolve(import.meta.dir,"../..");
const FILES=['benchmark-provider.ts','benchmark-usd-cash.ts','benchmark-inference.ts','openrouter-paid-admission.ts','openrouter-scientific-admission.ts','scientific-journal-campaign.ts','campaign-journal.ts','campaign-contract.ts','scientific-journal-proxy.ts','paid-resource-proof-v2.ts','scientific-journal-plan.ts','scientific-journal-storage.ts','scientific-journal-resources.ts','campaign-workers.ts','prepare-scientific-journal-store.ps1','freeze-scientific-journal.py','audit-scientific-campaign.py','audit-scientific-journal.py'];
const files=(directory:string):string[]=>readdirSync(directory,{withFileTypes:true}).flatMap(row=>row.isDirectory()?files(join(directory,row.name)):row.isFile()&&/\.(ts|html)$/.test(row.name)?[join(directory,row.name)]:[]);
const save=(path:string,value:any)=>{writeFileSync(path,JSON.stringify(value,null,2)+'\n',{flag:'wx'});return actualPin(path);};
function powershellEnv(){const env={...process.env};for(const key of Object.keys(env))if(key.toLowerCase()==='psmodulepath')delete env[key];env.PSModulePath=join(process.env.SystemRoot??'C:/Windows','System32/WindowsPowerShell/v1.0/Modules');return env;}

export async function prepareOpenRouterScientific(profile:string,benchmarks:string[],capUsd?:number){
  const runId='repair-'+new Date().toISOString().replace(/[:.]/g,'-'),plan=fixedScientificPlan(ROOT,runId,profile,benchmarks);
  const output=join(ROOT,'docs/repair-2026-10-10/openrouter-scientific-preparations',runId);mkdirSync(output,{recursive:true});
  const funding=await prepareOpenRouterFunding(ROOT,output,capUsd);
  const { executionFiles } = await import('./scientific-journal-campaign.ts');
  const sourcePins=[...new Set([...files(join(ROOT,'app/src')),...FILES.map(name=>join(import.meta.dir,name)),...executionFiles.map(name=>join(ROOT,name)),
    ...['test/_lib.ts','app/package.json','app/bun.lock','app/tsconfig.json','examples/benchmark/_lib/gradelib.py', ...benchmarks.map(name=>'examples/benchmark/'+name+'/stand.py')].map(name=>join(ROOT,name))])].sort().map(actualPin);
  const recipe={protocol:'openrouter-scientific-recipe-v1',provider:BENCHMARK_PROVIDER.kind,currency:'USD',runId,profile,benchmarks,
    taskScheduleSha256:plan.taskScheduleSha256,sourcePins,...funding,modelCalls:0,providerForwardingEnabled:false};
  const recipePin=save(join(output,'recipe.json'),recipe);
  return{recipePin,plannedTaskRuns:plan.tasks.length,modelCalls:0,providerForwardingEnabled:false};
}

export function openRouterScientificAdmission(recipeFile:string):ScientificPaidAdmission{
  const recipePin=actualPin(resolve(recipeFile)),recipe=jsonPin(recipePin);
  demand(recipe.protocol==='openrouter-scientific-recipe-v1'&&recipe.provider===BENCHMARK_PROVIDER.kind&&recipe.currency==='USD'&&recipe.modelCalls===0&&recipe.providerForwardingEnabled===false,'scientific_openrouter_recipe');
  const plan=fixedScientificPlan(ROOT,recipe.runId,recipe.profile,recipe.benchmarks);
  demand(plan.taskScheduleSha256===recipe.taskScheduleSha256,'scientific_openrouter_task_schedule');
  for(const pin of recipe.sourcePins)verifyPin(pin);
  let lease:Awaited<ReturnType<typeof acquireOpenRouterAdmission>>,cash:BenchmarkCash|undefined,state:{output:string;store:string};
  const tickets=new Map<number,BenchmarkCashTicket>(),workers=new Set<number>();
  const ensureCash=()=>cash??=createBenchmarkCash({directory:join(state.store,'currency'),runId:recipe.runId,providerKind:'real-provider',admission:lease,prices:recipe.prices,
    journal:{directory:state.store,configPin:actualPin(join(state.store,'journal-config.json')),sourcePin:actualPin(join(import.meta.dir,'campaign-journal.ts'))}},BENCHMARK_PROVIDER);
  return{provider:BENCHMARK_PROVIDER,capUsd:recipe.capUsd,priorCampaignCostUpperBoundUsd:0,
    metadata:{protocol:recipe.protocol,prospectiveRunId:recipe.runId,recipePin,taskScheduleSha256:recipe.taskScheduleSha256,providerKind:'real-provider',currency:'USD',originalDeepSeekCnyLedgerReused:false},
    executionFiles:FILES.map(name=>'scripts/repair-2026-10-08/'+name),
    async acquireLock(input){demand(input.root===ROOT&&input.runId===recipe.runId,'scientific_openrouter_identity');verifyPin(recipePin);
      lease=await acquireOpenRouterAdmission({root:ROOT,output:input.root===ROOT?join(ROOT,'docs/repair-2026-10-08/campaigns',recipe.runId):'',runId:recipe.runId,family:'scientific-journal-openrouter-v1',entry:input.entry,sourcePins:recipe.sourcePins,prices:recipe.prices,balance:recipe.balance,capUsd:recipe.capUsd});
      return{path:lease.path,async release(proof){const closure=jsonPin(proof.workers as Pin);demand(closure.activeEngines===0&&closure.workerClosures.length===workers.size&&closure.workerClosures.every((row:any)=>workers.has(row.pid)&&row.stopReturned===true),'scientific_openrouter_workers_not_closed');lease.finishLightweight({ownedGenerationClosed:true,pendingRequests:0,certificate:proof.certificate});}};},
    async prepareStore(input){lease.assertOwned();
      const script=join(import.meta.dir,'prepare-scientific-journal-store.ps1');
      for(const mode of ['Inspect','Apply'])execFileSync('powershell.exe',['-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass','-File',script,'-Mode',mode,'-RunId',recipe.runId,...(mode==='Apply'?['-OwnedPid',String(lease.owned.pid),'-OwnerNonce',lease.owned.ownerNonce]:[])],{windowsHide:true,timeout:30000,env:powershellEnv()});
      const pin=actualPin(join(input.output,'storage-layout.json')),layout=validateScientificStore(ROOT,recipe.runId,pin);state={output:input.output,store:layout.physicalStore};return pin;},
    registerWorker(input){lease.assertOwned();workers.add(input.pid);const pin=save(join(input.output,`openrouter-worker-${input.worker}.json`),{runId:recipe.runId,pid:input.pid,worker:input.worker,ownerNonce:lease.owned.ownerNonce});lease.registerOwnedProcess(pin);},
    beforeForward(admitted,prefix,raw,route){const funded=ensureCash().beforeForward({id:recipe.runId+'/'+admitted.requestSeq,route,rawRequest:Buffer.from(raw),capturedRequest:actualPin(admitted.requestFile),journal:{admitted,startPrefix:prefix as any}});tickets.set(admitted.requestSeq,funded.ticket);demand(funded.admitted,'scientific_openrouter_usd_exhausted');},
    afterDurableFinish(receipt){const result=ensureCash().finish(tickets.get(receipt.requestSeq)!,{kind:'journal-finish',journalRef:receipt.journalRef});demand(!result.poisoned,'scientific_openrouter_unknown_charge');},
    afterFailedJournalCapture(request:any,_finish,evidence:any){if(!request||!tickets.has(request.requestSeq))return;ensureCash().finish(tickets.get(request.requestSeq)!,evidence.journalRef?{kind:'journal-finish',journalRef:evidence.journalRef}:{kind:'failed-capture',requestSeq:request.requestSeq,evidence});},
    certify(input:any){demand(input.modelTransportActive===0&&input.workers.length===workers.size&&input.workers.every((row:any)=>row.stopReturned===true),'scientific_openrouter_active_workers');const pin=ensureCash().close();const verified=verifyBenchmarkCashClosure(pin);demand(verified.proof.releasePermitted===true,'scientific_openrouter_cash_unclosed');return{protocol:'scientific-openrouter-financial-close-v1',currency:'USD',cashClosePin:pin,valid:true,accountingClosed:true,invoice:false};},
    failed(){cash?.close();},
  };
}
if(import.meta.main){const [mode,profile,list,cap]=process.argv.slice(2);demand(mode==='prepare'&&profile&&list,'use_prepare_profile_benchmarks_capUsd');console.log(JSON.stringify(await prepareOpenRouterScientific(profile,list.split(','),cap===undefined?undefined:Number(cap))));}
