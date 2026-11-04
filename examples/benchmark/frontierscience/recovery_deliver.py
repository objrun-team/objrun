"""Transfer offline closeout material separately; never edits either frozen run package."""
from pathlib import Path
import csv
import hashlib
import json
import re
import shutil
import tarfile
import recovery_ops as ops

read=lambda p:json.loads(p.read_text(encoding='utf-8'))
sha=lambda b:hashlib.sha256(b).hexdigest()

def main():
    local=ops.LOCAL;original=ops.REPO/'docs/frontierscience'/ops.ORIGINAL
    for folder in [local,original]:assert read(folder/'LOCAL_VERIFICATION.json')['allPassed']
    combined=read(local/'COMBINED_SUMMARY.json');assert all(x['allPassed'] for x in combined['verification'].values())
    rows=list(csv.DictReader((local/'COMBINED_RESULTS.csv').open(encoding='utf-8-sig')))
    ids=read(original/'full-results/data/source.json')['ids']
    assert len(rows)==200 and {(r['arm'],r['id']) for r in rows}=={(a,i) for a in ['baseline','objrun'] for i in ids}
    manifest=read(local/'recovery-manifest.json');selected={(e['arm'],e['id']) for e in manifest['entries'] if e['action'] in {'objrun_once','score_once'}}
    assert {tuple((r['arm'],r['id'])) for r in rows if r['appliedSource']=='recovery-round-1'}==selected
    for row in rows:
        batch=local if row['appliedSource']=='recovery-round-1' else original
        frozen=read(batch/'full-results/outputs/canonical/final-results'/row['arm']/(row['id']+'.json'))
        assert row['appliedCandidateSha256']==frozen['candidateSha256']
    stage=local/'delivery-materials';stage.mkdir(exist_ok=True)
    names=['FINAL_REPORT.md','COMBINED_SUMMARY.json','COMBINED_RESULTS.csv','CASE_REVIEW.json','DELIVERY_README.md','recovery-manifest.json',
           'LOCAL_VERIFICATION-initial.json','AUDITOR_CORRECTIONS.json']
    for name in names:shutil.copy2(local/name,stage/name)
    for label,folder in [('original',original),('recovery',local)]:
        d=stage/label;d.mkdir(exist_ok=True)
        for name in ['LOCAL_VERIFICATION.json','retrieval.json','connection.json']:
            shutil.copy2(folder/name,d/name)
        for name in ['source-pins.json','status.json','controls.json','SUMMARY.json']:
            shutil.copy2(folder/'full-results/outputs/canonical'/name,d/name)
    scripts=stage/'offline-and-ops-source';scripts.mkdir(exist_ok=True)
    for p in Path(__file__).parent.iterdir():
        if p.suffix in {'.py','.ts'}:shutil.copy2(p,scripts/p.name)
    credential_text=(ops.REPO/'.env').read_text(encoding='utf-8-sig')
    match=re.search(r'^\s*(?:export\s+)?DEEPSEEK_API_KEY\s*=\s*(.*?)\s*$',credential_text,re.M)
    if not match:raise RuntimeError('CannotVerifyCredentialAbsence')
    secret=match[1].strip().strip('\"\'').encode()
    files={}
    for p in stage.rglob('*'):
        if p.is_file() and p.name!='FILES.json':
            raw=p.read_bytes();assert secret not in raw,'CredentialLeakSuppressed'
            files[p.relative_to(stage).as_posix()]={'sha256':sha(raw),'bytes':len(raw)}
    (stage/'FILES.json').write_text(json.dumps(files,indent=2)+'\n',encoding='utf-8')
    archive=local/'frontierscience-delivery.tar.gz'
    if not archive.exists():
        with tarfile.open(archive,'w:gz') as tar:tar.add(stage,arcname='delivery')
    else:
        with tarfile.open(archive) as tar:
            assert json.load(tar.extractfile('delivery/FILES.json'))==files,'ExistingDeliveryWouldChange'
    digest=sha(archive.read_bytes());size=archive.stat().st_size
    preflight=json.loads(ops.remote(ops.guard_code()+f"""import json,hashlib
r=Path({ops.REMOTE!r});meta=json.loads((r/'data/recovery-manifest.json').read_text())
original=guard({ops.ORIGIN!r},meta['originalArchiveSha256'])
a=r/{archive.name!r}
if a.exists():assert hashlib.sha256(a.read_bytes()).hexdigest()=={digest!r},'ExistingDeliveryDifferent'
print(json.dumps({{'original':original,'alreadyUploaded':a.exists()}}))
"""))
    if not preflight['alreadyUploaded']:ops.scp(archive,'novaeve:'+ops.REMOTE+'/'+archive.name)
    receipt=json.loads(ops.remote(ops.guard_code()+f"""import hashlib,json,tarfile
r=Path({ops.REMOTE!r});a=r/{archive.name!r}
assert hashlib.sha256(a.read_bytes()).hexdigest()=={digest!r} and a.stat().st_size=={size}
with tarfile.open(a) as t:t.extractall(r,filter='data')
files=json.loads((r/'delivery/FILES.json').read_text())
for rel,meta in files.items():
 p=r/'delivery'/rel;assert hashlib.sha256(p.read_bytes()).hexdigest()==meta['sha256'] and p.stat().st_size==meta['bytes']
actual={{p.relative_to(r/'delivery').as_posix() for p in (r/'delivery').rglob('*') if p.is_file() and p.name!='FILES.json'}}
assert actual==set(files)
for p in Path('/proc').glob('[0-9]*/cmdline'):
 try:raw=p.read_bytes()
 except OSError:continue
 assert str(r).encode() not in raw,'RecoveryOwnedProcessStillLive'
out=r/'outputs/canonical'
assert not [p for p in (out/'calls').glob('**/dispatch.json') if not p.with_name('receipt.json').exists()]
assert not [p for p in (out/'jobs').glob('*/*.json') if not (out/'judgments'/p.parent.name/p.name).exists()]
recarchive=r/(r.name+'-results.tar.gz');recsha=hashlib.sha256(recarchive.read_bytes()).hexdigest()
assert recsha=={read(local/'retrieval.json')['sha256']!r}
print(json.dumps({{'deliveryArchiveSha256':{digest!r},'deliveryArchiveBytes':{size},'filesVerified':len(files),'original':guard({ops.ORIGIN!r},{manifest['originalArchiveSha256']!r}),
                  'recoveryArchiveSha256':recsha,'ownedRecoveryProcessesLive':[],'paidRequestsDrained':True,'remoteDirectory':str(r/'delivery')}}))
"""))
    receipt.update(twoEndsSha256Verified=True,localArchive=str(archive),originalLocalChecks=read(original/'LOCAL_VERIFICATION.json')['checks'],
                   recoveryLocalChecks=read(local/'LOCAL_VERIFICATION.json')['checks'],candidateMap200Verified=True,caseReviewCompleted=True,
                   recoveryRoundLimitReached=True,remainingExceptions=read(local/'full-results/outputs/canonical/status.json')['remainingExceptions'])
    (local/'CLOSEOUT.json').write_text(json.dumps(receipt,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(receipt))

if __name__=='__main__':main()
