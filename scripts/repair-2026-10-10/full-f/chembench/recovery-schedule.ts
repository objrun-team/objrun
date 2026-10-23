/** Recovery ordering only; the frozen cohort and taskSchedule remain unchanged. */
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { Database } from 'bun:sqlite';
const json=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
export function recoveryHistory(runDirectories:string[], latest:any[]) {
  const attempts=new Map<number,Set<string>>();
  const evidence:any[]=[];
  const add=(index:number,runId:string,path:string,kind:string)=>{
    if(!Number.isInteger(index)||index<0||index>=500)throw Error('Recovery history index outside frozen cohort');
    const seen=attempts.get(index)??new Set<string>();seen.add(runId);attempts.set(index,seen);
    evidence.push({index,runId,path,kind});
  };
  for(const dir of runDirectories){
    const runId=dir.split(/[\\/]/).at(-1)!;
    for(const name of readdirSync(dir).filter(n=>/^task-\d+\.json$/.test(n))){const r=json(join(dir,name));add(r.index,runId,join(dir,name),'archived-outcome');}
    for(const name of readdirSync(dir).filter(n=>/^engine-\d+-\d+\.json$/.test(n))){
      const e=json(join(dir,name)),path=join(dir,`worker-${e.worker}`,`task-${e.taskIndex}`,'data/h2h.sqlite');
      if(!existsSync(path))continue;
      const db=new Database(path,{readonly:true});
      try{if((db.query('select count(*) as n from task').get() as any).n>0)add(e.taskIndex,runId,join(dir,name),'started-cold-engine-task');}finally{db.close();}
    }
  }
  for(const r of latest)if(!attempts.has(r.index))add(r.index,r.runId,'results/task-'+r.index+'.json','legacy-outcome');
  return {attempts,evidence};
}
export function recoveryOrder<T extends {index:number}>(tasks:T[], latest:any[],attempts:Map<number,Set<string>>){
  const skip=new Set(latest.filter(r=>r.acceptance?.valid===true||r.terminalProtocolFailure===true||r.terminalTimeoutFailure===true).map(r=>r.index));
  return tasks.filter(t=>!skip.has(t.index)).sort((a,b)=>(attempts.get(a.index)?.size??0)-(attempts.get(b.index)?.size??0)||a.index-b.index);
}
