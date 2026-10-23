import {Database} from 'bun:sqlite';
import {join} from 'node:path';
import {finalCandidate} from '../runtime-snapshot/app/src/objective/candidate.ts';

export function readNativeCheckpoint(engineDir:string,taskId:string) {
 const db=new Database(join(engineDir,'data/h2h.sqlite'),{readonly:true});
 const conn={all:(sql:string,params:any[]=[])=>{const q=db.prepare(sql);try{return q.all(...params);}finally{q.finalize();}},run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}};
 try {
  const candidate=finalCandidate(conn as any,taskId);
  const state=conn.all('select * from task where id=?',[taskId])[0] as any;
  const trace=conn.all('select * from agent_bot_msg order by instance,unit,seq limit 100000');
  return {candidate,state,trace};
 }finally{db.close();}
}

export function recoverSubmittedAtDeadline(engineDir:string,taskId:string,error:unknown,now=Date.now()) {
 if(!String(error).includes('ProviderSolveDeadlineReached'))throw error;
 const checkpoint=readNativeCheckpoint(engineDir,taskId);
 const {candidate,state}=checkpoint;
 const deadline=Number(state?.created_at)+Number(state?.solve_seconds)*1000;
 const verdict=state?.result?JSON.parse(state.result):null;
 if(!Number.isFinite(deadline)||now<deadline||candidate?.how!=='submitted'||verdict?.outcome==='grader_error')throw error;
 return {answer:candidate.body,candidateHow:candidate.how,engineState:state.state,engineVerdict:verdict,
  modelProtocolFailure:false,solveSeconds:Number(state.solve_seconds),nativeInterruptedBy:String(error),
  recoveredFromNativeCheckpoint:true,checkpoint};
}
