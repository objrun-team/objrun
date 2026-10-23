import {gunzipSync} from 'node:zlib';
// Isolated production SDK fixture. All model traffic terminates on localhost.
// A private reference is used only as a synthetic positive-control tool argument.
// This is never a model-generated answer, campaign score, or paid readiness proof.
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {randomUUID} from 'node:crypto';
import {Database} from 'bun:sqlite';import {machine as baselineMachine} from './native-machine.ts';import {machine as baselineBudgetMachine} from './budget-handoff-entry-machine.mjs';import {machine as candidateMachine} from './submit-length-feedback-control-machine.mjs';
import {loadChemiqFPlan,chemiqObjective,ChemiqRouteSeal} from '../../../repair-2026-10-08/chemiq-f-journal-contract-v3.ts';
import {ChemiqGradingRecorder} from '../../../repair-2026-10-08/chemiq-f-grading-recorder-v3.ts';
import {actualPin,hash,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
const mode=process.argv[2]??'green';assert(['red','green'].includes(mode));const machine=mode==='red'?baselineBudgetMachine:candidateMachine;
const root=path.resolve(import.meta.dirname,'../../../..'),base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq'),dir=path.join(base,'sdk-boundary-controls',Date.now().toString()+'-submit-feedback-'+mode);fs.mkdirSync(dir,{recursive:true});
const run='repair-'+Date.now()+'-12-0',plan=loadChemiqFPlan(run,'full816'),task=plan.tasks[39];task.taskId='local-cq39/'+task.officialId;
const privateRow=JSON.parse(fs.readFileSync(plan.datasetPin.path,'utf8').trim().split(/\r?\n/)[39]),answer=String(privateRow.answer);assert.equal(privateRow.verification_method,'canonical_smi_match');
const replayRun=JSON.parse(fs.readFileSync(path.join(base,'active-run.json'),'utf8'));const replayResponsePath=path.join(replayRun.output,'journal/provider-12-response.json.gz');const replayResponse=JSON.parse(gunzipSync(fs.readFileSync(replayResponsePath)).toString());assert.equal(replayResponse.choices[0].finish_reason,'length');assert(!replayResponse.choices[0].message.tool_calls?.length);
const token=randomUUID()+randomUUID(),recorder=new ChemiqGradingRecorder(plan,path.join(dir,'physical-grading'),'http://127.0.0.1:17918',token),grade=Bun.serve({hostname:'127.0.0.1',port:0,fetch:r=>recorder.handle(r)}),rows=[];
let ordinary=0,required=0,engine;
const model=Bun.serve({hostname:'127.0.0.1',port:0,async fetch(r){
 assert.equal(r.method,'POST');assert(new URL(r.url).pathname.endsWith('/v1/chat/completions'));
 const body=await r.json();assert.equal(body.model,'deepseek/deepseek-v4.1-flash');assert.equal(body.max_tokens,16384);assert.equal(body.reasoning.effort,'high');
 const submit=body.tools.find(t=>t.function.name==='submit');assert(submit,'actual registered submit schema required');
 const only=body.tools.length===1,seq=only?required++:ordinary++,length=only?seq<3:true;
 const prefix=only?'required-reasoning-':'ordinary-reasoning-',thought=prefix+seq+';';
 const carried=body.messages.filter(m=>m.role==='assistant').map(m=>m.reasoning_content??m.reasoning??'').join('');
 if(seq>0)assert(carried.includes(only?(replayResponse.choices[0].message.reasoning??replayResponse.choices[0].message.reasoning_content):prefix+(seq-1)+';'),'previous reasoning must reach next actual SDK request');
 if(!only&&seq===3){await engine.api('POST','/exec',{sql:'update task set created_at=:created where id=:id',params:{created:Date.now()-680000,id:task.taskId}});}
 rows.push({ordinal:rows.length,onlySubmit:only,length,localResponseThoughtSha:hash(thought),carriedReasoningSha:hash(carried),request:body});
 if(only){const reminder=body.messages.some(m=>m.role==='user'&&typeof m.content==='string'&&m.content.includes('The previous response was rejected: no actual required tool call was delivered.'));rows[rows.length-1].submissionReminder=reminder;if(!reminder){if(seq===3)await engine.api('POST','/exec',{sql:'update task set created_at=:created where id=:id',params:{created:Date.now()-900001,id:task.taskId}});return Response.json(replayResponse);}assert.equal(mode,'green');assert.equal(body.messages.filter(m=>m.role==='user'&&typeof m.content==='string'&&m.content.includes('The previous response was rejected: no actual required tool call was delivered.')).length,1);assert.equal(seq,1);return Response.json({...replayResponse,id:'gen-local-feedback-tool-control',choices:[{index:0,finish_reason:'tool_calls',message:{role:'assistant',content:'',tool_calls:[{id:'local-control-submit',type:'function',function:{name:'submit',arguments:JSON.stringify({answer})}}]}}]});}
 const message=length?{role:'assistant',content:'',reasoning:thought}:{role:'assistant',content:'',tool_calls:[{id:'fixture-'+rows.length,type:'function',function:{name:'submit',arguments:JSON.stringify({answer})}}]};
 return Response.json({id:'gen-local-boundary-'+rows.length,model:body.model,provider:'DigitalOcean',created:1,object:'chat.completion',choices:[{index:0,message,finish_reason:length?'length':'tool_calls'}],usage:{prompt_tokens:1,completion_tokens:1,total_tokens:2,completion_tokens_details:{reasoning_tokens:length?1:0}}});
}});
const proof={replayResponsePin:actualPin(replayResponsePath),replaySubmissionLengthOnly:true,syntheticToolResponseOnReminder:mode==='green',upstreamEfficacyProven:false,syntheticDeadlineExpireAfterFourthLength:mode==='red',protocol:'chemiq39-production-sdk-boundary-control-v1',syntheticLocalOnly:true,campaignScore:false,modelCalls:0,externalModelCalls:0,ownerAcquired:false,dockerActions:0,parameters:{solveSeconds:900,maxTokens:16384,effort:'high',checks:5,maxBranches:4,maxDeadSiblings:100000,maxUnits:12},passed:false};
try{
 let wall=1000000;const gate=new ChemiqRouteSeal(()=>wall);gate.open('local-deadline',wall);gate.bindCreation('local-deadline',wall);wall+=900000;gate.check('local-deadline');wall++;assert.throws(()=>gate.check('local-deadline'));proof.deadlineControl={solveSeconds:900,atDeadlineAllowed:true,afterDeadlineNewDispatchRejected:true,clockInjectedLocalOnly:true};
 process.env.TGENGIN_GRADER_TOKEN=token;process.env.TGENGIN_GRADER_ORIGINS='http://127.0.0.1:'+grade.port;const directory=path.join(dir,'engine');fs.mkdirSync(directory);engine=await machine({}, {directory,keep:true});
 const objective=chemiqObjective('http://127.0.0.1:'+grade.port);
 await engine.api('POST','/declare',{handles:objective.nodes.map(n=>({name:n.handle,expectMs:120000})),places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY','deepseek/deepseek-v4.1-flash']],unit:'fn:unit.tools'}]});
 await engine.api('POST','/exec',{sql:"update tool set usable=case when name in ('submit','verify','task_tree','node_load') then 1 else 0 end"});
 await engine.api('POST','/exec',{sql:"delete from api where key_env!='OPENROUTER_API_KEY' or model!='deepseek/deepseek-v4.1-flash'"});
 await engine.api('POST','/exec',{sql:"update api set base_url=:base,retry_on='[]'",params:{base:'http://127.0.0.1:'+model.port+'/v1'}});
 await engine.api('POST','/tasks',{id:task.taskId,run,mode:'repair',agent:'bot',place:'local',source:'user',description:task.prompt,objective,readable:false,solveSeconds:900,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
 let state;const localControlDeadline=Date.now()+60000;
    do{state=await engine.api('GET','/tasks/'+encodeURIComponent(task.taskId));if(['done','failed'].includes(state.state)&&state.result&&!['finalization_pending','finalization_error'].includes(JSON.parse(state.result).outcome))break;await Bun.sleep(100);}while(Date.now()<localControlDeadline);
 proof.state=state;proof.mode=mode;proof.syntheticClockInjection={taskCreatedAtShiftMs:680000,localOnly:true};
 if(mode==='green'){assert.equal(state.state,'done');assert.equal(JSON.parse(state.result).valid,true);assert.equal(JSON.parse(state.result).pass,1);assert.equal(ordinary,8);assert.equal(required,2);}else{assert.equal(state.state,'failed');assert.equal(JSON.parse(state.result).outcome,'no_candidate');assert.equal(ordinary,8);assert.equal(required,4);}
 const db=new Database(path.join(directory,'data/h2h.sqlite'),{readonly:true}),calls=db.query("select at,body from agent_bot_msg where kind='call'").all(),t=db.query('select created_at,solve_seconds from task').get();db.close();
 proof.submitCalls=calls.filter(r=>JSON.parse(r.body).calls?.some(c=>c.name==='submit')).map(r=>({at:r.at,beforeDeadline:r.at<t.created_at+900000}));if(mode==='green')assert(proof.submitCalls.length>0&&proof.submitCalls.every(c=>c.beforeDeadline));else assert.equal(proof.submitCalls.length,0);
 await recorder.drain();proof.gradingClosePin=recorder.closeArtifact(path.join(dir,'grading-close.json'));proof.requests=rows;proof.actualRegisteredSubmitSchema=rows[0].request.tools.find(t=>t.function.name==='submit').function.parameters;proof.passed=true;
}catch(e){proof.error=String(e);process.exitCode=1;}finally{
 if(engine)await engine.stop();await recorder.drain();await model.stop(true);await grade.stop(true);
 if(engine){const tracePath=path.join(dir,'engine','budget-handoff-boundaries.jsonl');if(fs.existsSync(tracePath)){proof.boundaryTracePin=actualPin(tracePath);proof.boundaries=fs.readFileSync(tracePath,'utf8').trim().split(/\r?\n/).filter(Boolean).map(JSON.parse);if(mode==='green')assert(proof.boundaries.some(b=>b.applied&&b.remainingSeconds>0&&b.remainingSeconds<=225));}}
 proof.sourcePins=[actualPin(import.meta.filename),actualPin(path.join(root,'app/src/llm/index.ts')),actualPin(path.join(root,'app/src/tree/dfs.ts'))];for(const p of proof.sourcePins)verifyPin(p);
 fs.writeFileSync(path.join(dir,'control.json'),JSON.stringify(proof,null,2));fs.writeFileSync(path.join(base,'task39-submit-feedback-sdk-'+mode+'.json'),JSON.stringify({path:path.join(dir,'control.json'),passed:proof.passed,error:proof.error??null,modelCalls:0,campaignScore:false},null,2));
}
console.log(JSON.stringify({passed:proof.passed,error:proof.error??null,ordinary,required,modelCalls:0,dir}));
