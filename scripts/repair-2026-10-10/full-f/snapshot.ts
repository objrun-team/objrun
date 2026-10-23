/** Read-only summary of the four retained Bench jobs. No model calls or owner mutations. */
import { readFileSync, writeFileSync, existsSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { jsonPin } from '../../repair-2026-10-08/paid-resource-proof-v2.ts';
const root=resolve(import.meta.dir,'../../..'),home=join(root,'docs/repair-2026-10-10/full-f-rerun');
const read=(path:string)=>JSON.parse(readFileSync(path,'utf8').replace(/^\uFEFF/,''));
const control=read(join(home,'control.json')),threads=read(join(home,'threads.json'));
const broker=control.broker&&existsSync(control.broker.healthPath)?read(control.broker.healthPath):undefined;
const historicalBrokers=(control.brokerHistory??[]).filter((history:any)=>history.runId!==broker?.runId).map((history:any)=>{
  const health=read(history.healthPath),reconciled=history.reconciliationPin?jsonPin(history.reconciliationPin).result:undefined;
  if(history.recoveryPin){const r=jsonPin(history.recoveryPin);return{...health,healthy:false,canonicalOwner:null,resources:{},resourceSlots:[],activeRequests:0,queuedRequests:0,lanes:r.lanes};}
  return {...health,lanes:health.lanes.map((lane:any)=>{
    const row=reconciled?.lanes.find((entry:any)=>entry.runId===lane.runId);
    return row?{...lane,billedUsd:row.effectiveBilledUsd,unknownCount:row.remainingUnknownCostCount,originalUnknownCostCount:row.originalUnknownCount,closed:true}:lane;
  })};
});
const allBrokers=[...historicalBrokers,...(broker?[broker]:[])];
const benches=['chembench','chemiq','skillsbench','terminal-bench'].map(slug=>{
  const s=existsSync(join(home,slug,'status.json'))?read(join(home,slug,'status.json')):{};
  const lanes=allBrokers.flatMap((entry:any)=>entry.lanes??[]).filter((l:any)=>l.slug===slug);
  return {slug,threadId:threads.threads.find((t:any)=>t.slug===slug)?.threadId,phase:s.phase??s.stage??'preparing',
    denominator:s.denominator??s.planned??null,completed:s.completed??0,passed:s.passed??0,
    dispatchedRequests:lanes.reduce((n:number,l:any)=>n+l.dispatched,0),knownBilledUsd:lanes.reduce((n:number,l:any)=>n+l.billedUsd,0),
    unknownCostCount:lanes.reduce((n:number,l:any)=>n+l.unknownCount,0),activeRequests:lanes.reduce((n:number,l:any)=>n+l.active,0),
    runnerPid:s.runnerPid??s.pid??s.processPid??s.backgroundPaidProcessPid??null,statusPath:join(home,slug,'status.json'),
    accountingClosed:lanes.length>0&&lanes.every((l:any)=>l.closed),financialClosed:lanes.length>0&&lanes.every((l:any)=>l.closed&&l.unknownCount===0),
    originalHistoricalUnknownCostCount:lanes.reduce((n:number,l:any)=>n+(l.originalUnknownCostCount??0),0),blockers:s.blockers??[],error:s.error??s.fatal??null};
});
const cancelled=['aime','gpqa','cmt','minif2f','deepswe'].map(slug=>{const s=read(join(home,slug,'status.json'));return{slug,cancelled:s.cancelled===true,benchModelRequests:s.modelRequests??s.externalModelCalls??s.providerRequests??0};});
const report={protocol:'four-bench-full-f-snapshot-v1',atUtc:new Date().toISOString(),codex:{model:'gpt-6.1-sol',effort:'medium',configuredServiceTier:'default'},
  model:'deepseek/deepseek-v4.1-flash',provider:broker?.providerName??'Relace',providerSwitch:control.providerSwitch??null,reasoningEnabled:true,arms:['F'],publicUOnly:true,currency:'USD',
  costPolicy:control.costPolicy??null,historicalBrokerRunIds:historicalBrokers.map((entry:any)=>entry.runId),
  broker:{healthy:broker?.healthy??false,stopReason:broker?.stopReason??null,pid:broker?.pid??null,maxInFlight:broker?.maxInFlight??4,activeRequests:broker?.activeRequests??0,queuedRequests:broker?.queuedRequests??0,
    canonicalOwnerActive:!!broker?.canonicalOwner,perBenchLimits:broker?.perBenchLimits??null,availableResourceSlots:broker?.availableResourceSlots??null,
    resourceOwners:Object.fromEntries(Object.entries(broker?.resources??{}).map(([k,v]:any)=>[k,{slug:v.slug,pid:v.pid}]))},benches,cancelled,
  knownBilledUsd:benches.reduce((n,b)=>n+b.knownBilledUsd,0),unknownCostCount:benches.reduce((n,b)=>n+b.unknownCostCount,0),
  invoice:false,modelCallsByThisSnapshot:0};
writeFileSync(join(home,'latest.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report,null,2));
