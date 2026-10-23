"""Reviewed staged dependency restoration; contains no legacy candidate runner.

Host stages use GETs for public dependency bytes only. Container stages require
the existing fixed image, network=none, read-only root, and the dedicated E bind.
No elan, git clone, apt, pip, mutable branch, or remote Kimina service is used.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import struct
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile

RUN_ID = "01a119ed-fdf7-7c32-b323-de9bab1290b6"
EXPECTED_HOST_ROOT = "E:/objrun-experiment-cache/" + RUN_ID + "/minif2f-v415"
IMAGE = "sha256:adccbc2412fe240d3bba28a81e136d2e816a28b003263a2f1738098a67cbfbba"
CAP = 14*1024**3
RESERVE_E = 3*1024**3
RESERVE_F = 1024**3
MAX_CACHE_BLOB = 64*1024**2
MAX_UNPACK_FILE = 64*1024**2
MAX_UNPACK_FILES = 8
PINS = {"lean": "v4.15.0", "mathlib4": "9837ca9d65d9de6fad1ef4381750ca688774e608",
        "repl": "21966799da3691a0912b5a15193585bd2dd7165d",
        "kimina-lean-server": "fb2393de3461db35eda4c714e3fd21187e92ec90"}


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def dump(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".new")
    part.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    part.replace(path)


def stamp():
    return datetime.now(timezone.utc).isoformat()


def allocated_envelope(root):
    # E was read-only probed as 4096-byte NTFS allocation units. Gate repeats
    # that check; include a cluster per directory for metadata. Actual volume
    # free bytes are independently guarded by the PowerShell wrapper.
    total = 0
    for home, dirs, files in os.walk(root, followlinks=False):
        total += 4096*(len(dirs)+1)
        for name in files:
            path = Path(home)/name
            size = path.lstat().st_size
            total += ((size+4095)//4096)*4096
    return total


def room(root, addition=0, host=False):
    used = allocated_envelope(root)
    if used+addition > CAP:
        raise RuntimeError(f"owned directory cap: {used}+{addition}>{CAP}")
    if host:
        import ctypes
        sectors, block, free, total = (ctypes.c_ulong() for _ in range(4))
        if not ctypes.windll.kernel32.GetDiskFreeSpaceW("E:/", ctypes.byref(sectors), ctypes.byref(block), ctypes.byref(free), ctypes.byref(total)) or sectors.value*block.value != 4096:
            raise RuntimeError("E allocation unit differs from the reviewed 4096-byte envelope")
        if shutil.disk_usage("E:/").free-addition < RESERVE_E:
            raise RuntimeError("E reserve would fall below 3 GiB")
        if shutil.disk_usage("F:/").free < RESERVE_F:
            raise RuntimeError("F reserve fell below 1 GiB")
    return used


def owner(root, create=False):
    root = Path(root)
    if os.name == "nt" and str(root.resolve()).replace("\\", "/").casefold() != EXPECTED_HOST_ROOT.casefold():
        raise RuntimeError("only the exact reviewed E root is permitted")
    marker = root/"owned-root.json"
    expected = {"run_id": RUN_ID, "host_root": EXPECTED_HOST_ROOT, "purpose": "pinned public miniF2F dependency restoration"}
    if create and not marker.exists():
        if root.exists() and any(root.iterdir()):
            raise RuntimeError("refuse a nonempty directory without the exact ownership marker")
        room(root, host=True)
        root.mkdir(parents=True, exist_ok=True)
        dump(marker, expected)
    if not marker.exists() or json.loads(marker.read_bytes()) != expected:
        raise RuntimeError("dedicated root ownership mismatch")
    return root


def public_lock(public, expected_digest):
    public = Path(public)
    path = public/"public-lock.json"
    if sha(path) != expected_digest:
        raise RuntimeError("public lock SHA-256 differs from the reviewed preflight")
    lock = json.loads(path.read_bytes())
    for name, revision in PINS.items():
        if lock["pins"][name] != revision:
            raise RuntimeError("public source pin mismatch")
    for entry in lock["entries"]:
        path = public/entry["file"]
        if path.stat().st_size != entry["bytes"] or sha(path) != entry["sha256"]:
            raise RuntimeError("frozen public bytes changed: " + entry["file"])
    return lock


def bounded_get(url, dest, limit, root, expected_bytes=None, expected_hash=None):
    dest = Path(dest)
    if dest.exists():
        raise RuntimeError("refuse overwriting an unreviewed existing public download")
    dest.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "TgEngin-pinned-public-minif2f/1"})
    began = time.monotonic()
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != 200:
            raise RuntimeError("public dependency GET did not return 200")
        length = int(response.headers.get("Content-Length", "0"))
        if length > limit or (expected_bytes is not None and length and length != expected_bytes):
            raise RuntimeError("public dependency response size differs")
        room(root, min(length or limit, limit)+65536, host=True)
        http = {k.lower(): v for k, v in response.headers.items() if k.lower() in {"etag", "content-md5", "last-modified", "content-length"}}
        written = 0
        digest = hashlib.sha256()
        part = dest.with_name(dest.name+".part")
        with part.open("xb") as output:
            while chunk := response.read(1024**2):
                if time.monotonic()-began > 3*3600:
                    raise RuntimeError("public acquisition exceeded its three-hour wall limit")
                written += len(chunk)
                if written > limit:
                    raise RuntimeError("bounded public dependency download exceeded its limit")
                room(root, len(chunk)+65536, host=True)
                output.write(chunk)
                digest.update(chunk)
    value = digest.hexdigest()
    if (expected_bytes is not None and written != expected_bytes) or (expected_hash is not None and value != expected_hash):
        raise RuntimeError("public dependency downloaded bytes or SHA-256 differ")
    part.replace(dest)
    return {"url": url, "bytes": written, "sha256": value, "http": http, "recorded_at_utc": stamp()}


def download(root, public, lock_sha):
    root = owner(root, create=True)
    lock = public_lock(public, lock_sha)
    release = json.loads((Path(public)/"lean-release-v4.15.0.json").read_bytes())
    asset = next(x for x in release["assets"] if x["name"] == "lean-4.15.0-linux.zip")
    if asset["size"] != 427590493 or asset.get("digest") is not None:
        raise RuntimeError("reviewed release asset metadata differs")
    receipt = root/"audit/lean-download.json"
    dest = root/"downloads/lean-4.15.0-linux.zip"
    if receipt.exists():
        old = json.loads(receipt.read_bytes())
        if old["asset_id"] != asset["id"] or old["bytes"] != dest.stat().st_size or old["sha256"] != sha(dest):
            raise RuntimeError("previous acquired Lean release no longer matches its receipt")
        print(json.dumps({"already_acquired": True, "sha256": old["sha256"]}))
        return
    result = bounded_get(asset["browser_download_url"], dest, asset["size"], root, asset["size"])
    result.update({"asset_id": asset["id"], "release_id": release["id"], "published_digest": None,
                   "hash_assurance": "official URL and asset ID via HTTPS; SHA-256 measured after download, no upstream SHA-256 was published",
                   "public_lock_sha256": lock_sha, "executable_run": False})
    dump(receipt, result)
    print(json.dumps({"downloaded_bytes": result["bytes"], "sha256": result["sha256"], "executable_run": False}))


def run(cmd, root, cwd=None, env=None, timeout=1800, file_limit=None, output=None):
    import resource
    room(root)
    def limits():
        os.setsid()
        if file_limit:
            resource.setrlimit(resource.RLIMIT_FSIZE, (file_limit, file_limit))
    # All invoked executables have been pinned/hash-checked before this function.
    result = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, timeout=timeout, preexec_fn=limits)
    if result.returncode:
        raise RuntimeError(f"public build/probe failed ({result.returncode}): {result.stderr.decode(errors='replace')[-2000:]}")
    if output:
        Path(output).write_bytes(result.stdout)
    room(root)
    return result.stdout.decode(errors="replace").strip()


def untar(source, destination, root):
    if destination.exists():
        raise RuntimeError("source destination already exists; resume via the bootstrap receipt or inspect owned partials")
    with tarfile.open(source, "r:gz") as archive:
        members = archive.getmembers()
        prefixes = {PurePosixPath(x.name).parts[0] for x in members}
        if len(prefixes) != 1:
            raise RuntimeError("public source archive has multiple roots")
        addition = sum(x.size for x in members)+65536*(len(members)+1)
        room(root, addition)
        temporary = root/("extract-"+destination.name)
        if temporary.exists():
            raise RuntimeError("owned partial source extraction needs inspection")
        temporary.mkdir()
        archive.extractall(temporary, filter="data")
        destination.parent.mkdir(parents=True, exist_ok=True)
        (temporary/next(iter(prefixes))).rename(destination)
        temporary.rmdir()


def unzip(source, destination, root, strip_root=False):
    with zipfile.ZipFile(source) as archive:
        infos = archive.infolist()
        room(root, sum(x.file_size for x in infos)+65536*(len(infos)+1))
        for item in infos:
            pure = PurePosixPath(item.filename)
            if pure.is_absolute() or ".." in pure.parts:
                raise RuntimeError("unsafe public ZIP path")
            parts = pure.parts[1:] if strip_root else pure.parts
            if not parts:
                continue
            target = destination.joinpath(*parts)
            if item.is_dir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            mode = item.external_attr >> 16
            if stat.S_ISLNK(mode):
                link = archive.read(item).decode()
                if PurePosixPath(link).is_absolute() or not (target.parent/link).resolve().is_relative_to(destination.resolve()):
                    raise RuntimeError("public ZIP symlink leaves the owned toolchain")
                target.symlink_to(link)
            else:
                with archive.open(item) as incoming, target.open("xb") as outgoing:
                    shutil.copyfileobj(incoming, outgoing, 1024**2)
                target.chmod((mode & 0o777) or 0o644)


def environment(root):
    env = dict(os.environ)
    env.update({"PATH": str(root/"toolchain/bin")+":/usr/local/bin:/usr/bin:/bin", "HOME": str(root/"home"),
                "XDG_CACHE_HOME": str(root/"xdg-cache"), "TMPDIR": "/tmp", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONPATH": str(root/"python-support"), "TGENGIN_MF2F_HOME": str(root), "TGENGIN_MF2F_BACKEND": "repl",
                "TGENGIN_MF2F_REPLS": "1", "TGENGIN_MF2F_MEM_GB": "12", "TGENGIN_MF2F_TIMEOUT": "300",
                "TGENGIN_MF2F_MAX_USES": "4", "TGENGIN_MF2F_STRICT_AXIOMS": "0"})
    return env


def bootstrap(root, public, lock_sha, problems_sha):
    root = owner(root)
    public = Path(public)
    lock = public_lock(public, lock_sha)
    receipt = root/"audit/bootstrap.json"
    if receipt.exists():
        raise RuntimeError("bootstrap receipt exists; use later stages, do not silently rebuild")
    acquired = json.loads((root/"audit/lean-download.json").read_bytes())
    lean_zip = root/"downloads/lean-4.15.0-linux.zip"
    if sha(lean_zip) != acquired["sha256"] or acquired["public_lock_sha256"] != lock_sha:
        raise RuntimeError("acquired release checksum or reviewed lock differs")
    if sha(public/"problems.jsonl") != problems_sha:
        raise RuntimeError("pinned 488-problem metadata checksum differs")
    unzip(lean_zip, root/"toolchain", root, strip_root=True)
    untar(public/"mathlib-source.tar.gz", root/"mathlib4", root)
    untar(public/"repl-source.tar.gz", root/"repl", root)
    manifest = json.loads((root/"mathlib4/lake-manifest.json").read_bytes())
    for package in manifest["packages"]:
        untar(public/("package-"+package["name"]+".tar.gz"), root/"mathlib4/.lake/packages"/package["name"], root)
    for wheel in lock["python_wheels"]:
        unzip(public/wheel["file"], root/"python-support", root)
    models = root/"vendor/kimina-lean-server/client/kimina_client/models.py"
    models.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(public/"kimina-models.py", models)
    shutil.copyfile(public/"problems.jsonl", root/"problems.jsonl")
    # This fixed official helper has no elan/git/pip installation path.
    untar(public/"leantar-linux.tar.gz", root/"tools/leantar-release", root)
    leantar_options = list((root/"tools/leantar-release").rglob("leantar"))
    if len(leantar_options) != 1:
        raise RuntimeError("fixed leantar release layout differs")
    leantar = root/"tools/leantar"
    leantar_options[0].rename(leantar)
    leantar.chmod(0o755)
    env = environment(root)
    versions = {"lean": run([str(root/"toolchain/bin/lean"), "--version"], root, env=env),
                "clang": run([str(root/"toolchain/bin/clang"), "--version"], root, env=env),
                "leantar": run([str(leantar), "--version"], root, env=env)}
    if "version 4.15.0" not in versions["lean"] or "0.1.14" not in versions["leantar"]:
        raise RuntimeError("frozen executable version probe differs")
    run([str(root/"toolchain/bin/lake"), "build"], root, cwd=root/"repl", env=env, timeout=1800)
    if not (root/"repl/.lake/build/bin/repl").is_file():
        raise RuntimeError("fixed REPL build output missing")
    compiled = root/"mathlib4/.lake/build/lib/Cache"
    compiled.mkdir(parents=True, exist_ok=True)
    env["LEAN_PATH"] = str(compiled.parent)+":"+str(root/"toolchain/lib/lean")
    for module in ["IO", "Hashing"]:
        run([str(root/"toolchain/bin/lean"), "-o", str(compiled/(module+".olean")), "Cache/"+module+".lean"], root, cwd=root/"mathlib4", env=env)
    module_manifest = root/"audit/module-cache-manifest.jsonl"
    run([str(root/"toolchain/bin/lean"), "-R", "/plan", "--run", "/plan/mathlib_cache_manifest.lean"], root,
        cwd=root/"mathlib4", env=env, output=module_manifest)
    rows = [json.loads(x) for x in module_manifest.read_text().splitlines() if x]
    if len(rows) < 5000 or any(not re.fullmatch(r"[0-9a-f]{16}\.ltar", x["ltar"]) for x in rows):
        raise RuntimeError("official module cache key export is incomplete")
    dump(receipt, {"recorded_at_utc": stamp(), "pins": PINS, "image_id": IMAGE, "public_lock_sha256": lock_sha,
                   "lean_download_sha256": acquired["sha256"], "versions": versions,
                   "module_cache_manifest_sha256": sha(module_manifest), "module_cache_count": len(rows),
                   "repl_binary_sha256": sha(root/"repl/.lake/build/bin/repl"), "models_sha256": sha(models),
                   "problems_sha256": sha(root/"problems.jsonl"), "owned_envelope_bytes": room(root),
                   "network": "none", "candidate_run": False})
    print(json.dumps({"bootstrap_complete": True, "official_cache_keys": len(rows), "candidate_run": False}))


def cache_download(root):
    root = owner(root)
    bootstrap_receipt = json.loads((root/"audit/bootstrap.json").read_bytes())
    manifest = root/"audit/module-cache-manifest.jsonl"
    if sha(manifest) != bootstrap_receipt["module_cache_manifest_sha256"]:
        raise RuntimeError("official cache key manifest changed")
    rows = [json.loads(x) for x in manifest.read_text().splitlines() if x]
    receipt = root/"audit/cache-downloads.jsonl"
    old = {x["ltar"]: x for x in (json.loads(line) for line in receipt.read_text().splitlines())} if receipt.exists() else {}
    began = time.monotonic()
    for index, item in enumerate(rows):
        if time.monotonic()-began > 3*3600:
            raise RuntimeError("public cache acquisition exceeded its three-hour wall limit")
        name = item["ltar"]
        if not re.fullmatch(r"[0-9a-f]{16}\.ltar", name):
            raise RuntimeError("non-official public cache object name")
        path = root/"downloads/mathlib-cache"/name
        if name in old:
            if not path.exists() or sha(path) != old[name]["sha256"]:
                raise RuntimeError("previous cache receipt no longer matches downloaded bytes")
            continue
        result = bounded_get("https://lakecache.blob.core.windows.net/mathlib4/f/"+name, path, MAX_CACHE_BLOB, root)
        result.update(item)
        with receipt.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(result)+"\n")
        if (index+1) % 200 == 0:
            print(json.dumps({"cache_objects_downloaded": index+1, "total": len(rows), "owned_envelope_bytes": room(root, host=True)}), flush=True)
    dump(root/"audit/cache-download-complete.json", {"recorded_at_utc": stamp(), "objects": len(rows),
        "module_cache_manifest_sha256": sha(manifest), "download_receipts_sha256": sha(receipt),
        "compressed_bytes": sum(x["bytes"] for x in [json.loads(line) for line in receipt.read_text().splitlines()]),
        "owned_envelope_bytes": room(root, host=True), "candidate_run": False})
    print(json.dumps({"cache_download_complete": True, "objects": len(rows), "candidate_run": False}))


def ltar_paths(path, mathlib):
    # Audit the fixed official LTAR layout before invoking its unpacker. This is
    # a dependency-file path/space guard, never a proof or CMT parser.
    data = path.read_bytes()
    if data[:4] not in {b"LTAR", b"LTR2"}:
        raise RuntimeError("unsupported public cache archive format")
    position = 12
    paths = []
    def cstring():
        nonlocal position
        end = data.index(b"\0", position)
        value = data[position:end].decode()
        position = end+1
        return value
    def payload():
        nonlocal position
        kind = data[position]
        position += 1
        if kind in [0, 1]:
            size = struct.unpack_from("<Q", data, position)[0]
            position += 8+size
        elif kind in [2, 3]:
            position += 8
        else:
            raise RuntimeError("unsupported public cache compression format")
        if position > len(data):
            raise RuntimeError("truncated public cache payload")
    paths.append(cstring())
    if data[:4] == b"LTR2":
        payload()
    while position < len(data):
        value = cstring()
        if value:
            paths.append(value)
            payload()
        else:
            cstring()  # comment, not code and not a path
    if len(paths) > MAX_UNPACK_FILES:
        raise RuntimeError("public cache object exceeds the reviewed eight-file envelope")
    for value in paths:
        pure = PurePosixPath(value)
        if pure.is_absolute() or ".." in pure.parts or not value.startswith(".lake/") or len(pure.parts)>16 or len(value.encode())>256:
            raise RuntimeError("public cache file leaves the owned Mathlib build")
        target = (mathlib/value).resolve()
        if not target.is_relative_to(mathlib.resolve()):
            raise RuntimeError("public cache path crosses an owned-root symlink")
    return paths


def unpack_probe(root):
    root = owner(root)
    complete = json.loads((root/"audit/cache-download-complete.json").read_bytes())
    downloaded = root/"audit/cache-downloads.jsonl"
    if sha(downloaded) != complete["download_receipts_sha256"]:
        raise RuntimeError("cache download receipt checksum differs")
    records = [json.loads(line) for line in downloaded.read_text().splitlines()]
    env = environment(root)
    mathlib = root/"mathlib4"
    unpacked = root/"audit/cache-unpacked.jsonl"
    if unpacked.exists():
        raise RuntimeError("partial unpack receipt exists; inspect it before any rerun")
    for index, record in enumerate(records):
        path = root/"downloads/mathlib-cache"/record["ltar"]
        if path.stat().st_size != record["bytes"] or sha(path) != record["sha256"]:
            raise RuntimeError("cached dependency bytes changed")
        paths = ltar_paths(path, mathlib)
        # Eight outputs at <=64 MiB each are a strict per-object upper bound.
        # Refuse to launch the official unpacker if that envelope would cross 14 GiB.
        room(root, len(paths)*(MAX_UNPACK_FILE+2*1024**2)+65536)
        run([str(root/"tools/leantar"), "-x", str(path)], root, cwd=mathlib, env=env, timeout=300, file_limit=MAX_UNPACK_FILE)
        outputs = []
        for value in paths:
            target = mathlib/value
            if not target.is_file():
                raise RuntimeError("official cache unpack omitted an expected file")
            outputs.append({"path": value, "bytes": target.stat().st_size, "sha256": sha(target)})
        with unpacked.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"ltar": record["ltar"], "source_sha256": record["sha256"], "files": outputs})+"\n")
        # Remove only this exact, already-hashed owned dependency blob after all
        # unpacked files have their hashes durably recorded. Public receipts
        # and source archives remain, and no unrelated path is removed.
        path.unlink()
        if (index+1) % 200 == 0:
            print(json.dumps({"cache_objects_unpacked": index+1, "total": len(records), "owned_envelope_bytes": room(root)}), flush=True)
    # The original stand module and official Kimina functions are used unchanged.
    # These artificial public controls establish dependency operation, never a
    # historical result. No old task ID or candidate is read by this worker.
    probe_code = '''import importlib.util,json,sys
spec=importlib.util.spec_from_file_location("mf2f_restore_stand","/plan/stand.py")
m=importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
header="import Mathlib\\nimport Aesop\\n\\nset_option maxHeartbeats 0\\n\\nopen BigOperators Real Nat Topology Rat\\n\\n"
results={}
for label,prop,tactic in [("good","True","trivial"),("sorry","True","sorry"),("wrong","False","trivial")]:
 name="tgengin_restore_control_"+label
 item={"name":name,"header":header,"statement":"theorem "+name+" : "+prop+" := by\\n"}
 results[label]=m.judge(item,header+item["statement"]+"  "+tactic)
for r in m.LEAN.idle:r.kill()
want={"good":[True,True,True],"sorry":[True,True,False],"wrong":[True,False,False]}
ok=all([results[k][x] for x in ["stated","compiles","sound"]]==v and not results[k].get("backend_error") for k,v in want.items())
print(json.dumps({"public_controls":results,"controls_passed":ok,"book_count":len(m.BOOK),"candidate_run":False}))
sys.exit(0 if ok and len(m.BOOK)==488 else 1)
'''
    output = root/"audit/public-controls.json"
    run([sys.executable, "-c", probe_code], root, env=env, timeout=1800, output=output)
    controls = json.loads(output.read_bytes())
    dump(root/"audit/restoration-complete.json", {"recorded_at_utc": stamp(), "pins": PINS, "image_id": IMAGE,
        "public_controls_sha256": sha(output), "cache_unpacked_receipts_sha256": sha(unpacked),
        "cache_objects": len(records), "controls_passed": controls["controls_passed"],
        "owned_envelope_bytes": room(root), "candidate_run": False, "historical_score_certified": False})
    print(json.dumps({"restoration_complete": True, "controls_passed": controls["controls_passed"], "candidate_run": False}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=["download", "bootstrap", "cache-download", "unpack-probe"])
    parser.add_argument("--root", required=True)
    parser.add_argument("--public")
    parser.add_argument("--lock-sha")
    parser.add_argument("--problems-sha")
    args = parser.parse_args()
    try:
        if args.stage == "download":
            download(args.root, args.public, args.lock_sha)
        elif args.stage == "bootstrap":
            bootstrap(Path(args.root), args.public, args.lock_sha, args.problems_sha)
        elif args.stage == "cache-download":
            cache_download(args.root)
        else:
            unpack_probe(Path(args.root))
    except Exception as error:
        # Preserve the exact owned partials; do not automatically retry, choose
        # another toolchain/cache revision, or treat dependency failure as a grade.
        try:
            root = owner(args.root)
            room(root, 65536, host=os.name == "nt")
            parts = list((root/"downloads").rglob("*.part"))[:50]
            partials = [{"path": p.relative_to(root).as_posix(), "bytes": p.stat().st_size, "sha256": sha(p)}
                        for p in parts if p.resolve().is_relative_to(root.resolve())]
            dump(root/("audit/"+args.stage+"-failure.json"), {"recorded_at_utc": stamp(), "stage": args.stage,
                "error_type": type(error).__name__, "error": str(error), "owned_partials": partials,
                "candidate_run": False, "historical_score_certified": False})
        except Exception:
            pass  # The caller's output preserves the error if even audit space is unavailable.
        raise
