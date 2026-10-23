"""Canonical, auditable conversion of downloaded AIME/ChemBench parquet data."""
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import pyarrow.parquet as pq

HOME = Path(os.environ.get('PHASE1_DATA_ROOT', '/data'))
slug = sys.argv[1]
home = HOME / slug
rows = []
if slug == 'aime':
    for row in pq.read_table(home / 'raw/aimo-validation-aime.parquet').to_pylist():
        match = re.search(r'(\d{4})_AIME_(I|II)_Problems/Problem_(\d+)', row['url'])
        if not match or match[1] != '2024': continue
        year, part, number = int(match[1]), match[2], int(match[3])
        rows.append({'id': f'aime-{year}-{part}-{number}', 'year': year, 'contest': part, 'number': number, 'problem': row['problem'], 'answer': int(str(row['answer']).strip()), 'url': row['url']})
    assert len(rows) == 30
    raw = home / 'raw'
    official = [json.loads(line) for line in (raw / 'math-ai-aime25.jsonl').read_text(encoding='utf-8').splitlines()]
    crosscheck = [json.loads(line) for part in ['I', 'II'] for line in (raw / f'opencompass-aime2025-{part}.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(official) == len(crosscheck) == 30
    for i, (row, other) in enumerate(zip(official, crosscheck)):
        answer = int(str(row['answer']).strip())
        assert answer == int(re.sub(r'\D', '', str(other['answer'])))
        part, number = ('I', i+1) if i < 15 else ('II', i-14)
        rows.append({'id': f'aime-2025-{part}-{number}', 'year': 2025, 'contest': part, 'number': number, 'problem': row['problem'], 'answer': answer})
    rows.sort(key=lambda row: (row['year'], row['contest'], row['number']))
    name = 'aime.jsonl'
elif slug == 'chembench':
    for file in sorted((home / 'parquet').glob('*.parquet')):
        for row in pq.read_table(file).to_pylist():
            # Same one-example representation as the existing official adapter.
            assert len(row['examples']) == 1
            raw = row['examples'][0]
            example = {'input': raw['input']}
            if raw.get('target') is not None: example['target'] = raw['target']
            if raw.get('target_scores') is not None:
                example['target_scores'] = json.loads(raw['target_scores']) if isinstance(raw['target_scores'], str) else raw['target_scores']
            rows.append({'uuid':row['uuid'],'topic':file.stem,'name':row['name'],'keywords':row['keywords'],'metrics':row['metrics'],'preferred_score':row['preferred_score'],'relative_tolerance':row.get('relative_tolerance'),'example':example})
    assert len(rows) == 2785, len(rows)
    name = 'chembench.jsonl'
else: raise ValueError(slug)
output = home / name
output.write_text(''.join(json.dumps(row, ensure_ascii=False) + '\n' for row in rows), encoding='utf-8')
record = json.loads((home / 'source.json').read_text(encoding='utf-8'))
record['derivedDataset'] = {'file': name, 'tasks': len(rows), 'sha256': hashlib.sha256(output.read_bytes()).hexdigest()}
(home / 'source.json').write_text(json.dumps(record, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'benchmark': slug, 'tasks': len(rows), 'sha256': record['derivedDataset']['sha256']}))
