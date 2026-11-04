"""Readable local delivery summary from verified artifacts; no model operations."""
from collections import Counter
from pathlib import Path
import csv
import json
from ops import LOCAL
from protocol import DEFECT, digest


def main():
    read=lambda p:json.loads(p.read_text(encoding='utf-8'))
    verification=read(LOCAL/'LOCAL_VERIFICATION.json');delivery=read(LOCAL/'DELIVERY.json')
    assert verification['allPassed'] and delivery['verified'] and delivery['delivered']
    summary=read(LOCAL/'SUMMARY.json');root=Path(delivery['retrieval']['fullResults']);out=root/'outputs/canonical'
    server_checks=len(read(LOCAL/'AUDIT.json')['checks'])
    with (LOCAL/'FINAL_RESULTS.csv').open(encoding='utf-8-sig',newline='') as f:rows=list(csv.DictReader(f))
    assert len(rows)==1416
    def counts(items):
        valid=[r for r in items if r['solverValid']=='True' and r['gradeValid']=='True']
        passed=sum(r['passed']=='True' for r in valid);n=len(items);unknown=n-len(valid)
        return {'tasks':n,'valid':len(valid),'passed':passed,'unknown':unknown,'accuracyBounds':[passed/n,(passed+unknown)/n]}
    for arm in summary['arms']:
        observed=counts([r for r in rows if r['arm']==arm])
        assert all(observed[k]==summary['arms'][arm][k] for k in observed)
    seq_sensitivity={a:counts([r for r in rows if r['arm']==a and r['category']=='SeqQA' and r['id']!=DEFECT]) for a in summary['arms']}
    trace=[r for r in read(LOCAL/'TRAJECTORY_ANALYSIS.json') if r['arm']=='objrun']
    labels=Counter(len(r['distinctEvaluatedLabels']) for r in trace)
    trajectory={'firstCandidatePassed':sum(bool(r['firstCandidateGrade']['passed']) for r in trace),'firstCandidatePresent':sum(r['firstCandidate'] is not None for r in trace),
                'denominator':708,'distinctEvaluatedLabelsHistogram':dict(sorted(labels.items())),
                'multipleEvaluatedLabels':sum(v for k,v in labels.items() if k>1),'firstCorrectnessFeedbackFalseThenSubmittedPass':sum(r.get('realRepairCandidate',False) for r in trace)}
    assert trajectory['firstCandidatePassed']==summary['firstCandidate']['objrunPassed']
    costs=summary['accounting']['byArm'];total_cost=sum(c['knownActualCostUsd'] for c in costs.values());unknown_cost=sum(c['unknownCostRequests'] for c in costs.values())
    recovery_archive=read(LOCAL/'v2-pilot-recovery-archive.json')
    assert recovery_archive['twoEndsSha256Verified'] and digest(Path(recovery_archive['localArchive']).read_bytes())==recovery_archive['sha256']
    results={'verified':True,'parameters':summary['parameters'],'oracleFeedback':True,'arms':summary['arms'],'categories':summary['categories'],'subtasks':summary['subtasks'],
             'paired':summary['paired'],'knownDuplicateChoiceSensitivity':summary['knownDuplicateChoiceSensitivity'],'seq599Sensitivity':seq_sensitivity,'trajectory':trajectory,
             'accounting':summary['accounting'],'knownActualCostUsd':total_cost,'unknownCostRequests':unknown_cost,'recoveryTiming':delivery['recoveryTiming'],
             'views':delivery['views'],'retrieval':delivery['retrieval'],'localVerificationCheckCount':verification['checkCount'],
             'originalPilotArchive':delivery['originalPilotArchive'],'recoveryPilotArchive':recovery_archive,
             'sourceSha256':digest(Path(__file__).read_bytes()),'summarySha256':digest((LOCAL/'SUMMARY.json').read_bytes()),'verificationSha256':digest((LOCAL/'LOCAL_VERIFICATION.json').read_bytes())}
    normalization=LOCAL/'verification-history/approval-line-ending-normalization.json'
    if normalization.exists():results['approvalLineEndingNormalization']=read(normalization)
    (LOCAL/'RESULTS.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    def bounds(s):return f"{s['accuracyBounds'][0]*100:.2f}%–{s['accuracyBounds'][1]*100:.2f}%"
    def link(name,path):return f'[{name}]({Path(path).as_posix()})'
    lines=['# LAB-Bench 实验结果与交付','','708 题 × 单次尝试 / 完整 ObjRun，共 1416 条终态；8 条基础设施未知保留，完整归档回传与本地核验通过。',
           '','|题集|组别|有效/总数|已知通过|基础设施未知|全分母准确率范围|','|---|---|---:|---:|---:|---|']
    for category,arms in list(summary['categories'].items())+[('全部',summary['arms'])]:
        for arm,s in arms.items():lines.append(f"|{category}|{arm}|{s['valid']}/{s['tasks']}|{s['passed']}|{s['unknown']}|{bounds(s)}|")
    lines+=['','未知不强记为答错；表中范围只反映这些未知的最坏/最好取值。正常格式失败属于已知方法失败。',
            '', '|组别|有效答案 precision|全分母 coverage|格式无效|长度截断|','|---|---:|---:|---:|---:|']
    for arm,s in summary['arms'].items():lines.append(f"|{arm}|{s['precision']*100:.2f}%|{s['coverage']*100:.2f}%|{s['formatInvalid']}|{s['length']}|")
    paired=summary['paired']
    lines+=['',f"完整有效配对 {paired['validPairs']} 题；配对准确率差 {paired['differenceOnValidPairs']*100:.2f} 个百分点，分层题目 bootstrap 95% 区间 [{paired['ci95ConditionalOnValidPairs'][0]*100:.2f}, {paired['ci95ConditionalOnValidPairs'][1]*100:.2f}]。这只描述本次 API 运行的题目重采样不确定性，不代表重复实验间波动。",
            '', '**解释限制：** 单次组有 391 题格式无效，其中 356 次长度截断均未形成可解析答案。完整组获得在线金标正误反馈，允许在预算内反复验证选项；高最终分数包含输出格式、工具执行和选项排除的收益，不能直接解释成生物学推理修复。',
            '',f"同一批完整方法轨迹中，首次候选已知通过 {trajectory['firstCandidatePassed']}/708；{trajectory['multipleEvaluatedLabels']} 题评估过多个不同标签；{trajectory['firstCorrectnessFeedbackFalseThenSubmittedPass']} 条记录首次正确性反馈为否、最终真实提交通过。这些是轨迹统计，没有新增第三个实验组。",
            '', '|组别|已知实际费用 USD|费用未知请求|全部传输尝试|','|---|---:|---:|---:|']
    for arm,c in costs.items():lines.append(f"|{arm}|{c['knownActualCostUsd']:.9f}|{c['unknownCostRequests']}|{c['requests']}|")
    lines+=[ '',f"已知实际费用合计 ${total_cost:.9f}，另有 {unknown_cost} 笔费用未知；无未结算在途请求。使用 OpenRouter usage.cost；v2 账本已经包含所有 v1 回执，不重复叠加试跑费用。未知费用不作零，也不把预留金额当实际费用。",
             '',f'预设同文选项题 {DEFECT} 保留在主结果。排除后全题集 707 题的结果见 RESULTS.json；SeqQA 599 题敏感性结果如下：',
             '', '|组别|有效/599|已知通过|未知|准确率范围|','|---|---:|---:|---:|---|']
    for arm,s in seq_sensitivity.items():lines.append(f"|{arm}|{s['valid']}|{s['passed']}|{s['unknown']}|{bounds(s)}|")
    lines+=['','3 条试跑恢复只使用原剩余约 297 秒，首逻辑请求 wire 不变、各累计两次传输。修复停机间隔约 324 秒单独记录，因此不是连续 600 秒墙钟实验。原中断视图、恢复视图和双方排除这 3 题的视图保存在 DELIVERY.json。原试跑全部有效的门槛未通过；用户明确批准保留 3 条未知继续，其余审计要求保持。',
            '', f"服务器审计 {server_checks} 项、本地核验 {verification['checkCount']} 项通过。归档 SHA256：{delivery['retrieval']['sha256']}。",
            '',link('完整解压材料目录',root)+'；'+link('完整归档',delivery['retrieval']['archive'])+'。',
            '',link('逐题 CSV',LOCAL/'FINAL_RESULTS.csv')+'；'+link('完整统计及各子任务',LOCAL/'SUMMARY.json')+'；'+link('候选与反馈轨迹索引',LOCAL/'TRAJECTORY_ANALYSIS.json')+'；'+link('本地核验',LOCAL/'LOCAL_VERIFICATION.json')+'。',
            '', '完整解压材料包含源数据、私有评分映射、冻结源码与依赖、全部模型请求/响应/generation ID/usage、候选、评分、异常、SQLite/任务树和日志。文件清单位于 full-results/outputs/canonical/file-inventory.json。']
    if normalization.exists():lines+=['','本地批准记录曾因 Windows CRLF 与归档 LF 换行差异中止核验。只规范本地换行后重新执行原标准，JSON 内容、归档和实验数据不变；原件与转换哈希证据见 '+link('换行规范化记录',normalization)+'。']
    (LOCAL/'RESULTS.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
    source=LOCAL/'delivery-analysis-source';source.mkdir(exist_ok=True);(source/Path(__file__).name).write_bytes(Path(__file__).read_bytes())
    manifest={p.name:digest(p.read_bytes()) for p in [LOCAL/'RESULTS.md',LOCAL/'RESULTS.json',source/Path(__file__).name]}
    (LOCAL/'RESULTS_PROVENANCE.json').write_text(json.dumps({'files':manifest,'scope':'local postprocessing of verified delivery; frozen archive unmodified'},indent=2)+'\n',encoding='utf-8')
    print(json.dumps({'report':str(LOCAL/'RESULTS.md'),'knownActualCostUsd':total_cost,'unknownCostRequests':unknown_cost,'seq599Sensitivity':seq_sensitivity}))


if __name__=='__main__':main()
