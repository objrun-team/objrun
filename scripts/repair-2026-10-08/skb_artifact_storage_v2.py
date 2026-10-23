"""Independent D-only evidence descriptor and bounded native writes.

No import/Plan creates D directories, starts Docker or calls a provider. Root
must independently approve a new entry/recipe/auditor and actual native/Docker
proof before using this profile. Existing JPG sources and floors are unchanged. This new descriptor binds the exact ten-task selection; it is not the old one-task descriptor.
"""
import argparse
import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import stat
import threading

PROTOCOL = 'skb-ten-owned-D-evidence-storage-v1'
REPO = Path(__file__).resolve().parents[2]
D_PARENT = 'D:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/skillsbench-ten-small-batch'
STORE_CAP = 3 * 1024**3
D_MIN = 3 * 1024**3
F_MIN = C_MIN = 1024**3
F_POINTER_CAP = 1024**2
SOLVER_UPPER_CAP = 10 * 1024**3  # maximum original selected task storage metadata; task-specific bound must also hold
PRIVATE_RAM_CAP = 512 * 1024**2  # explicit new private RAM protocol, old overlay was128MiB
DOCKER_METADATA_RESERVE = 16 * 1024**2
F_STOP_BUFFER = 8 * 1024**2
DIRECTORIES = ('raw', 'sqlite', 'journal', 'cash', 'source', 'taskmeta', 'private-logs',
               'stand', 'captures', 'tmp', 'python-cache', 'bun-cache', 'leases', 'audit')
STAGES = {'provider': 'raw', 'engine_db': 'sqlite', 'journal': 'journal', 'cash': 'cash',
          'frozen_source_zip': 'source', 'task_metadata': 'taskmeta', 'private_grade': 'private-logs',
          'stand': 'stand', 'capture': 'captures', 'host_temp': 'tmp', 'python_bytecode': 'python-cache',
          'bun_cache': 'bun-cache', 'native_owner_lease': 'leases', 'closing_audit': 'audit'}


class StorageFault(RuntimeError):
    def __init__(self, kind, detail): super().__init__(detail); self.kind = kind


def require(value, kind, detail):
    if not value: raise StorageFault(kind, detail)


def fingerprint(path):
    p = Path(path); z = p.lstat()
    require(stat.S_ISREG(z.st_mode) and not getattr(z, 'st_file_attributes', 0) & 0x400,
            'nonregular_input', 'Pinned input must be an ordinary regular file')
    with p.open('rb') as f: h = hashlib.file_digest(f, 'sha256').hexdigest()
    require(p.stat().st_size == z.st_size, 'source_race', 'Pinned input changed during hashing')
    return {'path': str(p), 'bytes': z.st_size, 'sha256': h}


def canonical(value): return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode() + b'\n'
def allocation(size): return max(4096, (size + 4095) // 4096 * 4096)


def selection_manifest_pin():
    path = REPO / 'docs/repair-2026-10-08/skillsbench-ten-artifact-readonly-preflight/selection-v1/ten-task-list.json'
    item = fingerprint(path)
    require(item['sha256'] == 'f4b8781fc636d67af17265bfffe41d9ff76195f4e9539d6cd37b5db6b29ee021',
            'selection_changed', 'Exact public ten-task paired selection changed')
    value = json.loads(path.read_bytes())
    require(value.get('taskCount') == 10 and value.get('methods') == ['U', 'F'] and value.get('sameOrderedListRequired') is True,
            'selection', 'Wrong fixed paired task schedule')
    return item


def descriptor(nonce):
    require(isinstance(nonce, str) and re.fullmatch('[0-9a-f]{32}', nonce), 'nonce', 'Fresh explicit32-hex owner nonce required')
    root = D_PARENT + '/' + nonce
    dirs = {name: root + '/' + name for name in DIRECTORIES}
    return {'protocol': PROTOCOL, 'ownerNonce': nonce, 'storeLogical': root, 'storePhysical': root,
        'directories': dirs, 'stageMapping': {k: dirs[v] for k, v in STAGES.items()},
        'storeMaximumAllocatedBytes': STORE_CAP, 'DMinimumFreeBytes': D_MIN,
        'FMinimumFreeBytes': F_MIN, 'CMinimumFreeBytes': C_MIN, 'FPointerMaximumAllocatedBytes': F_POINTER_CAP,
        'solverUpperMaximumBytes': SOLVER_UPPER_CAP, 'privateSharedRamMaximumBytes': PRIVATE_RAM_CAP,
        'dockerMetadataReserveBytes': DOCKER_METADATA_RESERVE, 'FStopBufferBytes': F_STOP_BUFFER,
        'FPointerDirectory': str(REPO / 'docs/repair-2026-10-08/skb-ten-D-store-pointers' / nonce),
        'nativeEnvironment': {'TEMP': dirs['tmp'], 'TMP': dirs['tmp'], 'TMPDIR': dirs['tmp'],
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONPYCACHEPREFIX': dirs['python-cache'],
            'BUN_RUNTIME_TRANSPILER_CACHE_PATH': dirs['bun-cache'] + '/transpiler',
            'BUN_INSTALL_CACHE_DIR': dirs['bun-cache'] + '/install', 'XDG_CACHE_HOME': dirs['bun-cache']},
        'nativePythonArguments': ['-B', '-X', 'utf8'], 'profileSourcePin': fingerprint(__file__),
        'namespaceReady': False, 'actualDIdentityValidated': False, 'actualDockerTmpfsValidated': False,
        'paidReady': False, 'DockerMutations': 0, 'modelCalls': 0,
        'scope': 'Only fixed ten-distinct-task paired U/F SkillsBench evidence; physical geometry reused in a new explicit scope; originals not moved',
        'selectionManifestPin': selection_manifest_pin()}


def validate_descriptor(value):
    require(isinstance(value, dict) and value.get('protocol') == PROTOCOL, 'profile', 'Wrong independent storage profile')
    expected = descriptor(value.get('ownerNonce'))
    require(value == expected, 'profile_changed', 'Profile fields/source/paths/caps differ from the exact prepared descriptor')
    return expected


def native_environment(value, existing=None):
    validate_descriptor(value)
    env = dict(existing or {})
    env.update(value['nativeEnvironment'])
    return env


def path_for(value, stage, relative):
    validate_descriptor(value)
    require(stage in STAGES and isinstance(relative, str) and relative and '\\' not in relative and ':' not in relative and
            len(relative.encode()) <= 240 and not any(ord(c) < 32 or ord(c) == 127 for c in relative) and
            all(p not in ('', '.', '..') and not p.endswith((' ', '.')) for p in relative.split('/')),
            'stage_path', 'Stage path is outside the exact D-only ordinary namespace')
    windows = PureWindowsPath(relative)
    require(not windows.is_absolute() and not windows.drive and not any(
        re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in windows.parts),
        'stage_path', 'A Windows device/absolute path cannot be an evidence filename')
    return value['stageMapping'][stage] + '/' + relative


def resource_requirements(value, solver_active, solver_writable_bytes=0, solver_writable_limit=None):
    validate_descriptor(value)
    require(type(solver_active) is bool and type(solver_writable_bytes) is int and
            0 <= solver_writable_bytes <= SOLVER_UPPER_CAP, 'resource_state', 'Solver writable observation is invalid')
    if solver_active:
        require(type(solver_writable_limit) is int and 0 < solver_writable_limit <= SOLVER_UPPER_CAP and
                solver_writable_bytes <= solver_writable_limit, 'resource_state', 'Exact task solver allowance required')
    else:
        require(solver_writable_limit is None or type(solver_writable_limit) is int, 'resource_state', 'Wrong inactive resource allowance')
    remaining = solver_writable_limit - solver_writable_bytes if solver_active else 0
    return {'C': C_MIN, 'D': D_MIN,
            'F': F_MIN + F_POINTER_CAP + DOCKER_METADATA_RESERVE + F_STOP_BUFFER + remaining,
            'solverRemainingFReservationBytes': remaining, 'sharedPrivateRamBytes': PRIVATE_RAM_CAP,
            'headroomCreditForVhdInternalSlack': 0,
            'scope': 'Conservative Windows volume-free gate; no assumption of unproven VHD preallocation credit'}


def assess_resources(value, free, solver_active, solver_writable_bytes=0, initial=False, solver_writable_limit=None):
    bounds = resource_requirements(value, solver_active, solver_writable_bytes, solver_writable_limit)
    require(all(type(free.get(x)) is int and free[x] >= 0 for x in ('C', 'D', 'F')),
            'volume_observation', 'Actual C/D/F free-byte observations required')
    need_d = D_MIN + STORE_CAP if initial else D_MIN
    deficits = {'C': max(0, bounds['C'] - free['C']), 'D': max(0, need_d - free['D']),
                'F': max(0, bounds['F'] - free['F'])}
    return {'protocol': PROTOCOL, 'admitted': not any(deficits.values()), 'deficitBytes': deficits,
            'requirements': {**bounds, 'D': need_d}, 'initialStoreReservation': initial,
            'solverActive': solver_active, 'actualPrivateTmpfsProofRequired': True}


def ordinary(path, boundary):
    p, b = Path(os.path.abspath(path)), Path(os.path.abspath(boundary))
    require(p == b or b in p.parents, 'containment', 'Native evidence path escaped its exact owner')
    while True:
        z = p.lstat()
        require(stat.S_ISDIR(z.st_mode) and not getattr(z, 'st_file_attributes', 0) & 0x400,
                'reparse', 'Evidence ancestor is not an ordinary directory')
        if p == b: break
        p = p.parent


class NativeStorageLease:
    """Fresh actual share-deny lease; no stale takeover, unlink or PID claims."""
    def __init__(self, root, nonce, fixture_only=False):
        self.root, self.nonce, self.fixture_only = Path(root), nonce, fixture_only
        self.path, self.stream, self.lock = self.root / 'leases/storage.lock', None, threading.RLock()
        self.failed = False

    def __enter__(self):
        require(os.name == 'nt' and re.fullmatch('[0-9a-f]{32}', self.nonce), 'native_owner', 'Actual Windows/fresh nonce required')
        boundary = REPO / '.scratch/skb-ten-D-storage-controls' if self.fixture_only else Path('D:/')
        require(self.root.name == self.nonce and (self.fixture_only or self.root.parent == Path(D_PARENT)),
                'native_owner', 'Lease is outside its exact native owned root')
        ordinary(self.path.parent, boundary)
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                  wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        api.CreateFileW.restype = wintypes.HANDLE
        h = api.CreateFileW(str(self.path), 0xC0000000, 0, None, 1, 0x00200000, None)
        require(h != ctypes.c_void_p(-1).value, 'lease_collision', 'Fresh native lease is held or already exists')
        import msvcrt
        try: fd = msvcrt.open_osfhandle(h, os.O_RDWR | os.O_BINARY)
        except BaseException:
            api.CloseHandle.argtypes = [wintypes.HANDLE]; api.CloseHandle(h); raise
        try: self.stream = os.fdopen(fd, 'r+b', buffering=0)
        except BaseException: os.close(fd); raise
        try: self._write(True)
        except BaseException: self.stream.close(); self.stream = None; self.failed = True; raise
        return self

    def _write(self, held):
        raw = canonical({'protocol': PROTOCOL + '-native-lease', 'nonce': self.nonce,
                         'pid': os.getpid(), 'root': str(self.root), 'held': held, 'fixtureOnly': self.fixture_only})
        self.stream.seek(0); require(self.stream.write(raw) == len(raw), 'lease_write', 'Native lease write was incomplete')
        self.stream.truncate(); self.stream.flush(); os.fsync(self.stream.fileno())

    def raw(self):
        with self.lock:
            require(self.stream is not None and not self.failed, 'native_owner', 'Actual owned lease is not open')
            self.stream.seek(0); return self.stream.read(4097)

    def assert_owned(self):
        with self.lock:
            data = json.loads(self.raw())
            require(data.get('protocol') == PROTOCOL + '-native-lease' and data.get('held') is True and
                    data.get('nonce') == self.nonce and data.get('pid') == os.getpid() and
                    data.get('root') == str(self.root) and data.get('fixtureOnly') is self.fixture_only,
                    'native_owner', 'Actual native lease identity changed')

    def close(self):
        with self.lock:
            if self.stream is not None:
                try: self.assert_owned(); self._write(False)
                except BaseException: self.failed = True; raise
                finally: self.stream.close(); self.stream = None

    def __exit__(self, *_): self.close()


class InstanceLease:
    """Shared candidate/private operation lease at the exact new D run root.

    Native CREATE_NEW/share0 prevents cross-process overlap. The original C
    lease is checked only for existence. No stale takeover is supported. A
    release archives final bytes before native handle-bound deletion; failure
    leaves evidence and never removes a path based on a PID guess.
    """
    LEGACY_C_LEASE = Path('C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6/project-cache/sku-jpg/owned-instance.lock')

    def __init__(self, value, nonce, receipt_directory, fixture_root=None):
        validate_descriptor(value)
        require(isinstance(nonce, str) and re.fullmatch('[0-9a-f]{32}', nonce), 'nonce', 'Fresh operation nonce required')
        self.value, self.nonce = value, nonce
        self.fixture_only = fixture_root is not None
        self.root = Path(fixture_root) if self.fixture_only else Path(value['storePhysical'])
        self.receipt_directory = Path(receipt_directory)
        self.path, self.stream, self.lock = self.root / 'leases/instance.lock', None, threading.RLock()
        self.held, self.closed, self.failed = False, False, False
        self.source_pin, self.closure = fingerprint(__file__), None
        self.actor_pid, self.expected_held = os.getpid(), True

    def _raw(self, held):
        return canonical({'protocol': PROTOCOL + '-instance-lease', 'ownerNonce': self.value['ownerNonce'],
            'nonce': self.nonce, 'pid': self.actor_pid, 'root': str(self.root), 'held': held,
            'fixtureOnly': self.fixture_only, 'sourcePin': self.source_pin})

    def acquire(self):
        with self.lock:
            require(os.name == 'nt' and self.stream is None and not self.closed and not self.failed,
                    'instance_lease', 'Fresh actual native acquisition required')
            boundary = REPO / '.scratch/skb-ten-D-storage-controls' if self.fixture_only else Path('D:/')
            if self.fixture_only:
                require(re.fullmatch('[0-9a-f]{32}', self.root.name), 'fixture_scope', 'Wrong owned F fixture')
            else:
                require(self.root == Path(self.value['storePhysical']) and not os.path.lexists(self.LEGACY_C_LEASE),
                        'legacy_or_foreign_instance', 'Old C lease exists or new D owner differs; no overwrite')
            ordinary(self.path.parent, boundary); ordinary(self.receipt_directory, self.root)
            api = ctypes.WinDLL('kernel32', use_last_error=True)
            api.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
            api.CreateFileW.restype = wintypes.HANDLE
            h = api.CreateFileW(str(self.path), 0xC0010000, 0, None, 1, 0x00200000, None)
            require(h != ctypes.c_void_p(-1).value, 'lease_collision', 'Foreign/held/stale instance lease exists')
            import msvcrt
            try: fd = msvcrt.open_osfhandle(h, os.O_RDWR | os.O_BINARY)
            except BaseException:
                api.CloseHandle.argtypes = [wintypes.HANDLE]; api.CloseHandle(h); raise
            try: self.stream = os.fdopen(fd, 'r+b', buffering=0)
            except BaseException: os.close(fd); raise
            try: self._write(True); self.held = True
            except BaseException:
                self.failed = True; self.stream.close(); self.stream = None; raise
            return self

    def _write(self, held):
        raw = self._raw(held)
        self.stream.seek(0); require(self.stream.write(raw) == len(raw), 'lease_write', 'Lease bytes were not completely written')
        self.stream.truncate(); self.stream.flush(); os.fsync(self.stream.fileno())
        return raw

    def assert_owned(self):
        with self.lock:
            require(self.stream is not None and self.held and not self.failed, 'instance_lease', 'Instance lease is not actually held')
            self.stream.seek(0)
            require(self.stream.read(4097) == self._raw(self.expected_held) and fingerprint(__file__) == self.source_pin,
                    'instance_lease_changed', 'Instance ownership or executable source changed')

    def _archive(self, name, raw):
        ordinary(self.receipt_directory, self.root)
        p = self.receipt_directory / name
        require(shutil.disk_usage(self.root.anchor).free >= (0 if self.fixture_only else D_MIN) + allocation(len(raw)),
                'volume_reserve', 'Instance closure cannot preserve its native volume reserve')
        with p.open('xb') as f:
            require(f.write(raw) == len(raw), 'short_write', 'Closure archive was incomplete')
            f.flush(); os.fsync(f.fileno())
        pin = fingerprint(p)
        require(pin['sha256'] == hashlib.sha256(raw).hexdigest(), 'write_readback', 'Closure bytes changed after fsync')
        return pin

    def release(self):
        with self.lock:
            self.assert_owned()
            if self.actor_pid != os.getpid(): native_actor_absent(self.actor_pid)
            try:
                raw = self._write(False)
                raw_pin = self._archive('instance-lease-closed-bytes.json', raw)
                import msvcrt
                api = ctypes.WinDLL('kernel32', use_last_error=True)
                class Disposition(ctypes.Structure): _fields_ = [('DeleteFile', wintypes.BOOL)]
                flag = Disposition(True)
                api.SetFileInformationByHandle.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
                api.SetFileInformationByHandle.restype = wintypes.BOOL
                require(api.SetFileInformationByHandle(msvcrt.get_osfhandle(self.stream.fileno()), 4,
                                                      ctypes.byref(flag), ctypes.sizeof(flag)),
                        'native_delete', 'Exact owned native handle deletion was rejected; retain the lease')
                self.stream.close(); self.stream = None; self.held = False; self.closed = True
                require(not os.path.lexists(self.path), 'native_delete', 'Exact owned instance path remained after handle close')
                self.closure = {'protocol': PROTOCOL + '-instance-closure', 'ownerNonce': self.value['ownerNonce'],
                    'nonce': self.nonce, 'pid': self.actor_pid, 'releaseActorPid': os.getpid(), 'leasePath': str(self.path), 'finalLeaseBytesPin': raw_pin,
                    'nativeDeleteByOwnedHandleReturned': True, 'nativeHandleClosed': True, 'leasePathAbsent': True,
                    'fixtureOnly': self.fixture_only, 'actorAbsenceCertified': self.actor_pid != os.getpid(), 'paidReady': False}
                return self._archive('instance-lease-closure.json', canonical(self.closure))
            except BaseException:
                self.failed = True
                raise

    def retain_after_failure(self):
        with self.lock:
            self.failed = True
            if self.stream is not None: self.stream.close(); self.stream = None
            self.held = False  # only handle state; path and its original held bytes remain


def validate_instance_closure(closure_pin, value, nonce, actor_pid, receipt_directory):
    """Parse the closed native handle's exact archived owner/source bytes."""
    validate_descriptor(value)
    box = Path(receipt_directory)
    root = Path(value['storePhysical'])
    ordinary(box, root)
    require(type(actor_pid) is int and actor_pid > 0 and re.fullmatch('[0-9a-f]{32}', nonce),
            'closure_owner', 'Actual operation PID/nonce required')
    require(Path(closure_pin['path']) == box / 'instance-lease-closure.json' and fingerprint(closure_pin['path']) == closure_pin,
            'closure_path', 'Closure Pin escaped its owned operation')
    closure = json.loads(Path(closure_pin['path']).read_bytes())
    raw_pin = closure.get('finalLeaseBytesPin')
    require(isinstance(raw_pin, dict) and Path(raw_pin['path']) == box / 'instance-lease-closed-bytes.json'
            and fingerprint(raw_pin['path']) == raw_pin, 'closure_bytes', 'Actual archived lease bytes differ')
    require(closure.get('protocol') == PROTOCOL + '-instance-closure' and closure.get('ownerNonce') == value['ownerNonce']
            and closure.get('nonce') == nonce and closure.get('pid') == actor_pid and closure.get('releaseActorPid') == actor_pid
            and Path(closure.get('leasePath', '')) == root / 'leases/instance.lock'
            and closure.get('nativeDeleteByOwnedHandleReturned') is True and closure.get('nativeHandleClosed') is True
            and closure.get('leasePathAbsent') is True and closure.get('fixtureOnly') is False,
            'closure_owner', 'Native closure owner/PID/nonce/root/handle differs')
    expected = {'protocol': PROTOCOL + '-instance-lease', 'ownerNonce': value['ownerNonce'], 'nonce': nonce,
                'pid': actor_pid, 'root': str(root), 'held': False, 'fixtureOnly': False, 'sourcePin': fingerprint(__file__)}
    require(Path(raw_pin['path']).read_bytes() == canonical(expected),
            'closure_bytes', 'Closed lease does not contain the exact expected source-bound owner')
    return closure


def native_actor_absent(pid):
    """Exact native PID absence; access denied, PID reuse or a live PID refuses."""
    require(os.name == 'nt' and type(pid) is int and pid > 0, 'native_actor', 'Positive actual native PID required')
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.OpenProcess.argtypes=[wintypes.DWORD,wintypes.BOOL,wintypes.DWORD];api.OpenProcess.restype=wintypes.HANDLE
    ctypes.set_last_error(0);handle=api.OpenProcess(0x1000,False,pid)
    if handle:
        api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle(handle)
        raise StorageFault('actor_not_absent','Actual PID exists; never stop or adopt it by guess')
    require(ctypes.get_last_error()==87,'actor_absence_unknown','Native PID absence is not unambiguous')
    return {'pid':pid,'actualNativeOpenProcessAbsent':True,'win32Error':87}


def adopt_exited_instance(value, nonce, pid, receipt_directory):
    """Explicit timeout recovery only; pin old bytes before owned-handle delete.

    This is not a normal acquire or stale takeover. It requires exact native PID
    absence, same fixed source/owner/nonce and an actual share0 existing handle.
    Caller must close its exact Docker resources before release() is permitted.
    """
    native_actor_absent(pid)
    lease=InstanceLease(value,nonce,receipt_directory)
    ordinary(lease.path.parent,Path('D:/'));ordinary(lease.receipt_directory,lease.root)
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[wintypes.LPCWSTR,wintypes.DWORD,wintypes.DWORD,ctypes.c_void_p,wintypes.DWORD,wintypes.DWORD,wintypes.HANDLE]
    api.CreateFileW.restype=wintypes.HANDLE
    h=api.CreateFileW(str(lease.path),0xC0010000,0,None,3,0x00200000,None)
    require(h != ctypes.c_void_p(-1).value,'lease_collision','Exact old instance lease missing, live or substituted')
    import msvcrt
    try:fd=msvcrt.open_osfhandle(h,os.O_RDWR|os.O_BINARY);lease.stream=os.fdopen(fd,'r+b',buffering=0)
    except BaseException:
        api.CloseHandle.argtypes=[wintypes.HANDLE];api.CloseHandle(h);raise
    try:
        raw=lease.stream.read(4097);data=json.loads(raw)
        lease.actor_pid=pid;lease.expected_held=data.get('held')
        require(type(lease.expected_held) is bool and raw==lease._raw(lease.expected_held),
                'instance_recovery_identity','Exact original actor/nonce/source lease bytes differ')
        native_actor_absent(pid);lease.held=True
        lease._archive('recovery-original-instance-bytes.json',raw)
        return lease
    except BaseException:
        lease.stream.close();lease.stream=None;lease.failed=True;raise


def cluster_size(volume):
    require(os.name == 'nt', 'native_volume', 'Actual Windows allocation unit required')
    api = ctypes.WinDLL('kernel32', use_last_error=True)
    api.GetDiskFreeSpaceW.argtypes = [wintypes.LPCWSTR, ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD),
                                   ctypes.POINTER(wintypes.DWORD), ctypes.POINTER(wintypes.DWORD)]
    api.GetDiskFreeSpaceW.restype = wintypes.BOOL
    a, b, c, d = (wintypes.DWORD() for _ in range(4))
    root = Path(volume).anchor
    require(api.GetDiskFreeSpaceW(root, ctypes.byref(a), ctypes.byref(b), ctypes.byref(c), ctypes.byref(d)),
            'native_volume', 'Actual allocation-unit query failed')
    unit = a.value * b.value
    require(4096 <= unit <= 65536 and unit & (unit - 1) == 0, 'native_volume', 'Unsupported actual allocation unit')
    return unit


class OwnedWriteBudget:
    """Native-only bounded new writes; all writers use the same instance/lock.

    This does not own a paid lock or replace journal/cash rules. A partial or
    failed fsync poisons this writer and retains evidence; no automatic resume.
    """
    def __init__(self, root, cap, reserve_floor, volume_root, native_lease, fixture_only=False):
        self.root, self.volume_root = Path(root), Path(volume_root)
        require(self.root.is_absolute() and self.volume_root.is_absolute() and
                self.root.anchor.lower() == self.volume_root.anchor.lower(),
                'volume_mismatch', 'Actual write volume and measured reserve volume must be identical')
        self.cap, self.floor, self.fixture_only = cap, reserve_floor, fixture_only
        self.lock, self.poisoned, self.claimed = threading.RLock(), False, set()
        require(isinstance(native_lease, NativeStorageLease) and native_lease.root == self.root and
                native_lease.fixture_only is fixture_only, 'native_owner', 'An actual module-owned exclusive lease is required')
        self.lease = native_lease; self.lease.assert_owned(); self.unit = cluster_size(volume_root)
        if fixture_only:
            parent = REPO / '.scratch/skb-ten-D-storage-controls'
            ordinary(self.root, parent)
            require(re.fullmatch('[0-9a-f]{32}', self.root.name), 'fixture_scope', 'Fixture is not this module fresh F control root')
        else:
            require(os.name == 'nt' and re.fullmatch('[0-9a-f]{32}', self.root.name) and
                    self.root.parent == Path(D_PARENT), 'D_owner_scope', 'Only the fixed fresh D owner is supported')
            ordinary(self.root, Path('D:/'))
        require(0 < cap <= STORE_CAP and reserve_floor >= (0 if fixture_only else D_MIN),
                'write_budget', 'Evidence write cap/reserve exceeds its independent profile')
        self.charged = 0
        self.directories = set()
        for parent, dirs, files in os.walk(self.root, followlinks=False):
            ordinary(parent, self.root); self.charged += self.unit
            self.directories.add(Path(parent).relative_to(self.root).as_posix())
            for name in dirs: ordinary(Path(parent) / name, self.root)
            for name in files:
                require(Path(parent) / name == self.lease.path, 'not_fresh', 'Writer refuses existing unknown evidence')
                self.charged += self.unit
        require(self.charged <= cap, 'owned_cap', 'Fresh native directory/lease allocation already exceeds its cap')

    def _path(self, relative):
        require(isinstance(relative, str) and relative and Path(relative).as_posix() == relative and
                not any(p in ('', '.', '..') or p.endswith((' ', '.')) or
                        re.fullmatch(r'(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?', p, re.I) for p in relative.split('/')) and
                not any(ord(c) < 32 or ord(c) == 127 for c in relative) and ':' not in relative and '\\' not in relative,
                'write_path', 'Native write path is not a contained ordinary relative path')
        p = self.root / relative; ordinary(p.parent, self.root)
        require(not os.path.lexists(p), 'existing_evidence', 'Fresh write refuses an existing or partial path')
        return p

    def write_fresh(self, relative, raw):
        require(isinstance(raw, bytes), 'write_type', 'Only exact byte payloads are supported')
        with self.lock:
            self.lease.assert_owned()
            require(not self.poisoned and relative not in self.claimed, 'poisoned_writer', 'Failed/ambiguous writer cannot automatically resume')
            p = self._path(relative); charge = max(self.unit, (len(raw) + self.unit - 1) // self.unit * self.unit)
            require(self.charged + charge <= self.cap, 'owned_cap', 'Owned allocated reservation would exceed its cap')
            require(shutil.disk_usage(self.volume_root).free >= self.floor + charge,
                    'volume_reserve', 'Actual volume reserve is below the next write envelope')
            self.charged += charge; self.claimed.add(relative)
            try:
                with p.open('xb') as f:
                    for start in range(0, len(raw), 65536):
                        chunk = raw[start:start + 65536]; self.lease.assert_owned()
                        require(shutil.disk_usage(self.volume_root).free >= self.floor + len(chunk),
                                'volume_reserve', 'Reserve was lost during a bounded chunk')
                        require(f.write(chunk) == len(chunk), 'short_write', 'Evidence write was incomplete')
                    f.flush(); os.fsync(f.fileno())
                result = fingerprint(p)
                require(result['bytes'] == len(raw) and result['sha256'] == hashlib.sha256(raw).hexdigest(),
                        'write_readback', 'Actual fsynced evidence readback differs')
                return {**result, 'fsyncReturned': True, 'allocatedCharge': charge, 'fixtureOnly': self.fixture_only}
            except BaseException:
                self.poisoned = True
                raise

    def audit(self):
        with self.lock:
            self.lease.assert_owned(); actual, paths, directories = 0, [], set()
            for parent, dirs, files in os.walk(self.root, followlinks=False):
                ordinary(parent, self.root); actual += self.unit
                directories.add(Path(parent).relative_to(self.root).as_posix())
                for name in dirs: ordinary(Path(parent) / name, self.root)
                for name in files:
                    p = Path(parent) / name; z = p.lstat()
                    if p == self.lease.path:
                        require(z.st_size <= self.unit, 'native_owner', 'Lease exceeded its own allocated cluster')
                        self.lease.assert_owned(); actual += self.unit; continue
                    require(stat.S_ISREG(z.st_mode) and not getattr(z, 'st_file_attributes', 0) & 0x400,
                            'reparse', 'Owned evidence tree includes a nonregular file')
                    require(z.st_nlink == 1, 'hardlink', 'Owned evidence cannot alias another native file')
                    actual += max(self.unit, (z.st_size + self.unit - 1) // self.unit * self.unit)
                    paths.append(p.relative_to(self.root).as_posix())
            require(set(paths) == self.claimed and directories == self.directories and actual <= self.charged <= self.cap,
                    'untracked_write', 'Unknown owned bytes or a failed allocation ledger were observed')
            return {'protocol': PROTOCOL, 'allocatedUpperBound': actual, 'reservationCharged': self.charged,
                    'poisoned': self.poisoned, 'files': len(paths), 'fixtureOnly': self.fixture_only,
                    'paidReady': False, 'actualNativeExclusiveLeaseAsserted': True,
                    'actualAllocationUnit': self.unit, 'leaseClosureAndActorAbsenceCertified': False}


def observe_owned_store(value):
    """Read-only ordinary tree envelope for direct SQLite/Bun/journal writers.

    Their own producer limits/leases remain mandatory. This observer cannot
    provide a kernel quota or certify that all asynchronous writes were fsynced.
    """
    validate_descriptor(value); root = Path(value['storePhysical']); ordinary(root, Path('D:/'))
    unit = cluster_size(root); total, files, dirs = 0, 0, 0
    for parent, names, entries in os.walk(root, followlinks=False):
        ordinary(parent, root); total += unit; dirs += 1
        for name in names: ordinary(Path(parent) / name, root)
        for name in entries:
            p = Path(parent) / name; z = p.lstat()
            require(stat.S_ISREG(z.st_mode) and z.st_nlink == 1 and not getattr(z, 'st_file_attributes', 0) & 0x400,
                    'untrusted_store_entry', 'Direct evidence writer created a nonregular/reparse/hardlinked file')
            total += max(unit, (z.st_size + unit - 1) // unit * unit); files += 1
    free = {k: shutil.disk_usage(k + ':/').free for k in ('C', 'D', 'F')}
    require(total <= STORE_CAP and free['D'] >= D_MIN, 'owned_store_boundary', 'Current D envelope/reserve exceeded its declared boundary')
    return {'protocol': PROTOCOL, 'ownerNonce': value['ownerNonce'], 'storePhysical': value['storePhysical'],
            'allocatedEnvelopeBytes': total, 'allocationUnit': unit, 'files': files, 'directories': dirs,
            'volumeFreeBytes': free, 'capBytes': STORE_CAP, 'kernelQuotaCertified': False,
            'allProducerFsyncsCertified': False, 'producerAdmissionAndStopDrainRequired': True, 'paidReady': False}


def main():
    p = argparse.ArgumentParser(); p.add_argument('--nonce', required=True); a = p.parse_args()
    print(json.dumps(descriptor(a.nonce), ensure_ascii=False))


if __name__ == '__main__': main()
