"""Zero-provider-call fixture of the actual new scheduler with the preserved solver body."""
from pathlib import Path
import json,sqlite3,subprocess,time
from infra_retry_policy import ARMS,EXPERIMENT,SUFFIX,classify,sha

BASE=Path('/var/tmp/tgengin-scibench-20261016');tool=Path(__file__).resolve().parent
root=BASE/'fixtures'/('infra-retry2-fixture-'+str(int(time.time())))
root.mkdir(parents=True);package=root/'package';package.mkdir();out=root/'outputs/canonical';out.mkdir(parents=True)
source=BASE/'scibench-formal-20261016-v4-c32/package'
old=(source/'run.ts').read_text();one=old[old.index('async function executeOne('):old.index('\nasync function main()')]
template=(tool/'infra_retry2_runner.ts').read_text().replace('// New attempt scheduling only; __EXECUTE_ONE__ is copied byte-for-byte from the formal runner.','// zero-model fixture')
(package/'run.ts').write_text(template.replace('__EXECUTE_ONE__',one));(package/'sequence.ts').write_bytes((source/'sequence.ts').read_bytes())
cfg=json.loads((source/'experiment.json').read_text());(package/'experiment.json').write_text(json.dumps(cfg))
tasks=[{'id':f'fixture-{i:03d}','source':'fixture','prompt':f'fixture-{i:03d}'} for i in range(12)];(root/'data').mkdir();(root/'data'/cfg['catalog']).write_text(json.dumps(tasks))
attempts=[{'arm':arm,'id':t['id'],'attemptId':EXPERIMENT+'/'+arm+'/'+t['id']+'/infra-retry-2','attemptNo':2,'previousAttemptId':'fixture/prior/infra-retry-1','previousResultSha256':sha('previous-'+arm+t['id']),'originalPromptSha256':sha(t['prompt']+SUFFIX),'originalResultSha256':sha('mock-original-'+arm+t['id'])} for t in tasks for arm in ARMS]
db=sqlite3.connect(root/'attempts.sqlite');db.execute('CREATE TABLE attempts(attemptId TEXT PRIMARY KEY,state TEXT,ownerPid INTEGER,claimedAtUtc TEXT,completedAtUtc TEXT,resultSha256 TEXT)');db.executemany('INSERT INTO attempts(attemptId,state) VALUES(?,?)',[(x['attemptId'],'pending') for x in attempts]);db.commit();db.close()
(package/'repair-plan.json').write_text(json.dumps({'attempts':attempts,'registryPath':str(root/'attempts.sqlite'),'maxNewFullAttemptsPerIdentity':1,'originalExperiment':EXPERIMENT}));(out/'controls.json').write_text('{"allPassed":true}')
common=r'''
import {existsSync,mkdirSync,readFileSync,readdirSync,writeFileSync,openSync,closeSync,renameSync} from 'node:fs';import {join,dirname,resolve} from 'node:path';import {createHash} from 'node:crypto';
export const HERE=import.meta.dir,ROOT=resolve(HERE,'..'),OUT=join(ROOT,'outputs/canonical');export const read=(p:string)=>JSON.parse(readFileSync(p,'utf8'));export const cfg=read(join(HERE,'experiment.json'));export const hash=(x:any)=>createHash('sha256').update(x).digest('hex');
export function save(p:string,v:any){mkdirSync(dirname(p),{recursive:true});let t=p+'.tmp';writeFileSync(t,JSON.stringify(v));renameSync(t,p);}export function durable(p:string,v:any){mkdirSync(dirname(p),{recursive:true});let f=openSync(p,'wx');writeFileSync(f,JSON.stringify(v));closeSync(f);}export const walk=(p:string):string[]=>existsSync(p)?readdirSync(p,{withFileTypes:true}).flatMap(x=>x.isDirectory()?walk(join(p,x.name)):[join(p,x.name)]):[];
export const accounting=()=>({modelCalls:0,actualCostUsd:0,unknownCostCount:0,unknownCostUpperBoundUsd:0,budgetSpentUsd:0});export class BudgetStop extends Error{};export async function observe(){}
let active=0,peak=0,calls=0;export async function mocked(answer:string){active++;calls++;peak=Math.max(peak,active);await new Promise(r=>setTimeout(r,100));active--;save(join(OUT,'mock-metrics.json'),{active,peak,calls,realProviderCalls:0});return answer;}
export async function model(dir:string,body:any,group:string,deadline:number){const arm=group.split('/').at(-2),index=Number(dir.split('-').at(-1));if(arm!=='binary'&&body.messages.length!==1)throw Error('FixtureHistoryLeak');if(arm==='binary'&&body.messages.length!==1+2*index)throw Error('FixtureBinaryHistoryMismatch');if(arm==='binary')for(let i=2;i<body.messages.length;i+=2)if(body.messages[i].role!=='user'||!['passed','failed'].includes(body.messages[i].content))throw Error('FixtureBinaryFeedbackLeak');const answer=await mocked(body.messages[0].content.includes('fixture-000')?'no':'ok');return {answer,receipt:{}};}
'''
(package/'common.ts').write_text(common)
(package/'native.ts').write_text("import {mocked} from './common.ts'; export async function native(q:any,dir:string,calls:string,grade:any){return {answer:await mocked('ok'),candidateHow:'submit',budgetReason:null};}")
(package/'stand.py').write_text('''import hashlib,json
from http.server import BaseHTTPRequestHandler,HTTPServer
class Handler(BaseHTTPRequestHandler):
 def log_message(self,*a):pass
 def do_POST(self):
  data=json.loads(self.rfile.read(int(self.headers['Content-Length'])));answer=data['input']['result'];self.send_response(200);self.end_headers();self.wfile.write(json.dumps({'valid':True,'passed':answer=='ok','candidateSha256':hashlib.sha256(answer.encode()).hexdigest()}).encode())
s=HTTPServer(('127.0.0.1',0),Handler);print(json.dumps({'port':s.server_port}),flush=True);s.serve_forever()
''')
p=subprocess.run([str((BASE/'scibench-formal-20261016-v4-c32/bin/bun').resolve()),str(package/'run.ts')],cwd=root,capture_output=True,text=True,timeout=60)
(root/'stdout.log').write_text(p.stdout);(root/'stderr.log').write_text(p.stderr);assert p.returncode==0,p.stderr[-2500:]
status=json.loads((out/'status.json').read_text());assert status['stage']=='complete',status
metrics=json.loads((out/'mock-metrics.json').read_text());assert metrics['peak']==32 and metrics['realProviderCalls']==0,metrics
records=[json.loads(p.read_text()) for p in (out/'results').rglob('*.json')];assert len(records)==48 and len({r['attemptId'] for r in records})==48
for r in records:
 if r['arm']!='objrun':assert r['sampleCount']==(5 if r['id']=='fixture-000' and r['arm']!='baseline' else 1)
db=sqlite3.connect(root/'attempts.sqlite');assert db.execute("SELECT count(*) FROM attempts WHERE state='complete'").fetchone()[0]==48
assert db.execute("UPDATE attempts SET state='started' WHERE state='pending'").rowcount==0;db.close()
base={'arm':'objrun','grade':{'valid':False,'passed':False,'outcome':'infrastructure_error'},'error':'Error: ProviderFault:TimeoutError','modelCalls':1}
assert classify(base)=='infra_transport'
assert classify({**base,'grade':{'valid':True,'passed':False}})=='valid_fail'
assert classify({**base,'candidateHow':'none'})=='native_no_final_submission'
assert classify({**base,'engineVerdict':{'expired':'over solve_seconds=600s'}})=='native_budget_exhausted'
assert classify({**base,'error':'Error: SourceChanged:module'})=='integrity_or_protocol_error'
assert classify({**base,'error':'Unexpected application error'})=='unclassified_invalid'
assert classify({**base,'arm':'baseline','error':'TimeoutError: account check','modelCalls':0})=='infra_account_check'
assert all(r['attemptNo']==2 and r['previousAttemptId'].endswith('/infra-retry-1') and len(r['previousResultSha256'])==64 for r in records)
result={'allPassed':True,'fixtureRoot':str(root),'realProviderCalls':0,'observedPeakTasks':32,'completedFreshAttempts':48,'preservedExecuteOneSha256':sha(one),'checks':['actual runner completes all planned identities','four arms share32','independent context isolation','binary own answer and boolean feedback only','baseline1 and sequence5 ceilings','EX early stop','unique attempt primary keys and completed claim rejection','valid failures excluded','native budget and no-submit excluded','unclassified and integrity errors quarantined','account check and provider faults included','second-round previous-result links retained']}
(tool/'FIXTURE_AUDIT.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result))
