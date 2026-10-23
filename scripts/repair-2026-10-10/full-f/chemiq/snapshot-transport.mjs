import {readFileSync,writeFileSync,mkdirSync,copyFileSync,existsSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {Database} from 'bun:sqlite';
import {actualPin} from '../../../repair-2026-10-08/paid-resource-proof-v2.ts';
const root=resolve(import.meta.dir,'../../../..'),out=join(root,'docs/repair-2026-10-10/full-f-rerun/chemiq');
const receipt=JSON.parse(readFileSync(join(out,'transport-switch-suspended.json'),'utf8').replace(/^\uFEFF/,''));
const snapshot=join(receipt.output,'transport-switch-snapshots');mkdirSync(snapshot,{recursive:true});
const tasks=[];
for(const process of receipt.engines){
 const from=join(receipt.output,'task-'+process.index,'engine/data/h2h.sqlite'),to=join(snapshot,'task-'+process.index);mkdirSync(to,{recursive:true});
 const pins=[];for(const suffix of ['','-wal','-shm'])if(existsSync(from+suffix)){const path=join(to,'h2h.sqlite'+suffix);copyFileSync(from+suffix,path);pins.push(actualPin(path));}
 const db=new Database(from,{readonly:true});try{tasks.push({index:process.index,pid:process.pid,databasePins:pins,tasks:db.query('select * from task').all(),repairs:db.query('select * from task_repair').all()});}finally{db.close();}
}
writeFileSync(join(snapshot,'snapshot.json'),JSON.stringify({atUtc:new Date().toISOString(),runId:receipt.runId,enginesSuspended:true,paidRequestsDrainedBeforeKill:true,tasks,scoreCertificate:false},null,2)+'\n');
console.log(JSON.stringify({saved:true,tasks:tasks.map(t=>({index:t.index,state:t.tasks.map(r=>({state:r.state,result:r.result}))}))}));
