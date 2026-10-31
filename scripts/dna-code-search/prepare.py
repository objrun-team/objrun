import hashlib
import json
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from checker import check, independent_check

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = Path(__file__).resolve().parent
BASE = ROOT / 'data/dna-code-search'
RUN = BASE / ('run-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ'))
RUN.mkdir(parents=True)
for name in ['work', 'reference', 'verified', 'jobs', 'requests', 'engine', 'runtime']:
    (RUN/name).mkdir()
shutil.copytree(BASE/'preparation/reference/opendata', RUN/'reference/opendata')
for name in ['published-fss.txt', 'published-gc.txt', 'openrouter-model.json', 'zenodo-record.json']:
    shutil.copy2(BASE/'preparation'/name, RUN/'reference'/name)
for name in ['GOAL.md', 'checker.py', 'guard.py']:
    shutil.copy2(SCRIPTS/name, RUN/name)
words = (RUN/'reference/published-fss.txt').read_text().split()
report = check(words)
report['independent_valid'] = independent_check(words)
assert report['valid'] and report['independent_valid'] and report['size'] == 676
(RUN/'baseline-audit.json').write_text(json.dumps(report, indent=2))
(RUN/'best-verified.json').write_text(json.dumps({**report, 'source': 'published baseline'}, indent=2))
shutil.copy2(RUN/'reference/published-fss.txt', RUN/'work/candidate.txt')
shutil.copy2(RUN/'GOAL.md', RUN/'reference/GOAL.md')
shutil.copytree(ROOT/'app/src', RUN/'runtime/src')
shutil.copy2(ROOT/'app/package.json', RUN/'runtime/package.json')
subprocess.run(['cmd', '/c', 'mklink', '/J', str(RUN/'runtime/node_modules'), str(ROOT/'app/node_modules')], check=True, capture_output=True)
adapter = RUN/'runtime/src/llm/index.ts'
source = adapter.read_text(encoding='utf-8')
old = 'export const HARD_WALL_MS = 900_000;'
assert source.count(old) == 1
adapter.write_text(source.replace(old, 'export const HARD_WALL_MS = 18_000_000;'), encoding='utf-8')
files = {str(p.relative_to(RUN/'runtime/src')): hashlib.sha256(p.read_bytes()).hexdigest()
         for p in (RUN/'runtime/src').rglob('*') if p.is_file()}
(RUN/'runtime-manifest.json').write_text(json.dumps({
    'repository_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'snapshot_hashes': files,
    'runtime_only_change': 'llm/index.ts HARD_WALL_MS 900000 -> 18000000; original source unchanged',
    'request_policy': 'Proxy removes max_tokens/max_completion_tokens and provider price ceilings; only campaign deadline governs. Provider context/server limits remain.',
    'count_fields': '2147483647 is an operational unlimited sentinel required by the existing finite-integer schema; no attainable count cap in five hours.',
    'python': sys.executable,
}, indent=2))
(BASE/'latest-run.txt').write_text(str(RUN), encoding='utf-8')
print(str(RUN))
