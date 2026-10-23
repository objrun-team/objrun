import {Database} from 'bun:sqlite';
import {finalCandidate} from './engine/app/src/objective/candidate.ts';
const q=JSON.parse(await Bun.stdin.text()),db=new Database(q.db,{readonly:true});
try{
 const c=finalCandidate({all:(sql:string,params:any[]=[])=>{
  const args=[...params];if(sql.includes('at <= ?'))args[args.length-1]=Math.min(Number(args[args.length-1]),q.cutoffMs);
  const s=db.prepare(sql);try{return s.all(...args);}finally{s.finalize();}
 },run(){throw Error('readonly')},exec(){throw Error('readonly')},close(){}} as any,q.taskId);
 console.log(JSON.stringify({answer:c?.body??'',candidateHow:c?.how??'none',cutoffMs:q.cutoffMs}));
}finally{db.close();}
