"""Multi-file extension of ordinary artifact v2's daemon TAR boundary.

Candidate files stay opaque host blobs. Never extract a candidate TAR on the
host, never import its code, and never send candidate interpreters or libraries
to the trusted grader. An explicit reviewed policy is mandatory per task.
"""
from __future__ import annotations
from dataclasses import dataclass
import hashlib
import io
from pathlib import PurePosixPath
import tarfile
import csv
import zipfile

PROTOCOL = 'skillsbench-full-f-ordinary-artifact-envelope-v1'
FORBIDDEN_ROOTS = ('/verifier', '/oracle', '/logs', '/rt', '/usr', '/bin', '/sbin', '/lib', '/etc', '/proc', '/sys', '/dev')
EXECUTABLE_SUFFIXES = {'.py', '.pyc', '.pyo', '.sh', '.so', '.dll', '.exe', '.class', '.jar', '.js', '.mjs', '.cjs', '.wasm', '.bat', '.cmd', '.ps1'}

class ArtifactFault(ValueError):
    pass

@dataclass(frozen=True)
class Policy:
    task_id: str
    source_path: str
    destination_path: str
    kind: str  # exact file or explicitly reviewed data directory
    maximum_bytes: int
    maximum_files: int
    approved_data_only: bool
    normalized_data_format: str | None = None  # staged, explicit CSV-only opt-in

def ordinary_path(path):
    if not isinstance(path, str) or not path.startswith('/') or '\\' in path or '\x00' in path:
        raise ArtifactFault('absolute POSIX path required')
    segments = path.split('/')[1:]
    if not segments or any(part in ('', '.', '..') for part in segments):
        raise ArtifactFault('noncanonical path denied')
    for prefix in FORBIDDEN_ROOTS:
        if path == prefix or path.startswith(prefix + '/') or (prefix == '/rt' and path.startswith('/rt-')):
            raise ArtifactFault('trusted/runtime namespace denied')
    return path

def validate_policy(policy):
    ordinary_path(policy.source_path); ordinary_path(policy.destination_path)
    if policy.kind not in ('file', 'directory') or policy.approved_data_only is not True:
        raise ArtifactFault('reviewed data-only file/directory policy required')
    if policy.normalized_data_format is not None:
        if (policy.normalized_data_format not in ('csv','xlsx') or policy.kind != 'file' or
                PurePosixPath(policy.source_path).suffix.lower() != '.'+policy.normalized_data_format or
                PurePosixPath(policy.destination_path).suffix.lower() != '.'+policy.normalized_data_format):
            raise ArtifactFault('explicit exact CSV data normalization policy required')
    if not (type(policy.maximum_bytes) is int and 0 < policy.maximum_bytes <= 1024**3 and
            type(policy.maximum_files) is int and 0 < policy.maximum_files <= 100000):
        raise ArtifactFault('bounded task-specific envelope required')
    if policy.kind == 'file' and policy.maximum_files != 1:
        raise ArtifactFault('single file requires one member bound')

def parse_daemon_tar(raw, policy):
    validate_policy(policy)
    if not isinstance(raw, bytes) or len(raw) > policy.maximum_bytes + (policy.maximum_files + 8) * 2048:
        raise ArtifactFault('daemon archive cap exceeded')
    basename = PurePosixPath(policy.source_path).name
    seen, blobs, total = set(), [], 0
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as archive:
        for member in archive:
            name = member.name
            if name.startswith('./'): name = name[2:]
            if not name or name.startswith('/') or '\\' in name or any(p in ('', '.', '..') for p in name.split('/')):
                raise ArtifactFault('noncanonical archive member denied')
            if name in seen: raise ArtifactFault('duplicate archive member denied')
            seen.add(name)
            if len(seen) > policy.maximum_files * 4 + 4: raise ArtifactFault('archive member count exceeded')
            if name != basename and not (policy.kind == 'directory' and name.startswith(basename + '/')):
                raise ArtifactFault('archive member outside declared output')
            if member.isdir():
                if policy.kind != 'directory': raise ArtifactFault('directory in single-file policy')
                continue
            if not member.isfile() or member.islnk() or member.issym():
                raise ArtifactFault('link/special file denied')
            if policy.kind == 'directory' and name == basename: raise ArtifactFault('directory root replaced by file')
            relative = '' if name == basename else name[len(basename) + 1:]
            destination = policy.destination_path + ('/' + relative if relative else '')
            ordinary_path(destination)
            if PurePosixPath(destination).suffix.lower() in EXECUTABLE_SUFFIXES:
                raise ArtifactFault('candidate executable denied in data replay')
            normalize_permissions = bool(member.mode & 0o111)
            office_mode = (policy.task_id == 'organize-messy-files' and policy.kind == 'directory'
                           and policy.source_path == policy.destination_path == '/root/papers'
                           and PurePosixPath(destination).suffix.lower() in ('.docx','.pptx'))
            glm_nml_mode = (policy.task_id=='glm-lake-mendota' and policy.kind=='file' and policy.source_path==policy.destination_path=='/root/glm3.nml' and policy.maximum_bytes<=262144)
            if normalize_permissions and policy.normalized_data_format not in ('csv','xlsx') and not office_mode and not glm_nml_mode:
                raise ArtifactFault('candidate executable denied in data replay')
            if member.size < 0 or total + member.size > policy.maximum_bytes or len(blobs) >= policy.maximum_files:
                raise ArtifactFault('ordinary output envelope exceeded')
            stream = archive.extractfile(member)
            body = stream.read(member.size + 1)
            if len(body) != member.size: raise ArtifactFault('truncated archive member')
            # Shebangs and binary executables must use a separate untrusted
            # execution adapter, never this trusted data verifier path.
            if body.startswith((b'#!', b'\x7fELF', b'MZ', b'\x00asm')):
                raise ArtifactFault('executable payload denied in data replay')
            if normalize_permissions and glm_nml_mode:
                # NML is data for the original pinned GLM binary, never an executable.
                # Preserve every content byte; only drop inherited permission bits.
                try:
                    body.decode('utf-8-sig')
                    if b'\x00' in body: raise ValueError('binary NML')
                except (UnicodeError,ValueError) as error:
                    raise ArtifactFault('inherited NML mode requires bounded UTF-8 data') from error
            if normalize_permissions and office_mode:
                try:
                    with zipfile.ZipFile(io.BytesIO(body)) as office:
                        entries=office.infolist(); names=[x.filename for x in entries]
                        main='word/document.xml' if destination.lower().endswith('.docx') else 'ppt/presentation.xml'
                        if len(names)>10000 or len(names)!=len(set(names)) or not {'[Content_Types].xml',main}<=set(names):raise ValueError('invalid passive OOXML')
                        if sum(x.file_size for x in entries)>256*1024**2:raise ValueError('expanded OOXML bound')
                        for entry in entries:
                            name=entry.filename
                            if name.startswith('/') or '\\' in name or '..' in name.split('/') or entry.flag_bits&1:raise ValueError('unsafe OOXML member')
                            if PurePosixPath(name).suffix.lower() in EXECUTABLE_SUFFIXES or any(x in name.lower() for x in ('vbaproject','/embeddings/','/activex/')):raise ValueError('active OOXML content')
                        if office.testzip() is not None:raise ValueError('OOXML CRC')
                except (ValueError,zipfile.BadZipFile,RuntimeError) as error:
                    raise ArtifactFault('inherited mode normalization requires bounded passive DOCX/PPTX') from error
            if normalize_permissions and policy.normalized_data_format=='xlsx':
                try:
                    with zipfile.ZipFile(io.BytesIO(body)) as workbook:
                        entries=workbook.infolist();names=[x.filename for x in entries]
                        if len(names)>10000 or len(names)!=len(set(names)) or not {'[Content_Types].xml','xl/workbook.xml'}<=set(names):raise ValueError('invalid OOXML workbook')
                        if sum(x.file_size for x in entries)>min(256*1024**2,policy.maximum_bytes*32):raise ValueError('expanded workbook limit')
                        for entry in entries:
                            name=entry.filename
                            if name.startswith('/') or '\\' in name or '..' in name.split('/') or entry.flag_bits&1:raise ValueError('unsafe OOXML entry')
                            if PurePosixPath(name).suffix.lower() in EXECUTABLE_SUFFIXES or any(x in name.lower() for x in ('vbaproject','/embeddings/','/activex/')):raise ValueError('active workbook content')
                        if workbook.testzip() is not None:raise ValueError('workbook CRC')
                except (ValueError,zipfile.BadZipFile,RuntimeError) as error:
                    raise ArtifactFault('normalized XLSX must be a bounded passive OOXML workbook') from error
            if normalize_permissions and policy.normalized_data_format=='csv':
                try:
                    if b'\x00' in body: raise ValueError('binary CSV')
                    rows = [row for row in csv.reader(io.StringIO(body.decode('utf-8-sig')), strict=True) if row]
                    # Row width is a scoring concern for the original verifier.
                    # In particular its DictReader skips one-field comment rows.
                    # Preserve all bytes; normalize only the replay file mode.
                except (ValueError, UnicodeError, csv.Error) as error:
                    raise ArtifactFault('normalized output must be bounded UTF-8 CSV data') from error
            total += member.size
            item = {'destination': destination, 'bytes': len(body), 'sha256': hashlib.sha256(body).hexdigest(), 'body': body}
            if normalize_permissions:
                item.update(sourceMode=member.mode, requiredDataReplayMode=0o600,
                            normalizationRequiresTrustedWriterChmod=True)
            blobs.append(item)
    if policy.kind == 'file' and len(blobs) != 1:
        raise ArtifactFault('exact single output missing')
    return {'protocol': PROTOCOL, 'taskId': policy.task_id, 'sourcePath': policy.source_path,
            'totalBytes': total, 'files': blobs, 'candidateExecutablesUsed': False,
            'candidateSnapshotUsed': False, 'hostExtractionUsed': False}

def evaluation_key(run_id, task_id, solver_nonce, mutation_counter, artifacts, candidate_answer):
    # Both workspace and answer changes invalidate the latest result. A fresh
    # verify always invokes grading; only its immediately matching passed node
    # may reuse that one result (the production v2 stand already has this rule).
    import json
    identity = [run_id, task_id, solver_nonce, mutation_counter,
                sorted((f['destination'], f['sha256']) for f in artifacts), candidate_answer]
    return hashlib.sha256(json.dumps(identity, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest()
