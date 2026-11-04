"""Audit retrieved bytes, candidates, model wires, feedback visibility, and costs."""
import hashlib
import json
import math
from pathlib import Path
import statistics
import sys
from collections import Counter
import csv
import sqlite3

REPO = Path(__file__).resolve().parents[4]
LOCAL = REPO / 'docs/scibench/pilot-20261016-v1'
ROOT = LOCAL / 'full-results'
OUT = ROOT / 'outputs/canonical'
read = lambda p: json.loads(p.read_text(encoding='utf-8'))
sha = lambda s: hashlib.sha256(s if isinstance(s, bytes) else s.encode()).hexdigest()
sys.path.insert(0, str(ROOT / 'package'))
from grade import Scorer
scorer = Scorer(ROOT / 'package/vendor')
book = {r['id']: r for r in read(ROOT / 'data/private-tasks.json')}
catalog = read(ROOT / 'data/public-pilot.json')
cfg = read(ROOT / 'package/experiment.json')
records = [read(p) for p in sorted((OUT / 'results').rglob('*.json'))]
checks = []
def check(name, ok):
    checks.append({'name': name, 'passed': bool(ok)})
    if not ok:
        print('FAILED ' + name)

check('21x4-record-identity', len(records) == 84 and {(r['arm'], r['id']) for r in records} == {(a, t['id']) for a in cfg['arms'] for t in catalog})
check('zero-overlap-development-selection', read(ROOT / 'data/source.json')['promptOverlap'] == 0)
check('public-input-whitelist', all(set(t) == {'id', 'source', 'prompt'} for t in catalog))
check('controls-complete', read(OUT / 'controls.json')['allPassed'])
remote_prefix = read(OUT / 'launch.json')['root'].rstrip('/') + '/'
for pin in read(OUT / 'source-pins.json')['files']:
    relative = pin['path'].removeprefix(remote_prefix)
    check('source-pin:' + relative, sha((ROOT / relative).read_bytes()) == pin['sha256'])
prompt_by_id = {r['id']: r['prompt'] for r in catalog}
suffix = '\nSolve the problem. End with one finite numeric answer in the requested unit inside \\boxed{...}. For scientific notation use a\\times 10^{n}.'
receipts = []
length_empty = 0
for p in sorted((OUT / 'calls').rglob('request.json')):
    request, receipt = read(p), read(p.with_name('receipt.json'))
    response_path = p.with_name('response.json')
    receipts.append(receipt)
    check('wire:' + str(p.relative_to(OUT)), request['model'] == cfg['model'] and request['temperature'] == 0 and request['max_tokens'] == 16384
          and request['provider']['only'] == ['digitalocean'] and request['provider']['allow_fallbacks'] is False
          and request['reasoning'] == {'enabled': True, 'effort': 'high', 'exclude': False})
    check('request-hash:' + str(p.relative_to(OUT)), sha(json.dumps(request, ensure_ascii=False, separators=(',', ':'))) == receipt['requestSha256'])
    arm, tid = p.relative_to(OUT / 'calls').parts[:2]
    if arm != 'objrun':
        sample_index = int(p.relative_to(OUT / 'calls').parts[2].split('-')[-1])
        expected = [{'role': 'user', 'content': prompt_by_id[tid] + suffix}]
        if arm == 'binary':
            samples = read(OUT / 'tasks' / arm / tid / 'samples.json')
            for item in samples[:sample_index]:
                expected += [{'role': 'assistant', 'content': item['answer']}, {'role': 'user', 'content': 'passed' if item['grade']['passed'] else 'failed'}]
        check('model-information-boundary:' + str(p.relative_to(OUT)), request['messages'] == expected)
    else:
        check('native-tool-whitelist:' + str(p.relative_to(OUT)), all(t['function']['name'] in {'submit', 'verify', 'task_tree', 'node_load'} for t in request.get('tools', [])))
    if response_path.exists() and receipt['httpStatus'] == 200:
        response = read(response_path)
        check('returned-model-provider:' + str(p.relative_to(OUT)), response.get('provider') == 'DigitalOcean' and response.get('model') in {cfg['model'], cfg['canonicalModel']})
        if receipt.get('finishReason') == 'length' and not response.get('choices', [{}])[0].get('message', {}).get('content'):
            length_empty += 1

delivery_rows = []
for r in records:
    task = OUT / 'tasks' / r['arm'] / r['id']
    candidate = (task / 'final-answer.txt').read_text(encoding='utf-8')
    check('final-candidate-hash:' + r['arm'] + '/' + r['id'], sha(candidate) == r['candidateSha256'])
    if r['grade'].get('valid'):
        verdict = scorer.judge(candidate, book[r['id']])
        check('offline-final-acceptance:' + r['arm'] + '/' + r['id'], verdict['passed'] == r['grade']['passed'] and verdict['candidateSha256'] == r['grade']['candidateSha256'])
    if r['arm'] != 'objrun' and (task / 'samples.json').exists():
        samples = read(task / 'samples.json')
        check('attempt-ceiling:' + r['arm'] + '/' + r['id'], 1 <= len(samples) <= (1 if r['arm'] == 'baseline' else 5))
        check('EX-early-stop:' + r['arm'] + '/' + r['id'], not any(s['grade']['passed'] for s in samples[:-1]))
        check('selected-delivery:' + r['arm'] + '/' + r['id'], samples[-1]['answer'] == candidate)
        for sample in samples:
            check('sample-grade:' + r['arm'] + '/' + r['id'] + '/' + str(sample['index']), scorer.judge(sample['answer'], book[r['id']])['passed'] == sample['grade']['passed'])
    if r['arm'] == 'objrun':
        check('native-evidence:' + r['id'], all((task / x).exists() for x in ['trace.json', 'tree.json', 'engine/data/h2h.sqlite', 'tool-permissions.json']))
        if r['grade'].get('valid'):
            connection = sqlite3.connect(str(task / 'engine/data/h2h.sqlite'))
            connection.row_factory = sqlite3.Row
            native_task = connection.execute('select * from task').fetchone()
            deadline = native_task['created_at'] + native_task['solve_seconds'] * 1000
            selected = None
            for unit in connection.execute('select * from task_repair order by unit desc'):
                for message in connection.execute("select body from agent_bot_msg where instance=? and unit=? and kind='call' and at<=? order by seq desc", (unit['instance'], unit['unit'], deadline)):
                    try:
                        handins = [x for x in reversed(json.loads(message['body']).get('calls', [])) if x.get('name') == 'submit']
                        if handins:
                            selected = handins[0].get('input', {}).get('answer', '')
                            break
                    except (ValueError, TypeError):
                        pass
                if selected is not None:
                    break
            connection.close()
            check('native-final-submit-before-solve-deadline:' + r['id'], selected == candidate)
        for item in read(task / 'feedback.json') if (task / 'feedback.json').exists() else []:
            exposed = item['exposed']
            check('native-feedback-boundary:' + r['id'] + '/' + item['candidateSha256'], set(exposed) == {'value', 'note'} and
                  type(exposed['value']) is bool and exposed['note'] in ['', 'End with a boxed finite numeric answer in the requested unit.'] and
                  (item['node'] == 'parsed' or exposed['note'] == ''))
    tools = []
    if r['arm'] == 'objrun' and (task / 'trace.json').exists():
        for message in read(task / 'trace.json'):
            if message.get('kind') == 'call':
                try:
                    tools.extend(c.get('name') for c in json.loads(message['body']).get('calls', []))
                except (ValueError, TypeError):
                    pass
    delivery_rows.append({'arm': r['arm'], 'id': r['id'], 'valid': r['grade'].get('valid'),
                          'passed': r['grade'].get('passed') if r['grade'].get('valid') else '',
                          'candidateSha256': r['candidateSha256'], 'actualCostUsd': r['actualCostUsd'],
                          'unknownCostCount': r['unknownCostCount'], 'unknownCostUpperBoundUsd': r['unknownCostUpperBoundUsd'],
                          'seconds': r['seconds'], 'sampleCount': r.get('sampleCount', ''),
                          'verifyToolCalls': tools.count('verify'), 'submitToolCalls': tools.count('submit'),
                          'treeNodes': len(read(task / 'tree.json')) if (task / 'tree.json').exists() else '',
                          'stoppingReason': r.get('stoppingReason', r.get('error', ''))})
    check('per-task-dollar-ceiling:' + r['arm'] + '/' + r['id'], r['budgetSpentUsd'] <= cfg['perQuestionDollarCap'] + 1e-9)

actual = sum(r['actualCostUsd'] or 0 for r in receipts)
unknown = sum(bool(r['unknownCost']) for r in receipts)
unknown_upper = sum(r['upperBoundUsd'] for r in receipts if r['unknownCost'])
check('receipt-cost-conservation', math.isclose(actual, sum(r['actualCostUsd'] for r in records), rel_tol=1e-9, abs_tol=1e-9))
check('pilot-total-dollar-ceiling', actual + unknown_upper <= cfg['pilotBudgetUsd'])
dispatches = list((OUT / 'calls').rglob('dispatch.json'))
check('no-unreceipted-dispatch', all(p.with_name('receipt.json').exists() for p in dispatches))

def percentile(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, math.ceil(q * len(values)) - 1)]

arm_stats = {}
for arm in cfg['arms']:
    rr = [r for r in records if r['arm'] == arm]
    arm_stats[arm] = {'records': len(rr), 'valid': sum(bool(r['grade'].get('valid')) for r in rr),
                      'passed': sum(bool(r['grade'].get('valid') and r['grade']['passed']) for r in rr),
                      'actualCostUsd': sum(r['actualCostUsd'] for r in rr),
                      'unknownCostCount': sum(r['unknownCostCount'] for r in rr),
                      'meanSeconds': statistics.mean(r['seconds'] for r in rr),
                      'p95CostUsd': percentile([r['budgetSpentUsd'] for r in rr], .95),
                      'budgetStops': sum('Budget' in str(r.get('stoppingReason', '')) for r in rr)}
five_sample_estimates = []
for r in records:
    if r['arm'] == 'independent':
        samples = read(OUT / 'tasks/independent' / r['id'] / 'samples.json')
        costs = [s['receipt']['actualCostUsd'] if s['receipt']['actualCostUsd'] is not None else s['receipt']['upperBoundUsd'] for s in samples]
        five_sample_estimates.append(5 * statistics.mean(costs))
# EX early stopping censors the number of draws; this is explicitly a planning estimate.
observed_reserve = []
for p in (OUT / 'calls').rglob('dispatch.json'):
    observed_reserve.append(read(p)['reserveUsd'])
recommended = math.ceil((percentile(five_sample_estimates, .95) + max(observed_reserve)) * 100) / 100
budget_replay = []
for record in records:
    folder = OUT / 'calls' / record['arm'] / record['id']
    events = sorted([(read(p), read(p.with_name('receipt.json')), str(p.relative_to(OUT))) for p in folder.rglob('dispatch.json')], key=lambda x: x[0]['atUtc'])
    spent = 0
    for dispatch, receipt, path in events:
        if spent + dispatch['reserveUsd'] > recommended + 1e-9:
            budget_replay.append({'arm': record['arm'], 'id': record['id'], 'firstBlockedDispatch': path,
                                  'spentBeforeUsd': spent, 'newRequestReserveUsd': dispatch['reserveUsd']})
            break
        spent += receipt['actualCostUsd'] if receipt['actualCostUsd'] is not None else receipt['upperBoundUsd']
formal_estimate = sum(arm_stats[a]['actualCostUsd'] / 21 * 416 for a in cfg['arms'])
formal_upper_projection = (actual + unknown_upper) / 21 * 416
budget = {'recommendedPerQuestionMultiArmUsd': recommended, 'rule': 'ceil_cent(p95(5*mean observed independent candidate cost per dev question) + maximum observed full-request reserve)',
          'planningEstimateNotMeasuredFiveDrawCosts': True, 'observedPilotActualUsd': actual,
          'formal416FourArmPointEstimateUsd': formal_estimate,
          'formal416FourArmIncludingUnknownProjectionUsd': formal_upper_projection,
          'formal416FourArmPlanningReserveUsd': math.ceil(formal_upper_projection * 1.5),
          'suggestedInitialProjectBudgetUsd': math.ceil(formal_upper_projection * 1.5 / 5) * 5,
          'formalMultiArmHardCeilingUsd': 416 * 3 * recommended,
          'formalAllFourArmsHardCeilingIfSameCapUsd': 416 * 4 * recommended,
          'observedTrajectoryBudgetReplayBlockedTasks': budget_replay,
          'singleArmCostNotIncludedInMultiArmHardCeiling': True,
          'formalNotLaunched': True, 'pilotRepresentativeness': '21 development questions; _sol selection; long-tail costs remain uncertain'}
audit = {'allPassed': all(c['passed'] for c in checks), 'checks': len(checks), 'failures': [c for c in checks if not c['passed']],
         'actualCostUsd': actual, 'unknownCostCount': unknown, 'unknownCostUpperBoundUsd': unknown_upper,
         'modelCalls': len(receipts), 'arms': arm_stats, 'finishReasons': dict(Counter(r.get('finishReason') for r in receipts)),
         'lengthResponsesWithEmptyContent': length_empty, 'details': checks}
(LOCAL / 'AUDIT.json').write_text(json.dumps(audit, indent=2) + '\n', encoding='utf-8')
(LOCAL / 'FORMAL_BUDGET.json').write_text(json.dumps(budget, indent=2) + '\n', encoding='utf-8')
with (LOCAL / 'RESULTS.csv').open('w', newline='', encoding='utf-8-sig') as handle:
    writer = csv.DictWriter(handle, fieldnames=list(delivery_rows[0]))
    writer.writeheader()
    writer.writerows(delivery_rows)
lines = ['# SciBench 21题四组试跑结果', '', '范围：七教材各三题的独立开发集，排除于正式416题。', '',
         '| 组别 | 有效 / 21 | 通过 / 21 | 实际美元 | 平均秒数 |', '|---|---:|---:|---:|---:|']
labels = {'baseline': '单次', 'objrun': '完整ObjRun', 'independent': '独立采样，EX早停，最多5次', 'binary': '二值反馈，最多5次'}
for arm in cfg['arms']:
    s = arm_stats[arm]
    lines.append(f"| {labels[arm]} | {s['valid']} | {s['passed']} | {s['actualCostUsd']:.6f} | {s['meanSeconds']:.1f} |")
lines += ['', f'实际费用合计 ${actual:.6f}，费用未知 {unknown} 笔，未知费用预留 ${unknown_upper:.6f}。',
          'ObjRun 的 atkins-dev-001 与 atkins-dev-002 为接口异常：HTTP200仅有空白保活正文，约303秒后关闭，没有交付答案或generation ID。两条结果保留为未知，不按答错处理；原始请求、响应和费用预留完整保存。',
          f"输出达到16k上限 {sum(r.get('finishReason') == 'length' for r in receipts)} 次，其中content为空 {length_empty} 次；保留费用和原始响应，不从thinking提取答案。",
          f"审计 {len(checks)} 项，全部通过：{audit['allPassed']}。评分控制、反馈边界、固定wire参数、候选身份和费用守恒的细节见 AUDIT.json。",
          '校验通过表示记录与协议核验通过，不表示84条均取得有效评分；本轮有效评分82条、接口异常2条。',
          '', '模型：OpenRouter deepseek/deepseek-v4.1-flash，DigitalOcean，high，temperature=0，max_tokens=16384。纯文本，无检索与Python执行。',
          '', f'正式实验建议三种多轮方法每题共同费用上限 ${recommended:.2f}；独立／二值最多5次，ObjRun保留c5/600秒/4分支/12units。',
          f'按已记录请求及其最坏费用预留顺序回放该上限，{len(budget_replay)} 条试跑轨迹会提前停止；这不是重新调用模型的低预算实验。',
          f'按试跑已知实际费用线性外推，416题四组约 ${formal_estimate:.2f}；计入未知费用预留后约 ${formal_upper_projection:.2f}，再加50%计划预留约 ${math.ceil(formal_upper_projection*1.5)}。这是开发集外推，不是账单保证；三组共同硬上限合计 ${416*3*recommended:.2f}，另计单次组。',
          f'建议首批费用计划按5美元向上取整为 ${math.ceil(formal_upper_projection*1.5/5)*5}。若四组都采用每题${recommended:.2f}硬上限，全部416题的理论上限为${416*4*recommended:.2f}；费用计划与理论最坏上限含义不同。',
          '600秒为任务求解时钟，报告耗时还包含引擎启动、API轮询和清理。有效ObjRun最终答案另从SQLite核对为求解截止前的真实submit，不使用超时后的答案或verify候选。',
          '', '预算上限由费用决定，未依据试跑正确率选参。EX早停导致没有观察每题完整五次费用，因此使用已观察候选成本估计并额外保留一请求预留，细节见 FORMAL_BUDGET.json。',
          '', '本次仅用于接入验收和预算校准；不据21题分数宣称方法收益或替代416题正式结果。正式实验尚未启动。']
(LOCAL / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({'allPassed': audit['allPassed'], 'checks': len(checks), 'failures': audit['failures'][:10], 'arms': arm_stats, 'budget': budget}))
