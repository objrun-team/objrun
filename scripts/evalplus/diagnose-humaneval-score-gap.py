"""Read-only paired score and saved native-search diagnosis; no model requests."""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HE = ROOT / 'docs/evalplus-20261012/humaneval'
def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

expected = read(HE / 'task-ids.json')
baseline = {r['officialId']: r for p in (HE / 'full/results/baseline').glob('*.json') for r in [read(p)]}
independent = {r['officialId']: r for p in (HE / 'full/results/independent').glob('*.json') for r in [read(p)]}
combined = read(HE / 'objrun-fireworks-v1/recovery/combined-progress-checkpoint.json')
sources = {p['officialId']: p for p in combined['provenance']}
objrun = {tid: read(p['resultPath']) for tid, p in sources.items()}
passed = lambda r: r['grade'].get('valid') and r['grade'].get('passed')
base_losses = [tid for tid in expected if passed(baseline[tid]) and not passed(objrun[tid])]
base_wins = [tid for tid in expected if passed(objrun[tid]) and not passed(baseline[tid])]
ind_losses = [tid for tid in expected if passed(independent[tid]) and not passed(objrun[tid])]
ind_wins = [tid for tid in expected if passed(objrun[tid]) and not passed(independent[tid])]
focus = set(base_losses + ind_losses + base_wins)
all_nodes, details = [], []
for tid in expected:
    out = Path(sources[tid]['resultPath']).parents[2]
    short = tid.replace('/', '-')
    path = out / 'tasks/objrun' / short / 'engine/data/h2h.sqlite'
    connection = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        task = dict(connection.execute('select * from task').fetchone())
        units = [dict(r) for r in connection.execute('select * from task_repair order by unit')]
        node_count = len({u['node'] for u in units})
        verify_hashes = []
        for message in connection.execute("select body from agent_bot_msg where kind='call'"):
            try:
                for call in json.loads(message['body']).get('calls', []):
                    answer = call.get('input', {}).get('answer')
                    if call.get('name') == 'verify' and isinstance(answer, str):
                        verify_hashes.append(hashlib.sha256(answer.encode()).hexdigest())
            except (ValueError, TypeError):
                pass
        all_nodes.append({'officialId': tid, 'nodes': node_count, 'nativeState': task['state'], 'passed': passed(objrun[tid]),
                          'verifyCalls': len(verify_hashes), 'uniqueVerifyCandidates': len(set(verify_hashes))})
        if tid not in focus:
            continue
        messages = [dict(r) for r in connection.execute('select * from agent_bot_msg order by unit,seq')]
        calls = []
        messages_by_kind = {}
        for m in messages:
            messages_by_kind[m['kind']] = messages_by_kind.get(m['kind'], 0) + 1
            if m['kind'] != 'call':
                continue
            try:
                payload = json.loads(m['body'])
            except (ValueError, TypeError):
                continue
            for call in payload.get('calls', []):
                answer = call.get('input', {}).get('answer')
                calls.append({'name': call.get('name'), 'instance': m['instance'], 'unit': m['unit'],
                              'answerSha256': hashlib.sha256(answer.encode()).hexdigest() if isinstance(answer, str) else None,
                              'matchesFinalAnswer': answer == objrun[tid].get('answer'),
                              'answer': answer})
        # Inspect actual recorded model context for public verification results.
        feedback = []
        for p in (out / 'calls/objrun' / short).rglob('request.json'):
            for m in read(p).get('messages', []):
                text = m.get('content', '')
                if isinstance(text, str) and ('Public base tests failed' in text or m.get('role') == 'tool'):
                    feedback.append({'requestPath': str(p), 'role': m.get('role'), 'content': text[:1800]})
        result = objrun[tid]
        details.append({'officialId': tid, 'provider': sources[tid]['provider'], 'baselinePassed': passed(baseline[tid]),
                        'independentPassed': passed(independent[tid]), 'objrunPassed': passed(result),
                        'basePassed': result['grade'].get('groups', {}).get('base', {}).get('passed'),
                        'nodes': node_count, 'nativeState': task['state'], 'nativeVerdict': result.get('engineVerdict'),
                        'seconds': result['seconds'], 'modelCalls': result['modelCalls'],
                        'protocolRepairCalls': result.get('protocolRepairCalls'), 'units': units,
                        'messageKinds': messages_by_kind, 'calls': calls,
                        'verifyCandidates': len([c for c in calls if c['name'] == 'verify']),
                        'uniqueVerifyCandidates': len({c['answerSha256'] for c in calls if c['name'] == 'verify'}),
                        'allVerifyCandidatesMatchFinal': all(c['matchesFinalAnswer'] for c in calls if c['name'] == 'verify'),
                        'actualPublicFeedback': feedback,
                        'taskChecks': task.get('checks'), 'taskCheckLeft': task.get('check_left')})
    finally:
        connection.close()

evidence = {'baselineWinsObjrunLoses': base_losses, 'objrunWinsBaselineLoses': base_wins,
            'independentWinsObjrunLoses': ind_losses, 'objrunWinsIndependentLoses': ind_wins,
            'oneNodeTasks': sum(r['nodes'] == 1 for r in all_nodes),
            'multiNodeTasks': sum(r['nodes'] > 1 for r in all_nodes),
            'multipleDistinctVerifyCandidateTasks': [r['officialId'] for r in all_nodes if r['uniqueVerifyCandidates'] > 1],
            'nodeCountDistribution': {n: sum(r['nodes'] == n for r in all_nodes) for n in sorted({r['nodes'] for r in all_nodes})},
            'details': details, 'allTaskNodeCounts': all_nodes,
            'noCoreChanges': True, 'noModelRequests': True, 'originalResultsUnchanged': True}
path = HE / 'diagnosis/final-score-gap-evidence.json'
path.write_text(json.dumps(evidence, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
compact = {k: v for k, v in evidence.items() if k not in ['details', 'allTaskNodeCounts']}
compact['focus'] = [{k: r[k] for k in ['officialId', 'provider', 'basePassed', 'objrunPassed', 'nodes', 'nativeState', 'seconds', 'modelCalls', 'protocolRepairCalls', 'verifyCandidates', 'uniqueVerifyCandidates', 'allVerifyCandidatesMatchFinal']} for r in details]
print(json.dumps(compact, ensure_ascii=True, indent=2))
