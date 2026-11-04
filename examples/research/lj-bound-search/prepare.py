from pathlib import Path
import json,sys,shutil,subprocess,hashlib,datetime
ROOT=Path(__file__).resolve().parents[3];SCRIPTS=Path(__file__).resolve().parent
RUN=Path((ROOT/'data/lj-bound-search/latest-run.txt').read_text().strip())
assert not (RUN/'deadline.json').exists()
for name in ('check.py','replay.py'):
    shutil.copy2(SCRIPTS/name,RUN/'checker'/name)
for name in ('GOAL.md','PROOF_FAMILY.md'):
    shutil.copy2(SCRIPTS/name,RUN/name);shutil.copy2(SCRIPTS/name,RUN/'reference'/name)
shutil.copytree(RUN/'checker',RUN/'reference/checker',dirs_exist_ok=True)
shutil.copytree(RUN/'baseline',RUN/'reference/baseline',dirs_exist_ok=True)
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
def hashes(d):return {str(p.relative_to(d)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in d.rglob('*') if p.is_file() and '__pycache__' not in str(p)}
manifest={'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'original_source_hashes':hashes(ROOT/'app/src'),'snapshot_hashes':hashes(RUN/'runtime/src'),'runtime_only_patches':patches,'python':sys.executable,'linux_environment':'/home/imontlaji/.local/share/objrun-lj-20261031-env','count_policy':'Count-based stop guards disabled in private snapshot; finite schema maxima are bookkeeping only. Sole budget is original absolute five-hour deadline.','request_policy':'Exact fixed model; no output-token or price ceilings; first paid dispatch starts clock.','shared_files_changed':False,'initial_user_changes':['site/app.js','site/home.css','site/index.html','site/media/','site/tools/scroll-check.cjs']}
(RUN/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
frozen={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':{n:hashlib.sha256((RUN/n).read_bytes()).hexdigest() for n in ('GOAL.md','PROOF_FAMILY.md','baseline/reference.json','baseline/original-average-certificate.json','baseline/small-N-calibration.json','checker/check.py','checker/replay.py')},'success_policy':'exact all-N bound above unrounded existing implication and independent replay; alternate methods require host proof review'}
(RUN/'frozen-g.json').write_text(json.dumps(frozen,indent=2))
(RUN/'best-verified.json').write_text('{}')
(RUN/'work/candidate.json').write_text(json.dumps({'method':'ball_average_v1','a':'0.684','b':'0.684','cutoff':'0.64','particle_minus_energy':0}))
for name in ('guard.py','finalize.py'):
    if (SCRIPTS/name).exists():shutil.copy2(SCRIPTS/name,RUN/name)
print(RUN)
