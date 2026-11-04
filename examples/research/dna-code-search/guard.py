"""Independent campaign deadline guard; only stop the processes owned by this run."""
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import psutil

run = Path(sys.argv[1]).resolve()
deadline = json.loads((run/'deadline.json').read_text())
remaining = max(0, deadline['deadline_epoch'] - time.time())
end_mono = time.monotonic() + remaining
while time.time() < deadline['deadline_epoch'] and time.monotonic() < end_mono:
    if (run/'completion.json').exists():
        sys.exit(0)
    time.sleep(min(5, max(.01, end_mono-time.monotonic())))
receipt = {'time': datetime.now(timezone.utc).isoformat(), 'reason': 'five_hour_deadline', 'actions': []}
procfile = run/'process.json'
if procfile.exists():
    info = json.loads(procfile.read_text())
    if info.get('container'):
        result = subprocess.run(['docker', 'stop', '--time', '0', info['container']], capture_output=True, text=True, timeout=30)
        receipt['actions'].append({'container': info['container'], 'returncode': result.returncode})
    # Allow the runner to save its final state; the container already stopped.
    time.sleep(3)
    for key in ['engine', 'runner']:
        item = info.get(key, {})
        try:
            proc = psutil.Process(item['pid'])
            if abs(proc.create_time()-item['created']) < 1:
                proc.kill()
                receipt['actions'].append({'process': key, 'pid': item['pid'], 'killed': True})
        except (psutil.Error, KeyError):
            pass
(run/'deadline-guard.json').write_text(json.dumps(receipt, indent=2))
