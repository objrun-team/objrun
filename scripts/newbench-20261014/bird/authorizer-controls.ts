import {join} from 'node:path';
import {HERE,OUT,read,save,grade} from './common.ts';
const tasks=read(join(HERE,'public-tasks.json')),gold=read(join(HERE,'dev_20251106.json'));
const dir=join(OUT,'diagnosis-authorizer/controls-after'),checks:any={};
for(const id of [94,95,103,105,106]){
 const task=tasks.find((t:any)=>t.question_id===id),sql=gold.find((t:any)=>t.question_id===id).SQL;
 checks['gold-'+id]=await grade(task,sql,dir);
}
const task=tasks.find((t:any)=>t.question_id===94);
checks.count=await grade(task,'SELECT COUNT(*) FROM client',dir,'SELECT COUNT(*) FROM client');
checks.attach=await grade(task,"ATTACH DATABASE ':memory:' AS extra",dir,'SELECT 1');
checks.write=await grade(task,'CREATE TABLE forbidden(x)',dir,'SELECT 1');
checks.extension=await grade(task,"SELECT load_extension('x')",dir,'SELECT 1');
checks.pragma=await grade(task,'PRAGMA database_list',dir,'SELECT 1');
checks.temp=await grade(task,'SELECT COUNT(*) FROM temp.sqlite_master',dir,'SELECT 1');
const allPassed=Object.entries(checks).every(([k,v]:[string,any])=>v.valid&&(k.startsWith('gold-')||k==='count'?v.passed:!v.passed));
save(join(OUT,'diagnosis-authorizer/controls-after.json'),{atUtc:new Date().toISOString(),allPassed,checks});console.log(JSON.stringify({allPassed,checks}));if(!allPassed)process.exitCode=1;
