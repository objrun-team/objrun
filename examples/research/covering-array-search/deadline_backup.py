"""One-shot OS-scheduled backup of the original campaign deadline guard."""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psutil

run = Path(sys.argv[1]).resolve()
deadline = json.loads((run / 'deadline.json').read_text())
while time.time() < deadline['deadline_epoch']:
    time.sleep(min(1, deadline['deadline_epoch'] - time.time()))

alive = []
for name in ('process.json', 'supervisor-process.json'):
    try:
        value = json.loads((run / name).read_text())
        entries = [value] if 'pid' in value else [value.get('runner', {}), value.get('engine', {})]
        for item in entries:
            try:
                p = psutil.Process(item['pid'])
                if abs(p.create_time() - item['created']) < .5:
                    alive.append(item['pid'])
            except (psutil.Error, KeyError):
                pass
    except (OSError, ValueError):
        pass

receipt = {'checked_utc': datetime.now(timezone.utc).isoformat(),
           'original_deadline_utc': deadline['deadline_utc'],
           'owned_processes_alive': alive}
if (run / 'deadline-guard.json').exists() and not alive:
    receipt['action'] = 'primary deadline guard already stopped owned processes'
else:
    receipt['action'] = 'invoke trusted deadline guard; never start model or search'
    result = subprocess.run([sys.executable, str(run / 'guard.py'), str(run)], check=False)
    receipt['guard_exit_code'] = result.returncode
(run / 'deadline-backup-receipt.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
