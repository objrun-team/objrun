import hashlib,json,shutil,subprocess,sys
from pathlib import Path
from datetime import datetime,timezone
root=Path(__file__).resolve().parents[3];scripts=Path(__file__).resolve().parent
run=Path((root/'data/spherical-landscape/latest-run.txt').read_text().strip())
assert not (run/'deadline.json').exists(),'Preparation cannot reset an active campaign'
for name in ['engine','jobs','requests','verified','runtime','work/candidates']:(run/name).mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,str(scripts/'build_runner.py')],check=True)
for name in ['GOAL.md','checker.py','checker_selftest.py','audit_loop.py','guard.py','run.ts','monitor.py','finalize.py']:
    shutil.copy2(scripts/name,run/name)
shutil.copy2(scripts/'GOAL.md',run/'reference/GOAL.md')
shutil.copy2(scripts/'search_support.py',run/'work/search_support.py')
shutil.copy2(run/'reference/author-reference.json',run/'work/candidate.json')
baseline=json.loads((run/'baseline-audit.json').read_text())
summary={k:v for k,v in baseline.items() if k not in ['gram','perturbations','full_tangent_spectrum','quotient_spectrum']}
(run/'best-verified.json').write_text(json.dumps(summary,indent=2))
shutil.copytree(root/'app/src',run/'runtime/src',dirs_exist_ok=True)
shutil.copy2(root/'app/package.json',run/'runtime/package.json')
if not (run/'runtime/node_modules').exists():subprocess.run(['cmd','/c','mklink','/J',str(run/'runtime/node_modules'),str(root/'app/node_modules')],check=True,capture_output=True)
patches={
 'llm/index.ts':[('export const HARD_WALL_MS = 900_000;','export const HARD_WALL_MS = 18_000_000;'),('out.finishReason !== "length" || round >= knobs.continueTimes','out.finishReason !== "length"')],
 'objective/tool.ts':[('if (spent >= here) {','if (false) {')],
 'tree/dfs.ts':[('return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);','return false; // Absolute campaign deadline is the sole campaign budget.'),('if (tried >= Number(a.task.max_dead_siblings ?? 3))','if (false)')],
 'engine/loop.ts':[('if (dead >= cap) {','if (false) {'),('if (used >= Number(cap.max_units)) {','if (false) {')],
 'trigger/data.ts':[('if (cap && n > Number(cap.max_units)) {','if (false) {')],
}
for name,changes in patches.items():
    p=run/'runtime/src'/name;s=p.read_text(encoding='utf8')
    for old,new in changes:assert s.count(old)==1,(name,old);s=s.replace(old,new)
    p.write_text(s,encoding='utf8')
sha=lambda p:hashlib.sha256(p.read_bytes()).hexdigest()
(run/'runtime-manifest.json').write_text(json.dumps({'prepared_utc':datetime.now(timezone.utc).isoformat(),'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=root,text=True).strip(),'python':sys.executable,'linux_environment_readonly':'/home/imontlaji/.local/share/objrun-quadrature-20261030-env','source_hashes':{str(p.relative_to(root/'app/src')):sha(p) for p in (root/'app/src').rglob('*') if p.is_file()},'runtime_hashes':{str(p.relative_to(run/'runtime/src')):sha(p) for p in (run/'runtime/src').rglob('*') if p.is_file()},'runtime_only_patches':patches,'count_policy':'Count-based campaign stops disabled in private source snapshot. Finite schema fields only placeholders. Proxy omits output token limits.','applicable_AGENTS':'No AGENTS.md found in root ancestors or app/scripts subtrees; repository README and scripts/README.md read.','initial_git_status':subprocess.check_output(['git','status','--short'],cwd=root,text=True)},indent=2))
(run/'frozen-g.json').write_text(json.dumps({'frozen_utc':datetime.now(timezone.utc).isoformat(),'definition':{'d':6,'n':24,'unit_norm':True,'objective':'sum of all 576 Gram entries to fourth power minus 36'},'files':{n:sha(run/n) for n in ['checker.py','GOAL.md']},'criteria':{'norm':1e-12,'gradient':1e-9,'positive_gap':1e-6,'negative_curvature':-1e-7,'near_zero':1e-7,'non_global_energy_gap':1e-8},'checker_selftest_sha256':sha(run/'checker-selftest.json'),'baseline_audit_sha256':sha(run/'baseline-audit.json')},indent=2))
(run/'requirements-lock.txt').write_text(subprocess.check_output([sys.executable,'-m','pip','freeze'],text=True))
print(run)
