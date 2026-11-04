import {readFileSync,writeFileSync} from 'node:fs';
import {resolve,join} from 'node:path';
import {parse} from '../../../app/node_modules/yaml/dist/index.js';
const root=resolve(import.meta.dir,'../../..'),run=readFileSync(join(root,'data/spherical-landscape/latest-run.txt'),'utf8').trim();
const ep=JSON.parse(readFileSync(join(run,'endpoints.json'),'utf8')),cfg=parse(readFileSync(join(run,'engine/config.yaml'),'utf8'));
async function call(path:string,body:any){const r=await fetch(ep.engine+path,{method:'POST',headers:{'content-type':'application/json',authorization:'Bearer '+cfg.api.token},body:JSON.stringify(body)});if(!r.ok)throw new Error(String(r.status));return r.json();}
const before=await call('/query',{sql:"select * from agent_landscape_msg where unit in (28,29) order by unit,seq"});
writeFileSync(join(run,'intervention-repair-before.json'),JSON.stringify(before,null,2));
const result=await call('/exec',{sql:"update agent_landscape_msg set unit=29,seq=3 where instance='spherical-landscape-search-001#1' and unit=28 and seq=2 and kind='user'"});
writeFileSync(join(run,'intervention-repair.json'),JSON.stringify({time:new Date().toISOString(),reason:'Preserve actual tool-call/result adjacency; relocate automated intervention to subsequent unfinished ask unit. Original rows saved intact in intervention-repair-before.json.',result},null,2));
console.log(JSON.stringify(result));
