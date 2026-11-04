"""Download immutable public sources, select development questions before any model call."""
import concurrent.futures
import hashlib
import json
from pathlib import Path
import sys
import urllib.request

REVISION = 'e14e0ca3d3db0f02928a18d435b9c3d15656a7c5'
SOURCES = ['atkins', 'chemmc', 'quan', 'matter', 'fund', 'class', 'thermo']


def prepare(root):
    data, vendor = root / 'data', root / 'package/vendor'
    data.mkdir(parents=True, exist_ok=True)
    vendor.mkdir(parents=True, exist_ok=True)
    pins = []
    files = [f'dataset/original/{name}{suffix}.json' for name in SOURCES for suffix in ['', '_sol']]
    files += ['eval/post_process.py', 'eval/eval_zero.py', 'LICENSE']

    def fetch(name):
        url = f'https://raw.githubusercontent.com/mandyyyyii/scibench/{REVISION}/{name}'
        path = vendor / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_bytes(urllib.request.urlopen(url, timeout=40).read())
        raw = path.read_bytes()
        return {'path': str(path.relative_to(root)).replace('\\', '/'), 'url': url,
                'sha256': hashlib.sha256(raw).hexdigest(), 'bytes': len(raw)}

    pins = list(concurrent.futures.ThreadPoolExecutor(max_workers=6).map(fetch, files))
    for name in ['post_process.py', 'eval_zero.py']:
        (vendor / name).write_bytes((vendor / 'eval' / name).read_bytes())
    sys.path.insert(0, str(root / 'package'))
    from grade import Scorer
    scorer = Scorer(vendor)
    formal = []
    for name in SOURCES:
        for i, row in enumerate(json.loads((vendor / f'dataset/original/{name}.json').read_text(encoding='utf-8'))):
            formal.append({**row, 'id': f'scibench-{name}-{i:03}', 'sourceFile': name, 'sourceIndex': i})
    assert len(formal) == 416
    norm = lambda r: ' '.join(r['problem_text'].split())
    seen = {norm(r) for r in formal}
    assert len(seen) == 416
    pilot = []
    for name in SOURCES:
        chosen = 0
        rows = json.loads((vendor / f'dataset/original/{name}_sol.json').read_text(encoding='utf-8'))
        for i, row in enumerate(rows):
            if norm(row) in seen:
                continue
            chosen += 1
            pilot.append({**row, 'id': f'scibench-{name}-dev-{i:03}', 'sourceFile': name, 'sourceIndex': i})
            seen.add(norm(row))
            if chosen == 3:
                break
        assert chosen == 3, name
    all_rows = formal + pilot
    for row in all_rows:
        scorer.target(row)
    def save(path, obj):
        path.write_text(json.dumps(obj, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')
    save(data / 'private-tasks.json', all_rows)
    save(data / 'public-pilot.json', [scorer.public(r) for r in pilot])
    save(data / 'public-formal.json', [scorer.public(r) for r in formal])
    save(data / 'source.json', {'revision': REVISION, 'files': pins, 'formalCount': 416,
         'pilotCount': 21, 'pilotIds': [r['id'] for r in pilot], 'promptOverlap': 0,
         'selection': 'first three nonoverlapping _sol rows per source, release order',
         'publicFields': ['id', 'source', 'prompt']})
    print(json.dumps({'formal': len(formal), 'pilot': len(pilot), 'promptOverlap': 0}))


if __name__ == '__main__':
    prepare(Path(sys.argv[1]).resolve())
