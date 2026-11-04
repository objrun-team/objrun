import { expect, test } from "bun:test";
import { mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { tbToolGateway } from "../../scripts/benchmark-repair/tb-tool-gateway.ts";
import { tbEngine } from "../../scripts/benchmark-repair/tb-engine.ts";
import { nginxGeneration } from "../../scripts/benchmark-repair/tb-nginx-contract.ts";

test("the authenticated gateway seals admission and drains every actual forwarded response", async () => {
  const directory=mkdtempSync(join(tmpdir(),"tgengin-tb-gateway-")), oldToken=process.env.TGENGIN_GRADER_TOKEN, oldOrigins=process.env.TGENGIN_GRADER_ORIGINS;
  let release!:()=>void, forwarded=0, completed=0;
  const hold=new Promise<void>(resolve=>{release=resolve;});
  const stand=Bun.serve({hostname:"127.0.0.1",port:0,async fetch(request){expect(request.headers.get("X-ObjRun-Grader-Token")).toBe("fixture-token");forwarded++;await hold;completed++;return Response.json({code:0,stdout:"finished",stderr:""});}});
  const gateway=tbToolGateway({stand:"http://127.0.0.1:"+stand.port,token:"fixture-token",store:directory,ledger(){}});
  process.env.TGENGIN_GRADER_TOKEN="fixture-token";process.env.TGENGIN_GRADER_ORIGINS="http://127.0.0.1:"+stand.port;
  gateway.register("owned",()=>undefined);
  const call=(token:string)=>fetch(gateway.origin+"/place",{method:"POST",headers:{"X-ObjRun-Grader-Token":token,"content-type":"application/json"},body:JSON.stringify({place:"owned",tool:"bash",args:{command:"true"}})});
  try {
    expect((await call("")).status).toBe(401);expect((await call("forged")).status).toBe(401);expect(forwarded).toBe(0);
    const a=call("fixture-token"), b=call("fixture-token");
    for(let i=0;i<100&&forwarded!==2;i++)await Bun.sleep(5);
    expect(forwarded).toBe(2);gateway.seal("owned");
    expect((await call("fixture-token")).status).toBe(409);expect(forwarded).toBe(2);
    let drained=false;const barrier=gateway.drain("owned",1000).then(value=>{drained=true;return value;});
    await Bun.sleep(20);expect(drained).toBe(false);expect(completed).toBe(0);
    release();expect((await a).status).toBe(200);expect((await b).status).toBe(200);
    const closure=await barrier;expect(closure.outstanding).toBe(0);expect(completed).toBe(2);
    expect(closure.receipts.filter(row=>row.forwarded).every(row=>!!row.finishedAt&&row.httpStatus===200)).toBe(true);
    expect(closure.receipts.find(row=>!row.forwarded)?.denial).toBe("task_delivered");
    expect(readFileSync(join(directory,"tool-0-request.json.gz")).length).toBeGreaterThan(0);
  } finally {release();await gateway.stop();await stand.stop(true);process.env.TGENGIN_GRADER_TOKEN=oldToken;process.env.TGENGIN_GRADER_ORIGINS=oldOrigins;rmSync(directory,{recursive:true,force:true});}
});

test("a real U task reaches task_timeout before its admitted tool completes; drain preserves the late receipt", async () => {
  const directory=mkdtempSync(join(tmpdir(),"tgengin-tb-timeout-"));
  const prior={token:process.env.TGENGIN_GRADER_TOKEN,origins:process.env.TGENGIN_GRADER_ORIGINS,key:process.env.OBJRUN_TB_GATE_TEST_KEY};
  let forwarded=0;
  const stand=Bun.serve({hostname:"127.0.0.1",port:0,async fetch(){forwarded++;await Bun.sleep(1800);return Response.json({code:0,stdout:"late actual finish",stderr:""});}});
  const gateway=tbToolGateway({stand:"http://127.0.0.1:"+stand.port,token:"fixture-token",store:join(directory,"tools"),ledger(){}});
  process.env.TGENGIN_GRADER_TOKEN="fixture-token";process.env.TGENGIN_GRADER_ORIGINS="http://127.0.0.1:"+stand.port+","+gateway.origin;process.env.OBJRUN_TB_GATE_TEST_KEY="fixture-api";
  const provider=Bun.serve({hostname:"127.0.0.1",port:0,fetch:()=>Response.json({id:"local-only",model:"local-mock",choices:[{message:{role:"assistant",content:null,tool_calls:[{id:"late",type:"function",function:{name:"bash",arguments:JSON.stringify({command:"safe-local-mock"})}}]},finish_reason:"tool_calls"}],usage:{prompt_tokens:1,completion_tokens:1}})});
  let engine:Awaited<ReturnType<typeof tbEngine>>|undefined;
  try {
    gateway.register("owned",()=>undefined);
    engine=await tbEngine({maxTokens:8192,retryTimes:0,continueTimes:0,reasoningEffort:"none",temperature:0,seed:42},join(directory,"engine"));
    await engine.api("POST","/exec",{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select 'OBJRUN_TB_GATE_TEST_KEY','deepseek-flash',handle,modes,:base,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'",params:{base:"http://127.0.0.1:"+provider.port+"/v1"}});
    await engine.api("POST","/declare",{handles:[{name:gateway.origin+"/place",expectMs:930000}],places:[{place:"owned",identity:gateway.origin+"/place",forward:true,tools:[{tool:"bash",policy:"always"}]}],modes:[{mode:"late_probe",cycles:[{cycle:"ask",apiMode:"chat",maxUnits:2,from:[],next:["act"],infer:"fn:infer.dfs"},{cycle:"act",maxUnits:2,from:["ask"],next:["ask"],infer:"fn:infer.dfs"}]}],agents:[{name:"bot",apis:[["OBJRUN_TB_GATE_TEST_KEY","deepseek-flash"]],unit:"fn:unit.tools"}]});
    await engine.api("POST","/exec",{sql:"update tool set usable=0 where name not in ('bash','submit')"});
    await engine.api("POST","/tasks",{id:"late-task",run:"local-probe",mode:"late_probe",agent:"bot",place:"owned",source:"user",description:"Local deterministic regression",solveSeconds:1,maxBranches:1,maxDeadSiblings:1});
    let task:{state:string;result:string;created_at:number;solve_seconds:number}|undefined;
    for(let i=0;i<300;i++){const value=await engine.api<typeof task>("GET","/tasks/late-task");if(value?.state==="failed"){task=value;break;}await Bun.sleep(10);}
    expect(task).toBeDefined();expect(JSON.parse(task!.result).outcome).toBe("task_timeout");expect(forwarded).toBe(1);
    // This is the old runner's failure: terminal + no provider pending does not
    // certify tool completion. A recorded actual response is still missing.
    expect(gateway.receipts.some(row=>row.forwarded&&!row.finishedAt)).toBe(true);
    gateway.seal("owned","task_timeout");const closure=await gateway.drain("owned",3000);
    expect(closure.receipts[0]!.finishedAt!).toBeGreaterThan(task!.created_at+1000);
    let trace:{rows:Record<string,unknown>[]};
    for(let i=0;;i++){trace=await engine.api("POST","/query",{sql:"select * from agent_bot_msg where instance like 'late-task#%' order by unit,seq"});if(trace.rows.some(row=>row.kind==="tool")||i===100)break;await Bun.sleep(10);}
    const verdict=nginxGeneration({runtimeVerdict:JSON.parse(task!.result),state:task!.state,deadline:task!.created_at+1000,candidate:undefined,calls:[{httpStatus:200,finishedAt:"closed",usage:{prompt_tokens:1,completion_tokens:1}}],trace:trace!.rows});
    expect(verdict).toMatchObject({valid:true,kind:"experimental_failure",outcome:"budget_exhausted"});
    expect(trace!.rows.some(row=>row.kind==="tool"&&Number(row.at)>task!.created_at+1000)).toBe(true);
  } finally {if(engine)await engine.stop();await gateway.stop();await stand.stop(true);await provider.stop(true);process.env.TGENGIN_GRADER_TOKEN=prior.token;process.env.TGENGIN_GRADER_ORIGINS=prior.origins;process.env.OBJRUN_TB_GATE_TEST_KEY=prior.key;rmSync(directory,{recursive:true,force:true});}
},10000);
