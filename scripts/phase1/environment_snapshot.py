"""Freeze installed grading dependencies without importing the base Python environment."""
import argparse
from datetime import datetime, timezone
import hashlib
from importlib import metadata
import json
from pathlib import Path
import platform

ROOT = Path(__file__).resolve().parents[2]

def digest(path):
    hasher = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            hasher.update(chunk)
    return hasher.hexdigest()

def snapshot(image_id, bun_version):
    caches = []
    for name in ['python-extras', 'material-extras', 'host-extras']:
        home = ROOT / '.phase1-data' / name
        packages = sorted({f"{d.metadata['Name']}=={d.version}" for d in metadata.distributions(path=[str(home)])}, key=str.lower)
        lock = ROOT / 'examples/benchmark/_lib' / f'requirements-{name}.txt'
        lock.write_text('\n'.join(packages) + '\n', encoding='utf-8')
        files = []
        for path in sorted(home.rglob('*')):
            if path.is_file() and path.name != 'phase1-files.json' and '__pycache__' not in path.parts and path.suffix != '.pyc':
                files.append({'path': path.relative_to(home).as_posix(), 'bytes': path.stat().st_size, 'sha256': digest(path)})
        manifest = json.dumps(files, sort_keys=True, separators=(',', ':')).encode()
        # Keep the detailed manifest in the private reproducible environment cache.
        (home / 'phase1-files.json').write_bytes(manifest)
        caches.append({'cache': name, 'requirements': lock.relative_to(ROOT).as_posix(), 'packages': packages, 'files': len(files), 'fileManifestSha256': hashlib.sha256(manifest).hexdigest()})
    result = {
        'recordedAt': datetime.now(timezone.utc).isoformat(),
        'host': {'python': platform.python_version(), 'platform': platform.platform(), 'bun': bun_version, 'java': '1.8.0_341'},
        'image': {'tag': 'objrun-scicode:phase1', 'id': image_id, 'dockerfileSha256': digest(ROOT / 'examples/benchmark/scicode/Dockerfile')},
        'dependencies': caches,
        'isolation': {'candidateUid': 65534, 'network': 'none in scientific candidate execution', 'readOnly': True, 'oracleDirectory': '/root/oracle; inaccessible to candidate UID', 'dataLocation': 'F: workspace cache', 'scienceworld': 'native Java simulator; observation-only action tool'},
        'protocolLimits': ['Single SciCode preparation environment; canonical multi-environment evaluation not reproduced.', 'HumanEval+ RPC execution includes communication overhead in timing.', 'Base image and extra dependency mounts are recorded separately; historical environments are not backfilled.'],
    }
    (ROOT / 'docs/phase1/environment.json').write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'image': image_id, 'dependencyCaches': len(caches), 'packages': sum(len(c['packages']) for c in caches)}))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--image-id', required=True)
    parser.add_argument('--bun-version', required=True, help='Version observed by the calling shell; Bun may be exposed as a PowerShell alias on Windows.')
    args=parser.parse_args()
    snapshot(args.image_id, args.bun_version)
