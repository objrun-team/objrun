// Host infrastructure observations delivered through the real ObjRun task API.
import {readFileSync,appendFileSync} from 'node:fs';
import {resolve,join,dirname} from 'node:path';
import {parse} from '../../app/node_modules/yaml/dist/index.js';
const root=resolve(import.meta.dir,'../..');
const run=readFileSync(join(root,'data/ks-original-search/latest-run.txt'),'utf8').trim();
const end=JSON.parse(readFileSync(join(run,'deadline.json'),'utf8'));
if(Date.now()>=end.deadline_epoch*1000)throw new Error('Original window closed');
const ep=JSON.parse(readFileSync(join(run,'endpoints.json'),'utf8'));
const config=parse(readFileSync(join(dirname(dirname(ep.database)),'config.yaml'),'utf8'));
const status=JSON.parse(readFileSync(join(run,'status.json'),'utf8'));
const body=readFileSync(process.argv[2],'utf8');
const res=await fetch(ep.engine+'/tasks/'+status.task.id+'/messages',{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+config.api.token},body:JSON.stringify({body:'[Automated host-orchestrator observation, not a new user instruction]\n'+body})});
const result=await res.json();appendFileSync(join(run,'host-interventions.jsonl'),JSON.stringify({time:new Date().toISOString(),body,result})+'\n');console.log(JSON.stringify(result));
