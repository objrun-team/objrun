import { expect, test } from "bun:test";
import { mkdirSync, mkdtempSync, rmSync, statfsSync, writeFileSync } from "node:fs";
import { freemem, tmpdir } from "node:os";
import { join } from "node:path";
import { machine, type Machine } from "../_lib.ts";
import { requestedWorkers, workerPreflight, roundRobinBenchmarks } from "../../scripts/benchmark-repair/campaign-workers.ts";

test("four workers are preferred and explicit counts are checked before generation", () => {
  expect(requestedWorkers()).toBe(4);
  for (const value of ["1","2","3","4"]) expect(requestedWorkers(value)).toBe(Number(value));
  for (const value of ["", "0", "5", "2.5", "NaN", " 4 "]) expect(()=>requestedWorkers(value)).toThrow();
  const GiB=1024**3;
  expect(workerPreflight({requested:4,freeMemoryBytes:2*GiB,freeDiskBytes:2*GiB})).toMatchObject({selected:4,reason:"requested_workers_available"});
  expect(workerPreflight({requested:4,freeMemoryBytes:GiB,freeDiskBytes:2*GiB})).toMatchObject({selected:2,reason:"reduced_before_generation_for_memory_or_disk"});
  expect(workerPreflight({requested:4,freeMemoryBytes:2*GiB,freeDiskBytes:768*1024**2})).toMatchObject({selected:2});
  expect(()=>workerPreflight({requested:4,freeMemoryBytes:512*1024**2,freeDiskBytes:2*GiB})).toThrow("before generation");
});

test("independent benchmark tasks alternate without changing their arm/replica order", () => {
  const tasks=[...Array.from({length:4},(_,i)=>({benchmark:"gpqa",arm:["U","R","R","F"][i],replica:i,officialId:"same-id"})),...Array.from({length:2},(_,i)=>({benchmark:"cmt",arm:i?"F":"U",replica:0,officialId:"same-id"}))];
  const schedule=roundRobinBenchmarks(tasks,["gpqa","cmt"]);
  expect(schedule.map(task=>task.benchmark)).toEqual(["gpqa","cmt","gpqa","cmt","gpqa","gpqa"]);
  expect(schedule.filter(task=>task.benchmark==="gpqa")).toEqual(tasks.slice(0,4));
  expect(schedule.filter(task=>task.benchmark==="cmt")).toEqual(tasks.slice(4));
  expect(()=>roundRobinBenchmarks(tasks,["gpqa"])).toThrow();
  expect(()=>roundRobinBenchmarks(tasks,["gpqa","gpqa","cmt"])).toThrow();
});

test("four real local workers share one mock provider and a fixed mixed-benchmark queue", async () => {
  const directory=mkdtempSync(join(tmpdir(),"tgengin-four-worker-"));
  const disk=statfsSync(directory), admission=workerPreflight({requested:4,freeMemoryBytes:freemem(),freeDiskBytes:disk.bavail*disk.bsize});
  const prior=process.env.OBJRUN_WORKER_TEST_KEY;process.env.OBJRUN_WORKER_TEST_KEY="local-mock-only";
  let active=0,peak=0,calls=0;
  const provider=Bun.serve({hostname:"127.0.0.1",port:0,async fetch(request){expect(request.headers.get("authorization")).toBe("Bearer local-mock-only");active++;peak=Math.max(peak,active);calls++;await Bun.sleep(200);active--;return Response.json({id:"mock-"+calls,model:"local-mock",choices:[{message:{role:"assistant",content:null,tool_calls:[{id:"submit-"+calls,type:"function",function:{name:"submit",arguments:JSON.stringify({answer:"fixed local answer"})}}]},finish_reason:"tool_calls"}],usage:{prompt_tokens:1,completion_tokens:1}});}});
  const engines:Machine[]=[], completed:number[]=[];
  const plan=roundRobinBenchmarks([0,1,2,3].flatMap(i=>[{benchmark:"gpqa",officialId:"same-"+i},{benchmark:"cmt",officialId:"same-"+i}]),["gpqa","cmt"]);
  let next=0;
  try {
    expect(admission.selected).toBe(4);
    await Promise.all(Array.from({length:4},async(_,workerId)=>{
      mkdirSync(join(directory,"worker-"+workerId),{recursive:true});
      const engine=await machine({maxTokens:8192,retryTimes:0,continueTimes:0,reasoningEffort:"none",temperature:0,seed:42},{directory:join(directory,"worker-"+workerId),keep:true});engines.push(engine);
      await engine.api("POST","/exec",{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'OBJRUN_WORKER_TEST_KEY','deepseek-flash',handle,modes,:base,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'",params:{base:"http://127.0.0.1:"+provider.port+"/v1"}});
      await engine.api("POST","/declare",{places:[{place:"local"}],modes:[{mode:"worker_probe",cycles:[{cycle:"ask",apiMode:"chat",maxUnits:2,from:[],next:["act"],infer:"fn:infer.dfs"},{cycle:"act",maxUnits:2,from:["ask"],next:["ask"],infer:"fn:infer.dfs"}]}],agents:[{name:"bot",apis:[["OBJRUN_WORKER_TEST_KEY","deepseek-flash"]],unit:"fn:unit.tools"}]});
      await engine.api("POST","/exec",{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
      while(next<plan.length){const index=next++,task=plan[index]!,id="preparation/"+task.benchmark+"/U0/"+task.officialId;await engine.api("POST","/tasks",{id,run:"local-preparation",mode:"worker_probe",agent:"bot",place:"local",source:"user",description:"Local worker preparation only",solveSeconds:10,maxBranches:1,maxDeadSiblings:1});let done=false;for(let i=0;i<500;i++){const result=await engine.api<{state:string}>("GET","/tasks/"+encodeURIComponent(id));if(result.state==="done"){done=true;break;}await Bun.sleep(10);}expect(done).toBe(true);completed.push(index);}
    }));
    expect(new Set(engines.map(engine=>engine.pid)).size).toBe(4);
    expect(completed.sort((a,b)=>a-b)).toEqual(plan.map((_,i)=>i));
    expect(calls).toBe(16);expect(peak).toBe(4);expect(active).toBe(0);
    writeFileSync(join(directory,"campaign-four-worker-local.json"),JSON.stringify({observedAt:new Date().toISOString(),valid:true,scope:"Local mock preparation only; no benchmark score",realLLMRequests:0,costUsd:0,mockCompletionCalls:calls,providerPeakRequests:peak,workerPids:engines.map(engine=>engine.pid),workerPreflight:admission,schedule:plan.map((task,index)=>({index,...task})),completedIndices:completed,oneProvider:true},null,2)+"\n");
  } finally {await Promise.all(engines.map(engine=>engine.stop()));await provider.stop(true);process.env.OBJRUN_WORKER_TEST_KEY=prior;rmSync(directory,{recursive:true,force:true});}
},15000);
