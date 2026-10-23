import {join} from 'node:path';
import {readFileSync} from 'node:fs';
import {Database} from 'bun:sqlite';
import {native} from './native.ts';
import {cfg,ROOT,OUT,read,save,hash} from './common.ts';
const original=cfg.recoveryFrom;
if(!original)throw Error('RecoveryControlsRequireOriginal');
cfg.recoveryFixture=true;
process.env.OPENROUTER_API_KEY='fixture-not-a-real-key';
const checks:any[]=[];
function check(name:string,ok:any){checks.push({name,passed:!!ok});if(!ok)throw Error(name);}
for(const task of read(join(ROOT,'data/public-recovery.json'))){
 const dir=join(OUT,'recovery-control-v4',task.id);
 const r=await native(task,dir,join(OUT,'unused-calls'),async answer=>({valid:true,parsed:answer==='GOOD',passed:answer==='GOOD',candidateSha256:hash(answer)}),true);
 check(task.id+':actual-native-continuation-submits',r.answer==='GOOD'&&r.candidateHow==='submitted');
 const p=read(join(dir,'recovery-provenance.json'));
 check(task.id+':unused-original-clock-only',p.remainingSolveMilliseconds>0&&p.remainingSolveMilliseconds<300000&&p.usedSolveMilliseconds+p.remainingSolveMilliseconds===600000);
 const db=new Database(join(dir,'engine/data/h2h.sqlite'),{readonly:true});
 const priorCalls:any[]=db.query("select body from agent_bot_msg where unit<? and kind='call'").all(p.pendingUnit);
 check(task.id+':completed-units-preserved',priorCalls.length===(task.id.endsWith('001')?1:0));
 const tools:any[]=db.query("select body from agent_bot_msg where kind='tool'").all();
 check(task.id+':checks-retained',!task.id.endsWith('001')||tools.some(t=>JSON.parse(t.body).value?.left===4));
 db.close();
 check(task.id+':original-bytes-unmodified',p.originalEngineFiles.every((f:any)=>hash(readFileSync(f.path))===f.sha256));
}
delete cfg.recoveryFixture;
save(join(OUT,'recovery-controls.json'),{allPassed:checks.every(c=>c.passed),modelCalls:0,checks});
console.log(JSON.stringify({allPassed:true,checks:checks.length,modelCalls:0}));
