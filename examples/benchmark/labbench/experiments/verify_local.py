"""Verify complete delivery using frozen rules and an independent file inventory."""
from pathlib import Path
import json
import re
import sys

REPO=Path(__file__).resolve().parents[4]


def main():
    # Read local ops constants before loading the delivered package modules.
    from ops import LOCAL
    metadata=json.loads((LOCAL/'retrieval.json').read_text(encoding='utf-8'));root=Path(metadata['fullResults'])
    sys.path.insert(0,str(root/'package'))
    from protocol import digest
    from report import audit
    result=audit()
    remote_approval=root/'outputs/canonical/formal-with-exceptions-approval.json'
    local_approval=LOCAL/'formal-with-exceptions-approval.json'
    if remote_approval.exists():
        if not local_approval.exists() or digest(remote_approval.read_bytes())!=digest(local_approval.read_bytes()):
            raise RuntimeError('TrustedLocalApprovalDoesNotMatchArchive')
        from acceptance_policy import apply_acceptance
        result=apply_acceptance(result,json.loads(local_approval.read_text(encoding='utf-8')),json.loads((root/'outputs/canonical/canary.json').read_text(encoding='utf-8')))
    checks=result['checks']
    archive=Path(metadata['archive'])
    checks.append({'name':'archive-sha256','passed':digest(archive.read_bytes())==metadata['sha256'] and archive.stat().st_size==metadata['bytes'] and metadata['twoEndsSha256Verified']})
    inventory=json.loads((root/'outputs/canonical/file-inventory.json').read_text(encoding='utf-8'))
    for rel,sha in inventory.items():checks.append({'name':'inventory:'+rel,'passed':(root/rel).is_file() and digest((root/rel).read_bytes())==sha})
    # The live credential is loaded only for this bounded absence check, never exported.
    credential=(REPO/'.env').read_text(encoding='utf-8-sig')
    match=re.search(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',credential,re.M)
    hits=[]
    if match:
        secret=match[1].strip().strip('\"\'').encode()
        if len(secret)>8:
            for path in root.rglob('*'):
                if not path.is_file():continue
                tail=b''
                with path.open('rb') as f:
                    for chunk in iter(lambda:f.read(1024*1024),b''):
                        data=tail+chunk
                        if secret in data:hits.append(path.relative_to(root).as_posix());break
                        tail=data[-len(secret):]
        checks.append({'name':'credential-absent-from-archive','passed':not hits,'hitFiles':hits})
    result={'allPassed':all(x['passed'] for x in checks),'checks':checks,'checkCount':len(checks),'failures':[x for x in checks if not x['passed']],'archiveSha256':metadata['sha256']}
    (LOCAL/'LOCAL_VERIFICATION.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    for name in ['SUMMARY.json','AUDIT.json','REPORT.md','FINAL_RESULTS.csv','TRAJECTORY_ANALYSIS.json']:(LOCAL/name).write_bytes((root/'outputs/canonical'/name).read_bytes())
    print(json.dumps({'allPassed':result['allPassed'],'checks':len(checks),'failures':result['failures'][:10]}))
    if not result['allPassed']:raise SystemExit(1)


if __name__=='__main__':main()
