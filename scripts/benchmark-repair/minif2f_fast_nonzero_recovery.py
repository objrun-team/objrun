"""Independent, source-bound recovery of the interrupted batch061; no decoder.

The prepared review cannot authorize Restore. Root must separately close the
exact historical container, review an actual Gate and create a production
authorization. A successful certificate closes 21 observed objects, not the
original 64-object batch, and never certifies all5826 objects or old proofs.
"""
import argparse
import contextlib
import ctypes
from ctypes import wintypes
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import time
import uuid
from datetime import datetime, timezone

PROTOCOL = 'minif2f-fast-nonzero-recovery-v1'
FAST = 'bounded-official-cache-unpack-v2-archive-dot-prefix'
TOTAL, BASE, COMMITTED, TARGET = 5826, 3906, 3926, 3927
CID = '56ec80686d5d9320055412460b3789934a23941e887ab6062deb2d436dc76ed2'
OWNER = 'b3c2fccab2f34473b5a0bc8b9a7a88c8'
NAME = 'objrun-minif-fast-2f8ffcb90a64'
LTAR = '52287fda062577c7.ltar'
ROOT = Path('E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415')
REPO = Path(__file__).resolve().parents[2]
DIAG = REPO / 'docs/repair-2026-10-08/minif2f-fast-batch061-readonly-diagnosis/diagnosis.json'
DIAG_SHA = 'b5c3e55b97ca9deb543836aad5a649035e6de55bd357d85547e4d7b4ba05eb23'
BASE_PATH = REPO / 'docs/repair-2026-10-08/minif2f-v2-bulk-runtime-04875795a5764ce9abc7e7d57303db40/batch-060-cache-fast-progress.json'
BASE_SHA = 'b6bce6ad657c01f78ab3b82c69268bac7dd953c4bc9c55dde458b0cb783b52a6'
FAST_SHA = 'ef0ddf5d708f6507d256af7a3c77e68c71a1eb7adda79ab7a7f19e9a246fbc09'
RESERVATION, MAX_LINE, WALL = 32 * 1024**2, 16384, 3 * 3600
BUILD_ROOTS = ('.lake/build',) + tuple('.lake/packages/' + p + '/.lake/build' for p in
    ('plausible', 'LeanSearchClient', 'importGraph', 'proofwidgets', 'aesop', 'Qq', 'batteries', 'Cli'))
META = ('cache-fast-progress.json', 'cache-fast-unpack.lock',
        'cache-fast-container.json', 'cache-fast-item.json',
        'cache-unpacked.jsonl', 'cache-fast-commits.jsonl')


class Fault(RuntimeError):
    def __init__(self, kind, detail): super().__init__(detail); self.kind = kind


def need(value, kind, detail):
    if not value: raise Fault(kind, detail)


def digest(data): return hashlib.sha256(data).hexdigest()
def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()
def now(): return datetime.now(timezone.utc).isoformat()


def regular(path):
    z = Path(path).lstat()
    need(stat.S_ISREG(z.st_mode) and not getattr(z, 'st_file_attributes', 0) & 0x400,
         'nonregular', 'Expected an ordinary regular file')
    return z


def ordinary(path, boundary):
    path, boundary = Path(path).absolute(), Path(boundary).absolute()
    need(path == boundary or boundary in path.parents, 'containment', 'Path escapes its fixed root')
    while True:
        z = path.lstat()
        need(stat.S_ISDIR(z.st_mode) and not getattr(z, 'st_file_attributes', 0) & 0x400,
             'ancestor', 'Ancestor is not an ordinary directory')
        if path == boundary: break
        path = path.parent


def sha(path):
    regular(path)
    with Path(path).open('rb') as f: return hashlib.file_digest(f, 'sha256').hexdigest()


def pin(path):
    p = Path(path); return {'path': str(p), 'bytes': regular(p).st_size, 'sha256': sha(p)}


def fsync_json(path, value, fresh=False):
    path = Path(path); ordinary(path.parent, ROOT if ROOT in path.parents else REPO)
    data = canonical(value) + b'\n'
    need(len(data) <= 256 * 1024, 'audit_size', 'Audit record exceeds its reservation')
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    with temp.open('xb') as f: f.write(data); f.flush(); os.fsync(f.fileno())
    if fresh: need(not os.path.lexists(path), 'existing_record', 'A fresh record already exists')
    if os.name == 'nt':
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.MoveFileExW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
        api.MoveFileExW.restype = wintypes.BOOL
        need(api.MoveFileExW(str(temp), str(path), (0 if fresh else 1) | 8), 'audit_replace', 'Durable metadata move failed')
    else: temp.replace(path)
    with path.open('r+b') as f: f.flush(); os.fsync(f.fileno())
    need(path.read_bytes() == data, 'audit_readback', 'Metadata readback differs')
    return pin(path)


def lines(raw):
    need(bool(raw) and raw.endswith(b'\n'), 'tail_truncated', 'Journal lacks a complete final line')
    result = []
    for line in raw.splitlines(keepends=True):
        need(0 < len(line) <= MAX_LINE, 'line_limit', 'Journal line is empty or oversized')
        try: result.append((line, json.loads(line)))
        except (ValueError, UnicodeError) as e: raise Fault('journal_json', 'Journal line is invalid') from e
    return result


def output_path(value):
    need(isinstance(value, str) and value and '\\' not in value and ':' not in value and
         not any(ord(c) < 32 or ord(c) == 127 for c in value) and not value.startswith('/') and
         all(p not in ('', '.', '..') for p in value.split('/')) and len(value.split('/')) <= 16 and
         len(value.encode()) <= 256 and any(value.startswith(b + '/') for b in BUILD_ROOTS),
         'output_schema', 'Path escapes the nine bounded ordinary build trees')
    return value


def verify_boundary(receipts, commits, records, base_receipts_sha, base_commits_sha, item):
    """Pure raw-byte check; not a filesystem, decoder or fsync certificate."""
    rows, cs = lines(receipts), lines(commits)
    need(len(records) == TOTAL and len(rows) == TARGET and len(cs) == COMMITTED,
         'boundary_count', 'Expected exactly3906 +20commits +1receipt')
    need(digest(b''.join(x[0] for x in rows[:BASE])) == base_receipts_sha and
         digest(b''.join(x[0] for x in cs[:BASE])) == base_commits_sha,
         'base_prefix_changed', 'Original3906 raw journal prefix changed')
    used, end = set(), 0
    for index, (raw, row) in enumerate(rows):
        source = records[index]; end += len(raw)
        need(row.get('protocol') == FAST and row.get('ltar') == source['ltar'] and
             row.get('source_sha256') == source['sha256'] and row.get('source_bytes') == source['bytes'] and
             row.get('source_url') == source['url'] and row.get('outputs_fsynced') is True,
             'receipt_source', 'Receipt differs from its pinned acquisition source')
        need(isinstance(row.get('files'), list) and 0 < len(row['files']) <= 8,
             'files_count', 'Receipt has an invalid output count')
        for f in row['files']:
            p = output_path(f['path'])
            need(p.casefold() not in used and
                 type(f['bytes']) is int and 0 <= f['bytes'] <= 64 * 1024**2 and
                 bool(re.fullmatch('[0-9a-f]{64}', f['sha256'])), 'output_schema', 'Malformed or duplicate output')
            used.add(p.casefold())
        if index < COMMITTED:
            c = cs[index][1]
            need(c.get('protocol') == FAST and c.get('ltar') == row['ltar'] and
                 c.get('receipt_end') == end and c.get('receipt_line_sha256') == digest(raw) and
                 c.get('receipt_fsync_returned') is True, 'commit_link', 'Commit hash/offset/source differs')
    pending = rows[-1][1]
    need(pending['ltar'] == LTAR and len(pending['files']) == 7 and
         item.get('protocol') == FAST and item.get('ltar') == LTAR and
         item.get('state') == 'materialized_and_fsynced' and item.get('files') == pending['files'],
         'pending_intent', 'Pending receipt and exact materialization intent differ')
    return rows, cs


def verify_actor_observation(pids, container):
    need({p['pid'] for p in pids} == {109444, 124128} and
         all(p['present'] is False for p in pids), 'actor_present', 'A historical host actor is still present')
    need(container.get('requested_cid') == CID and container.get('absent') is True,
         'container_not_absent', 'Exact historical container absence is required')


def verify_pins(pins):
    for p in pins:
        need(pin(p['path'])['sha256'] == p['sha256'] and regular(p['path']).st_size == p['bytes'],
             'source_drift', 'Reviewed source or input identity changed')


def module_fast():
    path = REPO / 'scripts/benchmark-repair/minif2f_fast_unpack_v2.py'
    need(sha(path) == FAST_SHA, 'source_drift', 'Frozen fast-v2 source changed')
    spec = importlib.util.spec_from_file_location('nonzero_reviewed_fast', path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m


def native_actors():
    ps = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    env = dict(os.environ)
    env['PSModulePath'] = os.pathsep.join([str(ps.parent / 'Modules'),
        str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'WindowsPowerShell/Modules')])
    code = "$ErrorActionPreference='Stop';$a=@();foreach($taskPid in @(109444,124128)){$p=Get-CimInstance Win32_Process -Filter ('ProcessId='+$taskPid) -ErrorAction Stop;$a+=[pscustomobject]@{pid=$taskPid;present=($null -ne $p)}};$a|ConvertTo-Json -Compress"
    p = subprocess.run([str(ps), '-NoProfile', '-NonInteractive', '-Command', code],
                       capture_output=True, env=env, timeout=30)
    need(p.returncode == 0, 'pid_query', 'Native exact-PID query failed')
    ids = json.loads(p.stdout.decode('utf-8-sig'))
    c = subprocess.run(['docker', 'inspect', '--type', 'container', '--format', '{{.Id}}', CID],
                       capture_output=True, timeout=30)
    error = c.stderr.decode('utf-8', errors='replace')
    absent = c.returncode != 0 and 'no such' in error.casefold() and CID in error
    observation = {'requested_cid': CID, 'absent': absent, 'observed_at_utc': now(),
                   'pid_stdout_sha256': digest(p.stdout), 'pid_stderr_sha256': digest(p.stderr),
                   'cid_stdout_sha256': digest(c.stdout), 'cid_stderr_sha256': digest(c.stderr)}
    verify_actor_observation(ids, observation)
    return {'pids': ids, 'container': observation}


class WinFile:
    """Real share-deny handle. Fresh leases use CREATE_NEW, never OPEN_ALWAYS."""
    def __init__(self, path, fresh=False): self.path, self.fresh, self.stream = Path(path), fresh, None
    def __enter__(self):
        need(os.name == 'nt', 'platform', 'Actual Windows ownership is required')
        ordinary(self.path.parent, ROOT if ROOT in self.path.parents else REPO)
        if not self.fresh: regular(self.path)
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        create = api.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        h = create(str(self.path), 0xC0000000 if self.fresh else 0x80000000,
                   0, None, 1 if self.fresh else 3, 0x00200000, None)
        need(h != ctypes.c_void_p(-1).value, 'exclusive_handle', 'Owned native handle could not be acquired')
        import msvcrt
        try: fd = msvcrt.open_osfhandle(h, (os.O_RDWR if self.fresh else os.O_RDONLY) | os.O_BINARY)
        except BaseException:
            api.CloseHandle.argtypes = [wintypes.HANDLE]; api.CloseHandle(h); raise
        try: self.stream = os.fdopen(fd, 'r+b' if self.fresh else 'rb', buffering=0)
        except BaseException: os.close(fd); raise
        return self
    def raw(self): self.stream.seek(0); return self.stream.read(16385)
    def write(self, value):
        need(self.fresh and self.stream is not None, 'handle_state', 'Writable owned handle is not open')
        b = canonical(value) + b'\n'; need(len(b) <= MAX_LINE, 'marker_size', 'Marker too large')
        self.stream.seek(0); self.stream.write(b); self.stream.truncate(); self.stream.flush(); os.fsync(self.stream.fileno())
    def close(self):
        if self.stream is not None: self.stream.close(); self.stream = None
    def __exit__(self, *_): self.close()


def nt_id(path):
    """Fresh real NT file identity, including directories; handles always close."""
    need(os.name == 'nt', 'platform', 'NT file identity required')
    class Info(ctypes.Structure):
        _fields_ = [('attrs', wintypes.DWORD), ('created', wintypes.FILETIME),
                    ('accessed', wintypes.FILETIME), ('written', wintypes.FILETIME),
                    ('volume', wintypes.DWORD), ('size_hi', wintypes.DWORD), ('size_lo', wintypes.DWORD),
                    ('links', wintypes.DWORD), ('index_hi', wintypes.DWORD), ('index_lo', wintypes.DWORD)]
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                               wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    api.CreateFileW.restype = wintypes.HANDLE
    api.GetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.POINTER(Info)]
    api.GetFileInformationByHandle.restype = wintypes.BOOL
    api.CloseHandle.argtypes = [wintypes.HANDLE]
    h = api.CreateFileW(str(path), 0, 7, None, 3, 0x02200000, None)
    need(h != ctypes.c_void_p(-1).value, 'file_identity', 'NT identity open failed')
    try:
        z = Info(); need(api.GetFileInformationByHandle(h, ctypes.byref(z)), 'file_identity', 'NT identity query failed')
        need(not z.attrs & 0x400, 'reparse', 'A stage identity is a reparse point')
        return {'volume': z.volume, 'index_hi': z.index_hi, 'index_lo': z.index_lo, 'attrs': z.attrs}
    finally: api.CloseHandle(h)


def stage_ids(path):
    ordinary(path, ROOT if ROOT in Path(path).parents else REPO)
    result = {'': nt_id(path)}
    for parent, dirs, files in os.walk(path, followlinks=False):
        need(not files, 'stage_files', 'Interrupted stage contains a nonempty output')
        for name in dirs:
            p = Path(parent) / name; ordinary(p, path); result[p.relative_to(path).as_posix()] = nt_id(p)
    need(len(result) == 29, 'stage_count', 'Expected exactly root +28 ordinary empty directories')
    return result


def snapshot(review):
    verify_pins(review['sourcePins']); need(sha(DIAG) == DIAG_SHA, 'diagnosis_changed', 'Readonly diagnosis changed')
    diag = json.loads(DIAG.read_bytes()); expected = {Path(x['path']).name: x for x in diag['inputs'] if ROOT in Path(x['path']).parents}
    raw = {}
    for name in META:
        b = (ROOT / 'audit' / name).read_bytes()
        need(len(b) == expected[name]['bytes'] and digest(b) == expected[name]['sha256'],
             'interruption_changed', 'Original interrupted metadata or journal changed')
        raw[name] = b
    fast = module_fast(); helper = fast.load_helper(REPO); helper.exact_root(ROOT); helper.allocation_unit()
    helper.volume_reserves(RESERVATION); helper.writer_probe()
    records, provenance = fast.inputs(REPO, ROOT, helper)
    need((REPO / review['baseClosurePath']).resolve() == BASE_PATH.resolve() and sha(BASE_PATH) == BASE_SHA,
         'base_closure_changed', 'Original batch060 closure changed')
    base = json.loads(BASE_PATH.read_bytes())
    item = json.loads(raw['cache-fast-item.json'])
    rows, cs = verify_boundary(raw['cache-unpacked.jsonl'], raw['cache-fast-commits.jsonl'],
                              records, base['receipts_sha256'], base['commits_sha256'], item)
    stage = ROOT / 'audit' / ('cache-fast-stage-' + OWNER)
    need(Path(item['stage']) == stage, 'stage_path', 'Stage differs from the fixed owned stage')
    identity = fast.source_identity(REPO, ROOT, helper)
    need(identity == diag['canonicalProgress']['source_before'] == base['source_after'],
         'source_identity', 'Original Lean/package/source identity changed')
    used = set()
    for _, row in rows:
        for value in row['files']:
            path = fast.output_path(value['path']); target = ROOT / 'mathlib4' / path
            fast.ordinary_ancestors(target.parent, ROOT)
            need(path.casefold() not in used and fast.regular(target).st_size == value['bytes'] and
                 sha(target) == value['sha256'], 'output_mismatch', 'Actual committed or pending output differs')
            used.add(path.casefold())
    directory = ROOT / 'downloads/mathlib-cache'
    need({p.name for p in directory.iterdir()} == {r['ltar'] for r in records[COMMITTED:]},
         'remaining_set', 'Remaining compressed set differs')
    for record in records[COMMITTED:]:
        p = directory / record['ltar']
        need(regular(p).st_size == record['bytes'] and sha(p) == record['sha256'], 'compressed_changed', 'Original compressed input differs')
    pending = rows[-1][1]; original = directory / LTAR
    need(fast.ltar_paths(original.read_bytes()) == [x['path'] for x in pending['files']],
         'header_paths', 'Pure original archive header and exact seven output paths differ')
    allocation = helper.full_scan(ROOT)
    need(allocation['allocated_envelope_bytes'] + RESERVATION <= 14 * 1024**3, 'envelope', 'Recovery archive would exceed14GiB')
    actors = native_actors()
    return {'fast': fast, 'helper': helper, 'raw': raw, 'records': records, 'rows': rows,
            'provenance': provenance, 'source': identity, 'allocation': allocation,
            'stage': stage, 'stage_ids': stage_ids(stage), 'actors': actors}


def close_pending(receipts_path, commits_path, blob, outputs, row, old_receipts_sha,
                  old_commits_sha, receipt_line, nonce, witness_dir):
    """Actual fresh fsync and append; an IO failure never deletes the input."""
    need(sha(receipts_path) == old_receipts_sha and sha(commits_path) == old_commits_sha,
         'journal_changed', 'Journals changed before new recovery fsync')
    need(row['ltar'] == LTAR and regular(blob).st_size == row['source_bytes'] and
         sha(blob) == row['source_sha256'], 'compressed_changed', 'Exact pending original differs')
    blob = Path(blob).absolute(); bound = ROOT if ROOT in blob.parents else REPO
    ordinary(blob.parent, bound); ordinary(Path(outputs), bound)
    need(blob == ROOT / 'downloads/mathlib-cache' / LTAR or
         (REPO / '.scratch/minif2f-nonzero-recovery-controls') in blob.parents,
         'delete_target', 'Leaf IO target is not the fixed original or an owned F fixture')
    for file in row['files']:
        target = Path(outputs) / output_path(file['path']); ordinary(target.parent, bound); regular(target)
        with target.open('r+b') as stream:
            need(os.fstat(stream.fileno()).st_size == file['bytes'] and
                 hashlib.file_digest(stream, 'sha256').hexdigest() == file['sha256'],
                 'output_mismatch', 'Actual pending output differs before recovery fsync')
            stream.flush(); os.fsync(stream.fileno())
    with Path(receipts_path).open('r+b') as stream:
        need(hashlib.file_digest(stream, 'sha256').hexdigest() == old_receipts_sha,
             'journal_changed', 'Receipt changed before recovery fsync')
        stream.flush(); os.fsync(stream.fileno()); end = stream.seek(0, os.SEEK_END)
    witness = {'protocol': PROTOCOL, 'nonce': nonce, 'ltar': LTAR, 'new_outputs_fsync_returned': True,
               'new_receipt_fsync_returned': True, 'old_receipt_fsync_return_certified': False,
               'receipt_line_sha256': digest(receipt_line), 'receipt_end': end, 'recorded_at_utc': now()}
    wp = fsync_json(Path(witness_dir) / 'pending-fsync-witness.json', witness, fresh=True)
    commit = {'protocol': FAST, 'ltar': LTAR, 'receipt_line_sha256': digest(receipt_line),
              'receipt_end': end, 'receipt_fsync_returned': True, 'recorded_at_utc': now(),
              'recovery_protocol': PROTOCOL, 'recovery_nonce': nonce}
    encoded = canonical(commit) + b'\n'
    with Path(commits_path).open('ab') as stream:
        need(stream.tell() == regular(commits_path).st_size and sha(commits_path) == old_commits_sha,
             'journal_changed', 'Commit journal changed before exact append')
        start = stream.tell(); stream.write(encoded); stream.flush(); os.fsync(stream.fileno()); end_commit = stream.tell()
    cp = fsync_json(Path(witness_dir) / 'pending-commit-witness.json',
                    {'protocol': PROTOCOL, 'nonce': nonce, 'new_commit_fsync_returned': True,
                     'commit_line_sha256': digest(encoded), 'commit_start': start,
                     'commit_end': end_commit, 'fsync_witness_pin': wp}, fresh=True)
    need(regular(blob).st_size == row['source_bytes'] and sha(blob) == row['source_sha256'],
         'compressed_changed', 'Exact original changed before contained unlink')
    need(Path(blob).name == LTAR, 'delete_target', 'Delete target is not the one fixed LTAR')
    Path(blob).unlink()
    return {'fsync_witness_pin': wp, 'commit_witness_pin': cp,
            'new_commit_line_sha256': digest(encoded), 'commit_end': end_commit}


def load_review(path, expected):
    need(sha(path) == expected, 'review_drift', 'Review bytes changed')
    r = json.loads(Path(path).read_bytes())
    need(r['protocol'] == PROTOCOL and r['diagnosisSha256'] == DIAG_SHA and r['targetPrefix'] == TARGET,
         'review_scope', 'Review is not the fixed21-object recovery')
    verify_pins(r['sourcePins'])
    need(sum(x['bytes'] for x in r['sourcePins']) <= 1024**2,
         'source_archive_bound', 'Source snapshot exceeds its pre-reserved1MiB limit')
    need(any(Path(p['path']).resolve() == Path(__file__).resolve() and p['sha256'] == sha(__file__)
             for p in r['sourcePins']), 'self_source', 'This actual recovery source is not reviewed')
    r['_actual_review_pin'] = pin(path)
    return r


def gate(review):
    start = time.monotonic(); s = snapshot(review)
    return {'protocol': PROTOCOL, 'state': 'readonly_gate_passed', 'validated': True,
            'recovery_nonce': review['recoveryNonce'],
            'recorded_at_utc': now(), 'diagnosis_sha256': DIAG_SHA, 'source': s['source'],
            'input_provenance': s['provenance'], 'actors': s['actors'], 'stage_ids': s['stage_ids'],
            'allocation_envelope': s['allocation']['allocated_envelope_bytes'], 'source_sha256': sha(__file__),
            'base_prefix': BASE, 'old_commits': COMMITTED, 'pending_receipts': 1, 'target_prefix': TARGET,
            'remaining_after_recovery': TOTAL - TARGET, 'original64_batch_closed': False,
            'full5826_closed': False, 'decoded_objects': 0, 'decoder_executed': False, 'public_get': False,
            'elapsed_seconds': time.monotonic() - start}


def production(review):
    auth = review.get('production_authorization')
    need(isinstance(auth, dict), 'prepared_only', 'Prepared F review cannot authorize an actual Restore')
    verify_pins([auth['gatePin'], auth['independentReviewPin']])
    g = json.loads(Path(auth['gatePin']['path']).read_bytes())
    need(g['protocol'] == PROTOCOL and g['validated'] is True and g['source_sha256'] == sha(__file__) and
         g['target_prefix'] == TARGET and g['original64_batch_closed'] is False and
         g.get('recovery_nonce') == review['recoveryNonce'],
         'gate_binding', 'Production authorization does not bind the actual Gate')
    age = (datetime.now(timezone.utc) - datetime.fromisoformat(g['recorded_at_utc'])).total_seconds()
    need(0 <= age <= 600, 'gate_stale', 'Actual Gate is older than10minutes')
    peer = json.loads(Path(auth['independentReviewPin']['path']).read_bytes())
    need(peer.get('protocol') == PROTOCOL + '-root-reviewed' and peer.get('allow_restore') is True and
         peer.get('source_sha256') == sha(__file__) and peer.get('gate_sha256') == auth['gatePin']['sha256'] and
         peer.get('diagnosis_sha256') == DIAG_SHA and peer.get('target_prefix') == TARGET and
         peer.get('recovery_nonce') == review['recoveryNonce'] and peer.get('decoder_authorized') is False,
         'root_review_binding', 'Root source/Gate review is not the exact narrow authorization')
    return g


def restore(review):
    g = production(review); started = time.monotonic(); s = snapshot(review)
    production(review)  # Readonly full scans must not silently outlive Gate TTL.
    need(s['source'] == g['source'] and s['provenance'] == g['input_provenance'] and
         s['stage_ids'] == g['stage_ids'], 'gate_changed', 'Gate inputs or stage identities changed')
    nonce = review['recoveryNonce']; need(bool(re.fullmatch('[0-9a-f]{32}', nonce)), 'nonce', 'Invalid fixed fresh nonce')
    audit = ROOT / 'audit'; history = audit / ('cache-fast-nonzero-history-' + nonce)
    lease_path = audit / 'cache-fast-nonzero-recovery.lock'
    intent_path, receipt_path = audit / 'cache-fast-nonzero-recovery-intent.json', audit / 'cache-fast-nonzero-recovery.json'
    need(not any(os.path.lexists(p) for p in [history, lease_path, intent_path, receipt_path]),
         'existing_transaction', 'Unknown/failed recovery transaction is preserved; no automatic retry')
    acquisition_path = audit / 'public-cache-acquisition.lock'; old_fast_path = audit / 'cache-fast-unpack.lock'
    stack = contextlib.ExitStack(); own = old_guard = acquire = fresh_fast = None
    phase, failure, closure = 'initial', None, None
    try:
        acquire = stack.enter_context(WinFile(acquisition_path))
        need(digest(acquire.raw()) == '24f91e9a9790a0d14a94e6e5f530af0fa51c8823203a94eae5d68f9cd026a368',
             'acquisition_changed', 'Original complete acquisition marker changed')
        old_guard = stack.enter_context(WinFile(old_fast_path))
        need(old_guard.raw() == s['raw']['cache-fast-unpack.lock'], 'lease_changed', 'Original interrupted marker changed')
        own = stack.enter_context(WinFile(lease_path, fresh=True))
        own.write({'protocol': PROTOCOL, 'held': True, 'pid': os.getpid(), 'nonce': nonce, 'recorded_at_utc': now()})
        native_actors(); s['helper'].writer_probe(); s['helper'].volume_reserves(RESERVATION)
        verify_pins(review['sourcePins'])
        for name, raw in s['raw'].items():
            current = old_guard.raw() if name == 'cache-fast-unpack.lock' else (audit / name).read_bytes()
            need(current == raw, 'interruption_changed', 'An original changed before guarded history preservation')
        need(stage_ids(s['stage']) == s['stage_ids'], 'stage_changed', 'Fresh stage identities changed')
        fsync_json(intent_path, {'protocol': PROTOCOL, 'nonce': nonce, 'pid': os.getpid(),
            'source_sha256': sha(__file__), 'diagnosis_sha256': DIAG_SHA, 'target_prefix': TARGET,
            'original_batch_closed': False, 'history': str(history), 'stage_before': s['stage_ids'],
            'input_provenance': s['provenance'], 'actors': s['actors']}, fresh=True)
        history.mkdir(); archived = []
        for name, raw in s['raw'].items():
            p = history / name
            with p.open('xb') as f: f.write(raw); f.flush(); os.fsync(f.fileno())
            need(p.read_bytes() == raw, 'history_readback', 'Original interruption archive differs'); archived.append(pin(p))
        (history / 'executed-source').mkdir()
        executed_sources = []
        for index, source in enumerate(review['sourcePins']):
            data = Path(source['path']).read_bytes()
            need(digest(data) == source['sha256'], 'source_drift', 'Source changed before history copy')
            dest = history / 'executed-source' / (str(index) + '-' + Path(source['path']).name)
            with dest.open('xb') as handle: handle.write(data); handle.flush(); os.fsync(handle.fileno())
            need(dest.read_bytes() == data, 'history_readback', 'Archived executed source differs')
            executed_sources.append({'original': source, 'archived': pin(dest)})
        stage_before = stage_ids(s['stage']); s['stage'].rename(history / 'original-stage')
        stage_after = stage_ids(history / 'original-stage')
        need(stage_before == stage_after, 'stage_changed', 'Same-volume stage rename changed identities')
        hp = fsync_json(history / 'history.json', {'protocol': PROTOCOL, 'nonce': nonce, 'old_metadata': archived,
            'diagnosis_pin': pin(DIAG), 'source_pins': review['sourcePins'], 'executed_sources': executed_sources, 'original_batch_prefix': BASE,
            'original_requested_count': 64, 'original_batch_closed': False,
            'stage_before': stage_before, 'stage_after': stage_after}, fresh=True)
        phase = 'history_preserved'
        new = close_pending(audit / 'cache-unpacked.jsonl', audit / 'cache-fast-commits.jsonl',
            ROOT / 'downloads/mathlib-cache' / LTAR, ROOT / 'mathlib4', s['rows'][-1][1],
            digest(s['raw']['cache-unpacked.jsonl']), digest(s['raw']['cache-fast-commits.jsonl']),
            s['rows'][-1][0], nonce, history)
        phase = 'pending_independently_committed'
        rr = lines((audit / 'cache-unpacked.jsonl').read_bytes()); cc = lines((audit / 'cache-fast-commits.jsonl').read_bytes())
        need(len(rr) == len(cc) == TARGET and
             (audit / 'cache-unpacked.jsonl').read_bytes() == s['raw']['cache-unpacked.jsonl'] and
             (audit / 'cache-fast-commits.jsonl').read_bytes().startswith(s['raw']['cache-fast-commits.jsonl']),
             'new_journal_changed', 'Recovery changed or fabricated old journal bytes')
        end = 0
        for (raw, row), (_, c) in zip(rr, cc):
            end += len(raw)
            need(c['ltar'] == row['ltar'] and c['receipt_line_sha256'] == digest(raw) and c['receipt_end'] == end,
                 'new_commit_link', 'New recovery commit chain differs')
            for value in row['files']:
                target = ROOT / 'mathlib4' / s['fast'].output_path(value['path'])
                need(regular(target).st_size == value['bytes'] and sha(target) == value['sha256'],
                     'output_mismatch', 'An actual output changed before recovery closure')
        remaining = s['records'][TARGET:]; directory = ROOT / 'downloads/mathlib-cache'
        need({p.name for p in directory.iterdir()} == {r['ltar'] for r in remaining}, 'remaining_set', 'Remaining-only set differs')
        for record in remaining:
            p = directory / record['ltar']
            need(regular(p).st_size == record['bytes'] and sha(p) == record['sha256'], 'compressed_changed', 'Remaining original changed')
        source_after = s['fast'].source_identity(REPO, ROOT, s['helper'])
        _, provenance_after = s['fast'].inputs(REPO, ROOT, s['helper'])
        need(source_after == s['source'] and provenance_after == s['provenance'], 'source_identity', 'Source/provenance changed')
        final = s['helper'].full_scan(ROOT)
        need(final['allocated_envelope_bytes'] <= s['allocation']['allocated_envelope_bytes'] + RESERVATION and
             final['allocated_envelope_bytes'] <= 14 * 1024**3, 'envelope', 'Recovery exceeded its fixed allocation reservation')
        for path, meta in s['allocation']['files'].items():
            if not path.startswith('audit/cache-fast-') and path != 'audit/cache-unpacked.jsonl' and path != 'downloads/mathlib-cache/' + LTAR:
                need(final['files'].get(path) == meta, 'outside_write', 'Recovery altered another original file')
        need(all(path.startswith('audit/cache-fast-') for path in set(final['files']) - set(s['allocation']['files'])),
             'outside_write', 'Recovery created a file outside its bounded audit namespace')
        s['helper'].volume_reserves(); verify_pins(review['sourcePins']); native_actors()
        need(time.monotonic() - started <= WALL, 'wall_limit', 'Original3hour stage cap exceeded')
        closure = {'protocol': PROTOCOL, 'closed': False, 'state': 'awaiting_native_lease_release',
            'nativeLeaseHandlesClosed': False, 'nonce': nonce, 'restore_pid': os.getpid(),
            'restore_pid_absence_certified': False, 'source_sha256': sha(__file__), 'source_before': s['source'],
            'actual_review_pin': review['_actual_review_pin'], 'gate_pin': review['production_authorization']['gatePin'],
            'root_review_pin': review['production_authorization']['independentReviewPin'],
            'source_after': source_after, 'input_provenance': s['provenance'], 'history_pin': hp,
            'intent_pin': pin(intent_path), 'actors': s['actors'], 'stage_before': stage_before,
            'stage_after': stage_after, 'new_pending_commit': new, 'base_prefix': BASE,
            'recovery_objects': 21, 'processed_prefix': TARGET, 'original_requested_count': 64,
            'original_batch_exit_fabricated': False, 'original_batch_closed': False,
            'cache_unpack_complete': False, 'receipts_sha256': sha(audit / 'cache-unpacked.jsonl'),
            'commits_sha256': sha(audit / 'cache-fast-commits.jsonl'), 'final_envelope': final['allocated_envelope_bytes'],
            'controls_executed': False, 'decoder_executed': False, 'public_get': False,
            'decoded_objects': 0, 'llm_called': False, 'candidate_run': False, 'recorded_at_utc': now()}
        fsync_json(receipt_path, closure, fresh=True)
        # The old bytes remain archived. No marker is relabelled as batch061 success.
        old_guard.close(); old_fast_path.rename(history / 'original-fast-marker-moved.lock')
        (audit / 'cache-fast-item.json').rename(history / 'original-item-moved.json')
        (audit / 'cache-fast-container.json').rename(history / 'original-owner-moved.json')
        fsync_json(audit / 'cache-fast-container.json', {'protocol': PROTOCOL, 'state': 'recovery_no_decoder',
            'former_container_id': CID, 'former_owner_label': OWNER, 'actual_former_container_absent': True,
            'nonce': nonce, 'recorded_at_utc': now()}, fresh=True)
        fresh_fast = stack.enter_context(WinFile(old_fast_path, fresh=True))
        fresh_fast.write({'protocol': PROTOCOL, 'held': False, 'pid': os.getpid(), 'nonce': nonce,
                          'outcome': 'recovery_closed', 'recorded_at_utc': now()})
        own.write({'protocol': PROTOCOL, 'held': False, 'pid': os.getpid(), 'nonce': nonce,
                   'outcome': 'recovery_closed', 'recorded_at_utc': now()})
        phase = 'handles_releasing'
    except BaseException as error:
        failure = error
        if own is not None and own.stream is not None:
            try: own.write({'protocol': PROTOCOL, 'held': False, 'pid': os.getpid(), 'nonce': nonce,
                            'outcome': 'infrastructure_invalid', 'phase': phase, 'error_type': getattr(error, 'kind', type(error).__name__)})
            except BaseException: pass
        raise
    finally: stack.close()
    # All three original/native exclusion handles have really closed first.
    with WinFile(acquisition_path) as a:
        need(digest(a.raw()) == '24f91e9a9790a0d14a94e6e5f530af0fa51c8823203a94eae5d68f9cd026a368',
             'acquisition_changed', 'Original complete marker was modified')
    for p in [old_fast_path, lease_path]:
        with WinFile(p) as h:
            marker = json.loads(h.raw()); need(marker['held'] is False and marker['nonce'] == nonce,
                                              'lease_unclosed', 'Actual reopened lease differs')
    closure.update(closed=True, state='recovery_closed', nativeLeaseHandlesClosed=True,
                   fast_lease_pin=pin(old_fast_path), recovery_lease_pin=pin(lease_path))
    rp = fsync_json(receipt_path, closure)
    baseline = {'protocol': FAST, 'recovery_protocol': PROTOCOL, 'state': 'recovery_closed',
        'validated': True, 'processed_prefix': TARGET, 'prefix_before': BASE,
        'recovery_objects': 21, 'original_requested_count': 64, 'original_batch_closed': False,
        'requested_count': 0, 'reviewed_script_sha256': sha(__file__), 'original_producer_sha256': FAST_SHA,
        'source_before': s['source'], 'source_after': closure['source_after'],
        'input_provenance': s['provenance'], 'receipts_sha256': closure['receipts_sha256'],
        'commits_sha256': closure['commits_sha256'], 'cache_unpack_complete': False,
        'lease_handle_closed': True, 'fast_lease_release_sha256': sha(old_fast_path),
        'recovery_receipt_pin': rp, 'history_pin': closure['history_pin'], 'intent_pin': closure['intent_pin'],
        'final_envelope': closure['final_envelope'], 'controls_executed': False, 'candidate_run': False,
        'llm_called': False, 'public_get': False, 'recorded_at_utc': now()}
    bp = fsync_json(audit / 'cache-fast-progress.json', baseline)
    # Mandatory new-entry witness: an old Gate alone cannot certify recovery.
    # If final baseline fsync/receipt fails, CheckClosed and the new serial
    # entry refuse even if a positive-looking baseline exists on disk.
    commit_pin = fsync_json(audit / 'cache-fast-nonzero-baseline-commit.json',
        {'protocol': PROTOCOL, 'nonce': nonce, 'baseline_pin': bp, 'recovery_receipt_pin': rp,
         'baseline_fsync_returned': True, 'all_native_exclusion_handles_closed': True,
         'source_sha256': sha(__file__), 'recorded_at_utc': now()}, fresh=True)
    envelope_after = s['helper'].full_scan(ROOT)['allocated_envelope_bytes']
    need(envelope_after + 16384 <= s['allocation']['allocated_envelope_bytes'] + RESERVATION and
         envelope_after + 16384 <= 14 * 1024**3, 'envelope', 'Final recovery metadata exceeded its fixed reservation')
    s['helper'].volume_reserves(16384)
    envelope_pin = fsync_json(audit / 'cache-fast-nonzero-final-envelope.json',
        {'protocol': PROTOCOL, 'nonce': nonce, 'baseline_commit_pin': commit_pin,
         'measured_allocation_before_this_small_record': envelope_after,
         'final_allocation_upper_bound': envelope_after + 16384,
         'initial_allocation': s['allocation']['allocated_envelope_bytes'], 'reservation': RESERVATION,
         'cap': 14 * 1024**3, 'E_min_free': 3 * 1024**3, 'F_min_free': 1024**3,
         'source_sha256': sha(__file__), 'recorded_at_utc': now()}, fresh=True)
    return {'protocol': PROTOCOL, 'recovery_receipt_pin': rp, 'baseline_pin': bp, 'baseline_commit_pin': commit_pin,
            'final_envelope_pin': envelope_pin,
            'processed_prefix': TARGET, 'original_batch_closed': False, 'full5826_closed': False,
            'require_separate_check_closed_after_process_exit': True}


def verify_baseline_commit(record, baseline_pin, receipt_pin, nonce, source_sha):
    need(isinstance(record, dict) and record.get('protocol') == PROTOCOL and record.get('nonce') == nonce and
         record.get('baseline_fsync_returned') is True and record.get('all_native_exclusion_handles_closed') is True and
         record.get('source_sha256') == source_sha and record.get('baseline_pin') == baseline_pin and
         record.get('recovery_receipt_pin') == receipt_pin, 'closure_graph', 'Mandatory actual baseline commit witness differs')


def check_closed(review):
    verify_pins(review['sourcePins']); audit = ROOT / 'audit'
    receipt = json.loads((audit / 'cache-fast-nonzero-recovery.json').read_bytes())
    baseline = json.loads((audit / 'cache-fast-progress.json').read_bytes())
    baseline_commit = json.loads((audit / 'cache-fast-nonzero-baseline-commit.json').read_bytes())
    verify_baseline_commit(baseline_commit, pin(audit / 'cache-fast-progress.json'),
                           pin(audit / 'cache-fast-nonzero-recovery.json'), receipt['nonce'], sha(__file__))
    need(receipt['protocol'] == PROTOCOL and receipt['closed'] is True and
         type(receipt.get('restore_pid')) is int and receipt['restore_pid'] > 0 and
         receipt['nativeLeaseHandlesClosed'] is True and receipt['processed_prefix'] == TARGET and
         receipt['cache_unpack_complete'] is False and receipt['original_batch_closed'] is False and
         receipt['source_sha256'] == sha(__file__) and baseline['state'] == 'recovery_closed' and
         baseline['processed_prefix'] == TARGET and baseline['reviewed_script_sha256'] == sha(__file__) and
         baseline['recovery_receipt_pin'] == pin(audit / 'cache-fast-nonzero-recovery.json') and
         baseline_commit['protocol'] == PROTOCOL and baseline_commit['nonce'] == receipt['nonce'] and
         baseline_commit['baseline_fsync_returned'] is True and baseline_commit['all_native_exclusion_handles_closed'] is True and
         baseline_commit['source_sha256'] == sha(__file__) and baseline_commit['baseline_pin'] == pin(audit / 'cache-fast-progress.json') and
         baseline_commit['recovery_receipt_pin'] == pin(audit / 'cache-fast-nonzero-recovery.json'),
         'closure_graph', 'This is not the exact3927 recovery baseline')
    for p in [receipt['history_pin'], receipt['intent_pin'], receipt['fast_lease_pin'], receipt['recovery_lease_pin'],
              receipt['new_pending_commit']['fsync_witness_pin'], receipt['new_pending_commit']['commit_witness_pin'],
              receipt['actual_review_pin'], receipt['gate_pin'], receipt['root_review_pin']]:
        verify_pins([p])
    envelope = json.loads((audit / 'cache-fast-nonzero-final-envelope.json').read_bytes())
    need(envelope['protocol'] == PROTOCOL and envelope['nonce'] == receipt['nonce'] and
         envelope['baseline_commit_pin'] == pin(audit / 'cache-fast-nonzero-baseline-commit.json') and
         envelope['source_sha256'] == sha(__file__) and envelope['final_allocation_upper_bound'] <= 14 * 1024**3 and
         envelope['final_allocation_upper_bound'] <= envelope['initial_allocation'] + RESERVATION,
         'envelope', 'Final allocation certificate differs')
    need(sha(audit / 'cache-unpacked.jsonl') == receipt['receipts_sha256'] and
         sha(audit / 'cache-fast-commits.jsonl') == receipt['commits_sha256'], 'closure_graph', 'Current journals changed')
    history = json.loads(Path(receipt['history_pin']['path']).read_bytes())
    verify_pins(history['old_metadata'])
    for x in history['executed_sources']: verify_pins([x['archived']])
    need(stage_ids(Path(receipt['history_pin']['path']).parent / 'original-stage') == receipt['stage_after'] == receipt['stage_before'],
         'stage_changed', 'Archived28-directory identity graph changed')
    need(not (audit / 'cache-fast-item.json').exists(), 'unknown_item', 'New pending materialization exists')
    owner = json.loads((audit / 'cache-fast-container.json').read_bytes())
    need(owner['protocol'] == PROTOCOL and owner['state'] == 'recovery_no_decoder' and owner['nonce'] == receipt['nonce'] and
         owner['former_container_id'] == CID and owner['actual_former_container_absent'] is True, 'owner_changed', 'Recovery owner graph differs')
    fast = module_fast(); helper, _, _, provenance, prior, _ = fast.gate(REPO)
    need(len(prior) == TARGET and provenance == receipt['input_provenance'] and
         fast.source_identity(REPO, ROOT, helper) == receipt['source_after'], 'closure_graph', 'Full actual outputs/source/provenance changed')
    native_actors()
    # PID absence for the new restorer is checked after its actual exit.
    ps = Path(os.environ.get('SystemRoot', 'C:/Windows')) / 'System32/WindowsPowerShell/v1.0/powershell.exe'
    code = "$ErrorActionPreference='Stop';$p=Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(receipt['restore_pid']) + "' -ErrorAction Stop;[pscustomobject]@{present=($null -ne $p)}|ConvertTo-Json -Compress"
    env = dict(os.environ); env['PSModulePath'] = os.pathsep.join([str(ps.parent / 'Modules'),
        str(Path(os.environ.get('ProgramFiles', 'C:/Program Files')) / 'WindowsPowerShell/Modules')])
    q = subprocess.run([str(ps), '-NoProfile', '-NonInteractive', '-Command', code], capture_output=True, timeout=30, env=env)
    need(q.returncode == 0 and json.loads(q.stdout.decode('utf-8-sig'))['present'] is False,
         'restore_actor_present', 'Actual restorer process has not exited')
    for name, expected in [('public-cache-acquisition.lock', '24f91e9a9790a0d14a94e6e5f530af0fa51c8823203a94eae5d68f9cd026a368'),
                           ('cache-fast-unpack.lock', receipt['fast_lease_pin']['sha256']),
                           ('cache-fast-nonzero-recovery.lock', receipt['recovery_lease_pin']['sha256'])]:
        with WinFile(audit / name) as handle: need(digest(handle.raw()) == expected, 'lease_changed', 'Actual exclusive reopen marker differs')
    return {'protocol': PROTOCOL, 'validated': True, 'processed_prefix': TARGET,
            'actual_restore_pid_absent': True, 'historical_actors_absent': True,
            'exact_historical_container_absent': True, 'all_native_handles_reopened_and_closed': True,
            'original64_batch_closed': False, 'full5826_closed': False, 'receipt_pin': pin(audit / 'cache-fast-nonzero-recovery.json'),
            'baseline_pin': pin(audit / 'cache-fast-progress.json'), 'recorded_at_utc': now()}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--stage', choices=['Gate', 'Restore', 'CheckClosed'], required=True)
    p.add_argument('--review', required=True); p.add_argument('--review-sha', required=True)
    a = p.parse_args(); need(os.name == 'nt', 'platform', 'Actual Windows host required')
    review = load_review(a.review, a.review_sha)
    result = {'Gate': gate, 'Restore': restore, 'CheckClosed': check_closed}[a.stage](review)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    try: main()
    except BaseException as error:
        import sys
        print(json.dumps({'protocol': PROTOCOL, 'validated': False, 'error_type': getattr(error, 'kind', type(error).__name__),
                          'error': str(error), 'original_batch_closed': False, 'full5826_closed': False,
                          'decoder_executed': False, 'public_get': False, 'llm_called': False}), file=sys.stderr)
        raise SystemExit(1)
