"""Local health ledger every 15 minutes; final replay survives chat scheduling."""
import sys,json,time,subprocess,hashlib
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[3];SCRIPTS=Path(__file__).resolve().parent
run=Path(sys.argv[1]);out=run/'monitoring';out.mkdir(exist_ok=True)
deadline=json.loads((run/'deadline.json').read_text())['deadline_epoch']
def linux(p):return '/mnt/'+str(p)[0].lower()+str(p)[2:].replace('\\','/')
def snapshot():
 now=datetime.now(timezone.utc);stamp=now.strftime('%Y%m%dT%H%M%SZ')
 p=subprocess.run([sys.executable,str(SCRIPTS/'monitor.py'),str(run)],capture_output=True,text=True,encoding='utf-8',timeout=30)
 try:r=json.loads(p.stdout)
 except ValueError:r={'monitor_error':p.stderr,'stdout':p.stdout}
 q=subprocess.run(['wsl','-d','Ubuntu','--','python3',linux(SCRIPTS/'namespace_health.py'),'rna-bound-search-run-20261030-a'],capture_output=True,text=True,timeout=30)
 try:r['linux_namespaces']=json.loads(q.stdout)
 except ValueError:r['linux_health_error']=q.stderr
 r['candidate_files']=[{'path':str(f.relative_to(run)),'bytes':f.stat().st_size,'mtime':f.stat().st_mtime} for f in (run/'work').glob('*.json')]
 r['checker_integrity']={n:hashlib.sha256((run/n).read_bytes()).hexdigest()==h for n,h in json.loads((run/'frozen-g.json').read_text())['files'].items()}
 (out/(stamp+'.json')).write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8')
 (out/'latest.json').write_text(json.dumps(r,indent=2,ensure_ascii=False),encoding='utf-8')
snapshot()
next_check=time.time()+900
while time.time()<deadline:
 time.sleep(min(1,max(.01,deadline-time.time()),max(.01,next_check-time.time())))
 if time.time()>=next_check and time.time()<deadline:
  try:snapshot()
  except Exception as e:(out/'watchdog-errors.jsonl').open('a').write(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'error':str(e)})+'\n')
  next_check+=900
# Allow the independent guard and namespace supervisors to complete their stop.
time.sleep(3)
q=subprocess.run([sys.executable,str(SCRIPTS/'finalize.py'),str(run)],capture_output=True,text=True,encoding='utf-8')
(out/'automatic-finalization.stdout.log').write_text(q.stdout,encoding='utf-8')
(out/'automatic-finalization.stderr.log').write_text(q.stderr,encoding='utf-8')
(out/'automatic-finalization.json').write_text(json.dumps({'utc':datetime.now(timezone.utc).isoformat(),'returncode':q.returncode},indent=2))
try:snapshot()
except Exception:pass
