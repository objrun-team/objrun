"""Build a new isolated runnable package using the audited SciCode engine snapshot."""
from pathlib import Path
import hashlib
import json
import shutil
import sys
import os

REPO = Path(__file__).resolve().parents[4]
ORIGIN = Path('C:/Users/y1252/Documents/Codex/2026-10-15/s-c/outputs/scicode/full-results/reproduction/package/engine')
root = Path(sys.argv[1]).resolve()
package = root / 'package'
package.mkdir(parents=True, exist_ok=True)
for source in (REPO / 'examples/benchmark/scibench/experiments').iterdir():
    if source.suffix in {'.py', '.ts', '.json'}:
        shutil.copyfile(source, package / source.name)
for name in ['grade.py', 'stand.py', 'G.json']:
    shutil.copyfile(REPO / 'examples/benchmark/scibench' / name, package / name)
if not (package / 'engine').exists():
    shutil.copytree(ORIGIN, package / 'engine', ignore=shutil.ignore_patterns('node_modules', '__pycache__', '.env'))
pins = []
for directory, dirs, files in os.walk(package / 'engine', followlinks=False):
    dirs[:] = sorted(d for d in dirs if d not in {'node_modules', '__pycache__'})
    for name in sorted(files):
        p = Path(directory) / name
        pins.append({'path': str(p.relative_to(package)).replace('\\', '/'), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()})
(package / 'engine-origin.json').write_text(json.dumps({'origin': str(ORIGIN), 'provenance': 'audited SciCode original experiment engine snapshot; copied without modification', 'files': pins}, indent=2) + '\n')
print(json.dumps({'root': str(root), 'engineFiles': len(pins)}))
