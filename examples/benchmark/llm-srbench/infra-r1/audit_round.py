"""Audit supplemental attempts without relabeling the failed original audits."""
import importlib.util
from shared import *
def audit(require_complete=False,originals=True):
    plan=load(CONTROL/'plan.json');verify_sources()
    if originals:verify_originals()
    sp=importlib.util.spec_from_file_location('frozen_solver_audit',ROOT/'package/audit.py');m=importlib.util.module_from_spec(sp);sp.loader.exec_module(m);raw=m.audit(ROOT,False);issues=list(raw['issues']);selected={(e['arm'],e['key']):e for e in plan['selected']};starts=[];results=[]
    for d in (OUT/'tasks').glob('*/*'):
        pair=(d.parent.name,d.name)
        if pair not in selected:issues.append('OutsideSupplementalScope:'+str(pair));continue
        e=selected[pair];a=load(d/'attempt.json');starts.append(pair)
        if a['attemptId']!=e['attemptId']:issues.append('AttemptIdentity:'+str(pair))
        if not (d/'result.json').exists():issues.append('UnsettledAttempt:'+str(pair));continue
        results.append(load(d/'result.json'))
        for p in (d/'calls').glob('*'):
            if not p.name.startswith(e['attemptId']+'--'):issues.append('OldLogicalNamespace:'+str(pair))
    if len(starts)!=len(set(starts)):issues.append('DuplicateAttempt')
    if require_complete and set(starts)!=set(selected):issues.append('UnattemptedSelectedCells')
    fees=ledger(OUT/'tasks');total=plan['originalAccounting']['accountedUpperBoundUsd']+fees['accountedUpperBoundUsd']
    if total>78+1e-7:issues.append('CumulativeDollarCap')
    return {'allPassed':not issues,'issues':issues,'originalResultsPreserved':originals,'sourcePinsMatch':True,'recordCount':len(results),'attemptedCount':len(starts),'selectedCount':len(selected),'complete':set(starts)==set(selected) and len(results)==len(starts),'accounting':fees,'cumulativeUpperBoundUsd':total,'originalAuditsRemainFailed':True,'originalUnknownReserveRetainedUsd':plan['originalAccounting']['unknownReserveUsd'],'originalSolverAudit':raw}
if __name__=='__main__':print(json.dumps(audit(True)))
