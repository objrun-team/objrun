"""Bounded-policy operations. No entry point can launch the unlimited runner."""
from pathlib import Path
import hashlib
import json
import sys
import tarfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recovery'))
import ops_recovery as old
from core import read, save, sha, now, NAME

LOCAL, REMOTE = old.LOCAL, old.REMOTE


def pull():
    files = json.loads(old.remote(f'''from pathlib import Path
import json
r=Path({REMOTE!r});v={{}}
for name in ['status.json','launch.json','first-valid.json','FINAL_DISPOSITIONS.json','bounded-controller-done.json','bounded-controls.json','AUDIT.json','SUMMARY.json','final-freeze.json','bounded-operations-pins.json','bounded-report-pins.json']:
 p=r/name
 if p.exists():v[name]=p.read_text()
for name in ['bounded-controller.stderr.log','controller.stderr.log']:
 p=r/name
 if p.exists():v[name]=p.read_text()[-8000:]
print(json.dumps(v))
'''))
    for name, content in files.items():
        (LOCAL / name).write_bytes(content.encode())
    status = read(LOCAL / 'status.json')
    print(json.dumps(status), flush=True)
    return status


def finalize():
    result = json.loads(old.remote(f'''from pathlib import Path
import sys,json,time
r=Path({REMOTE!r});s=json.loads((r/'status.json').read_text());assert s['stage'] in ['bounded_ready_for_report','complete','needs_attention'] and not s['active'];assert json.loads((r/'bounded-controller-done.json').read_text())['resolvedCount']==8
owner=json.loads((r/'launch.json').read_text())['pid'];p=Path('/proc')/str(owner)/'cmdline';assert not p.exists() or not p.read_bytes(),'ControllerStillAlive'
for home in (r/'attempts').glob('*/*/attempt-*'):
 assert (home/'terminal.json').exists()
 process=json.loads((home/'worker-process.json').read_text());cmd=Path('/proc')/str(process['pid'])/'cmdline'
 assert not cmd.exists() or str(home).encode() not in cmd.read_bytes(),'WorkerStillAlive'
sys.path.insert(0,str(r/'operations-bounded'));sys.path.insert(0,str(r/'operations'));import report_bounded
audit,result=report_bounded.generate(r);assert audit['allPassed']
from core import save,now,sha
save(r/'final-freeze.json',{{'atUtc':now(),'resolvedCount':8,'firstValidCount':result['firstValidCount'],'auditPassed':True,'policySha256':sha(r/'control/final-attempt-policy.json')}},not (r/'final-freeze.json').exists())
s.update(stage='complete',atUtc=now(),resolvedCount=8,selectedCount=result['firstValidCount']);save(r/'status.json',s)
print(json.dumps({{'auditPassed':True,'checks':audit['checkCount'],'resolvedCount':8,'firstValidCount':result['firstValidCount'],'attemptCount':result['attemptCount'],'finalScored':result['finalScored']['arms'],'fees':result['fees']}}))
''', 600))
    save(LOCAL / 'finalization.json', result)
    print(json.dumps(result), flush=True)


def retrieve():
    receipt = json.loads(old.remote(f'''from pathlib import Path
import json,hashlib,tarfile
r=Path({REMOTE!r});assert json.loads((r/'status.json').read_text())['stage']=='complete';assert json.loads((r/'AUDIT.json').read_text())['allPassed'];assert json.loads((r/'final-freeze.json').read_text())['resolvedCount']==8
owner=json.loads((r/'launch.json').read_text())['pid'];p=Path('/proc')/str(owner)/'cmdline';assert not p.exists() or not p.read_bytes(),'ControllerStillWriting'
for home in (r/'attempts').glob('*/*/attempt-*'):
 assert (home/'terminal.json').exists();worker=json.loads((home/'worker-process.json').read_text())['pid'];p=Path('/proc')/str(worker)/'cmdline';assert not p.exists() or str(home).encode() not in p.read_bytes(),'WorkerStillWriting'
a=Path({old.NAS!r})/({NAME!r}+'-bounded-final-results.tar.gz')
if not a.exists():
 inventory={{x.relative_to(r).as_posix():hashlib.sha256(x.read_bytes()).hexdigest() for x in r.rglob('*') if x.is_file() and x.name!='file-inventory-recovery.json'}}
 (r/'file-inventory-recovery.json').write_bytes((json.dumps(inventory,indent=2)+'\\n').encode());temp=a.with_suffix('.partial');assert not temp.exists(),'ExistingArchivePartial'
 with tarfile.open(temp,'w:gz',dereference=True) as tar:
  for x in sorted(r.iterdir()):tar.add(x,arcname=x.name,filter=lambda v:None if '.env' in Path(v.name).parts else v)
 temp.rename(a)
h=hashlib.sha256()
with a.open('rb') as stream:
 for b in iter(lambda:stream.read(1024*1024),b''):h.update(b)
print(json.dumps({{'remoteArchive':str(a),'sha256':h.hexdigest(),'bytes':a.stat().st_size}}))
''', 600))
    archive = LOCAL / Path(receipt['remoteArchive']).name
    if not archive.exists():
        temp = archive.with_name(archive.name + '.download.partial')
        assert not temp.exists(), 'ExistingDownloadPartial'
        old.scp('novaeve:' + receipt['remoteArchive'], temp, 600)
        assert sha(temp) == receipt['sha256']
        temp.rename(archive)
    assert sha(archive) == receipt['sha256'] and archive.stat().st_size == receipt['bytes']
    out = LOCAL / 'full-results'
    if not out.exists():
        temp = LOCAL / 'full-results.extracting'
        assert not temp.exists(), 'ExistingExtractionPartial'
        temp.mkdir()
        with tarfile.open(archive) as tar:
            tar.extractall(temp, filter='data')
        temp.rename(out)
    receipt.update(archive=str(archive), fullResults=str(out), twoEndsSha256Verified=True)
    save(LOCAL / 'retrieval.json', receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == '__main__':
    {'pull': pull, 'finalize': finalize, 'retrieve': retrieve}[sys.argv[1]]()
