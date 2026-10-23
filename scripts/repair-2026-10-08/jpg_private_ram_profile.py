"""Pure plan/validators for one shared512MiB private RAM volume. No Docker run.

Volume-subpath support, mount backing, immutable base Python, capacity and full
official controls remain actual Root preconditions. No fixture certifies them.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re

PROTOCOL = 'jpg-private-original-image-shared-ram-v1'
IMAGE = 'sha256:92892771245d31d0b1af4a0c603effbdaf02bf62c1c055081f44a462f5261ced'
RAM = 512 * 1024**2
MEMORY = 4096 * 1024**2
SHM = 8 * 1024**2
SEEDER_MEMORY = 256 * 1024**2
MOUNTS = {'/root': 'home', '/app/workspace': 'workspace', '/verifier': 'tests',
          '/verifier-wheels': 'wheels', '/logs': 'logs', '/tmp': 'tmp'}
LABEL = 'objrun.jpg.private-ram-owner'
OPTIONS = {'type': 'tmpfs', 'device': 'tmpfs', 'o': 'size=536870912,mode=0700,nosuid,nodev'}
ENV = {'HOME': '/root', 'PATH': '/root/.local/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin',
       'UV_OFFLINE': '1', 'UV_FIND_LINKS': '/verifier-wheels', 'UV_PYTHON_DOWNLOADS': 'never',
       'UV_NO_CONFIG': '1', 'UV_PYTHON': '/usr/bin/python3.12', 'UV_CACHE_DIR': '/root/.cache/uv',
       'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONNOUSERSITE': '1', 'PYTHONPATH': '', 'PYTHONSTARTUP': '',
       'PYTHONHOME': '', 'LD_PRELOAD': '', 'LD_LIBRARY_PATH': '', 'LC_ALL': 'C.UTF-8',
       'TEMP': '/tmp', 'TMP': '/tmp', 'TMPDIR': '/tmp'}


class RamFault(RuntimeError):
    def __init__(self, kind, detail): super().__init__(detail); self.kind = kind


def require(value, kind, detail):
    if not value: raise RamFault(kind, detail)


def plan(nonce):
    require(isinstance(nonce, str) and re.fullmatch('[0-9a-f]{32}', nonce), 'nonce', 'Exact fresh32-hex nonce required')
    volume = 'objrun-jpg-ram-' + nonce
    shared = ['--pull', 'never', '--label', LABEL + '=' + nonce, '--read-only', '--network', 'none',
              '--log-driver', 'none', '--user', '0:0',
              '--memory-swap', str(MEMORY), '--cpus', '4', '--shm-size', str(SHM),
              '--cap-drop', 'ALL', '--security-opt', 'no-new-privileges', '--workdir', '/app/workspace',
              '--entrypoint', '/bin/bash']
    create = ['create', '--name', 'objrun-jpg-private-' + nonce, *shared, '--memory', str(MEMORY)]
    for target, subpath in MOUNTS.items():
        create += ['--mount', 'type=volume,source=' + volume + ',target=' + target + ',volume-subpath=' + subpath + ',volume-nocopy']
    for name, value in ENV.items(): create += ['--env', name + '=' + value]
    create += [IMAGE, '-c', 'exec /bin/sleep infinity']
    seeder = ['create', '--pull', 'never', '--name', 'objrun-jpg-ram-seeder-' + nonce,
              '--label', LABEL + '=' + nonce, '--read-only', '--network', 'none', '--memory', str(SEEDER_MEMORY),
              '--log-driver', 'none', '--user', '0:0',
              '--memory-swap', str(SEEDER_MEMORY), '--cpus', '1', '--shm-size', str(SHM), '--cap-drop', 'ALL',
              '--security-opt', 'no-new-privileges', '--workdir', '/', '--entrypoint', '/bin/bash',
              '--mount', 'type=volume,source=' + volume + ',target=/objrun,volume-nocopy', IMAGE, '-c',
              'set -e; mkdir -p /objrun/home/.local/bin /objrun/home/.cache/uv /objrun/workspace /objrun/tests /objrun/wheels /objrun/logs/verifier /objrun/tmp; exec /bin/sleep infinity']
    return {'protocol': PROTOCOL, 'nonce': nonce, 'imageId': IMAGE, 'volumeName': volume,
        'volumeCreate': ['volume', 'create', '--driver', 'local', '--label', LABEL + '=' + nonce,
                         '--opt', 'type=tmpfs', '--opt', 'device=tmpfs', '--opt', OPTIONS['o'], volume],
        'seederCreate': seeder, 'graderCreate': create, 'mountSubpaths': dict(MOUNTS),
        'trustedBasePythonPath': '/usr/bin/python3.12', 'trustedPythonVersion': '3.12.3',
        'trustedUvPythonCachePrefix': '/root/.cache/uv/archive-v0/', 'hostBinds': [],
        'privateEnvironment': dict(ENV), 'privateMemoryBytes': MEMORY, 'privateCPUs': 4,
        'privateSharedRamMaximumBytes': RAM, 'sharedMemoryBytesEachRole': SHM,
        'seederMemoryMaximumBytes': SEEDER_MEMORY, 'officialVerifierSeconds': 600,
        'volumeLifetime': 'Seeder stays alive until grader removed and all D outputs fsync/readback; remove seeder then exact owned volume.',
        'writes': {'uvExecutableAndEnv': '/root/.local/bin', 'uvVirtualEnvironments': '/root/.cache/uv',
                   'candidateOnlyXlsx': '/app/workspace/stat_ocr.xlsx', 'trustedTestsAndGT': '/verifier',
                   'trustedWheels': '/verifier-wheels', 'reports': '/logs/verifier', 'temporary': '/tmp'},
        'additionalDockerKernelMounts': 'Docker /dev and both8MiB /dev/shm are distinct kernel mounts; do not certify them as part of the512MiB shared input/log volume. Memory/physical admission includes them conservatively.',
        'tmpfsMemoryChargedToPrivateCgroupProven': False,
        'physicalExtraRamReservationBytes': RAM + SEEDER_MEMORY + 2 * SHM + 2 * 64 * 1024**2,
        'perRoleDevTmpfsMaximumBytes': 64 * 1024**2,
        'actualVolumeSubpathSupported': False, 'actualSameTmpfsSuperblockVerified': False,
        'officialControlsExecuted': False, 'actualReady': False, 'DockerMutations': 0,
        'requiresRootActualProof': True, 'sourceSha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}


def validate_plan(p):
    require(isinstance(p, dict) and p == plan(p.get('nonce')), 'ram_profile_changed',
            'RAM plan must match the exact current source, nonce, resources and mount argv')


def validate_volume(actual, p):
    validate_plan(p)
    require(actual.get('Name') == p['volumeName'] and actual.get('Driver') == 'local' and
            actual.get('Options') == OPTIONS and (actual.get('Labels') or {}).get(LABEL) == p['nonce'],
            'volume_identity', 'Exact owned512MiB tmpfs volume driver/options/nonce differ')


def validate_container(actual, p, seeder=False):
    validate_plan(p)
    role = 'objrun-jpg-ram-seeder-' if seeder else 'objrun-jpg-private-'
    h, c = actual.get('HostConfig', {}), actual.get('Config', {})
    require(re.fullmatch('[0-9a-f]{64}', actual.get('Id', '')) and actual.get('Name') == '/' + role + p['nonce'] and
            actual.get('Image') == IMAGE and c.get('Image') == IMAGE and (c.get('Labels') or {}).get(LABEL) == p['nonce'],
            'container_identity', 'Immutable original image/owned role/nonce was substituted')
    require(h.get('ReadonlyRootfs') is True and h.get('NetworkMode') == 'none' and h.get('Binds') in (None, []) and
            h.get('Privileged') is False and h.get('PidMode') in ('', None) and h.get('IpcMode') == 'private' and
            h.get('Tmpfs') in (None,{}) and h.get('CapAdd') in (None,[]) and h.get('Devices') in (None,[]) and
            h.get('DeviceRequests') in (None,[]) and h.get('DeviceCgroupRules') in (None,[]) and
            h.get('UsernsMode') in ('',None) and h.get('UTSMode') in ('',None) and c.get('User') == '0:0' and
            h.get('Memory') == (SEEDER_MEMORY if seeder else MEMORY) and
            h.get('MemorySwap') == (SEEDER_MEMORY if seeder else MEMORY) and
            h.get('NanoCpus') == (1000000000 if seeder else 4000000000) and h.get('ShmSize') == SHM and
            (h.get('LogConfig') or {}).get('Type') == 'none' and
            h.get('CapDrop') == ['ALL'] and h.get('SecurityOpt') in (['no-new-privileges'],['no-new-privileges:true']),
            'namespace', 'Read-only root/private network/memory/CPU/capability namespace differs')
    required = {'/objrun': ''} if seeder else MOUNTS
    mounts = h.get('Mounts', [])
    require(len(mounts) == len(required) and len(actual.get('Mounts', [])) == len(required),
            'mount_count', 'An unexpected host/volume/tmpfs mount was added')
    seen = set()
    for m in mounts:
        target, o = m.get('Target'), m.get('VolumeOptions') or {}
        require(target in required and target not in seen and m.get('Type') == 'volume' and
                m.get('Source') == p['volumeName'] and m.get('ReadOnly', False) is False and o.get('NoCopy') is True and
                o.get('Subpath', '') == required[target], 'mount_identity', 'A mount does not use its exact shared owned subpath')
        seen.add(target)
    seen = set()
    for m in actual['Mounts']:
        target = m.get('Destination')
        require(target in required and target not in seen and m.get('Type') == 'volume' and
                m.get('Name') == p['volumeName'] and m.get('Driver') == 'local' and m.get('RW') is True,
                'daemon_mount', 'Actual daemon mounts include another source or protected host bind')
        seen.add(target)
    env_rows = c.get('Env', [])
    require(all(isinstance(x, str) and '=' in x for x in env_rows) and
            len(env_rows) == len({x.split('=', 1)[0] for x in env_rows}), 'private_env', 'Duplicate/malformed container environment')
    env = dict(x.split('=', 1) for x in env_rows)
    require(not any(k in env for k in ('TGENGIN_GRADER_TOKEN', 'DEEPSEEK_API_KEY', 'TGENGIN_CONFIG', 'OBJRUN_SKB_MOCK_KEY')),
            'credential_env', 'A host credential entered the private role')
    if not seeder:
        require(all(env.get(k) == v for k, v in ENV.items()), 'private_env', 'Private interpreter/cache/temporary environment differs')
    require(c.get('WorkingDir') == ('/' if seeder else '/app/workspace') and c.get('Entrypoint') == ['/bin/bash'] and
            c.get('Cmd') == (p['seederCreate'][-2:] if seeder else ['-c', 'exec /bin/sleep infinity']),
            'command_identity', 'The trusted idle/seeding command or working directory was substituted')


def validate_mount_probe(probe, p, require_capacity=True):
    """Actual Root probe schema, not a production certificate factory."""
    validate_plan(p)
    require(probe.get('protocol') == PROTOCOL + '-native-mount-probe' and probe.get('nonce') == p['nonce'] and
            probe.get('imageId') == IMAGE and probe.get('rootFilesystemReadOnly') is True and
            probe.get('trustedBasePythonPath') == '/usr/bin/python3.12' and probe.get('python') == '3.12.3' and
            re.fullmatch('[0-9a-f]{64}', probe.get('basePythonSha256', '')) and
            probe.get('basePythonImageSource') == IMAGE and probe.get('seederAliveDuringProbe') is True,
            'native_probe', 'Actual image-bound trusted Python/root/seed-lifetime proof is incomplete')
    rows = probe.get('paths')
    require(isinstance(rows, list) and len(rows) == len(MOUNTS), 'native_probe', 'All six write paths must be measured')
    devices = set(); seen = set()
    for r in rows:
        require(r.get('path') in MOUNTS and r['path'] not in seen and r.get('filesystem') == 'tmpfs' and
                type(r.get('fsid')) is str and re.fullmatch('[0-9]+',r['fsid']) and
                type(r.get('device')) is str and re.fullmatch('[0-9]+',r['device']) and int(r['device'])>0 and type(r.get('blockSize')) is int and
                type(r.get('totalBlocks')) is int and r['blockSize'] > 0 and r['totalBlocks'] > 0 and
                r['blockSize'] * r['totalBlocks'] == RAM and r.get('volumeName') == p['volumeName'],
                'tmpfs_backing', 'Each path must share the exact measured512MiB tmpfs, not an overlay/host directory')
        seen.add(r['path']); devices.add((r['fsid'],r['device']))
    require(type(require_capacity) is bool and len(devices) == 1 and probe.get('rootReadonlyWriteRejected') is True and
            (not require_capacity or probe.get('capacityBoundaryReachedAndRejected') is True) and
            type(probe.get('graderSizeRwBefore')) is int and type(probe.get('graderSizeRwAfter')) is int and
            0 <= probe['graderSizeRwBefore'] == probe['graderSizeRwAfter'] <= 1024**2,
            'ram_boundary', 'Actual shared capacity/unchanged overlay/read-only root controls are missing')


def main():
    p = argparse.ArgumentParser(); p.add_argument('--nonce', required=True); a = p.parse_args()
    print(json.dumps(plan(a.nonce)))


if __name__ == '__main__': main()
