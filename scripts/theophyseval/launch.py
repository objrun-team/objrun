"""Launch an owned controller with the existing key in memory only."""
from pathlib import Path
import json
import os
import re
import shutil
import subprocess
import sys

REPO = Path(__file__).resolve().parents[2]
ROOT = REPO.parent / 'tmp/theophyseval-20261016-v3'
mode = sys.argv[1] if len(sys.argv) > 1 else 'pilot'
if mode == 'formal':
    raise RuntimeError('LocalFormalLaunchDisabled: formal TheoPhysEval must use the separately frozen novaeve entrypoint')
config = ROOT / 'package' / ('formal.json' if mode == 'formal' else 'experiment.json')
cfg = json.loads(config.read_text())
key = None
for line in (REPO / '.env').read_text(encoding='utf-8-sig').splitlines():
    match = re.match(r'^\s*(?:export\s+)?OPENROUTER_API_KEY\s*=\s*(.*?)\s*$', line)
    if match:
        key = match[1].strip().strip('\"\'')
        break
if not key:
    raise RuntimeError('MissingExistingAuthorizedKey')
bun = shutil.which('bun.exe')
if not bun:
    candidates = [Path(os.environ['APPDATA']) / 'npm/node_modules/bun/bin/bun.exe', Path(os.environ['USERPROFILE']) / '.bun/bin/bun.exe']
    bun = next((str(p) for p in candidates if p.exists()), None)
if not bun:
    raise RuntimeError('BunExecutableUnavailable')
env = {k: v for k, v in os.environ.items() if not k.endswith('_API_KEY')}
env.update(OPENROUTER_API_KEY=key, TPE_RUN=cfg['run'], TPE_CONFIG=str(config))
out = ROOT / 'outputs' / cfg['run']
out.mkdir(parents=True, exist_ok=True)
if mode == 'preflight':
    p = subprocess.run([bun, '-e', "const {observe,balance}=await import('./package/common.ts');await observe();await balance(true);console.log('Provider route, tariff and account preflight passed; no model request.');"], cwd=ROOT, env=env, capture_output=True, text=True)
    if key in p.stdout or key in p.stderr:
        raise RuntimeError('UnexpectedCredentialInOutputSuppressed')
    print(p.stdout[-1800:]);print(p.stderr[-1000:])
    raise SystemExit(p.returncode)
if (out / 'launch.json').exists():
    raise RuntimeError('ExistingLaunchMustNotBeRepeated')
with (out / 'controller.stdout.log').open('ab') as a, (out / 'controller.stderr.log').open('ab') as b:
    child = subprocess.Popen([bun, str(ROOT / 'package/run.ts')], cwd=ROOT, env=env, stdin=subprocess.DEVNULL,
                             stdout=a, stderr=b, creationflags=subprocess.CREATE_NO_WINDOW)
record = {'pid': child.pid, 'run': cfg['run'], 'entry': str(ROOT / 'package/run.ts'), 'config': str(config), 'keyWritten': False}
(out / 'launch.json').write_text(json.dumps(record, indent=2) + '\n')
print(json.dumps(record))
