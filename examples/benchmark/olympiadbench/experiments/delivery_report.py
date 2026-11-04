"""Write a delivery supplement after independent verification, without changing the archive."""
from pathlib import Path
from decimal import Decimal
import datetime as dt
import json
from ops import LOCAL


def main():
    def read(p):return json.loads(p.read_text(encoding='utf-8'))
    delivery=read(LOCAL/'DELIVERY.json');verification=read(LOCAL/'LOCAL_VERIFICATION.json')
    assert delivery['verified'] and verification['allPassed']
    meta=read(LOCAL/'retrieval.json');root=Path(meta['fullResults']);out=root/'outputs/canonical'
    summary=read(out/'SUMMARY.json');audit=read(out/'AUDIT.json');status=read(out/'status.json')
    assert audit['allPassed'] and status['stage']=='complete'
    rows=[read(p) for p in (out/'results').glob('*/*.json')]
    costs={a:Decimal(0) for a in ['baseline','objrun']};unknown=[];exceptions=[]
    for p in (out/'calls').rglob('receipt.json'):
        x=read(p);rel=p.relative_to(out/'calls');arm=rel.parts[2];u=x.get('usage')
        # This entire run was on Saturday UTC. Recompute the observed official weekend tariff.
        assert all(dt.datetime.fromtimestamp(x[k],dt.timezone.utc).weekday()>=5 for k in ['startedEpoch','endedEpoch'])
        if not isinstance(u,dict):unknown.append(str(rel));assert x['cost']['kind']=='unknown'
        else:
            hit=u['prompt_cache_hit_tokens'];miss=u['prompt_cache_miss_tokens'];output=u['completion_tokens']
            assert u['prompt_tokens']==hit+miss
            value=(Decimal(hit)*Decimal('.003')+Decimal(miss)*Decimal('.15')+Decimal(output)*Decimal('.6'))/Decimal(1000000)
            assert abs(value-Decimal(str(x['cost']['lowerUsd'])))<Decimal('1e-12')
            assert abs(value-Decimal(str(x['cost']['upperUsd'])))<Decimal('1e-12')
            costs[arm]+=value
        if x.get('error'):
            dispatch=read(p.with_name('dispatch.json'))
            exceptions.append({'path':str(rel),'error':x['error'],'httpStatus':x['httpStatus'],'endedMinusDeadlineSeconds':x['endedEpoch']-dispatch['deadlineEpoch'],'costUnknown':x['cost']['kind']=='unknown'})
    for arm,value in costs.items():assert abs(value-Decimal(str(summary['accounting']['byArm'][arm]['estimateLowerUsd'])))<Decimal('1e-8')
    no_submit=[r['id'] for r in rows if r['arm']=='objrun' and r.get('candidateHow')!='submitted']
    deadline_markers=sum(r.get('error')=='OriginalSolveDeadlineExhausted' for r in rows if r['arm']=='objrun')
    detail={'allPassed':True,'method':'independent Decimal recomputation from complete usage at observed weekend USD tariff per million: hit .003 / miss .15 / output .6',
            'knownEstimatedUsdByArm':{a:str(v) for a,v in costs.items()},'knownEstimatedUsd':str(sum(costs.values())),
            'unknownCostRequests':unknown,'requestExceptions':exceptions,'noSubmissionIds':no_submit,
            'remoteAuditChecks':len(audit['checks']),'localVerificationChecks':verification['checkCount'],'archiveSha256':meta['sha256']}
    with (LOCAL/'DELIVERY_COST_RECHECK.json').open('x',encoding='utf-8') as f:json.dump(detail,f,ensure_ascii=False,indent=2);f.write('\n')
    paired=summary['paired'];wins=len(paired['wins']);losses=len(paired['losses']);both=summary['arms']['baseline']['passed']-losses
    lines=['# OlympiadBench 完整交付报告','',
        f"批次 `{summary['run']}`，novaeve 已完成；472 条唯一结果全部有效。268 项零模型验收和固定 8 题两组 canary 均通过，canary 已纳入正式结果，没有重复生成。",'',
        '|方法|通过/题数|成功率|模型请求|已知 usage 的估算费用 USD|未知费用请求|',
        '|---|---:|---:|---:|---:|---:|']
    for arm,label in [('baseline','单次尝试'),('objrun','完整 ObjRun')]:
        a=summary['arms'][arm];c=summary['accounting']['byArm'][arm]
        lines.append(f"|{label}|{a['passed']}/236|{a['knownCorrectFraction']:.2%}|{c['requests']}|{costs[arm]}|{c['unknownCostRequests']}|")
    lines+=['',f"配对提升 **{paired['difference']*100:.2f} 个百分点**；五个子领域内分层 bootstrap 20,000 次，seed=20261017，95% 区间 **{paired['ci95'][0]*100:.2f}–{paired['ci95'][1]*100:.2f} 个百分点**。仅完整方法通过 {wins} 题，仅单次通过 {losses} 题，都通过 {both} 题，都失败 {236-wins-losses-both} 题。区间只反映本次题目重采样，不代表 API 重复运行稳定性。",'',
        '|子领域|题数|单次通过|完整方法通过|','|---|---:|---:|---:|']
    for name,arms in summary['subfields'].items():lines.append(f"|{name}|{arms['baseline']['tasks']}|{arms['baseline']['passed']}|{arms['objrun']['passed']}|")
    lines+=['',f"费用按保存的官方周末费率独立重算，已知部分范围为 **${sum(costs.values())}–${sum(costs.values())}**；另有 **{len(unknown)} 次未知费用**，不能给出总费用有限上界，也未将其计零。逐请求实际账单不可获得。这些请求都在原始整题 deadline 附近中止，HTTP 状态为 200 但没有完整 usage；差值详见费用复核 JSON。",'',
        f"完整组 {len(no_submit)} 题在原时限内没有真实提交，按协议记为正常未通过；{deadline_markers} 条结果保留 OriginalSolveDeadlineExhausted 标记，未重开时钟或补答。单次组 {summary['arms']['baseline']['length']} 条返回 length，按原始输出评分。题目级接口/评分未知为 0。已结算回执全齐，{len(exceptions)} 条 deadline 中止回执与普通完整响应分列。",'',
        '全部使用 DeepSeek 官方 API 的 deepseek-flash，thinking enabled/high/16384；观察映射 DeepSeek-V4.1-Flash-1017 为滚动别名。完整方法为真实 ObjRun，整题 600 秒、c5、4 分支、ask/act 各 12 units，仅 submit/verify/task_tree/node_load；任务/模型并发上限 16，规则评分并发 4。固定官方 MathJudger、final_answer[0]、参数顺序与逐题容差。',
        '完整方法增加了尝试和在线规则反馈，本实验支持系统效果比较，不能单独归因于某个机制或声称同费用效率。69 条内部首次拒绝后最终通过的轨迹只作为待独立审查的修复候选。','',
        '原汇总器将一条字符串 submit 参数当作对象而报错；离线修正按冻结 native finalCandidate 的空答案语义读取，不对字符串重新 JSON 解码。236 条完整方法的最终候选绑定均通过。原报错、原脚本、失败回放、修正脚本与依据保存在归档的 outputs/canonical/analysis-recovery-v1、analysis-recovery-v2。冻结科学包、原候选、评分与请求回执均未修改，无新模型调用。第一次恢复脚本因未部署的操作性 verifier 路径退出，第二次命令生成在执行前语法失败，原件和修正依据同样保留。',
        '另有一个官方公开评分样例的标注与固定 inference 路径不一致；wrapper 与固定官方实现一致，已在零模型验收中披露，没有据此修改评分。','',
        f"远端审计 **{len(audit['checks']):,} 项通过**；本地独立核验 **{verification['checkCount']:,} 项通过**，覆盖两端归档 SHA256、候选/真实 submit、源码依赖、官方 wire、usage/费用、全局并发和材料无 Key。额外费用重算见 [DELIVERY_COST_RECHECK.json](DELIVERY_COST_RECHECK.json)。",'',
        f"完整归档 {meta['bytes']:,} 字节，SHA256 `{meta['sha256']}`。",'',
        f"- [逐题 CSV](FINAL_RESULTS.csv)\n- [全部结果、日志、原始请求响应、SQLite、源码和依赖]({Path(meta['archive']).name})\n- [解压后的全量目录](full-results/)\n- [机器汇总](SUMMARY.json)\n- [远端审计](AUDIT.json)\n- [本地核验](LOCAL_VERIFICATION.json)\n- [交付回执](DELIVERY.json)",'',
        f"NAS 不可变归档：`{meta['remoteArchive']}`。本交付补充报告位于归档旁，不改写已校验的原归档。"]
    with (LOCAL/'DELIVERY_REPORT.md').open('x',encoding='utf-8') as f:f.write('\n'.join(lines)+'\n')
    print(json.dumps({'written':'DELIVERY_REPORT.md','costRecheckPassed':True,'knownEstimateUsd':str(sum(costs.values())),'unknownCostRequests':len(unknown)}))


if __name__=='__main__':main()
