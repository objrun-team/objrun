"""Authorized valid12 pilot only. This entry point cannot launch test244."""
from __future__ import annotations
from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
from lean_worker import Grader, digest, save
from sequence import messages, check_messages
from transport import Transport, BudgetStop

def run(root):
    root = Path(root).resolve(); os.chdir(root)
    cfg = json.loads((root / 'package/experiment.json').read_text())
    catalog = json.loads((root / 'data/public-pilot.json').read_text())
    assert cfg['formalAuthorized'] is False and cfg['scope'] == 'valid12-development-only'
    assert cfg['taskCount'] == len(catalog) == 12 and all(q['split'] == 'valid' for q in catalog)
    if cfg.get('transportRetryOffset', 0):
        lineage = json.loads((root / 'outputs/recovery-lineage.json').read_text())
        assert cfg['transportRetryOffset'] == 3 and cfg['maxTransportAttempts'] == 3 and cfg['recoveryBatchesAllowed'] == 1
        assert lineage['originalDeadlinesRetained'] and lineage['allPriorExpensesAndUnknownReservationsRetained']
        previous_cfg = json.loads((root / 'outputs/previous-run-v1/package/experiment.json').read_text())
        changed = {k for k in set(cfg) | set(previous_cfg) if cfg.get(k) != previous_cfg.get(k)}
        assert changed <= {'runId', 'modelConcurrency', 'requestSpacingSeconds', 'transportBackoffSeconds', 'transportRetryOffset', 'recoveryBatchesAllowed'}, 'ScientificProtocolChangedDuringRecovery'
    controls = json.loads((root / 'outputs/controls.json').read_text())
    assert controls['allPassed'], 'ControlsRequired'
    files = [p for d in ['package', 'vendor', 'data'] for p in (root / d).iterdir() if p.is_file()]
    pins = {str(p.relative_to(root)): digest(p.read_bytes()) for p in files}
    assert pins == controls['sourcePins'], 'SourceChangedAfterControls'
    save(root / 'outputs/source-pins.json', pins)
    def frozen():
        if any(digest((root / p).read_bytes()) != h for p, h in pins.items()): raise RuntimeError('FrozenSourceChanged')
    transport = Transport(root, cfg, os.environ['OPENROUTER_API_KEY'])
    preflight = transport.preflight(); save(root / 'outputs/admission.json', preflight)
    environment = json.loads((root / 'outputs/environment.json').read_text())
    grader = Grader(root, cfg, digest(json.dumps(environment, sort_keys=True)))
    assert grader.identity == controls['graderIdentity'], 'GraderChangedAfterControls'
    state_lock = threading.Lock(); active = []; stage = 'running'; stop = threading.Event()
    def records(): return [json.loads(p.read_text()) for p in (root / 'outputs/results').glob('*/*.json')] if (root / 'outputs/results').exists() else []
    def status():
        with state_lock:
            data = records()
            save(root / 'outputs/status.json', {'runId': cfg['runId'], 'stage': stage, 'pid': os.getpid(), 'updatedAtEpoch': time.time(),
                  'planned': 24, 'completed': len(data), 'active': list(active), 'graderActive': grader.active, 'graderPeak': grader.peak,
                  'arms': {a: {'recorded': sum(r['arm'] == a for r in data), 'valid': sum(r['arm'] == a and r['grade']['valid'] for r in data),
                               'passed': sum(r['arm'] == a and r['grade']['valid'] and r['grade']['passed'] for r in data)} for a in cfg['arms']},
                  **transport.accounting(), 'fatal': transport.fatal})
    def timer():
        while not stop.wait(15): status()
    thread = threading.Thread(target=timer, daemon=True); thread.start()
    def execute(task, arm):
        group = arm + '/' + task['name']; directory = root / 'outputs/tasks' / group
        path = root / 'outputs/results' / arm / (task['name'] + '.json')
        if path.exists(): return json.loads(path.read_text())
        directory.mkdir(parents=True, exist_ok=True)
        started = directory / 'started.json'
        if started.exists(): start = json.loads(started.read_text())['atEpoch']
        else:
            start = time.time(); save(started, {'atEpoch': start, 'arm': arm, 'id': task['id'], 'deadlineEpoch': start + cfg['perTaskSeconds']})
        deadline = start + cfg['perTaskSeconds']
        history_path = directory / 'samples.json'; history = json.loads(history_path.read_text()) if history_path.exists() else []
        with state_lock: active.append({'arm': arm, 'id': task['id']})
        result = {'arm': arm, 'id': task['id'], 'name': task['name'], 'promptSha256': task['promptSha256'], 'startedAtEpoch': start}
        reason = 'five_attempt_ceiling'
        try:
            frozen()
            for index in range(len(history), cfg['maxAttempts']):
                if history and history[-1]['grade']['passed']: reason = 'first_correct'; break
                if time.time() >= deadline: raise BudgetStop('task_time_cap')
                sent = messages(cfg['systemPrompt'], task['prompt'], arm, history)
                check_messages(sent, cfg['systemPrompt'], task, arm, history)
                answer, receipt, call_directory = transport.generate(group, index, sent, deadline)
                (directory / ('candidate-%02d.txt' % index)).write_text(answer)
                grade = grader.accept(task, answer).result(timeout=max(1, deadline - time.time()))
                sample = {'index': index, 'answer': answer, 'candidateSha256': digest(answer), 'grade': grade, 'callDirectory': call_directory,
                          'receipt': receipt, 'finishedAtEpoch': time.time()}
                history.append(sample); save(history_path, history)
                if not grade['valid']: raise RuntimeError('PrivateGraderInfrastructureError')
                if grade['passed']: reason = 'first_correct'; break
            result['grade'] = history[-1]['grade'] if history else {'valid': True, 'passed': False, 'outcome': 'budget_no_candidate'}
        except BudgetStop as exc:
            reason = str(exc); result['grade'] = history[-1]['grade'] if history else {'valid': True, 'passed': False, 'outcome': 'budget_no_candidate'}
        except Exception as exc:
            reason = 'infrastructure_exception'; result['error'] = str(exc)
            result['grade'] = {'valid': False, 'passed': False, 'outcome': reason}
        result.update(sampleCount=len(history), answer=history[-1]['answer'] if history else '', candidateSha256=digest(history[-1]['answer'] if history else ''),
                      stoppingReason=reason, completedAtEpoch=time.time(), seconds=time.time() - start, **transport.accounting(group))
        (directory / 'final-answer.txt').write_text(result['answer']); save(path, result)
        with state_lock: active.remove({'arm': arm, 'id': task['id']})
        status(); print(json.dumps({k: result[k] for k in ['arm', 'id', 'sampleCount', 'stoppingReason', 'actualCostUsd', 'unknownCostCount']}), flush=True)
        return result
    try:
        jobs = [(q, cfg['arms'][(i + j) % 2]) for i, q in enumerate(catalog) for j in range(2)]
        with ThreadPoolExecutor(max_workers=cfg['modelConcurrency'], thread_name_prefix='solve') as pool:
            futures = [pool.submit(execute, q, arm) for q, arm in jobs]
            for future in as_completed(futures): future.result()
        stage = 'complete' if len(records()) == 24 and all(r['grade']['valid'] for r in records()) else 'complete_with_exceptions'
    finally:
        stop.set(); thread.join(timeout=2); grader.close(); status()
    import report
    report.finish(str(root))

if __name__ == '__main__': run(sys.argv[1])
