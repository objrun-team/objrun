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
lines = ['# SciBench 21-Problem, Four-Arm Pilot Results', '', 'Scope: an independent development set of three problems from each of seven textbooks, excluded from the formal 416-problem set.', '',
         '| Arm | Valid / 21 | Passed / 21 | Actual USD | Mean seconds |', '|---|---:|---:|---:|---:|']
labels = {'baseline': 'Single attempt', 'objrun': 'Full ObjRun', 'independent': 'Independent sampling, early stop on EX pass, up to 5 attempts', 'binary': 'Binary feedback, up to 5 attempts'}
for arm in cfg['arms']:
    s = arm_stats[arm]
    lines.append(f"| {labels[arm]} | {s['valid']} | {s['passed']} | {s['actualCostUsd']:.6f} | {s['meanSeconds']:.1f} |")
lines += ['', f'Total actual cost: ${actual:.6f}; {unknown} requests with unknown cost; reserve for unknown costs: ${unknown_upper:.6f}.',
          'ObjRun records atkins-dev-001 and atkins-dev-002 had API failures: HTTP 200 with only whitespace keepalive content, closing after about 303 seconds without an answer or generation ID. Both remain unknown rather than incorrect; original requests, responses, and cost reserves are fully preserved.',
          f"Output reached the 16k limit {sum(r.get('finishReason') == 'length' for r in receipts)} times, with empty content in {length_empty} cases. Costs and raw responses are retained; answers are not extracted from thinking.",
          f"Audit: {len(checks)} checks; all passed: {audit['allPassed']}. See AUDIT.json for grading controls, feedback boundaries, fixed wire parameters, candidate identity, and cost reconciliation.",
          'Passing verification means the records and protocol checks passed, not that all 84 records received valid grades. This run has 82 valid grades and 2 API failures.',
          '', 'Model: OpenRouter deepseek/deepseek-v4.1-flash, DigitalOcean, high, temperature=0, max_tokens=16384. Text only, without search or Python execution.',
          '', f'For the formal experiment, recommend a shared per-problem cost cap of ${recommended:.2f} for the three multi-round methods. Independent sampling/binary feedback allow up to 5 attempts; ObjRun retains c5/600 seconds/4 branches/12 units.',
          f'Replaying recorded requests and their worst-case cost reserves in order under this cap would stop {len(budget_replay)} pilot trajectories early. This is not a low-budget experiment with fresh model calls.',
          f'Linear extrapolation from known actual pilot costs gives approximately ${formal_estimate:.2f} for 416 problems across four arms, or ${formal_upper_projection:.2f} including reserves for unknown costs, and approximately ${math.ceil(formal_upper_projection*1.5)} with a further 50% planning reserve. This is a development-set projection, not a billing guarantee. The shared hard caps for three arms total ${416*3*recommended:.2f}, with the single-attempt arm counted separately.',
          f'Recommend rounding the initial cost plan up to the next $5: ${math.ceil(formal_upper_projection*1.5/5)*5}. If all four arms use a per-problem hard cap of ${recommended:.2f}, the theoretical maximum for all 416 problems is ${416*4*recommended:.2f}. A cost plan and a theoretical worst-case bound have different meanings.',
          'The 600-second limit is the task-solving clock; reported elapsed time also includes engine startup, API polling, and cleanup. Valid ObjRun final answers are independently checked in SQLite as actual submit calls before the solve deadline; answers after timeout and verify candidates are not used.',
          '', 'Budget caps are determined by costs, without selecting parameters from pilot accuracy. Early stopping on EX pass prevents observing all five attempts for each problem, so estimates use observed candidate costs plus a reserve for one additional request. See FORMAL_BUDGET.json.',
          '', 'This run is only for integration acceptance and budget calibration. Its 21-problem scores do not establish method gains or replace formal 416-problem results. The formal experiment has not started.']
(LOCAL / 'REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
print(json.dumps({'allPassed': audit['allPassed'], 'checks': len(checks), 'failures': audit['failures'][:10], 'arms': arm_stats, 'budget': budget}))
