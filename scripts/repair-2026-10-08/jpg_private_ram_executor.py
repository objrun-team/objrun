"""Independent trusted JPG RAM scorer. Import/default preparation is inert.

Only Root explicitly launches actual --namespace-probe/--grade operations after
source/resource review. No build/pull/provider; no host bind, snapshot execution
or candidate interpreter is admitted. Existing scorer is imported for its pinned
pure official-input/result functions, never its Docker/lease/main execution.
"""
from __future__ import annotations
import argparse
import ctypes
import errno
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import threading
import time
import uuid

import jpg_d_storage_profile as storage
import jpg_private_ram_profile as ram

PROTOCOL = 'jpg-private-shared-ram-executor-v1'
OLD_SHA = 'fd3a65ed2ee692daa2797a8f014ce2722dff1b66aa1db6d88870e04caa7776da'
REPO = storage.REPO
DOCKER = Path('D:/Program/resources/bin/docker.exe')  # observed installed client, not an assumed C installation
DOCKER_HOST = 'npipe:////./pipe/dockerDesktopLinuxEngine'
MAX_ARTIFACT = 8 * 1024**2
OUT_CAP, ERR_CAP = 1024**2, 256 * 1024
OP_CAP, CLOSE_RESERVE = 96 * 1024**2, 2 * 1024**2
HOST_RESERVE = 1024**3
OFFICIAL_SECONDS = 600


class GradeFault(RuntimeError):
    def __init__(self, kind, detail): super().__init__(detail); self.kind = kind


def demand(value, kind, detail):
    if not value: raise GradeFault(kind, detail)


def missing_target(exit_code, stdout, stderr, kind, target):
    """Narrow observed missing inspect, never a generic inspect-failure bypass.

    Message words are case-compatible; the declared target stays exact and
    case-sensitive. Only rc1, empty/JSON[] stdout and one known complete stderr
    line pass. Permission/transport, neighboring names, extra errors/items fail.
    """
    if type(exit_code) is not int or exit_code!=1 or not isinstance(stdout,bytes) or not isinstance(stderr,bytes):return False
    if kind=='container':
        if not isinstance(target,str) or not re.fullmatch(r'(?:[0-9a-f]{64}|objrun-jpg-(?:private|ram-seeder)-[0-9a-f]{32})',target):return False
        shapes=[('Error response from daemon: No such container: ',''),('Error: No such object: ',''),
                ('No such object: ',''),('No such container: ','')]
    elif kind=='volume':
        if not isinstance(target,str) or not re.fullmatch(r'objrun-jpg-ram-[0-9a-f]{32}',target):return False
        shapes=[('Error response from daemon: get ',': no such volume'),('Error response from daemon: No such volume: ',''),
                ('No such volume: ',''),('Error: No such volume: ','')]
    else:return False
    if len(stdout)>64 or len(stderr)>1024:return False
    try:
        if stdout.strip() and json.loads(stdout.decode('utf8',errors='strict'))!=[]:return False
        lines=stderr.decode('utf8',errors='strict').splitlines()
    except (ValueError,UnicodeError):return False
    if len(lines)!=1:return False
    line=lines[0].strip()
    return any(re.fullmatch('(?i:'+re.escape(prefix)+')'+re.escape(target)+'(?i:'+re.escape(suffix)+')',line) is not None
               for prefix,suffix in shapes)


def pin(path): return storage.fingerprint(path)
def canonical(value): return storage.canonical(value)


def verify_pin(value):
    demand(isinstance(value, dict) and isinstance(value.get('path'), str) and
           type(value.get('bytes')) is int and re.fullmatch('[0-9a-f]{64}', value.get('sha256', '')),
           'pin', 'Complete ordinary-file Pin required')
    actual = pin(value['path'])
    demand(actual['bytes'] == value['bytes'] and actual['sha256'] == value['sha256'], 'pin_changed', 'Pinned input changed')
    return actual


def pinned_json(path, expected):
    p = pin(path); demand(p['sha256'] == expected, 'pin_changed', 'Explicit input SHA differs')
    demand(p['bytes'] <= 2 * 1024**2, 'metadata_cap', 'Metadata exceeds its bounded parser')
    value = json.loads(Path(path).read_bytes()); verify_pin(p)
    return value, p


def official_module():
    path = Path(__file__).with_name('software-jpg-private-grader.py')
    demand(pin(path)['sha256'] == OLD_SHA, 'official_helper_source', 'Frozen pure official helper changed')
    spec = importlib.util.spec_from_file_location('jpg_pinned_pure_official', path)
    value = importlib.util.module_from_spec(spec); spec.loader.exec_module(value)
    return value


def source_pins():
    return [pin(p) for p in (Path(__file__), Path(storage.__file__), Path(ram.__file__),
                            Path(__file__).with_name('software-jpg-private-grader.py'))]


def stable_sources(before):
    demand(source_pins() == before, 'source_drift', 'Executable source bytes changed')


def parse_owner_rows(raw, pid, nonce, sources, plan_value, lease_path):
    """Strict typed owner journal. This parser alone is never closure proof."""
    demand(isinstance(raw,bytes) and len(raw)<=256*1024 and raw.endswith(b'\n'),
           'owner_chain_tail','Unknown/incomplete owner intent tail')
    previous='0'*64;rows=[];known={};pending=[]
    allowed={'instance_lease_acquired','volume_create_intent','container_create_intent','container_identity',
             'container_removed','container_absent_after_create_attempt','volume_removed','volume_absent_after_create_attempt'}
    for i,line in enumerate(raw.splitlines(keepends=True)):
        row=json.loads(line)
        demand(row.get('protocol')==PROTOCOL+'-owner-event' and row.get('seq')==i and row.get('previousSha256')==previous and
               row.get('pid')==pid and row.get('operationNonce')==nonce and row.get('kind') in allowed,
               'owner_chain','Exact original actor/nonce/source chain differs')
        rows.append(row);previous=hashlib.sha256(line).hexdigest()
        if row['kind']=='volume_create_intent':
            demand(row.get('name')==plan_value['volumeName'] and ('volume',plan_value['volumeName']) not in pending,
                   'owner_volume','Volume intent differs or repeats')
            pending.append(('volume',plan_value['volumeName']))
        elif row['kind']=='container_create_intent':
            role=row.get('role');name=('objrun-jpg-private-' if role=='grader' else 'objrun-jpg-ram-seeder-')+plan_value['nonce']
            demand(role in ('grader','seeder') and row.get('name')==name and row.get('imageId')==ram.IMAGE and ('container',name) not in pending,
                   'owner_container','Container intent substituted/repeated')
            pending.append(('container',name))
        elif row['kind']=='container_identity':
            role=row.get('role');name=('objrun-jpg-private-' if role=='grader' else 'objrun-jpg-ram-seeder-')+plan_value['nonce']
            demand(role in ('grader','seeder') and role not in known and row.get('name')==name and ('container',name) in pending and
                   row.get('expectedImageId')==ram.IMAGE and re.fullmatch('[0-9a-f]{64}',row.get('containerId','')),
                   'owner_container','Original immutable CID/name/image missing or substituted')
            known[role]={k:row[k] for k in ('name','containerId','expectedImageId','role','state')}
    demand(rows and rows[0].get('kind')=='instance_lease_acquired' and rows[0].get('sourcePins')==sources and
           rows[0].get('ramPlanSourceSha256')==plan_value['sourceSha256'] and rows[0].get('nonce')==nonce and
           Path(rows[0].get('leasePath',''))==Path(lease_path), 'owner_source','Original lease/source identity differs')
    return rows,pending,known


def fresh_bytes(path, raw, boundary):
    p = Path(path); storage.ordinary(p.parent, boundary)
    with p.open('xb') as f:
        demand(f.write(raw) == len(raw), 'short_write', 'Evidence write was incomplete')
        f.flush(); os.fsync(f.fileno())
    result = pin(p)
    demand(result['bytes'] == len(raw) and result['sha256'] == hashlib.sha256(raw).hexdigest(),
           'readback', 'Fsynced bytes did not read back identically')
    return result


def exact_tar_file(raw, name, maximum):
    demand(len(raw) <= maximum + 65536, 'output_capture_cap', 'Private report TAR exceeded its bound')
    with tarfile.open(fileobj=io.BytesIO(raw), mode='r:') as t:
        members = t.getmembers()
        demand(len(members) == 1 and members[0].isfile() and members[0].name in (name, './' + name) and
               0 <= members[0].size <= maximum, 'output_tar', 'Only the exact regular private report is accepted')
        f = t.extractfile(members[0]); body = f.read(maximum + 1)
        demand(len(body) == members[0].size, 'output_tar', 'Private report body was incomplete')
        return body


def capture_input(receipt, value):
    """The protected host receipt alone determines artifact delivery state."""
    state, evidence = receipt.get('state'), receipt.get('daemonEvidence') or {}
    cid = receipt.get('ownedContainerID', '')
    demand(receipt.get('taskId') == 'jpg-ocr-stat' and receipt.get('protocol') == 'skb-jpg-output-v1-preseed' and
           receipt.get('artifactPath') == '/app/workspace/stat_ocr.xlsx' and receipt.get('containerStopped') is True and
           receipt.get('mock') is not True and re.fullmatch('[0-9a-f]{64}', cid) and evidence.get('containerId') == cid and
           state in ('regular', 'absent', 'directory', 'symlink', 'too_large'), 'capture', 'Exact stopped-container host capture is required')
    if state == 'absent':
        demand(evidence.get('missingFileDiagnosticMatched') is True and not receipt.get('artifactSha256'),
               'capture_absent', 'Missing output requires exact daemon absence evidence')
        return None
    if state != 'regular':
        expected = 'regular' if state == 'too_large' else state
        demand(evidence.get('memberKind') == expected and evidence.get('method') == 'docker-cp-tar' and
               not receipt.get('artifactSha256') and (state != 'too_large' or evidence.get('size', 0) > MAX_ARTIFACT),
               'capture_format', 'Format/budget failure is not supported by the daemon member')
        return None
    demand(evidence.get('memberKind') == 'regular' and evidence.get('method') == 'docker-cp-tar' and
           evidence.get('rawTarCaptureComplete') is True and type(receipt.get('artifactBytes')) is int,
           'capture_regular', 'Regular output did not complete its exact daemon transfer')
    p = Path(receipt.get('hostArtifactPath', ''))
    root = Path(value['storePhysical']); storage.ordinary(p.parent, root)
    demand(p.name == 'stat_ocr.xlsx', 'artifact_name', 'Only the fixed XLSX is imported')
    item = pin(p); z = p.lstat()
    demand(z.st_nlink == 1 and item['bytes'] <= MAX_ARTIFACT and item['bytes'] == receipt['artifactBytes'] == evidence.get('size') and
           item['sha256'] == receipt.get('artifactSha256'), 'artifact_identity', 'Regular artifact bytes/size/identity differ')
    return item


def bounded_child(argv, env, directory, serial, guard, timeout, cap=OUT_CAP):
    """Two bounded pipe readers, exact direct-child wait, fsync+readback captures.

    A killed Docker client is never taken as daemon execution cleanup. The
    caller removes separately verified exact containers in its native finally.
    """
    box = Path(directory); out = box / ('command-%03d.stdout.bin' % serial); err = box / ('command-%03d.stderr.bin' % serial)
    faults, sizes, threads = [], [0, 0], []
    began = time.monotonic(); process = None
    guard(cap + ERR_CAP + 16384)
    argv_sha=hashlib.sha256(canonical(argv)).hexdigest()
    intent_pin=fresh_bytes(box / ('command-%03d.intent.json' % serial),canonical({
        'protocol':PROTOCOL+'-native-command-intent','serial':serial,'ownerPid':os.getpid(),'argvSha256':argv_sha,
        'atUnixMs':int(time.time()*1000),'spawnOutcomeKnown':False}),box)
    child_pin=None
    with out.open('xb') as a, err.open('xb') as b:
        try:
            guard(cap + ERR_CAP + 8192)
            process = subprocess.Popen(argv, cwd=box, env=env, stdin=subprocess.DEVNULL,
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=False,
                                       creationflags=(subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0))
            child_pin=fresh_bytes(box / ('command-%03d.child.json' % serial),canonical({
                'protocol':PROTOCOL+'-native-command-child','serial':serial,'ownerPid':os.getpid(),'childPid':process.pid,
                'argvSha256':argv_sha,'intentPin':intent_pin,'atUnixMs':int(time.time()*1000)}),box)
            def reader(stream, file, index, limit):
                try:
                    while True:
                        raw = stream.read(4096)
                        if not raw: break
                        if sizes[index] + len(raw) > limit:
                            faults.append('stdout_cap' if index == 0 else 'stderr_cap'); break
                        guard(len(raw) + 8192)
                        demand(file.write(raw) == len(raw), 'short_write', 'Child capture write was incomplete')
                        sizes[index] += len(raw)
                except BaseException as e: faults.append(getattr(e, 'kind', type(e).__name__))
                finally: stream.close()
            for i, (stream, file, limit) in enumerate(((process.stdout, a, cap), (process.stderr, b, ERR_CAP))):
                thread = threading.Thread(target=reader, args=(stream, file, i, limit), daemon=True); thread.start(); threads.append(thread)
            while process.poll() is None:
                if faults or time.monotonic() - began > timeout:
                    if not faults: faults.append('command_timeout')
                    process.kill(); break
                try: guard(8192)
                except BaseException as e: faults.append(getattr(e, 'kind', type(e).__name__)); process.kill(); break
                time.sleep(0.1)
            process.wait(timeout=10)
            for thread in threads: thread.join(timeout=10)
            if any(thread.is_alive() for thread in threads): faults.append('reader_not_closed')
        finally:
            if process is not None and process.poll() is None: process.kill(); process.wait(timeout=10)
            for stream in ((process.stdout, process.stderr) if process is not None else ()):
                if stream and not stream.closed: stream.close()
            for thread in threads: thread.join(timeout=1)
            a.flush(); os.fsync(a.fileno()); b.flush(); os.fsync(b.fileno())
    rows = {'pid': process.pid if process else None, 'argvSha256': argv_sha,'intentPin':intent_pin,'childPin':child_pin,
            'exitCode': process.returncode if process else None, 'seconds': time.monotonic() - began,
            'stdoutPin': pin(out), 'stderrPin': pin(err), 'captureFsyncReturned': True,
            'directChildWaitReturned': process is not None and process.poll() is not None,
            'pipeReadersClosed': not any(t.is_alive() for t in threads), 'faults': faults}
    fresh_bytes(box / ('command-%03d.json' % serial), canonical(rows), box)
    demand(not faults and rows['directChildWaitReturned'] and rows['pipeReadersClosed'],
           'bounded_child', 'Child timeout/capture/resource/closure failed; partial bytes retained')
    return rows, out.read_bytes(), err.read_bytes()


def mount_probe_code(p, full_capacity):
    """Fixed base interpreter; no candidate shell or Python content is executed."""
    return '''import errno,hashlib,json,os,sys
P=''' + repr({k: p[k] for k in ('protocol', 'nonce', 'imageId', 'volumeName')}) + '''
paths=''' + repr(list(ram.MOUNTS)) + '''
rows=[]
for path in paths:
 s=os.statvfs(path); rows.append({'path':path,'filesystem':'tmpfs' if s.f_fsid else 'unknown','fsid':str(s.f_fsid),'device':str(os.stat(path).st_dev),'blockSize':s.f_frsize,'totalBlocks':s.f_blocks,'volumeName':P['volumeName']})
# statvfs IDs are paired with independently read kernel mountinfo filesystem.
mounts=open('/proc/self/mountinfo').read().splitlines()
for row in rows:
 matches=[l for l in mounts if l.split()[4]==row['path']]
 row['filesystem']=matches[-1].split(' - ',1)[1].split()[0] if len(matches)==1 else 'missing-or-ambiguous'
readonly=False
try:
 fd=os.open('/usr/local/objrun-root-ro-'+P['nonce'],os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600);os.close(fd)
except OSError as e:readonly=e.errno==errno.EROFS
full=''' + repr(bool(full_capacity)) + '''
capacity=False; filled=0
if full:
 path='/tmp/objrun-capacity-'+P['nonce']; fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
 try:
  raw=b'x'*1048576
  while filled<=536870912:
   try:filled+=os.write(fd,raw)
   except OSError as e:
    if e.errno==errno.ENOSPC:capacity=True;break
    raise
 finally:os.close(fd);os.unlink(path)
base='/usr/bin/python3.12'
dev=os.statvfs('/dev');shm=os.statvfs('/dev/shm')
print(json.dumps({'protocol':P['protocol']+'-native-mount-probe','nonce':P['nonce'],'imageId':P['imageId'],'paths':rows,'rootFilesystemReadOnly':readonly,'trustedBasePythonPath':base,'python':sys.version.split()[0],'basePythonSha256':hashlib.sha256(open(base,'rb').read()).hexdigest(),'basePythonImageSource':P['imageId'],'seederAliveDuringProbe':True,'rootReadonlyWriteRejected':readonly,'capacityBoundaryReachedAndRejected':capacity,'capacityBytesWritten':filled,'capacityProbeExecuted':full,'devTmpfsBytes':dev.f_frsize*dev.f_blocks,'shmTmpfsBytes':shm.f_frsize*shm.f_blocks,'namespaces':{n:os.readlink('/proc/self/ns/'+n) for n in ['pid','mnt','net']}}))
'''


def seeder_kernel_code():
    return 'import os,json;d=os.statvfs("/dev");s=os.statvfs("/dev/shm");print(json.dumps({"devBytes":d.f_frsize*d.f_blocks,"shmBytes":s.f_frsize*s.f_blocks}))'


class RamOperation:
    def __init__(self, value, plan_value, output, sources_before, docker_sha, recipe, capture_cid=None):
        self.value, self.plan, self.output, self.before, self.recipe = value, plan_value, Path(output), sources_before, recipe
        self.client = pin(DOCKER); demand(self.client['sha256'] == docker_sha, 'docker_client', 'Fixed Docker CLI changed')
        self.serial, self.pending, self.identities, self.samples, self.command_records = 0, [], {}, [], []
        self.event_sha = '0' * 64; self.event_count = 0; self.closed = False; self.capture_cid = capture_cid
        self.env = {k: os.environ[k] for k in ('SystemRoot', 'WINDIR', 'PATH', 'PATHEXT') if k in os.environ}
        self.env.update(storage.native_environment(value))
        for k in ('HOME', 'USERPROFILE', 'APPDATA', 'LOCALAPPDATA', 'DOCKER_CONFIG'):
            path = Path(value['directories']['tmp']) / ('docker-' + k.lower())
            storage.ordinary(path.parent, Path(value['storePhysical']))
            path.mkdir(exist_ok=True); storage.ordinary(path, Path(value['storePhysical'])); self.env[k] = str(path)
        self.lease = storage.JpgInstanceLease(value, self.output.name[6:], self.output)

    def event(self, kind, **value):
        row = {'protocol': PROTOCOL + '-owner-event', 'seq': self.event_count, 'previousSha256': self.event_sha,
               'pid': os.getpid(), 'operationNonce': self.output.name[6:], 'atUnixMs':int(time.time()*1000), 'kind': kind, **value}
        raw = canonical(row); demand(len(raw) <= 32768, 'owner_event_cap', 'Owner event exceeds its metadata cap')
        path = self.output / 'owner-events.jsonl'
        with path.open('ab' if self.event_count else 'xb') as f:
            demand(f.write(raw) == len(raw), 'short_write', 'Owner intent was not durably written')
            f.flush(); os.fsync(f.fileno())
        self.event_sha = hashlib.sha256(raw).hexdigest(); self.event_count += 1

    def room(self, pending_bytes=0, closing=False):
        actual = storage.observe_owned_store(self.value)
        demand(actual['allocatedEnvelopeBytes'] + pending_bytes <= storage.STORE_CAP - (0 if closing else CLOSE_RESERVE),
               'D_cap', 'Whole owned D store plus this capture reserve exceeded3GiB')
        unit=storage.cluster_size(self.output)
        allocated = unit + sum(max(unit, (p.stat().st_size + unit-1)//unit*unit) for p in self.output.iterdir() if p.is_file())
        demand(allocated + pending_bytes <= OP_CAP, 'operation_cap', 'One private RAM operation exceeded96MiB evidence')
        free = actual['volumeFreeBytes']
        bounds = storage.assess_resources(self.value, free, self.capture_cid is not None,
                                         getattr(self, 'solver_size', 0))
        demand(bounds['admitted'], 'resource_reserve', 'C/D/F conservative background+solver reserve unavailable')
        demand(free['D'] >= storage.D_MIN + pending_bytes, 'D_reserve', 'Next capture would consume D3GiB reserve')
        if self.samples and len(self.samples) >= 256: self.samples.pop(0)
        self.samples.append({'atUnixMs': int(time.time()*1000), 'freeBytes': free, 'storeAllocatedEnvelopeBytes': actual['allocatedEnvelopeBytes'],
                             'pendingBytes': pending_bytes, 'solverWritableBytes': getattr(self, 'solver_size', 0),
                             'solverRemainingFBytes': bounds['requirements']['solverRemainingFReservationBytes']})

    def command(self, *argv, timeout=30, checked=True, closing=False, cap=OUT_CAP):
        demand(self.serial < 64, 'command_count', 'One operation cannot exceed64 Docker commands')
        self.serial += 1
        if not closing: stable_sources(self.before); verify_pin(self.client)
        guard = (lambda amount: self.room(amount, closing=True)) if closing else self.room
        rows, out, err = bounded_child([str(DOCKER), '--host', DOCKER_HOST, *argv], self.env, self.output,
                                      self.serial, guard, timeout, cap)
        self.command_records.append(pin(self.output / ('command-%03d.json' % self.serial)))
        if checked: demand(rows['exitCode'] == 0, 'docker_command', 'Docker command failed; exact raw stderr retained')
        return rows, out, err

    def json(self, *argv, **kwargs):
        _, raw, _ = self.command(*argv, **kwargs); return json.loads(raw)

    def absent_before_create(self, kind, name):
        rows, out, err = self.command(kind, 'inspect', name, checked=False)
        demand(missing_target(rows['exitCode'],out,err,kind,name),
               'not_fresh', 'Exact owned name already exists or daemon absence is ambiguous')

    def begin(self):
        self.lease.acquire(); self.event('instance_lease_acquired', leasePath=str(self.lease.path), nonce=self.lease.nonce,
                                        sourcePins=self.before, ramPlanSourceSha256=self.plan['sourceSha256'])
        # Classify only the captured candidate ID; absent is explicit daemon evidence.
        if self.capture_cid:
            rows, out, err = self.command('container', 'inspect', '--size', self.capture_cid, checked=False)
            if rows['exitCode'] != 0:
                demand(missing_target(rows['exitCode'],out,err,'container',self.capture_cid),
                       'candidate_absence', 'Captured candidate daemon identity is ambiguous')
                self.capture_cid = None
            else:
                actual = json.loads(out)[0]; h = actual['HostConfig']
                demand(actual['Id'] == self.capture_cid and actual['Image'] == ram.IMAGE and actual['State']['Running'] is False and
                       not h.get('Binds') and not h.get('PidMode') and h.get('Memory') == ram.MEMORY and h.get('NanoCpus') == 4000000000,
                       'solver_identity', 'Captured solver remains active/substituted or lacks its original namespace')
                self.solver_size = actual.get('SizeRw')
                demand(type(self.solver_size) is int and 0 <= self.solver_size <= storage.SOLVER_UPPER_CAP,
                       'solver_cap', 'Actual frozen JPG solver exceeded256MiB')
        self.room(32768)
        daemon = self.json('info', '--format', '{{json .}}')
        self.daemon = {k: daemon.get(k) for k in ('ID','Name','OSType','Driver','ServerVersion','MemTotal','NCPU')}
        demand(self.daemon['OSType'] == 'linux' and isinstance(self.daemon['ID'], str) and self.daemon['ID'],
               'daemon_identity', 'Exact local Linux daemon identity missing')
        class Memory(ctypes.Structure):
            _fields_=[('length',ctypes.c_ulong),('load',ctypes.c_ulong),('total',ctypes.c_ulonglong),('available',ctypes.c_ulonglong),
                      ('totalPage',ctypes.c_ulonglong),('availPage',ctypes.c_ulonglong),('totalVirtual',ctypes.c_ulonglong),('availVirtual',ctypes.c_ulonglong),('extended',ctypes.c_ulonglong)]
        m=Memory();m.length=ctypes.sizeof(m)
        demand(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(m)), 'physical_memory', 'Actual host physical memory query failed')
        need = ram.MEMORY + self.plan['physicalExtraRamReservationBytes'] + HOST_RESERVE
        demand(m.available >= need and self.daemon['MemTotal'] >= need and self.daemon['NCPU'] >= 4,
               'physical_memory', 'Private4GiB plus seeder/sharedRAM/kernel/headroom cannot be reserved')
        self.memory = {'actualHostAvailableBytes':m.available,'requiredBytes':need,'daemonMemTotal':self.daemon['MemTotal']}
        image = self.json('image', 'inspect', ram.IMAGE)[0]
        demand(image.get('Id') == ram.IMAGE and (image.get('Config',{}).get('Labels') or {}).get('objrun.skb.task-id') == 'jpg-ocr-stat',
               'original_image', 'Cached exact complete original task image was substituted')
        for kind, name in (('volume', self.plan['volumeName']), ('container', 'objrun-jpg-ram-seeder-' + self.plan['nonce']),
                           ('container', 'objrun-jpg-private-' + self.plan['nonce'])): self.absent_before_create(kind, name)

    def make(self):
        self.event('volume_create_intent', name=self.plan['volumeName'], planSourceSha256=self.plan['sourceSha256'])
        self.pending.append(('volume', self.plan['volumeName']))
        self.command(*self.plan['volumeCreate'])
        actual = self.json('volume', 'inspect', self.plan['volumeName'])[0]; ram.validate_volume(actual, self.plan)
        self.volume_before = actual
        for role in ('seeder', 'grader'):
            name = ('objrun-jpg-ram-seeder-' if role == 'seeder' else 'objrun-jpg-private-') + self.plan['nonce']
            self.event('container_create_intent', name=name, role=role, imageId=ram.IMAGE)
            self.pending.append(('container', name)); self.command(*self.plan[role + 'Create'])
            actual = self.json('container', 'inspect', '--size', name)[0]; ram.validate_container(actual, self.plan, seeder=role == 'seeder')
            self.identities[role] = {'name':name,'containerId':actual['Id'],'expectedImageId':ram.IMAGE,'role':role,'state':'created'}
            self.event('container_identity', **self.identities[role]); self.command('start', actual['Id'])
        self.namespace_before = self.inspect_roles()

    def inspect_roles(self):
        rows = {}
        for role, record in self.identities.items():
            actual = self.json('container','inspect','--size',record['containerId'])[0]
            ram.validate_container(actual,self.plan,seeder=role=='seeder')
            demand(actual['Id'] == record['containerId'] and actual['State']['Running'] is True and
                   type(actual.get('SizeRw')) is int and 0 <= actual['SizeRw'] <= 1024**2,
                   'private_running', 'Exact idle private role/rootfs writable-layer state differs')
            rows[role] = actual
        return rows

    def probe(self, full):
        before = self.inspect_roles(); cid = self.identities['grader']['containerId']
        _, raw, _ = self.command('exec',cid,'/usr/bin/python3.12','-I','-B','-c',mount_probe_code(self.plan,full),timeout=60)
        value = json.loads(raw); after = self.inspect_roles()
        value.update(graderSizeRwBefore=before['grader']['SizeRw'],graderSizeRwAfter=after['grader']['SizeRw'])
        ram.validate_mount_probe(value,self.plan,require_capacity=full)
        demand(value.get('devTmpfsBytes',ram.RAM+1) <= self.plan['perRoleDevTmpfsMaximumBytes'] and value.get('shmTmpfsBytes') == ram.SHM,
               'kernel_mount_budget', 'Docker auxiliary RAM mounts exceeded their separate reservations')
        kernel_code=seeder_kernel_code()
        _,kraw,_=self.command('exec',self.identities['seeder']['containerId'],'/usr/bin/python3.12','-I','-B','-c',kernel_code)
        kernel=json.loads(kraw)
        demand(type(kernel.get('devBytes')) is int and 0<=kernel['devBytes']<=self.plan['perRoleDevTmpfsMaximumBytes'] and
               kernel.get('shmBytes')==ram.SHM,'kernel_mount_budget','Seeder auxiliary RAM mounts exceeded their distinct reserve')
        value['seederKernelMounts']=kernel
        fresh_bytes(self.output / ('namespace-full-probe.json' if full else 'namespace-current-probe.json'),canonical(value),self.output)
        return value

    def copy(self, source, target):
        item=pin(source); demand(item['bytes'] <= 64*1024**2, 'trusted_input_cap','Single trusted file exceeds64MiB')
        self.command('cp',str(source),self.identities['grader']['containerId']+':'+target);verify_pin(item)
        return {'path':target,'bytes':item['bytes'],'sha256':item['sha256']}

    def cleanup(self):
        faults=[]
        # Native cleanup remains possible after room/source guard failure; bounded
        # cleanup captures use only owned D cap/reserve, never a new authorization.
        original_room=self.room
        def close_room(amount=0,closing=False):
            demand(shutil.disk_usage('D:/').free >= storage.D_MIN + amount, 'closing_D_reserve', 'Cannot durably capture cleanup at D reserve')
            observed=storage.observe_owned_store(self.value)
            demand(observed['allocatedEnvelopeBytes'] + amount <= storage.STORE_CAP, 'closing_D_cap', 'Cleanup capture exceeds whole D cap')
        self.room=close_room
        try:
            for role in ('grader','seeder'):
                name=('objrun-jpg-private-' if role=='grader' else 'objrun-jpg-ram-seeder-')+self.plan['nonce']
                if ('container',name) not in self.pending: continue
                try:
                    rows,out,err=self.command('container','inspect',name,checked=False,closing=True)
                    if rows['exitCode'] != 0:
                        demand(missing_target(rows['exitCode'],out,err,'container',name),'owned_absence','Creation attempt has ambiguous absence')
                        self.event('container_absent_after_create_attempt',name=name);continue
                    actual=json.loads(out)[0];ram.validate_container(actual,self.plan,seeder=role=='seeder')
                    record=self.identities.get(role)
                    demand(not record or record['containerId']==actual['Id'],'cleanup_identity','Owned container ID changed')
                    record=record or {'name':name,'containerId':actual['Id'],'expectedImageId':ram.IMAGE,'role':role};self.identities[role]=record
                    self.command('rm','-f',actual['Id'],timeout=30,closing=True)
                    # Actual fresh exact-ID absence, not an old removed flag.
                    r,o,e=self.command('container','inspect',actual['Id'],checked=False,closing=True)
                    demand(missing_target(r['exitCode'],o,e,'container',actual['Id']),'owned_absence','Exact container ID still exists')
                    record['state']='removed';self.event('container_removed',**record)
                except BaseException as e:faults.append(getattr(e,'kind',type(e).__name__))
            if ('volume',self.plan['volumeName']) in self.pending and not faults:
                try:
                    r,o,e=self.command('volume','inspect',self.plan['volumeName'],checked=False,closing=True)
                    if r['exitCode'] != 0:
                        demand(missing_target(r['exitCode'],o,e,'volume',self.plan['volumeName']),
                               'owned_volume_absence','Creation attempt has ambiguous volume identity')
                        self.event('volume_absent_after_create_attempt',name=self.plan['volumeName']);self.volume_removed=True
                        self.closed=True
                        return
                    actual=json.loads(o)[0];ram.validate_volume(actual,self.plan)
                    demand(not hasattr(self,'volume_before') or actual.get('Mountpoint')==self.volume_before.get('Mountpoint'),
                           'volume_replaced','Owned volume backing identity changed')
                    self.command('volume','rm',self.plan['volumeName'],closing=True)
                    r,o,e=self.command('volume','inspect',self.plan['volumeName'],checked=False,closing=True)
                    demand(missing_target(r['exitCode'],o,e,'volume',self.plan['volumeName']),'owned_volume_absence','Owned volume remains after removal')
                    self.event('volume_removed',name=self.plan['volumeName']);self.volume_removed=True
                except BaseException as e:faults.append(getattr(e,'kind',type(e).__name__))
        finally:self.room=original_room
        demand(not faults,'owned_cleanup','Exact private resources did not close; retain instance lease and evidence')
        self.closed=True


def verify_owned_graph(value, p, full_capacity):
    probe=value.get('namespaceProbe',{});ram.validate_mount_probe(probe,p,require_capacity=full_capacity)
    demand(probe.get('capacityProbeExecuted') is full_capacity and
           (not full_capacity or 0 < probe.get('capacityBytesWritten',0) <= ram.RAM),
           'capacity_proof','Capacity control/current metadata modes are not interchangeable')
    for field in ('operationOwnerPin','leaseClosurePin','namespaceProbePin'):verify_pin(value[field])
    owner=json.loads(Path(value['operationOwnerPin']['path']).read_bytes());closure=json.loads(Path(value['leaseClosurePin']['path']).read_bytes())
    demand(owner.get('closed') is True and owner.get('volumeRemoved') is True and
           len(owner.get('containers',[]))==2 and all(r.get('state')=='removed' for r in owner['containers']) and
           closure.get('nativeHandleClosed') is True and closure.get('leasePathAbsent') is True,
           'namespace_owned_graph','Actual cold owner/lease/volume closure graph incomplete')
    demand(json.loads(Path(value['namespaceProbePin']['path']).read_bytes())==probe,'namespace_probe_pin','Cold measured namespace bytes differ')
    demand(owner.get('ownerLabelKey')==ram.LABEL and owner.get('ownerLabelValue')==p['nonce'] and
           closure.get('nonce')==owner['lease']['nonce'] and closure.get('pid')==owner.get('processId') and
           closure.get('ownerNonce')==p['nonce'] and closure.get('fixtureOnly') is False and
           closure.get('nativeDeleteByOwnedHandleReturned') is True,'namespace_lease_graph','Cold native actor/nonce/delete graph differs')
    verify_pin(closure['finalLeaseBytesPin']);lease=json.loads(Path(closure['finalLeaseBytesPin']['path']).read_bytes())
    demand(lease.get('nonce')==closure['nonce'] and lease.get('pid')==closure['pid'] and lease.get('held') is False and
           lease.get('ownerNonce')==p['nonce'] and lease.get('fixtureOnly') is False,'namespace_lease_bytes','Cold actual final lease bytes differ')
    records=[]
    pins=[value['operationOwnerPin'],value['leaseClosurePin'],value['namespaceProbePin'],closure['finalLeaseBytesPin']]
    verify_pin(owner['ownerEventsPin']);pins.append(owner['ownerEventsPin'])
    event_raw=Path(owner['ownerEventsPin']['path']).read_bytes()
    demand(event_raw.endswith(b'\n'),'owner_chain','Owner intent journal has an incomplete tail')
    events,pending,known=parse_owner_rows(event_raw,owner['processId'],owner['operationNonce'],value.get('sourcePins'),p,closure['leasePath'])
    demand(events and events[0].get('kind')=='instance_lease_acquired' and events[0].get('nonce')==closure['nonce'] and
           owner.get('sourcePins')==value.get('sourcePins'),'owner_source_graph','Owned lease/source chain differs')
    for q in owner.get('commandRecordPins',[]):
        verify_pin(q);row=json.loads(Path(q['path']).read_bytes());verify_pin(row['stdoutPin']);verify_pin(row['stderrPin'])
        demand(row.get('directChildWaitReturned') is True and row.get('pipeReadersClosed') is True and
               row.get('captureFsyncReturned') is True and row.get('faults')==[], 'namespace_command_closure','Cold raw command/child capture not closed')
        records.append(row)
        verify_pin(row['intentPin']);verify_pin(row['childPin'])
        intent=json.loads(Path(row['intentPin']['path']).read_bytes());child=json.loads(Path(row['childPin']['path']).read_bytes())
        demand(intent.get('protocol')==PROTOCOL+'-native-command-intent' and child.get('protocol')==PROTOCOL+'-native-command-child' and
               child.get('intentPin')==row['intentPin'] and intent.get('ownerPid')==child.get('ownerPid')==owner['processId'] and
               intent.get('argvSha256')==child.get('argvSha256')==row['argvSha256'] and child.get('childPid')==row['pid'],
               'native_command_identity','Actual pre-spawn/direct-child source/owner/PID graph differs')
        pins += [q,row['stdoutPin'],row['stderrPin']]
        pins += [row['intentPin'],row['childPin']]
    demand(1<=len(records)<=64,'namespace_raw_graph','Cold raw command graph missing')
    def matching(args):
        digest=hashlib.sha256(canonical([str(DOCKER),'--host',DOCKER_HOST,*args])).hexdigest()
        return [r for r in records if r.get('argvSha256')==digest]
    infos=matching(['info','--format','{{json .}}'])
    demand(len(infos)==1 and infos[0]['exitCode']==0,'namespace_daemon_raw','Exact local daemon raw identity missing')
    daemon=json.loads(Path(infos[0]['stdoutPin']['path']).read_bytes())
    demand({k:daemon.get(k) for k in ('ID','Name','OSType','Driver','ServerVersion','MemTotal','NCPU')}==value.get('dockerDaemon'),
           'namespace_daemon_raw','Daemon summary differs from actual raw response')
    for role in ('grader','seeder'):
        r=next((r for r in owner['containers'] if r.get('role')==role),None)
        demand(r and re.fullmatch('[0-9a-f]{64}',r.get('containerId','')),'namespace_cid','Cold exact container ID missing')
        cid=r['containerId'];inspections=matching(['container','inspect','--size',cid])
        demand(role in known and known[role]['containerId']==cid,'namespace_intent_cid','Final owned CID differs from original create/identity journal')
        demand(bool(inspections),'namespace_inspect_raw','Actual exact role inspect raw missing')
        for record in inspections:
            actual=json.loads(Path(record['stdoutPin']['path']).read_bytes())[0];ram.validate_container(actual,p,seeder=role=='seeder')
            demand(actual['Id']==cid and actual['State']['Running'] is True,'namespace_inspect_raw','Actual cold role ID/state differs')
        demand(any(r['exitCode']==0 for r in matching(['rm','-f',cid])) and
               any(missing_target(r['exitCode'],Path(r['stdoutPin']['path']).read_bytes(),Path(r['stderrPin']['path']).read_bytes(),'container',cid)
                   for r in matching(['container','inspect',cid])),
               'namespace_removed_raw','Fresh exact container removal+absence raw missing')
    cold_probe=matching(['exec',next(r['containerId'] for r in owner['containers'] if r['role']=='grader'),
                         '/usr/bin/python3.12','-I','-B','-c',mount_probe_code(p,full_capacity)])
    demand(len(cold_probe)==1 and cold_probe[0]['exitCode']==0,'namespace_probe_raw','Exact source-bound capacity command missing')
    measured=json.loads(Path(cold_probe[0]['stdoutPin']['path']).read_bytes())
    demand(all(probe.get(k)==v for k,v in measured.items()),'namespace_probe_raw','Measured raw facts differ from namespace report')
    seeder_probe=matching(['exec',next(r['containerId'] for r in owner['containers'] if r['role']=='seeder'),
                           '/usr/bin/python3.12','-I','-B','-c',seeder_kernel_code()])
    demand(len(seeder_probe)==1 and seeder_probe[0]['exitCode']==0,'namespace_seeder_kernel','Actual distinct seeder kernel mounts not measured')
    kernel=json.loads(Path(seeder_probe[0]['stdoutPin']['path']).read_bytes())
    demand(kernel==probe.get('seederKernelMounts') and type(kernel.get('devBytes')) is int and
           0<=kernel['devBytes']<=p['perRoleDevTmpfsMaximumBytes'] and kernel.get('shmBytes')==ram.SHM,
           'namespace_seeder_kernel','Seeder RAM reservation differs from actual source-bound raw')
    demand(any(r['exitCode']==0 for r in matching(['volume','rm',p['volumeName']])) and
           any(missing_target(r['exitCode'],Path(r['stdoutPin']['path']).read_bytes(),Path(r['stderrPin']['path']).read_bytes(),'volume',p['volumeName'])
               for r in matching(['volume','inspect',p['volumeName']])), 'namespace_volume_raw','Actual exact volume rm/absence raw missing')
    return {'owner':owner,'commands':records,'inputPins':pins,'matching':matching}


def verify_namespace_proof(value, sources, descriptor_pin, p):
    demand(value.get('executorProtocol')==PROTOCOL and value.get('namespaceValidated') is True and value.get('validated') is False and
           value.get('formalLlmClosedLoopValidated') is False and value.get('ownedClosed') is True and
           value.get('sourcePins')==sources and value.get('descriptorPin')==descriptor_pin and value.get('ramProfileSourceSha256')==p['sourceSha256'],
           'namespace_proof','New source-bound actual cold namespace closure is required')
    verify_owned_graph(value,p,True)
    return value


def validate_namespace_proof(proof_pin, plan_value, descriptor_value, client_pin):
    """Public read-only new entry/auditor ABI; never creates D or calls Docker."""
    verify_pin(proof_pin);verify_pin(client_pin);storage.validate_descriptor(descriptor_value);ram.validate_plan(plan_value)
    demand(Path(client_pin['path'])==DOCKER,'docker_client','Only fixed actual Docker executable Pin admitted')
    value=json.loads(Path(proof_pin['path']).read_bytes());dp=value.get('descriptorPin')
    verify_pin(dp)
    cold_descriptor=json.loads(Path(dp['path']).read_bytes());storage.validate_descriptor(cold_descriptor)
    cold_plan_pin=value.get('ramPlanPin');verify_pin(cold_plan_pin)
    cold_plan=json.loads(Path(cold_plan_pin['path']).read_bytes());ram.validate_plan(cold_plan)
    demand(cold_plan['nonce']==cold_descriptor['ownerNonce'] and plan_value['nonce']==descriptor_value['ownerNonce'] and
           cold_plan['sourceSha256']==plan_value['sourceSha256'],
           'namespace_policy','Cold and new fresh owners must derive the same exact source-bound capacity/mount policy')
    demand(value.get('dockerClientPin')==client_pin,'namespace_client','Cold Docker client Pin differs')
    # The capability certificate keeps its original nonce/CIDs/raw bytes. Each
    # new grade measures a new namespace; old IDs never enter its owned graph.
    return verify_namespace_proof(value,source_pins(),dp,cold_plan)


def validate_grade_report(recipe, report_pin):
    """Read-only scorer auditor seam. CLI actor closure remains a separate join.

    No old scoring certificate or fixture boolean admits this new RAM protocol.
    New entry must additionally certify its actual helper exit/close and fresh
    daemon/PID absence. This function performs no subprocess/Docker/DB access.
    """
    verify_pin(report_pin);v=json.loads(Path(report_pin['path']).read_bytes())
    demand(v.get('protocol')=='skb-jpg-output-v1-preseed' and v.get('executorProtocol')==PROTOCOL and
           v.get('taskId')=='jpg-ocr-stat' and v.get('imageId')==ram.IMAGE and v.get('validated') is True and
           v.get('officialGradingValid') is True and v.get('formalLlmClosedLoopValidated') is False and
           v.get('ownedClosed') is True and v.get('sourcePins')==source_pins() and v.get('graderSourceSha256')==pin(__file__)['sha256'],
           'grade_report','New actual source-bound official verdict+private closure missing')
    d=recipe['DStorage']
    for q in recipe['gates'].values():verify_pin(q)
    for field,key in (('descriptorPin','descriptorPin'),('ramPlanPin','ramPlanPin'),('namespaceProofPin','namespaceProofPin'),('dockerClientPin','dockerClientPin')):
        verify_pin(d[key]);demand(v.get(field)==d[key],'grade_recipe_graph','Private report input differs from reviewed recipe')
    value=json.loads(Path(d['descriptorPin']['path']).read_bytes());p=json.loads(Path(d['ramPlanPin']['path']).read_bytes())
    storage.validate_descriptor(value);ram.validate_plan(p)
    validate_namespace_proof(d['namespaceProofPin'],p,value,d['dockerClientPin'])
    graph=verify_owned_graph(v,p,False);official=official_module()
    capture_pin=v['captureReceiptPin'];verify_pin(capture_pin);capture=json.loads(Path(capture_pin['path']).read_bytes())
    artifact=capture_input(capture,value);verdict=v.get('candidateVerdict',{})
    folder=Path(report_pin['path']).parent
    demand(folder.parent==Path(value['directories']['private-logs']) and re.fullmatch('grade-[0-9a-f]{32}',folder.name),
           'grade_namespace','Actual grade evidence is outside reviewed D-only owner')
    rewards={}
    cid=next(r['containerId'] for r in graph['owner']['containers'] if r['role']=='grader')
    for name in ('reward.txt','ctrf.json','dependency-versions.json'):
        q=pin(folder/name);graph['inputPins'].append(q);raw=Path(q['path']).read_bytes()
        records=graph['matching'](['cp',cid+':/logs/verifier/'+name,'-'])
        demand(len(records)==1 and records[0]['exitCode']==0 and exact_tar_file(Path(records[0]['stdoutPin']['path']).read_bytes(),name,512*1024)==raw,
               'grade_report_transfer','Raw daemon report transfer does not match durable accepted bytes')
        rewards[name]=raw
    deps,assets=official.require_dependencies(Path(recipe['gates']['profile']['path']),ram.IMAGE)
    demand(v['dependencyProfileSha256']==recipe['gates']['profile']['sha256'] and v['originalSourceHashes']==official.sources(),
           'grade_official_input','Exact official/dependency source graph differs')
    accepted=official.accepted_result(rewards['reward.txt'].decode('utf8'),json.loads(rewards['ctrf.json']),
                                     json.loads(rewards['dependency-versions.json']),deps,pin(assets['uv'])['sha256'])
    demand(all(verdict.get(k)==x for k,x in accepted.items()) and verdict.get('artifactSha256')==(artifact['sha256'] if artifact else None) and
           verdict.get('imageId')==ram.IMAGE and verdict.get('candidateSnapshotUsed') is False and verdict.get('candidateExecutablesUsed') is False and
           verdict.get('hostBinds') is False and verdict.get('graderNetwork')=='none' and verdict.get('privateReadOnlyRootfs') is True and
           verdict.get('sharedRamMaximumBytes')==ram.RAM and verdict.get('executorProtocol')==PROTOCOL,
           'grade_official_result','Exact one-test/interpreter/artifact verdict differs')
    demand(any(r['exitCode']==0 for r in graph['matching'](['exec',cid,'/bin/bash','/verifier/test.sh'])),
           'official_exec_raw','Original official test was not completed by the actual fixed exec command')
    return {'containerIds':[r['containerId'] for r in graph['owner']['containers']],
            'commandChildPids':[r['pid'] for r in graph['commands']],
            'volumeNames':[p['volumeName']],'inputPins':graph['inputPins']+[report_pin,capture_pin,*source_pins(),
                 *[x for x in d.values() if isinstance(x,dict) and 'path' in x and 'sha256' in x]],
            'operationOwnerPin':v['operationOwnerPin'],'cliPin':None,'reportPin':report_pin,
            'cliActorClosureRequired':True,'formalScoreCertified':False}


def recover_owned_after_child_exit(output, actual_pid, recipe):
    """Explicit parent timeout recovery; not a score/paid-lock release function.

    No implicit retry or original-evidence edit. Refuses a live/reused PID,
    incomplete owner journal, drifted source or substituted resource. A new
    small D directory stores exact cleanup/native closure; original bytes stay.
    """
    absent=storage.native_actor_absent(actual_pid)
    d=recipe['DStorage']
    for field in ('descriptorPin','ramPlanPin','dockerClientPin'):verify_pin(d[field])
    value=json.loads(Path(d['descriptorPin']['path']).read_bytes());p=json.loads(Path(d['ramPlanPin']['path']).read_bytes())
    storage.validate_descriptor(value);ram.validate_plan(p);before=source_pins()
    for q in before:demand(any(r.get('path')==q['path'] and r.get('sha256')==q['sha256'] and r.get('bytes')==q['bytes'] for r in recipe['sourcePins']),
                           'recovery_source','Actual timeout source is outside immutable recipe')
    old=Path(output);demand(old.parent==Path(value['directories']['private-logs']) and re.fullmatch('grade-[0-9a-f]{32}',old.name),
                            'recovery_namespace','Only the exact new D private grade may be recovered')
    storage.ordinary(old,Path(value['storePhysical']))
    journal_pin=pin(old/'owner-events.jsonl');raw=Path(journal_pin['path']).read_bytes()
    demand(len(raw)<=256*1024 and raw.endswith(b'\n'),'recovery_owner_tail','Unknown/incomplete owner dispatch tail; preserve for Root manual review')
    rows,pending,known=parse_owner_rows(raw,actual_pid,old.name[6:],before,p,Path(value['directories']['leases'])/'instance.lock')
    storage.native_actor_absent(actual_pid);verify_pin(journal_pin)
    # Recovery never copies old captures/outputs or adds a new grading attempt.
    initial=storage.observe_owned_store(value)
    demand(initial['allocatedEnvelopeBytes']+16*1024**2<=storage.STORE_CAP and initial['volumeFreeBytes']['D']>=storage.D_MIN+16*1024**2,
           'recovery_storage','Cannot preserve bounded cleanup at the original D cap/reserve')
    new=Path(value['directories']['private-logs'])/('grade-'+uuid.uuid4().hex);new.mkdir()
    operation=RamOperation(value,p,new,before,d['dockerClientPin']['sha256'],recipe)
    operation.pending=pending;operation.identities=known
    # Native lease adoption preserves exact old bytes and first verifies absence.
    operation.lease=storage.adopt_exited_instance(value,old.name[6:],actual_pid,new)
    operation.event('explicit_timeout_recovery',originalOwnerJournalPin=journal_pin,originalActorPid=actual_pid,actualAbsence=absent)
    try:
        storage.native_actor_absent(actual_pid);operation.cleanup();stable_sources(before);verify_pin(journal_pin)
        command_actor_evidence=[]
        for intent_file in sorted(old.glob('command-*.intent.json')):
            intent_pin=pin(intent_file);intent=json.loads(intent_file.read_bytes())
            demand(intent.get('ownerPid')==actual_pid and intent.get('protocol')==PROTOCOL+'-native-command-intent',
                   'timeout_command_owner','Original direct-command actor differs')
            child_file=intent_file.with_name(intent_file.name.replace('.intent.json','.child.json'))
            demand(child_file.is_file(),'timeout_command_unknown','Unrecorded spawn outcome; daemon cleaned but native closure unknown, retain lease')
            child_pin=pin(child_file);child=json.loads(child_file.read_bytes())
            demand(child.get('intentPin')==intent_pin and child.get('ownerPid')==actual_pid and child.get('argvSha256')==intent.get('argvSha256'),
                   'timeout_command_owner','Direct child receipt is not this exact prior command')
            command_actor_evidence.append({'intentPin':intent_pin,'childPin':child_pin,'actualAbsence':storage.native_actor_absent(child['childPid'])})
        lease_pin=operation.lease.release()
        owner={'protocol':PROTOCOL+'-timeout-owner','originalActorPid':actual_pid,'processId':os.getpid(),
               'containers':list(operation.identities.values()),'volumeName':p['volumeName'],'volumeRemoved':getattr(operation,'volume_removed',False),
               'commandRecordPins':operation.command_records,'leaseClosurePin':lease_pin,'originalOwnerJournalPin':journal_pin,
               'originalCommandActorAbsence':command_actor_evidence,
               'closed':operation.closed,'sourcePins':before,'originalEvidenceUnchanged':True}
        owner_pin=fresh_bytes(new/'operation-owner.json',canonical(owner),new)
        result={'protocol':PROTOCOL+'-timeout-recovery','status':'owned_timeout_closed_no_score','originalActorPid':actual_pid,
                'actualAbsence':storage.native_actor_absent(actual_pid),'originalOwnerJournalPin':journal_pin,'operationOwnerPin':owner_pin,
                'leaseClosurePin':lease_pin,'sourcePins':before,'closed':True,'validated':False,'formalScoreCertified':False,
                'originalCommandActorAbsence':command_actor_evidence,
                'paidLockReleased':False,'gradingRetried':False,'modelCalls':0}
        return fresh_bytes(new/'recovery.json',canonical(result),new)
    except BaseException:
        operation.lease.retain_after_failure();raise


def main():
    parser=argparse.ArgumentParser();mode=parser.add_mutually_exclusive_group()
    mode.add_argument('--grade',action='store_true');mode.add_argument('--namespace-probe',action='store_true')
    mode.add_argument('--verify-namespace-proof',action='store_true')
    for k in ('descriptor','ram-plan','recipe','namespace-proof','capture-receipt'):
        parser.add_argument('--'+k,type=Path);parser.add_argument('--'+k+'-sha256')
    parser.add_argument('--docker-client-sha256');parser.add_argument('--output',type=Path)
    parser.add_argument('--phase',choices=('feedback','final','control'),default='final')
    a=parser.parse_args()
    if not a.grade and not a.namespace_probe and not a.verify_namespace_proof:
        print(json.dumps({'executorProtocol':PROTOCOL,'preparedOnly':True,'modelCalls':0,'DockerMutations':0,'actualReady':False}));return
    demand(os.name=='nt' and sys.dont_write_bytecode,'native_host','Native Windows Python -B required')
    demand(all((a.descriptor,a.descriptor_sha256,a.ram_plan,a.ram_plan_sha256,a.docker_client_sha256)),
           'explicit_pins','Explicit reviewed descriptor/plan/client Pins required')
    value,dp=pinned_json(a.descriptor,a.descriptor_sha256);storage.validate_descriptor(value)
    p,rp=pinned_json(a.ram_plan,a.ram_plan_sha256);ram.validate_plan(p)
    demand(p['nonce']==value['ownerNonce'],'ram_owner','RAM plan is not this exact D owner')
    if a.verify_namespace_proof:
        demand(a.namespace_proof and a.namespace_proof_sha256,'namespace_proof','Explicit closed actual namespace proof required')
        _,np=pinned_json(a.namespace_proof,a.namespace_proof_sha256)
        demand(pin(DOCKER)['sha256']==a.docker_client_sha256,'docker_client','Reviewed Docker client Pin differs')
        verified=validate_namespace_proof(np,p,value,pin(DOCKER))
        print(json.dumps({'protocol':PROTOCOL+'-readonly-proof-verification','namespaceProofPin':np,'nativeNamespaceGraphVerified':True,
                          'actualHelperActorAbsenceRequired':True,'formalScoreCertified':False,'DockerMutations':0,'modelCalls':0}));return
    demand(all((a.recipe,a.recipe_sha256,a.output)), 'explicit_pins', 'Reviewed recipe and fresh actual output required')
    recipe,recipe_pin=pinned_json(a.recipe,a.recipe_sha256);before=source_pins()
    ds=recipe.get('DStorage',{})
    demand(ds.get('descriptorPin')==dp and ds.get('ramPlanPin')==rp and ds.get('dockerClientPin')==pin(DOCKER),
           'recipe_D_graph','Caller inputs differ from immutable new D recipe')
    for required in before:
        demand(any(q.get('path')==required['path'] and q.get('sha256')==required['sha256'] and q.get('bytes')==required['bytes'] for q in recipe.get('sourcePins',[])),
               'recipe_source_graph','Recipe does not freeze the actual complete private executor source set')
    official=official_module();original=official.sources()
    for item in recipe['gates'].values():verify_pin(item)
    manifest=json.loads(Path(recipe['gates']['image']['path']).read_bytes());build=json.loads(Path(recipe['gates']['build']['path']).read_bytes())
    image=official.require_build(manifest,build,original);demand(image==ram.IMAGE,'image_pin','Only exact original928 image admitted')
    deps,assets=official.require_dependencies(Path(recipe['gates']['profile']['path']),image)
    deps_before=[pin(path) for path in assets.values()]
    for path in assets.values():demand(path.lstat().st_nlink==1,'dependency_hardlink','Trusted dependency aliased')
    capture,capture_pin,artifact=None,None,None
    namespace,namespace_pin=None,None
    if a.grade:
        demand(all((a.capture_receipt,a.capture_receipt_sha256,a.namespace_proof,a.namespace_proof_sha256)),
               'grade_inputs','Protected capture and actual new namespace proof are mandatory')
        capture,capture_pin=pinned_json(a.capture_receipt,a.capture_receipt_sha256)
        storage.ordinary(a.capture_receipt.parent,Path(value['storePhysical']));artifact=capture_input(capture,value)
        namespace,namespace_pin=pinned_json(a.namespace_proof,a.namespace_proof_sha256)
        demand(ds.get('namespaceProofPin')==namespace_pin,'recipe_namespace_graph','Caller namespace proof differs from immutable recipe')
        namespace=validate_namespace_proof(namespace_pin,p,value,pin(DOCKER))
    output=Path(os.path.abspath(a.output));base=Path(value['directories']['private-logs'])
    demand(output.parent==base and re.fullmatch('grade-[0-9a-f]{32}',output.name),'output_namespace','Fresh fixed D/private-logs/grade-32hex required')
    storage.ordinary(base,Path(value['storePhysical']));demand(not os.path.lexists(output),'fresh_output','Prior output cannot be reused')
    # Reserve worst one-operation evidence, independently of parent producer budgets.
    initial=storage.observe_owned_store(value);demand(initial['allocatedEnvelopeBytes']+OP_CAP<=storage.STORE_CAP and
           initial['volumeFreeBytes']['D']>=storage.D_MIN+OP_CAP,'operation_reservation','Cannot reserve96MiB evidence inside D3GiB cap/floor')
    output.mkdir()
    operation=None;fault=None;result=None;probe=None;lease_pin=None
    report={'protocol':official.PROTOCOL,'executorProtocol':PROTOCOL,'taskId':official.TASK_ID,'denominator':87,
            'implementedTaskIds':[official.TASK_ID],'unsupportedTaskCount':86,'validated':False,'officialGradingValid':False,
            'formalLlmClosedLoopValidated':False,'graderSourceSha256':before[0]['sha256'],'sourcePins':before,'imageId':image,
            'descriptorPin':dp,'ramPlanPin':rp,'ramProfileSourceSha256':p['sourceSha256'],'recipePin':recipe_pin,
            'namespaceProofPin':namespace_pin,'captureReceiptPin':capture_pin,'captureReceiptSha256':capture_pin['sha256'] if capture_pin else None,
            'dockerClientPin':pin(DOCKER),'imageManifestSha256':recipe['gates']['image']['sha256'],'buildProofSha256':recipe['gates']['build']['sha256'],
            'dependencyProfileSha256':recipe['gates']['profile']['sha256'],'originalSourceHashes':original,
            'namespaceValidated':False,'ownedClosed':False,'phase':'namespace' if a.namespace_probe else a.phase,
            'modelCalls':0,'llmRequests':0,'imagePulls':0,'imageBuilds':0}
    try:
        operation=RamOperation(value,p,output,before,a.docker_client_sha256,recipe,capture.get('ownedContainerID') if capture else None)
        operation.begin();operation.make()
        if namespace:demand(operation.daemon==namespace['dockerDaemon'],'daemon_changed','Actual Engine differs from cold namespace proof')
        probe=operation.probe(a.namespace_probe)
        if namespace:demand(probe['basePythonSha256']==namespace['namespaceProbe']['basePythonSha256'],
                            'base_python_changed','Actual immutable base interpreter differs from source-bound cold capability')
        if a.grade:
            inputs=[]
            for name in ('test.sh','test_outputs.py','stat_oracle.xlsx'):
                inputs.append(operation.copy(official.TASK/'verifier'/name,'/verifier/'+name))
            for name,path in assets.items():
                target='/root/.local/bin/'+name if name in ('uv','uvx') else '/verifier-wheels/'+path.name
                inputs.append(operation.copy(path,target))
            env_path=output/'env';fresh_bytes(env_path,b'export PATH="$HOME/.local/bin:$PATH"\n',output)
            cf=output/'conftest.py';fresh_bytes(cf,official.conftest(deps,pin(assets['uv'])['sha256']).encode(),output)
            inputs += [operation.copy(env_path,'/root/.local/bin/env'),operation.copy(cf,'/verifier/conftest.py')]
            cid=operation.identities['grader']['containerId'];operation.command('exec',cid,'/bin/chmod','+x','/root/.local/bin/uv','/root/.local/bin/uvx')
            if artifact:
                verify_pin(artifact);inputs.append(operation.copy(Path(artifact['path']),official.ARTIFACT));verify_pin(artifact)
            verify_code='import hashlib,json,os;paths='+repr(inputs)+';print(json.dumps([{**p,"actualBytes":os.stat(p["path"]).st_size,"actualSha256":hashlib.sha256(open(p["path"],"rb").read()).hexdigest()} for p in paths]))'
            _,raw,_=operation.command('exec',cid,'/usr/bin/python3.12','-I','-B','-c',verify_code)
            actual=json.loads(raw);demand(len(actual)==len(inputs) and all(r['bytes']==r['actualBytes'] and r['sha256']==r['actualSha256'] for r in actual),'seed_copy_identity','Trusted RAM input bytes changed')
            fresh_bytes(output/'ram-input-identity.json',canonical(actual),output)
            operation.command('exec',cid,'/bin/bash','/verifier/test.sh',timeout=OFFICIAL_SECONDS)
            values={}
            for name in ('reward.txt','ctrf.json','dependency-versions.json'):
                _,raw,_=operation.command('cp',cid+':/logs/verifier/'+name,'-')
                body=exact_tar_file(raw,name,512*1024);fresh_bytes(output/name,body,output);values[name]=body
            versions=json.loads(values['dependency-versions.json'])
            result=official.accepted_result(values['reward.txt'].decode('utf8'),json.loads(values['ctrf.json']),versions,deps,pin(assets['uv'])['sha256'])
            demand(versions.get('executable','').startswith(p['trustedUvPythonCachePrefix']),'venv_origin','Private venv was not created in owned trusted RAM cache')
            result.update(imageId=image,originalSourceHashes=original,artifactSha256=artifact['sha256'] if artifact else None,
                          candidateSnapshotUsed=False,candidateExecutablesUsed=False,hostBinds=False,graderNetwork='none',dependencyVersions=versions,
                          executorProtocol=PROTOCOL,privateReadOnlyRootfs=True,sharedRamMaximumBytes=ram.RAM)
            if capture['state']!='regular':
                result.update(artifactCaptureState=capture['state'])
                if capture['state']!='absent':result.update(experimentalFailure=True,outcome='budget_exhausted' if capture['state']=='too_large' else 'invalid_artifact')
            report['candidateVerdict']=result;report['artifactCapture']={'trustedHostCapture':True,'state':capture['state'],'sha256':artifact['sha256'] if artifact else None}
        operation.inspect_roles();stable_sources(before)
        demand(official.sources()==original and [pin(path) for path in assets.values()]==deps_before,'input_drift','Official/dependency bytes changed during operation')
        verify_pin(dp);verify_pin(rp);verify_pin(recipe_pin)
        for item in recipe['gates'].values():verify_pin(item)
        if capture_pin:verify_pin(capture_pin)
    except BaseException as error:fault={'kind':getattr(error,'kind',type(error).__name__),'detail':str(error)[:1000]}
    finally:
        if operation:
            try:
                operation.cleanup();stable_sources(before)
                lease_pin=operation.lease.release()
            except BaseException as e:
                fault={'kind':getattr(e,'kind',type(e).__name__),'detail':str(e)[:1000]}
                operation.lease.retain_after_failure()
            owner={'schemaVersion':2,'protocol':PROTOCOL+'-owner','processId':os.getpid(),'operationNonce':output.name[6:],
                   'ownerLabelKey':ram.LABEL,'ownerLabelValue':p['nonce'],'containers':list(operation.identities.values()),
                   'volumeName':p['volumeName'],'volumeRemoved':getattr(operation,'volume_removed',False),
                   'lease':{'path':str(operation.lease.path),'nonce':operation.lease.nonce,'released':bool(lease_pin)},
                   'leaseClosurePin':lease_pin,'closed':operation.closed and bool(lease_pin),'ownerEventsPin':pin(output/'owner-events.jsonl') if (output/'owner-events.jsonl').exists() else None}
            owner['commandRecordPins']=operation.command_records
            owner['sourcePins']=before
            owner_pin=fresh_bytes(output/'operation-owner.json',canonical(owner),output)
            report.update(operationOwnerPin=owner_pin,ownedClosed=owner['closed'],leaseClosurePin=lease_pin,
                          dockerDaemon=getattr(operation,'daemon',None),resourceSamples=operation.samples,
                          physicalMemory=getattr(operation,'memory',None))
        if probe:
            report['namespaceProbe']=probe;report['namespaceProbePin']=pin(output/('namespace-full-probe.json' if a.namespace_probe else 'namespace-current-probe.json'))
        report['fault']=fault
        report['validated']=bool(a.grade and result and not fault and report['ownedClosed'])
        report['officialGradingValid']=report['validated']
        report['namespaceValidated']=bool(a.namespace_probe and probe and not fault and report['ownedClosed'])
        report['status']='valid_artifact_only_verdict_formal_llm_not_validated' if report['validated'] else 'namespace_closed_no_score' if report['namespaceValidated'] else 'invalid_infrastructure_no_score'
        rp_out=fresh_bytes(output/'report.json',canonical(report),output)
        print(json.dumps({'path':str(output/'report.json'),'reportPin':rp_out,'validated':report['validated'],'namespaceValidated':report['namespaceValidated'],
                          'status':report['status'],'formalLlmClosedLoopValidated':False}))


if __name__=='__main__':main()
