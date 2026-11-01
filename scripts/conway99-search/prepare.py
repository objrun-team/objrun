from pathlib import Path
import json,sys,shutil,subprocess,hashlib,datetime,urllib.request
ROOT=Path(__file__).resolve().parents[2]; HERE=Path(__file__).resolve().parent
RUN=ROOT/'data/conway99-search'/('run-'+datetime.datetime.now().strftime('%Y%m%d-%H%M%S'))
RUN.mkdir(parents=True,exist_ok=False)
for p in ('checker','reference','work/candidates','work/proofs','monitoring','jobs','requests','verified','engine','runtime','sources'):(RUN/p).mkdir(parents=True,exist_ok=True)
for name in ('check_pairs.py','check_matrix.py'):shutil.copy2(HERE/name,RUN/'checker'/name)
for name in ('GOAL.md','LITERATURE.md'):shutil.copy2(HERE/name,RUN/name);shutil.copy2(HERE/name,RUN/'reference'/name)
shutil.copytree(RUN/'checker',RUN/'reference/checker',dirs_exist_ok=True)
for name in ('rooted.py','test_checkers.py'):
    shutil.copy2(HERE/name,RUN/'reference'/name)
shutil.copy2(HERE/'rooted.py',RUN/'work/rooted.py')
sys.path.insert(0,str(HERE));from rooted import seed
(RUN/'work/seed.json').write_text(json.dumps({'matrix':seed(),'seed':20261031,'author':'host','kind':'unoptimized root scaffold'}))
shutil.copy2(RUN/'work/seed.json',RUN/'work/candidates/host-seed.json')
shutil.copytree(ROOT/'app/src',RUN/'runtime/src');shutil.copy2(ROOT/'app/package.json',RUN/'runtime/package.json')
# Link only dependencies; all runtime source and databases remain private.
subprocess.run(['cmd','/c','mklink','/J',str(RUN/'runtime/node_modules'),str(ROOT/'app/node_modules')],check=True,capture_output=True)
patches={
 'llm/index.ts':[('export const HARD_WALL_MS = 900_000;','export const HARD_WALL_MS = 18_000_000;'),('out.finishReason !== "length" || round >= knobs.continueTimes','out.finishReason !== "length"')],
 'objective/tool.ts':[('if (spent >= here) {','if (false) {')],
 'tree/dfs.ts':[('return nodes.filter((n) => n.cycle === cycle && Number(n.node) === node).length >= Number(cap.max_units);','return false; // Only absolute campaign deadline stops search.'),('if (tried >= Number(a.task.max_dead_siblings ?? 3))','if (false)')],
 'engine/loop.ts':[('if (dead >= cap) {','if (false) {'),('if (used >= Number(cap.max_units)) {','if (false) {')],
 'trigger/data.ts':[('if (cap && n > Number(cap.max_units)) {','if (false) {')]}
original={};modified={}
for name,changes in patches.items():
    src=(ROOT/'app/src'/name).read_text(encoding='utf-8');original[name]=hashlib.sha256(src.encode()).hexdigest()
    for a,b in changes:assert src.count(a)==1,(name,a);src=src.replace(a,b)
    (RUN/'runtime/src'/name).write_text(src,encoding='utf-8');modified[name]=hashlib.sha256(src.encode()).hexdigest()
hashes=lambda d:{p.relative_to(d).as_posix():hashlib.sha256(p.read_bytes()).hexdigest() for p in d.rglob('*') if p.is_file() and '__pycache__' not in p.parts}
manifest={'repository_head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),'snapshot_hashes':hashes(RUN/'runtime/src'),'patches':patches,'original_patch_hashes':original,'modified_patch_hashes':modified,'python':sys.executable,'linux_environment':'/home/imontlaji/.local/share/objrun-ca-20261030-env','policy':'No model preflight; first paid dispatch establishes deadline. No extra fee/token/iteration caps. Existing dependencies read-only.'}
(RUN/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
(RUN/'best-verified.json').write_text('{}')
(RUN/'contributions.json').write_text(json.dumps({'host':['literature audit','rooted algebraic reduction (prior art)','independent checker pair','small encoding tests','ObjRun isolation, proxy and deadline adapter','unoptimized rooted seed'],'model':'All ObjRun messages, tool commands and resulting files are recorded in engine SQLite, requests and jobs. Later changes recorded in monitoring/interventions.jsonl. No causal ObjRun performance claim.'},indent=2))
(RUN/'preparation.json').write_text(json.dumps({'applicable_AGENTS':'No AGENTS.md found in repository path ancestors or tracked source directories (rg including hidden, dependencies/data excluded).','run_instructions_read':['README.md','scripts/README.md','scripts/rna-bound-search/README.md','scripts/spherical-landscape/README.md','scripts/bench-runner/README.md'],'engine':'Real private app/src snapshot; open scientific campaign harness follows existing rna-bound-search, not Terminal-Bench/SkillsBench queue admission.','seed':20261031,'encoding':'rooted-v1','created':datetime.datetime.now(datetime.timezone.utc).isoformat()},indent=2))
(ROOT/'data/conway99-search/latest-run.txt').write_text(str(RUN))
print(RUN)
