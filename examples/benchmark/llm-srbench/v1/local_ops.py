"""Local operator: stage this source snapshot, pass key via SSH stdin, mirror artifacts."""
import argparse,hashlib,json,pathlib,re,shutil,subprocess,sys,tarfile,time
SOURCE=pathlib.Path(__file__).resolve().parent;REPO=SOURCE.parents[3]
LOCAL=REPO/'work/llm-srbench-20261019-v1';RESULTS=REPO/'runs/llm-srbench-release240-20261019';REMOTE='/mnt/aliyunsb/pingxingwang/tgengin-bench/llm-srbench-20261019-v1'
SSH=['ssh','-o','ClearAllForwardings=yes','-o','BatchMode=yes','-o','ConnectTimeout=12','novaeve']
def command(args,timeout=120,**kwargs):
    r=subprocess.run(args,capture_output=True,text=True,encoding='utf8',errors='replace',timeout=timeout,**kwargs)
    if r.returncode:raise RuntimeError((r.stderr or '')[-2000:]+'\n'+(r.stdout or '')[-2000:])
    return r.stdout
def remote(code,timeout=120):return command(SSH+['/usr/bin/python3.11','-'],input=code,timeout=timeout)
def copy(local,remote_path):
    r=subprocess.run(['scp','-q',str(local),'novaeve:'+remote_path],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=600)
    if r.returncode:raise RuntimeError(r.stderr[-1000:])
def stage():
    package=LOCAL/'package';package.mkdir(parents=True,exist_ok=True)
    for p in SOURCE.iterdir():
        if p.suffix in ['.py','.ts','.json','.md']:shutil.copy2(p,package/p.name)
    engine=package/'engine';(engine/'app').mkdir(parents=True,exist_ok=True);(engine/'test').mkdir(exist_ok=True)
    shutil.copytree(REPO/'app/src',engine/'app/src',dirs_exist_ok=True)
    for name in ['package.json','bun.lock','tsconfig.json']:shutil.copy2(REPO/'app'/name,engine/'app'/name)
    shutil.copy2(REPO/'test/_lib.ts',engine/'test/_lib.ts');(engine/'.env').write_text('')
    p=engine/'app/src/objective/run.ts';s=p.read_text(encoding='utf8');needle='export async function evaluate('
    assert s.count(needle)==1;s=s.replace(needle,'async function evaluateUnprojected(')
    s+='\n// Benchmark-copy feedback projection. Original project sources are unchanged.\nexport async function evaluate(...args: Parameters<typeof evaluateUnprojected>): Promise<Verdict> {\n const v=await evaluateUnprojected(...args);\n if(process.env.LLM_SRBENCH_BINARY === "1" && v.valid) return {...v, why:v.pass === 1 ? "passed" : "failed", note:"", trace:v.trace.map(t=>({node:t.node,value:t.value}))};\n return v;\n}\n';p.write_text(s,encoding='utf8')
    p=engine/'test/_lib.ts';s=p.read_text(encoding='utf8');s='import { appendFileSync as auditAppend } from "node:fs";\n'+s
    for stream in ['stdout','stderr']:
        old=f'proc.{stream}?.on("data", (d: Buffer) => (log += d.toString()));';new=f'proc.{stream}?.on("data", (d: Buffer) => {{ log += d.toString(); auditAppend(join(dir,"engine.{stream}.log"),d); }});';assert old in s;s=s.replace(old,new)
    p.write_text(s,encoding='utf8')
    meta={'date':'2026-10-19','sourceRepo':str(REPO),'head':command(['git','rev-parse','HEAD'],cwd=REPO).strip(),'source':'current project working tree snapshot','benchmarkCopyChanges':['binary verdict projection in evaluate','persist native engine stdout/stderr'],'originalSourcesModified':False}
    (package/'source-origin.json').write_text(json.dumps(meta,indent=2)+'\n')
    archive=LOCAL/'package.tar'
    with tarfile.open(archive,'w') as tar:tar.add(package,arcname='package',filter=lambda m:None if '__pycache__' in pathlib.PurePosixPath(m.name).parts else m)
    print(remote(f"from pathlib import Path\nr=Path('{REMOTE}');r.mkdir(parents=True,exist_ok=True)\nprint(str(r))"),flush=True)
    copy(archive,REMOTE+'/package.tar')
    setup=f'''from pathlib import Path
import tarfile,shutil,json,subprocess
r=Path('{REMOTE}');s=Path('/mnt/aliyunsb/pingxingwang/tgengin-bench/scicode-original-20261015')
assert not (r/'outputs/source-pins.json').exists(),'Refuse to mutate frozen experiment source'
with tarfile.open(r/'package.tar') as t:t.extractall(r,filter='data')
(r/'bin').mkdir(exist_ok=True)
shutil.copy2(s/'bin/bun',r/'bin/bun')
if not (r/'runtime/pyvenv.cfg').exists():subprocess.run(['/usr/bin/python3.11','-m','venv',str(r/'runtime')],check=True)
site=r/'runtime/lib/python3.11/site-packages'
(site/'000-frozen-scientific-runtime.pth').write_text('import sys;sys.dont_write_bytecode=True;sys.path.insert(0,'+repr(str(s/'venv/lib/python3.11/site-packages'))+')\\n')
if not (r/'package/engine/app/node_modules').exists():(r/'package/engine/app/node_modules').symlink_to(s/'package/engine/app/node_modules',target_is_directory=True)
(r/'outputs').mkdir(exist_ok=True)
print(json.dumps({{'setup':True}}))
'''
    print(remote(setup,timeout=600),flush=True)
    raw=REPO/'.phase1-data/llm-srbench/public-release'
    for subset in ['lsr_transform','lsr_synth_bio_pop_growth','lsr_synth_chem_react','lsr_synth_matsci','lsr_synth_phys_osc']:
        directory=raw/subset if subset=='lsr_transform' else LOCAL/'data-download'/subset
        print(remote(f"from pathlib import Path\nPath('{REMOTE}/data/raw/{subset}').mkdir(parents=True,exist_ok=True)"),end='')
        for p in sorted(directory.glob('*.parquet')):
            copy(p,REMOTE+'/data/raw/'+subset+'/'+p.name);print('uploaded',subset,p.name,p.stat().st_size,flush=True)
    print(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE+'/package/prepare.py'],timeout=600),flush=True)
def controls():
    print(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE+'/package/controls.py'],timeout=1200),flush=True)
def refresh():
    print(remote(f"from pathlib import Path\nassert not Path('{REMOTE}/outputs/source-pins.json').exists(),'Frozen source cannot be changed'\nprint('Unfrozen source refresh permitted')"),flush=True)
    archive=LOCAL/'source-refresh.tar'
    with tarfile.open(archive,'w') as tar:
        for p in SOURCE.iterdir():
            if p.suffix in ['.py','.ts','.json','.md']:tar.add(p,arcname='package/'+p.name)
    copy(archive,REMOTE+'/source-refresh.tar')
    print(remote(f"from pathlib import Path\nimport tarfile\nr=Path('{REMOTE}')\nassert not (r/'outputs/source-pins.json').exists()\nwith tarfile.open(r/'source-refresh.tar') as t:t.extractall(r,filter='data')\nprint('Source refreshed before paid launch')"),flush=True)
def launch():
    key=None
    for line in (REPO/'.env').read_text(encoding='utf-8-sig').splitlines():
        m=re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',line)
        if m:key=m[1].strip().strip('\"\'');break
    if not key:raise RuntimeError('Missing existing authorized OPENROUTER_API_KEY')
    r=subprocess.run(SSH+['/usr/bin/python3.11',REMOTE+'/package/launch_remote.py'],input=json.dumps({'key':key,'releaseTasks':240,'canaryTasks':10,'arms':4,'maximumSolverUsd':78}),capture_output=True,text=True,encoding='utf8',errors='replace',timeout=30)
    if key in r.stdout or key in r.stderr:raise RuntimeError('Unexpected credential in output; suppressed')
    print(r.stdout.strip());
    if r.stderr:print(r.stderr[-2000:],file=sys.stderr)
    if r.returncode:raise RuntimeError('LaunchFailed')
def pull():
    RESULTS.mkdir(parents=True,exist_ok=True)
    for name in ['status.json','launch.json','RUNNING.md','canary-audit.json','summary.json','REPORT.md','results.csv','provider-preflight.json','source-pins.json','controls/summary.json']:
        target=RESULTS/name;target.parent.mkdir(parents=True,exist_ok=True)
        r=subprocess.run(['scp','-q','novaeve:'+REMOTE+'/outputs/'+name,str(target)],capture_output=True,text=True,encoding='utf8',errors='replace',timeout=45)
        if r.returncode and name=='status.json':raise RuntimeError(r.stderr[-1000:])
    state=json.loads((RESULTS/'status.json').read_text());print(json.dumps(state,ensure_ascii=False))
    if state['stage'] not in ['complete','complete_with_exceptions','needs_attention']:return
    if (RESULTS/'retrieval.json').exists():
        prior=json.loads((RESULTS/'retrieval.json').read_text())
        if prior.get('sha256Verified') and prior.get('stage')==state['stage'] and prior.get('completeRecords')==state['completed']:return
    meta=json.loads(command(SSH+[REMOTE+'/runtime/bin/python',REMOTE+'/package/export.py'],timeout=600))
    archive=RESULTS/pathlib.PurePosixPath(meta['path']).name
    command(['scp','-q','novaeve:'+meta['path'],str(archive)],timeout=1200)
    with archive.open('rb') as f:got=hashlib.file_digest(f,'sha256').hexdigest()
    assert got==meta['sha256'] and archive.stat().st_size==meta['bytes']
    dest=RESULTS/'full-results';dest.mkdir(exist_ok=True)
    with tarfile.open(archive) as tar:tar.extractall(dest,filter='data')
    allrecords=list((dest/'outputs/tasks').glob('*/*/result.json'));assert len(allrecords)==meta['completeRecords']
    audited=command([sys.executable,str(SOURCE/'audit.py'),'--root',str(dest)],timeout=300)
    record={**meta,'localArchive':str(archive),'sha256Verified':True,'extractedResultRecords':len(allrecords),'localRoot':str(dest),'offlineAuditPassed':json.loads(audited)['allPassed']};(RESULTS/'retrieval.json').write_text(json.dumps(record,indent=2)+'\n');print(json.dumps(record))
if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['stage','refresh','controls','launch','pull']);a=p.parse_args();globals()[a.action]()
