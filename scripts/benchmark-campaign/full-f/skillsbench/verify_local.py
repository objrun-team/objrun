"""Zero-model checks for the new full roster and opaque multi-file boundary."""
import io
import json
import hashlib
from pathlib import Path
import tarfile
from ordinary_artifacts import ArtifactFault, Policy, parse_daemon_tar, evaluation_key

ROOT = Path(__file__).resolve().parents[4]
HOME = ROOT / 'docs/repair-2026-10-10/full-f-rerun/skillsbench'

def tar(rows):
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode='w') as archive:
        for name, body, kind in rows:
            member = tarfile.TarInfo(name); member.mode = 0o644
            if kind == 'link': member.type = tarfile.SYMTYPE; member.linkname = '/etc/passwd'
            else: member.size = len(body)
            archive.addfile(member, io.BytesIO(body) if kind != 'link' else None)
    return buffer.getvalue()

def main():
    manifest = json.loads((HOME / 'manifest.json').read_bytes())
    ids = [r['taskId'] for r in manifest['taskSchedule']]
    assert len(ids) == len(set(ids)) == manifest['denominator'] == 87
    assert manifest['arms'] == ['F'] and all(r['arm'] == 'F' for r in manifest['taskSchedule'])
    frozen_schedule = (json.dumps(manifest['taskSchedule'], ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '\n').encode()
    assert hashlib.sha256(frozen_schedule).hexdigest() == manifest['taskScheduleSha256']
    for pin in manifest['sourceFilePins']:
        path = Path(pin['path'])
        assert path.stat().st_size == pin['bytes']
        with path.open('rb') as stream:
            assert hashlib.file_digest(stream, 'sha256').hexdigest() == pin['sha256'], str(path)
    assert all(r['taskSeconds'] == r['originalResources']['agent']['timeout_sec'] for r in manifest['taskSchedule'])
    assert all(r['verifierSeconds'] == r['originalResources']['verifier']['timeout_sec'] for r in manifest['taskSchedule'])
    policy = Policy('local-control', '/root/output', '/root/output', 'directory', 20000, 4, True)
    valid = parse_daemon_tar(tar([('output/a.csv', b'one', 'file'), ('output/b.csv', b'two', 'file')]), policy)
    assert valid['totalBytes'] == 6 and len(valid['files']) == 2 and not valid['hostExtractionUsed']
    rejected = []
    cases = {
        'traversal': [('output/../secret.csv', b'x', 'file')],
        'absolute': [('/root/output/x.csv', b'x', 'file')],
        'symlink': [('output/x.csv', b'', 'link')],
        'duplicate': [('output/x.csv', b'1', 'file'), ('output/x.csv', b'2', 'file')],
        'foreign': [('foreign/x.csv', b'x', 'file')],
        'code': [('output/x.py', b'print(1)', 'file')],
        'shebang': [('output/x.csv', b'#!/bin/sh\necho x', 'file')],
        'elf': [('output/x.csv', b'\x7fELFpayload', 'file')],
        'over_budget': [('output/x.csv', b'x' * 20001, 'file')],
    }
    for name, rows in cases.items():
        try: parse_daemon_tar(tar(rows), policy)
        except ArtifactFault: rejected.append(name)
        else: raise AssertionError('Accepted invalid archive: ' + name)
    first = evaluation_key('run', 'task', 'nonce', 0, valid['files'], 'same-answer')
    changed = {**valid['files'][0], 'sha256': '0' * 64}
    assert first != evaluation_key('run', 'task', 'nonce', 0, [changed, valid['files'][1]], 'same-answer')
    assert first != evaluation_key('run', 'task', 'nonce', 1, valid['files'], 'same-answer')
    result = {'protocol': 'skillsbench-full-f-local-verification-v1', 'denominator': 87, 'arms': ['F'],
              'multiFileDataBoundaryPassed': True, 'rejectedCases': rejected, 'workspaceRefreshIdentityPassed': True,
              'allFrozenSourceFilesVerified': len(manifest['sourceFilePins']),
              'modelRequests': 0, 'DockerMutations': 0, 'realGraderExecuted': False, 'formalScoreCertified': False}
    (HOME / 'local-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps(result))

if __name__ == '__main__': main()
