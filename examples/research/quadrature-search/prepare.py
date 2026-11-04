import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
SCRIPTS=Path(__file__).resolve().parent
BASE=ROOT/'data/quadrature-search'
PREP=BASE/'preparation'
RUN=BASE/('run-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
RUN.mkdir(parents=True)
for name in ['work','reference','verified','jobs','requests','engine','runtime','comparison']:(RUN/name).mkdir()
for name in ['GOAL.md','RESEARCH.md','checker.py','independent_check.py','guard.py','run.ts','monitor.py']:
    shutil.copy2(SCRIPTS/name,RUN/name)
for name in ['diallo-prism-q7-n36.json','diallo-prism-q7-n36.audit.json','reproduction.json','openrouter-model.json','probe.request.json','probe.response.json']:
    shutil.copy2(PREP/name,RUN/'reference'/name)
for name in ['prior-prism-q7-n35.json','prior-prism-q7-n35.audit.json']:
    shutil.copy2(PREP/name,RUN/'comparison'/name)
shutil.copy2(RUN/'GOAL.md',RUN/'reference/GOAL.md')
shutil.copy2(RUN/'reference/diallo-prism-q7-n36.json',RUN/'work/candidate.json')
shutil.copy2(PREP/'diallo/data/published-results/pri/compact_hp/(degree,nodes)=(7,36).txt',RUN/'reference/diallo-compact.txt')
shutil.copy2(PREP/'diallo/data/published-results/pri/expanded_hp/(degree,nodes)=(7,36).csv',RUN/'reference/diallo-expanded.csv')
report=json.loads((PREP/'diallo-prism-q7-n36.audit.json').read_text())
assert report['valid'] and report['independent']['valid'] and report['size']==36
(RUN/'baseline-audit.json').write_text(json.dumps(report,indent=2))
summary={k:v for k,v in report.items() if k not in ('moments','independent')}
summary.update(source='published baseline',independent_valid=True)
(RUN/'best-verified.json').write_text(json.dumps(summary,indent=2))
shutil.copytree(ROOT/'app/src',RUN/'runtime/src')
shutil.copy2(ROOT/'app/package.json',RUN/'runtime/package.json')
subprocess.run(['cmd','/c','mklink','/J',str(RUN/'runtime/node_modules'),str(ROOT/'app/node_modules')],check=True,capture_output=True)
# Disable count-based stopping in this private snapshot, not merely a large cap.
# Required finite schema fields remain bookkeeping values, never termination criteria.
patches={
 'llm/index.ts':[
  ('export const HARD_WALL_MS = 900_000;','export const HARD_WALL_MS = 18_000_000;'),
  ('out.finishReason !== "length" || round >= knobs.continueTimes','out.finishReason !== "length"'),
 ],
 'objective/tool.ts':[('if (spent >= here) {','if (false) {')],
 'tree/dfs.ts':[
  ('return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);','return false; // Campaign uses only its absolute deadline.'),
  ('if (tried >= Number(a.task.max_dead_siblings ?? 3))','if (false)'),
 ],
 'engine/loop.ts':[
  ('if (dead >= cap) {','if (false) {'),
  ('if (used >= Number(cap.max_units)) {','if (false) {'),
 ],
 'trigger/data.ts':[('if (cap && n > Number(cap.max_units)) {','if (false) {')],
}
for name,changes in patches.items():
    path=RUN/'runtime/src'/name
    source=path.read_text(encoding='utf-8')
    for old,new in changes:
        assert source.count(old)==1,(name,old,source.count(old))
        source=source.replace(old,new)
    path.write_text(source,encoding='utf-8')
hashes=lambda directory:{str(p.relative_to(directory)):hashlib.sha256(p.read_bytes()).hexdigest() for p in directory.rglob('*') if p.is_file()}
(RUN/'runtime-manifest.json').write_text(json.dumps({
 'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
 'source_commits':{n:subprocess.check_output(['git','rev-parse','HEAD'],cwd=PREP/n,text=True).strip() for n in ('diallo','pinkse')},
 'snapshot_hashes':hashes(RUN/'runtime/src'),'runtime_only_patches':patches,
 'count_policy':'Finite schema fields are bookkeeping placeholders. All discovered count-based stop guards disabled in private runtime snapshot.',
 'request_policy':'Exact model only; omit max_tokens, max_completion_tokens, provider price ceilings; original campaign deadline is sole campaign budget.',
 'python':sys.executable,
 'linux_environment':'/home/imontlaji/.local/share/objrun-quadrature-20261030-env',
},indent=2))
(RUN/'frozen-g.json').write_text(json.dumps({'degree':7,'domain':'prism','weight':'Lebesgue 1','symmetry':'S3 x C2','tolerance':'1e-40','initial_threshold_exclusive':36,'files':{n:hashlib.sha256((RUN/n).read_bytes()).hexdigest() for n in ['checker.py','independent_check.py','GOAL.md']}},indent=2))
(BASE/'latest-run.txt').write_text(str(RUN),encoding='utf-8')
print(RUN)
