"""Exercises exact legacy run.ts with local mocks; no API key or model calls."""
from pathlib import Path
import hashlib,json,os,shutil,subprocess,time

origin=Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/scibench-formal-20261016-v1')
lab=origin.parent/'scibench-switch32-lab-20261016-v1'
lab.mkdir(exist_ok=True)
guard=Path(__file__).with_name('admission_drain.py')
outcomes=[]
for k in range(3):
    r=lab/('drain-fixture-'+str(k));assert not r.exists(),'NeverOverwriteFixture'
    package=r/'package';package.mkdir(parents=True);(r/'data').mkdir();(r/'bin').mkdir()
    (r/'bin/bun').symlink_to(origin/'bin/bun')
    out=r/'outputs/canonical';out.mkdir(parents=True)
    for n in ['run.ts','sequence.ts','stand.py']:shutil.copyfile(origin/'package'/n,package/n)
    (package/'grade.py').write_text('''import hashlib
class Scorer:
 def __init__(self,vendor):pass
 def target(self,row):return ('2','x')
 def public(self,row):return row
 def judge(self,text,row):return {'valid':True,'parsed':True,'passed':False,'outcome':'rejected','candidateSha256':hashlib.sha256(text.encode()).hexdigest()}
''')
    cfg=json.loads((origin/'package/experiment.json').read_text());cfg['run']=r.name;cfg['fixtureExtraMs']=k*30
    (package/'experiment.json').write_text(json.dumps(cfg))
    tasks=[{'id':'fixture-'+str(i).zfill(3),'source':'fixture','prompt':'fixture '+str(i)} for i in range(416)]
    (r/'data/public-formal.json').write_text(json.dumps(tasks));(r/'data/private-tasks.json').write_text(json.dumps(tasks))
    (out/'controls.json').write_text('{"allPassed":true}')
    common=(origin/'package/common.ts').read_text().split('export class BudgetStop')[0]
    common=common.replace("import {decodeProviderResponse} from './transport.ts';",'')
    common+='''export class BudgetStop extends Error{}
export async function observe(){}
export async function model(dir:string,body:any,groupCalls:string,deadline:number){
 const arm=groupCalls.split('/').at(-2),id=groupCalls.split('/').at(-1),start=Date.now();
 const d=join(dir,'attempt-0'),requestSha256=hash(JSON.stringify(body));
 durable(join(d,'request.json'),body);durable(join(d,'dispatch.json'),{atUtc:new Date().toISOString(),pid:process.pid,requestSha256,reserveUsd:0});
 await Bun.sleep(id==='fixture-000'?30:(arm==='baseline'?130:arm==='objrun'?1500:arm==='binary'?400:300)+cfg.fixtureExtraMs);
 if(Date.now()>deadline)throw Error('FixtureOriginalDeadlineExceeded');
 const receipt={generationId:'fixture-'+arm+'-'+id+'-'+dir.split('/').at(-1),actualCostUsd:0,unknownCost:false,upperBoundUsd:0,requestSha256,seconds:(Date.now()-start)/1000};
 durable(join(d,'receipt.json'),receipt);return {answer:'\\\\boxed{1}',receipt};
}
'''
    (package/'common.ts').write_text(common)
    (package/'native.ts').write_text('''import {join} from 'node:path';import {cfg,model} from './common.ts';
export async function native(task:any,dir:string,calls:string,grade:any){const r=await model(join(calls,'native-001'),{messages:[{role:'user',content:task.prompt}]},calls,Date.now()+cfg.solveSeconds*1000);return {answer:r.answer,candidateHow:'submit'};}
''')
    env={'PATH':str(r/'bin')+':/usr/bin:/bin','PYTHONUTF8':'1','NO_PROXY':'127.0.0.1,localhost'}
    with (out/'controller.stdout.log').open('wb') as so,(out/'controller.stderr.log').open('wb') as se:
        child=subprocess.Popen([str(r/'bin/bun'),str(package/'run.ts')],cwd=r,env=env,stdout=so,stderr=se)
    (out/'launch.json').write_text(json.dumps({'pid':child.pid,'root':str(r)}))
    until=time.monotonic()+10
    while not (out/'grader-process.json').exists() or not (out/'status.json').exists():
        assert child.poll() is None,(out/'controller.stderr.log').read_text()
        assert time.monotonic()<until;time.sleep(.005)
    p=subprocess.run(['/usr/bin/python3.11',str(guard),'--fixture','--root',str(r)],capture_output=True,text=True,timeout=30)
    if p.returncode:raise RuntimeError(p.stdout+p.stderr)
    child.wait(timeout=5)
    s=json.loads((out/'status.json').read_text());events=[json.loads(x) for x in (r/'ops/switch32/events.jsonl').read_text().splitlines()]
    rows=[json.loads(p.read_text()) for p in (out/'results').rglob('*.json')]
    dispatches=list((out/'calls').rglob('dispatch.json'))
    assert child.returncode==0 and s['stage']=='needs_attention' and not s['active']
    assert len(rows)>=8 and all(x['grade']['valid'] for x in rows)
    assert all(p.with_name('receipt.json').exists() for p in dispatches)
    assert any(x['event']=='premature_grader_sigterm_suppressed' and x['expectedController'] for x in events)
    assert hashlib.sha256((package/'run.ts').read_bytes()).digest()==hashlib.sha256((origin/'package/run.ts').read_bytes()).digest()
    result={'fixture':k,'records':len(rows),'requests':len(dispatches),'allReceipted':True,'noActive':True,'exactLegacyController':True,'allCandidatesValid':True,'sourceUnchanged':True,'events':events}
    outcomes.append(result)
(lab/'FIXTURE_AUDIT.json').write_text(json.dumps({'allPassed':True,'realModelCalls':0,'actualUsd':0,'fixtures':outcomes},indent=2)+'\n')
print(json.dumps({'allPassed':True,'realModelCalls':0,'fixtures':[{'fixture':x['fixture'],'records':x['records'],'requests':x['requests']} for x in outcomes]}))
