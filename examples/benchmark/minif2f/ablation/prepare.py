"""Prepare the fixed development catalog and a copy of existing public Lean assets."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import tarfile
import time

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
ASSETS = REPO / '.phase1-data/minif2f-restoration-public'
OLD = Path('E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415')

def sha(data):
    return hashlib.sha256(data).hexdigest()

def save(p, obj):
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')

def norm_statement(s):
    s = re.sub(r'theorem\s+[^\s(]+', 'theorem', s, count=1)
    return re.sub(r'\s+', ' ', s).strip()

def stratum(name):
    if name.startswith('amc'): return 'amc'
    if name.startswith('aime'): return 'aime'
    if name.startswith('imo'): return 'imo'
    if name.startswith('mathd_algebra'): return 'mathd_algebra'
    if name.startswith('mathd_numbertheory'): return 'mathd_numbertheory'
    return 'other'

def catalog(out):
    lock = json.loads((ASSETS / 'public-lock.json').read_text(encoding='utf-8'))
    source = ASSETS / 'deepseek-minif2f.jsonl'
    expected = next(e['sha256'] for e in lock['entries'] if e['file'] == source.name)
    assert sha(source.read_bytes()) == expected
    rows = [json.loads(line) for line in (ASSETS / 'problems.jsonl').read_text(encoding='utf-8').splitlines() if line.strip()]
    assert len(rows) == 488
    test = [r for r in rows if r['split'] == 'test']
    valid = [r for r in rows if r['split'] == 'valid']
    assert len(test) == len(valid) == 244
    raw_valid = {r['name']: r for r in map(json.loads, source.read_text(encoding='utf-8').splitlines()) if r['split'] == 'valid'}
    for r in valid:
        original = raw_valid[r['name']]
        assert r['header'] == original['header'] and r['statement'] == original['formal_statement']
    test_statements = {norm_statement(r['statement']) for r in test}
    test_informal = {re.sub(r'\s+', ' ', r['informal']).strip() for r in test if r['informal'].strip()}
    candidates = [r for r in valid if norm_statement(r['statement']) not in test_statements and re.sub(r'\s+', ' ', r['informal']).strip() not in test_informal]
    selected = []
    for group in ['amc', 'aime', 'imo', 'mathd_algebra', 'mathd_numbertheory', 'other']:
        ordered = sorted((r for r in candidates if stratum(r['name']) == group), key=lambda r: sha(('minif2f-valid-pilot-20261019:' + r['id']).encode()))
        assert len(ordered) >= 2, group
        selected.extend(ordered[:2])
    prompt_suffix = '\n\nWrite a complete Lean 4 proof. Return the entire Lean file in one lean code fence. Keep the theorem statement exactly as supplied. Mathlib is available. Do not use sorry or new axioms.'
    public = []
    for r in selected:
        q = {k: r[k] for k in ['id', 'name', 'split', 'header', 'informal', 'statement']}
        q['stratum'] = stratum(r['name'])
        q['prompt'] = r['informal'] + '\n\n```lean\n' + r['header'] + r['statement'] + '\n```' + prompt_suffix
        q.update({k + 'Sha256': sha(q[k].encode()) for k in ['header', 'statement', 'prompt']})
        public.append(q)
    save(out / 'data/public-pilot.json', public)
    save(out / 'data/selection.json', {'rule': 'Two per predeclared source stratum, SHA256 ascending of fixed seed plus stable id; normalized theorem-name-free statements and whitespace-normalized informal text checked against test before selection', 'seed': 'minif2f-valid-pilot-20261019', 'ids': [q['id'] for q in public], 'eligibleValid': len(candidates), 'validSourceSha256': expected, 'sourcePins': lock['pins'], 'bookSha256': sha((ASSETS / 'problems.jsonl').read_bytes()), 'publicPilotSha256': sha((out / 'data/public-pilot.json').read_bytes()), 'testRunAuthorized': False})
    vendor = out / 'vendor'; vendor.mkdir(exist_ok=True)
    for source_path, name in [(REPO / 'examples/benchmark/minif2f/stand.py', 'source_stand.py'), (ASSETS / 'kimina-models.py', 'kimina_models.py'), (ASSETS / 'public-lock.json', 'public-lock.json')]:
        (vendor / name).write_bytes(source_path.read_bytes())
    print(json.dumps({'selected': [r['id'] for r in public], 'root': str(out)}, ensure_ascii=False), flush=True)

def dependencies(out):
    archive = out / 'lean-dependencies.tar.gz'
    assert not archive.exists(), 'Dependency bundle exists; verify it rather than overwrite'
    lean_zip = OLD / 'downloads/lean-4.15.0-linux.zip'
    assert sha(lean_zip.read_bytes()) == '8eceac177fe2e2828f71add0d458e6a91187ce6d4f67d0f0364061b9e3dca59b'
    items = [(lean_zip, 'lean-linux.zip'), (OLD / 'repl/.lake/build/bin/repl', 'repl-bin')]
    for directory in ['mathlib4', 'tools']:
        for base, dirs, files in os.walk(OLD / directory, followlinks=False):
            dirs[:] = [d for d in dirs if d not in ['.git', '__pycache__'] and not (Path(base) / d).is_symlink()]
            for n in sorted(files):
                p = Path(base) / n
                if p.is_symlink() or (p.lstat().st_file_attributes & 0x400):
                    if 'docs' in p.parts: continue
                    raise RuntimeError('Unexpected source reparse: ' + str(p))
                items.append((p, str(p.relative_to(OLD)).replace('\\', '/')))
    seen = {}
    for name in ['mathlib-cache', 'mathlib-cache-failed-prefix']:
        for p in (OLD / 'downloads' / name).iterdir():
            if not p.is_file() or p.suffix != '.ltar': continue
            if p.name in seen:
                assert sha(p.read_bytes()) == sha(seen[p.name].read_bytes())
                continue
            seen[p.name] = p
            items.append((p, 'cache/' + p.name))
    pins = []
    with tarfile.open(archive, 'w:gz', compresslevel=1) as tar:
        for index, (path, dest) in enumerate(items):
            info = tar.gettarinfo(str(path), arcname=dest)
            if not info.isfile(): raise RuntimeError('Nonregular transfer source: ' + str(path))
            info.uid = info.gid = 0; info.uname = info.gname = ''
            info.mode = 0o755 if dest == 'repl-bin' or dest.startswith('tools/') else 0o644
            with path.open('rb') as stream: tar.addfile(info, stream)
            if index % 1000 == 0: print(json.dumps({'bundleFiles': index, 'totalFiles': len(items)}), flush=True)
    pins = [{'path': str(p), 'archivePath': d, 'bytes': p.stat().st_size} for p, d in items]
    save(out / 'dependency-bundle.json', {'archive': archive.name, 'bytes': archive.stat().st_size, 'sha256': sha(archive.read_bytes()), 'copiedSourcesOnly': True, 'originalPathsUnmodified': True, 'remainingCacheArchives': len(seen), 'files': pins})
    print(json.dumps({'archive': str(archive), 'bytes': archive.stat().st_size, 'files': len(items), 'remainingCaches': len(seen)}), flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('out', type=Path); parser.add_argument('--dependencies', action='store_true')
    args = parser.parse_args(); args.out.mkdir(parents=True, exist_ok=True)
    catalog(args.out)
    if args.dependencies: dependencies(args.out)
