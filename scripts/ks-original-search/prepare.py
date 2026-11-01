import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[2];scripts=Path(__file__).resolve().parent
run=Path((root/'data/ks-original-search/latest-run.txt').read_text().strip())
assert not (run/'deadline.json').exists(),'Cannot prepare or reset a started campaign'
for n in ['engine','jobs','requests','verified','runtime','work/candidates']:(run/n).mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,str(scripts/'build_runner.py')],check=True)
for name in ['GOAL.md','checker.py','independent.py','audit_loop.py','guard.py','linux_stop.py','run.ts','monitor.py','finalize.py','search_support.py','baseline_selftest.py']:
    shutil.copy2(scripts/name,run/name)
shutil.copy2(scripts.parent/'spherical-landscape/linux_cpu_snapshot.py',run/'linux_cpu_snapshot.py')
shutil.copy2(root/'artifacts/ks-original-search/literature-20261031.md',run/'reference/RESEARCH.md')
for name in ['GOAL.md','checker.py','independent.py']:shutil.copy2(run/name,run/'reference'/name)
shutil.copy2(scripts/'search_support.py',run/'work/search_support.py')
shutil.copy2(run/'reference/ck31.json',run/'work/candidate.json')
shutil.copy2(run/'baseline-audit.json',run/'reference/baseline-audit.json')
baseline=json.loads((run/'baseline-audit.json').read_text());baseline['artifact']=str(run/'reference/ck31.json')
(run/'best-verified.json').write_text(json.dumps(baseline,indent=2))
shutil.copytree(root/'app/src',run/'runtime/src',dirs_exist_ok=True);shutil.copy2(root/'app/package.json',run/'runtime/package.json')
if not (run/'runtime/node_modules').exists():subprocess.run(['cmd','/c','mklink','/J',str(run/'runtime/node_modules'),str(root/'app/node_modules')],check=True,capture_output=True)
patches={
 'llm/index.ts':[('export const HARD_WALL_MS = 900_000;','export const HARD_WALL_MS = 18_000_000;'),('out.finishReason !== "length" || round >= knobs.continueTimes','out.finishReason !== "length"')],
 'objective/tool.ts':[('if (spent >= here) {','if (false) {')],
 'tree/dfs.ts':[('return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);','return false; // Fixed absolute campaign deadline is the only budget.'),('if (tried >= Number(a.task.max_dead_siblings ?? 3))','if (false)')],
 'engine/loop.ts':[('if (dead >= cap) {','if (false) {'),('if (used >= Number(cap.max_units)) {','if (false) {')],
 'trigger/data.ts':[('if (cap && n > Number(cap.max_units)) {','if (false) {')],
}
for name,changes in patches.items():
    p=run/'runtime/src'/name;s=p.read_text(encoding='utf-8')
    for old,new in changes:assert s.count(old)==1,(name,old);s=s.replace(old,new)
    p.write_text(s,encoding='utf-8')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
manifest={'prepared_utc':datetime.now(timezone.utc).isoformat(),'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'python':sys.executable,'linux_environment_readonly':'/home/imontlaji/.local/share/objrun-ca-20261030-env','source_hashes':{str(p.relative_to(root/'app/src')):sha(p) for p in (root/'app/src').rglob('*') if p.is_file()},'runtime_hashes':{str(p.relative_to(run/'runtime/src')):sha(p) for p in (run/'runtime/src').rglob('*') if p.is_file()},'runtime_only_patches':patches,'count_policy':'Count guards disabled in private snapshot; finite fields bookkeeping only. Request output caps removed. No cost cap.','applicable_AGENTS':'No AGENTS.md in root ancestors or app/scripts/data subtrees. README and scripts README read.','initial_git_status':subprocess.check_output(['git','status','--short'],cwd=root,text=True),'attribution':{'host':'literature, coordinates reproduced from author rule, optional integer MUS seed, separate exact checker implementations, infrastructure and supervision','model':'decisions, authored scripts and tool invocations saved in ObjRun DB and requests; host seed invocations distinguishable','existing_tools':'ObjRun runtime, PySAT solvers, SymPy and scientific Python, Bun/SQLite, bubblewrap'}}
(run/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
(run/'frozen-g.json').write_text(json.dumps({'frozen_utc':datetime.now(timezone.utc).isoformat(),'definition':'original KS in real R3; all exact orthogonal pairs at most 1, all orthogonal triples exactly 1','baseline_n':31,'target_max_n':30,'literature_review':'reference/RESEARCH.md','files':{n:sha(run/n) for n in ['checker.py','independent.py','GOAL.md','reference/RESEARCH.md','reference/ck31.json']},'checker_selftest_sha256':sha(run/'checker-selftest.json'),'baseline_audit_sha256':sha(run/'baseline-audit.json')},indent=2))
(run/'requirements-host.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True))
(run/'requirements-linux.txt').write_text(subprocess.check_output(['wsl','-d','Ubuntu','--','/home/imontlaji/.local/share/objrun-ca-20261030-env/bin/python','-m','pip','freeze'],text=True))
print(run)
