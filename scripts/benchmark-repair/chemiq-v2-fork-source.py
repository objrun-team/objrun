"""Create a separate seven-file import graph from the exact frozen v1; never edit v1."""
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent
STATE = ROOT / 'docs/repair-2026-10-08/chemiq-f-journal-implementation-v1/handoff-2026-10-09/state.json'
assert hashlib.sha256(STATE.read_bytes()).hexdigest() == 'f68ca9b54ee7c8d71aaab20fbae9bf0548764fec3382aa39f46673eb08d84e80'
mapping = {
    'chemiq-f-journal-campaign.ts': 'chemiq-f-journal-campaign-v2.ts',
    'chemiq-f-journal-contract.ts': 'chemiq-f-journal-contract-v2.ts',
    'chemiq-f-paid-admission-v1.ts': 'chemiq-f-paid-admission-v2.ts',
    'chemiq-f-owned.ts': 'chemiq-f-owned-v2.ts',
    'chemiq-f-grading-recorder.ts': 'chemiq-f-grading-recorder-v2.ts',
    'chemiq-f-model-witness.ts': 'chemiq-f-model-witness-v2.ts',
    'audit-chemiq-f-journal.ts': 'audit-chemiq-f-journal-v2.ts',
}
pins = {Path(p['path']).name: p for p in json.loads(STATE.read_bytes())['completed']['frozenSourcePins']}
for old in mapping:
    assert hashlib.sha256((SOURCE / old).read_bytes()).hexdigest() == pins[old]['sha256'], old
for old, new in mapping.items():
    text = (SOURCE / old).read_text(encoding='utf-8')
    for before, after in mapping.items():
        text = text.replace(before, after)
    text = text.replace('chemiq-f-journal-campaigns', 'chemiq-f-journal-campaigns-v2')
    text = text.replace('chemiq-f-journal-preparations', 'chemiq-f-journal-preparations-v2')
    text = text.replace('.phase1-data/chemiq-f-journal', '.phase1-data/chemiq-f-journal-v2')
    text = re.sub(r'\b(chemiq-f-[a-z-]+)-v1\b', r'\1-v2', text)
    text = text.replace('chemiq-f-formal-readiness-v2/task-scope.json', 'chemiq-f-formal-readiness-v1/task-scope.json')
    text = text.replace('chemiq-f-prospective-fixed-scope-v2', 'chemiq-f-prospective-fixed-scope-v1')
    with (SOURCE / new).open('x', encoding='utf-8', newline='\n') as stream:
        stream.write(text)
print(json.dumps({'newFiles': list(mapping.values()), 'frozenV1SourcesUnchanged': True, 'modelCalls': 0}))
