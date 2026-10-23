/** Metadata-only observer. Does not modify frozen runner sources or dispatch any requests. */
import { existsSync,readFileSync,readdirSync,writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { Database } from 'bun:sqlite';
import { OUT } from './prepare.ts';
const json=(p:string)=>JSON.parse(readFileSync(p,'utf8'));
function enrich(){
  try{
    const statusPath=join(OUT,'status.json'),s=json(statusPath);
    const dir=join(OUT,'results'),records=existsSync(dir)?readdirSync(dir).filter(n=>/^task-\d+\.json$/.test(n)).map(n=>json(join(dir,n))):[];
    const attempted=new Set<number>(records.map(r=>r.index));
    if(s.runOut&&existsSync(s.runOut))for(const name of readdirSync(s.runOut).filter(n=>/^engine-\d+-\d+\.json$/.test(n))){
      const e=json(join(s.runOut,name)),dbPath=join(s.runOut,`worker-${e.worker}`,`task-${e.taskIndex}`,'data/h2h.sqlite');
      if(existsSync(dbPath)){const db=new Database(dbPath,{readonly:true});try{if((db.query('select count(*) as n from task').get() as any).n>0)attempted.add(e.taskIndex);}finally{db.close();}}
    }
    const counters={denominator:500,validlyScored:records.filter(r=>r.acceptance?.valid===true).length,
      terminalProtocolFailures:records.filter(r=>r.terminalProtocolFailure===true).length,
      terminalTimeoutFailures:records.filter(r=>r.terminalTimeoutFailure===true).length,
      infrastructureFailures:records.filter(r=>r.acceptance?.valid!==true&&!r.terminalProtocolFailure&&!r.terminalTimeoutFailure).length,
      attempted:attempted.size,unattempted:500-attempted.size,inProgress:attempted.size-records.length,
      scoreCertificationLimitation:'Constrained-auto can return no submit tool. Such terminal protocol failures remain in denominator and are not validly scored; reliable forced submission is not established.'};
    // Re-read after the scan to preserve the runner's newest financial/status fields.
    const latest=json(statusPath);if(latest.runId!==s.runId)return;
    if(Object.entries(counters).some(([k,v])=>latest[k]!==v))writeFileSync(statusPath,JSON.stringify({...latest,...counters,outcomeCountersObservedAtUtc:new Date().toISOString()},null,2)+'\n');
    return latest.stage;
  }catch{return undefined;}
}
enrich();
if(!process.argv.includes('--once')){const timer=setInterval(()=>{const stage=enrich();if(stage&&stage!=='running')clearInterval(timer);},5000);}
