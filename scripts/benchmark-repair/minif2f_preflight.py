"""Public dependency provenance and offline task identity, never Lean regrading.

collect makes bounded GETs for pinned public metadata and source archives only.
report reads the frozen public files and the three already-selected last submits.
No installer, container, model, remote verifier, or historical write is invoked.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import struct
import tarfile
import urllib.error
import urllib.request

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/repair-2026-10-08"
PUBLIC = ROOT / ".phase1-data/minif2f-restoration-public"
IMAGE = "sha256:adccbc2412fe240d3bba28a81e136d2e816a28b003263a2f1738098a67cbfbba"
PINS = {
    "lean": "v4.15.0",
    "mathlib4": "9837ca9d65d9de6fad1ef4381750ca688774e608",
    "repl": "21966799da3691a0912b5a15193585bd2dd7165d",
    "kimina-lean-server": "fb2393de3461db35eda4c714e3fd21187e92ec90",
    "Kimina-Prover-Preview": "7abd61a5d9861bf5c15b195c216c1bb233ac32e4",
    "DeepSeek-Prover-V1.5": "2c4ba9119eef74d0d611f494261b2c5bae98c69a",
    "AI-MO/minif2f_test": "5def318348521dfc34875045a9ecddf729a2b49f",
    "leantar": "v0.1.14",
    "leantar-source": "be54d5af4e9c61ed04809e3519f47f83a5b046a7",
}
FIXED = {
    ("minif2f-f-0731", "test/amc12a_2019_p12"): "1ad93d0d3b1daad8252bf0ef17e6ab044053daddafb599d035da6db007f16568",
    ("minif2f-f-0731b", "test/mathd_algebra_184"): "7bd5742ddab252e281bda4fb466ea314cc1f8618092b8f7b5a552c5de3053283",
    ("minif2f-f-0731b", "test/mathd_numbertheory_552"): "f3972196a6915d9284d991e36d39c17756de6163e23937b7670bf13f405b2b87",
}
HEADER = "import Mathlib\nimport Aesop\n\nset_option maxHeartbeats 0\n\nopen BigOperators Real Nat Topology Rat\n\n"
PARQUET_SHA = "a32985e3d44b5165fbd586f453055cd17de0d081f43d7806cbba3f321346a8c5"
PUBLIC_TOTAL_LIMIT = 100 * 1024**2


def sha(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def dump(path: Path, value) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get(url: str, limit: int, headers=None, expected_status=200) -> tuple[bytes, dict]:
    # Metadata requests never use a candidate ID, candidate text, GT, or API key.
    request = urllib.request.Request(url, headers={"User-Agent": "TgEngin-minif2f-public-provenance/1", **(headers or {})})
    with urllib.request.urlopen(request, timeout=60) as response:
        if response.status != expected_status:
            raise RuntimeError(f"unexpected HTTP status {response.status} for public URL")
        if int(response.headers.get("Content-Length", "0")) > limit:
            raise RuntimeError("public response exceeds the bounded preflight limit")
        data = response.read(limit + 1)
        if len(data) > limit:
            raise RuntimeError("public response exceeds the bounded preflight limit")
        # Signed CDN redirects are deliberately not written into reports.
        metadata = {k.lower(): v for k, v in response.headers.items() if k.lower() in {
            "content-length", "content-range", "etag", "last-modified", "content-md5"
        }}
    return data, metadata


def collect() -> None:
    PUBLIC.mkdir(parents=True, exist_ok=True)
    entries = []
    total = 0

    def save(name: str, url: str, limit=4 * 1024**2, expected_sha=None, headers=None, expected_status=200):
        nonlocal total
        data, metadata = get(url, min(limit, PUBLIC_TOTAL_LIMIT - total), headers, expected_status)
        digest = sha(data)
        if expected_sha and digest != expected_sha:
            raise RuntimeError(f"hash mismatch for pinned public artifact {name}")
        total += len(data)
        path = PUBLIC / name
        path.write_bytes(data)
        entries.append({"file": name, "url": url, "bytes": len(data), "sha256": digest, "http": metadata})
        return data

    release = json.loads(save("lean-release-v4.15.0.json", "https://api.github.com/repos/leanprover/lean4/releases/tags/v4.15.0"))
    repl_tag = json.loads(save("repl-tag-v4.15.0.json", "https://api.github.com/repos/leanprover-community/repl/git/ref/tags/v4.15.0"))
    if repl_tag["object"]["sha"] != PINS["repl"]:
        raise RuntimeError("the REPL tag no longer resolves to the pinned commit")
    save("leantar-release-v0.1.14.json", "https://api.github.com/repos/digama0/leangz/releases/tags/v0.1.14")
    ds = PINS["AI-MO/minif2f_test"]
    tree = json.loads(save("minif2f-tree.json", f"https://huggingface.co/api/datasets/AI-MO/minif2f_test/tree/{ds}?recursive=true"))
    parquet = next(x for x in tree if x["path"] == "data/train-00000-of-00001.parquet")
    if parquet["size"] != 74285 or parquet["lfs"]["oid"] != PARQUET_SHA:
        raise RuntimeError("pinned dataset LFS metadata differs")
    save("minif2f-test.parquet", f"https://huggingface.co/datasets/AI-MO/minif2f_test/resolve/{ds}/data/train-00000-of-00001.parquet", 74285, PARQUET_SHA)

    math = PINS["mathlib4"]
    raw = f"https://raw.githubusercontent.com/leanprover-community/mathlib4/{math}/"
    for path in ["lake-manifest.json", "lean-toolchain", "lakefile.lean", "Cache/IO.lean", "Cache/Requests.lean", "Cache/Main.lean", "Cache/Hashing.lean"]:
        save("mathlib-" + path.replace("/", "-"), raw + path)
    save("mathlib-tree.json", f"https://api.github.com/repos/leanprover-community/mathlib4/git/trees/{math}?recursive=1")
    # Pure archive inspection; no extraction and no source execution.
    tar_bytes = save("mathlib-source.tar.gz", f"https://codeload.github.com/leanprover-community/mathlib4/tar.gz/{math}", 32 * 1024**2)
    with tarfile.open(fileobj=io.BytesIO(tar_bytes), mode="r:gz") as archive:
        members = archive.getmembers()
        source_inventory = {"files": sum(m.isfile() for m in members), "logical_bytes": sum(m.size for m in members if m.isfile()),
                            "untrusted_paths_not_extracted": True}
    dependencies = json.loads((PUBLIC / "mathlib-lake-manifest.json").read_bytes())["packages"]
    # Commit hashes are the authoritative pins; exact public archive bytes are also frozen.
    package_archives = []
    for package in dependencies:
        repo = package["url"].removeprefix("https://github.com/")
        data = save("package-" + package["name"] + ".tar.gz", f"https://codeload.github.com/{repo}/tar.gz/{package['rev']}", 16 * 1024**2)
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as archive:
            package_archives.append({"name": package["name"], "rev": package["rev"], "archive_bytes": len(data),
                                     "logical_bytes": sum(m.size for m in archive.getmembers() if m.isfile())})

    repl = PINS["repl"]
    for path in ["lake-manifest.json", "lakefile.toml", "lean-toolchain"]:
        save("repl-" + path, f"https://raw.githubusercontent.com/leanprover-community/repl/{repl}/{path}")
    save("repl-source.tar.gz", f"https://codeload.github.com/leanprover-community/repl/tar.gz/{repl}", 4 * 1024**2)
    kimina = PINS["kimina-lean-server"]
    save("kimina-models.py", f"https://raw.githubusercontent.com/project-numina/kimina-lean-server/{kimina}/client/kimina_client/models.py")
    # Build helper is downloaded for checksum provenance only; never executed here.
    save("leantar-linux.tar.gz", "https://github.com/digama0/leangz/releases/download/v0.1.14/leantar-v0.1.14-x86_64-unknown-linux-musl.tar.gz", 1085233)

    linux_zip = next(x for x in release["assets"] if x["name"] == "lean-4.15.0-linux.zip")
    size = linux_zip["size"]
    url = linux_zip["browser_download_url"]
    suffix = save("lean-zip-end.bin", url, 65536, headers={"Range": f"bytes={size-65536}-{size-1}"}, expected_status=206)
    p = suffix.rfind(b"PK\x05\x06")
    eocd = struct.unpack_from("<4sHHHHIIH", suffix, p)
    central_size, central_offset = eocd[5:7]
    central = save("lean-zip-central.bin", url, 2 * 1024**2,
                   headers={"Range": f"bytes={central_offset}-{central_offset+central_size-1}"}, expected_status=206)
    if len(central) != central_size:
        raise RuntimeError("unexpected release ZIP central-directory length")
    p = 0
    zip_entries = []
    while p < len(central):
        values = struct.unpack_from("<4s6H3I5H2I", central, p)
        if values[0] != b"PK\x01\x02":
            raise RuntimeError("unexpected release ZIP central-directory signature")
        name_len, extra_len, comment_len = values[10:13]
        name = central[p + 46:p + 46 + name_len].decode("utf-8")
        zip_entries.append({"path": name, "compressed_bytes": values[8], "logical_bytes": values[9], "crc32": f"{values[7]:08x}"})
        p += 46 + name_len + extra_len + comment_len
    dump(PUBLIC / "lean-zip-inventory.json", zip_entries)
    # Inventory belongs in the lock as derived evidence with its own hash.
    b = (PUBLIC / "lean-zip-inventory.json").read_bytes()
    entries.append({"file": "lean-zip-inventory.json", "derived_from": ["lean-zip-end.bin", "lean-zip-central.bin"], "bytes": len(b), "sha256": sha(b)})
    missing_inventory = None
    try:
        save("mathlib-cache-commit.txt", f"https://lakecache.blob.core.windows.net/mathlib4/c/{math}", 1024**2)
    except urllib.error.HTTPError as error:
        missing_inventory = {"status": error.code, "reason": str(error.reason)}
    dump(PUBLIC / "public-lock.json", {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "pins": PINS, "entries": entries,
        "downloaded_public_bytes": total, "public_total_limit_bytes": PUBLIC_TOTAL_LIMIT,
        "source_inventory": source_inventory, "package_archives": package_archives,
        "lean_uncompressed_bytes": sum(x["logical_bytes"] for x in zip_entries),
        "mathlib_cache_commit_inventory_error": missing_inventory,
        "no_large_asset_download": True, "no_source_execution": True,
    })
    print(json.dumps({"public_files": len(entries), "downloaded_public_bytes": total, "no_installation": True}))


def normalize_declaration(s: str) -> str:
    # Metadata comparison mirrors stand.norm but deliberately returns no verdict.
    s = re.sub(r"/-.*?-/", " ", s, flags=re.S)
    s = re.sub(r"--[^\n]*", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def collect_support() -> None:
    """Small pinned public metadata/wheels; download only, no installation."""
    lock_path = PUBLIC / "public-lock.json"
    lock = json.loads(lock_path.read_bytes())
    total = lock["downloaded_public_bytes"]

    def save(name, url, limit=4*1024**2, expected=None):
        nonlocal total
        data, http = get(url, min(limit, PUBLIC_TOTAL_LIMIT-total))
        digest = sha(data)
        if expected and digest != expected:
            raise RuntimeError("public support artifact SHA-256 mismatch")
        (PUBLIC/name).write_bytes(data)
        lock["entries"] = [e for e in lock["entries"] if e["file"] != name]
        lock["entries"].append({"file": name, "url": url, "bytes": len(data), "sha256": digest, "http": http})
        total += len(data)
        return data

    server = PINS["leantar-source"]
    for path in ["src/ltar.rs", "src/tar.rs"]:
        save("leantar-" + path.replace("/", "-"), f"https://raw.githubusercontent.com/digama0/leangz/{server}/{path}")
    save("leantar-tag-object.json", "https://api.github.com/repos/digama0/leangz/git/tags/8eb3950c09f54e089c4d4abc38f68dd129c6589e")
    data = save("deepseek-minif2f.jsonl", f"https://raw.githubusercontent.com/deepseek-ai/DeepSeek-Prover-V1.5/{PINS['DeepSeek-Prover-V1.5']}/datasets/minif2f.jsonl")
    valid = [{"id": "valid/"+r["name"], "name": r["name"], "split": "valid", "header": r["header"],
              "informal": r["informal_prefix"], "statement": r["formal_statement"]}
             for r in (json.loads(line) for line in data.decode().splitlines()) if r["split"] == "valid"]
    if len(valid) != 244:
        raise RuntimeError("pinned valid metadata count differs")
    dump(PUBLIC/"problems-valid-rows.json", valid)
    b = (PUBLIC/"problems-valid-rows.json").read_bytes()
    lock["entries"] = [e for e in lock["entries"] if e["file"] != "problems-valid-rows.json"]
    lock["entries"].append({"file": "problems-valid-rows.json", "derived_from": "deepseek-minif2f.jsonl", "bytes": len(b), "sha256": sha(b)})
    wheels = []
    for name, version in [("pydantic", "2.10.6"), ("pydantic_core", "2.27.2"), ("annotated-types", "0.7.0"),
                          ("pygments", "2.18.0"), ("colorama", "0.4.6"), ("tabulate", "0.9.0")]:
        metadata = json.loads(save(f"pypi-{name}-{version}.json", f"https://pypi.org/pypi/{name}/{version}/json", 8*1024**2))
        options = [x for x in metadata["urls"] if x["filename"].endswith(".whl") and
                   (x["filename"].endswith("-py3-none-any.whl") or x["filename"].endswith("-py2.py3-none-any.whl") or
                    "cp312-cp312-manylinux_2_17_x86_64.manylinux2014_x86_64.whl" in x["filename"])]
        if len(options) != 1:
            raise RuntimeError("ambiguous fixed Linux/Python wheel for " + name)
        asset = options[0]
        save(asset["filename"], asset["url"], asset["size"], asset["digests"]["sha256"])
        wheels.append({"name": name, "version": version, "file": asset["filename"], "bytes": asset["size"], "sha256": asset["digests"]["sha256"]})
    lock["python_wheels"] = wheels
    lock["typing_extensions_reused_from_image"] = "4.16.0"
    lock["pins"] = PINS
    lock["downloaded_public_bytes"] = total
    lock["support_recorded_at_utc"] = datetime.now(timezone.utc).isoformat()
    for name in ["image-probe.json", "problems-test-rows.json"]:
        b = (PUBLIC/name).read_bytes()
        lock["entries"] = [e for e in lock["entries"] if e["file"] != name]
        lock["entries"].append({"file": name, "decoder_image_id": IMAGE, "bytes": len(b), "sha256": sha(b)})
    dump(lock_path, lock)
    print(json.dumps({"downloaded_public_bytes": total, "python_wheels": len(wheels), "no_installation": True}))


def report() -> None:
    lock_path = PUBLIC / "public-lock.json"
    lock = json.loads(lock_path.read_bytes())
    if lock["pins"] != PINS:
        raise RuntimeError("public pin manifest changed")
    for entry in lock["entries"]:
        b = (PUBLIC / entry["file"]).read_bytes()
        if len(b) != entry["bytes"] or sha(b) != entry["sha256"]:
            raise RuntimeError("frozen public evidence changed: " + entry["file"])
    decoded_path = PUBLIC / "problems-test-rows.json"
    # This file is decoded from the hash-checked public parquet by the fixed,
    # network-disabled/read-only scientific image, not by the host base packages.
    rows = json.loads(decoded_path.read_bytes())
    if len(rows) != 244:
        raise RuntimeError("unexpected pinned test question count")
    # Only public question metadata is recovered; other columns are not exported.
    book = {}
    for row in rows:
        prefix = HEADER + row["informal_prefix"]
        formal = row["formal_statement"]
        if not formal.startswith(prefix):
            raise RuntimeError("pinned setup.sh exact-prefix extraction does not apply to " + row["name"])
        item = {"id": "test/" + row["name"], "name": row["name"], "split": "test", "header": HEADER,
                "informal": row["informal_prefix"], "statement": formal[len(prefix):]}
        book[item["id"]] = item
    public_book = PUBLIC / "problems-test.jsonl"
    public_book.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in book.values()), encoding="utf-8")
    all_book = PUBLIC / "problems.jsonl"
    valid = json.loads((PUBLIC / "problems-valid-rows.json").read_bytes())
    all_book.write_text(public_book.read_text(encoding="utf-8") + "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in valid), encoding="utf-8")
    candidates_path = OUT / "legacy-candidates.json"
    b = candidates_path.read_bytes()
    old = json.loads(b)
    recovered = [r for run in old["runs"] if run["benchmark"] == "minif2f" for r in run["final_records"]]
    if {(r["run"], r["task"]) for r in recovered} != set(FIXED):
        raise RuntimeError("the fixed last-submit task set changed")
    results = []
    source_files = []
    for run in old["runs"]:
        if run["benchmark"] != "minif2f":
            continue
        for entry in run["source_files"]:
            path = Path(entry["path"])
            with path.open("rb") as stream:
                actual = hashlib.file_digest(stream, "sha256").hexdigest()
            source_files.append({**entry, "current_sha256": actual, "unchanged": actual == entry["sha256"]})
    for r in recovered:
        key = (r["run"], r["task"])
        if sha(r["candidate"].encode()) != FIXED[key] or r["candidate_sha256"] != FIXED[key]:
            raise RuntimeError("fixed candidate changed")
        if sha(r["description"].encode()) != r["description_sha256"]:
            raise RuntimeError("recovered description digest changed")
        item = book[r["task"]]
        match = re.search(r"```lean\n(.*?)\n```", r["description"], re.S)
        if not match:
            raise RuntimeError("old task has no Lean statement block")
        old_lean = match.group(1)
        old_informal = r["description"].split("```lean\n", 1)[0].rstrip("\n")
        theorem_re = r"theorem\s+" + re.escape(item["name"]) + r"\b.*?:= by"
        old_decl = re.search(theorem_re, old_lean, re.S)
        cand_decl = re.search(theorem_re, r["candidate"], re.S)
        official_norm = normalize_declaration(item["statement"])
        results.append({
            "run": r["run"], "task": r["task"], "candidate_sha256": FIXED[key], "candidate_bytes": r["candidate_bytes"],
            "call_id": r["call_id"], "unit": r["unit"], "seq": r["seq"], "at": r["at"],
            "declared_deadline_at": r["declared_deadline_at"], "deadline_eligible": r["at"] <= r["declared_deadline_at"],
            "selection_rule": r["selection_rule"], "description_sha256": r["description_sha256"],
            "official_problem_sha256": sha(json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()),
            "informal_exact_match_after_task_separator": old_informal == item["informal"].rstrip("\n"),
            "header_exact_match": old_lean.startswith(HEADER),
            "old_declaration_exact_match_after_header_separator": old_lean[len(HEADER):].lstrip("\n").rstrip("\n") == item["statement"].lstrip("\n").rstrip("\n"),
            "old_declaration_normalized_match": bool(old_decl) and normalize_declaration(old_decl.group()) == official_norm,
            "candidate_declaration_normalized_match": bool(cand_decl) and normalize_declaration(cand_decl.group()) == official_norm,
            "lean_compiles": None, "lean_sound": None, "precondition_only": True,
        })
    volumes = {x: shutil.disk_usage(x + ":/").free for x in ["C", "D", "E", "F"]}
    release = json.loads((PUBLIC / "lean-release-v4.15.0.json").read_bytes())
    assets = [{k: a.get(k) for k in ["id", "name", "size", "digest", "browser_download_url"]} for a in release["assets"] if a["name"] in ["lean-4.15.0-linux.zip", "lean-4.15.0-linux.tar.zst"]]
    plan_files = [ROOT/"scripts/benchmark-repair"/name for name in ["minif2f_preflight.py", "minif2f_restore.py", "minif2f_restore.ps1", "minif2f_restore.sh", "mathlib_cache_manifest.lean"]]
    result = {
        "recorded_at_utc": datetime.now(timezone.utc).isoformat(), "scope": "dependency provenance and fixed task preconditions only; no Lean regrading",
        "pins": PINS, "public_lock": {"path": str(lock_path), "sha256": sha(lock_path.read_bytes())},
        "public_downloaded_bytes": lock["downloaded_public_bytes"], "public_test_problem_count": len(book),
        "public_artifacts": lock["entries"],
        "public_all_problem_count": len(book) + len(valid),
        "public_all_problem_file": {"path": str(all_book), "bytes": all_book.stat().st_size, "sha256": sha(all_book.read_bytes())},
        "public_problem_file": {"path": str(public_book), "bytes": public_book.stat().st_size, "sha256": sha(public_book.read_bytes())},
        "metadata_reader": {"image_id": IMAGE, "library": "bundled pyarrow", "network": "none", "read_only": True,
                            "decoded_rows_file": str(decoded_path), "decoded_rows_sha256": sha(decoded_path.read_bytes())},
        "legacy_candidate_file_sha256": sha(b),
        "legacy_source_files": source_files, "legacy_sources_unchanged": all(x["unchanged"] for x in source_files),
        "records": results, "mismatches": [{"task": x["task"], "field": k} for x in results for k in ["informal_exact_match_after_task_separator", "header_exact_match", "old_declaration_exact_match_after_header_separator", "old_declaration_normalized_match", "candidate_declaration_normalized_match"] if not x[k]],
        "lean_release_assets": assets, "lean_uncompressed_bytes_measured_from_zip_directory": lock["lean_uncompressed_bytes"],
        "mathlib_source_inventory": lock["source_inventory"], "mathlib_pinned_packages": lock["package_archives"],
        "mathlib_cache_commit_inventory_error": lock["mathlib_cache_commit_inventory_error"],
        "storage": {"free_bytes_at_check": volumes,
                    "proposed_root": "E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415",
                    "D_alternative_root": "D:/objrun-experiment-cache/2026-10-08-minif2f", "D_alternative_status": "HOLD",
                    "root_created": False, "required_reserve_bytes": {"D": int(1.5*1024**3), "F": 1024**3},
                    "E_required_reserve_bytes": 3*1024**3, "E_directory_hard_cap_bytes": 14*1024**3,
                    "E_capacity_envelope_passes": volumes["E"] >= 17*1024**3 and volumes["F"] >= 1024**3,
                    "E_allocation_unit_bytes_readonly_probe": 4096,
                    "container_writable_layer_limit_bytes": 128*1024**2,
                    "ordinary_setup_peak_estimate_gib": {"low": 11.8, "high": 13.8},
                    "estimate_basis": "setup.sh 5 GB download + comment 5–6 GB oleans, measured Lean 1.367 GiB, source/support/build margin; not an actual Mathlib size inventory",
                    "ordinary_setup_fits_D_with_reserve": False,
                    "bounded_streaming_plan_verified": False,
                    "execution_gate": "HOLD pending root approval for the narrow E-root plan; no large download/install has occurred"},
        "existing_container_image_id": IMAGE, "docker_readonly_inspect_in_sandbox": "named pipe permission denied",
        "image_probe": json.loads((PUBLIC/"image-probe.json").read_bytes()),
        "python_support": {"wheels": lock["python_wheels"], "typing_extensions_from_image": "4.16.0",
                           "note": "Current frozen reconstruction; original setup.sh left these versions unpinned, so exact historical Python dependency equality is unverified."},
        "adapter_files": [{"path": str(ROOT/"examples/benchmark/minif2f"/name),
                           "sha256": sha((ROOT/"examples/benchmark/minif2f"/name).read_bytes())}
                          for name in ["stand.py", "setup.sh", "README.md"]],
        "reviewed_plan_files": [{"path": str(path), "bytes": path.stat().st_size, "sha256": sha(path.read_bytes())} for path in plan_files],
        "execution_plan": {
            "stage_order": ["Gate", "Download", "Bootstrap", "CacheDownload", "UnpackAndProbe", "Archive"],
            "completed_stages": ["Gate"], "large_download_approved": False, "E_root_write_approved": False,
            "candidate_execution_stage_present": False,
            "host_network_destinations": ["github.com/leanprover/lean4/releases/download/v4.15.0/lean-4.15.0-linux.zip", "lakecache.blob.core.windows.net/mathlib4/f/<official-public-cache-key>.ltar"],
            "host_network_method": "GET only; no candidate or private GT is available to the restoration worker",
            "container_network": "none", "container_image_pull": "never", "container_rootfs": "read-only",
            "container_tmpfs_bytes": 112*1024**2, "container_shm_bytes": 16*1024**2,
            "container_memory_bytes": 12*1024**3, "container_memory_swap_bytes": 12*1024**3,
            "container_logs": "Docker log driver none; stdout/stderr redirected to the owned E audit directory",
            "mounts": [
                {"source": "exact owned E root", "target": "/cache", "writable": True},
                {"source": str(PUBLIC), "target": "/public", "writable": False},
                {"source": "each minif2f_restore.py/.sh and mathlib_cache_manifest.lean file separately", "target": "/plan/<file>", "writable": False},
                {"source": str(ROOT/"examples/benchmark/minif2f/stand.py"), "target": "/plan/stand.py", "writable": False}],
            "cache_download_per_object_limit_bytes": 64*1024**2,
            "cache_unpack_per_file_rlimit_bytes": 64*1024**2,
            "cache_unpack_per_object_file_count_limit": 8,
            "cache_unpack_space_check": "current allocated envelope plus all eight possible 64 MiB files and path/receipt overhead must fit 14 GiB before the official unpacker runs",
            "cache_cleanup": "exact hashed .ltar removed only after successful official unpack and durable per-output SHA-256 receipts",
            "space_guard": "4096-byte E allocation units verified; host checks actual E>=3GiB/F>=1GiB and stops its own container on violation",
            "bootstrap_public_controls": ["True proof passes", "sorry compiles but is unsound", "False proof does not compile"],
            "legacy_inputs_mounted": False,
            "owned_cleanup": "Archive metadata first; exact owned-root marker/path and no reparse directories/live owned container; then native PowerShell Remove-Item -LiteralPath on that exact E root only",
            "build_execution_verified": False,
            "syntax_checks": {"python_ast": True, "powershell_parser": True, "bash_syntax": True, "lean_helper_compile": "pending toolchain"}},
        "backend": "local REPL only; Kimina remote service forbidden", "candidate_or_gt_sent_externally": False,
        "installer_executed": False, "lean_run": False, "kimina_golden_proof_zips_downloaded": False,
        "limitations": ["Official source hashes and question identity do not establish successful Lean elaboration or allowed axioms.",
                        "GitHub v4.15.0 release API has no asset SHA-256; exact asset bytes must be separately acquired and hashed before execution.",
                        "Mathlib commit cache inventory URL returned 404, which does not by itself establish that all module cache blobs are unavailable.",
                        "Old final-grading input digest was not saved; the fixed last submit is recovered by chronology, never selected by score."]
    }
    dump(OUT / "minif2f-restoration-preflight.json", result)
    print(json.dumps({"fixed_candidates": len(results), "identity_mismatches": len(result["mismatches"]), "lean_run": False, "legacy_sources_unchanged": result["legacy_sources_unchanged"]}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["collect", "collect-support", "report"])
    args = parser.parse_args()
    {"collect": collect, "collect-support": collect_support, "report": report}[args.command]()
