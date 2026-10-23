/** New pilot16's private cold controls. Preparation never runs a model or modifies old evidence. */
import { randomUUID } from 'node:crypto';
import { closeSync, existsSync, fsyncSync, mkdirSync, openSync, readFileSync, readdirSync, statfsSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { execFileSync } from 'node:child_process';
import { freemem } from 'node:os';
import { gzipSync } from 'node:zlib';
import { machine, type Machine } from '../../test/_lib.ts';
import { graderFetch } from '../../app/src/engine/registry.ts';
import { actualPin, demand, hash, jsonPin, same, verifyPin, type Pin } from './paid-resource-proof-v2.ts';
import { CHEMIQ_F_ROOT as ROOT, CHEMIQ_F_FAMILY, CHEMIQ_F_BOOK_SHA, CHEMIQ_F_STAND_SHA, CHEMIQ_F_PROVENANCE_SHA, loadChemiqFPlan, validateChemiqRuntimeGateContents } from './chemiq-f-journal-contract-v2.ts';
import { durableChemiqJson } from './chemiq-f-paid-admission-v2.ts';
import { observeChemiqOwned } from './chemiq-f-owned-v2.ts';
import { CHEMIQ_PRIVATE_CID, CHEMIQ_SOLVER_TOOLS, assertChemiqPrivateBridgeObservation, assertChemiqSolverColdObservation } from './chemiq-private-boundary-v2.ts';
import { loadChemiqProvenance } from './chemiq-nextwave-contract.ts';
import { captureProviderResponse, CapturedTransportFailure } from './scientific-journal-proxy.ts';
const DOC = join(ROOT, 'docs/repair-2026-10-08'), HOME = join(DOC, 'chemiq-f-journal-implementation-v2');
const PYTHON = 'D:/ProgramData/anaconda3/python.exe', PRIVATE = 'http://127.0.0.1:17918';
const utc = () => new Date().toISOString();
function nativeObservation(mode: string) {
  const stdout = execFileSync(PYTHON, ['-B', '-X', 'utf8', join(import.meta.dir, 'chemiq-resource-readonly-v2.py'), mode], {cwd: ROOT, windowsHide: true, encoding: 'utf8', timeout: 45000});
  const result = JSON.parse(stdout.trim()); verifyPin(result); return result as Pin;
}
export function prepareCold96(runId: string) {
  const plan = loadChemiqFPlan(runId, 'pilot16'), output = join(HOME, 'cold-materials', runId);
  demand(!existsSync(output), 'chemiq_cold_materials_never_overwrite'); mkdirSync(output, {recursive:true});
  const names = ['legacy-chemiq-616-controls-private-references-raw-length.json', 'legacy-chemiq-200-controls-private-references-raw-length.json'];
  const sourcePins = names.map(n => actualPin(join(DOC, n))), refs = sourcePins.map(jsonPin);
  const byId = new Map(refs.flatMap(r => r.records).map((r:any) => [r.task,r]));
  demand(refs.every(r => r.source_data_sha256 === CHEMIQ_F_BOOK_SHA) && byId.size === 816, 'chemiq_cold_private_source');
  const tasks = plan.tasks.map(task => {
    const r:any = byId.get(task.officialId); demand(r, 'chemiq_cold_reference_missing');
    const inputs = task.method === 'opsin' ? [r.reference_name, r.wrong_structure_name, 'Z'.repeat(301)] : [r.positive_input,r.negative_input,r.format_input];
    demand(inputs.every(v => typeof v === 'string' && v.length > 0) && (task.method === 'opsin' ? r.reference_found : r.positive_profile_precheck), 'chemiq_cold_positive_gap');
    const kinds = ['positive','wrongValue','wrongFormat'];
    const cases = Object.fromEntries(kinds.map((kind,i) => [kind,{input:inputs[i],inputSha256:hash(inputs[i]),expected:{parsed:kind !== 'wrongFormat',correct:kind === 'positive'},actual:null}]));
    return {index:task.index,officialIndex:task.officialIndex,officialId:task.officialId,promptSha256:task.promptSha256,method:task.method,cases};
  });
  const pin = durableChemiqJson(join(output,'private-materials.json'), {protocol:'chemiq-f-private-cold-materials-v2',family:CHEMIQ_F_FAMILY,runId,
    taskScheduleSha256:plan.taskScheduleSha256,scope:'pilot16',tasks,requests:96,sourcePins,executed:false,modelCalls:0,solverExposure:false,publicArchive:false});
  return {materialPin:pin,runId,requestedControls:96,taskCount:16,executed:false,modelCalls:0};
}
function gzipCapture(path:string, raw:Uint8Array) {
  const bytes = gzipSync(raw), fd = openSync(path,'wx',0o600);
  try { writeFileSync(fd,bytes); fsyncSync(fd); } finally { closeSync(fd); }
  demand(readFileSync(path).equals(bytes), 'chemiq_cold_gzip_readback'); return actualPin(path);
}
export async function solverCold(output:string,runId:string) {
  const directory = join(output,'solver-engine'); mkdirSync(directory,{recursive:true});
  const localKey = randomUUID(), keyName = 'OBJRUN_CHEMIQ_COLD_V2_KEY'; process.env[keyName] = localKey;
  const forbidden = ['read','write','edit','glob','grep','bash','python_exec'];
  const inputs:any = {read:{path:join(ROOT,'.phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl')},write:{path:join(directory,'must-not-exist.txt'),content:'not allowed'},
    edit:{path:join(directory,'must-not-exist.txt'),old:'a',new:'b'},glob:{pattern:'**/*',path:ROOT},grep:{pattern:'answer',path:ROOT},
    bash:{command:'echo forbidden'},python_exec:{code:'print("forbidden")'}};
  let localRequests = 0; const requestPins:Pin[] = [], toolsAdvertised:string[][] = []; let engine:Machine | undefined, registration:Pin | undefined;
  const local = Bun.serve({hostname:'127.0.0.1',port:0,async fetch(request) {
    demand(request.method === 'POST' && new URL(request.url).pathname === '/v1/chat/completions', 'chemiq_cold_local_route');
    demand(request.headers.get('authorization') === 'Bearer '+localKey, 'chemiq_cold_local_key');
    const raw = await request.text(), parsed = JSON.parse(raw), ordinal = localRequests++;
    requestPins.push(gzipCapture(join(output,`local-engine-request-${ordinal}.json.gz`),Buffer.from(raw)));
    toolsAdvertised.push((parsed.tools??[]).map((r:any)=>r.function?.name).filter(Boolean).sort());
    const calls = ordinal === 0 ? forbidden.map(name => ({id:'forbidden-'+name,type:'function',function:{name,arguments:JSON.stringify(inputs[name])}}))
      : [{id:'cold-submit-'+ordinal,type:'function',function:{name:'submit',arguments:JSON.stringify({answer:'cold capability test only'})}}];
    return Response.json({id:'local-cold-'+ordinal,model:'cold-fixture-no-remote-model',choices:[{message:{role:'assistant',content:null,tool_calls:calls},finish_reason:'tool_calls'}],usage:{prompt_tokens:1,completion_tokens:1}});
  }});
  const localPort=local.port;
  let toolRows:any[] = [], rejectedCalls:any[] = [], stopReturned = false, coldFault:unknown, close:Pin|undefined;
  try {
    engine = await machine({maxTokens:8192,retryTimes:0,continueTimes:0,reasoningEffort:'none',temperature:0,seed:42},{directory,keep:true});
    registration = durableChemiqJson(join(output,'cold-engine-registration.json'),{protocol:'paid-owned-process-v2',family:CHEMIQ_F_FAMILY,runId,ownerNonce:randomUUID(),taskIndex:0,pid:engine.pid,base:engine.base,startedAtUtc:utc(),role:'cold-only-native-engine-no-paid-lock'});
    await engine.api('POST','/exec',{sql:"insert or replace into api (key_env,model,handle,modes,base_url,retry_on) select :key,'deepseek-flash',handle,modes,:base,'[]' from api where key_env='DEEPSEEK_API_KEY' and model='deepseek-v4-flash'",params:{key:keyName,base:'http://127.0.0.1:'+local.port+'/v1'}});
    await engine.api('POST','/exec',{sql:'delete from api where key_env != :key',params:{key:keyName}});
    await engine.api('POST','/declare',{places:[{place:'local'}],modes:[{mode:'cold_capability',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[[keyName,'deepseek-flash']],unit:'fn:unit.tools'}]});
    await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
    toolRows = (await engine.api<any>('POST','/query',{sql:'select name,identity,usable from tool order by name'})).rows;
    await engine.api('POST','/tasks',{id:runId+'/cold/capability',run:runId,mode:'cold_capability',agent:'bot',place:'local',source:'user',description:'Local engine capability test only; no private reference input',solveSeconds:900,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
    const deadline = Date.now()+30000;
    while (Date.now()<deadline) {
      const rows = (await engine.api<any>('POST','/query',{sql:"select body from agent_bot_msg where kind='tool' order by unit,seq"})).rows;
      rejectedCalls = rows.flatMap((r:any)=>{try{return [JSON.parse(r.body)]}catch{return []}}).filter((r:any)=>forbidden.includes(r.name));
      if (forbidden.every(name=>rejectedCalls.some(r=>r.name===name))) break;
      await Bun.sleep(100);
    }
    demand(forbidden.every(name=>rejectedCalls.some(r=>r.name===name && r.value?.error === `${name} is registered but usable = 0, so it was not run`)), 'chemiq_cold_tools_not_actually_refused');
    demand(!existsSync(join(directory,'must-not-exist.txt')) && toolsAdvertised.every(names=>names.every(n=>CHEMIQ_SOLVER_TOOLS.includes(n))), 'chemiq_cold_tools_exposed_or_written');
    await engine.stop(); stopReturned=true;
  } catch(e) { coldFault=e; }
  finally {
    let cleanupFault:unknown;
    try {if(engine&&!stopReturned){await engine.stop();stopReturned=true;}} catch(e){cleanupFault=e;}
    try {await local.stop(true);} catch(e){cleanupFault??=e;}
    delete process.env[keyName];
    if(engine&&registration) try {close=await observeChemiqOwned(output,[registration],[localPort],'cold');} catch(e){cleanupFault??=e;}
    if(coldFault||cleanupFault) {
      durableChemiqJson(join(output,'cold-engine-failure.json'),{protocol:'chemiq-cold-engine-failure-v2',family:CHEMIQ_F_FAMILY,runId,modelCalls:0,
        observedAtUtc:utc(),error:coldFault instanceof Error?coldFault.name+':'+coldFault.message:'cold_failure',
        cleanupError:cleanupFault instanceof Error?cleanupFault.name+':'+cleanupFault.message:null,registrationPin:registration??null,
        closedObservationPin:close??null,stopReturned,closureCertified:!!close,nativeEngineHandleReturned:!!engine,localProviderPort:localPort});
      throw coldFault??cleanupFault;
    }
  }
  demand(engine && registration && stopReturned,'chemiq_cold_engine_missing');
  demand(close,'chemiq_cold_actual_close_missing');
  const frame = {protocol:'chemiq-solver-cold-observation-v2',family:CHEMIQ_F_FAMILY,runId,validated:true,modelCalls:0,remoteProviderRequests:0,
    localDeterministicReplies:localRequests,fixtureOnly:false,nativeEngineStarted:true,allowedTools:CHEMIQ_SOLVER_TOOLS,toolRows,rejectedCalls,toolsAdvertised,
    enginePid:engine.pid,enginePort:Number(new URL(engine.base).port),stopReturned,closed:true,closedObservationPin:close,registrationPin:registration,localProviderPort:localPort,
    taskDatabasePin:actualPin(join(directory,'data/h2h.sqlite')),toolUnitSourcePin:actualPin(join(ROOT,'app/src/tools/unit.ts')),localRequestPins:requestPins,
    privateControlsExposedToEngine:false,limits:['Local deterministic reply exercises actual tool execution refusal; it is not a real-model benchmark trial.','Native solver has no usable filesystem, Python, shell, search or network tool.']};
  assertChemiqSolverColdObservation(frame); return durableChemiqJson(join(output,'solver-cold-observation.json'),frame);
}
export async function runCold96(materialPin:Pin) {
  const materials = jsonPin(materialPin), plan = loadChemiqFPlan(materials.runId,'pilot16');
  demand(materials.executed===false&&materials.requests===96&&materials.taskScheduleSha256===plan.taskScheduleSha256,'chemiq_cold_material_identity');
  const output = join(HOME,'cold-executions',materials.runId+'-'+randomUUID()); mkdirSync(output,{recursive:true});
  const sourcePin = actualPin(import.meta.path), resourcePin = nativeObservation('resources'), resources=jsonPin(resourcePin);
  if (!resources.summary.cDiskFloorPassed || resources.disks.F.free < 1024**3 || freemem()<1024**3) {
    const failure = durableChemiqJson(join(output,'cold-start-rejected.json'),{protocol:'chemiq-cold-start-rejected-v2',observedAtUtc:utc(),resourcePin,materialPin,sourcePin,modelCalls:0,actualHttpRequests:0,nativeEngineStarted:false,reason:'existing_1GiB_disk_or_memory_floor'});
    return {started:false,failurePin:failure,modelCalls:0};
  }
  try {
    const inspectPin=nativeObservation('inspect'); assertChemiqPrivateBridgeObservation(jsonPin(inspectPin),ROOT);
    const bridgeObservationPin=nativeObservation('bridge'); demand(jsonPin(bridgeObservationPin).validated,'chemiq_cold_bridge_observation');
    process.env.PATH = 'D:/Program/resources/bin;'+process.env.PATH;
    const provenance=loadChemiqProvenance(ROOT,output), audit=provenance.audit('cold');
    const runtimeAuditPin=actualPin(join(output,'grader-provenance/chemiq/cold-runtime-audit.json'));
    demand(audit.valid&&audit.containerId===CHEMIQ_PRIVATE_CID,'chemiq_cold_runtime_audit');
    const healthResponse=await graderFetch(PRIVATE+'/health',{signal:AbortSignal.timeout(30000)}); demand(healthResponse.ok,'chemiq_cold_health'); const profile=await healthResponse.json();
    const healthPin=durableChemiqJson(join(output,'health.json'),{profile,observedAtUtc:utc(),httpStatus:healthResponse.status,modelCalls:0});
    const solverColdObservationPin=await solverCold(output,plan.runId), controls:any[]=[]; let index=0;
    for (const t of materials.tasks) {
      const cases:any={};
      for (const kind of ['positive','wrongValue','wrongFormat']) {
        const material=t.cases[kind], receipts:any={};
        for (const node of ['parsed','correct']) {
          const startedAtUtc=utc(), raw=JSON.stringify({node,input:{task:{id:`${plan.runId}/cold/${t.officialId}`},result:{body:material.input}}});
          const requestPin=gzipCapture(join(output,`control-${index}-request.json.gz`),Buffer.from(raw));
          let status:number|null=null, responseBytes=Buffer.alloc(0),fault:string|null=null,bodyComplete=true;
          try {const response=await graderFetch(PRIVATE+'/'+node,{method:'POST',headers:{'content-type':'application/json'},body:raw,signal:AbortSignal.timeout(120000)});status=response.status;const captured=await captureProviderResponse(response,4*1024**2);responseBytes=Buffer.from(captured.rawResponse);}
          catch(e){fault=e instanceof Error?e.name:'TransportFailure';bodyComplete=false;if(e instanceof CapturedTransportFailure){status=e.capture.httpStatus;responseBytes=Buffer.from(e.capture.rawBytes);}}
          const responsePin=gzipCapture(join(output,`control-${index}-response.json.gz`),responseBytes); let value:any=null;
          try{value=JSON.parse(new TextDecoder('utf-8',{fatal:true}).decode(responseBytes)).value}catch{fault??='InvalidJson'}
          const valid=!fault&&status===200&&typeof value==='boolean',receiptPin=durableChemiqJson(join(output,`control-${index}-receipt.json`),
            {protocol:'chemiq-f-runtime-control-receipt-v2',family:CHEMIQ_F_FAMILY,runId:plan.runId,index:index++,officialId:t.officialId,kind,node,
              startedAtUtc,finishedAtUtc:utc(),requestPin,requestRawSha256:hash(raw),responsePin,responseRawSha256:hash(responseBytes),httpStatus:status,
              bodyComplete,valid,value:valid?value:null,fault,containerId:CHEMIQ_PRIVATE_CID,standSourceSha256:CHEMIQ_F_STAND_SHA,datasetSha256:CHEMIQ_F_BOOK_SHA,modelCalls:0,fixtureOnly:false,credentialHeadersArchived:false});
          receipts[node]={receiptPin,valid,value};
        }
        cases[kind]={valid:receipts.correct.valid&&receipts.parsed.valid,value:receipts.correct.value,receiptPin:receipts.correct.receiptPin,parsedReceiptPin:receipts.parsed.receiptPin};
      }
      controls.push({officialId:t.officialId,...cases}); console.log(JSON.stringify({stage:'cold96',tasksCompleted:controls.length,actualHttpRequests:index,modelCalls:0}));
    }
    provenance.validate(); verifyPin(sourcePin);
    const gate={protocol:'chemiq-f-runtime-control-gate-v2',family:CHEMIQ_F_FAMILY,runId:plan.runId,scope:'pilot16',observedAtUtc:utc(),validated:true,modelCalls:0,
      officialQuestionCount:816,standSourcePin:actualPin(join(ROOT,'examples/benchmark/chemiq/stand.py')),provenancePin:actualPin(join(DOC,'chemiq-nextwave-grader-provenance.json')),
      datasetPin:plan.datasetPin,profile,healthPin,resourcePin,materialPin,sourcePin,requestedControls:96,actualHttpRequests:index,solverColdObservationPin,missingPositiveReferenceCount:0,controls,
      privateGrader:{networkMode:'bridge',boundaryProfile:'exact-original-loopback-bridge-v2',cleanInterpreter:true,solverToolsDisabled:true,containerId:CHEMIQ_PRIVATE_CID,inspectPin,runtimeAuditPin,bridgeObservationPin}};
    validateChemiqRuntimeGateContents(gate,plan);
    const gatePin=durableChemiqJson(join(output,'runtime-gate.json'),gate);
    return {started:true,validated:true,gatePin,actualHttpRequests:index,modelCalls:0,pilotTasksExecuted:0,output};
  } catch (e) {
    const failurePin=durableChemiqJson(join(output,'cold-failure.json'),{protocol:'chemiq-cold-failure-v2',observedAtUtc:utc(),materialPin,sourcePin,resourcePin,modelCalls:0,
      error:e instanceof Error?e.name+':'+e.message:'failure',validated:false});
    return {started:true,validated:false,failurePin,modelCalls:0,output};
  }
}
if(import.meta.main) {
  const [mode='prepare',value='repair-'+utc().replace(/[:.]/g,'-')]=process.argv.slice(2);
  if(mode==='prepare')console.log(JSON.stringify(prepareCold96(value)));
  else if(mode==='run')console.log(JSON.stringify(await runCold96(actualPin(resolve(value)))));
  else throw Error('Use prepare [fresh runId], or run <private-materials.json>');
}
