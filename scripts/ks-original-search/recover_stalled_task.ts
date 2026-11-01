// Preserve failed trajectory; let the same controller publish a fresh task under
// the original campaign deadline, keeping owned CPU jobs and checker untouched.
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join,dirname} from 'node:path';
import {parse} from '../../app/node_modules/yaml/dist/index.js';
const root=resolve(import.meta.dir,'../..'),run=readFileSync(join(root,'data/ks-original-search/latest-run.txt'),'utf8').trim();
const ep=JSON.parse(readFileSync(join(run,'endpoints.json'),'utf8'));
const cfg=parse(readFileSync(join(dirname(dirname(ep.database)),'config.yaml'),'utf8'));
const end=JSON.parse(readFileSync(join(run,'deadline.json'),'utf8'));
if(Date.now()>=end.deadline_epoch*1000)throw new Error('Original deadline closed');
const calls=readFileSync(join(run,'calls.jsonl'),'utf8').trim().split('\n').map(JSON.parse);
if(calls.some(d=>d.event==='dispatch'&&!calls.some(r=>r.id===d.id&&['response','fault'].includes(r.event))))throw new Error('In-flight model request; recovery refused');
const state=JSON.parse(readFileSync(join(run,'status.json'),'utf8'));const oldTask=state.task.id;
async function api(path:string,body:any){const r=await fetch(ep.engine+path,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+cfg.api.token},body:JSON.stringify(body)});const v=await r.json();if(!r.ok)throw new Error(JSON.stringify(v));return v;}
const snapshot=await api('/query',{sql:'select unit,seq,kind,body from agent_kssearch_msg where instance=:instance order by unit desc,seq desc limit 12',params:{instance:oldTask+'#1'}});
const failure=JSON.stringify(snapshot).includes('context_length_exceeded')?'provider_context_length_exceeded':JSON.stringify(snapshot).includes('Tool result is missing')?'missing_tool_result':null;
if(!failure)throw new Error('No explicit recoverable transport/context stall found');
const healthyJobs=state.active_jobs??[];
const stamp=Date.now();writeFileSync(join(run,`recovery-${stamp}-before.json`),JSON.stringify({oldTask,snapshot,deadline:end},null,2));
const note=`[HOST RECOVERY / infrastructure only]\nThe previous task stopped with ${failure}. All previous requests, model reasoning, tool outputs and the failed task are preserved. A fresh context in the SAME ObjRun controller continues inside the ORIGINAL five-hour window ending ${end.deadline_utc}. Model remains exactly deepseek/deepseek-v4.1-flash; checker and <=30 original R3 KS target are unchanged. Healthy owned jobs ${JSON.stringify(healthyJobs)} remain active; use job_status to inspect them and avoid duplicate launches. Current best independently verified n=31 is NOT success. Read /work/progress.json and the newest progress_ks30_*.json for prior search coverage; treat their finite-pool exclusion labels as model claims, not independently certified universal bounds. Current jobs 60 and 61 are exact size-bounded hitting-set searches over 289-ray integer and Q(sqrt2) pools. Earlier method bugs and transport failures were recorded; later ks30 scripts replaced the buggy initial ihs.py. Candidate coordinates, existing scripts and logs remain in /work. Do not reread all old logs into context. Use concise status reads and productive CPU work during remaining time. No new campaign/time/cost/token/iteration allowance is introduced. Stop at the immutable deadline; after it only host final verification is allowed. Do not repeatedly submit 31-ray sets or call partial finite-pool results main success.\n\n`;
writeFileSync(join(run,'work/HOST_RECOVERY.md'),note);
await api('/exec',{sql:"update task set state='failed',result=:result where id=:id and state='claimed'",params:{id:oldTask,result:JSON.stringify({outcome:'host_infrastructure_recovery',reason:failure+'; no clock reset or scientific rejection; healthy owned search jobs retained.'})}});
let next='';
while(Date.now()<end.deadline_epoch*1000){await Bun.sleep(250);const st=JSON.parse(readFileSync(join(run,'status.json'),'utf8'));if(st.task.id!==oldTask){next=st.task.id;break;}}
if(!next)throw new Error('No continuation task before deadline');
await api('/exec',{sql:'update task set description=:note || description where id=:id',params:{id:next,note}});
writeFileSync(join(run,`recovery-${stamp}.json`),JSON.stringify({utc:new Date().toISOString(),old_task:oldTask,new_task:next,reason:failure,deadline:end,note,healthy_jobs_retained:healthyJobs,checker_changed:false},null,2));
console.log(JSON.stringify({old_task:oldTask,new_task:next,deadline:end.deadline_utc,healthy_jobs_retained:healthyJobs}));
