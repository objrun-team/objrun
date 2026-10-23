/** TB revision 2: allow failed F candidate repair; seal only at terminal state. */

import {alignToolUnitBudget} from './tool-unit-budget.next.ts';
import { randomBytes } from "node:crypto";

import { BENCHMARK_PROVIDER, type BenchmarkProvider } from "../shared/digitalocean-provider.ts";

import { BENCHMARK_INFERENCE } from "../shared/digitalocean-inference.ts";

import { existsSync, mkdirSync, readFileSync } from "node:fs";

import { join, resolve } from "node:path";

import { Database } from "bun:sqlite";

import { finalCandidate } from "../../../../app/src/objective/candidate.ts";

import { classifyGeneration, gradeFixedCandidate, campaignComplete } from "../../../benchmark-repair/campaign-contract.ts";

import { actualPin, demand, hash, jsonPin, verifyPin, type Pin } from "../../../benchmark-repair/paid-resource-proof-v2.ts";

import { durable, TB12_FAMILY } from "../../../terminal-bench-repair/tb12-v2/paid_admission.ts";

import { providerGateway } from "./provider_gateway.ts";

import { freezeEngine, startEngine } from "./freeze_engine.ts";

import { startStand } from "../../../terminal-bench-repair/tb12-v2/stand_process.ts";

import { executedSources, snapshotSources } from "./gzip-build-pov-ray-image-pool-custody.next.ts";

import { segmentScope } from './segment-scope.ts';

import { engineTaskId } from './engine-task-id.ts';



const ROOT=resolve(import.meta.dir,"../../../..");

const SIX=["bash","read","write","edit","glob","grep"];

function objective(stand:string){return{nodes:[{name:"ran",domain:"bool",moment:"done",handle:stand+"/ran"},

  {name:"passed",domain:"bool",moment:"done",handle:stand+"/passed"}],edges:[{src:"ran",out:0,dst:"passed"}],

  sink:"passed",checks:4,reuse:"never"};}



/** Full denominator with either full readiness or a strictly proved ready segment. */

export async function executeFullF(options:{

  kind:"real-provider"|"local-mock";runId:string;output:string;sourcePins:Pin[];prices:Pin;

  provider?:BenchmarkProvider;admission?:Parameters<typeof providerGateway>[0]["admission"];providerKey?:string;

  transport?:(raw:string)=>Promise<{httpStatus:number;rawResponse:string}>;

  readinessPath?:string;

  /** Cold chess pair validates the actual project engine and hook path. */

  coldTaskIds?:string[];

  secrets?:Set<string>;

  initialDelivery?:boolean;realTaskIds?:string[];onRecord?:(record:any)=>void;

}) {

  const output=resolve(options.output);mkdirSync(output,{recursive:true});

  // Polling an admitted task checks ownership and immutable source. The full

  // resource floor is checked by the gateway immediately before each forward;

  // temporary verifier memory must not abort already-admitted work.

  const sourceGuard=()=>{Bun.gc(true);if(!options.initialDelivery)for(const pin of options.sourcePins)verifyPin(pin);options.admission?.assertOwned();};

  for(const pin of options.sourcePins)verifyPin(pin);

  sourceGuard();

  snapshotSources(output,options.sourcePins);

  const baseProof=options.readinessPath??join(ROOT,"docs/repair-2026-10-10/full-f-rerun/terminal-bench/private-scoring-ready.json");

  const context=jsonPin(actualPin(jsonPin(actualPin(baseProof)).contextManifest.path));

  const taskIds=options.kind==="local-mock"?options.coldTaskIds??["chess-best-move"]:options.realTaskIds??context.tasks.map((task:any)=>task.taskId);

  const scope=segmentScope(context.tasks.map((task:any)=>task.taskId),taskIds);

  if(taskIds.length!==89){

    const ready=jsonPin(actualPin(baseProof));

    demand(!!options.readinessPath&&ready.protocol==='terminal-ready-segment-v1'&&ready.fullPlanTaskCount===89&&

      JSON.stringify(ready.readyTaskIds)===JSON.stringify(taskIds),'terminal_ready_segment_proof');

  }

  const selected=context.tasks.filter((task:any)=>taskIds.includes(task.taskId));

  demand(selected.length===taskIds.length,"tb12_task_selection");

  const graderToken=randomBytes(32).toString("hex");

  const secrets=options.secrets??new Set<string>();

  secrets.add(graderToken);if(options.providerKey)secrets.add(options.providerKey);

  const routeProvider=options.provider??(options.kind==="real-provider"?BENCHMARK_PROVIDER:undefined);

  const model=routeProvider?.model??"deepseek-flash",keyEnv=routeProvider?"OPENROUTER_API_KEY":"DEEPSEEK_API_KEY";

  const provider=providerGateway({...options,provider:routeProvider,sourceGuard});

  secrets.add(provider.token);

  let stand:Awaited<ReturnType<typeof startStand>>|undefined;

  let machine:Awaited<ReturnType<typeof startEngine>>|undefined;

  const records:any[]=[],engineClosures:Pin[]=[];

  let fatal:any=null,standClose:Pin|undefined,financialClose:any,bundle:any;

  const boardHashes=new Map<string,string>();

  try {

    bundle=await freezeEngine(join(output,"frozen-engine"));

    stand=await startStand({output:join(output,"stand-process"),script:join(import.meta.dir,"stand_admitted_runtime_next.py"),baseProof,token:graderToken});

    process.env.TGENGIN_GRADER_TOKEN=graderToken;

    process.env.TGENGIN_GRADER_ORIGINS=stand.origin;

    durable(join(output,"manifest.json"),{protocol:"tb12-paired-trial-manifest-v1",family:TB12_FAMILY,runId:options.runId,

      providerKind:options.kind,...scope,arms:["F"],replica:0,

      model,provider:routeProvider?.kind??"deepseek-direct",providerName:routeProvider?.providerName,providerSlug:routeProvider?.providerSlug,currency:routeProvider?"USD":"CNY",...BENCHMARK_INFERENCE,thinking:{type:"enabled"},maxTokensPerRequest:BENCHMARK_INFERENCE.maxTokens,

      checks:4,reuse:"never",maxBranches:1,maxDeadSiblings:1,maxUnitsPerCycle:32,

      taskDeadlines:context.tasks.map((task:any)=>({taskId:task.taskId,agentSeconds:task.agentSeconds,verifierSeconds:task.verifierSeconds})),

      officialScope:actualPin(join(ROOT,"docs/repair-2026-10-10/full-f-rerun/terminal-bench/manifest.json")),

      contextManifest:actualPin(jsonPin(actualPin(baseProof)).contextManifest.path),baseProof:actualPin(baseProof),

      sourcePins:options.sourcePins,hostBun:actualPin(process.execPath),hostBunVersion:Bun.version,bundle,

      oldSingleNginxCounts:false,fullRunAuthorized:true,pairedOrder:"fixed public task order; F only",

      gradedInterface:"sealed regular data; untrusted OpenSSL script worker; narrow live nginx",

      feedback:"ran/passed booleans with generic failure note; no private assertions in model context",

      namespaceAndClockMeasuredBeforeAnyModel:true,paidConcurrency:1,

      executionRevision:"terminal-only-seal-v2",sealPolicy:"after actual task terminal and no pending provider transfer; before engine close and host final grade",

      initialDelivery:options.initialDelivery??false,fullIndependentReviewDeferred:options.initialDelivery??false,

      operationalCaptureLimitBytes:2*1024**2,officialStorageBytes:10240*1024**2,

      perContainerStorageQuotaEnforced:false,storageBoundaryPolicy:"10 GiB writable layer samples before/after tools and at seal; no continuous hard quota",

      guestAvailableStorageMeasuredBeforeAnyModel:true});

    for(const task of selected)for(const arm of ["F"] as const) {

      sourceGuard();

      const index=records.length,id=engineTaskId(options.runId,arm,task.taskId),place="tb12:"+id;

      const route=options.runId+"/"+arm+"/0/"+task.taskId;

      const up=await stand.call("/up",{place,attemptId:id,taskId:task.taskId,arm});

      let board:Pin|undefined;

      if(up.publicImage?.exists) {

        board=actualPin(up.publicImage.stored);

        demand(board.sha256===up.publicImage.sha256,"tb12_public_board_integrity");

        const prior=boardHashes.get(task.taskId);

        if(prior)demand(prior===board.sha256,"tb12_paired_image_changed");else boardHashes.set(task.taskId,board.sha256);

      }

      provider.register(route,task.taskId,arm,board);

      const engineDirectory=join(output,"workers",String(index)+"-"+arm);

      machine=await startEngine({directory:engineDirectory,bundle:bundle.executable,proxyKey:provider.token,

        graderToken,graderOrigins:[stand.origin],onSecret:value=>secrets.add(value)});

      await machine.api("POST","/exec",{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select :key,:model,handle,modes,:base,'[]' from api where key_env=:key and model=:seed",

        params:{key:keyEnv,model,seed:routeProvider?model:"deepseek-v4-flash",base:provider.origin+"/"+route+"/v1"}});

      const verifierMs=(task.verifierSeconds+30)*1000,toolMs=(task.agentSeconds+30)*1000;

      await machine.api("POST","/declare",{handles:[{name:stand.origin+"/place",expectMs:toolMs},

        ...["ran","passed"].map(node=>({name:stand!.origin+"/"+node,expectMs:verifierMs}))],

        places:[{place,identity:stand.origin+"/place",forward:true,tools:SIX.map(tool=>({tool,policy:"always"}))}],

        modes:[{mode:"repair_tb12",cycles:[{cycle:"ask",apiMode:"chat",maxUnits:32,from:[],next:["act"],infer:"fn:infer.dfs"},

          {cycle:"act",maxUnits:32,from:["ask"],next:["ask"],infer:"fn:infer.dfs"}]}],

        agents:[{name:"bot",apis:[[keyEnv,model]],unit:"fn:unit.tools"}]});

      await alignToolUnitBudget(machine,toolMs,join(engineDirectory,"tool-unit-envelope.json"));

      await machine.api("POST","/exec",{sql:"update tool set usable=0 where name not in ('bash','read','write','edit','glob','grep','submit','verify')"});

      const publicRoot=join(ROOT,".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks",task.taskId);

      const instruction=readFileSync(join(publicRoot,"instruction.md"),"utf8");

      const prompt=instruction+"\n\nEvery bash/read/write/edit/glob/grep call runs inside your task container. Submit the completed filesystem or service state; your answer is only an attempt label. Official tests remain outside your container. Use verify only when offered.";

      const started=Date.now();

      await stand.call("/begin",{place});

      await machine.api("POST","/tasks",{id,run:options.runId,mode:"repair_tb12",agent:"bot",place,source:"user",

        domain:"software",workdir:"/app",description:prompt,

        ...(arm==="F"?{objective:objective(stand.origin),readable:false}:{}),

        solveSeconds:task.agentSeconds,maxBranches:1,maxDeadSiblings:1,

        noSearch:["terminal-bench solution",task.taskId+" solution"]});

      let result:any,sealed=false;

      const expiry=started+(task.agentSeconds+task.verifierSeconds*5+120)*1000;

      while(Date.now()<expiry) {

        sourceGuard();

        let standState:any;
        for(let probe=0;probe<3;probe++){
          try{standState=JSON.parse(readFileSync(join(output,"stand-process/stand/stand-receipts.json"),"utf8"));break;}
          catch(error){if(!(error instanceof SyntaxError))throw error;if(probe===2)throw Error("terminal_stand_receipt_unreadable_after_bounded_retry");await Bun.sleep(25);}
        }

        if(standState.fatal){

          // Stop new paid requests immediately; allow already admitted requests to finish.

          provider.seal(route);

          if(!(provider.pending.get(route)??0))throw Error("terminal_stand_fault_admission_closed:"+standState.fatal.type);

          await Bun.sleep(250);continue;

        }

        const state=await machine.api<any>("GET","/tasks/"+encodeURIComponent(id));

        // A unit's submit can fail F acceptance and lead to another repair unit.

        // The stand serializes every runtime snapshot/grade and unpauses it;

        // a terminal task is the boundary for permanently closing mutations.

        const verdict=state.result?JSON.parse(String(state.result)):null;

        if(["done","failed"].includes(state.state)&&!["finalization_pending","finalization_error"].includes(verdict?.outcome)&&!(provider.pending.get(route)??0)) {

          result=state;provider.seal(route);

          if(!sealed){await stand.call("/seal",{place},verifierMs+30000);sealed=true;}

          break;

        }

        if(provider.fault())throw Error(provider.fault());

        await Bun.sleep(250);

      }

      demand(result,"tb12_actual_task_terminal_required");

      const engineClose=await machine.stop();engineClosures.push(engineClose);machine=undefined;

      const db=new Database(join(engineDirectory,"data/h2h.sqlite"),{readonly:true});

      let candidate:{body:string;how:string}|undefined;

      let trace:{rows:any[]},units:{rows:any[]};

      try{

        // Read the closed database directly: the HTTP query endpoint caps rows.

        trace={rows:db.query("select * from agent_bot_msg where instance like ? order by unit,seq").all(id+"#%")};

        units={rows:db.query("select * from agent_bot_ctx where instance like ? order by unit").all(id+"#%")};

        demand(units.rows.every((unit:any)=>Number(unit.done)===1),"tb12_unfinished_execution_unit");

        candidate=finalCandidate({all:(sql,params)=>db.query(sql).all(...((params??[]) as never[])) as any[],

        run(){throw Error("readonly");},exec(){throw Error("readonly");},close(){}},id);}finally{db.close();}

      const calls=provider.calls.filter(call=>call.route===route);

      const tools=trace.rows.filter(row=>row.kind==="tool").map(row=>({at:Number(row.at),...JSON.parse(String(row.body))}));

      const firstSubmit=tools.filter(row=>row.name==="submit").sort((a,b)=>a.at-b.at)[0];

      const repairedAfterFailedSubmit=!!firstSubmit&&tools.some(row=>row.name==="write"&&row.at>firstSubmit.at&&!row.value?.error);

      if(options.kind==="local-mock"&&arm==="F")demand(repairedAfterFailedSubmit,"tb12_actual_F_post_submit_repair_required");

      const runtimeVerdict=result.result?JSON.parse(String(result.result)):{valid:true,outcome:"unaided_generated"};

      const generation=classifyGeneration({runtimeVerdict,state:String(result.state),calls,trace:trace.rows,candidate:candidate?.body});

      const deadline=Number(result.created_at)+Number(result.solve_seconds)*1000;

      const lateMutation=trace.rows.some((row:any)=>{

        if(row.kind!=="tool"||Number(row.at)<=deadline)return false;

        try{return["bash","write","edit"].includes(JSON.parse(String(row.body)).name);}catch{return false;}

      });

      if(generation.valid&&lateMutation){generation.kind="experimental_failure";generation.outcome="budget_exhausted";generation.why="A mutation completed after the official task deadline.";}

      const record:any={index,family:TB12_FAMILY,runId:options.runId,officialId:task.taskId,arm,replica:0,taskId:id,place,

        candidateCid:up.cid,startedAtUtc:new Date(started).toISOString(),createdAt:result.created_at,deadlineUnixMs:deadline,

        agentSeconds:task.agentSeconds,verifierSeconds:task.verifierSeconds,

        promptSha256:hash(prompt),answer:candidate?.body??"",candidateHow:candidate?.how??"none",

        candidateLabelSha256:hash(candidate?.body??""),generation,generationValid:generation.valid,

        state:result.state,runtimeVerdict,engineClosePin:engineClose,trace:trace.rows,units:units.rows,calls,

        publicImagePin:board??null,lateMutation,sealedBeforeHostFinalGrade:true,hostEngineClosedBeforeFinalGrade:true,

        repairedAfterFailedSubmit,executionRevision:"terminal-only-seal-v2"};

      durable(join(output,"task-"+index+".json"),record);

      sourceGuard();

      record.acceptance=generation.valid&&generation.kind==="experimental_failure"?

        {valid:true,passed:false,outcome:generation.outcome,why:generation.why,candidateSha256:record.candidateLabelSha256,nodes:{}}:

        await gradeFixedCandidate({objective:objective(stand.origin),task:result,candidate:candidate?.body,

          expectedCandidateSha256:record.candidateLabelSha256,generation,timeoutMs:verifierMs});

      sourceGuard();

      durable(join(output,"task-"+index+".json"),record,true);

      records.push({index:record.index,acceptance:record.acceptance});

      await stand.call("/stop",{place});

      options.onRecord?.(record);

      durable(join(output,"summary.json"),{protocol:"tb12-paired-operational-summary-v1",family:TB12_FAMILY,

        runId:options.runId,providerKind:options.kind,...scope,recordedTaskRuns:records.length,

        operationalComplete:false,fatal:null,taskPins:records.map(row=>actualPin(join(output,"task-"+row.index+".json")))},true);

      console.log(JSON.stringify({taskId:task.taskId,arm,valid:record.acceptance.valid,passed:record.acceptance.passed,

        modelRequests:options.kind==="real-provider"?calls.filter(call=>call.providerAttempted).length:0}));

      if(!generation.valid||record.acceptance.valid!==true)throw Error("tb12_invalid_generation_or_grading_record");

    }

  }catch(error){fatal=error instanceof Error?{name:error.name,message:error.message,stack:error.stack}:String(error);}

  finally{

    if(machine)try{engineClosures.push(await machine.stop());machine=undefined;}catch(error){fatal??=String(error);}

    if(stand)try{standClose=await stand.close();stand=undefined;}catch(error){fatal??=String(error);}

    try{await provider.stop();financialClose=provider.close();}catch(error){fatal??=String(error);}

  }

  const segmentComplete=!fatal&&campaignComplete(taskIds.length,records);

  const complete=!fatal&&campaignComplete(scope.plannedTaskRuns,records);

  const summary=durable(join(output,"summary.json"),{protocol:"tb12-paired-operational-summary-v1",family:TB12_FAMILY,

    runId:options.runId,providerKind:options.kind,...scope,recordedTaskRuns:records.length,segmentComplete,

    operationalComplete:complete,formalScoreCertified:false,fatal,engineClosures,standClose:standClose??null,

    financialClose:financialClose??null,taskPins:records.map(row=>actualPin(join(output,"task-"+row.index+".json"))),

    modelCalls:options.kind==="real-provider"?provider.calls.filter(call=>call.providerAttempted).length:0,

    oldNginxIncluded:false,fullPlanActivated:true,fullRunExecuted:complete},true);

  return{summary,complete,segmentComplete,fatal,engineClosures,standClose,financialClose};

}


