import { expect, test } from "bun:test";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { acquirePaidCampaignLock } from "../scripts/repair-2026-10-08/paid-campaign-lock.ts";
import { nginxGeneration, nginxObjective, requireSafeHealth, requireNginxPreflight, IMAGE_ID, mockCall, TASK_ID, SIX_TOOLS } from "../scripts/repair-2026-10-08/tb-nginx-contract.ts";
import { tbEngine } from "../scripts/repair-2026-10-08/tb-engine.ts";

const health = () => ({ isolationReady:true,authenticated:true,unsafeDiagnostic:false,runtimeReady:true,backend:"docker",protocol:"tb-live-nginx-io-v1",maxLiveCandidates:1,graders:1,tasks:89,unsupportedTaskCount:88,level:2,supportedTaskIds:[TASK_ID],supportedTools:[...SIX_TOOLS] });
test("nginx gate rejects unsupported tasks, shared graders and missing tool executors", () => {
  expect(() => requireSafeHealth(health())).not.toThrow();
  for (const change of [{supportedTaskIds:[TASK_ID,"other-task"]},{isolationReady:false},{authenticated:false},{unsafeDiagnostic:true},{backend:"apptainer"},{unsupportedTaskCount:0},{supportedTools:["bash"]}]) expect(() => requireSafeHealth({...health(),...change})).toThrow();
  expect(nginxObjective("http://127.0.0.1:1").reuse).toBe("never");
});
test("late live mutations cannot pass while ordinary post-delivery grading may finish later", () => {
  const input = { runtimeVerdict:{valid:true,outcome:"passed"},state:"done",calls:[{httpStatus:200,finishedAt:"now",usage:{prompt_tokens:1,completion_tokens:1}}],candidate:"v1",deadline:1000 };
  expect(nginxGeneration({...input,trace:[{kind:"tool",at:1001,body:JSON.stringify({name:"bash"})}]})).toMatchObject({valid:true,kind:"experimental_failure",outcome:"budget_exhausted"});
  expect(nginxGeneration({...input,trace:[{kind:"tool",at:1001,body:JSON.stringify({name:"verify"})}]})).toMatchObject({valid:true,kind:"candidate"});
  expect(nginxGeneration({...input,runtimeVerdict:{valid:false,outcome:"grader_error"},trace:[]})).toMatchObject({valid:false,kind:"infrastructure_error"});
  expect(nginxGeneration({...input,candidate:undefined,trace:[]})).toMatchObject({valid:true,kind:"experimental_failure",outcome:"no_candidate"});
});
test("both mock arms exercise the same six tools and only F gets verify", () => {
  const u = Array.from({length:7},(_,i)=>mockCall(i,"U").name), f=Array.from({length:8},(_,i)=>mockCall(i,"F").name);
  expect(u).toEqual([...SIX_TOOLS,"submit"]);
  expect(f).toEqual([...SIX_TOOLS,"verify","submit"]);
});
test("paid TB cannot use failed, partial or stale official controls", () => {
  const control={valid:true,ran:true,completedTests:8};
  const proof={validated:true,officialGradingValid:true,protocol:"tb-live-nginx-io-v1",imageId:IMAGE_ID,dependencyProfile:"private-pinned",runtimeManifestSha256:"runtime",sourceHashes:{stand:"original"},phases:{empty:{...control,reward:0},oracle:{...control,reward:1}}};
  expect(()=>requireNginxPreflight(proof,{stand:"original"},"runtime")).not.toThrow();
  expect(()=>requireNginxPreflight({...proof,officialGradingValid:false},{stand:"original"},"runtime")).toThrow();
  expect(()=>requireNginxPreflight(proof,{stand:"changed"},"runtime")).toThrow();
  expect(()=>requireNginxPreflight({...proof,phases:{...proof.phases,empty:{...proof.phases.empty,completedTests:0}}},{stand:"original"},"runtime")).toThrow();
});
test("unknown existing locks and unfinished legacy campaigns are preserved", () => {
  const root=mkdtempSync(join(tmpdir(),"tgengin-fee-lock-"));
  try {
    mkdirSync(join(root,"docs/repair-2026-10-08/campaigns/old"),{recursive:true});
    writeFileSync(join(root,"docs/repair-2026-10-08/campaigns/old/summary.json"),JSON.stringify({completed:false}));
    expect(()=>acquirePaidCampaignLock({root,runId:"new",entry:"fixture"})).toThrow("Unfinished campaign");
    writeFileSync(join(root,"docs/repair-2026-10-08/campaigns/old/summary.json"),JSON.stringify({completed:false,fatal:"transport_failed"}));
    writeFileSync(join(root,"docs/repair-2026-10-08/campaigns/old/api-ledger.json"),JSON.stringify({reservedUpperBoundUsd:0.01,pending:{route:1}}));
    expect(()=>acquirePaidCampaignLock({root,runId:"new",entry:"fixture"})).toThrow("Unreconciled provider calls");
    rmSync(join(root,"docs"),{recursive:true,force:true});
    mkdirSync(join(root,".phase1-data"),{recursive:true});
    const file=join(root,".phase1-data/owned-paid-campaign.lock.json"), prior='{"pid":1234,"unknown":true}\n'; writeFileSync(file,prior);
    expect(()=>acquirePaidCampaignLock({root,runId:"new",entry:"fixture"})).toThrow("Existing or inaccessible paid lock");
    expect(readFileSync(file,"utf8")).toBe(prior);
  } finally {rmSync(root,{recursive:true,force:true});}
});
test("two actual local processes cannot own the paid lock concurrently", async () => {
  const root=mkdtempSync(join(tmpdir(),"tgengin-fee-race-"));
  const module=join(import.meta.dir,"../scripts/repair-2026-10-08/paid-campaign-lock.ts");
  const script="import {acquirePaidCampaignLock} from "+JSON.stringify(module)+"; const lock=acquirePaidCampaignLock({root:process.env.TGENGIN_LOCK_TEST_ROOT,runId:'owner',entry:'process-a'});console.log('ready');await new Promise(r=>process.stdin.once('data',r));lock.release();";
  const a=Bun.spawn([process.execPath,"-e",script],{env:{...process.env,TGENGIN_LOCK_TEST_ROOT:root},stdin:"pipe",stdout:"pipe",stderr:"pipe"});
  try {
    const reader=a.stdout.getReader(); const first=await reader.read(); expect(new TextDecoder().decode(first.value)).toContain("ready"); reader.releaseLock();
    const owner=JSON.parse(readFileSync(join(root,".phase1-data/owned-paid-campaign.lock.json"),"utf8")); expect(owner.pid).toBe(a.pid);
    const b=Bun.spawn([process.execPath,"-e","import {acquirePaidCampaignLock} from "+JSON.stringify(module)+";try{acquirePaidCampaignLock({root:process.env.TGENGIN_LOCK_TEST_ROOT,runId:'contender',entry:'process-b'});process.exitCode=1;}catch{console.log('blocked');}"],{env:{...process.env,TGENGIN_LOCK_TEST_ROOT:root},stdout:"pipe",stderr:"pipe"});
    expect(await new Response(b.stdout).text()).toContain("blocked");expect(await b.exited).toBe(0);
    a.stdin.write("release\n");a.stdin.end();expect(await a.exited).toBe(0);expect(existsSync(join(root,".phase1-data/owned-paid-campaign.lock.json"))).toBe(false);
  } finally {a.kill();await a.exited;rmSync(root,{recursive:true,force:true});}
},10000);
test("the actual TB host engine requires private authorization for SQL and task access", async () => {
  const directory=mkdtempSync(join(tmpdir(),"tgengin-tb-private-engine-"));
  let engine:Awaited<ReturnType<typeof tbEngine>>|undefined;
  try {
    engine=await tbEngine({maxTokens:8192,retryTimes:0,continueTimes:0,reasoningEffort:"none",temperature:0,seed:42},directory);
    expect((await fetch(engine.base+"/tasks")).status).toBe(401);
    expect((await fetch(engine.base+"/exec",{method:"POST",headers:{"content-type":"application/json"},body:JSON.stringify({sql:"select 1"})})).status).toBe(401);
    const result=await engine.api<{rows:{n:number}[]}>("POST","/query",{sql:"select 1 n"});expect(result.rows).toEqual([{n:1}]);
  } finally {if(engine)await engine.stop();rmSync(directory,{recursive:true,force:true});}
},10000);
