import {join} from 'node:path';
import {mkdirSync,readFileSync} from 'node:fs';
import {machine} from '../../../../test/_lib.ts';
import {BENCHMARK_INFERENCE} from '../../../benchmark-repair/benchmark-inference.ts';
import {BENCHMARK_PROVIDER} from '../../../benchmark-repair/benchmark-provider.ts';
import {loadChemiqFPlan} from '../../../benchmark-repair/chemiq-f-journal-contract-v3.ts';
import {OUT,save} from './prepare.ts';
const id='repair-'+Date.now(),plan=loadChemiqFPlan(id,'full816');
if(plan.tasks.some(t=>encodeURIComponent(`${id}/chemiq/F0/${t.officialId}`).length>100))throw Error('Task route exceeds 100');
const directory=join(OUT,'startup-validation-'+Date.now());mkdirSync(directory,{recursive:true});
const engine=await machine(BENCHMARK_INFERENCE,{directory,keep:true});
try{
  const apis:any=await engine.api('POST','/query',{sql:"select model,handle,modes from api where key_env='OPENROUTER_API_KEY' and model=:model",params:{model:BENCHMARK_PROVIDER.model}});
  if(apis.rows.length!==1)throw Error('Native OpenRouter API row missing');
  const taskId=plan.tasks[0].taskId;
  // Use a declaration without apiMode; no model request can be dispatched.
  await engine.api('POST','/declare',{places:[{place:'local'}],modes:[{mode:'preflight',cycles:[{cycle:'idle',from:[],next:[],maxUnits:1,infer:'fn:infer.dfs'}]}],agents:[{name:'bot',apis:[['OPENROUTER_API_KEY',BENCHMARK_PROVIDER.model]],unit:'fn:unit.tools'}]});
  await engine.api('POST','/exec',{sql:"update tool set usable=case when name in ('submit','verify','task_tree','node_load') then 1 else 0 end"});
  await engine.api('POST','/tasks',{id:taskId,run:id,mode:'preflight',agent:'bot',place:'local',source:'user',description:'No API preflight',solveSeconds:900,maxBranches:4,maxDeadSiblings:100000,noSearch:['all']});
  const state:any=await engine.api('POST','/query',{sql:'select state,result,created_at,solve_seconds from task where id=:id',params:{id:taskId}});
  if(state.rows.length!==1||state.rows[0].solve_seconds!==900)throw Error('Native task lookup failed');
  const status:any=await engine.api('GET',`/tasks/${encodeURIComponent(taskId)}/status`);if(status.created_at!==state.rows[0].created_at)throw Error('Short route lookup differs');
  save('startup-validation.json',{valid:true,taskNamespace:id,maxEncodedTaskIdLength:Math.max(...plan.tasks.map(t=>encodeURIComponent(t.taskId).length)),nativeApiRows:apis.rows,queryAndShortRoutePassed:true,solverRefusalProof:JSON.parse(readFileSync(join(OUT,'solver-validation/solver-cold-observation.json'),'utf8')).validated,modelCalls:0,observedAtUtc:new Date().toISOString()});
}finally{await engine.stop();}


