// Internal supervisor feedback, delivered as world evidence, never as a human.
import { readFileSync, appendFileSync } from 'node:fs';
import { resolve, join } from 'node:path';
import { open } from '../../app/src/H2H/db.ts';
import { deliver } from '../../app/src/msg/deliver.ts';
const run=resolve(process.argv[2]),file=resolve(process.argv[3]);
const ep=JSON.parse(readFileSync(join(run,'endpoints.json'),'utf8'));
const db=open({db:{file:ep.database,pragmas:{busy_timeout:5000}}} as any);
try {
 // Deliver after a completed act station's complete tool-result batch. Injecting
 // into a running act can split assistant calls from tool results and stall SDK.
 const u=db.ro.all("select task,agent,instance,unit from task_conway99_search where cycle='act' and done=1 order by rowid desc limit 1")[0];
 if(!u)throw Error('No completed tool-result batch; leave the feedback file queued');
 const seq=deliver(db.rw,{agent:String(u.agent),instance:String(u.instance),unit:Number(u.unit),by:'world',who:'campaign-health-monitor',body:readFileSync(file,'utf8')});
 const receipt={utc:new Date().toISOString(),event:'monitor_feedback',...u,seq,source_file:file,by:'world'};
 appendFileSync(join(run,'monitoring/interventions.jsonl'),JSON.stringify(receipt)+'\n');
 console.log(JSON.stringify(receipt));
}finally{db.close();}

