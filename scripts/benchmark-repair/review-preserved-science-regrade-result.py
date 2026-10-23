"""Audit stored results and retained inputs only; never call a model or grader."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DOC = ROOT / 'docs/repair-2026-10-08/preserved-science-regrade-c357edbf-29ae-4676-9456-a5fdd40e7315'
RESULT_SHA = 'f91533f6f24783c28837617c6504b5bc1231d3e8d08af731d3196c80cc5de04b'
PREP_SHA = '59615aaff32279f41b7e9a71ecd348d4b2d4bee8680bc61e071bd1d3768ed09b'
RUN = 'repair-2026-10-08T18-32-57-118Z'

def pin(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest())

def verify(p):
    actual = pin(p['path'])
    assert actual['bytes'] == p['bytes'] and actual['sha256'] == p['sha256'], p['path']

def load(path):
    return json.loads(Path(path).read_bytes())

def save(path, value):
    raw = value.encode('utf-8') if isinstance(value, str) else (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    with path.open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    assert path.read_bytes() == raw
    return pin(path)

def main():
    result_pin, prepare_pin = pin(DOC/'result.json'), pin(DOC/'prepare.json')
    assert result_pin['sha256'] == RESULT_SHA and prepare_pin['sha256'] == PREP_SHA
    result, prep, start = load(result_pin['path']), load(prepare_pin['path']), load(DOC/'execution-start.json')
    assert result['protocol'] == 'preserved-science-fixed-regrade-result-v1' and result['runId'] == prep['runId'] == RUN
    assert result['graded'] == len(result['taskEvidence']) == len(prep['original']['rows']) == 789
    assert result['modelCalls'] == start['modelCalls'] == 0
    assert result['originalCampaignCompleted'] is False and result['full1220ScoreCertificateValid'] is False
    assert result['originalAcceptanceFieldsModified'] is False and result['independentGroupAuditStillRequired'] is True
    for obj in (result, start):
        verify(obj['prepare']); verify(obj['entry']); verify(obj['financial'])
    verify(start['owned'])
    financial = load(result['financial']['path'])
    assert financial['validated'] is True and financial['financialOnly'] is True
    assert financial['scoreCertificate'] is False and financial['releasePermitted'] is False and financial['ownerClosureCertified'] is False
    assert financial['newUnknownCount'] == financial['newPendingCount'] == 0
    assert financial['originalUnknownCarryNanoCny'] == '8392180000' and financial['oldUnknownSettled'] is False
    manifest = load(prep['original']['manifest']['path'])
    plan = manifest['taskSchedule']
    assert len(plan) == 1220
    input_pins = [prep['original']['manifest'], prep['original']['progress'], prep['source']['recipe'], *prep['source']['sources']]
    assert len(prep['source']['sources']) == 81
    for p in input_pins:
        verify(p)
    originals = {r['index']:r for r in prep['original']['rows']}
    seen, tuple_seen, actual, outcomes = set(), set(), [], {}
    for evidence in result['taskEvidence']:
        verify(evidence)
        g = load(evidence['path'])
        i = g['index']
        assert i in originals and i not in seen and Path(evidence['path']).name == f'grade-{i}.json'
        seen.add(i)
        row = originals[i]
        verify(row['inputPin']); verify(g['original'])
        assert g['original'] == row['inputPin']
        r = load(row['inputPin']['path'])
        for f in ('index', 'benchmark', 'arm', 'replica', 'officialId', 'candidateSha256'):
            assert g[f] == r[f] == row[f]
        for f in ('index', 'benchmark', 'arm', 'replica', 'officialId'):
            assert r[f] == plan[i][f]
        assert hashlib.sha256(r['answer'].encode()).hexdigest() == r['candidateSha256']
        assert r['acceptance']['valid'] is False and r['acceptance']['outcome'] == 'pending_after_all_generation'
        a = g['acceptance']
        assert a['candidateSha256'] == r['candidateSha256'] and a['valid'] is True and type(a['passed']) is bool
        assert a['outcome'] in ('passed','rejected','budget_exhausted','no_candidate')
        assert a['passed'] == (a['outcome'] == 'passed')
        if 'verdict' in a:
            v = a['verdict']
            assert v['valid'] is True and v['pass'] in (0,1) and a['passed'] == (v['pass'] == 1)
            assert a['outcome'] == v['outcome']
            assert all('error' not in n for n in v['trace'])
        else:
            assert r['candidateHow'] == 'none' and a['passed'] is False
        key = '/'.join(map(str, (g['benchmark'],g['arm'],g['replica'])))
        tuple_key = key + '/' + g['officialId']
        assert tuple_key not in tuple_seen
        tuple_seen.add(tuple_key)
        actual.append((key,g['officialId'],a['passed']))
        outcomes[a['outcome']] = outcomes.get(a['outcome'],0)+1
    assert seen == set(originals)
    groups = []
    for g in result['groups']:
        required = sorted(p['officialId'] for p in plan if '/'.join(map(str,(p['benchmark'],p['arm'],p['replica']))) == g['key'])
        found = [(task,passed) for key,task,passed in actual if key == g['key']]
        observed = sorted(task for task,_ in found)
        complete = observed == required
        assert g['requiredOfficialIds'] == required and g['retainedOfficialIds'] == observed
        assert g['planned'] == len(required) and g['retained'] == g['graded'] == g['valid'] == len(found)
        assert g['passed'] == sum(passed for _,passed in found)
        assert g['originalKeysetComplete'] == g['completeGroupScoreEligible'] == complete
        groups.append({k:g[k] for k in ('key','planned','retained','graded','valid','passed','originalKeysetComplete','completeGroupScoreEligible')})
    for p in input_pins + [r['inputPin'] for r in prep['original']['rows']]:
        verify(p)
    assert pin(DOC/'result.json') == result_pin and pin(DOC/'prepare.json') == prepare_pin
    report = dict(protocol='preserved-science-regrade-stored-independent-audit-v1', validated=True,
        runId=RUN, reviewer=pin(__file__), resultPin=result_pin, preparePin=prepare_pin,
        startPin=pin(DOC/'execution-start.json'), entryPin=result['entry'], financialPin=result['financial'], ownedObservationPin=start['owned'],
        verifiedTaskEvidence=789, verifiedOriginalCandidates=789, verifiedFrozenSources=81,
        groups=groups, outcomeCounts=outcomes, modelCalls=0, graderRequests=0, auditMode='stored-only',
        originalAcceptanceFieldsModified=False, full1220ScoreCertificateValid=False,
        originalUnknownCarryRetainedNanoCny='8392180000', releaseAuthorized=False,
        missingPublishedIndexesWithin0To791=sorted(set(range(792))-seen),
        limitations=['No provider/raw financial replay, model generation, HTTP grading or current owner query performed here.',
                    'Historical owned observation is pinned; not fresh authority for later operations.',
                    'ChemBench U194/286 and F259/283 are partial observed records; neither is a complete500-task score.',
                    'Complete AIME/CMT keysets are independently checked stored outcomes of this interrupted experiment, not the original campaign becoming completed.',
                    'No invoice, equal-budget causal claim or authorization to generate remaining431 records.'])
    doc = ROOT / 'docs/repair-2026-10-08'
    out = save(doc/'preserved-science-regrade-stored-independent-audit.json', report)
    md = f"""已逐份只读核验 789 个新判卷收据、原候选 SHA 与 schedule tuple、81 个冻结执行源及完整题目集合，未调用模型或评分服务。原 acceptance 仍为 pending，原 1220 整批不完整，锁/财务释放不在本审计范围。

| 组 | 有效/已保留 | 通过 | 原计划分母 | 完整题目集合 |
| --- | ---: | ---: | ---: | --- |
"""
    for g in groups:
        md += f"| {g['key']} | {g['valid']}/{g['retained']} | {g['passed']} | {g['planned']} | {'是' if g['originalKeysetComplete'] else '否'} |\n"
    md += f"\nChemBench 的 194/286 与 259/283 仅为中断实验中保留记录的结果，不能作为 500 题分数。AIME/CMT 的完整集合已在保存收据上复核；这不补全整批、不执行剩余 431 条、不触及原四笔未知费用责任。actual financial4722 与历史 owned proof 仅核其 Pin，不重复原始47010件审计。详细报告 SHA {out['sha256']}；结果原件 SHA {RESULT_SHA}。\n"
    md_pin = save(doc/'preserved-science-regrade-stored-independent-audit.md', md)
    print(json.dumps({'report':out,'markdown':md_pin}))

if __name__ == '__main__':
    main()
