"""Independent review of the single human-approved unresolved bill. Never changes raw audit."""
import hashlib,importlib.util,json,pathlib
CONTROL='outputs/continuation-429'
def load(p):return json.loads(pathlib.Path(p).read_text(encoding='utf8'))
def sha(p):return hashlib.sha256(pathlib.Path(p).read_bytes()).hexdigest()
def inspect(root,require_complete=False):
    root=pathlib.Path(root);plan=load(root/CONTROL/'plan.json');problems=[]
    spec=importlib.util.spec_from_file_location('original_v2_audit',root/'package/audit.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    raw=m.audit(root,require_complete)
    approved=plan['approvedUnknown'];expected="TerminatedUnknownPaidRequest:"+str((approved['arm'],approved['key']))
    if raw['issues']!=[expected]:problems.append({'unexpectedOriginalIssues':raw['issues'],'expectedOnly':[expected]})
    for path,digest in plan['protectedFiles'].items():
        p=root/path
        if not p.is_file() or sha(p)!=digest:problems.append({'protectedEvidenceChanged':path})
    for cell,paths in plan['protectedCallFiles'].items():
        current={p.relative_to(root).as_posix() for p in (root/'outputs/tasks'/cell/'calls').rglob('*') if p.is_file()}
        if current!=set(paths):problems.append({'oldRequestsChanged':cell})
    for name in ['receipt.json','dispatch.json','response.raw.txt']:
        if sha(root/approved['path']/name)!=approved['hashes'][name]:problems.append({'approvedExceptionEvidenceChanged':name})
    receipt=load(root/approved['path']/'receipt.json')
    if receipt.get('actualCostUsd') is not None or not receipt['unknownCost'] or receipt['reservedUpperBoundUsd']!=approved['reservedUpperBoundUsd']:problems.append('UnknownReserveChanged')
    if require_complete:
        if raw['recordCount']!=483:problems.append('Expected483Records')
        expectedcells={(e['arm'],e['key']) for e in plan['remainingCells']}|{tuple(e) for e in plan['protectedCells']}
        cells={(p.parent.parent.name,p.parent.name) for p in (root/'outputs/tasks').glob('*/*/result.json')}
        if expectedcells!=cells:problems.append('ContinuationMapping')
    return {'approvedExceptionAuditPassed':not problems,'allOtherChecksPassed':not problems,'originalOfflineAuditPassed':raw['allPassed'],'allPaidCostsKnown':False,'originalAudit':raw,'approvedException':{k:approved[k] for k in ['id','arm','key','reservedUpperBoundUsd']},'additionalIssues':problems,'recordCount':raw['recordCount'],'requireComplete':require_complete}
