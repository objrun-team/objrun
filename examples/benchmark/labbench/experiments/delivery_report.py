"""Final local delivery note, retaining the original and paused-recovery views."""
from pathlib import Path
import json
from ops import LOCAL
from protocol import digest


def main():
    verified=json.loads((LOCAL/'LOCAL_VERIFICATION.json').read_text(encoding='utf-8'))
    if not verified['allPassed']:raise RuntimeError('FullLocalVerificationRequired')
    retrieval=json.loads((LOCAL/'retrieval.json').read_text(encoding='utf-8'));root=Path(retrieval['fullResults']);out=root/'outputs/canonical'
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    cfg=read(root/'package/experiment.json');rows=[read(p) for p in (out/'results').glob('*/*.json')]
    assert len(rows)==1416
    def counts(items):
        known=[r for r in items if r['solverValid'] and r['grade'].get('valid')]
        passed=sum(r['grade']['passed'] for r in known);n=len(items);u=n-len(known)
        return {'total':n,'valid':len(known),'passed':passed,'unknown':u,'accuracyBounds':[passed/n,(passed+u)/n]}
    recovery=cfg.get('canaryTransportRecovery',{});original={};checks=[];timings=[]
    for tid,spec in recovery.items():
        original[('objrun',tid)]=read(out/'prior-canary/results/objrun'/(tid+'.json'))
        current=next(r for r in rows if r['arm']=='objrun' and r['id']==tid)
        home=out/'calls/solve'/tid/'objrun/native-001';dispatches=[read(p) for p in home.glob('attempt-*/dispatch.json')]
        checks.append({'id':tid,'firstLogicalWireUnchanged':len({p['requestSha256'] for p in dispatches})==1,'totalAttempts':len(dispatches),'withinOriginalThree':len(dispatches)<=3})
        timings.append({'id':tid,'consumedBeforeRecovery':spec['consumedSolveSeconds'],'remainingGranted':spec['remainingSolveSeconds'],
                        'cumulativeSolverWallSeconds':current.get('cumulativeSolveSeconds'),'repairDowntimeSeconds':current.get('recoveryWallGapSeconds'),
                        'budgetInterpretation':'600s cumulative active task clock; repair downtime excluded and separately disclosed; not uninterrupted wall clock'})
    views={}
    for name,items in [('withTransportRecovery',rows),('originalInterruptedView',[original.get((r['arm'],r['id']),r) for r in rows]),
                       ('excludingPausedRecoveryItems',[r for r in rows if r['id'] not in recovery])]:
        views[name]={a:counts([r for r in items if r['arm']==a]) for a in cfg['arms']}
    for check in checks:assert check['firstLogicalWireUnchanged'] and check['withinOriginalThree']
    summary=read(out/'SUMMARY.json');original_archive=read(LOCAL/'original-pilot-archive.json')
    assert original_archive['twoEndsSha256Verified'] and digest(Path(original_archive['localArchive']).read_bytes())==original_archive['sha256']
    report={'delivered':True,'verified':True,'retrieval':retrieval,'originalPilotArchive':original_archive,'views':views,'recoveryChecks':checks,'recoveryTiming':timings,
            'accounting':summary['accounting'],'costDeduplication':'v2 ledger already includes every inherited v1 receipt; do not add original pilot costs again',
            'analysisSourceSha256':digest(Path(__file__).read_bytes())}
    (LOCAL/'DELIVERY.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    lines=['# LAB-Bench 完整交付','','ProtocolQA108＋SeqQA600；仅单次与完整 ObjRun；完整方法具有金标正误反馈。','',
           '|结果视图|组别|有效/总数|通过|准确率范围|','|---|---|---:|---:|---|']
    for view,arms in views.items():
        for arm,s in arms.items():lines.append(f"|{view}|{arm}|{s['valid']}/{s['total']}|{s['passed']}|{s['accuracyBounds']}|")
    lines+=['','3条恢复没有交付过旧候选，其首逻辑请求按原wire从剩余传输次数继续。已用约303秒、剩余约297秒；修复停机间隔单独记录，因此这3条不是不中断的600秒墙钟实验。原中断视图和排除这3题的配对范围同时保留。',
            '', '费用以v2完整账本为准，包含原v1回执及新增恢复费用；不再与原试跑费用相加。缺失费用保留未知。', '', '|组别|已知实际美元|未知费用请求|请求数|','|---|---:|---:|---:|']
    for arm,c in summary['accounting']['byArm'].items():lines.append(f"|{arm}|{c['knownActualCostUsd']:.9f}|{c['unknownCostRequests']}|{c['requests']}|")
    lines+=['',f"全量归档：{retrieval['archive']}",f"SHA256：{retrieval['sha256']}",f"原试跑归档：{original_archive['localArchive']}",f"原试跑SHA256：{original_archive['sha256']}",
            '',f"本地核验通过，检查数：{verified['checkCount']}。逐题CSV、源数据、候选、原始请求响应、费用、日志、SQLite与轨迹在完整归档及full-results内。",
            '准确率、precision、coverage及各子任务结果见SUMMARY.json；同文选项题的预设敏感性分析另报。最终选择正确不自动证明生物学推理得到修复。']
    (LOCAL/'DELIVERY_REPORT.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    print(json.dumps({'delivered':True,'verified':True,'views':views,'accounting':summary['accounting']}))


if __name__=='__main__':main()
