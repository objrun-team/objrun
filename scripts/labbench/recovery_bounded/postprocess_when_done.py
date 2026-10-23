"""Model-free final aggregation as soon as the capped solver controller exits."""
from pathlib import Path
import fcntl
import json
import sys
import time

root = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(root / 'operations'))
from core import read, save, sha, now
from report_bounded import generate

lock = (root / 'bounded-postprocess.lock').open('a+b')
fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
try:
    while True:
        status = read(root / 'status.json')
        if status['stage'] == 'complete':
            break
        if status['stage'] == 'bounded_ready_for_report':
            process = Path('/proc') / str(read(root / 'launch.json')['pid']) / 'cmdline'
            if process.exists() and process.read_bytes():
                time.sleep(1)
                continue
            assert not status['active']
            for home in (root / 'attempts').glob('*/*/attempt-*'):
                assert (home / 'terminal.json').exists()
                process = Path('/proc') / str(read(home / 'worker-process.json')['pid']) / 'cmdline'
                assert not process.exists() or str(home).encode() not in process.read_bytes()
            audit, result = generate(root)
            assert audit['allPassed']
            save(root / 'final-freeze.json', {'atUtc': now(), 'resolvedCount': 8, 'firstValidCount': result['firstValidCount'], 'auditPassed': True, 'policySha256': sha(root / 'control/final-attempt-policy.json')}, True)
            status.update(stage='complete', atUtc=now(), resolvedCount=8, selectedCount=result['firstValidCount'])
            save(root / 'status.json', status)
            print(json.dumps({'atUtc': now(), 'auditPassed': True, 'checks': audit['checkCount'], 'finalScored': result['finalScored']['arms'], 'fees': result['fees']}), flush=True)
            break
        if status['stage'] not in ['running_bounded', 'bounded_ready_for_report']:
            raise RuntimeError('UnexpectedStage:' + status['stage'])
        time.sleep(5)
except Exception as error:
    save(root / 'bounded-postprocess-error.json', {'atUtc': now(), 'error': type(error).__name__ + ':' + str(error), 'modelCalls': 0})
    status = read(root / 'status.json')
    status.update(stage='needs_attention', atUtc=now(), postprocessError=type(error).__name__ + ':' + str(error))
    save(root / 'status.json', status)
    raise
