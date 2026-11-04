"""Build the local human-readable index and independent-verification supplement."""
from pathlib import Path
import datetime
import hashlib
import json
import sys
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'recovery'))
from ops_recovery import LOCAL, ORIGINAL_LOCAL
from core import read, save, sha


def link(path, label):
    return f'[{label}]({Path(path).resolve().as_posix()})'


def main():
    delivery = read(LOCAL / 'DELIVERY.json')
    proof = read(LOCAL / 'LOCAL_VERIFICATION.json')
    assert delivery['delivered'] and delivery['verified'] and delivery['resolvedCount'] == 8 and proof['allPassed']
    result = read(LOCAL / 'INDEPENDENT_SUMMARY.json')
    now = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=8))).isoformat()
    lines = ['# LAB-Bench 最终交付', '', f'已完成完整回传和本地核验，时间：{now}（Asia/Shanghai）。原实验本地82227项核验通过，本批补跑18123项核验通过；两份完整归档的本地与服务器SHA256均一致。15分钟跟进已暂停，本批专用SSH隧道已关闭，共享代理未改动。', '', '最终成绩按用户指定规则：最后三条超时按0分计入708题分母，保留原始solverValid、grade、answer及真实submit。超时默认失败与实际有效但未通过分开记录；没有伪造答案或提交。', '', '|题集|单次 baseline|完整 ObjRun|完整法超时默认失败|', '|---|---:|---:|---:|']
    for category, arms in list(result['finalScored']['categories'].items()) + [('总计', result['finalScored']['arms'])]:
        a, b = arms['baseline'], arms['objrun']
        lines.append(f"|{category}|{a['passed']}/{a['tasks']}（{a['passRate']*100:.2f}%）|{b['passed']}/{b['tasks']}（{b['passRate']*100:.2f}%）|{b['timeoutDefaultFailures']}|")
    lines += ['', '单次组实际有效708条、通过296条、未通过412条，其中保留原有391条格式无效结果；完整组实际有效705条且全部通过，另3条为超时默认失败。完整法的0条“有效但未通过”与3条超时默认失败不能混为一类。', '', '|对照口径|baseline|ObjRun|', '|---|---|---|']
    for name, view in [('原始实验，基础设施未知保留', 'original'), ('首次有效补跑补齐后，余下未知保留', 'firstValidCompletedUnknown')]:
        a, b = result[view]['arms']['baseline'], result[view]['arms']['objrun']
        lines.append(f"|{name}|通过{a['passed']}，未知{a['unknown']}，准确率区间{a['accuracyBounds'][0]*100:.2f}%–{a['accuracyBounds'][1]*100:.2f}%|通过{b['passed']}，未知{b['unknown']}，准确率区间{b['accuracyBounds'][0]*100:.2f}%–{b['accuracyBounds'][1]*100:.2f}%|")
    lines += ['', '|费用范围|已知实际 USD|费用未知的传输数|传输数|', '|---|---:|---:|---:|']
    for scope, groups in [('原始实验', result['fees']['original']['byArm']), ('全部补跑（含失败）', result['fees']['allRecoveryAttempts']['byArm']), ('合计', result['fees']['combinedByArm'])]:
        lines.append(f"|{scope}|{sum(v['knownActualCostUsd'] for v in groups.values()):.9f}|{sum(v['unknownCostRequests'] for v in groups.values())}|{sum(v['requests'] for v in groups.values())}|")
    lines += ['', '未知费用没有计作0。费用依据OpenRouter实际usage.cost回执；预留费不算实际费用。原v2账本已包含v1，合计只计一次。', '', f"仅原8个基础设施异常身份参与补跑，共{result['attemptCount']}次独立尝试，5个身份取得首次有效结果，3个按最后一次超时结束。全部补跑的声明最大求解预算合计{result['additionalDeclaredSolveBudgetSeconds']}秒（每次600秒，不等于实际用时）；有界规则生效后只新开2次，新增声明预算1200秒，在途9832第6次未重置时钟。", '', '|身份（ObjRun，除标明baseline）|总尝试次数|最终处置|', '|---|---:|---|']
    for v in result['finalSources']:
        outcome = '首次实际有效，即停止' if v['actualValid'] else '超时默认失败，行政计0'
        lines.append(f"|{v['arm']}/{v['id']}|{v['attemptCount']}|{outcome}|")
    lines += ['', '|子任务|baseline|ObjRun|超时默认失败|', '|---|---:|---:|---:|']
    for name, arms in result['finalScored']['subtasks'].items():
        a, b = arms['baseline'], arms['objrun']
        lines.append(f"|{name}|{a['passed']}/{a['tasks']}|{b['passed']}/{b['tasks']}|{b['timeoutDefaultFailures']}|")
    pair = result['finalScored']['pairedScoredAll708']
    lines += ['', f"最终计零口径的708题配对差值为{pair['deltaObjrunMinusBaseline']*100:.2f}个百分点，题目bootstrap95%区间为{pair['bootstrap95'][0]*100:.2f}–{pair['bootstrap95'][1]*100:.2f}个百分点（5000次，seed20261019）；这只描述本次题目样本，不覆盖供应商故障或重复试验的不确定性。实际有效配对子集另见SUMMARY.json。", '', '预设同文选项题ded3f6ac-c54c-4626-86b4-cc607a44334f的敏感性：']
    for arm, s in result['finalScored']['knownDuplicateChoiceSensitivity'].items():
        lines.append(f"- 排除此题后总计：{arm} {s['passed']}/{s['tasks']}（{s['passRate']*100:.2f}%）。")
    rows = read(Path(delivery['recoveryArchive']['fullResults']) / 'FINAL_RECORDS.json')
    for arm in ['baseline', 'objrun']:
        items = [r for r in rows if r['arm'] == arm and r['category'] == 'SeqQA' and r['id'] != 'ded3f6ac-c54c-4626-86b4-cc607a44334f']
        passed = sum(bool(r['solverValid'] and r['grade'].get('valid') and r['grade'].get('passed')) for r in items)
        lines.append(f'- 排除此题后SeqQA：{arm} {passed}/{len(items)}（{passed/len(items)*100:.2f}%）。')
    lines += ['', '解释限制：完整ObjRun具有金标正确性反馈，可逐步排除MCQ选项；与单次组的差异同时受工具、反馈、预算及格式约束影响，不能直接解释为无反馈的生物推理提升。新增尝试是增加独立预算后的基础设施补充实验，最终成绩另含用户指定的超时行政计零。模型响应alias不代表不可变版本。原最初3条试跑恢复按累计活动任务时钟执行，修复停机单独记录，并非连续600秒墙钟；本批所有新尝试都独立给予完整600秒。', '', '交付文件：', '']
    for name in ['RESULTS.md', 'ORIGINAL_RESULTS.csv', 'FIRST_VALID_UNKNOWN_RESULTS.csv', 'FINAL_RESULTS.csv', 'FINAL_PROVENANCE.json', 'SUMMARY.json', 'LOCAL_VERIFICATION.json', 'LOCAL_VERIFICATION_ADAPTER.json', 'DELIVERY.json']:
        lines.append('- ' + link(LOCAL / name, name))
    lines += ['- ' + link(delivery['originalArchive']['archive'], '原始实验完整归档'), '- ' + link(delivery['recoveryArchive']['archive'], '全部补跑与最终计零完整归档'), '- ' + link(delivery['recoveryArchive']['fullResults'], '全部补跑日志、轨迹、候选、SQLite与原始请求回执'), '', '两份归档共同包含原始实验、全部失败/成功补跑、generation IDs、usage、真实submit、SQLite/任务树、错误日志、源码/依赖/数据和恢复例外；原结果未被覆盖。Windows本地核验仅通过适配器抽取原pinned纯分类函数以避免导入Linux fcntl，原报告和核验检查逐项未改动，适配源码与证据同时交付。', '', f"原始归档SHA256：{delivery['originalArchive']['sha256']}", f"补跑归档SHA256：{delivery['recoveryArchive']['sha256']}"]
    (LOCAL / 'DELIVERY_REPORT.md').write_bytes(('\n'.join(lines) + '\n').encode())
    files = [LOCAL / name for name in ['DELIVERY_REPORT.md', 'RESULTS.md', 'ORIGINAL_RESULTS.csv', 'FIRST_VALID_UNKNOWN_RESULTS.csv', 'FINAL_RESULTS.csv', 'FINAL_PROVENANCE.json', 'SUMMARY.json', 'INDEPENDENT_SUMMARY.json', 'LOCAL_VERIFICATION.json', 'LOCAL_VERIFICATION_ADAPTER.json', 'DELIVERY.json', 'RUNNING.json', 'FOLLOWUP.json', 'proxy-stop.json', 'verification-process.json']]
    files += [Path(__file__), Path(__file__).with_name('verify_windows.py')]
    manifest = {p.name: sha(p) for p in files}
    save(LOCAL / 'local-delivery-inventory.json', manifest)
    archive = LOCAL / 'labbench-local-delivery-audit.zip'
    assert not archive.exists(), 'Do not overwrite an existing delivery supplement'
    with zipfile.ZipFile(archive, 'x', compression=zipfile.ZIP_DEFLATED) as zipped:
        for p in files + [LOCAL / 'local-delivery-inventory.json']:
            zipped.write(p, p.name)
    with zipfile.ZipFile(archive) as zipped:
        assert zipped.testzip() is None
        for name, digest in manifest.items():
            assert hashlib.sha256(zipped.read(name)).hexdigest() == digest
    save(LOCAL / 'local-delivery-supplement.json', {'archive': str(archive), 'sha256': sha(archive), 'bytes': archive.stat().st_size, 'fileCount': len(manifest) + 1, 'localInventoryVerified': True})
    print(json.dumps({'report': str(LOCAL / 'DELIVERY_REPORT.md'), 'supplement': read(LOCAL / 'local-delivery-supplement.json')}))


if __name__ == '__main__':
    main()
