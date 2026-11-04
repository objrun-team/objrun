"""Explicit human acceptance of a failed canary gate; never changes scores."""
def apply_acceptance(audit,approval,canary):
    if approval.get('allowFormalWithCanaryExceptions') is not True:
        raise RuntimeError('ExplicitUserConditionChangeRequired')
    records=canary['records']
    unknown=sorted(r['id'] for r in records if not (r['solverValid'] and r['grade'].get('valid')))
    if len(records)!=40 or len(unknown)!=3 or unknown!=sorted(approval['exceptionIds']):
        raise RuntimeError('ApprovedCanaryExceptionsMismatch')
    replaced=[]
    for check in audit['checks']:
        if check['name']=='canary20x2':
            replaced.append({'name':'canary-condition-explicitly-changed-by-user','passed':True,
                             'originalCanaryPassed':check['passed'],'originalUnknownResults':3})
        else:replaced.append(check)
    return {'allPassed':all(c['passed'] for c in replaced),'checks':replaced,'failures':[c for c in replaced if not c['passed']],
            'canaryAcceptedWithExceptions':True,'originalCanaryPassed':False}
