"""Bounded batches of official cache unpacking; no compiler, GET, candidate or LLM.

Host gate is read-only. Only the reviewed Windows batch entry writes the exact
owned E root. A Linux worker can write the nine declared build mounts only.
Each batch has two full allocation scans; no per-object full-tree walk occurs.
Successful batches resume an exact verified prefix. Failed/ambiguous phases
require a separate root-reviewed recovery; this program never repairs them.
"""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import queue
import re
import signal
import stat
import struct
import subprocess
import sys
import tarfile
import threading
import time
import uuid
import zipfile

PROTOCOL = 'bounded-official-cache-unpack-v1'
RUN_ID = '01a119ed-fdf7-7c32-b323-de9bab1290b6'
HOST_ROOT = 'E:/objrun-experiment-cache/' + RUN_ID + '/minif2f-v415'
IMAGE = 'sha256:adccbc2412fe240d3bba28a81e136d2e816a28b003263a2f1738098a67cbfbba'
HELPER_SHA = 'a02c3519b0ccba8a74e577991fedcf75f0c05fb181cfeb617b7e51b060384c2b'
CORE_SHA = '8c8b77f6bf64ec6b07f82419dab8d0d5ee24bad3157cd51cfe2a942b8a28cd98'
LOCK_SHA = 'ee033a2d51ef5f7dc51b573285df3c2d78689fc9edcaaf8781420525c1d8d857'
BOOT_SHA = 'cf84863b8c93839a35ca7989cc7c83fad94d09444269d563a14b28324bc76a77'
KEYS_SHA = 'bc7f8caa504054de03a3ec6a945de4a4ab7bdb12918029763c46bbb817d6dda9'
LEANTAR_SHA = 'e8fd0b10b883e7ef96f6870dc31d5c12db9c393c5658d7c9d68ceb486ee1a623'
AZURE = 'https://lakecache.blob.core.windows.net/mathlib4/f/'
PACKAGES = ('plausible', 'LeanSearchClient', 'importGraph', 'proofwidgets', 'aesop', 'Qq', 'batteries', 'Cli')
BUILD_ROOTS = ('.lake/build',) + tuple('.lake/packages/' + p + '/.lake/build' for p in PACKAGES)
MAX_BLOB = MAX_FILE = 64 * 1024**2
MAX_FILES, MAX_LINE, MAX_COMMENT = 8, 16384, 1024 * 1024
CAP, UNIT, AUDIT_BUDGET = 14 * 1024**3, 4096, 16 * 1024**2
E_RESERVE, F_RESERVE = 3 * 1024**3, 1024**3
PER_FILE_METADATA = 2 * 1024**2
BLOB_WALL, STAGE_WALL, MAX_BATCH = 300, 3 * 3600, 64


class InfraError(RuntimeError):
    def __init__(self, kind, message):
        self.kind = kind
        super().__init__(message)


def require(value, kind, message):
    if not value:
        raise InfraError(kind, message)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=False).encode()


def fingerprint(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def regular(path):
    info = Path(path).lstat()
    require(stat.S_ISREG(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
            'nonregular_path', 'Expected an actual regular non-reparse file: ' + str(path))
    return info


def ordinary_ancestors(path, root):
    path, root = Path(path).absolute(), Path(root).absolute()
    require(path.is_relative_to(root), 'path_escape', 'Path leaves its fixed owned root')
    current = path
    while True:
        if os.path.lexists(current):
            info = current.lstat()
            require(stat.S_ISDIR(info.st_mode) and not getattr(info, 'st_file_attributes', 0) & 0x400,
                    'reparse_path', 'Output parent is not an actual ordinary directory')
        if current == root:
            return
        current = current.parent


def output_path(value):
    pure = PurePosixPath(value)
    require(isinstance(value, str) and value and '\\' not in value and ':' not in value and
            not any(ord(c) < 32 or ord(c) == 127 for c in value) and
            not pure.is_absolute() and all(p not in {'', '.', '..'} for p in value.split('/')) and
            len(pure.parts) <= 16 and len(value.encode()) <= 256,
            'archive_path', 'Archive path is not a bounded canonical relative path')
    require(any(value.startswith(base + '/') for base in BUILD_ROOTS),
            'archive_path', 'Archive output is outside the nine fixed build trees')
    return value


def ltar_paths(data):
    """Inspect the fixed primary LTAR/LTR2 layout; the official binary decodes it."""
    require(12 <= len(data) <= MAX_BLOB and data[:4] in {b'LTAR', b'LTR2'},
            'archive_format', 'Unknown or out-of-bounds official archive header')
    position, comments = 12, 0

    def cstring(comment=False):
        nonlocal position, comments
        end = data.find(b'\0', position)
        require(end >= position, 'archive_truncated', 'Archive string lacks its terminator')
        raw = data[position:end]
        position = end + 1
        if comment:
            comments += len(raw)
            require(comments <= MAX_COMMENT, 'archive_comment', 'Archive comment exceeds its reviewed envelope')
        else:
            require(len(raw) <= 256, 'archive_path', 'Archive path exceeds its byte limit')
        try:
            return raw.decode('utf-8', errors='strict')
        except UnicodeError as error:
            raise InfraError('archive_utf8', 'Official archive path/comment is not UTF-8') from error

    def payload():
        nonlocal position
        require(position + 9 <= len(data), 'archive_truncated', 'Archive payload header is truncated')
        kind = data[position]
        position += 1
        length = struct.unpack_from('<Q', data, position)[0]
        position += 8
        require(kind in {0, 1, 2, 3}, 'archive_compression', 'Unknown official archive compression tag')
        if kind in {0, 1}:
            require(length <= MAX_BLOB and position + length <= len(data),
                    'archive_truncated', 'Compressed payload leaves the bounded input')
            position += length

    paths = [output_path(cstring())]
    if data[:4] == b'LTR2':
        payload()
    while position < len(data):
        value = cstring()
        if value:
            paths.append(output_path(value))
            require(len(paths) <= MAX_FILES, 'archive_file_count', 'Archive has more than eight outputs')
            payload()
        else:
            cstring(comment=True)
    require(len(paths) == len({p.casefold() for p in paths}), 'archive_duplicate_path', 'Archive repeats or aliases an output path')
    return paths


def durable_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + '.new')
    require(not temporary.exists(), 'audit_partial', 'Unreviewed audit partial exists')
    encoded = canonical(value) + b'\n'
    require(len(encoded) <= AUDIT_BUDGET, 'audit_limit', 'Audit document exceeds its reservation')
    with temporary.open('xb') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    temporary.replace(path)


def commit_outputs(root, record, files, receipt, commit_receipt):
    """The receipt's real fsync must return before the exact original is unlinked."""
    root = Path(root)
    require(bool(re.fullmatch('[0-9a-f]{16}\\.ltar', record['ltar'])) and record['url'] == AZURE + record['ltar'],
            'blob_delete_identity', 'Delete input is not an exact fixed cache key/URL')
    original = root / 'downloads/mathlib-cache' / record['ltar']
    ordinary_ancestors(original.parent, root)
    row = {'protocol': PROTOCOL, 'ltar': record['ltar'], 'source_sha256': record['sha256'],
           'source_bytes': record['bytes'], 'source_url': record['url'], 'files': files,
           'outputs_fsynced': True, 'recorded_at_utc': stamp()}
    encoded = canonical(row) + b'\n'
    require(len(encoded) <= MAX_LINE, 'audit_limit', 'Per-blob receipt exceeds its reservation')
    with Path(receipt).open('ab') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
        receipt_end = stream.tell()
    commit = {'protocol': PROTOCOL, 'ltar': record['ltar'], 'receipt_line_sha256': hashlib.sha256(encoded).hexdigest(),
              'receipt_end': receipt_end, 'receipt_fsync_returned': True, 'recorded_at_utc': stamp()}
    with Path(commit_receipt).open('ab') as stream:
        stream.write(canonical(commit) + b'\n')
        stream.flush()
        os.fsync(stream.fileno())
    info = regular(original)
    require(info.st_size == record['bytes'] and sha(original) == record['sha256'],
            'blob_changed_before_delete', 'Exact original blob differs after its durable output receipt')
    original.unlink()  # Only this exact 16hex name from the pinned download manifest.
    return row


def bounded_official(binary, archive, cwd, file_limit=MAX_FILE, wall=BLOB_WALL):
    """No reimplementation: invoke the hash-pinned official executable itself."""
    import resource

    def limits():
        resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
        resource.setrlimit(resource.RLIMIT_CPU, (120, 120))
        resource.setrlimit(resource.RLIMIT_AS, (1024**3, 1024**3))

    process = subprocess.Popen([str(binary), '--jobs', '1', '-f', '-x', str(archive)], cwd=cwd,
        stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        start_new_session=True, preexec_fn=limits)
    outputs, overflow = [bytearray(), bytearray()], threading.Event()

    def collect(index, incoming):
        while chunk := incoming.read(4096):
            if len(outputs[index]) + len(chunk) > 65536:
                overflow.set()
                try: os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError: pass
                break
            outputs[index].extend(chunk)

    threads = [threading.Thread(target=collect, args=(i, pipe), daemon=True)
               for i, pipe in enumerate((process.stdout, process.stderr))]
    for thread in threads: thread.start()
    timed_out = False
    try:
        process.wait(timeout=wall)
    except subprocess.TimeoutExpired:
        timed_out = True
        os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=10)
    finally:
        for thread in threads: thread.join(timeout=5)
        require(not any(t.is_alive() for t in threads), 'official_pipe_stuck', 'Official output reader did not close')
    require(not timed_out and not overflow.is_set(), 'official_limit', 'Official process exceeded its wall/output limit')
    require(process.returncode == 0, 'official_process', 'Official executable failed; preserve partial outputs')
    return {'exit_code': process.returncode, 'stdout': outputs[0].decode(errors='replace'),
            'stderr': outputs[1].decode(errors='replace'), 'jobs': 1,
            'rlimit_fsize': file_limit, 'rlimit_cpu': 120, 'rlimit_as': 1024**3}


def staged_files(base):
    """Walk only the small fresh staging trees, never the complete cache root."""
    base, files = Path(base), []
    for relative in BUILD_ROOTS:
        tree = base / relative
        ordinary_ancestors(tree, base)
        for home, dirs, names in os.walk(tree, followlinks=False):
            ordinary_ancestors(Path(home), base)
            for directory in dirs: ordinary_ancestors(Path(home) / directory, base)
            for name in names:
                path = Path(home) / name
                regular(path)
                files.append(output_path(path.relative_to(base).as_posix()))
                require(len(files) <= MAX_FILES, 'staged_file_count', 'Staging contains more than eight actual regular files')
    return files


def unpack_one(root, record):
    require(os.name == 'posix' and str(Path(root).absolute()) == '/cache',
            'worker_root', 'Official unpack worker only accepts the fixed /cache mount')
    root = Path(root)
    name = record.get('ltar', '')
    require(bool(re.fullmatch('[0-9a-f]{16}\\.ltar', name)) and record.get('url') == AZURE + name,
            'blob_identity', 'Input key/URL differs from the pinned download namespace')
    archive = root / 'downloads/mathlib-cache' / name
    before = regular(archive)
    require(0 < before.st_size == record['bytes'] <= MAX_BLOB and sha(archive) == record['sha256'],
            'blob_identity', 'Actual read-only input differs from its original receipt')
    paths = ltar_paths(archive.read_bytes())
    staged = Path('/stage/mathlib4')
    require(not staged_files(staged), 'stage_not_fresh', 'A previous/partial staged output exists; do not reuse it')
    for value in paths:
        target = staged / value
        ordinary_ancestors(target.parent, staged)
        require(not os.path.lexists(target), 'stage_not_fresh', 'Expected staging output already exists')
    binary = root / 'tools/leantar'
    regular(binary)
    require(sha(binary) == LEANTAR_SHA, 'official_binary', 'Official leantar binary differs')
    result = bounded_official(binary, archive, staged)
    require(set(staged_files(staged)) == set(paths), 'output_missing', 'Official exit status omitted or added a fresh expected output')
    files = []
    for value in paths:
        target = staged / value
        ordinary_ancestors(target.parent, staged)
        require(os.path.lexists(target), 'output_missing', 'Official exit status did not produce every expected output')
        info = regular(target)
        require(info.st_size <= MAX_FILE, 'output_file_limit', 'Official output exceeds 64 MiB')
        with target.open('rb') as stream:
            digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            os.fsync(stream.fileno())
        files.append({'path': value, 'bytes': info.st_size, 'sha256': digest})
    require(regular(archive).st_size == before.st_size and sha(archive) == record['sha256'],
            'readonly_input_changed', 'Official process changed its read-only original input')
    return {'valid': True, 'files': files, 'expected_output_count': len(paths), 'outputs_fsync_returned': True,
            'official': result, 'input_sha256': record['sha256'], 'fresh_staged_outputs': True}


def worker():
    # start --attach is asynchronous on the Windows caller. Do not admit an
    # operation until the actual Linux process has proven its fresh mounts.
    ready = {'protocol': PROTOCOL, 'worker_ready': True, 'official_binary_sha256': sha('/cache/tools/leantar'),
             'staged_regular_files': len(staged_files('/stage/mathlib4'))}
    sys.stdout.buffer.write(canonical(ready) + b'\n'); sys.stdout.buffer.flush()
    for incoming in sys.stdin.buffer:
        try:
            require(len(incoming) <= MAX_LINE and incoming.endswith(b'\n'), 'ipc_frame', 'Worker IPC frame is not bounded')
            request = json.loads(incoming)
            require(set(request) == {'record'}, 'ipc_frame', 'Unknown worker operation')
            result = unpack_one('/cache', request['record'])
        except Exception as error:
            result = {'valid': False, 'outcome': 'infrastructure_invalid',
                      'error_type': getattr(error, 'kind', type(error).__name__), 'error': str(error)}
        encoded = canonical(result) + b'\n'
        require(len(encoded) <= MAX_LINE, 'ipc_frame', 'Worker reply exceeds its reservation')
        sys.stdout.buffer.write(encoded); sys.stdout.buffer.flush()
        if not result['valid']: return 1
    return 0


def load_helper(project):
    path = project / 'scripts/benchmark-repair/minif2f_public_cache.py'
    require(sha(path) == HELPER_SHA, 'helper_source', 'Fixed root-reviewed cache helper changed')
    spec = importlib.util.spec_from_file_location('fixed_cache_helper', path)
    helper = importlib.util.module_from_spec(spec); spec.loader.exec_module(helper)
    return helper


def read_lines(path, maximum=MAX_LINE):
    regular(path)
    raw = Path(path).read_bytes()
    require(not raw or raw.endswith(b'\n'), 'receipt_truncated', 'Receipt has a truncated final line')
    rows = []
    for line in raw.splitlines(keepends=True):
        require(0 < len(line) <= maximum, 'receipt_line', 'Receipt line is empty or oversized')
        rows.append((line, json.loads(line)))
    return rows


def inputs(project, root, helper):
    complete_path = root / 'audit/cache-download-complete.json'
    require(complete_path.exists(), 'download_unclosed', '5826-object download-complete receipt does not exist')
    rows = helper.inputs(root, project / '.phase1-data/minif2f-restoration-public',
                         project / 'scripts/benchmark-repair/minif2f_restore.py')
    complete = json.loads(complete_path.read_bytes())
    downloaded_path, proof_path = root / 'audit/cache-downloads.jsonl', root / 'audit/public-cache-acquisition.json'
    require(sha(downloaded_path) == complete['download_receipts_sha256'] and
            sha(proof_path) == complete['acquisition_proof_sha256'], 'download_provenance', 'Original closed receipts differ')
    proof = json.loads(proof_path.read_bytes())
    require(complete['objects'] == proof['objects'] == len(rows) == 5826 and
            complete['module_cache_manifest_sha256'] == proof['module_cache_manifest_sha256'] == KEYS_SHA and
            proof['bootstrap_receipt_sha256'] == BOOT_SHA and proof['core_sha256'] == CORE_SHA and
            proof['public_lock_sha256'] == LOCK_SHA and complete['acquisition_protocol'] == proof['protocol'] == helper.PROTOCOL and
            proof['download_receipts_sha256'] == complete['download_receipts_sha256'] and
            proof['all_cache_blob_sha256_rechecked'] is True and proof['pre_existing_files_unchanged_by_metadata'] is True and
            complete['candidate_run'] is False and proof['llm_called'] is False,
            'download_provenance', 'Closed acquisition provenance is not the fixed complete protocol')
    by_name = {row['ltar']: row for row in rows}
    records = {}
    for _, record in read_lines(downloaded_path, 2048):
        name = record['ltar']
        require(name in by_name and name not in records and record['module'] == by_name[name]['module'] and
                record['url'] == AZURE + name and record['http_status'] == 200 and
                record['acquisition_protocol'] == helper.PROTOCOL and
                bool(re.fullmatch('[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}', record['lease_id'])) and
                isinstance(record['bytes'], int) and 0 < record['bytes'] <= MAX_BLOB and
                bool(re.fullmatch('[0-9a-f]{64}', record['sha256'])),
                'download_row', 'Cache row key/URL/count/size/hash/provenance is invalid')
        records[name] = record
    require(set(records) == set(by_name) and sum(r['bytes'] for r in records.values()) == complete['compressed_bytes'],
            'download_count', 'Original object count or compressed byte sum differs')
    return [records[row['ltar']] for row in rows], {'download_complete_sha256': sha(complete_path),
            'download_receipts_sha256': sha(downloaded_path), 'acquisition_proof_sha256': sha(proof_path),
            'bootstrap_sha256': BOOT_SHA, 'keys_sha256': KEYS_SHA, 'public_lock_sha256': LOCK_SHA}


def verified_prefix(root, records):
    receipts = root / 'audit/cache-unpacked.jsonl'
    commits = root / 'audit/cache-fast-commits.jsonl'
    progress_path = root / 'audit/cache-fast-progress.json'
    if not receipts.exists():
        require(not commits.exists() and not progress_path.exists(), 'unknown_partial', 'Orphan fast phase state exists')
        return [], set()
    require(progress_path.exists() and commits.exists(), 'legacy_or_partial_receipt', 'Unpacking receipts lack this protocol successful phase closure')
    progress = json.loads(progress_path.read_bytes())
    require(progress.get('protocol') == PROTOCOL and progress.get('validated') is True and
            progress['receipts_sha256'] == sha(receipts) and progress['commits_sha256'] == sha(commits),
            'previous_phase_unclosed', 'Previous phase is failed, ambiguous or changed; root recovery is required')
    unpacked, committed = read_lines(receipts), read_lines(commits)
    require(len(unpacked) == len(committed) == progress['processed_prefix'], 'receipt_count', 'Prior prefix/commit count differs')
    used, end = set(), 0
    for index, ((line, row), (_, commit)) in enumerate(zip(unpacked, committed)):
        source = records[index]; end += len(line)
        require(row.get('protocol') == commit.get('protocol') == PROTOCOL and
                row['ltar'] == commit['ltar'] == source['ltar'] and row['source_sha256'] == source['sha256'] and
                row['source_bytes'] == source['bytes'] and row['source_url'] == source['url'] and
                row['outputs_fsynced'] is True and commit['receipt_fsync_returned'] is True and
                commit['receipt_line_sha256'] == hashlib.sha256(line).hexdigest() and commit['receipt_end'] == end and
                not (root / 'downloads/mathlib-cache' / source['ltar']).exists(),
                'ambiguous_receipt', 'Prior receipt/blob deletion is not an exact closed prefix')
        require(0 < len(row['files']) <= MAX_FILES, 'receipt_files', 'Prior receipt exceeds eight actual outputs')
        for file in row['files']:
            path = output_path(file['path']); target = root / 'mathlib4' / path
            ordinary_ancestors(target.parent, root)
            require(path.casefold() not in used and regular(target).st_size == file['bytes'] <= MAX_FILE and sha(target) == file['sha256'],
                    'receipt_output_changed', 'Prior actual output differs or overlaps another blob')
            used.add(path.casefold())
    return [row for _, row in unpacked], used


def source_identity(project, root, helper):
    public = project / '.phase1-data/minif2f-restoration-public'
    sources = []
    archives = [('mathlib', root / 'mathlib4'), ('repl', root / 'repl')] + [
            ('package-' + p, root / 'mathlib4/.lake/packages' / p) for p in PACKAGES]
    for name, destination in archives:
        ordinary_ancestors(destination, root)
        archive_path = public / (name + '-source.tar.gz' if name in {'mathlib', 'repl'} else name + '.tar.gz')
        with tarfile.open(archive_path, 'r:gz') as archive:
            for member in archive.getmembers():
                pure = PurePosixPath(member.name)
                require(not pure.is_absolute() and '..' not in pure.parts, 'source_archive_path', 'Pinned source path leaves its root')
                if len(pure.parts) == 1: continue
                target = destination.joinpath(*pure.parts[1:])
                ordinary_ancestors(target.parent, root)
                if member.isdir(): ordinary_ancestors(target, root); continue
                protected_relative = target.relative_to(root).as_posix()
                require(not any(protected_relative.startswith('mathlib4/' + b + '/') for b in BUILD_ROOTS),
                        'source_in_build_mount', 'A pinned source file would fall in a writable build mount')
                if member.issym():
                    require(name == 'package-batteries' and member.linkname == '../README.md', 'source_link', 'Unrecognized source link')
                    proof = helper.verify_fixed_source_link(root, target)
                    sources.append({'source': name, **proof}); continue
                require(member.isfile(), 'source_nonregular', 'Source archive has an unrecognized nonregular member')
                with archive.extractfile(member) as stream: expected = hashlib.file_digest(stream, 'sha256').hexdigest()
                require(regular(target).st_size == member.size and sha(target) == expected, 'source_changed', 'Actual source differs from its fixed archive: ' + str(target))
                sources.append({'source': name, 'path': '/'.join(pure.parts[1:]), 'bytes': member.size, 'sha256': expected})
    boot = json.loads((root / 'audit/bootstrap.json').read_bytes())
    toolchain_archive = root / 'downloads/lean-4.15.0-linux.zip'
    require(regular(toolchain_archive).st_size == 427590493 and sha(toolchain_archive) == boot['lean_download_sha256'],
            'toolchain_archive', 'Lean download bytes differ from fixed Bootstrap')
    with zipfile.ZipFile(toolchain_archive) as archive:
        for member in archive.infolist():
            pure = PurePosixPath(member.filename)
            require(not pure.is_absolute() and '..' not in pure.parts, 'toolchain_path', 'Pinned toolchain path leaves its root')
            if member.is_dir(): continue
            target = root / 'toolchain' / Path(*pure.parts[1:])
            ordinary_ancestors(target.parent, root)
            with archive.open(member) as stream: expected = hashlib.file_digest(stream, 'sha256').hexdigest()
            require(regular(target).st_size == member.file_size and sha(target) == expected,
                    'toolchain_changed', 'Actual toolchain bytes differ from fixed release')
            sources.append({'source': 'toolchain', 'path': '/'.join(pure.parts[1:]), 'bytes': member.file_size, 'sha256': expected})
    require(sha(root / 'repl/.lake/build/bin/repl') == boot['repl_binary_sha256'] and sha(root / 'tools/leantar') == LEANTAR_SHA,
            'executable_identity', 'Fixed REPL or official unpacker differs')
    return {'sha256': fingerprint(sources), 'verified_entries': len(sources), 'lean_archive_sha256': boot['lean_download_sha256'],
            'repl_sha256': boot['repl_binary_sha256'], 'leantar_sha256': LEANTAR_SHA}


def gate(project):
    helper = load_helper(project)
    root = helper.exact_root(HOST_ROOT); helper.allocation_unit(); helper.volume_reserves()
    records, provenance = inputs(project, root, helper)
    prior, used = verified_prefix(root, records)
    directory = root / 'downloads/mathlib-cache'
    remaining = {r['ltar'] for r in records[len(prior):]}
    require({p.name for p in directory.iterdir()} == remaining, 'unknown_blob', 'Input directory contains an untracked or missing artifact')
    for record in records[len(prior):]:
        path = directory / record['ltar']
        require(regular(path).st_size == record['bytes'] and sha(path) == record['sha256'],
                'blob_identity', 'Remaining original blob differs from its acquisition receipt')
    return helper, root, records, provenance, prior, used


class AcquisitionGuard:
    """Hold original acquisition lease share-deny without changing its bytes."""
    def __init__(self, path): self.path, self.stream = Path(path), None
    def __enter__(self):
        api = ctypes.WinDLL('kernel32', use_last_error=True)
        create = api.CreateFileW
        create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        create.restype = wintypes.HANDLE
        import msvcrt
        regular(self.path)
        handle = create(str(self.path), 0x80000000, 0, None, 3, 0x00200000, None)
        require(handle != ctypes.c_void_p(-1).value, 'acquisition_active', 'Original acquisition lease cannot be held read-only share-deny')
        fd = msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY)
        self.stream = os.fdopen(fd, 'rb', buffering=0)
        try:
            raw = self.stream.read(16385)
            require(0 < len(raw) <= 16384, 'acquisition_lease', 'Original lease is empty or oversized')
            marker = json.loads(raw)
            require(marker.get('protocol') == 'public-cache-acquisition-v1' and marker.get('run_id') == RUN_ID and
                    marker.get('held') is False and marker.get('outcome') == 'complete',
                    'acquisition_unclosed', 'Original acquisition lease has not completed and released')
            self.sha256 = hashlib.sha256(raw).hexdigest()
        except BaseException:
            self.stream.close(); self.stream = None
            raise
        return self
    def __exit__(self, *_):
        if self.stream: self.stream.close(); self.stream = None


class DockerWorker:
    def __init__(self, root, project):
        self.root, self.project, self.cid, self.pipe = root, project, None, None
        self.name, self.nonce = 'objrun-minif-fast-' + uuid.uuid4().hex[:12], uuid.uuid4().hex
        self.reply = queue.Queue(maxsize=1)
        self.stage = root / 'audit' / ('cache-fast-stage-' + self.nonce)

    def __enter__(self):
        try:
            return self.create()
        except BaseException:
            # An enter failure does not trigger context-manager __exit__.
            # The fresh random name/label/image intent was saved before create.
            if hasattr(self, 'owner_path'):
                self.close()
            raise

    def create(self):
        require(not self.stage.exists(), 'stage_collision', 'Fresh owned staging root already exists')
        self.stage.mkdir()
        for relative in BUILD_ROOTS:
            path = self.stage / 'mathlib4' / relative
            ordinary_ancestors(path.parent, self.root)
            path.mkdir(parents=True, exist_ok=True); ordinary_ancestors(path, self.root)
        argv = ['docker', 'create', '--name', self.name, '--label', 'objrun.minif-fast=' + self.nonce,
                '--pull', 'never', '--network', 'none', '--read-only', '--cap-drop', 'ALL',
                '--security-opt', 'no-new-privileges', '--cpus', '2', '--memory', '2g', '--memory-swap', '2g',
                '--pids-limit', '64', '--log-driver', 'none', '--user', '0:0',
                '--tmpfs', '/tmp:rw,nosuid,nodev,size=67108864', '--shm-size', '16m',
                '--env', 'PYTHONDONTWRITEBYTECODE=1', '--mount', 'type=bind,source=' + str(self.root) + ',target=/cache,readonly',
                '--mount', 'type=bind,source=' + str(self.stage) + ',target=/stage,readonly',
                '--mount', 'type=bind,source=' + str(Path(__file__).resolve()) + ',target=/plan/fast.py,readonly']
        for relative in BUILD_ROOTS:
            argv += ['--mount', 'type=bind,source=' + str(self.stage / 'mathlib4' / relative) + ',target=/stage/mathlib4/' + relative]
        owner = {'protocol': PROTOCOL, 'name': self.name, 'owner_label': self.nonce, 'image_id': IMAGE,
                 'state': 'creation_pending', 'container_id': None, 'recorded_at_utc': stamp()}
        self.owner_path = self.root / 'audit/cache-fast-container.json'; durable_json(self.owner_path, owner)
        result = subprocess.run(argv + ['--interactive', '--entrypoint', 'python', IMAGE, '-B', '/plan/fast.py', 'worker'], capture_output=True, text=True, timeout=30)
        require(result.returncode == 0, 'container_create', 'Cannot create the exact owned worker')
        self.cid = result.stdout.strip()
        owner.update(state='created', container_id=self.cid); durable_json(self.owner_path, owner)
        self.verify()
        self.pipe = subprocess.Popen(['docker', 'start', '--attach', '--interactive', self.cid], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW)
        def read():
            while line := self.pipe.stdout.readline(MAX_LINE + 1):
                self.reply.put(line)
        self.reader = threading.Thread(target=read, daemon=True); self.reader.start()
        try: encoded = self.reply.get(timeout=30)
        except queue.Empty as error: raise InfraError('worker_startup', 'Actual Linux worker did not become ready') from error
        require(len(encoded) <= MAX_LINE and encoded.endswith(b'\n'), 'worker_startup', 'Worker startup frame is invalid')
        ready = json.loads(encoded)
        require(ready.get('protocol') == PROTOCOL and ready.get('worker_ready') is True and
                ready.get('official_binary_sha256') == LEANTAR_SHA and ready.get('staged_regular_files') == 0,
                'worker_startup', 'Actual worker binary or fresh staged state differs')
        return self

    def verify(self, configuration=True):
        result = subprocess.run(['docker', 'inspect', self.cid or self.name], capture_output=True, text=True, timeout=30)
        if result.returncode:
            require('no such' in result.stderr.casefold() and (self.cid or self.name) in result.stderr,
                    'container_identity', 'Owned worker cannot be inspected')
            if not configuration: return None
            raise InfraError('container_identity', 'Owned worker is absent before work')
        item = json.loads(result.stdout)[0]
        require(item['Image'] == IMAGE and item['Config']['Labels'].get('objrun.minif-fast') == self.nonce and item['Name'] == '/' + self.name,
                'container_identity', 'Worker image/name/label differs')
        require(not self.cid or item['Id'] == self.cid, 'container_identity', 'Worker immutable ID differs')
        if configuration:
            mounts = {m['Destination']: m for m in item['Mounts']}
            expected = {'/cache': (self.root, False), '/stage': (self.stage, False), '/plan/fast.py': (Path(__file__).resolve(), False)}
            expected.update({'/stage/mathlib4/' + relative: (self.stage / 'mathlib4' / relative, True) for relative in BUILD_ROOTS})
            require(set(mounts) == set(expected), 'worker_mount', 'Worker mount set differs')
            for destination, (source, writable) in expected.items():
                actual = mounts[destination]
                normalized = actual['Source'].replace('\\', '/').rstrip('/').casefold()
                for prefix in ('/run/desktop/mnt/host/', '/host_mnt/'):
                    if normalized.startswith(prefix):
                        normalized = normalized[len(prefix)] + ':' + normalized[len(prefix) + 1:]
                require(actual['Type'] == 'bind' and actual['RW'] is writable and normalized == str(source).replace('\\', '/').rstrip('/').casefold(),
                        'worker_mount', 'Worker has an unexpected source/type/write mode')
            host = item['HostConfig']
            require(host['ReadonlyRootfs'] and host['NetworkMode'] == 'none' and host['NanoCpus'] == 2 * 10**9 and
                    host['Memory'] == host['MemorySwap'] == 2 * 1024**3 and host['PidsLimit'] == 64 and
                    host['CapDrop'] == ['ALL'] and 'no-new-privileges' in ' '.join(host['SecurityOpt']),
                    'worker_configuration', 'Worker root/network/CPU/memory/process restrictions differ')
        self.cid = item['Id']
        return item

    def call(self, record):
        self.pipe.stdin.write(canonical({'record': record}) + b'\n'); self.pipe.stdin.flush()
        try: encoded = self.reply.get(timeout=BLOB_WALL + 30)
        except queue.Empty as error: raise InfraError('worker_timeout', 'Worker did not close a bounded blob response') from error
        require(len(encoded) <= MAX_LINE and encoded.endswith(b'\n'), 'ipc_frame', 'Worker response is unbounded or truncated')
        result = json.loads(encoded)
        require(result.get('valid') is True and result.get('outputs_fsync_returned') is True and result.get('fresh_staged_outputs') is True,
                result.get('error_type', 'worker_invalid'), result.get('error', 'Official output did not validate'))
        return result

    def materialize(self, record, files):
        # The Linux process has exited for this object and closed its files.
        # Every source is a fresh regular staged file, then same-E replace gives
        # the official native build path without a second copy allocation.
        ordinary_ancestors(self.stage, self.root)
        require(set(staged_files(self.stage / 'mathlib4')) == {f['path'] for f in files},
                'stage_identity', 'Staged actual output set changed before materialization')
        intent = {'protocol': PROTOCOL, 'ltar': record['ltar'], 'stage': str(self.stage), 'files': files,
                  'state': 'materialization_pending', 'recorded_at_utc': stamp()}
        durable_json(self.root / 'audit/cache-fast-item.json', intent)
        for file in files:
            source = self.stage / 'mathlib4' / output_path(file['path'])
            target = self.root / 'mathlib4' / file['path']
            ordinary_ancestors(source.parent, self.root); ordinary_ancestors(target.parent, self.root)
            require(regular(source).st_size == file['bytes'] <= MAX_FILE and sha(source) == file['sha256'],
                    'stage_identity', 'Fresh staged bytes differ before same-volume materialization')
            target.parent.mkdir(parents=True, exist_ok=True); ordinary_ancestors(target.parent, self.root)
            if os.path.lexists(target): regular(target)
            source.replace(target)
            with target.open('r+b') as stream:
                require(hashlib.file_digest(stream, 'sha256').hexdigest() == file['sha256'], 'output_identity', 'Materialized bytes differ')
                stream.flush(); os.fsync(stream.fileno())
        # Remove only the known now-empty descendants of the nine fresh roots.
        # No recursive delete, no unknown directory or partial file is pruned.
        parents = set()
        for file in files:
            base = next(b for b in BUILD_ROOTS if file['path'].startswith(b + '/'))
            boundary = self.stage / 'mathlib4' / base
            parent = (self.stage / 'mathlib4' / file['path']).parent
            while parent != boundary:
                parents.add(parent); parent = parent.parent
        for path in sorted(parents, key=lambda p: len(p.parts), reverse=True):
            ordinary_ancestors(path, self.stage)
            path.rmdir()  # Refuses a nonempty directory instead of deleting it.
        require(not staged_files(self.stage / 'mathlib4'), 'stage_not_empty', 'Materialized stage still contains an actual file')
        intent.update(state='materialized_and_fsynced', materialized_at_utc=stamp())
        durable_json(self.root / 'audit/cache-fast-item.json', intent)

    def discard_empty_stage(self):
        # Only after successful batch/source/receipt closure and exact daemon
        # removal. These directories were created by this object's nonce.
        owner = json.loads(self.owner_path.read_bytes())
        require(owner.get('state') == 'removed' and owner.get('owner_label') == self.nonce,
                'stage_cleanup', 'Cannot remove staged directories before exact owned worker closure')
        require(not staged_files(self.stage / 'mathlib4'), 'stage_cleanup', 'A staged partial must remain for review')
        known = {self.stage}
        for relative in BUILD_ROOTS:
            current = self.stage / 'mathlib4' / relative
            while current != self.stage:
                known.add(current); current = current.parent
        for path in sorted(known, key=lambda p: len(p.parts), reverse=True):
            ordinary_ancestors(path, self.stage)
            path.rmdir()  # Never recursively deletes unknown files/directories.
        return len(known)

    def __exit__(self, *_):
        self.close()

    def close(self):
        if self.pipe:
            self.pipe.stdin.close()
            try: self.pipe.wait(timeout=10)
            except subprocess.TimeoutExpired: pass  # Exact daemon stop below is authoritative.
        item = self.verify(configuration=False)
        if item:
            result = subprocess.run(['docker', 'rm', '--force', item['Id']], capture_output=True, text=True, timeout=30)
            require(result.returncode == 0, 'worker_cleanup', 'Owned worker removal did not succeed')
            result = subprocess.run(['docker', 'inspect', item['Id']], capture_output=True, text=True, timeout=30)
            require(result.returncode != 0 and 'no such' in result.stderr.casefold() and item['Id'] in result.stderr,
                    'worker_cleanup', 'Daemon did not confirm exact owned worker absent')
        if self.pipe:
            try: self.pipe.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.pipe.terminate(); self.pipe.wait(timeout=10)  # This exact child handle only.
        owner = json.loads(self.owner_path.read_bytes()); owner['state'] = 'removed' if item else 'absent_after_create_attempt'; owner['removed_at_utc'] = stamp()
        durable_json(self.owner_path, owner)


def batch(project, count, review_sha):
    require(sha(__file__) == review_sha, 'review_source', 'Batch requires the exact root-reviewed script SHA')
    require(1 <= count <= MAX_BATCH, 'batch_limit', 'Batch count must be 1..64')
    helper, root, records, provenance, prior, used = gate(project)
    lease = helper.Lease(root / 'audit/cache-fast-unpack.lock')
    # Separate cooperative fast lease; the original acquisition record remains
    # unchanged and its share-deny read handle excludes another acquisition.
    try: lease.acquire()
    except BaseException:
        lease.close(); raise
    outcome, started, failure = 'infrastructure_invalid', time.monotonic(), None
    report = {'protocol': PROTOCOL, 'candidate_run': False, 'llm_called': False, 'public_get': False,
              'reviewed_script_sha256': review_sha, 'helper_sha256': HELPER_SHA, 'input_provenance': provenance,
              'prefix_before': len(prior), 'requested_count': count, 'validated': False, 'recorded_at_utc': stamp()}
    progress_path = root / 'audit/cache-fast-progress.json'
    receipts, commits = root / 'audit/cache-unpacked.jsonl', root / 'audit/cache-fast-commits.jsonl'
    try:
        with AcquisitionGuard(root / 'audit/public-cache-acquisition.lock') as acquisition:
            report['original_acquisition_lease_sha256'] = acquisition.sha256
            helper.writer_probe()  # Before any owned writable container exists.
            initial = helper.full_scan(root)
            identity_before = source_identity(project, root, helper)
            envelope, peak = initial['allocated_envelope_bytes'] + AUDIT_BUDGET, initial['allocated_envelope_bytes'] + AUDIT_BUDGET
            require(envelope <= CAP, 'root_cap', 'Initial envelope plus durable audit budget exceeds 14 GiB')
            report.update(initial_envelope=initial['allocated_envelope_bytes'], source_before=identity_before)
            durable_json(progress_path, {**report, 'validated': False, 'state': 'running', 'processed_prefix': len(prior)})
            for path in (receipts, commits):
                if not path.exists():
                    with path.open('xb') as stream: stream.flush(); os.fsync(stream.fileno())
            with DockerWorker(root, project) as worker:
                report['worker_identity'] = worker.verify()
                # Avoid saving image environment; store only the relevant mounts/IDs.
                item = report.pop('worker_identity')
                report['worker'] = {'container_id': item['Id'], 'image_id': item['Image'], 'mounts': item['Mounts'],
                                    'root_readonly': item['HostConfig']['ReadonlyRootfs'], 'network': item['HostConfig']['NetworkMode'], 'cpus': 2}
                for record in records[len(prior):len(prior) + count]:
                    require(time.monotonic() - started <= STAGE_WALL, 'stage_timeout', 'Bounded batch exceeds three hours')
                    blob = root / 'downloads/mathlib-cache' / record['ltar']
                    paths = ltar_paths(blob.read_bytes())
                    require(not {p.casefold() for p in paths} & used, 'output_overlap', 'Blob overwrites an earlier committed output')
                    reservation = len(paths) * (MAX_FILE + PER_FILE_METADATA) + 65536
                    require(envelope + reservation <= CAP, 'root_cap', 'Worst per-blob output would cross 14 GiB')
                    helper.volume_reserves(reservation)
                    peak = max(peak, envelope + reservation)
                    actual = worker.call(record)
                    require([f['path'] for f in actual['files']] == paths, 'output_paths', 'Actual output set differs from audited archive')
                    worker.materialize(record, actual['files'])
                    for file in actual['files']:
                        target = root / 'mathlib4' / file['path']
                        ordinary_ancestors(target.parent, root)
                        require(regular(target).st_size == file['bytes'] <= MAX_FILE and sha(target) == file['sha256'],
                                'output_identity', 'Host actual output differs from the official worker result')
                    committed = commit_outputs(root, record, actual['files'], receipts, commits)
                    prior.append(committed); used.update(p.casefold() for p in paths)
                    envelope += sum(helper.rounded(f['bytes']) + PER_FILE_METADATA for f in actual['files']) + 65536 - helper.rounded(record['bytes'])
                    helper.volume_reserves()
                    if len(prior) % 16 == 0: print(json.dumps({'processed_prefix': len(prior), 'total': 5826, 'envelope_upper_bound': envelope}), flush=True)
            helper.writer_probe()
            identity_after = source_identity(project, root, helper)
            require(identity_before == identity_after, 'source_changed', 'Source/toolchain/REPL identity changed across batch')
            _, provenance_after = inputs(project, root, helper)
            require(provenance_after == provenance, 'input_provenance_changed', 'Original source/Bootstrap/key/download receipts changed across batch')
            final = helper.full_scan(root)
            allowed = lambda path: path.startswith('audit/cache-fast-') or path == 'audit/cache-unpacked.jsonl' or any(path.startswith('mathlib4/' + base + '/') for base in BUILD_ROOTS) or bool(re.fullmatch('downloads/mathlib-cache/[0-9a-f]{16}\\.ltar', path))
            for path, metadata in initial['files'].items():
                require(allowed(path) or final['files'].get(path) == metadata, 'outside_write', 'Pre-existing non-output file changed')
                if any(path.startswith('mathlib4/' + base + '/') for base in BUILD_ROOTS) and path.removeprefix('mathlib4/').casefold() not in used:
                    require(final['files'].get(path) == metadata, 'unexpected_output', 'An undeclared pre-existing build file changed')
            require(all(allowed(p) for p in set(final['files']) - set(initial['files'])), 'outside_write', 'Unexpected file appeared outside the nine build/audit trees')
            for path in set(final['files']) - set(initial['files']):
                if any(path.startswith('mathlib4/' + base + '/') for base in BUILD_ROOTS):
                    require(path.removeprefix('mathlib4/').casefold() in used, 'unexpected_output', 'Official process produced an undeclared regular output')
            require(final['allocated_envelope_bytes'] + AUDIT_BUDGET <= CAP and final['allocated_envelope_bytes'] <= envelope,
                    'ledger_mismatch', 'Final allocation exceeds the conservative incremental envelope')
            # Recheck all prior and new actual cache outputs, not just this batch.
            for row in prior:
                for file in row['files']:
                    target = root / 'mathlib4' / file['path']
                    require(regular(target).st_size == file['bytes'] and sha(target) == file['sha256'], 'final_output_changed', 'Committed output changed before closure')
            remaining = records[len(prior):]
            directory = root / 'downloads/mathlib-cache'
            require({p.name for p in directory.iterdir()} == {r['ltar'] for r in remaining},
                    'remaining_blob_set', 'A remaining original input is missing or an unknown file appeared')
            for record in remaining:
                path = directory / record['ltar']
                require(regular(path).st_size == record['bytes'] and sha(path) == record['sha256'],
                        'remaining_blob_changed', 'An unprocessed original changed across batch')
            helper.volume_reserves(AUDIT_BUDGET)
            require(time.monotonic() - started <= STAGE_WALL, 'stage_timeout', 'Batch including closure exceeds three hours')
            report.update(validated=True, state='batch_closed', processed_prefix=len(prior), source_after=identity_after,
                full_directory_scans=2, final_envelope=final['allocated_envelope_bytes'], ledger_peak=peak,
                receipts_sha256=sha(receipts), commits_sha256=sha(commits), cache_unpack_complete=len(prior) == 5826,
                controls_executed=False, elapsed_seconds=round(time.monotonic() - started, 3))
            report['known_empty_stage_directories_removed'] = worker.discard_empty_stage()
            report['final_envelope_scope'] = 'Verified upper bound before removal of exact known empty staged directories'
            durable_json(progress_path, {**report, 'validated': False, 'state': 'awaiting_lease_release'})
            outcome = 'batch_closed'
    except Exception as error:
        failure = {'error_type': getattr(error, 'kind', type(error).__name__), 'error': str(error)}
        report.update(validated=False, state='failed_preserve_partials', processed_prefix=len(prior), **failure)
        try: durable_json(progress_path, report)
        except Exception as audit_error: report['audit_error'] = type(audit_error).__name__
        raise
    finally:
        try:
            lease.write({'held': False, 'released_at_utc': stamp(), 'pid': os.getpid(), 'stage': PROTOCOL, 'outcome': outcome})
        finally:
            lease.close()
    # No completed certificate is published before both native lease handles
    # have closed. A crash/final fsync failure stays awaiting_lease_release.
    report['fast_lease_release_sha256'] = sha(root / 'audit/cache-fast-unpack.lock')
    report['lease_handle_closed'] = True
    durable_json(progress_path, report)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stage', choices=['gate', 'batch', 'worker'])
    parser.add_argument('--count', type=int, default=64)
    parser.add_argument('--review-sha', default='')
    args = parser.parse_args()
    if args.stage == 'worker': return worker()
    require(os.name == 'nt', 'host_platform', 'Host stage requires actual Windows ownership/reserve semantics')
    project = Path(__file__).resolve().parents[2]
    try:
        if args.stage == 'gate':
            _, _, records, provenance, prior, _ = gate(project)
            result = {'protocol': PROTOCOL, 'gate_passed': True, 'objects': len(records), 'verified_prefix': len(prior),
                      'input_provenance': provenance, 'e_write': False, 'public_get': False, 'candidate_run': False, 'llm_called': False}
        else:
            result = batch(project, args.count, args.review_sha)
        print(json.dumps(result, ensure_ascii=False)); return 0
    except Exception as error:
        print(json.dumps({'protocol': PROTOCOL, 'valid': False, 'outcome': 'infrastructure_invalid',
            'error_type': getattr(error, 'kind', type(error).__name__), 'error': str(error),
            'candidate_run': False, 'llm_called': False, 'public_get': False}), file=sys.stderr)
        return 2


if __name__ == '__main__':
    sys.exit(main())
