"""Public cache acquisition protocol v1; no compiler, candidate, or model calls.

An exclusive Windows file lease serializes this acquisition protocol. The root
orchestrator must also refrain from starting older write stages, which do not
implement this lease. Local process/container probes reject observed conflicts.
Only the fixed official public Azure GET endpoint is reachable by this worker.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import socket
import ssl
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request
import uuid

PROTOCOL = "public-cache-acquisition-v1"
RUN_ID = "01a119ed-fdf7-7c32-b323-de9bab1290b6"
ROOT = "E:/objrun-experiment-cache/"+RUN_ID+"/minif2f-v415"
CORE_SHA = "8c8b77f6bf64ec6b07f82419dab8d0d5ee24bad3157cd51cfe2a942b8a28cd98"
LOCK_SHA = "ee033a2d51ef5f7dc51b573285df3c2d78689fc9edcaaf8781420525c1d8d857"
BOOTSTRAP_SHA = "cf84863b8c93839a35ca7989cc7c83fad94d09444269d563a14b28324bc76a77"
MANIFEST_SHA = "bc7f8caa504054de03a3ec6a945de4a4ab7bdb12918029763c46bbb817d6dda9"
MANIFEST_COUNT = 5826
AZURE = "https://lakecache.blob.core.windows.net/mathlib4/f/"
UNIT = 4096
CAP = 14*1024**3
E_RESERVE, F_RESERVE = 3*1024**3, 1024**3
MAX_BLOB = 64*1024**2
META_PER_BLOB = 64*1024
AUDIT_BUDGET = 16*1024**2
BLOCK = 1024**2
WALL_SECONDS = 3*3600
MAX_RECEIPT_LINE = 2048
LEASE_NAME = "public-cache-acquisition.lock"
BATTERIES_SOURCE_LINK = "mathlib4/.lake/packages/batteries/docs/README.md"
BATTERIES_SOURCE_TARGET = "mathlib4/.lake/packages/batteries/README.md"
BATTERIES_TARGET_SHA = "757c07bff79755bcc7b9e86ead61627ead6ec64a5fe8d94073f90121a485dc51"
BATTERIES_TARGET_BYTES = 3302
BATTERIES_LX_TAG = 0xA000001D
# Read-only FSCTL_GET_REPARSE_POINT of the exact official link on this E
# volume yielded this LX version-2 payload. Every other tag/target is rejected.
BATTERIES_REPARSE_BYTES = bytes.fromhex("1d0000a010000000020000002e2e2f524541444d452e6d64")


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def rounded(size):
    return ((size+UNIT-1)//UNIT)*UNIT


def durable_json(path, data):
    # These small known audit paths are covered by the stage audit reservation.
    path = Path(path)
    part = path.with_name(path.name+".new")
    if part.exists():
        raise RuntimeError("unknown audit partial; inspect before rerunning")
    with part.open("xb") as stream:
        stream.write((json.dumps(data, ensure_ascii=False, indent=2)+"\n").encode())
        stream.flush()
        os.fsync(stream.fileno())
    part.replace(path)


def assert_regular(path):
    item = Path(path).lstat()
    if not stat.S_ISREG(item.st_mode) or getattr(item, "st_file_attributes", 0) & 0x400:
        raise RuntimeError("unreviewed nonregular/reparse file: "+str(path))


def read_reparse_bytes(path):
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    create = api.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    handle = create(str(path), 0, 7, None, 3, 0x00200000, None)  # OPEN_REPARSE_POINT, no write access.
    if handle == ctypes.c_void_p(-1).value:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        ioctl = api.DeviceIoControl
        ioctl.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD,
                          ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        ioctl.restype = wintypes.BOOL
        buffer, written = ctypes.create_string_buffer(16384), wintypes.DWORD()
        if not ioctl(handle, 0x000900A8, None, 0, buffer, len(buffer), ctypes.byref(written), None):
            raise ctypes.WinError(ctypes.get_last_error())
        return buffer.raw[:written.value]
    finally:
        api.CloseHandle.argtypes = [wintypes.HANDLE]
        api.CloseHandle(handle)


def verify_fixed_source_link(root, path):
    relative = path.relative_to(root).as_posix()
    info = path.lstat()
    if (relative != BATTERIES_SOURCE_LINK or getattr(info, "st_reparse_tag", None) != BATTERIES_LX_TAG
            or read_reparse_bytes(path) != BATTERIES_REPARSE_BYTES):
        raise RuntimeError("owned reparse is not the exact fixed official batteries source link")
    target = root/BATTERIES_SOURCE_TARGET
    assert_regular(target)
    if target.stat().st_size != BATTERIES_TARGET_BYTES or sha(target) != BATTERIES_TARGET_SHA:
        raise RuntimeError("fixed official batteries source link target bytes differ")
    return {"relative_path": relative, "reparse_tag": BATTERIES_LX_TAG,
            "exact_link_target": "../README.md", "target_sha256": BATTERIES_TARGET_SHA,
            "target_bytes": BATTERIES_TARGET_BYTES, "no_follow_accounting": True}


def exact_root(path):
    path = Path(path)
    if os.name != "nt" or str(path.absolute()).replace("\\", "/").casefold() != ROOT.casefold():
        raise RuntimeError("this acquisition only permits the exact reviewed Windows E root")
    for ancestor in [path, *path.parents]:
        item = ancestor.lstat()
        if getattr(item, "st_file_attributes", 0) & 0x400:
            raise RuntimeError("owned root has a reparse ancestor")
    marker = path/"owned-root.json"
    assert_regular(marker)
    if json.loads(marker.read_bytes()) != {"run_id": RUN_ID, "host_root": ROOT,
            "purpose": "pinned public miniF2F dependency restoration"}:
        raise RuntimeError("owned root marker differs")
    return path


def allocation_unit():
    api = ctypes.WinDLL("kernel32", use_last_error=True)
    sectors, block, free, total = (wintypes.DWORD() for _ in range(4))
    if not api.GetDiskFreeSpaceW("E:/", ctypes.byref(sectors), ctypes.byref(block), ctypes.byref(free), ctypes.byref(total)):
        raise ctypes.WinError(ctypes.get_last_error())
    if sectors.value*block.value != UNIT:
        raise RuntimeError("E allocation unit differs from the frozen 4096-byte envelope")


def volume_reserves(addition=0):
    values = {"e_free_bytes": shutil.disk_usage("E:/").free, "f_free_bytes": shutil.disk_usage("F:/").free}
    if values["e_free_bytes"]-addition < E_RESERVE or values["f_free_bytes"] < F_RESERVE:
        raise RuntimeError("actual E/F reserve would cross 3 GiB/1 GiB")
    return values


def full_scan(root):
    """Same envelope formula as the executed core, also rejecting reparses.

    No per-blob caller invokes this function. The baseline metadata map permits
    a final check that pre-existing files outside declared audit paths stayed
    unchanged. Cryptographic frozen inputs are independently checked.
    """
    total, files, links = 0, {}, []
    for home, dirs, names in os.walk(root, followlinks=False):
        home = Path(home)
        for directory in [home, *(home/name for name in dirs)]:
            item = directory.lstat()
            if not stat.S_ISDIR(item.st_mode) or getattr(item, "st_file_attributes", 0) & 0x400:
                raise RuntimeError("unreviewed directory reparse in owned root")
        total += UNIT*(len(dirs)+1)
        for name in names:
            path = home/name
            item = path.lstat()
            if getattr(item, "st_file_attributes", 0) & 0x400:
                links.append(verify_fixed_source_link(root, path))
            else:
                assert_regular(path)
            total += rounded(item.st_size)
            files[path.relative_to(root).as_posix()] = (item.st_size, item.st_mtime_ns)
    if total > CAP:
        raise RuntimeError("full owned allocation envelope exceeds 14 GiB")
    volume_reserves()
    fingerprint = hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {"allocated_envelope_bytes": total, "files": files, "metadata_fingerprint_sha256": fingerprint,
            "fixed_source_links_verified": links}


def inputs(root, public, core_path):
    if sha(core_path) != CORE_SHA:
        raise RuntimeError("executed restoration core bytes changed")
    spec = importlib.util.spec_from_file_location("mf2f_executed_core", core_path)
    core = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(core)
    core.public_lock(public, LOCK_SHA)
    boot_path, manifest_path = root/"audit/bootstrap.json", root/"audit/module-cache-manifest.jsonl"
    for path in [boot_path, manifest_path]:
        assert_regular(path)
    if sha(boot_path) != BOOTSTRAP_SHA or sha(manifest_path) != MANIFEST_SHA:
        raise RuntimeError("completed Bootstrap/official cache manifest bytes changed")
    boot = json.loads(boot_path.read_bytes())
    if (boot["pins"] != core.PINS or boot["public_lock_sha256"] != LOCK_SHA
            or boot["module_cache_count"] != MANIFEST_COUNT or boot["module_cache_manifest_sha256"] != MANIFEST_SHA
            or boot["candidate_run"] or boot["image_id"] != core.IMAGE):
        raise RuntimeError("completed official Bootstrap provenance differs")
    rows = [json.loads(line) for line in manifest_path.read_text().splitlines()]
    if len(rows) != MANIFEST_COUNT or len({r["ltar"] for r in rows}) != MANIFEST_COUNT:
        raise RuntimeError("official cache key count/uniqueness differs")
    for row in rows:
        module = PurePosixPath(row["module"])
        if (set(row) != {"module", "ltar"} or not re.fullmatch(r"[0-9a-f]{16}\.ltar", row["ltar"])
                or module.is_absolute() or ".." in module.parts or module.suffix != ".lean"):
            raise RuntimeError("official public module key is malformed")
    return rows


class Lease:
    """A real Windows share-deny file handle, not a claimed Git/filesystem shim."""
    def __init__(self, path):
        self.path, self.stream, self.id = Path(path), None, str(uuid.uuid4())

    def acquire(self):
        import msvcrt
        api = ctypes.WinDLL("kernel32", use_last_error=True)
        create = api.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                           wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        ctypes.set_last_error(0)
        handle = create(str(self.path), 0x80000000|0x40000000, 0, None, 4, 0x80|0x00200000, None)
        existed = ctypes.get_last_error() == 183
        if handle == ctypes.c_void_p(-1).value:
            raise RuntimeError("exclusive acquisition lease unavailable: "+str(ctypes.WinError(ctypes.get_last_error())))
        attributes = (wintypes.DWORD*2)()
        get_info = api.GetFileInformationByHandleEx
        get_info.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        get_info.restype = wintypes.BOOL
        if not get_info(handle, 9, ctypes.byref(attributes), ctypes.sizeof(attributes)) or attributes[0] & 0x400:
            api.CloseHandle.argtypes = [wintypes.HANDLE]
            api.CloseHandle(handle)
            raise RuntimeError("lease handle is unknown or a reparse point")
        fd = msvcrt.open_osfhandle(handle, os.O_RDWR|os.O_BINARY)
        self.stream = os.fdopen(fd, "r+b", buffering=0)
        old_bytes = self.stream.read(16385)
        if len(old_bytes) > 16384:
            self.close()
            raise RuntimeError("unknown oversized prior lease record")
        if existed and not old_bytes:
            self.close()
            raise RuntimeError("pre-existing empty lease record requires review")
        if old_bytes:
            try:
                old = json.loads(old_bytes)
            except Exception:
                self.close()
                raise RuntimeError("prior lease record is not valid JSON")
            if old.get("protocol") != PROTOCOL or old.get("run_id") != RUN_ID or old.get("held") is not False:
                self.close()
                raise RuntimeError("prior lease marker is unknown/stale; inspect without automatic takeover")
        self.write({"held": True, "acquired_at_utc": stamp(), "pid": os.getpid()})

    def write(self, values):
        value = {"protocol": PROTOCOL, "run_id": RUN_ID, "lease_id": self.id, **values}
        encoded = (json.dumps(value, sort_keys=True)+"\n").encode()
        if len(encoded) > 16384:
            raise RuntimeError("lease record exceeds its fixed budget")
        self.stream.seek(0)
        self.stream.write(encoded)
        self.stream.truncate()
        self.stream.flush()
        os.fsync(self.stream.fileno())

    def close(self):
        if self.stream is not None:
            self.stream.close()
            self.stream = None


def normalize_mount(value):
    value = value.replace("\\", "/").rstrip("/").casefold()
    for prefix in ["/run/desktop/mnt/host/", "/host_mnt/"]:
        if value.startswith(prefix) and len(value) > len(prefix)+1:
            value = value[len(prefix)]+":"+value[len(prefix)+1:]
    if value.startswith("//?/"):
        value = value[4:]
    return value


def writer_probe():
    # Raw command lines remain in this local subprocess memory and are never
    # logged/transmitted. The JSON contains only conflicting IDs/stage names.
    command = r'''$ErrorActionPreference='Stop'; $all=@(Get-CimInstance Win32_Process); $excluded=@(__PID__); $cur=__PID__; while($cur){$p=$all|Where-Object ProcessId -eq $cur; if(-not $p){break}; $cur=[int]$p.ParentProcessId; $excluded+=$cur}; $hits=@(); foreach($p in $all){if($excluded -contains [int]$p.ProcessId){continue}; $c=[string]$p.CommandLine; if($c -match '(?i)minif2f_(restore|runtime|public_cache)\.(py|ps1|sh)["''\s]+(?:[\s\S]*?-Stage["''\s]+)?(download|bootstrap|cache-download|unpack-probe|workspace|worker|Acquire|CacheDownload|UnpackAndProbe|RegradeCandidates|CleanOwned)(?:["''\s]|$)'){$hits+=[pscustomobject]@{pid=[int]$p.ProcessId;name=$p.Name;stage=$Matches[3]}}}; [pscustomobject]@{host_conflicts=$hits}|ConvertTo-Json -Compress -Depth 5'''.replace("__PID__", str(os.getpid()))
    result = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command], capture_output=True, timeout=10)
    if result.returncode:
        raise RuntimeError("local write-stage process probe failed")
    hosts = json.loads(result.stdout.decode("utf-8-sig"))["host_conflicts"]
    listed = subprocess.run(["docker", "ps", "--no-trunc", "--format", "{{.ID}}"], capture_output=True, timeout=10)
    if listed.returncode:
        raise RuntimeError("local running-container inventory unavailable")
    ids = listed.stdout.decode().split()
    conflicts = []
    if ids:
        inspected = subprocess.run(["docker", "inspect", *ids], capture_output=True, timeout=10)
        if inspected.returncode:
            raise RuntimeError("local running-container mount probe failed")
        root = normalize_mount(ROOT)
        for container in json.loads(inspected.stdout):
            for mount in container.get("Mounts", []):
                source = normalize_mount(mount.get("Source", ""))
                overlap = source and (source == root or source.startswith(root+"/") or root.startswith(source+"/"))
                if mount.get("RW") and overlap:
                    conflicts.append({"container_id": container["Id"], "source": source, "destination": mount.get("Destination")})
    proof = {"recorded_at_utc": stamp(), "host_conflicts": hosts, "running_container_ids_checked": ids,
             "writable_mount_conflicts": conflicts, "directory_lease_scope": "cooperative acquisition exclusion plus observed local writers; older stages require sole-writer root scheduling"}
    if hosts or conflicts:
        raise RuntimeError("another observed writer overlaps the owned root: "+json.dumps(proof))
    return proof


class Ledger:
    def __init__(self, initial, reserve=volume_reserves):
        self.lock = threading.RLock()
        self.used = initial+AUDIT_BUDGET+META_PER_BLOB
        self.reservations = {}
        self.reserve = reserve
        self.peak = self.used
        self.check()

    def check(self):
        with self.lock:
            future = sum(self.reservations.values())
            forecast = self.used+future
            if forecast > CAP:
                raise RuntimeError("incremental allocation forecast exceeds 14 GiB")
            # Keep the entire inflight reservation, even after a block writes.
            # This deliberately double-counts inflight bytes in free-space
            # forecasting so delayed allocation cannot understate the reserve.
            values = self.reserve(future+AUDIT_BUDGET)
            self.peak = max(self.peak, forecast)
            return values

    def begin(self, name, limit):
        with self.lock:
            if name in self.reservations:
                raise RuntimeError("duplicate inflight object")
            self.reservations[name] = rounded(limit)+META_PER_BLOB
            try:
                self.check()
            except Exception:
                del self.reservations[name]
                raise

    def committed(self, name, size):
        with self.lock:
            self.used += rounded(size)+META_PER_BLOB
            del self.reservations[name]
            self.check()


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise RuntimeError("official cache GET redirect is outside the reviewed endpoint")


class PublicOpenFailure(RuntimeError):
    def __init__(self, attempts):
        self.transport_attempts = attempts
        super().__init__("official public response-open failed: " + json.dumps(attempts))


def open_public_response(opener, request, guard, sleeper=time.sleep):
    """Retry only an idempotent GET's transient failure before a response opens.

    HTTP responses, TLS/redirect errors and every body/integrity failure are
    outside this policy. The same fixed Request is reused; no partial is read,
    replaced, promoted or removed by this function.
    """
    attempts = []
    for index in range(3):
        guard()
        began = time.monotonic()
        try:
            response = opener.open(request, timeout=60)
        except Exception as error:
            reason = error.reason if isinstance(error, urllib.error.URLError) else error
            response_received = isinstance(error, urllib.error.HTTPError)
            retryable = (not response_received and not isinstance(reason, ssl.SSLError)
                and (isinstance(reason, (TimeoutError, socket.timeout))
                    or isinstance(reason, OSError) and
                       (getattr(reason, "winerror", None) in {10053, 10054, 10060}
                        or getattr(reason, "errno", None) in {errno.ETIMEDOUT, errno.ECONNRESET, errno.ECONNABORTED})))
            attempts.append({"attempt": index+1, "response_received": response_received,
                "error_type": type(error).__name__, "reason_type": type(reason).__name__,
                "winerror": getattr(reason, "winerror", None), "errno": getattr(reason, "errno", None),
                "http_status": error.code if response_received else None, "retryable": retryable,
                "seconds": round(time.monotonic()-began, 3)})
            if not retryable or index == 2:
                raise PublicOpenFailure(attempts) from error
            guard()
            sleeper((0.5, 2.0)[index])
        else:
            attempts.append({"attempt": index+1, "response_received": True,
                             "seconds": round(time.monotonic()-began, 3)})
            return response, attempts
    raise AssertionError("bounded response-open loop did not terminate")


def validate_resume(root, rows):
    receipt = root/"audit/cache-downloads.jsonl"
    by_name = {r["ltar"]: r for r in rows}
    old = {}
    if receipt.exists():
        assert_regular(receipt)
        for line in receipt.read_text().splitlines():
            if not line or len(line.encode()) > MAX_RECEIPT_LINE:
                raise RuntimeError("unknown/truncated cache receipt row")
            row = json.loads(line)
            name = row["ltar"]
            if (name in old or name not in by_name or row["module"] != by_name[name]["module"]
                    or row["url"] != AZURE+name or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"])
                    or not 0 < row["bytes"] <= MAX_BLOB):
                raise RuntimeError("prior cache receipt differs from the fixed public key/URL/size")
            path = root/"downloads/mathlib-cache"/name
            assert_regular(path)
            if path.stat().st_size != row["bytes"] or sha(path) != row["sha256"]:
                raise RuntimeError("completed cache bytes no longer match the prior original hash")
            old[name] = row
    directory = root/"downloads/mathlib-cache"
    if directory.exists():
        for path in directory.iterdir():
            assert_regular(path)
            if path.name not in old:
                raise RuntimeError("unknown final/partial cache artifact; inspect before resuming: "+path.name)
    for path in [root/"audit/cache-download-complete.json.new", root/"audit/public-cache-acquisition.json.new"]:
        if path.exists():
            raise RuntimeError("unknown final audit partial; inspect before resuming")
    prior_proof = root/"audit/public-cache-acquisition.json"
    if prior_proof.exists():
        assert_regular(prior_proof)
        prior = json.loads(prior_proof.read_bytes())
        if (prior.get("protocol") != PROTOCOL or prior.get("module_cache_manifest_sha256") != MANIFEST_SHA
                or prior.get("bootstrap_receipt_sha256") != BOOTSTRAP_SHA
                or prior.get("download_receipts_sha256") != sha(receipt)):
            raise RuntimeError("pre-existing acquisition proof is unknown or does not match original receipts")
    return old


def acquire(root, public, core_path, workers):
    root = exact_root(root)
    allocation_unit()
    volume_reserves(AUDIT_BUDGET+16384)
    rows = inputs(root, public, core_path)
    lease = Lease(root/"audit"/LEASE_NAME)
    lease.acquire()
    stop = threading.Event()
    monitor_errors = []
    completed, ledger, initial, final = {}, None, None, None
    began = time.monotonic()
    progress_lock = threading.Lock()
    probe_count = 0
    outcome = "aborted"
    try:
        start_probe = writer_probe()
        old = validate_resume(root, rows)
        if (root/"audit/cache-download-complete.json").exists():
            raise RuntimeError("complete acquisition already exists; use its receipt instead of another download stage")
        initial = full_scan(root)
        ledger = Ledger(initial["allocated_envelope_bytes"])
        directory = root/"downloads/mathlib-cache"
        directory.mkdir(exist_ok=True)
        completed.update(old)
        receipt = root/"audit/cache-downloads.jsonl"
        if not receipt.exists():
            with receipt.open("xb") as stream:
                stream.flush()
                os.fsync(stream.fileno())

        def guard():
            if stop.is_set():
                raise RuntimeError("public acquisition stopped after another failure/conflict")
            if time.monotonic()-began > WALL_SECONDS:
                stop.set()
                raise RuntimeError("public acquisition exceeded its three-hour wall budget")
            ledger.check()

        def monitor():
            nonlocal probe_count
            while not stop.wait(10):
                try:
                    guard()
                    writer_probe()
                    probe_count += 1
                except Exception as error:
                    monitor_errors.append(str(error))
                    stop.set()
                    return

        observer = threading.Thread(target=monitor, name="owned-writer-observer", daemon=True)
        observer.start()

        def get_one(row):
            name, url = row["ltar"], AZURE+row["ltar"]
            guard()
            # Independent openers have no cookies, auth headers, proxy, or
            # mutable URL source. TLS validation uses Python's default context.
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
            request = urllib.request.Request(url, headers={"User-Agent": "TgEngin-public-cache-acquisition-v1", "Accept-Encoding": "identity"}, method="GET")
            opened, transport_attempts = open_public_response(opener, request, guard)
            with opened as response:
                if response.status != 200 or response.geturl() != url:
                    raise RuntimeError("official public cache GET did not return the fixed URL/200")
                guard()
                raw_length = response.headers.get("Content-Length")
                length = int(raw_length) if raw_length is not None else None
                if length is not None and not 0 < length <= MAX_BLOB:
                    raise RuntimeError("official cache response exceeds the 64 MiB bound")
                http = {k.lower(): v for k, v in response.headers.items()
                        if k.lower() in {"etag", "content-md5", "last-modified", "content-length"}}
                if any(len(v) > 256 for v in http.values()):
                    raise RuntimeError("official HTTP metadata exceeds its fixed receipt budget")
                ledger.begin(name, length or MAX_BLOB)
                part = directory/(name+".part")
                digest, written = hashlib.sha256(), 0
                with part.open("xb") as stream:
                    # read1 performs at most one underlying buffered/socket
                    # read. A slow byte stream cannot make read(BLOCK) wait to
                    # fill an entire MiB before the wall/stop/reserve guard.
                    while chunk := response.read1(BLOCK):
                        guard()
                        written += len(chunk)
                        if written > MAX_BLOB or (length is not None and written > length):
                            raise RuntimeError("official cache stream exceeds its declared/bounded size")
                        stream.write(chunk)
                        digest.update(chunk)
                        ledger.check()  # Actual E/F free-space probe after every block, too.
                    stream.flush()
                    os.fsync(stream.fileno())
                if not written or (length is not None and written != length):
                    raise RuntimeError("official cache GET was truncated")
                result = {**row, "url": url, "bytes": written, "sha256": digest.hexdigest(), "http": http,
                          "recorded_at_utc": stamp(), "acquisition_protocol": PROTOCOL, "lease_id": lease.id,
                          "http_status": 200, "hash_assurance": "official public cache key/URL; SHA-256 measured after GET"}
                result["transport_policy"] = "same-key-response-open-transient-only-max3-v1"
                result["transport_attempts"] = transport_attempts
                encoded = (json.dumps(result, separators=(",", ":"))+"\n").encode()
                if len(encoded) > MAX_RECEIPT_LINE:
                    raise RuntimeError("per-blob public receipt exceeds its fixed budget")
                guard()
                with ledger.lock:
                    destination = directory/name
                    if destination.exists():
                        raise RuntimeError("refuse replacing an existing cache object")
                    part.replace(destination)
                    with receipt.open("ab") as stream:
                        stream.write(encoded)
                        stream.flush()
                        os.fsync(stream.fileno())
                    completed[name] = result
                    ledger.committed(name, written)
                with progress_lock:
                    count = len(completed)
                    if count % 200 == 0 or count == MANIFEST_COUNT:
                        print(json.dumps({"public_cache_objects": count, "total": MANIFEST_COUNT,
                            "incremental_forecast_bytes": ledger.used, "elapsed_seconds": round(time.monotonic()-began, 1),
                            "candidate_run": False}), flush=True)

        pending = [row for row in rows if row["ltar"] not in old]
        errors = []
        try:
            with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="public-get") as pool:
                futures = {pool.submit(get_one, row): row["ltar"] for row in pending}
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as error:
                        errors.append({"ltar": futures[future], "error": type(error).__name__+": "+str(error),
                                       "transport_attempts": getattr(error, "transport_attempts", None)})
                        stop.set()
                        for job in futures:
                            job.cancel()
                        break
        finally:
            stop.set()
            observer.join(timeout=35)
            if observer.is_alive():
                raise RuntimeError("writer observer did not terminate; refuse final certification")
        if errors or monitor_errors:
            raise RuntimeError("public acquisition failed: "+json.dumps({"objects": errors, "observer": monitor_errors}))
        if len(completed) != MANIFEST_COUNT:
            raise RuntimeError("fixed official public key set is incomplete")
        validate_resume(root, rows)  # Every completed byte/hash, including newly acquired objects.
        inputs(root, public, core_path)  # Recheck the public source lock/core/Bootstrap, too.
        final = full_scan(root)
        allowed = {"audit/"+LEASE_NAME, "audit/cache-downloads.jsonl", "audit/public-cache-acquisition.json", "audit/cache-download-complete.json"}
        for name, metadata in initial["files"].items():
            if name not in allowed and final["files"].get(name) != metadata:
                raise RuntimeError("pre-existing owned file metadata changed outside this acquisition: "+name)
        new_paths = set(final["files"])-set(initial["files"])
        if any(name not in allowed and not re.fullmatch(r"downloads/mathlib-cache/[0-9a-f]{16}\.ltar", name) for name in new_paths):
            raise RuntimeError("another unexpected file appeared during exclusive acquisition")
        if final["allocated_envelope_bytes"] > ledger.used or final["allocated_envelope_bytes"]+AUDIT_BUDGET > CAP:
            raise RuntimeError("final allocation envelope exceeded the conservative ledger/finalization budget")
        end_probe = writer_probe()
        downloaded_hash = sha(receipt)
        proof = {"protocol": PROTOCOL, "recorded_at_utc": stamp(), "lease_id": lease.id,
            "core_sha256": CORE_SHA, "bootstrap_receipt_sha256": BOOTSTRAP_SHA, "public_lock_sha256": LOCK_SHA,
            "module_cache_manifest_sha256": MANIFEST_SHA, "objects": MANIFEST_COUNT, "workers": workers,
            "initial_allocated_envelope_bytes": initial["allocated_envelope_bytes"],
            "initial_metadata_fingerprint_sha256": initial["metadata_fingerprint_sha256"],
            "final_allocated_envelope_bytes": final["allocated_envelope_bytes"],
            "final_metadata_fingerprint_sha256": final["metadata_fingerprint_sha256"],
            "fixed_source_links_verified": final["fixed_source_links_verified"],
            "ledger_peak_forecast_bytes": ledger.peak, "finalization_reserved_bytes": AUDIT_BUDGET,
            "finalization_envelope_upper_bound_bytes": final["allocated_envelope_bytes"]+AUDIT_BUDGET,
            "start_writer_probe": start_probe, "end_writer_probe": end_probe, "periodic_writer_probes": probe_count,
            "pre_existing_files_unchanged_by_metadata": True, "all_cache_blob_sha256_rechecked": True,
            "download_receipts_sha256": downloaded_hash, "resumed_objects": len(old),
            "transport_policy": "same-key-response-open-transient-only-max3-v1",
            "new_receipt_transport_attempts": sum(len(r.get("transport_attempts", [])) for name, r in completed.items() if name not in old),
            "legacy_receipt_transport_attempts_unknown": len(old),
            "elapsed_seconds": round(time.monotonic()-began, 3), "full_directory_scans": 2,
            "candidate_run": False, "llm_called": False, "executable_run": False,
            "executable_run_scope": "downloaded toolchain/cache executables; the host Python acquisition worker runs",
            "lease_release_protocol": "held=false is fsynced while owning share-deny handle; handle is closed before the final stdout receipt"}
        durable_json(root/"audit/public-cache-acquisition.json", proof)
        complete = {"recorded_at_utc": stamp(), "objects": MANIFEST_COUNT, "module_cache_manifest_sha256": MANIFEST_SHA,
            "download_receipts_sha256": downloaded_hash, "compressed_bytes": sum(r["bytes"] for r in completed.values()),
            "owned_envelope_bytes": final["allocated_envelope_bytes"], "candidate_run": False,
            "acquisition_protocol": PROTOCOL, "acquisition_proof_sha256": sha(root/"audit/public-cache-acquisition.json")}
        durable_json(root/"audit/cache-download-complete.json", complete)
        volume_reserves(AUDIT_BUDGET)
        outcome = "complete"
        lease.write({"held": False, "released_at_utc": stamp(), "pid": os.getpid(), "outcome": outcome,
            "complete_receipt_sha256": sha(root/"audit/cache-download-complete.json"),
            "post_scan_envelope_upper_bound_bytes": proof["finalization_envelope_upper_bound_bytes"]})
    except Exception as error:
        stop.set()
        # Never delete or resume partials. They and completed original-hash
        # receipts stay visible for root review after an interrupted GET.
        failure_scan, failure_scan_error = None, None
        if initial is not None and final is None:
            try:
                failure_scan = full_scan(root)["allocated_envelope_bytes"]
            except Exception as scan_error:
                failure_scan_error = type(scan_error).__name__+": "+str(scan_error)
        lease.write({"held": False, "released_at_utc": stamp(), "pid": os.getpid(), "outcome": outcome,
                     "completed_objects": len(completed), "error": (type(error).__name__+": "+str(error))[:4096],
                     "failure_post_scan_envelope_bytes": failure_scan, "failure_post_scan_error": failure_scan_error,
                     "unknown_or_partial_requires_review": True})
        raise
    finally:
        lease.close()
    print(json.dumps({"public_cache_acquisition_complete": True, "objects": MANIFEST_COUNT,
        "protocol": PROTOCOL, "lease_handle_closed": True, "lease_id": lease.id,
        "complete_receipt_sha256": sha(root/"audit/cache-download-complete.json"),
        "lease_release_sha256": sha(root/"audit"/LEASE_NAME), "candidate_run": False}), flush=True)


def gate(root, public, core_path):
    root = exact_root(root)
    allocation_unit()
    free = volume_reserves()
    inputs(root, public, core_path)
    proof = writer_probe()
    path = root/"audit"/LEASE_NAME
    if path.exists():
        # A read-only gate does not create/claim a lease or scan the entire E tree.
        assert_regular(path)
        prior = json.loads(path.read_bytes())
        if prior.get("held") is not False or prior.get("protocol") != PROTOCOL or prior.get("run_id") != RUN_ID:
            raise RuntimeError("prior acquisition lease requires review")
    print(json.dumps({"protocol": PROTOCOL, "manifest_sha256": MANIFEST_SHA, "objects": MANIFEST_COUNT,
                      "workers_max": 4, "writer_probe": proof, **free, "e_write": False, "public_get": False,
                      "candidate_run": False, "core_sha256": CORE_SHA}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["gate", "acquire"])
    parser.add_argument("--root", default=ROOT)
    parser.add_argument("--public", required=True)
    parser.add_argument("--core", required=True)
    parser.add_argument("--workers", type=int, choices=range(1, 5), default=4)
    args = parser.parse_args()
    if args.stage == "gate":
        gate(args.root, args.public, args.core)
    else:
        acquire(args.root, args.public, args.core, args.workers)
