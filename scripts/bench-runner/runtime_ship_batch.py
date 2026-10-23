"""Batch the four small frozen runtime files; retain the original Node copy.

This is an opt-in ship_runtime implementation. It neither creates actors nor
changes native guards, command bounds, the runtime bytes, or task clocks.
"""
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time


DESTINATIONS = {
    'runtime.mjs': 'rt-runtime.mjs',
    'libgcc_s.so.1': 'rt-lib/libgcc_s.so.1',
    'libstdc++.so.6': 'rt-lib/libstdc++.so.6',
}


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def bundle(staged):
    from docker_owned import ROOT
    permitted = ROOT / 'docs/repair-2026-10-10/full-f-rerun/terminal-bench'
    rows = staged['files']
    paths = {Path(row['path']).name: Path(row['path']) for row in rows}
    assert len(paths) == len(rows) == 4
    assert set(paths) == {'node', *DESTINATIONS}
    expected = staged['manifest']['assets']
    assert set(expected) == set(paths)
    for name, path in paths.items():
        assert path.resolve().is_relative_to(permitted.resolve())
        assert path.is_file() and not path.is_symlink()
        assert digest(path) == expected[name], 'runtime_asset_changed'
    launcher = Path(staged['launcher']['path'])
    assert launcher.resolve().is_relative_to(permitted.resolve())
    assert launcher.is_file() and not launcher.is_symlink()
    assert digest(launcher) == staged['launcher']['sha256']
    manifest = {}
    output = io.BytesIO()
    with tarfile.open(fileobj=output, mode='w', format=tarfile.USTAR_FORMAT) as archive:
        directory = tarfile.TarInfo('rt-lib')
        directory.type = tarfile.DIRTYPE
        directory.mode = 0o755
        archive.addfile(directory)
        sources = [(paths[name], destination, expected[name])
                   for name, destination in DESTINATIONS.items()]
        sources.append((launcher, 'rt', staged['launcher']['sha256']))
        for source, destination, sha in sources:
            data = source.read_bytes()
            assert hashlib.sha256(data).hexdigest() == sha
            info = tarfile.TarInfo(destination)
            info.size = len(data)
            info.mode = 0o755 if destination == 'rt' else 0o644
            archive.addfile(info, io.BytesIO(data))
            manifest['/' + destination] = {'sha256': sha, 'bytes': len(data)}
    manifest['/rt-node'] = {'sha256': expected['node'], 'bytes': paths['node'].stat().st_size}
    raw = output.getvalue()
    assert len(raw) <= 16 * 1024 * 1024, 'small_runtime_bundle_bound'
    return paths, raw, manifest


def ship_runtime(native, cid, staged):
    paths, raw, expected = bundle(staged)
    native.guard()
    before = native.assert_actor(cid)
    assert before['State']['Running'] and not before['State']['Paused']
    # This exact call retains the existing accepted NAS/server-local Node path.
    node_receipt = native.upload(paths['node'], cid, '/rt-node')
    archive_path = Path(staged['launcher']['path']).parent / 'runtime-small-bundle.tar'
    with archive_path.open('xb') as stream:
        stream.write(raw)
    native.guard()
    native.assert_actor(cid)
    upload = native.checked(['cp', '-', cid + ':/'], stdin=raw)
    proof = native.execute(cid, ['/bin/sh', '-c',
        'chmod 0755 /rt /rt-node && LD_LIBRARY_PATH=/rt-lib /rt-node --version'])
    assert native.text(proof) == 'v22.22.2'
    running = native.assert_actor(cid)
    for key in ('Id', 'Image', 'HostConfig', 'Mounts', 'Labels'):
        assert running[key] == before[key], 'runtime_actor_identity_changed'
    assert running['State']['Pid'] > 0
    guest_code = (
        'const fs=require("node:fs"),crypto=require("node:crypto"),expected='
        + json.dumps(expected, separators=(',', ':')) + ';'
        'for(const [p,e] of Object.entries(expected)){' 
        'const s=fs.lstatSync(p);if(!s.isFile()||s.isSymbolicLink()||s.size!==e.bytes)throw Error("runtime_file_identity");'
        'if(crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex")!==e.sha256)throw Error("runtime_file_hash");}'
        'const s=fs.statfsSync("/app");console.log(JSON.stringify({'
        'availableStorageBytes:s.bavail*s.bsize,wallUnixMs:Date.now(),numericGuestPid:process.pid,'
        'numericParentPid:process.ppid,namespaces:Object.fromEntries(["pid","mnt","net"].map(n=>[n,fs.readlinkSync("/proc/self/ns/"+n)])),'
        'runtimeFilesVerified:expected}));'
    )
    started = time.time()
    receipt = native.execute(cid, ['/bin/sh', '-c',
        'LD_LIBRARY_PATH=/rt-lib /rt-node -e ' + "'" + guest_code + "'"])
    stopped = time.time()
    guest = json.loads(native.text(receipt))
    assert guest['numericGuestPid'] > 0 and guest['wallUnixMs'] > 0
    assert guest['availableStorageBytes'] >= 10240 * 1024 ** 2
    assert guest['runtimeFilesVerified'] == expected
    calibration = {'hostStartUnixSeconds': started, 'hostStopUnixSeconds': stopped,
        'guest': guest, 'guestMinusHostSecondsInterval': [guest['wallUnixMs'] / 1000 - stopped,
        guest['wallUnixMs'] / 1000 - started], 'receipt': receipt, 'measuredBeforeAnyModel': True}
    return {'protocol': 'tb12-shipped-runtime-before-model-v1', 'candidateCid': cid,
        'runningState': running, 'nodeVersionReceipt': proof, 'runtimeManifest': staged,
        'numericPidAndClockCalibration': calibration,
        'batchShipment': {'protocol': 'bench-frozen-small-runtime-batch-v1',
            'archivePin': {'path': str(archive_path), 'bytes': len(raw),
                           'sha256': hashlib.sha256(raw).hexdigest()},
            'nodeCopyReceipt': node_receipt, 'smallBundleUploadReceipt': upload,
            'guestFullHashVerified': True, 'originalNativeGuardsUnchanged': True}}
