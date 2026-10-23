/** Initial delivery: two isolated paired lanes, lightweight receipts, no old
 * human API cap or cross-bench global lock. Existing graders are reused. */
import { randomBytes } from "node:crypto";
import { BENCHMARK_INFERENCE } from "../repair-2026-10-08/benchmark-inference.ts";
import { BENCHMARK_PROVIDER,benchmarkProviderKey } from "../repair-2026-10-08/benchmark-provider.ts";
import { acquireOpenRouterAdmission } from "../repair-2026-10-08/openrouter-paid-admission.ts";
import { existsSync, readFileSync, unlinkSync } from "node:fs";
import { join, resolve } from "node:path";
import { freemem } from "node:os";
import { actualPin, demand, hash, jsonPin, nanoCny, REAL_CLOCK, same } from "../repair-2026-10-08/paid-resource-proof-v2.ts";
import { durable } from "./tb12-v2/paid_admission.ts";
import { executePaired } from "./tb12-v2/paired_trial.ts";
import { executedSources } from "./tb12-v2/freeze_sources.ts";
const ROOT=resolve(import.meta.dir,"../.."),PREP=join(ROOT,"docs/repair-2026-10-09/tb12-preparation-v1");
const runId="repair-"+new Date().toISOString().replace(/[:.]/g,"-");
const home=join(ROOT,"docs/repair-2026-10-09/tb12-fast-runs-v3",runId);
const sourcePins=[...executedSources(),actualPin(import.meta.path)];
const scopePin=actualPin(join(ROOT,"docs/repair-2026-10-08/tb-multitask-twelve-scope-v1/task-scope.json"));
const taskIds=jsonPin(scopePin).taskIds as string[];demand(taskIds.length===12&&new Set(taskIds).size===12,"tb12_fast_fixed_scope");
const requestedCapUsd=process.argv[2]===undefined?undefined:Number(process.argv[2]);
if(requestedCapUsd!==undefined)demand(Number.isFinite(requestedCapUsd)&&requestedCapUsd>0,"tb12_openrouter_cap_usd");
const admission=await acquireOpenRouterAdmission({root:ROOT,output:home,runId,family:"terminal-bench-fast-corrected-v3",entry:import.meta.path,sourcePins,capUsd:requestedCapUsd});
const balancePin=admission.balance,pricePin=admission.prices,owned=admission.owned;
const providerKey=benchmarkProviderKey(ROOT),envelope=admission.capUsd;
const concurrency=freemem()>=5*1024**3?2:1;
durable(join(home,"manifest.json"),{protocol:"tb12-fast-initial-manifest-v3",runId,taskIds,plannedTaskRuns:24,arms:["U","F"],
  concurrency,pairedOrder:"U then F within each task; deterministic modulo task lanes",sourcePins,scopePin,balancePin,provider:BENCHMARK_PROVIDER.kind,currency:"USD",
  model:BENCHMARK_PROVIDER.model,...BENCHMARK_INFERENCE,thinking:{type:"enabled"},maxTokensPerRequest:BENCHMARK_INFERENCE.maxTokens,
  fixedHumanFeeCap:null,old9CnyLimitSuperseded:true,actualAvailableCashEnvelopeUsd:envelope,originalDeepSeekCnyLedgerReused:false,
  rawAccounting:true,initialDelivery:true,fullIndependentReviewDeferred:true,completePackageDeferred:true,old17RecordsExcludedFromComparison:true});
const records:any[]=[],results:any[]=[];
const publish=()=>{
  const rows=taskIds.map(taskId=>({taskId,...Object.fromEntries(["U","F"].map(arm=>{
    const value=records.find(row=>row.taskId===taskId&&row.arm===arm);return[arm,value??{status:"未完成"}];}))}));
  const score={U:records.filter(row=>row.arm==="U"&&row.passed).length,F:records.filter(row=>row.arm==="F"&&row.passed).length};
  const summary={protocol:"tb12-fast-initial-results-v3",runId,plannedTaskRuns:24,completedTaskRuns:records.length,
    distinctTasksWithResults:new Set(records.map(row=>row.taskId)).size,score,rows,records,
    initialDelivery:true,allCertificationsComplete:false,completePackageDeferred:true,old17RecordsExcluded:true,
    modelRequests:records.reduce((sum,row)=>sum+row.modelRequests,0),laneSummaries:results.map(value=>value.summary)};
  durable(join(home,"initial-results.json"),summary,true);
  const lines=["# Terminal-Bench 修正版初版结果", "", "固定 12 题同题 U/F；沿用原任务时间预算。旧 17 条记录只保留为诊断，不计此表。",
    "", "已评分 "+records.length+"/24 条；当前 U "+score.U+"、F "+score.F+"。未完成项目不能当作失败或通过。",
    "", "| 题目 | U | F |", "|---|---|---|"];
  for(const row of rows)lines.push("| "+row.taskId+" | "+(row.U.status??row.U.outcome)+" | "+(row.F.status??row.F.outcome)+" |");
  lines.push("", "初版已保存模型原始请求/响应、任务轨迹、实际原测试评分和容器关闭记录；完整打包、额外独立审阅与最终认证后置。",
    "", "机器可读结果：initial-results.json；原始记录：lane-0/、lane-1/。使用两个独立候选/评分服务；每题 U 后 F。API 用量与旧 9 元上限不再作为此次加速限制，仍保留轻量原始账本。", "");
  durable(join(home,"initial-report-data.json"),{lines},true);
  // Write a plain Markdown file, preserving normal line breaks.
  const {writeFileSync}=require("node:fs");writeFileSync(join(home,"初版结果.md"),lines.join("\n"));
};
publish();console.log(JSON.stringify({home,concurrency,initialReport:join(home,"初版结果.md"),modelRequests:0}));
await Promise.all(Array.from({length:concurrency},async(_,lane)=>{
  const selected=taskIds.filter((_,index)=>index%concurrency===lane),laneId=runId+"-"+lane;
  const output=join(ROOT,"docs/repair-2026-10-09/tb12-runs-v1",laneId);
  const selectedEnvelope=envelope/concurrency;
  const lease=admission.forkLane(laneId,output,selectedEnvelope);
  const result=await executePaired({kind:"real-provider",runId:laneId,output,sourcePins,prices:pricePin,admission:lease,providerKey,provider:BENCHMARK_PROVIDER,
    initialDelivery:true,realTaskIds:selected,onRecord(record){
      records.push({taskId:record.officialId,arm:record.arm,passed:record.acceptance.passed,outcome:record.acceptance.outcome,
        status:record.acceptance.passed?"通过":record.acceptance.outcome,modelRequests:record.calls.filter((row:any)=>row.providerAttempted).length,
        rawRecordPin:actualPin(join(output,"task-"+record.index+".json")),generationValid:record.generationValid,
        originalFinalGradePerformed:record.generation.kind!=="experimental_failure"});
      publish();console.log(JSON.stringify({completed:records.length,taskId:record.officialId,arm:record.arm,passed:record.acceptance.passed}));
    }});
  results.push(result);publish();
}));
const closed=results.every(result=>result.standClose&&result.financialClose&&jsonPin(result.financialClose.cashClose).releasePermitted===true);
durable(join(home,"initial-close-summary.json"),{runId,operationalComplete:results.every(result=>result.complete)&&records.length===24,
  allLaneClosuresObserved:closed,laneResults:results,fullIndependentCertification:false,source:actualPin(import.meta.path)});
if(closed){admission.finishLightweight({ownedGenerationClosed:true,pendingRequests:0,laneResults:results.map(value=>value.summary)});durable(join(home,"bench-lock-release.json"),{owned,allLaneClosuresObserved:true,exactOwnBenchLockRemoved:true});}
publish();console.log(JSON.stringify({home,completed:records.length,allLaneClosuresObserved:closed,initialReport:join(home,"初版结果.md")}));
process.exitCode=records.length===24&&closed?0:2;
