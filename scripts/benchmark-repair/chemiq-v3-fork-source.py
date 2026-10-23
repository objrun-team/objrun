"""Append-only execution fork; every paid V2 source stays at its original recipe hash."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
RECIPE = ROOT / 'docs/repair-2026-10-08/chemiq-f-journal-preparations-v2/repair-2026-10-09T09-40-03-707Z/recipe.json'
assert hashlib.sha256(RECIPE.read_bytes()).hexdigest() == 'eca1ba0b646844c247539d66436614659abb2e7d65c55c78a4cd6f09bcbb9d5c'
pins = json.loads(RECIPE.read_bytes())['sourcePins']
for pin in pins:
    data = Path(pin['path']).read_bytes()
    assert len(data) == pin['bytes'] and hashlib.sha256(data).hexdigest() == pin['sha256'], pin['path']
names = ['chemiq-f-journal-campaign', 'chemiq-f-journal-contract', 'chemiq-f-paid-admission',
         'chemiq-f-owned', 'chemiq-f-grading-recorder', 'chemiq-f-model-witness',
         'audit-chemiq-f-journal', 'chemiq-private-boundary', 'chemiq-cold96',
         'chemiq-other-paid-discovery', 'chemiq-launch-preparation', 'chemiq-paid-seed']
mapping = {n + '-v2.ts': n + '-v3.ts' for n in names}
for old, new in mapping.items():
    text = (HERE / old).read_text(encoding='utf-8')
    for before, after in mapping.items():
        text = text.replace(before, after)
    text = re.sub(r'\b(chemiq-f-[a-z-]+)-v2\b', r'\1-v3', text)
    text = text.replace('chemiq-f-formal-readiness-v3-900s', 'chemiq-f-formal-readiness-v2-900s')
    text = text.replace('chemiq-f-journal-implementation-v2', 'chemiq-f-journal-implementation-v3')
    text = text.replace('chemiq-solver-cold-observation-v2', 'chemiq-solver-cold-observation-v3')
    text = text.replace('exact-original-loopback-bridge-v2', 'exact-original-loopback-bridge-v3')
    text = text.replace('chemiq-pilot-user-resource-directive-v2', 'chemiq-pilot-user-resource-directive-v2')
    text = text.replace("join(HOME,'user-resource-directive.json')", "join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/user-resource-directive.json')")
    text = text.replace("join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v3/user-resource-directive.json')", "join(ROOT,'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/user-resource-directive.json')")
    text = text.replace('chemiq-resource-financial-preflight-v2', 'chemiq-resource-financial-preflight-v3')
    with (HERE / new).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
with (HERE / 'chemiq-f-provider-proxy-v3.ts').open('x', encoding='utf-8', newline='\n') as stream:
    stream.write((HERE / 'scientific-journal-proxy.ts').read_text(encoding='utf-8'))
home = ROOT / 'docs/repair-2026-10-08/chemiq-f-journal-implementation-v3'
home.mkdir(exist_ok=True)
proof = {'protocol': 'chemiq-f-append-only-execution-fork-v3', 'parentRecipePin': {
    'path': str(RECIPE), 'bytes': RECIPE.stat().st_size, 'sha256': hashlib.sha256(RECIPE.read_bytes()).hexdigest()},
    'originalSourcePins': pins, 'originalSourcesUnchanged': True, 'newFiles': list(mapping.values()) + ['chemiq-f-provider-proxy-v3.ts'],
    'modelCalls': 0, 'paidLockTaken': False}
with (home / 'fork-source-proof.json').open('x', encoding='utf-8', newline='\n') as stream:
    stream.write(json.dumps(proof, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'newFiles': proof['newFiles'], 'originalSourcesUnchanged': True, 'modelCalls': 0}))
