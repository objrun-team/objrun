"""ChemIQ-only read-only host/Docker observations; no creation or termination."""
from datetime import datetime, timezone
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'docs/repair-2026-10-08/chemiq-f-journal-implementation-v2/observations'
CID = '4c334ef1f093e82cf9e26ec06aaf0edd09385212c249e42b9ee7f7b8aae73153'
DOCKER = 'D:/Program/resources/bin/docker.exe'

def utc():
    return datetime.now(timezone.utc).isoformat()

def save(label, value):
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / (label + '-' + utc().replace(':', '-').replace('.', '-') + '.json')
    raw = (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode('utf-8')
    with path.open('xb') as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    if path.read_bytes() != raw:
        raise RuntimeError('Observation readback mismatch')
    result = {'path': str(path), 'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest()}
    print(json.dumps({**result, 'summary': value.get('summary')}, ensure_ascii=False))
    return result

def resources():
    class Memory(ctypes.Structure):
        _fields_ = [('length', ctypes.c_ulong), ('load', ctypes.c_ulong)] + [(key, ctypes.c_ulonglong) for key in ['totalPhys','availPhys','totalPageFile','availPageFile','totalVirtual','availVirtual','availExtendedVirtual']]
    frame = Memory()
    frame.length = ctypes.sizeof(frame)
    ok = bool(ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(frame)))
    disks = {drive: dict(zip(('total','used','free'), shutil.disk_usage(drive + ':/'))) for drive in ['C','D','F']}
    lock = ROOT / '.phase1-data/owned-paid-campaign.lock.json'
    row = json.loads(lock.read_text(encoding='utf-8-sig')) if lock.exists() else None
    value = {'protocol': 'chemiq-host-resource-observation-v2', 'observedAtUtc': utc(), 'modelCalls': 0,
        'disks': disks, 'memory': {'valid': ok, 'totalPhysical': frame.totalPhys, 'availablePhysical': frame.availPhys},
        'canonicalLock': {'present': lock.exists(), 'owner': row}, 'thresholds': {'diskFloorBytes': 1024**3, 'recommendedCBytes': int(1.3*1024**3)},
        'summary': {'cFreeBytes': disks['C']['free'], 'cDiskFloorPassed': disks['C']['free'] >= 1024**3, 'availableMemoryBytes': frame.availPhys, 'canonicalLockPresent': lock.exists()}}
    save('resources', value)

def inspect():
    started = utc()
    result = subprocess.run([DOCKER, '-H', 'npipe:////./pipe/dockerDesktopLinuxEngine', 'inspect', CID], capture_output=True, text=True, encoding='utf-8', timeout=30)
    if result.returncode:
        save('private-inspect-failure', {'protocol': 'chemiq-private-inspect-failure-v2', 'startedAtUtc': started, 'observedAtUtc': utc(), 'containerId': CID,
            'status': result.returncode, 'stderr': result.stderr, 'modelCalls': 0, 'summary': {'success': False, 'status': result.returncode}})
        return
    raw = result.stdout
    row = json.loads(raw)[0]
    env = row.get('Config', {}).get('Env') or []
    env_records = []
    for item in env:
        key, _, val = item.partition('=')
        public = key.startswith('TGENGIN_CHEMIQ_') or key in {'PATH','PYTHONPATH','PYTHONDONTWRITEBYTECODE','PYTHON_VERSION','LANG','PYTHONUNBUFFERED'}
        env_records.append(key + '=' + (val if public else '[redacted:' + hashlib.sha256(val.encode()).hexdigest() + ']'))
    row['Config']['Env'] = env_records
    value = {'protocol': 'chemiq-private-inspect-observation-v2', 'startedAtUtc': started, 'observedAtUtc': utc(), 'modelCalls': 0,
        'containerId': CID, 'rawInspectSha256': hashlib.sha256(raw.encode()).hexdigest(), 'nonpublicEnvironmentValuesRedacted': True,
        'inspect': row, 'summary': {'success': True, 'containerId': row['Id'], 'imageId': row['Image'], 'running': row['State']['Running'],
        'networkMode': row['HostConfig']['NetworkMode'], 'readonlyRootfs': row['HostConfig']['ReadonlyRootfs'], 'privileged': row['HostConfig']['Privileged'],
        'pidMode': row['HostConfig']['PidMode'], 'published': row['NetworkSettings']['Ports'],
        'mounts': [{'source':m['Source'],'destination':m['Destination'],'rw':m['RW']} for m in row['Mounts']]}}
    save('private-inspect', value)

def bridge():
    frozen = json.loads((ROOT / '.local-evidence/repository/test/fixtures/repair/chemiq-nextwave-grader-provenance.json').read_bytes())
    prior = frozen['host_bridge']
    process = prior['process']
    pid = int(process['ProcessId'])
    command = "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[Text.UTF8Encoding]::new($false); Get-CimInstance Win32_Process -Filter 'ProcessId=" + str(pid) + "' | Select-Object ProcessId,ExecutablePath,CommandLine,CreationDate | ConvertTo-Json -Compress"
    result = subprocess.run(['C:/Windows/System32/WindowsPowerShell/v1.0/powershell.exe','-NoProfile','-NonInteractive','-Command',command], capture_output=True, text=True, encoding='utf-8', timeout=20)
    if result.returncode or result.stderr.strip():
        save('bridge-observation-failure', {'protocol':'chemiq-bridge-observation-failure-v2','modelCalls':0,'status':result.returncode,'stderr':result.stderr,'observedAtUtc':utc(),'summary':{'valid':False}})
        return
    actual = json.loads(result.stdout)
    queue = ROOT / 'docs/repair-2026-10-08/legacy-opsin-bridge'
    status = json.loads((queue / 'status.json').read_bytes())
    profile = json.loads((queue / 'profile.json').read_bytes())
    assert actual['ProcessId'] == status['pid'] == pid and not status.get('stopped') and time.time()-status['heartbeat'] < 30
    assert actual['CommandLine'] == process['CommandLine']
    assert Path(actual['ExecutablePath']).resolve() == Path(process['ExecutablePath']).resolve()
    def pin(path):
        path = Path(path).resolve()
        raw = path.read_bytes()
        return {'path':str(path),'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()}
    pins = {name:pin(prior[field]['path']) for name,field in [('processSourcePin','script'),('javaPin','java_executable'),('pythonPin','python_executable')]}
    for name, field in [('processSourcePin','script'),('javaPin','java_executable'),('pythonPin','python_executable')]:
        assert pins[name]['sha256'] == prior[field]['sha256']
    pins['jarPin'] = pin(frozen['opsin_jar']['path'])
    assert pins['jarPin']['sha256'] == 'd25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab'
    java = subprocess.run([pins['javaPin']['path'],'-version'], capture_output=True, text=True, encoding='utf-8', timeout=20, check=True)
    assert (java.stdout + java.stderr).strip() == profile['java_version']
    save('bridge-observation', {'protocol':'chemiq-private-host-bridge-observation-v2','observedAtUtc':utc(),'observedUnixSeconds':time.time(),'modelCalls':0,'validated':True,
        'actualPid':pid,'actualProcess':actual,'status':status,'profile':profile,**pins,'summary':{'valid':True,'actualPid':pid,'javaPinned':True,'legacyQueuePreserved':True}})

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['resources','inspect','bridge'])
    mode = parser.parse_args().mode
    {'resources':resources,'inspect':inspect,'bridge':bridge}[mode]()
