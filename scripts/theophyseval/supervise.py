"""Wait for pilot completion, audit it, and launch the authorized full suite once."""
import json
from pathlib import Path
import subprocess
import sys
import time
from datetime import datetime, timezone
from audit import audit

ROOT = Path(__file__).resolve().parents[1]
SOURCE = Path(__file__).resolve().parents[3] / 'TgEngin/scripts/theophyseval'
PILOT = 'theophyseval-pilot-20261016-v3'
FORMAL = 'theophyseval-formal-20261016-v3'


def save(state):
    path = ROOT / 'outputs/supervisor-status.json'
    temp = path.with_suffix('.tmp')
    temp.write_text(json.dumps({**state, 'at_utc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}, indent=2) + '\n')
    temp.replace(path)


def wait_run(run):
    path = ROOT / 'outputs' / run / 'status.json'
    while True:
        if path.exists():
            try:
                s = json.loads(path.read_text())
                save({'phase': 'waiting', 'run': run, 'stage': s['stage'], 'arms': s['arms']})
                if s['stage'] in {'complete', 'complete_with_exceptions', 'needs_attention'} and not s['active']:
                    return s
                age = (datetime.now(timezone.utc) - datetime.fromisoformat(s['atUtc'].replace('Z', '+00:00'))).total_seconds()
                if age > 120:
                    save({'phase': 'controller_stale', 'run': run, 'seconds_since_status': age, 'pid': s['pid']})
                    raise RuntimeError('ControllerStatusStale:' + run)
            except json.JSONDecodeError:
                pass
        time.sleep(10)


def main():
    save({'phase': 'pilot_running', 'run': PILOT})
    state = wait_run(PILOT)
    if state['stage'] != 'complete':
        save({'phase': 'pilot_needs_attention', 'run': PILOT, 'stage': state['stage']})
        return
    pilot = audit(PILOT)
    controls = {name: json.loads((ROOT / 'control' / name).read_text())['passed'] for name in ['grading-controls.json', 'special-grading-controls.json', 'container-controls.json', 'engine-controls.json', 'timeout-controls.json', 'auth-controls.json', 'control-plane-controls.json']}
    if not pilot['passed'] or not all(controls.values()):
        save({'phase': 'gate_rejected', 'pilot': pilot, 'controls': controls})
        return
    acceptance = {'passed': True, 'pilot': PILOT, 'pilot_audit': pilot, 'controls': controls,
                  'user_authorized_scope': '49 automatic problems x four arms; start full after successful selfcheck and pilot'}
    (ROOT / 'control/pilot-acceptance.json').write_text(json.dumps(acceptance, indent=2) + '\n')
    save({'phase': 'launching_formal', 'run': FORMAL})
    p = subprocess.run([sys.executable, str(SOURCE / 'launch.py'), 'formal'], capture_output=True, text=True)
    if p.returncode:
        save({'phase': 'formal_launch_failed', 'error': p.stderr[-1500:]})
        return
    wait_run(FORMAL)
    report = audit(FORMAL)
    save({'phase': 'complete' if report['passed'] else 'formal_needs_attention', 'run': FORMAL, 'audit': report})


if __name__ == '__main__':
    main()
