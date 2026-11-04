"""One bounded engineering recovery; never erase attempts, deadlines or expenses."""
from pathlib import Path
import hashlib
import json
import os
import shutil
import time

def prepare(project, previous, destination):
    project, previous, destination = map(Path, (project, previous, destination))
    assert previous.parent == destination.parent == project / 'pm-runtime/runs'
    state = json.loads((previous / 'outputs/status.json').read_text())
    assert state['stage'] in ('complete', 'complete_with_exceptions') and state['completed'] == 24
    pid = state['pid']
    cmd = Path('/proc') / str(pid) / 'cmdline'
    assert not (cmd.exists() and str(previous / 'package/run.py').encode() in cmd.read_bytes()), 'Previous controller still alive'
    assert not destination.exists(), 'Recovery already prepared; inspect, do not overwrite'
    cfg = json.loads((previous / 'package/experiment.json').read_text())
    assert cfg['formalAuthorized'] is False and cfg['taskCount'] == 12
    for path, expected in json.loads((previous / 'outputs/source-pins.json').read_text()).items():
        assert hashlib.sha256((previous / path).read_bytes()).hexdigest() == expected, 'Previous source changed'
    for p in (previous / 'outputs/calls').rglob('dispatch.json'):
        assert (p.parent / 'receipt.json').exists(), 'Unresolved dispatch requires reconciliation'
    retry_groups = []
    result_paths = list((previous / 'outputs/results').glob('*/*.json'))
    assert len(result_paths) == 24
    for path in result_paths:
        record = json.loads(path.read_text())
        if record['grade']['valid']: continue
        assert record.get('error', '').startswith(('TransportChainFailed:', 'TransportChainExhausted')), record
        samples_path = previous / 'outputs/tasks' / record['arm'] / record['name'] / 'samples.json'
        samples = json.loads(samples_path.read_text()) if samples_path.exists() else []
        assert all(s['grade']['valid'] for s in samples), 'Existing candidate needs explicit regrading'
        assert len(samples) < cfg['maxAttempts']
        retry_groups.append(record['arm'] + '/' + record['name'])
    destination.mkdir()
    for directory in ['data', 'vendor', 'outputs']:
        shutil.copytree(previous / directory, destination / directory)
    (destination / 'assets').symlink_to(previous / 'assets', target_is_directory=True)
    shutil.copy2(previous / 'dependency-bundle.json', destination / 'dependency-bundle.json')
    out = destination / 'outputs'; archive = out / 'previous-run-v1'; archive.mkdir()
    shutil.copytree(previous / 'package', archive / 'package')
    keep = {'calls', 'control', 'grades', 'score-cache.sqlite', 'tasks', 'results', 'environment.json', 'previous-run-v1'}
    for p in list(out.iterdir()):
        if p.name not in keep: shutil.move(str(p), str(archive / p.name))
    (archive / 'results').mkdir()
    for group in retry_groups:
        arm, name = group.split('/', 1)
        target = archive / 'results' / arm; target.mkdir(exist_ok=True)
        shutil.move(str(out / 'results' / arm / (name + '.json')), str(target / (name + '.json')))
    lineage = {'previousRoot': str(previous), 'recoveryRoot': str(destination), 'previousState': state,
        'atEpoch': time.time(), 'retryGroups': retry_groups, 'reusedValidResults': 24 - len(retry_groups),
        'sourcePins': json.loads((archive / 'source-pins.json').read_text()),
        'originalDeadlinesRetained': True, 'existingCandidatesAndScoresRetained': True,
        'allPriorExpensesAndUnknownReservationsRetained': True, 'additionalLogicalAttemptQuota': 0,
        'recoveryBatchesAllowed': 1, 'recoveryTransportIndices': [3, 4, 5],
        'reason': 'Fixed BaseTen shared pool returned upstream HTTP429; serialize and pace the single recovery batch'}
    (out / 'recovery-lineage.json').write_text(json.dumps(lineage, indent=2) + '\n')
    # Bootstrap's initial descriptive label preceded the capability fix. Raw process
    # records and the real namespace sentinel control establish the actual boundary.
    (out / 'isolation-correction.json').write_text(json.dumps({'bootstrapLabel': 'clearenv',
        'actualEnvironmentClearer': '/usr/bin/env -i', 'bubblewrapVersion': '0.4.0',
        'evidence': 'control/attempt-*/isolation.stdout.txt and grades/*/invocation-*/execution-*/process.json'}, indent=2) + '\n')
    print(json.dumps({'prepared': str(destination), 'retryGroups': len(retry_groups), 'reuse': 24-len(retry_groups)}))
