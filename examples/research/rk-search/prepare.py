import json,hashlib,shutil,subprocess,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];HERE=Path(__file__).resolve().parent;BASE=ROOT/'data/rk-search';PREP=BASE/'preparation'
RUN=BASE/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'));RUN.mkdir()
for n in ['work','reference','verified','engine','requests','jobs','runtime','comparison']:(RUN/n).mkdir()
for n in ['GOAL.md','checker.py','independent_check.py','benchmarks.py','guard.py','run.ts','monitor.py']:shutil.copy2(HERE/n,RUN/n)
for n in ['baseline.json','baseline-audit.json','table8.html','paper.html']:shutil.copy2(PREP/n,RUN/'reference'/n)
for n in ['nodepy','RK-Opt']:shutil.copytree(PREP/n,RUN/'reference'/n,ignore=shutil.ignore_patterns('.git','__pycache__'))
shutil.copy2(PREP/'baseline.json',RUN/'work/candidate.json');shutil.copy2(PREP/'baseline.json',RUN/'best-verified.candidate.json')
shutil.copytree(ROOT/'app/src',RUN/'runtime/src');shutil.copy2(ROOT/'app/package.json',RUN/'runtime/package.json')
subprocess.run(['cmd','/c','mklink','/J',str(RUN/'runtime/node_modules'),str(ROOT/'app/node_modules')],check=True,capture_output=True)
patches={
 'llm/index.ts':[('export const HARD_WALL_MS = 900_000;','export const HARD_WALL_MS = 18_000_000;'),('out.finishReason !== "length" || round >= knobs.continueTimes','out.finishReason !== "length"')],
 'objective/tool.ts':[('if (spent >= here) {','if (false) {')],
 'tree/dfs.ts':[('return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);','return false; // Sole campaign budget is absolute time.'),('if (tried >= Number(a.task.max_dead_siblings ?? 3))','if (false)')],
 'engine/loop.ts':[('if (dead >= cap) {','if (false) {'),('if (used >= Number(cap.max_units)) {','if (false) {')],
 'trigger/data.ts':[('if (cap && n > Number(cap.max_units)) {','if (false) {')],
}
for n,changes in patches.items():
    p=RUN/'runtime/src'/n;s=p.read_text(encoding='utf-8')
    for old,new in changes:assert s.count(old)==1,(n,old);s=s.replace(old,new)
    p.write_text(s,encoding='utf-8')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
criteria={'stages':5,'storage':'Williamson 2N','order':3,'constraint_tolerance':'1e-50','minimum_absolute_improvement':'1e-25','uncertainty_multiplier':100,'stability_polynomial':'all coefficients frozen to exact baseline','primary':'NodePy order-four error-vector L2 norm','held_out_odes':'benchmarks.py; hidden from optimization','secondary':'coefficient conditioning and implemented-2N internal amplification, not primary acceptance thresholds'}
(RUN/'frozen-criteria.json').write_text(json.dumps(criteria,indent=2))
(RUN/'frozen-g.json').write_text(json.dumps({'files':{n:sha(RUN/n) for n in ['checker.py','independent_check.py','benchmarks.py','GOAL.md','frozen-criteria.json','reference/baseline.json','reference/baseline-audit.json']}},indent=2))
manifest={'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'sources':{n:subprocess.check_output(['git','rev-parse','HEAD'],cwd=PREP/n,text=True).strip() for n in ['nodepy','RK-Opt']},'python':sys.executable,'linux_environment':'/home/imontlaji/.local/share/objrun-quadrature-20261030-env','runtime_only_patches':patches,'runtime_hashes':{str(p.relative_to(RUN/'runtime/src')):sha(p) for p in (RUN/'runtime/src').rglob('*') if p.is_file()},'model':'deepseek/deepseek-v4.1-flash','paid_preflight':False,'clock_policy':'immutable first paid dispatch plus 18000 seconds','caps':'no monetary,token,iteration caps; finite engine schema fields are non-enforcing placeholders','shared_wsl':'not restarted; immutable scientific environment mounted read-only per namespace'}
(RUN/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
r=subprocess.run([sys.executable,str(RUN/'checker.py'),str(RUN/'work/candidate.json')],capture_output=True,text=True,check=True);audit=json.loads(r.stdout);assert audit['valid'],audit
(RUN/'baseline-audit.json').write_text(json.dumps(audit,indent=2));(RUN/'best-verified.json').write_text(json.dumps({k:v for k,v in audit.items() if k not in ['high_precision','independent']},indent=2))
(RUN/'requirements-lock.txt').write_bytes(subprocess.check_output([sys.executable,'-m','pip','freeze']))
(BASE/'latest-run.txt').write_text(str(RUN));print(RUN)
