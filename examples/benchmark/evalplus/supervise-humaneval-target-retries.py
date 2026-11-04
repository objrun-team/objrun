"""Run at most ten fresh ObjRun retry rounds; preserve the original batch."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import time

ROOT = Path(__file__).resolve().parents[3]
HE = ROOT / 'docs/evalplus-20261012/humaneval'
OUT = HE / 'objrun-retry-to-target-v1'
BUN = Path('C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe')
RUNNER = ROOT / 'examples/benchmark/evalplus/run-humaneval-objrun-target-retry.ts'

def read(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))

def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + '.' + str(os.getpid()) + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=True, indent=2) + '\n', encoding='utf-8')
    tmp.replace(path)

def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()

def check_sources():
    for pin in [HE.parent / 'source-pins.json', HE / 'objrun-adapter-v1-source-pins.json', HE / 'objrun-fireworks-v1-source-pins.json', HE / 'final-verification-source-pins.json', HE / 'objrun-retry-to-target-v1-source-pins.json']:
        for item in read(pin)['files']:
            if hashlib.sha256(Path(item['path']).read_bytes()).hexdigest() != item['sha256']:
                raise RuntimeError('FrozenSourceChanged:' + item['path'])

def processes():
    engines = [read(p) for p in (OUT / 'rounds').glob('*/tasks/objrun/*/engine-process.json')]
    numeric = ','.join(str(e['pid']) for e in engines) or '0'
    cmd = "@(Get-CimInstance Win32_Process | Where-Object { $_.ProcessId -in @(" + numeric + ") -or ($_.Name -eq 'bun.exe' -and $_.CommandLine -match 'run-humaneval-objrun-(target-retry|adapter|fireworks)\\.ts') -or ($_.Name -eq 'python.exe' -and $_.CommandLine -match 'supervise-humaneval-target-retries\\.py' -and $_.CommandLine -notmatch '--verify') } | Select-Object ProcessId,Name,@{Name='CreationUtc';Expression={$_.CreationDate.ToUniversalTime().ToString('o')}},CommandLine) | ConvertTo-Json -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', cmd], capture_output=True, text=True, check=True)
    value = json.loads(result.stdout) if result.stdout.strip() else []
    rows = value if isinstance(value, list) else [value]
    owned = []
    for row in rows:
        command = row.get('CommandLine') or ''
        if 'supervise-humaneval-target-retries.py' in command and '--verify' not in command:
            owned.append(row)
        elif row['Name'].lower() == 'bun.exe':
            if any(name in command for name in ['run-humaneval-objrun-target-retry.ts', 'run-humaneval-objrun-adapter.ts', 'run-humaneval-objrun-fireworks.ts']):
                owned.append(row)
            elif any(e['pid'] == row['ProcessId'] and datetime.datetime.fromisoformat(row['CreationUtc'].replace('Z', '+00:00')) <= datetime.datetime.fromisoformat(e['atUtc'].replace('Z', '+00:00')) for e in engines):
                if not command or str(ROOT / 'app/src/main.ts').replace('/', '\\').lower() in command.replace('/', '\\').lower():
                    owned.append(row)
    return owned

def native_pass(path):
    row = read(path)
    if not row.get('grade', {}).get('valid') or not row['grade'].get('passed') or row.get('candidateHow') != 'submitted':
        raise RuntimeError('CumulativePassHasNoValidNativeSubmit:' + str(path))
    out = Path(path).parents[2]
    db_path = out / 'tasks/objrun' / row['officialId'].replace('/', '-') / 'engine/data/h2h.sqlite'
    db = sqlite3.connect(db_path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    try:
        task = dict(db.execute('select * from task').fetchone())
        deadline = task['created_at'] + task['solve_seconds'] * 1000
        completed = [dict(u) for u in db.execute("select * from task_repair where cycle='submit' and done=1")]
        matching = False
        for unit in completed:
            for message in db.execute("select body from agent_bot_msg where kind='call' and unit=? and instance=? and at<=?", (unit['unit'], unit['instance'], deadline)):
                try:
                    matching |= any(c.get('name') == 'submit' and c.get('input', {}).get('answer') == row['answer'] for c in json.loads(message['body']).get('calls', []))
                except (ValueError, TypeError):
                    pass
        if not matching:
            raise RuntimeError('NativeSubmitNotCompletedOrAnswerMismatch:' + row['officialId'])
        for group in ['base', 'plus']:
            grade = row['grade']['groups'][group]
            if not grade['passed'] or grade['checked'] != grade['cases'] or grade['correct'] != grade['cases']:
                raise RuntimeError('IncompletePassingGroup:' + row['officialId'])
    finally:
        db.close()

def report(checkpoint=False):
    state = read(OUT / 'effective-state.json')
    cfg = read(HE / 'objrun-retry-to-target-v1-config.json')
    assert len(state['fixedIds']) == len(state['cases']) == len(set(state['fixedIds'])) == 164
    passed = sum(c['passed'] for c in state['cases'].values())
    assert passed <= cfg['targetPassed'] == 160
    receipts = [read(p) for p in (OUT / 'rounds').rglob('receipt.json')]
    dispatches = list((OUT / 'rounds').rglob('dispatch.json'))
    pending = [str(p.parent) for p in dispatches if not (p.parent / 'receipt.json').exists()]
    unknown = [r for r in receipts if r.get('unknownCost') or r.get('actualCostUsd') is None]
    rounds = [read(p) for p in sorted((OUT / 'rounds').glob('*/status.json'))]
    supervisor = read(OUT / 'status.json') if (OUT / 'status.json').exists() else {}
    old = read(cfg['originalStatePath'])
    protocol = set()
    for path in (OUT / 'rounds').rglob('submit-response-attempts.json'):
        for event in read(path):
            if event.get('protocolAttempt') == 1 and event.get('generationId'):
                protocol.add((str(path).split('rounds')[1].split('tasks')[0], event.get('requestHash'), event['generationId']))
    value = {'atUtc': now(), 'metric': state['metric'], 'stage': supervisor.get('stage'),
             'originalPassed': cfg['originalPassed'], 'total': 164, 'passed': passed, 'accuracy': passed / 164,
             'minimumPassed': cfg['minimumPassed'], 'minimumReached': passed >= cfg['minimumPassed'],
             'upperTargetPassed': cfg['targetPassed'], 'targetReached': passed >= cfg['targetPassed'],
             'maxRounds': cfg['maxRounds'], 'currentRound': supervisor.get('round', 0),
             'completedRounds': len([r for r in rounds if r.get('stage') == 'complete']),
             'newPassedIds': [tid for tid in state['fixedIds'] if state['cases'][tid].get('passedAtRound', 0)],
             'remainingFailedIds': [tid for tid in state['fixedIds'] if not state['cases'][tid]['passed']],
             'attempts': len(list((OUT / 'rounds').glob('*/results/objrun/*.json'))),
             'modelCalls': len(dispatches), 'receipts': len(receipts), 'pendingRequests': pending,
             'retryKnownCostUsd': sum(r['actualCostUsd'] for r in receipts if isinstance(r.get('actualCostUsd'), (int, float))),
             'retryUnknownCostCount': len(unknown), 'retryUnknownCostUpperBoundUsd': sum(r.get('upperBoundUsd') or 0 for r in unknown),
             'originalKnownCostUsd': old['knownCostUsd'], 'originalUnknownCostCount': old['unknownCostCount'],
             'originalUnknownCostUpperBoundUsd': old['unknownCostUpperBoundUsd'],
             'protocolRepairCalls': len(protocol), 'cumulativeRoundSeconds': sum(r.get('elapsedSeconds', 0) for r in rounds),
             'processes': processes(), 'coreModified': False, 'originalSingleRunResultsPreserved': True,
             'resultRoot': str(OUT), 'stopReason': supervisor.get('stopReason'), 'error': supervisor.get('error')}
    value['totalKnownCostUsd'] = value['originalKnownCostUsd'] + value['retryKnownCostUsd']
    value['totalUnknownCostCount'] = value['originalUnknownCostCount'] + value['retryUnknownCostCount']
    value['totalUnknownCostUpperBoundUsd'] = value['originalUnknownCostUpperBoundUsd'] + value['retryUnknownCostUpperBoundUsd']
    if checkpoint:
        prior = read(OUT / 'progress-checkpoint.json') if (OUT / 'progress-checkpoint.json').exists() else {'passed': cfg['originalPassed']}
        value['newPassedSinceLastCheck'] = passed - prior['passed']
        save(OUT / 'progress-checkpoint.json', value)
    return value

def finish(stage, round_number, reason):
    save(OUT / 'status.json', {'atUtc': now(), 'pid': os.getpid(), 'stage': stage, 'round': round_number, 'stopReason': reason})
    check_sources()
    state = read(OUT / 'effective-state.json')
    for case in state['cases'].values():
        if case['passed']:
            native_pass(case['resultPath'])
    value = report(True)
    if value['pendingRequests']:
        raise RuntimeError('FinalReportHasPendingRequests')
    save(OUT / 'FINAL-RETRY-REPORT.json', value)
    lines = ['HumanEval+ ObjRun retry final status', '',
             f"Stop reason: {reason}. Rounds: {value['currentRound']}/{value['maxRounds']}. Original: 152/164. Cumulative: {value['passed']}/164 ({value['accuracy']:.5%}).",
             f"Minimum 157: {value['minimumReached']}. Upper target 160: {value['targetReached']}. This cumulative retry score does not replace the original single-run score.", '',
             'Newly passed: ' + ', '.join(value['newPassedIds']), 'Still failed: ' + ', '.join(value['remainingFailedIds']), '',
             f"New retries: {value['attempts']} task attempts, {value['modelCalls']} requests; known cost ${value['retryKnownCostUsd']:.9f}, unknown {value['retryUnknownCostCount']} with upper bound ${value['retryUnknownCostUpperBoundUsd']:.7f}.",
             f"Including the original ObjRun: known ${value['totalKnownCostUsd']:.9f}; unknown {value['totalUnknownCostCount']}, upper bound ${value['totalUnknownCostUpperBoundUsd']:.7f}.",
             f"Cumulative retry round time: {value['cumulativeRoundSeconds']:.3f} seconds. Every counted pass matches completed native submit and full base+plus checks. Core and shared grading unchanged.", '',
             'Per-task latest passing result: ' + str(OUT / 'effective-state.json'), 'All rounds/calls/SQLite/trace: ' + str(OUT / 'rounds'), 'Details: ' + str(OUT / 'FINAL-RETRY-REPORT.json')]
    (OUT / 'FINAL-RETRY-REPORT.md').write_text('\n'.join(lines) + '\n', encoding='utf-8')
    print(json.dumps(value, ensure_ascii=True), flush=True)

def main():
    cfg = read(HE / 'objrun-retry-to-target-v1-config.json')
    check_sources()
    live = [p for p in processes() if p['ProcessId'] != os.getpid()]
    if live:
        raise RuntimeError('OtherHumanEvalRunnerOrSupervisorStillLive:' + json.dumps(live))
    if report()['pendingRequests']:
        raise RuntimeError('UnreconciledPriorDispatch')
    for round_number in range(1, cfg['maxRounds'] + 1):
        state = read(OUT / 'effective-state.json')
        if state['passed'] >= cfg['targetPassed']:
            return finish('complete', round_number - 1, 'upper_target_reached')
        round_out = OUT / 'rounds' / ('round-%04d' % round_number)
        complete = round_out / 'status.json'
        if complete.exists() and read(complete).get('stage') == 'complete':
            continue
        round_out.mkdir(parents=True, exist_ok=True)
        selection = round_out / 'selected-task-ids.json'
        if not selection.exists():
            remaining = [tid for tid in state['fixedIds'] if not state['cases'][tid]['passed']]
            remaining.sort(key=lambda tid: read(state['cases'][tid]['originalResultPath']).get('seconds', 0))
            save(selection, remaining)
        assert set(read(selection)).issubset(cfg['initialFailedIds'])
        check_sources()
        save(OUT / 'status.json', {'atUtc': now(), 'pid': os.getpid(), 'stage': 'running', 'round': round_number})
        stdout = open(round_out / 'stdout.log', 'ab')
        stderr = open(round_out / 'stderr.log', 'ab')
        try:
            child = subprocess.Popen([str(BUN), 'run', str(RUNNER), 'humaneval', 'full', round_out.name], cwd=ROOT, stdout=stdout, stderr=stderr, creationflags=subprocess.CREATE_NO_WINDOW)
            save(round_out / 'launch.json', {'atUtc': now(), 'pid': child.pid, 'supervisorPid': os.getpid(), 'stdout': str(round_out / 'stdout.log'), 'stderr': str(round_out / 'stderr.log'), 'round': round_number})
            while child.poll() is None:
                time.sleep(5)
            if child.returncode:
                raise RuntimeError('RoundRunnerFailed:' + str(child.returncode))
        finally:
            stdout.close(); stderr.close()
        if report()['pendingRequests']:
            raise RuntimeError('RoundEndedWithUnreconciledDispatch')
        fatal = [read(p) for p in (round_out / 'calls').rglob('receipt.json') if read(p).get('httpStatus') in (400, 401, 402, 403, 404)]
        if fatal:
            raise RuntimeError('PersistentProviderFaultRequiresDiagnosis')
        print(json.dumps({'round': round_number, 'passed': read(OUT / 'effective-state.json')['passed']}, ensure_ascii=True), flush=True)
        live_engines = [p for p in processes() if p['ProcessId'] != os.getpid()]
        if live_engines:
            raise RuntimeError('RoundEndedWithNativeEngineStillLive:' + json.dumps(live_engines))
        if read(OUT / 'effective-state.json')['passed'] >= cfg['targetPassed']:
            return finish('complete', round_number, 'upper_target_reached')
    return finish('complete', cfg['maxRounds'], 'maximum_rounds_reached')

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--verify', action='store_true')
    parser.add_argument('--checkpoint', action='store_true')
    args = parser.parse_args()
    try:
        if args.verify:
            check_sources()
            print(json.dumps(report(args.checkpoint), ensure_ascii=True, indent=2))
        else:
            main()
    except Exception as error:
        if not args.verify:
            save(OUT / 'status.json', {'atUtc': now(), 'pid': os.getpid(), 'stage': 'needs_attention', 'error': str(error)})
        raise
