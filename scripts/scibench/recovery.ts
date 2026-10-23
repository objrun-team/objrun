import {cpSync,existsSync,mkdirSync,readFileSync} from 'node:fs';
import {join,resolve} from 'node:path';
import {Database} from 'bun:sqlite';
import {cfg,read,save,hash,walk} from './common.ts';

/** Work on a separate copy; retain history, checks, branches, and the unused solve clock. */
export function restoreNative(task:any,dir:string,base:string){
 const original=resolve(cfg.recoveryFrom),source=join(original,'outputs/canonical/tasks/objrun',task.id);
 const prior=read(join(original,'outputs/canonical/results/objrun',task.id+'.json'));
 if(prior.grade?.valid||!String(prior.error).includes('NonJSONProviderResponse'))throw Error('RecoveryScopeMismatch');
 const target=join(dir,'engine');if(existsSync(join(target,'data/h2h.sqlite')))throw Error('RecoveryAlreadyAttempted');
 if(resolve(dir).startsWith(original+'/'))throw Error('RecoveryMustPreserveOriginal');
 mkdirSync(dir,{recursive:true});cpSync(join(source,'engine'),target,{recursive:true});
 const sourcePins=walk(join(source,'engine')).map(path=>({path,sha256:hash(readFileSync(path))}));
 const db=new Database(join(target,'data/h2h.sqlite'));
 const tasks:any[]=db.query('select * from task').all();if(tasks.length!==1)throw Error('RecoveryTaskIdentity');
 const row=tasks[0],used=Math.max(0,Date.parse(prior.completedAtUtc)-row.created_at),remaining=row.solve_seconds*1000-used;
 if(remaining<=0||row.solve_seconds!==cfg.solveSeconds)throw Error('NoOriginalSolveTimeRemaining');
 const pending:any[]=db.query('select * from task_repair where done=0').all();
 if(pending.length!==1||pending[0].cycle!=='ask')throw Error('AmbiguousNativeRecovery');
 const p=pending[0],messages:any[]=db.query('select * from agent_bot_msg where instance=? and unit=?').all(p.instance,p.unit);
 if(messages.some(m=>{
  if(m.role==='user')return false;
  if(m.role!=='system'||m.kind!=='inject')return true;
  const b=JSON.parse(m.body);return !b.sent&&!b.stuck;
 }))throw Error('PendingUnitHasDeliveredResponse');
 const now=Date.now();
 db.transaction(()=>{
  db.query('update task set created_at=? where id=?').run(now-used,row.id);
  db.query('update task_repair set at=? where task=? and unit=?').run(now,row.id,p.unit);
  db.query("delete from agent_bot_msg where instance=? and unit=? and role='system' and kind='inject'").run(p.instance,p.unit);
  db.query("update api set base_url=? where key_env='OPENROUTER_API_KEY' and model=?").run(base+'/v1',cfg.model);
  for(const name of ['parsed','correct']){
   const handle:any=db.query('select name from handle where name like ?').get('%/'+name);
   if(!handle)throw Error('MissingOriginalGraderHandle');
   db.query('update handle set name=? where name=?').run(base+'/'+name,handle.name);
  }
 })();db.close();
 const sealed=new Database(join(target,'data/sealed.sqlite'));
 const objective:any=sealed.query('select body from objective where task=?').get(row.id),spec=JSON.parse(objective.body);
 for(const node of spec.nodes)node.handle=base+'/'+node.name;
 sealed.query('update objective set body=? where task=?').run(JSON.stringify(spec),row.id);sealed.close();
 const faults=walk(join(original,'outputs/canonical/calls/objrun',task.id)).filter(p=>p.endsWith('/receipt.json')).map(path=>({path,value:read(path)})).filter(x=>x.value.fault==='NonJSONProviderResponse');
 if(faults.length!==1)throw Error('RecoveryFaultIdentity');
 const requestPath=join(resolve(faults[0].path,'..'),'request.json'),wire=read(requestPath);
 save(join(dir,'recovery-provenance.json'),{originalRoot:original,originalRecord:prior,originalEngineFiles:sourcePins,
  taskId:row.id,pendingUnit:p.unit,originalCreatedAt:row.created_at,originalSolveSeconds:row.solve_seconds,
  usedSolveMilliseconds:used,remainingSolveMilliseconds:remaining,resumedCreatedAt:now-used,deadline:now+remaining,
  preservedChecks:true,preservedHistory:true,preservedBranches:true,removedUndeliveredMarkers:messages.filter(m=>m.role==='system'),
  interruptedRequestPath:requestPath,interruptedRequestSha256:hash(JSON.stringify(wire)),recoverySessionsAllowed:1,
  policy:'Replay the interrupted wire once, then continue this native task inside its unused original 600s clock; never regenerate completed units. API transport chain remains at most 3 attempts.'});
 return {id:row.id,deadline:now+remaining,wire};
}
