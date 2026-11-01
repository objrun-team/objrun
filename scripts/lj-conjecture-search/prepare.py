from pathlib import Path
import sys,json,shutil,subprocess,hashlib,datetime
ROOT=Path(__file__).resolve().parents[2];D=Path(__file__).resolve().parent
OLD=ROOT/'data/lj-bound-search/run-20261031T115203Z';BASE=ROOT/'data/lj-conjecture-search'
BASE.mkdir(exist_ok=True);pointer=BASE/'latest-run.txt'
if pointer.exists():RUN=Path(pointer.read_text().strip());assert not (RUN/'deadline.json').exists(),'Cannot reprepare a paid run'
else:
    RUN=BASE/('run-'+datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
    RUN.mkdir();pointer.write_text(str(RUN))
for n in ('work','checker','baseline','reference','verified','reviews','requests','jobs','engine','final','controller-sources'):(RUN/n).mkdir(exist_ok=True)
for n,h in json.loads((OLD/'frozen-g.json').read_text())['files'].items():assert hashlib.sha256((OLD/n).read_bytes()).hexdigest()==h
shutil.copytree(OLD/'reference',RUN/'reference',dirs_exist_ok=True,ignore=shutil.ignore_patterns('__pycache__'))
for n in ('proof','baseline'):
    shutil.copytree(OLD/n,RUN/'reference/prior-round'/n,dirs_exist_ok=True)
for n in ('check.py','replay.py'):shutil.copy2(OLD/'checker'/n,RUN/'checker'/('ball_'+n))
prior=json.loads((OLD/'best-verified.json').read_text())
shutil.copy2(prior['artifact'],RUN/'baseline/prior-candidate.json')
shutil.copy2(prior['certificate'],RUN/'baseline/prior-certificate.json')
shutil.copy2(OLD/'final/summary.json',RUN/'baseline/prior-summary.json')
for n in ('GOAL.md','CRITERIA.json'):
    shutil.copy2(D/n,RUN/n);shutil.copy2(D/n,RUN/'reference'/n)
shutil.copy2(D/'check.py',RUN/'checker/check.py')
shutil.copytree(RUN/'checker',RUN/'reference/round2-checker',dirs_exist_ok=True)
if not (RUN/'runtime/src').exists():
    shutil.copytree(OLD/'runtime/src',RUN/'runtime/src')
    shutil.copy2(ROOT/'app/package.json',RUN/'runtime/package.json')
    subprocess.run(['cmd','/c','mklink','/J',str(RUN/'runtime/node_modules'),str(ROOT/'app/node_modules')],check=True,capture_output=True)
def hashes(d):return {str(p.relative_to(d)).replace('\\','/'):hashlib.sha256(p.read_bytes()).hexdigest() for p in d.rglob('*') if p.is_file() and '__pycache__' not in str(p)}
manifest=json.loads((OLD/'runtime-manifest.json').read_text());manifest.update(repository_head=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),python=sys.executable,snapshot_hashes=hashes(RUN/'runtime/src'),prior_run=str(OLD),initial_user_changes=subprocess.check_output(['git','status','--short'],cwd=ROOT,text=True).splitlines(),source_snapshot_origin='Prior real ObjRun snapshot with elapsed-time-only patches, copied unmodified; frozen hashes match.')
(RUN/'runtime-manifest.json').write_text(json.dumps(manifest,indent=2))
for n in ('guard.py','finalize.py','linux_owned.py','supervisor.py','monitor.py'):
    if (D/n).exists():shutil.copy2(D/n,RUN/n)
frozen={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'files':{n:hashlib.sha256((RUN/n).read_bytes()).hexdigest() for n in ('GOAL.md','CRITERIA.json','checker/check.py','checker/ball_check.py','checker/ball_replay.py','baseline/prior-candidate.json','baseline/prior-certificate.json')},'success_policy':'Only >=1 / >1 universal proof or globally certified <1 counterexample; improved subunit bound is secondary.'}
(RUN/'frozen-g.json').write_text(json.dumps(frozen,indent=2))
(RUN/'best-verified.json').write_text(json.dumps({'primary_passed':False,'prior_lower_bound_exact':'347/500 * 2^(1/6)'}))
(RUN/'work/candidate.json').write_text('{"method":"calibration"}')
(RUN/'RUN_NOTES.md').write_text('''# Round2 LJ conjecture experiment

Primary goal now resolves r_min>=1 or gives globally certified r_min<1.
Strict >1 is separate. Merely improving .7789886615 is SECONDARY ONLY.
Read frozen GOAL.md/CRITERIA.json and prior-round materials. All old experiment
files preserved. Same exact OpenRouter model; first new paid dispatch starts
this new five-hour window. No paid preflight. Never reset/extend deadline.json.

Monitor every15 minutes via scripts/lj-conjecture-search/monitor.py. Check process
identity/CPU work, requests/receipts and immutable verified/bundles. Complete
primary claims require independent host mathematical review and independent
certificate replay, NOT just schema or model self-check. Protected review receipt
must match bundle SHA256 and both report hashes. Until then primary_passed=false.
For a genuine primary proof request, review promptly instead of waiting for15min.

supervisor.py is launched as an external controller before the runner; it owns
the immutable deadline guard and closeout, so stopping the engine/runner does not
kill the finalizer (fixes prior Windows process-lifetime issue). All Linux tools
remain private bwrap namespaces, exact-path stop only. Never restart shared WSL.

At success or expiry stop ALL owned model requests/solver processes; finalize.py
rechecks existing bundles and prior proof, accounts every API receipt, then the
host heartbeat must delete its monitoring automation and write cleanup receipt.
After cutoff verification/closeout only, no research search or paid requests.
No fees/token/iteration total caps and no purchased compute. Do not expose .env,
engine/config.yaml or API keys. Do not publish. Copy all model code/seeds/coords,
proofs/certificates, source versions, trajectories and receipts into this run.
Host contributions and fixed-model contributions must remain separately recorded.
''',encoding='utf-8')
# Text counterpart for fast model reading; retain original HTML bytes too.
try:
    from bs4 import BeautifulSoup
    p=RUN/'reference/kiessling-wales-2511.15008.html'
    (p.with_suffix('.txt')).write_text(BeautifulSoup(p.read_text(encoding='utf-8'),'html.parser').get_text('\n'),encoding='utf-8')
except ImportError:pass
print(RUN)
