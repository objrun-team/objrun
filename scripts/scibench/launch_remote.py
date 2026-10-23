"""Launch the single authorized pilot with an in-memory credential supplied on stdin."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root = Path(__file__).resolve().parents[1]
out = root / 'outputs/canonical'
out.mkdir(parents=True, exist_ok=True)
payload = json.load(sys.stdin)
key = payload.pop('key')
if not isinstance(key, str) or not key.strip():
    raise RuntimeError('MissingCredential')
if (out / 'launch.json').exists():
    old = json.loads((out / 'launch.json').read_text())
    raise RuntimeError('PilotAlreadyLaunchedInspectExistingPid:' + str(old['pid']))
env = {k: v for k, v in os.environ.items() if not k.endswith('_API_KEY')}
env.update(OPENROUTER_API_KEY=key, PATH=str(root / 'bin') + ':/usr/bin:/bin', PYTHONUTF8='1', NO_PROXY='127.0.0.1,localhost')
with (out / 'controller.stdout.log').open('ab') as stdout, (out / 'controller.stderr.log').open('ab') as stderr:
    child = subprocess.Popen([str(root / 'bin/bun'), str(root / 'package/run.ts')], cwd=root, env=env,
                             stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr, start_new_session=True)
record = {'pid': child.pid, 'root': str(root), 'entry': 'package/run.ts',
          'atUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
          'credentialWritten': False, 'metadata': payload}
(out / 'launch.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
