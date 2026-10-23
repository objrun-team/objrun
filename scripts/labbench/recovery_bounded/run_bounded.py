"""Apply the human's final-attempt caps without changing frozen solve code."""
from pathlib import Path
import fcntl
import os
import subprocess
import sys
import time

ROOT = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else None
if ROOT:
    sys.path.insert(0, str(ROOT / 'operations'))
from core import read, save, sha, now, key, attempt_home, ledger, valid, NAME


def alive(pid, script, home):
    p = Path('/proc') / str(pid or 0) / 'cmdline'
    return p.exists() and script.encode() in p.read_bytes() and str(home).encode() in p.read_bytes()


def final_classification(terminal):
    if terminal['valid']:
        return 'actual-valid'
    evidence = str(terminal.get('error') or '') + ' ' + str(terminal.get('stopReason') or '')
    if any(x in evidence.lower() for x in ['timeout', 'timed out', 'deadlineexhausted']):
        return 'timeout-default-failure'
    return 'other-infrastructure-default-failure'


def main(root):
    lock = (root / 'controller.lock').open('a+b')
    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    policy = read(root / 'control/final-attempt-policy.json')
    caps = {x['identity']: x for x in policy['boundaries']}
    jobs = read(root / 'recovery.json')['jobs']
    for rel, digest in read(root / 'operations-pins.json').items():
        assert sha(root / rel) == digest
    for rel, digest in read(root / 'bounded-operations-pins.json').items():
        assert sha(root / rel) == digest
    assert policy['supersedesUnlimitedRetries'] and len(caps) == 8
    save(root / 'control/admission.json', {'modelSlots': 1})
    while True:
        selected, dispositions, active, pending, homes_all = {}, {}, [], [], []
        for job in jobs:
            k = key(job)
            homes = sorted((root / 'attempts' / job['arm'] / job['id']).glob('attempt-*'))
            homes_all.extend(homes)
            assert len(homes) <= caps[k]['lastAttemptNumber'], ('CapExceeded', k)
            terms = []
            for home in homes:
                if (home / 'terminal.json').exists():
                    terms.append((home, read(home / 'terminal.json')))
                    continue
                meta = read(home / 'attempt.json')
                process = read(home / 'worker-process.json') if (home / 'worker-process.json').exists() else {}
                if alive(process.get('pid'), 'worker.py', home):
                    active.append({'identity': k, 'home': home.relative_to(root).as_posix(), 'pid': process['pid']})
                elif time.time() <= meta['createdEpoch'] + 900:
                    active.append({'identity': k, 'home': home.relative_to(root).as_posix(), 'pid': process.get('pid'), 'awaitingOrphanSafeDeadline': True})
                else:
                    save(home / 'terminal.json', {'number': meta['number'], 'identity': meta['identity'], 'arm': job['arm'], 'id': job['id'], 'valid': False, 'result': None, 'resultSha256': None, 'error': 'WorkerExitedWithoutTerminal', 'stopReason': None, 'requiresUser': False, 'endedEpoch': time.time(), 'classification': 'infrastructure-stopped-by-final-policy'}, True)
            first = next(((home, t) for home, t in terms if t['valid']), None)
            if first:
                home, t = first
                assert home == homes[-1], ('AttemptAfterFirstValid', k)
                selected[k] = {'home': home.relative_to(root).as_posix(), 'terminal': t, 'resultSha256': t['resultSha256']}
                dispositions[k] = {'identity': k, 'classification': 'actual-valid', 'source': home.relative_to(root).as_posix(), 'attemptNumber': t['number'], 'solverValid': True, 'administrativeScore': None}
            elif len(homes) == caps[k]['lastAttemptNumber'] and len(terms) == len(homes):
                home, t = terms[-1]
                assert not t['valid']
                dispositions[k] = {'identity': k, 'classification': final_classification(t), 'source': home.relative_to(root).as_posix(), 'attemptNumber': t['number'], 'solverValid': False, 'administrativeScore': 0, 'answerFabricated': False, 'terminalError': t.get('error'), 'terminalSha256': sha(home / 'terminal.json')}
            elif not any(a['identity'] == k for a in active):
                assert len(homes) == caps[k]['attemptsAtBoundary'] and not caps[k]['activeAtBoundary']
                pending.append(job)
        save(root / 'first-valid.json', selected)
        save(root / 'FINAL_DISPOSITIONS.json', dispositions)
        if not active and pending:
            job = pending[0]
            k = key(job)
            number = caps[k]['lastAttemptNumber']
            home = attempt_home(root, job, number)
            home.mkdir(parents=True, exist_ok=False)
            meta = {**job, 'number': number, 'identity': NAME + '/' + k + '/attempt-%04d' % number, 'createdEpoch': time.time(), 'createdAtUtc': now(), 'fullSolveBudgetSeconds': 600, 'oldTimeOrCandidateReused': False, 'finalAttemptPolicySha256': sha(root / 'control/final-attempt-policy.json'), 'finalAttempt': True}
            save(home / 'attempt.json', meta, True)
            env = {**os.environ, 'PATH': str(root / 'frozen/bin') + ':/usr/bin:/bin', 'HOME': str(root / 'frozen/runtime-home'), 'PYTHONDONTWRITEBYTECODE': '1', 'NO_PROXY': '127.0.0.1,localhost'}
            with (home / 'worker.stdout.log').open('ab') as out, (home / 'worker.stderr.log').open('ab') as err:
                child = subprocess.Popen([str(root / 'frozen/venv/bin/python'), str(root / 'operations/worker.py'), str(root), str(home)], cwd=root, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err, start_new_session=True)
            save(home / 'worker-process.json', {'pid': child.pid, 'atUtc': now()}, True)
            active.append({'identity': k, 'home': home.relative_to(root).as_posix(), 'pid': child.pid})
            homes_all.append(home)
        complete = len(dispositions) == 8 and not active
        save(root / 'status.json', {'stage': 'bounded_ready_for_report' if complete else 'running_bounded', 'pid': os.getpid(), 'atUtc': now(), 'selectedCount': len(selected), 'resolvedCount': len(dispositions), 'targetCount': 8, 'attemptCount': len(homes_all), 'firstValid': selected, 'active': active, 'workerConcurrency': 1, 'blocked': None, 'finalAttemptCaps': {k: v['lastAttemptNumber'] for k, v in caps.items()}, 'accounting': ledger(homes_all), 'policy': 'bounded final attempts, timeout administrative zero; raw solver validity unchanged'})
        if complete:
            save(root / 'bounded-controller-done.json', {'atUtc': now(), 'pid': os.getpid(), 'resolvedCount': 8, 'firstValidCount': len(selected), 'policySha256': sha(root / 'control/final-attempt-policy.json')}, True)
            return
        time.sleep(5)


if __name__ == '__main__':
    main(ROOT)
