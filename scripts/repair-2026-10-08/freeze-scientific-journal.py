"""Independent one-time streaming source freeze for prospective journal campaigns."""
import hashlib
import json
import pathlib
import os
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[2]
metadata = pathlib.Path(sys.argv[1]).resolve()
store = pathlib.Path(sys.argv[2]).resolve()
assert metadata.is_relative_to(ROOT), 'only owned F project metadata is implemented'
manifest = json.loads((metadata / 'manifest.json').read_text(encoding='utf-8'))
source_files = []
def file_sha(path):
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()

def file_record(path):
    return {'path': path.relative_to(ROOT).as_posix(), 'sha256': file_sha(path), 'bytes': path.stat().st_size}
if not store.is_relative_to(ROOT):
    pin = manifest['storageLayout']
    path = pathlib.Path(pin['path'])
    assert path.resolve() == metadata / 'storage-layout.json', 'owned storage receipt outside metadata'
    assert file_sha(path) == pin['sha256'], 'owned storage receipt changed'
    layout = json.loads(path.read_bytes())
    owner_root = pathlib.Path('D:/objrun-experiment-stores/01a119ed-fdf7-7c32-b323-de9bab1290b6')
    expected = owner_root / ('scientific-journal-v2-' + manifest['campaign'])
    logical = ROOT / '.phase1-data/repair' / manifest['campaign']
    assert store == expected.resolve() and layout['protocol'] == 'scientific-journal-store-v2' and layout['runId'] == manifest['campaign'] and layout['mode'] == 'owned-d-new-store' and layout['junctionVerified'] is True and layout['reuse'] == 'never' and layout['oldStoresMoved'] is False, 'unreviewed physical store'
    assert pathlib.Path(layout['physicalStore']).resolve() == store and logical.resolve() == store and pathlib.Path(layout['logicalStore']).absolute() == logical, 'logical physical store mismatch'
    for at in [store, *store.parents]:
        identity = at.stat(follow_symlinks=False)
        assert at.is_dir() and not getattr(identity, 'st_file_attributes', 0) & 1024, 'physical store ancestor reparse'
    for name in ('physicalOwnerReceiptPin', 'storageLeasePin', 'scriptPin'):
        proof = layout[name]; assert file_sha(pathlib.Path(proof['path'])) == proof['sha256'], 'storage ownership proof changed'
    assert file_sha(logical / 'storage-owner.json') == layout['physicalOwnerReceiptPin']['sha256'], 'logical ownership bytes differ'
for name, value in manifest['hostExecutors'].items():
    path = pathlib.Path(value['path'])
    if not path.is_absolute() or not path.is_file():
        raise RuntimeError('actual host executor missing: ' + name)
    value.update({'sha256': file_sha(path), 'bytes': path.stat().st_size})
for path in sorted((ROOT / 'app/src').rglob('*')):
    if path.is_file() and path.suffix in ('.ts', '.html'):
        source_files.append(file_record(path))
used = ['test/_lib.ts', 'app/package.json', 'app/bun.lock', 'app/tsconfig.json', 'examples/benchmark/_lib/gradelib.py']
used += [f"examples/benchmark/{slug}/{'grader.py' if slug == 'cmt' else 'stand.py'}" for slug in manifest['benchmarks']]
used += manifest['additionalExecutionFiles']
for name in sorted(set(used)):
    source_files.append(file_record(ROOT / name))
source_files.sort(key=lambda value: value['path'])
if len({value['path'] for value in source_files}) != len(source_files):
    raise RuntimeError('duplicate execution source')
repair_files = [value for value in source_files if value['path'].startswith('scripts/repair-2026-10-08/')]
sources = [value for value in source_files if value not in repair_files]
compact = lambda value: json.dumps(value, separators=(',', ':'), ensure_ascii=False).encode()
source = {'schemaVersion': 1, 'createdAt': manifest['createdAt'], 'provenance': 'New prospective executed source; not the runtime of any old failed batch',
          'files': sources, 'repairFiles': repair_files, 'sourceDigest': hashlib.sha256(compact(sources)).hexdigest(),
          'taskScheduleSha256': manifest['taskScheduleSha256']}
if manifest.get('graderProvenance'):
    source['graderProvenance'] = manifest['graderProvenance']
body = {'sourceDigest': source['sourceDigest'], 'repairFiles': repair_files}
if source.get('graderProvenance'):
    body['graderProvenance'] = source['graderProvenance']
body['taskScheduleSha256'] = source['taskScheduleSha256']
source['executionDigest'] = hashlib.sha256(compact(body)).hexdigest()
dependencies = []
for file in sorted((ROOT / 'app/node_modules').rglob('*')):
    if file.is_file() and file.suffix in ['.js', '.cjs', '.mjs', '.json', '.wasm', '.node', '.ts'] and '.bin' not in file.parts:
        dependencies.append(file_record(file))
if not dependencies:
    raise RuntimeError('actual installed dependencies unavailable')
store.mkdir(parents=True, exist_ok=True)
archive = store / 'frozen-source.zip'
with archive.open('xb') as archive_file:
    with zipfile.ZipFile(archive_file, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
        for value in source_files + dependencies:
            path = ROOT / value['path']
            if file_record(path) != value:
                raise RuntimeError('source changed while archiving')
            output.write(path, value['path'])
    archive_file.flush()
    os.fsync(archive_file.fileno())
for value in source_files + dependencies:
    if file_record(ROOT / value['path']) != value:
        raise RuntimeError('source changed during freeze')
evidence = {'campaign': manifest['campaign'], 'sourceExecutionDigest': source['executionDigest'], 'archive': str(archive),
            'archiveSha256': file_sha(archive), 'archiveBytes': archive.stat().st_size, 'archiveFlushReturned': True, 'archiveFsyncReturned': True,
            'sourceFiles': len(source_files), 'dependencyFiles': dependencies,
            'dependencyDigest': hashlib.sha256(compact(dependencies)).hexdigest(),
            'scope': 'Actual current core, journal entry and installed dependencies; excludes credentials and private/reference task data',
            'limits': 'Grader actual runtime/image and remote model identity are separately audited.'}
manifest['sourceExecutionDigest'] = source['executionDigest']
manifest['acceptanceContract'] = next(value for value in repair_files if value['path'].endswith('/campaign-contract.ts'))
durability = []
for name, value in [('source.json', source), ('frozen-source.json', evidence), ('manifest.json', manifest)]:
    path = metadata / name
    raw = (json.dumps(value, indent=2, ensure_ascii=False) + '\n').encode('utf-8')
    with path.open('wb') as output:
        output.write(raw); output.flush(); os.fsync(output.fileno())
    if path.read_bytes() != raw:
        raise RuntimeError('metadata readback differs: ' + name)
    durability.append({'name': name, 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(), 'flushReturned': True, 'fsyncReturned': True})
receipt = {'archiveFsyncReturned': True, 'archiveSha256': evidence['archiveSha256'], 'metadata': durability,
           'claim': 'Actual flush/fsync calls returned and readback bytes matched; no claim of device or power-loss measurement.'}
with (metadata / 'source-durability.json').open('wb') as output:
    output.write((json.dumps(receipt, indent=2) + '\n').encode()); output.flush(); os.fsync(output.fileno())
print(json.dumps({'sourceExecutionDigest': source['executionDigest'], 'archiveSha256': evidence['archiveSha256'], 'archiveBytes': evidence['archiveBytes'], 'metadataFsyncReturned': True}))
