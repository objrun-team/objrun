"""Isolated adaptation of the existing, real ObjRun five-hour harness."""
from pathlib import Path
import json,sys,shutil,subprocess,hashlib
ROOT=Path(__file__).resolve().parents[2]
SCRIPTS=Path(__file__).resolve().parent
RUN=ROOT/'data/rna-bound-search/run-20261030-a'
BASE=ROOT/'data/rna-bound-search'
assert not (RUN/'deadline.json').exists(),'do not prepare over a started run'
for n in ('jobs','requests','verified','engine','runtime'):(RUN/n).mkdir(exist_ok=True)
if not (RUN/'runtime/src').exists():
 shutil.copytree(ROOT/'app/src',RUN/'runtime/src')
 shutil.copy2(ROOT/'app/package.json',RUN/'runtime/package.json')
 subprocess.run(['cmd','/c','mklink','/J',str(RUN/'runtime/node_modules'),str(ROOT/'app/node_modules')],check=True,capture_output=True)
patches={
 'llm/index.ts':[('export const HARD_WALL_MS = 900_000;','export const HARD_WALL_MS = 18_000_000;'),('out.finishReason !== "length" || round >= knobs.continueTimes','out.finishReason !== "length"')],
 'objective/tool.ts':[('if (spent >= here) {','if (false) {')],
 'tree/dfs.ts':[('return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);','return false; // Sole campaign budget is elapsed time.'),('if (tried >= Number(a.task.max_dead_siblings ?? 3))','if (false)')],
 'engine/loop.ts':[('if (dead >= cap) {','if (false) {'),('if (used >= Number(cap.max_units)) {','if (false) {')],
 'trigger/data.ts':[('if (cap && n > Number(cap.max_units)) {','if (false) {')],
}
for name,changes in patches.items():
 src=(ROOT/'app/src'/name).read_text(encoding='utf-8')
 for old,new in changes:assert src.count(old)==1,(name,old);src=src.replace(old,new)
 (RUN/'runtime/src'/name).write_text(src,encoding='utf-8')
hashes=lambda d:{str(p.relative_to(d)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in d.rglob('*') if p.is_file()}
manifest={'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'snapshot_hashes':hashes(RUN/'runtime/src'),'runtime_only_patches':patches,'python':sys.executable,'linux_environment':'/home/imontlaji/.local/share/objrun-rna-20261030-env','count_policy':'Count-based stopping guards disabled in private snapshot; finite schema bookkeeping only. Task time placeholders do not extend the absolute host/namespace deadline.','request_policy':'Exact fixed model; no output-token or price ceilings; no paid preflight; first dispatch starts five hours.'}
(RUN/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
# The model sees read-only references, including a copy of the frozen checker.
for n in ('targets-frozen.json','GOAL.md'):shutil.copy2(RUN/n,RUN/'reference'/n)
for directory in ('checker','baseline'):
 shutil.copytree(RUN/directory,RUN/'reference'/directory,dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__','checker-tests'))
frozen={'files':{**{n:hashlib.sha256((RUN/n).read_bytes()).hexdigest() for n in ('targets-frozen.json','GOAL.md')},**{'checker/'+n:h for n,h in hashes(RUN/'checker').items() if '__pycache__' not in n}}}
(RUN/'frozen-g.json').write_text(json.dumps(frozen,indent=2))
(BASE/'latest-run.txt').write_text(str(RUN))
if not (RUN/'best-verified.json').exists():(RUN/'best-verified.json').write_text('{}')
# Trivial bound-one preflight is genuine and exercises the independent checker
# without searching or relying on the author cache.
if not (RUN/'work/candidate.json').exists():(RUN/'work/candidate.json').write_text('{"target_id":"52","components":[]}')
print(RUN)
