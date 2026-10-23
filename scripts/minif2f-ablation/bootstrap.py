"""Materialize copied public assets on the owning project's local ext4 tier."""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
import urllib.request

def log(obj): print(json.dumps(obj), flush=True)
def file_sha(path):
    with path.open('rb') as stream: return hashlib.file_digest(stream, 'sha256').hexdigest()

def main():
    root = Path(sys.argv[1]).resolve(); os.chdir(root)
    metadata = json.loads((root / 'dependency-bundle.json').read_text())
    bundle = root / metadata['archive']
    assert file_sha(bundle) == metadata['sha256'], 'Bundle integrity'
    assets = root / 'assets'
    assert not assets.exists(), 'Never overwrite an existing bootstrap; inspect its receipt'
    assets.mkdir()
    with tarfile.open(bundle, 'r:gz') as archive:
        for i, member in enumerate(archive):
            path = PurePosixPath(member.name)
            assert member.isfile() and not path.is_absolute() and '..' not in path.parts
            dest = assets.joinpath(*path.parts); dest.parent.mkdir(parents=True, exist_ok=True)
            source = archive.extractfile(member)
            with dest.open('xb') as output:
                while data := source.read(1024**2): output.write(data)
            os.chmod(dest, member.mode)
            if i % 3000 == 0: log({'stage': 'extract', 'files': i})
    log({'stage': 'lean-toolchain'})
    lean = assets / 'lean'; lean.mkdir()
    with zipfile.ZipFile(assets / 'lean-linux.zip') as archive:
        for member in archive.infolist():
            p = PurePosixPath(member.filename)
            assert p.parts[0] == 'lean-4.15.0-linux' and '..' not in p.parts
            if len(p.parts) == 1: continue
            dest = lean.joinpath(*p.parts[1:]); dest.parent.mkdir(parents=True, exist_ok=True)
            if member.is_dir(): dest.mkdir(exist_ok=True); continue
            mode = member.external_attr >> 16
            if stat.S_ISLNK(mode):
                target = archive.read(member).decode()
                resolved = (dest.parent / target).resolve()
                assert resolved.is_relative_to(lean)
                dest.symlink_to(target)
            else:
                with archive.open(member) as stream, dest.open('xb') as output:
                    while data := stream.read(1024**2): output.write(data)
                os.chmod(dest, mode & 0o777 or (0o755 if p.parts[1] == 'bin' else 0o644))
    env = dict(os.environ)
    env.update(PATH=str(lean / 'bin') + ':/usr/bin:/bin', LEAN_SYSROOT=str(lean), LD_LIBRARY_PATH=str(lean / 'lib/lean') + ':' + str(lean / 'lib'))
    version = subprocess.run([str(lean / 'bin/lean'), '--version'], capture_output=True, text=True, env=env, check=True)
    log({'lean': version.stdout.strip()})
    leantar = assets / 'tools/leantar'
    help_result = subprocess.run([str(leantar), '--help'], capture_output=True, text=True, env=env)
    (root / 'outputs/bootstrap-leantar-help.txt').write_text(help_result.stdout + help_result.stderr)
    caches = sorted((assets / 'cache').glob('*.ltar'))
    # Official Mathlib Cache.IO invokes leantar with -x and the archive paths.
    for index in range(0, len(caches), 128):
        result = subprocess.run([str(leantar), '-f', '-x', '--jobs', '4', *map(str, caches[index:index + 128])],
                                cwd=assets / 'mathlib4', env=env, capture_output=True, text=True)
        path = root / 'outputs/bootstrap-cache' / str(index); path.mkdir(parents=True, exist_ok=True)
        (path / 'stdout.txt').write_text(result.stdout); (path / 'stderr.txt').write_text(result.stderr)
        log({'stage': 'unpack-cache', 'done': min(index + 128, len(caches)), 'total': len(caches), 'exitCode': result.returncode})
        if result.returncode: raise RuntimeError('CacheUnpackFailed:' + str(index))
    # The older local acquisition was interrupted. Check all expected modules instead
    # of treating its progress counter as proof of a complete environment.
    expected_modules = [json.loads(line) for line in (root / 'vendor/module-cache-manifest.jsonl').read_text().splitlines()]
    object_pins = json.loads((root / 'vendor/cache-object-pins.json').read_text())
    package_names = {'Batteries': 'batteries', 'Aesop': 'aesop', 'Qq': 'Qq', 'ProofWidgets': 'proofwidgets',
                     'Plausible': 'plausible', 'LeanSearchClient': 'LeanSearchClient', 'ImportGraph': 'importGraph'}
    missing = []
    for row in expected_modules:
        module = Path(row['module']); top = module.parts[0].removesuffix('.lean')
        build = assets / 'mathlib4'
        if top in package_names: build = build / '.lake/packages' / package_names[top]
        target = build / '.lake/build/lib' / module.with_suffix('.olean')
        if not target.exists(): missing.append(row)
    log({'stage': 'module-coverage', 'expected': len(expected_modules), 'missing': len(missing)})
    downloaded = []
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({'http': 'http://127.0.0.1:18519', 'https': 'http://127.0.0.1:18519'}))
    for row in missing:
        name = row['ltar']; dest = assets / 'cache' / name
        if not dest.exists():
            pin = object_pins.get(name)
            # Cache URL comes from pinned official Mathlib Cache.Requests, not a guessed mirror.
            url = pin['url'] if pin else 'https://lakecache.blob.core.windows.net/mathlib4/f/' + name
            with opener.open(url, timeout=30) as response: data = response.read(16 * 1024**2)
            if pin: assert len(data) == pin['bytes'] and hashlib.sha256(data).hexdigest() == pin['sha256']
            dest.write_bytes(data)
            downloaded.append({'ltar': name, 'sha256': file_sha(dest), 'bytes': len(data), 'priorPinMatched': pin is not None})
        result = subprocess.run([str(leantar), '-f', '-x', '--jobs', '4', str(dest)], cwd=assets / 'mathlib4', env=env, capture_output=True, text=True)
        if result.returncode: raise RuntimeError('MissingModuleUnpack:' + name + ':' + result.stderr)
    (root / 'outputs/missing-cache-downloads.json').write_text(json.dumps(downloaded, indent=2) + '\n')
    identity = {'leanVersion': version.stdout.strip(), 'leanZipSha256': file_sha(assets / 'lean-linux.zip'),
                'replSha256': file_sha(assets / 'repl-bin'), 'leantarSha256': file_sha(leantar),
                'mathlibCommit': '9837ca9d65d9de6fad1ef4381750ca688774e608',
                'replCommit': '21966799da3691a0912b5a15193585bd2dd7165d',
                'bundleSha256': metadata['sha256'], 'unpackedRemainingArchives': len(caches),
                'additionalMissingArchives': len(downloaded),
                'isolation': 'bubblewrap unshare-all, env -i, fresh tmpfs, readonly dependencies',
                'atUtc': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
    (root / 'outputs/environment.json').write_text(json.dumps(identity, indent=2) + '\n')
    log({'stage': 'complete', 'environment': identity})

if __name__ == '__main__': main()
