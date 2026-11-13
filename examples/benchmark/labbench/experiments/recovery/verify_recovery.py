"""Independent local audit and original/completed delivery; never calls a model."""
from pathlib import Path
import json
import re
from ops_recovery import LOCAL,ORIGINAL_LOCAL,REPO
from core import read,save,sha
from report_recovery import generate

def main():
    meta=read(LOCAL/'retrieval.json');root=Path(meta['fullResults']);checks=[]
    def check(name,value):checks.append({'name':name,'passed':bool(value)})
    check('recovery-archive-two-ends',meta['twoEndsSha256Verified'] and sha(meta['archive'])==meta['sha256'] and Path(meta['archive']).stat().st_size==meta['bytes'])
    check('trusted-new-authorization', (LOCAL/'authorization.json').read_bytes()==(root/'authorization.json').read_bytes() and read(root/'authorization.json')['retryUntilFirstValid'])
    parent=read(ORIGINAL_LOCAL/'retrieval.json');original_proof=read(ORIGINAL_LOCAL/'LOCAL_VERIFICATION.json')
    check('original-verified-archive-unchanged',original_proof['allPassed'] and sha(parent['archive'])==parent['sha256']==read(root/'recovery.json')['originalArchiveSha256'])
    old_inventory=read(Path(parent['fullResults'])/'outputs/canonical/file-inventory.json')
    for p in (root/'original-reference/results').glob('*/*.json'):
        rel='outputs/canonical/results/'+p.parent.name+'/'+p.name;check('original-record:'+rel,sha(p)==old_inventory[rel])
    inventory=read(root/'file-inventory-recovery.json')
    for n,(rel,h) in enumerate(inventory.items(),1):
        check('inventory:'+rel,(root/rel).is_file() and sha(root/rel)==h)
        if n%2000==0:print(json.dumps({'inventoryChecked':n,'total':len(inventory)}),flush=True)
    audit,result=generate(root,local=True);checks.extend(audit['checks'])
    server=read(root/'SUMMARY.json');check('independent-completed-stats',result['completed']['arms']==server['completed']['arms'] and result['completed']['categories']==server['completed']['categories'])
    check('independent-first-valid-provenance',result['recoverySources']==server['recoverySources'])
    for arm,g in result['fees']['allRecoveryAttempts']['byArm'].items():
        other=server['fees']['allRecoveryAttempts']['byArm'][arm];check('independent-fees:'+arm,abs(g['knownActualCostUsd']-other['knownActualCostUsd'])<1e-9 and g['unknownCostRequests']==other['unknownCostRequests'] and g['requests']==other['requests'])
    env=(REPO/'.env').read_text(encoding='utf-8-sig');m=re.search(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$',env,re.M);assert m
    secret=m[1].strip().strip('\"\'').encode();assert len(secret)>8;hits=[]
    for n,p in enumerate((p for p in root.rglob('*') if p.is_file()),1):
        tail=b''
        with p.open('rb') as stream:
            for chunk in iter(lambda:stream.read(1024*1024),b''):
                data=tail+chunk
                if secret in data:hits.append(p.relative_to(root).as_posix());break
                tail=data[-len(secret):]
        if n%5000==0:print(json.dumps({'credentialAbsenceFilesScanned':n}),flush=True)
    check('credential-absent',not hits)
    proof={'allPassed':all(c['passed'] for c in checks),'checkCount':len(checks),'checks':checks,'failures':[c for c in checks if not c['passed']],'archiveSha256':meta['sha256']}
    save(LOCAL/'LOCAL_VERIFICATION.json',proof)
    assert proof['allPassed'],proof['failures'][:10]
    save(LOCAL/'INDEPENDENT_SUMMARY.json',result)
    for name in ['SUMMARY.json','ORIGINAL_RESULTS.csv','COMPLETED_RESULTS.csv','REPLACEMENT_PROVENANCE.json']:(LOCAL/name).write_bytes((root/name).read_bytes())
    lines=['# LAB-Bench original experiment and first-valid recovery results','','The original experiment is fully preserved. Only the original 8 infrastructure failures receive fresh 600-second attempts, using the first valid result to fill gaps. A valid wrong answer, format failure, or normal budget exhaustion immediately stops that identity.','', '|Result view|Task set|Arm|Passed/total|Unknowns|Accuracy bounds|','|---|---|---|---:|---:|---|']
    for view in ['original','completed']:
        for category,arms in list(result[view]['categories'].items())+[('All',result[view]['arms'])]:
            for arm,s in arms.items():lines.append(f"|{view}|{category}|{arm}|{s['passed']}/{s['tasks']}|{s['unknown']}|{s['accuracyBounds'][0]*100:.2f}%–{s['accuracyBounds'][1]*100:.2f}%|")
    lines+=['',f"There were {result['attemptCount']} recovery attempts with {result['additionalDeclaredSolveBudgetSeconds']} additional declared solving seconds. Each logical request permits at most 3 transports; costs include every failed and successful attempt. See REPLACEMENT_PROVENANCE.json for provenance and counts per identity.",'','|Cost scope|Arm|Known actual USD|Unknown-cost requests|Transport attempts|','|---|---|---:|---:|---:|']
    for scope,groups in [('Original experiment',result['fees']['original']['byArm']),('All recovery attempts',result['fees']['allRecoveryAttempts']['byArm']),('Combined',result['fees']['combinedByArm'])]:
        for arm,g in groups.items():lines.append(f"|{scope}|{arm}|{g['knownActualCostUsd']:.9f}|{g['unknownCostRequests']}|{g['requests']}|")
    lines+=['','The completed view is an infrastructure-conditioned supplemental result with additional independent budgets; it does not replace the frozen original experiment. The full method has ground-truth feedback; original single-shot format failures and truncations remain, without retries for correctness. The downtime exception for the original 3 pilot recoveries still belongs to the original view. Every attempt in this batch receives a fresh full 600 seconds.',
            '',f"Passed {proof['checkCount']} local checks. Recovery archive SHA256: {meta['sha256']}. Original archive SHA256: {parent['sha256']}.",
            '',f"Complete materials: {meta['fullResults']}",f"Recovery archive: {meta['archive']}",f"Original archive: {parent['archive']}"]
    (LOCAL/'RESULTS.md').write_bytes(('\n'.join(lines)+'\n').encode())
    save(LOCAL/'DELIVERY.json',{'delivered':True,'verified':True,'localChecks':proof['checkCount'],'recoveryArchive':meta,'originalArchive':parent,'firstValidCount':8,'attemptCount':result['attemptCount'],'additionalDeclaredSolveBudgetSeconds':result['additionalDeclaredSolveBudgetSeconds'],'fees':result['fees']})
    print(json.dumps({'allPassed':True,'checks':proof['checkCount'],'attempts':result['attemptCount'],'completed':result['completed']['arms'],'fees':result['fees']}),flush=True)

if __name__=='__main__':main()
