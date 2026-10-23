import { mkdirSync } from 'node:fs';
import { join } from 'node:path';
import { machine } from '../../../../test/_lib.ts';
import { BENCHMARK_INFERENCE } from '../../../repair-2026-10-08/benchmark-inference.ts';
import { BENCHMARK_PROVIDER } from '../../../repair-2026-10-08/benchmark-provider.ts';
import { submissionFault } from './runtime-health.ts';
import { OUT,save } from './prepare.ts';
let calls=0;
const mock=Bun.serve({hostname:'127.0.0.1',port:0,fetch(req){if(['/parsed','/correct'].includes(new URL(req.url).pathname))return Response.json({value:true});const final=++calls>1;return Response.json({id:'local-fixture-'+calls,model:BENCHMARK_PROVIDER.model,provider:'Relace',choices:[{index:0,message:final?{role:'assistant',content:'[ANSWER]A[/ANSWER]'}:{role:'assistant',content:null,tool_calls:[{id:'local-submit',type:'function',function:{name:'submit',arguments:JSON.stringify({answer:'[ANSWER]A[/ANSWER]'})}}]},finish_reason:final?'stop':'tool_calls'}],usage:{prompt_tokens:10,completion_tokens:5,total_tokens:15,cost:0}});}});
const dir=join(OUT,'local-fixture',Date.now().toString());mkdirSync(dir,{recursive:true});const engine=await machine(BENCHMARK_INFERENCE,{directory:dir,keep:true});
try{
  await engine.api('POST','/declare',{places:[{place:'local'}],modes:[{mode:'repair',cycles:[{cycle:'ask',apiMode:'chat',maxUnits:12,from:[],next:['act'],infer:'fn:infer.dfs'},{cycle:'act',maxUnits:12,from:['ask'],next:['ask'],infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',BENCHMARK_PROVIDER.model]],unit:'fn:unit.tools'}]});
  await engine.api('POST','/exec',{sql:"update api set base_url=:endpoint,retry_on='[]' where key_env='OPENROUTER_API_KEY' and model=:model",params:{endpoint:`http://127.0.0.1:${mock.port}/v1`,model:BENCHMARK_PROVIDER.model}});
  await engine.api('POST','/exec',{sql:"update tool set usable=0 where name not in ('submit','verify','task_tree','node_load')"});
  const taskId='local-protocol-fixture';await engine.api('POST','/tasks',{id:taskId,mode:'repair',agent:'bot',place:'local',source:'user',description:'Submit A',objective:{nodes:[{name:'parsed',domain:'bool',moment:'done',handle:`http://127.0.0.1:${mock.port}/parsed`},{name:'correct',domain:'bool',moment:'done',handle:`http://127.0.0.1:${mock.port}/correct`}],edges:[{src:'parsed',out:0,dst:'correct'}],sink:'correct',checks:5},readable:false,solveSeconds:600,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
  const start=Date.now();let detected:any;while(Date.now()-start<20000){detected=await submissionFault(engine,taskId);if(detected)break;await Bun.sleep(250);}if(!detected)throw Error('Production missing-submit fault was not detected');
  save('protocol-fixture.json',{passed:true,actualProductionEngine:true,coldEngine:true,durableFault:detected,detectedMs:Date.now()-start,mockCalls:calls,externalModelCalls:0,costUsd:0});console.log(JSON.stringify({passed:true,externalModelCalls:0,mockCalls:calls}));
}finally{await engine.stop();await mock.stop(true);}
