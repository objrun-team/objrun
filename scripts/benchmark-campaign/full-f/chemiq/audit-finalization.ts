/** Read-only audit of completed task evidence; never dispatches or mutates running code/database. */
import {readFileSync,writeFileSync,readdirSync,mkdirSync} from 'node:fs';
import {join} from 'node:path';
import {gunzipSync} from 'node:zlib';
import {Database} from 'bun:sqlite';
import {OUT} from './prepare.ts';
const active=JSON.parse(readFileSync(join(OUT,'active-run.json'),'utf8'));
const rows:any[]=[];
for(const entry of readdirSync(active.output,{withFileTypes:true}).filter(e=>e.isDirectory()&&/^task-\d+$/.test(e.name))){
  let r:any;try{r=JSON.parse(readFileSync(join(active.output,entry.name,'result.json'),'utf8'));}catch{continue;}
  if(r.generationValid&&r.acceptance?.outcome!=='budget_exhausted')continue;
  const db=new Database(join(active.output,entry.name,'engine/data/h2h.sqlite'),{readonly:true});
  try{
    const tables:any[]=db.query("select name from sqlite_master where name like 'task%'").all();
    const repair=tables.some(t=>t.name==='task_repair')?db.query('select * from task_repair').all():[];
    const calls=(r.calls??[]).map((c:any)=>{
      const q=JSON.parse(gunzipSync(readFileSync(c.requestFile)).toString()),p=JSON.parse(gunzipSync(readFileSync(c.responseFile)).toString());
      return {seq:c.requestSeq,status:c.httpStatus,started:c.startedAt,ended:c.finishedAt,toolChoice:c.wireParameters.tool_choice,
        toolNames:q.tools?.map((x:any)=>x.function.name),finishReasons:p.choices?.map((x:any)=>x.finish_reason),returnedTools:p.choices?.flatMap((x:any)=>x.message.tool_calls?.map((t:any)=>t.function.name)??[]),fault:c.fault??null,costBasis:c.costBasis,cost:c.billedCostUsd??null,generationId:c.requestId??null,provider:c.providerName??null,model:c.servedModel??null};
    });
    const trace=readFileSync(r.tracePin.path,'utf8').trim().split('\n').map(v=>JSON.parse(v));
    const markers=trace.filter(v=>/RequiredToolCallMissing|finaliz|stuck|error|expired/.test(v.body??'')).map(v=>({at:v.at,role:v.role,kind:v.kind,body:v.body.slice(0,2000)}));
    rows.push({index:r.index,officialId:r.officialId,state:r.state,runtime:r.runtimeVerdict,generation:r.generationClassification,acceptance:r.acceptance,seconds:r.seconds,
      deadline:r.declaredDeadlineAt,knownCostUsd:(r.calls??[]).reduce((n:number,c:any)=>n+(c.billedCostUsd??0),0),calls,repair,markers,
      classification:r.generationValid?'valid_experimental_budget_exhausted':'unresolved_finalization_not_valid_score'});
  }finally{db.close();}
}
const result={protocol:'chemiq-finalization-readonly-audit-v1',observedAtUtc:new Date().toISOString(),runId:active.runId,denominator:816,modelCallsByAudit:0,rows};
mkdirSync(join(OUT,'diagnostics'),{recursive:true});writeFileSync(join(OUT,'diagnostics/finalization-audit.json'),JSON.stringify(result,null,2)+'\n');
console.log(JSON.stringify(result));
