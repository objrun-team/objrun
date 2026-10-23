"""Bounded native Windows snapshot of twelve fixed, stopped science DB files.

No SQLite driver is imported. Original files are opened as byte streams only.
All twelve deny-write/delete source handles are obtained before copying starts.
Only a fresh same-thread D sibling is writable in production; controls use newly
created F fixtures. No source rename/delete, paid-lock mutation, API, or scoring.
"""
from __future__ import annotations
import argparse
import ctypes
from ctypes import wintypes as w
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[2]
RUN = 'repair-2026-10-08T18-32-57-118Z'
THREAD = '01a119ed-fdf7-7c32-b323-de9bab1290b6'
OWNER = Path('D:/objrun-experiment-stores') / THREAD
STORE = OWNER / ('scientific-journal-v2-' + RUN)
META = ROOT / 'docs/repair-2026-10-08/campaigns' / RUN
FIRST = ROOT / 'docs/repair-2026-10-08' / ('scientific-interruption-' + RUN) / 'first-pass.json'
FIRST_SHA = '204cc6a0bfa793934b4abdfd78534a57ee606295feffe24a6878c76732652758'
NATIVE_EXE = Path('D:/ProgramData/anaconda3/python.exe')
NATIVE_SHA = '6965927a96b81d1717c1d2186de7feb9b29ebf8775464020ebc2f25de6ef8ee0'
PS = Path('C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe')
LIMIT = 512 * 1024**2
D_RESERVE = 1024**3
REPORT_LIMIT = 300 * 1024
FIXTURE_BASE = ROOT / '.scratch/scientific-db-snapshot-controls'
_FIXTURES = set()
_ACTIVE_HANDLES = set()


def need(ok, reason):
    if not ok:
        raise RuntimeError(reason)


def utc():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pin(path):
    path = Path(path).absolute()
    with path.open('rb') as handle:
        h = hashlib.sha256()
        n = 0
        while chunk := handle.read(1024**2):
            h.update(chunk)
            n += len(chunk)
    return {'path': str(path), 'bytes': n, 'sha256': h.hexdigest()}


def verify(value):
    actual = pin(value['path'])
    need(actual == value, 'pin_changed')
    return actual


def ordinary(path, *, file=False):
    path = Path(path).absolute()
    need(path.resolve() == path, 'reparse_or_noncanonical_path')
    for parent in [path, *path.parents]:
        s = parent.lstat()
        need(not parent.is_symlink() and not (getattr(s, 'st_file_attributes', 0) & 0x400), 'reparse_path')
        need(stat.S_ISREG(s.st_mode) if parent == path and file else stat.S_ISDIR(s.st_mode), 'not_ordinary_path')
    return path


def new_dirs(path):
    path = Path(path).absolute()
    ancestor = path
    while not ancestor.exists():
        ancestor = ancestor.parent
    ordinary(ancestor)
    path.mkdir(parents=True, exist_ok=True)
    ordinary(path)


def files(store):
    return [Path(store) / f'worker-{worker}/data/h2h.sqlite{suffix}'
            for worker in range(4) for suffix in ['', '-wal', '-shm']]


K = ctypes.WinDLL('kernel32', use_last_error=True)
K.CreateFileW.argtypes = [w.LPCWSTR, w.DWORD, w.DWORD, ctypes.c_void_p, w.DWORD, w.DWORD, w.HANDLE]
K.CreateFileW.restype = w.HANDLE
K.CloseHandle.argtypes = [w.HANDLE]
K.CloseHandle.restype = w.BOOL
K.ReadFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
K.ReadFile.restype = w.BOOL
K.WriteFile.argtypes = [w.HANDLE, ctypes.c_void_p, w.DWORD, ctypes.POINTER(w.DWORD), ctypes.c_void_p]
K.WriteFile.restype = w.BOOL
K.SetFilePointerEx.argtypes = [w.HANDLE, ctypes.c_longlong, ctypes.c_void_p, w.DWORD]
K.SetFilePointerEx.restype = w.BOOL
K.FlushFileBuffers.argtypes = [w.HANDLE]
K.FlushFileBuffers.restype = w.BOOL
K.GetDiskFreeSpaceExW.argtypes = [w.LPCWSTR, ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong), ctypes.POINTER(ctypes.c_ulonglong)]
K.GetDiskFreeSpaceExW.restype = w.BOOL


class FileInformation(ctypes.Structure):
    _fields_ = [('attributes', w.DWORD), ('creation', w.FILETIME), ('access', w.FILETIME),
                ('write', w.FILETIME), ('volume', w.DWORD), ('sizeHigh', w.DWORD),
                ('sizeLow', w.DWORD), ('links', w.DWORD), ('indexHigh', w.DWORD), ('indexLow', w.DWORD)]


K.GetFileInformationByHandle.argtypes = [w.HANDLE, ctypes.POINTER(FileInformation)]
K.GetFileInformationByHandle.restype = w.BOOL
INVALID = ctypes.c_void_p(-1).value
READ, WRITE, SHARE_READ = 0x80000000, 0x40000000, 1
EXISTING, CREATE_NEW, FLAGS = 3, 1, 0x08000000 | 0x00200000


def win(ok):
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())


def free(path):
    a, b, c = (ctypes.c_ulonglong() for _ in range(3))
    win(K.GetDiskFreeSpaceExW(str(Path(path).anchor), ctypes.byref(a), ctypes.byref(b), ctypes.byref(c)))
    return a.value


class NativeFile:
    def __init__(self, path, *, write=False):
        self.path = Path(path).absolute()
        self.handle = K.CreateFileW(str(self.path), WRITE if write else READ,
                                   0 if write else SHARE_READ, None,
                                   CREATE_NEW if write else EXISTING, FLAGS, None)
        if self.handle in [None, INVALID]:
            raise ctypes.WinError(ctypes.get_last_error())
        _ACTIVE_HANDLES.add(self.handle)
        self.write = write
        self.closed = False
        try:
            v = self.info()
            need(not (v['attributes'] & (0x400 | 0x10)), 'native_source_not_regular_or_reparse')
        except Exception:
            self.close()
            raise

    def info(self):
        v = FileInformation()
        win(K.GetFileInformationByHandle(self.handle, ctypes.byref(v)))
        return {'attributes': v.attributes, 'volumeSerial': str(v.volume),
                'fileId': str((v.indexHigh << 32) | v.indexLow),
                'bytes': (v.sizeHigh << 32) | v.sizeLow, 'links': v.links,
                'writeTime100ns': str((v.write.dwHighDateTime << 32) | v.write.dwLowDateTime),
                'creationTime100ns': str((v.creation.dwHighDateTime << 32) | v.creation.dwLowDateTime)}

    def chunks(self):
        win(K.SetFilePointerEx(self.handle, 0, None, 0))
        buffer = ctypes.create_string_buffer(1024**2)
        while True:
            n = w.DWORD()
            win(K.ReadFile(self.handle, buffer, len(buffer), ctypes.byref(n), None))
            if not n.value:
                break
            yield buffer.raw[:n.value]

    def sha(self):
        before = self.info()
        h, n = hashlib.sha256(), 0
        for chunk in self.chunks():
            h.update(chunk)
            n += len(chunk)
        after = self.info()
        need(before == after and n == before['bytes'], 'source_identity_or_size_changed')
        return {'path': str(self.path), 'bytes': n, 'sha256': h.hexdigest(), 'nativeIdentity': after}

    def put(self, chunk):
        buffer = ctypes.create_string_buffer(chunk)
        offset = 0
        while offset < len(chunk):
            n = w.DWORD()
            win(K.WriteFile(self.handle, ctypes.byref(buffer, offset), len(chunk) - offset, ctypes.byref(n), None))
            need(n.value > 0, 'target_short_write')
            offset += n.value

    def flush(self):
        win(K.FlushFileBuffers(self.handle))

    def close(self):
        if self.closed:
            return
        win(K.CloseHandle(self.handle))
        _ACTIVE_HANDLES.discard(self.handle)
        self.closed = True


def metadata(store):
    result = []
    for path in files(store):
        ordinary(path, file=True)
        s = path.stat()
        result.append({'path': str(path), 'bytes': s.st_size, 'device': str(s.st_dev),
                       'fileId': str(s.st_ino), 'mtimeNs': str(s.st_mtime_ns),
                       'sourceRelativePath': str(path.relative_to(store))})
    need(len(result) == 12 and sum(p['bytes'] for p in result) * 2 <= LIMIT, 'twelve_file_or_512MiB_bound')
    return result


def original_lock():
    need(pin(FIRST)['sha256'] == FIRST_SHA, 'original_first_pass_changed')
    first = json.loads(FIRST.read_bytes())
    expected = first['lock']['pin']
    need(Path(expected['path']).absolute() == ROOT / '.phase1-data/owned-paid-campaign.lock.json', 'canonical_lock_path')
    ordinary(expected['path'], file=True)
    verify(expected)
    record = json.loads(Path(expected['path']).read_bytes())
    need(record == first['lock']['record'] and record['runId'] == RUN and record['pid'] == 104376,
         'canonical_original_owner_changed')
    return {'pin': expected, 'record': record}


def actors():
    lock = original_lock()
    first = json.loads(FIRST.read_bytes())
    pids, ports, pins = [104376], [], []
    for i in range(4):
        expected = first['processes'][i]['pin']
        ordinary(expected['path'], file=True)
        verify(expected)
        record = json.loads(Path(expected['path']).read_bytes())
        from urllib.parse import urlsplit
        address = urlsplit(record['base'])
        need(record['worker'] == i and record['runId'] == RUN and record['ownerNonce'] == lock['record']['ownerNonce']
             and address.hostname == '127.0.0.1' and type(address.port) is int, 'original_worker_identity')
        pids.append(record['pid'])
        ports.append(address.port)
        pins.append(expected)
    need(len(set(pids)) == 5 and len(set(ports)) == 4, 'five_actor_four_port_set')
    filt = ' OR '.join(f'ProcessId={n}' for n in pids)
    tcp = ' OR '.join(f'LocalPort={n}' for n in ports)
    command = ("$ErrorActionPreference='Stop';$taskP=@(Get-CimInstance Win32_Process -Filter '" + filt +
               "' | ForEach-Object{@{pid=[int]$_.ProcessId;createdAtUtc=$_.CreationDate.ToUniversalTime().ToString('o');name=$_.Name}});" +
               "$taskT=@(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter '" + tcp +
               "' | ForEach-Object{@{port=[int]$_.LocalPort;pid=[int]$_.OwningProcess}});" +
               "@{observedAtUtc=[DateTime]::UtcNow.ToString('o');processes=$taskP;tcp=$taskT}|ConvertTo-Json -Depth 5 -Compress")
    started = time.monotonic()
    proc = subprocess.run([str(PS), '-NoProfile', '-NonInteractive', '-Command', command],
                          stdin=subprocess.DEVNULL, capture_output=True, timeout=15,
                          creationflags=subprocess.CREATE_NO_WINDOW)
    need(proc.returncode == 0, 'fresh_actor_query_unknown')
    result = json.loads(proc.stdout.decode('utf-8-sig'))
    need(result['processes'] == [] and result['tcp'] == [] and time.monotonic() - started < 15,
         'original_actor_or_recorded_port_present')
    verify(lock['pin'])
    return {'lock': lock, 'pids': pids, 'recordedWorkerPorts': ports, 'workerReceiptPins': pins,
            'actualNativeObservation': result, 'proxyPortNotAssumed': True}


def copy_one(source, destination, expected):
    ordinary(destination.parent)
    need(not destination.exists(), 'target_already_exists')
    target = NativeFile(destination, write=True)
    h, count = hashlib.sha256(), 0
    flushed = False
    try:
        for chunk in source.chunks():
            target.put(chunk)
            h.update(chunk)
            count += len(chunk)
        need(count == expected['bytes'] and h.hexdigest() == expected['sha256'], 'copied_bytes_mismatch')
        target.flush()
        flushed = True
    finally:
        target.close()
    ordinary(destination, file=True)
    probe = NativeFile(destination)
    try:
        observed = probe.sha()
    finally:
        probe.close()
    need(observed['bytes'] == count and observed['sha256'] == h.hexdigest(), 'target_readback_mismatch')
    return {**observed, 'FlushFileBuffersReturned': flushed, 'createNew': True}


def snapshot_core(source_store, target, guard, *, fixture=False, hook=None):
    source_store, target = Path(source_store).absolute(), Path(target).absolute()
    if fixture:
        need(source_store in _FIXTURES and target.parent == source_store.parent and not target.exists(), 'fixture_root_not_self_created')
    else:
        need(source_store == STORE and target.parent == OWNER and target.name.startswith('scientific-db-snapshot-' + RUN + '-'), 'production_owned_roots')
        need(guard is actors and hook is None, 'production_guard_must_be_native')
        need(free(OWNER) - 2 * sum(p['bytes'] for p in metadata(STORE)) >= D_RESERVE, 'D_reserve')
    initial = metadata(source_store)
    ordinary(target.parent)
    need(not target.exists(), 'fresh_target_required')
    source_handles, before, copied, after, observations = [], [], [], [], []
    result = {'protocol': 'science-worker-db-snapshot-v1', 'runId': RUN, 'fixtureOnly': fixture,
              'validated': False, 'snapshotComplete': False, 'sourceStore': str(source_store), 'target': str(target),
              'initialMetadata': initial, 'rawCopies': [], 'workingCopies': [], 'originalSqliteOpened': False,
              'models': 0, 'gradingCalls': 0, 'paidLockMutations': 0, 'proxyPortEstablished': False}
    try:
        observations.append(guard())
        for path in files(source_store):
            ordinary(path, file=True)
            handle = NativeFile(path)
            source_handles.append(handle)
            ordinary(path, file=True)
            need(handle.info()['fileId'] == str(path.stat().st_ino), 'native_handle_path_identity')
        need(len(source_handles) == 12 and len({(h.info()['volumeSerial'], h.info()['fileId']) for h in source_handles}) == 12,
             'all_twelve_distinct_source_handles_required')
        before = [handle.sha() for handle in source_handles]
        result['sourceBefore'] = before
        result['allSourceHandlesAcquiredBeforeAnyCopy'] = True
        observations.append(guard())
        if hook:
            need(fixture, 'production_hooks_forbidden')
            hook('all_handles', source_handles, target)
        target.mkdir(exist_ok=False)
        for phase in ['raw', 'working']:
            for item, handle in zip(before, source_handles):
                relative = handle.path.relative_to(source_store)
                destination = target / phase / relative
                new_dirs(destination.parent)
                ordinary(destination.parent)
                need(destination.is_relative_to(target), 'target_escape')
                if not fixture:
                    need(free(OWNER) >= D_RESERVE + item['bytes'] + 1024**2, 'D_reserve_before_file')
                record = copy_one(handle, destination, item)
                copied.append(record)
                result['rawCopies' if phase == 'raw' else 'workingCopies'].append(record)
                need(sum(p['bytes'] for p in copied) <= LIMIT, 'copied_512MiB_bound')
                if hook:
                    hook('copied_file', source_handles, target)
        after = [handle.sha() for handle in source_handles]
        result['sourceAfter'] = after
        need(before == after and initial == metadata(source_store), 'original_changed_during_snapshot')
        for value in copied:
            need(pin(value['path'])['sha256'] == value['sha256'] and pin(value['path'])['bytes'] == value['bytes'], 'final_target_changed')
        observations.append(guard())
        result.update(validated=True, snapshotComplete=True, originalBytesUnchanged=True,
                      copiedLogicalBytes=sum(p['bytes'] for p in copied), actorObservations=observations,
                      sourceDenyWriteAndDelete=True, sourceShareReadOnly=True, originalNeverRenamedOrDeleted=True,
                      postCopyProxyPolicy='Do not assume a port. Only a separate reviewed reader may open raw immutable checkpointed copies or working WAL-aware copies and select api.base_url; bind a unique localhost origin to the copy Pin.')
    except Exception as error:
        result['error'] = type(error).__name__ + ':' + str(getattr(error, 'winerror', None) or error)
        result['partialOwnedTargetPreserved'] = target.exists()
        result['noDeleteOrRenamePerformed'] = True
        try:
            result['sourceAfterFailure'] = [handle.sha() for handle in source_handles]
            result['originalBytesUnchangedAfterFailure'] = len(before) == 12 and before == result['sourceAfterFailure']
        except Exception:
            result['originalBytesUnchangedAfterFailure'] = None
    finally:
        close_errors = []
        for handle in source_handles:
            try:
                handle.close()
            except Exception as error:
                close_errors.append(type(error).__name__)
        result['sourceHandlesClosed'] = not close_errors
        if close_errors:
            result['validated'] = result['snapshotComplete'] = False
            result['closeErrors'] = close_errors
    return result


def create_fixture():
    top = FIXTURE_BASE / uuid.uuid4().hex
    source = top / 'original'
    for i, path in enumerate(files(source)):
        new_dirs(path.parent)
        path.write_bytes(bytes([i]) * (4096 + i))
    _FIXTURES.add(source.absolute())
    return source.absolute(), top / 'snapshot'


def fixture_snapshot(source, target, *, hook=None):
    need(Path(source).absolute() in _FIXTURES, 'fixture_root_not_self_created')
    return snapshot_core(source, target, lambda: {'fixtureOnly': True, 'nativeActorQueriesRun': False}, fixture=True, hook=hook)


def save_new(path, value):
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    need(len(raw) <= REPORT_LIMIT, 'F_receipt_300KiB_bound')
    with path.open('xb') as handle:
        handle.write(raw)
        handle.flush()
        os.fsync(handle.fileno())
    need(path.read_bytes() == raw, 'F_receipt_readback')
    return pin(path)


def review_guard(path, expected_sha):
    ordinary(path, file=True)
    value = pin(path)
    need(value['sha256'] == expected_sha, 'review_changed')
    review = json.loads(Path(path).read_bytes())
    need(review['protocol'] == 'science-worker-db-snapshot-review-v1' and review['validated'] is True
         and review['productionSnapshotPerformed'] is False, 'review_profile')
    verify(review['sourcePin'])
    need(Path(review['sourcePin']['path']).absolute() == Path(__file__).resolve(), 'review_wrong_source')
    verify(review['launcherPin'])
    verify(review['controlsPin'])
    need(pin(Path(sys.executable).resolve())['sha256'] == NATIVE_SHA, 'absolute_native_interpreter_required')
    return value


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', required=True, choices=['gate', 'snapshot'])
    parser.add_argument('--review', type=Path, required=True)
    parser.add_argument('--review-sha', required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    args = parser.parse_args()
    out = args.receipt.absolute()
    need(out.is_relative_to(ROOT / 'docs/repair-2026-10-08/science-db-snapshots') and not out.exists(), 'fresh_F_receipt_scope')
    new_dirs(out.parent)
    review_before = review_guard(args.review, args.review_sha)
    result = {'protocol': 'science-worker-db-snapshot-gate-v1', 'mode': args.mode,
              'observedAtUtc': utc(), 'validated': False, 'runId': RUN, 'reviewPin': review_before,
              'sourcePin': pin(Path(__file__).resolve()), 'originalSqliteOpened': False}
    try:
        need(Path(sys.executable).resolve() == NATIVE_EXE, 'no_python_shim')
        initial_guard = actors()
        initial = metadata(STORE)
        need(free(OWNER) >= D_RESERVE + 2 * sum(p['bytes'] for p in initial) + 2 * 1024**2, 'D_copy_resource_envelope')
        if args.mode == 'gate':
            result.update(validated=True, snapshotComplete=False, productionCopyCreated=False,
                          sourceMetadata=initial, originalLockAndActors=initial_guard,
                          freeDBytes=free(OWNER), futureCopyLimitBytes=LIMIT, DReserveBytes=D_RESERVE,
                          originalSourceReadHandlesOpened=False, proxyPortNotAssumed=True)
        else:
            target = OWNER / ('scientific-db-snapshot-' + RUN + '-' + uuid.uuid4().hex)
            result = snapshot_core(STORE, target, actors)
            result.update(mode=args.mode, reviewPin=review_before, sourcePin=pin(Path(__file__).resolve()), observedAtUtc=utc())
        need(review_before == review_guard(args.review, args.review_sha), 'review_or_source_changed_during_operation')
    except Exception as error:
        result.update(validated=False, snapshotComplete=False, error=type(error).__name__ + ':' + str(getattr(error, 'winerror', None) or error))
    result.update(scoreCertificate=False, paidRestartAuthorized=False, canonicalLockWritten=False,
                  originalProviderOrConfigRead=False, proxyPortEstablished=False)
    evidence = save_new(out, result)
    print(json.dumps({'receipt': evidence, 'validated': result['validated'], 'mode': args.mode,
                      'snapshotComplete': result.get('snapshotComplete', False), 'originalSqliteOpened': False}))
    return 0 if result['validated'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
