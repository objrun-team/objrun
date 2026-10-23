"""Strict raw audit and the separately named bounded-unknown policy audit."""
import importlib.util
from shared import *

def audit(root=ROOT,originals=False):
    root=pathlib.Path(root);plan=load(root/'control/plan.json');issues=[];raw_issues=[];rounds={}
    if root==ROOT:verify_sources()
    else:
        for e in load(root/'control/source-pins.json'):
            if sha(root/e['path'])!=e['sha256']:issues.append('SourceHash:'+e['path'])
    if originals:verify_history()
    sp=importlib.util.spec_from_file_location('raw_solver_auditor',root/'control/raw_audit.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m)
    all_attempts=[]
    for name in ['main','repair']:
        view=root/'rounds'/name;d=view/'outputs'
        expected=plan['selected'] if name=='main' else load(root/'outputs/repair-plan.json')['selected'] if (root/'outputs/repair-plan.json').exists() else []
        allowed={(e['arm'],e['key']):e for e in expected}
        if not d.exists():
            if name=='main' or expected:issues.append('MissingRound:'+name)
            continue
        raw=m.audit(root,False,out_path=d);raw_issues.extend(name+':'+i for i in raw['issues'])
        approved_unknown=[];actual_pairs=[]
        for cell in d.glob('tasks/*/*'):
            pair=cell.parent.name,cell.name;actual_pairs.append(pair)
            if pair not in allowed:issues.append('OutsideRoundScope:'+name+':'+str(pair));continue
            a=load(cell/'attempt.json');all_attempts.append(a['attemptId'])
            if a['attemptId']!=allowed[pair]['attemptId']:issues.append('AttemptId:'+str(pair))
            if not (cell/'result.json').exists():issues.append('UnsettledAttempt:'+str(pair));continue
            for dispatch in (cell/'calls').rglob('dispatch.json'):
                if not dispatch.parent.parent.name.startswith(a['attemptId']+'--'):issues.append('OldLogicalNamespace:'+str(pair))
            fees=ledger(cell)
            if fees['unknownRequests']:
                proof=load(cell/'isolation-settlement.json')
                if proof['localCallsActive']!=0 or not proof['nativeExited'] or not proof['trustedBoundAndFullReserve']:issues.append('UnknownNotSafelySettled:'+str(pair))
                if not math.isclose(proof['accounting']['accountedUpperBoundUsd'],fees['accountedUpperBoundUsd'],abs_tol=1e-9):issues.append('UnknownReserveChanged:'+str(pair))
                if len(proof['unknownRequests'])!=len(fees['unknownRequests']):issues.append('UnknownProofCoverage:'+str(pair))
                for p in proof['unknownRequests']:
                    rel=pathlib.PurePosixPath(p['requestDirectory']).relative_to(pathlib.PurePosixPath(plan['serverRoot']))
                    directory=root/pathlib.Path(str(rel))
                    for field,namefile in [('requestSha256','request.json'),('dispatchSha256','dispatch.json'),('receiptSha256','receipt.json')]:
                        if sha(directory/namefile)!=p[field]:issues.append('UnknownEvidenceChanged:'+str(pair))
                    request=load(directory/'request.json');rawbody=json.dumps(request,ensure_ascii=False,separators=(',',':')).encode();bound=len(rawbody)*.3/1e6+16384*1.2/1e6
                    if not math.isclose(bound,p['reservedUpperBoundUsd'],abs_tol=1e-10):issues.append('UnknownBoundNotReproducible:'+str(pair))
                approved_unknown.append("TerminatedUnknownPaidRequest:"+str(pair))
        if len(actual_pairs)!=len(set(actual_pairs)) or set(actual_pairs)!=set(allowed):issues.append('RoundCoverage:'+name)
        residual=[i for i in raw['issues'] if i not in approved_unknown]
        issues.extend(name+':'+i for i in residual)
        f=d/'candidate-fee-freeze.json'
        if not f.exists():issues.append('MissingCandidateFeeFreeze:'+name)
        else:
            frozen=load(f)
            if frozen['idOodAccessed']:issues.append('EarlyTestAccess:'+name)
            for e in frozen['files']:
                if sha(root/e['path'])!=e['sha256']:issues.append('FrozenCandidateEvidenceChanged:'+e['path'])
            if not math.isclose(ledger(d/'tasks')['accountedUpperBoundUsd'],frozen['accounting']['accountedUpperBoundUsd'],abs_tol=1e-9):issues.append('FrozenFinancialJournalChanged:'+name)
        rounds[name]={'records':len(actual_pairs),'expected':len(allowed),'rawVersionAuditPassed':raw['allPassed'],'controlledUnknownCells':len(approved_unknown),'accounting':ledger(d/'tasks')}
    if len(all_attempts)!=len(set(all_attempts)):issues.append('DuplicateAttemptIdentityAcrossRounds')
    cumulative=plan['historicalAccounting']['accountedUpperBoundUsd']+sum(v['accounting']['accountedUpperBoundUsd'] for v in rounds.values())
    if cumulative>78+1e-7:issues.append('CumulativeBudget')
    return {'controlledAuditPassed':not issues,'issues':issues,'rawVersionAuditPassed':not raw_issues,'rawIssuesRetained':raw_issues,'rounds':rounds,'cumulativeUpperBoundUsd':cumulative,'historicalAuditsPassed':False,'allVersionsIntegrityPassed':False,'originalHistoryVerifiedOnServer':originals,'oneRepairRoundOnly':True}
if __name__=='__main__':print(json.dumps(audit(originals=True)))
