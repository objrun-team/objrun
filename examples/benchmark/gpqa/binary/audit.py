"""Read-only audit of a binary GPQA run; never prints questions, answers, or credentials."""
import argparse
import gzip
import hashlib
import json
from collections import Counter
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument('run_id')
args = parser.parse_args()
root = Path(__file__).resolve().parents[4]
output = root / 'docs/gpqa' / args.run_id
store = root / '.phase1-data/gpqa-binary' / args.run_id
manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
summary = json.loads((output / 'summary.json').read_text(encoding='utf-8'))
ledger = json.loads((output / 'api-ledger.json').read_text(encoding='utf-8'))
errors = []


def check(condition, message):
    if not condition:
        errors.append(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


source = json.loads((output / 'source.json').read_text(encoding='utf-8'))
for pinned in source['pins']:
    check(digest((Path(source['runtime']) / pinned['path']).read_bytes()) == pinned['sha256'], 'runtime_source_changed:' + pinned['path'])
check(digest((root / '.phase1-data/gpqa/dataset/gpqa_diamond.csv').read_bytes()) == manifest['datasetSha256'], 'dataset_changed')
for path in output.glob('manifest-resume-*.json'):
    resumed = json.loads(path.read_text(encoding='utf-8'))
    for field in ('tasks', 'model', 'thinking', 'search', 'temperature', 'requestedSeed',
                  'datasetShuffleSeed', 'maxTokensPerRequest', 'checksPerAttempt',
                  'maxBranches', 'maxDeadSiblings', 'solveSeconds', 'datasetSha256', 'sourceDigest'):
        check(resumed[field] == manifest[field], 'resume_changed_' + field)
finished = [call for call in ledger['calls'] if call.get('finishedAt')]
counts = Counter()
models = Counter()
tool_names = Counter()
finish_reasons = Counter()
total_cost = 0.0
verify_outputs = set()
for call in finished:
    sequence = call['sequence']
    request_raw = gzip.decompress(Path(call['requestFile']).read_bytes())
    response_raw = gzip.decompress(Path(call['responseFile']).read_bytes())
    check(digest(request_raw) == call['requestSha256'], f'request_hash_{sequence}')
    check(digest(response_raw) == call['responseSha256'], f'response_hash_{sequence}')
    request, response = json.loads(request_raw), json.loads(response_raw)
    check(request['model'] == 'deepseek-flash', f'model_{sequence}')
    check(request.get('thinking') == {'type': 'disabled'}, f'thinking_{sequence}')
    check('reasoning_effort' not in request, f'legacy_thinking_toggle_{sequence}')
    check(request.get('max_tokens') == 8192, f'output_budget_{sequence}')
    check(request.get('temperature') == 0, f'temperature_{sequence}')
    for tool in request.get('tools', []):
        name = tool.get('function', {}).get('name')
        tool_names[name] += 1
        check(name in manifest['allowedTools'], f'forbidden_tool_{sequence}')
    tool_ids = {}
    for message in request.get('messages', []):
        for tool_call in message.get('tool_calls', []):
            tool_ids[tool_call.get('id')] = tool_call.get('function', {}).get('name')
        if message.get('role') == 'tool' and tool_ids.get(message.get('tool_call_id')) == 'verify':
            content = message.get('content')
            try:
                feedback = json.loads(content) if isinstance(content, str) else content
            except (ValueError, TypeError):
                feedback = None
            if isinstance(feedback, dict) and feedback.get('valid') is True and 'pass' in feedback:
                check(feedback['pass'] in (0, 1), f'nonbinary_verify_{sequence}')
                check(not feedback.get('note'), f'feedback_note_{sequence}')
                check(feedback.get('why') in ('', 'correct evaluated to false'), f'feedback_explanation_{sequence}')
                verify_outputs.add((call['route'], message.get('tool_call_id'), content))
    check(call['httpStatus'] == 200 and not call.get('fault'), f'api_fault_{sequence}')
    usage = response.get('usage', {})
    counts['prompt_tokens'] += usage.get('prompt_tokens', 0)
    counts['completion_tokens'] += usage.get('completion_tokens', 0)
    cached = usage.get('prompt_cache_hit_tokens', usage.get('prompt_tokens_details', {}).get('cached_tokens', 0))
    counts['cached_tokens'] += cached
    check(usage.get('completion_tokens_details', {}).get('reasoning_tokens', 0) == 0, f'reasoning_usage_{sequence}')
    for choice in response.get('choices', []):
        message = choice['message']
        check(not message.get('reasoning_content') and not message.get('reasoning'), f'reasoning_content_{sequence}')
        finish_reasons[choice.get('finish_reason')] += 1
    expected_cost = ((usage.get('prompt_tokens', 0) - cached) * .3 + cached * .006 + usage.get('completion_tokens', 0) * 1.2) / 1e6
    check(abs(expected_cost - call.get('accountedUpperBoundUsd', 0)) < 1e-9, f'cost_{sequence}')
    total_cost += call.get('accountedUpperBoundUsd', 0)
    models[call.get('servedModel')] += 1
check(abs(total_cost - ledger['recordedUsageUpperBoundUsd']) < 1e-8, 'ledger_cost_sum')

events = []
event_path = output / 'grader-events.jsonl'
if event_path.exists():
    for line in event_path.read_text(encoding='utf-8').splitlines():
        if line:
            events.append(json.loads(line))
for index, event in enumerate(events):
    response = event['response']
    check(set(response) == {'value'} and type(response['value']) is bool, f'feedback_shape_{index}')
    if event['node'] == '/ready':
        check(response == {'value': True}, f'nonconstant_ready_{index}')
    else:
        check(event['node'] == '/correct', f'unknown_grader_node_{index}')
records = summary['records']
check(len({r['index'] for r in records}) == len(records), 'duplicate_task_index')
check(len({r['officialId'] for r in records}) == len(records), 'duplicate_official_id')
for record in records:
    planned = manifest['tasks'][record['index']]
    check(record['officialId'] == planned['officialId'] and record['promptSha256'] == planned['promptSha256'], 'task_prompt_changed')
    raw = json.loads((store / f"task-{record['index']}.json").read_text(encoding='utf-8'))
    check(digest(raw['answer'].encode()) == record['candidateSha256'], 'candidate_hash')
    check(record['generationValid'] and record['acceptance']['valid'], 'invalid_generation_or_acceptance')
if summary['completed']:
    check(len(records) == 198, 'final_denominator')
    check(len(finished) == len(ledger['calls']), 'unfinished_calls_at_completion')
    check(ledger['reservedUpperBoundUsd'] < 1e-8, 'outstanding_cost_at_completion')

first_grades = {}
candidate_grades = {}
for event in events:
    if event['node'] != '/correct':
        continue
    task_id = event['taskId']
    first_grades.setdefault(task_id, event['response']['value'])
    by_candidate = candidate_grades.setdefault(task_id, {})
    candidate = event['candidateSha256']
    if candidate in by_candidate:
        check(by_candidate[candidate] == event['response']['value'], 'inconsistent_same_candidate_grade')
    else:
        by_candidate[candidate] = event['response']['value']
first_correct = sum(first_grades.get(r['taskId'], False) for r in records)
recovered = sum(first_grades.get(r['taskId']) is False and r['acceptance']['passed'] for r in records)
curve = {str(n): sum(any(list(candidate_grades.get(r['taskId'], {}).values())[:n]) for r in records) for n in range(1, 6)}

report = {'runId': args.run_id, 'completed': summary['completed'], 'auditPassed': not errors,
          'auditScriptSha256': digest(Path(__file__).read_bytes()), 'verifiedRuntimeSourceFiles': len(source['pins']),
          'auditedFinishedCalls': len(finished), 'unfinishedCalls': len(ledger['calls']) - len(finished),
          'completedTasks': len(records), 'passedTasks': sum(r['acceptance']['passed'] for r in records),
          'accuracy': sum(r['acceptance']['passed'] for r in records) / 198,
          'costUpperBoundUsd': total_cost, 'usage': dict(counts), 'servedModels': dict(models),
          'toolsOnWire': dict(tool_names), 'finishReasons': dict(finish_reasons),
          'firstCheckedCandidateCorrect': first_correct, 'recoveredAfterIncorrectCheck': recovered,
          'solveByFirstNUniqueCandidateTexts': curve,
          'curveMeaning': 'First n distinct texts actually sent to the official grader; excludes exact-text repeated/final regrades. First check is not an independently run U baseline.',
          'auditedVerifyOutputsOnWire': len(verify_outputs),
          'graderEvents': len(events), 'binaryFeedbackOnly': not any('feedback' in e or 'ready' in e for e in errors),
          'failedTasks': [{'officialId': r['officialId'], 'seconds': r['seconds'], 'runtimeWhy': r['runtimeVerdict'].get('why'),
                           'costUpperBoundUsd': r['costUpperBoundUsd']} for r in records if not r['acceptance']['passed']],
          'errors': errors, 'limits': 'Token costs use frozen peak prices, not settlement; no claim that the provider alias is a pinned checkpoint.'}
report_path = output / ('audit-final.json' if summary['completed'] else 'audit-progress.json')
report_path.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps(report))
raise SystemExit(0 if not errors else 1)
