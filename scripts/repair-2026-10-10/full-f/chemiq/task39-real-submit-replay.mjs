/** Read-only captured-trace regression signal. No model, grader, Docker or owner actions. */
import fs from 'node:fs';import path from 'node:path';import assert from 'node:assert/strict';import {gunzipSync} from 'node:zlib';
import {Database} from 'bun:sqlite';import {actualPin,verifyPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
import {verifyApprovedSupplierStreamEvidence} from '../chembench/supplier-stream-continuation.ts';
const root=path.resolve(import.meta.dirname,'../../../..'),base=path.join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq'),read=p=>JSON.parse(fs.readFileSync(p,'utf8'));
const run=process.argv[2]??'repair-2026-10-11T05-06-00-577Z-12-2026-10-11T05-28-25-388Z',out=path.join(base,'runs',run),manifest=read(path.join(out,'manifest.json'));
const broker=path.dirname(read(path.join(base,'status.json')).brokerHealthPath),journal=read(path.join(out,'journal/api-state.json')),db=new Database(path.join(out,'task-39/engine/data/h2h.sqlite'),{readonly:true});
const task=db.query('select state,result,created_at,solve_seconds from task').get(),calls=db.query("select body,at from agent_bot_msg where kind='call'").all();db.close();
const submitCalls=calls.flatMap(row=>{try{return(JSON.parse(row.body).calls??[]).filter(c=>c.name==='submit').map(c=>({at:row.at,beforeDeadline:row.at<=task.created_at+900000,name:c.name}));}catch{return[]}});
const receipts=[];
for(let seq=0;seq<journal.finishedRequestCount;seq++){
 const dir=path.join(broker,'stream-evidence',run+'-'+seq),evidence=read(path.join(dir,'capture.evidence.json')),request=JSON.parse(gunzipSync(fs.readFileSync(path.join(dir,'capture.original-request.json.gz'))).toString());
 for(const key of ['originalRequest','wireRequest','rawSSE'])if(evidence[key])verifyPin(evidence[key]);
 if(!fs.existsSync(path.join(dir,'capture.aggregate.json'))){
  assert.equal(evidence.bodyComplete,false,'missing aggregate must have explicit incomplete-body evidence');
  receipts.push({seq,complete:false,fault:evidence.fault,cost:null,capturePin:actualPin(path.join(dir,'capture.evidence.json')),rawSSEPin:evidence.rawSSE});continue;
 }
 const aggregate=read(path.join(dir,'capture.aggregate.json')),verified=verifyApprovedSupplierStreamEvidence(dir);
 const message=aggregate.choices?.[0]?.message??{};
 receipts.push({seq,complete:true,validReplay:verified.valid,id:aggregate.id,provider:aggregate.provider,cost:aggregate.usage?.cost,usage:aggregate.usage,finishReason:aggregate.choices?.[0]?.finish_reason,response:{contentLength:(message.content??'').length,reasoningLength:(message.reasoning??'').length,reasoningDetails:message.reasoning_details?.length??0,toolCalls:message.tool_calls?.length??0},request:{maxTokens:request.max_tokens,reasoning:request.reasoning,toolChoice:request.tool_choice,toolNames:request.tools?.map(t=>t.function?.name),messages:request.messages.map(m=>({role:m.role,keys:Object.keys(m),contentLength:typeof m.content==='string'?m.content.length:0,reasoningLength:(m.reasoning??m.reasoning_content??'').length,reasoningDetails:m.reasoning_details?.length??0}))},aggregatePin:actualPin(path.join(dir,'capture.aggregate.json'))});
}
const report={atUtc:new Date().toISOString(),runId:run,supplier:manifest.settings.providerSlug,modelCalls:0,dockerActions:0,ownerAcquired:false,originalDeadlineSeconds:task.solve_seconds,task,submitCalls,receipts,passesActualSubmitCriterion:submitCalls.some(c=>c.beforeDeadline),failureSymptom:'Original900 deadline passed without actual submit; full responses and incomplete transport evidence remain separate',sourcePins:[actualPin(import.meta.filename),actualPin(path.join(root,'scripts/repair-2026-10-08/campaign-contract.ts')),actualPin(path.join(root,'scripts/repair-2026-10-10/full-f/chemiq/native-machine.ts'))]};
for(const p of report.sourcePins)verifyPin(p);
fs.writeFileSync(path.join(base,'task39-real-submit-replay-'+manifest.settings.providerSlug+'.json'),JSON.stringify(report,null,2));
console.log(JSON.stringify({runId:run,supplier:report.supplier,actualSubmitCalls:submitCalls.length,modelCalls:0,completeResponses:receipts.filter(r=>r.complete).length,incompleteResponses:receipts.filter(r=>!r.complete).length,allCompleteLength:receipts.filter(r=>r.complete).every(r=>r.finishReason==='length'),red:!report.passesActualSubmitCriterion}));
assert(report.passesActualSubmitCriterion,'real captured SDK run did not submit within original900 deadline');
