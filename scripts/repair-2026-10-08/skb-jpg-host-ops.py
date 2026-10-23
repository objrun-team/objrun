"""Bounded host I/O and exact-ownership recovery; never execute an artifact."""
from __future__ import annotations
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import tarfile
import threading
import time

TASK_ID = 'jpg-ocr-stat'
PROTOCOL = 'skb-jpg-output-v1-preseed'
LEASE_PATH = Path('C:/Users/y1252/.codex/visualizations/2026/10/08/01a119ed-fdf7-7c32-b323-de9bab1290b6/project-cache/sku-jpg/owned-instance.lock')

def daemon_absent(stderr: bytes, target: str):
    diagnostic=stderr.decode('utf-8','replace').casefold()
    return bool(re.search(r'no such (?:object|container):\s*'+re.escape(target.casefold())+r'(?=\s|$)',diagnostic))

def first_artifact_member(raw: bytes):
    """Accept bounded PAX/GNU metadata, then let tarfile apply path/size fields."""
    offset = 0
    extensions = {tarfile.XHDTYPE, tarfile.XGLTYPE, tarfile.GNUTYPE_LONGNAME, tarfile.GNUTYPE_LONGLINK}
    while True:
        if len(raw) < offset+512:
            return None
        header = tarfile.TarInfo.frombuf(raw[offset:offset+512], 'utf-8', 'strict')
        if header.type not in extensions:
            with tarfile.open(fileobj=io.BytesIO(raw[:offset+512]), mode='r:') as archive:
                return archive.next()
        if header.size < 0 or header.size > 65536:
            raise RuntimeError('Artifact TAR extension exceeds declared metadata bound')
        offset += 512+((header.size+511)//512)*512
        if offset > 256*1024:
            raise RuntimeError('Artifact TAR metadata exceeds declared capture bound')

def process_has_exited(pid: int):
    import os
    if os.name == 'nt':
        import ctypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = ctypes.c_void_p
        kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
        kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_ulong]
        kernel.CloseHandle.argtypes = [ctypes.c_void_p]
        handle = kernel.OpenProcess(0x100000, False, pid) # SYNCHRONIZE, read-only
        if not handle:
            return ctypes.get_last_error() == 87 # ERROR_INVALID_PARAMETER: no such PID
        try:return kernel.WaitForSingleObject(handle, 0) == 0
        finally:kernel.CloseHandle(handle)
    try:os.kill(pid, 0)
    except ProcessLookupError:return True
    except PermissionError:return False
    return False


def bounded_artifact_tar(argv, maximum: int, seconds: float):
    """Drain both pipes with fixed memory bounds and a host wall-clock guard.

    A stalled daemon may never emit a first byte; the supervisor therefore does
    not wait on a blocking read. A nonregular or oversize first TAR member is
    enough to record the declared format failure without transferring payload.
    """
    process = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output, errors = bytearray(), bytearray()
    guard, stopped = threading.Lock(), threading.Event()
    faults = []
    def read(stream, target, cap):
        try:
            while not stopped.is_set():
                chunk = stream.read1(65536)
                if not chunk:
                    return
                with guard:
                    remaining = cap-len(target)
                    target.extend(chunk[:remaining])
                    if len(chunk) > remaining:
                        faults.append('Docker artifact transfer exceeded bounded capture')
                        stopped.set()
        except Exception:
            with guard:
                faults.append('Docker artifact pipe did not close safely')
                stopped.set()
    readers = [threading.Thread(target=read, args=(process.stdout, output, maximum+1024*1024), daemon=True),
               threading.Thread(target=read, args=(process.stderr, errors, 1024*1024), daemon=True)]
    for reader in readers:
        reader.start()
    started, truncated = time.monotonic(), False
    try:
        while True:
            with guard:
                if faults:
                    raise RuntimeError(faults[0])
                header = bytes(output[:256*1024+512]) if len(output) >= 512 else None
            if header:
                member = first_artifact_member(header)
            else:
                member = None
            if member:
                if not member.isfile() or member.size > maximum:
                    truncated = True
                    break
            if time.monotonic()-started >= seconds:
                raise RuntimeError('Docker artifact capture exceeded its host deadline')
            if process.poll() is not None:
                break
            time.sleep(0.02)
    finally:
        if process.poll() is None:
            process.kill()
        process.wait(timeout=10)
        for reader in readers:
            reader.join(timeout=2)
        stopped.set()
        if any(reader.is_alive() for reader in readers):
            raise RuntimeError('Docker artifact pipes remained open after process exit')
        process.stdout.close(); process.stderr.close()
    with guard:
        if faults:
            raise RuntimeError(faults[0])
        return bytes(output), bytes(errors), process.returncode, not truncated


def recover_owned_grader(folder: Path, child_pid: int, image_id: str, docker_run=None):
    """Called only after the exact spawned CLI has exited.

    Missing/substituted evidence leaves the lease intact. No name-only or
    global Docker cleanup is permitted, even for an unfinished create call.
    """
    run = docker_run or (lambda argv, **kw: subprocess.run(['docker', *argv], capture_output=True, timeout=kw.get('timeout', 10)))
    path = folder/'operation-owner.json'
    recovery = {'taskId': TASK_ID, 'protocol': PROTOCOL, 'processId': child_pid,
                'processExited': process_has_exited(child_pid), 'reconciled': False, 'containers': [], 'leaseReleased': False}
    try:
        if not recovery['processExited']:
            raise RuntimeError('Private operation has not exited; no cleanup or lease release is allowed')
        owner = json.loads(path.read_text(encoding='utf-8'))
        prefix = owner.get('ownerLabelValue', '')
        if owner.get('schemaVersion') != 1 or owner.get('taskId') != TASK_ID or owner.get('protocol') != PROTOCOL or owner.get('processId') != child_pid or owner.get('ownerLabelKey') != 'objrun.jpg-owner' or not re.fullmatch(r'objrun-jpg-[0-9a-f]{12}', prefix):
            raise RuntimeError('Private grader recovery identity mismatch')
        for item in owner.get('containers', []):
            name, recorded_id = item.get('name', ''), item.get('containerId')
            role = item.get('role')
            if role not in ['grader', 'candidate', 'official-oracle'] or not re.fullmatch(re.escape(prefix+'-'+role)+r'-[0-9a-f]{8}', name) or item.get('expectedImageId') != image_id or (recorded_id is not None and not re.fullmatch(r'[0-9a-f]{64}', recorded_id)):
                raise RuntimeError('Private grader container receipt is not an exact owned identity')
            inspected = run(['inspect', name], timeout=10)
            if inspected.returncode:
                if not daemon_absent(inspected.stderr,name):
                    raise RuntimeError('Private grader daemon identity could not be inspected')
                if item.get('state') == 'creation_pending':
                    raise RuntimeError('Pending create has no final daemon identity; retain its lease')
                recovery['containers'].append({'name': name, 'state': 'confirmed_absent'})
                continue
            actual = json.loads(inspected.stdout)[0]
            cid = actual.get('Id', '')
            if actual.get('Name') != '/'+name or actual.get('Image') != image_id or (actual.get('Config', {}).get('Labels') or {}).get('objrun.jpg-owner') != prefix or not re.fullmatch(r'[0-9a-f]{64}', cid) or (recorded_id is not None and cid != recorded_id):
                raise RuntimeError('Refusing recovery of a substituted private grader container')
            removed = run(['rm', '-f', cid], timeout=30)
            if removed.returncode:
                raise RuntimeError('Exact owned private grader cleanup failed')
            absent = run(['inspect', cid], timeout=10)
            if absent.returncode == 0 or not daemon_absent(absent.stderr,cid):
                raise RuntimeError('Private grader cleanup was not confirmed by daemon')
            recovery['containers'].append({'name': name, 'containerId': cid, 'state': 'removed_and_confirmed_absent'})
        lease = owner.get('lease') or {}
        lease_path = Path(lease.get('path', '')).resolve()
        if lease_path != LEASE_PATH.resolve() or not re.fullmatch(r'[0-9a-f]{32}', lease.get('nonce', '')):
            raise RuntimeError('Private grader lease recovery identity mismatch')
        if lease_path.exists():
            data = json.loads(lease_path.read_text(encoding='utf-8'))
            if data.get('nonce') != lease['nonce'] or data.get('pid') != child_pid:
                raise RuntimeError('Refusing release of a foreign or changed private grader lease')
            lease_path.unlink()
        recovery.update(reconciled=True, leaseReleased=True)
    except Exception as error:
        recovery['error'] = str(error)
    (folder/'host-recovery.json').write_text(json.dumps(recovery, indent=2)+'\n', encoding='utf-8')
    if not recovery['reconciled']:
        raise RuntimeError('Private grader timeout cleanup could not be certified; lease retained')
    return recovery


def run_private_grader(argv, folder: Path, image_id: str, seconds: float = 650):
    child = subprocess.Popen(argv, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    (folder.parent/('cli-'+folder.name+'.json')).write_text(json.dumps({'processId': child.pid,
        'startedAt': time.time(), 'operationOutput': str(folder),
        'argvSha256': hashlib.sha256(json.dumps(argv).encode()).hexdigest()})+'\n', encoding='utf-8')
    try:
        stdout, stderr = child.communicate(timeout=seconds)
    except subprocess.TimeoutExpired:
        child.kill(); child.communicate(timeout=10)
        recover_owned_grader(folder, child.pid, image_id)
        raise RuntimeError('Private grader CLI exceeded its host operational deadline')
    if child.returncode:
        recover_owned_grader(folder, child.pid, image_id)
        raise RuntimeError('Private grader CLI did not close a valid report')
    if len(stdout) > 1024*1024 or len(stderr) > 1024*1024:
        raise RuntimeError('Private grader CLI response exceeded its host evidence boundary')
    return subprocess.CompletedProcess(argv, child.returncode, stdout, stderr)

def audit_evidence(output: Path, store: Path, secrets, private_configs):
    import gzip
    import zipfile
    values = [value.encode() for value in secrets if isinstance(value, str) and value]
    if len(values) != len(secrets) or len(values) < 6:
        raise RuntimeError('Actual host credentials must remain in memory for the evidence audit')
    excluded = {path.resolve() for path in private_configs}
    findings, files, members = [], 0, 0
    def inspect(raw, name):
        if any(value in raw for value in values):
            findings.append(name)
    for base in [output, store]:
        for path in sorted(base.rglob('*')):
            if not path.is_file() or path.resolve() in excluded:
                continue
            files += 1
            if path.suffix == '.zip':
                with zipfile.ZipFile(path) as archive:
                    for item in archive.infolist():
                        members += 1
                        inspect(archive.read(item), str(path)+'::'+item.filename)
            else:
                raw = path.read_bytes()
                inspect(gzip.decompress(raw) if path.suffix == '.gz' else raw, str(path))
    frozen_path=output/'frozen-source.json'
    if frozen_path.is_file():
        refs=json.loads(frozen_path.read_text(encoding='utf-8')).get('dependencyReferences')
        if refs:
            referenced=Path(refs['path'])
            if hashlib.sha256(referenced.read_bytes()).hexdigest()!=refs['sha256']:
                raise RuntimeError('Dependency reference changed before credential audit')
            with zipfile.ZipFile(referenced) as archive:
                for member in refs['members']:
                    raw=archive.read(member['name'])
                    if hashlib.sha256(raw).hexdigest()!=member['sha256']:
                        raise RuntimeError('Referenced dependency bytes changed before audit')
                    members+=1;inspect(raw,str(referenced)+'::'+member['name'])
    report = {'passed': not findings, 'secretValuesChecked': len(values), 'filesChecked': files,
              'archiveMembersChecked': members, 'findings': findings,
              'excludedPrivateConfigPaths': [str(path) for path in sorted(excluded)],
              'scope': 'Exact host engine/publisher and stand/gateway/proxy credential values checked in task/G/tool/API receipts, SQLite and frozen ZIP; candidate environment requires separate live validation.'}
    (output/'evidence-secret-audit.json').write_text(json.dumps(report, indent=2)+'\n', encoding='utf-8')
    if findings:
        raise RuntimeError('A private host credential entered experiment evidence')
    return report


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--recover', action='store_true')
    mode.add_argument('--audit', action='store_true')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--process-id', type=int)
    parser.add_argument('--image-id')
    parser.add_argument('--store', type=Path)
    parser.add_argument('--private-config', type=Path, action='append', default=[])
    args = parser.parse_args()
    if args.audit:
        import sys
        if not args.store:
            raise RuntimeError('The exact owned evidence store is required')
        line=sys.stdin.readline(16385)
        if len(line)>16384 or not line.endswith('\n'):
            raise RuntimeError('A bounded newline-framed host credential message is required')
        print(json.dumps(audit_evidence(args.output, args.store, json.loads(line), args.private_config)))
    else:
        if not args.process_id or args.process_id <= 0 or not re.fullmatch(r'sha256:[0-9a-f]{64}', args.image_id or ''):
            raise RuntimeError('Exact private operation PID/image are required')
        print(json.dumps(recover_owned_grader(args.output, args.process_id, args.image_id)))
