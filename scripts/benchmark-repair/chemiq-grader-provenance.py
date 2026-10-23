"""Read-only scoring provenance and a public-code archive; excludes all GT/payloads."""
import argparse
from datetime import datetime, timezone
import hashlib
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[2] if __file__ != "<stdin>" else Path("/")
OUT = ROOT / "docs/repair-2026-10-08"
CONTAINER = "objrun-repair-chemiq-local-opsin-raw-length"
EXPECTED_JAR = "d25bc08f41b8f6fcd6f35e18ab83f3b8d9218cdb003d55c5f74aaefe2e0c68ab"


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def file_record(path):
    path = Path(path)
    return {"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size}


def worker():
    home = Path(os.environ["TGENGIN_CHEMIQ_HOME"])
    vendor = home / "vendor/ChemIQ"
    # Match stand.py's public-module resolution; do NOT construct AnswerVerifier
    # or open questions/opsin_cache/control/payload files in this process.
    sys.path.insert(0, str(vendor))
    modules = {name: importlib.import_module(name) for name in ["utils.parser", "utils.answer_verifier", "rdkit", "rdkit.Chem", "rdkit.Chem.rdchem", "numpy", "requests", "urllib3", "charset_normalizer", "idna", "certifi"]}
    actual_modules = {name: {**file_record(mod.__file__), "version": getattr(mod, "__version__", None)} for name, mod in modules.items()}
    distributions = []
    for name in ["rdkit", "numpy", "requests", "urllib3", "charset-normalizer", "idna", "certifi"]:
        dist = importlib.metadata.distribution(name)
        files = []
        for member in dist.files or []:
            path = Path(dist.locate_file(member))
            if path.is_file() and path.suffix != ".pyc":
                files.append({"distribution_path": str(member), **file_record(path)})
        distributions.append({"name": name, "version": dist.version, "files": files,
            "total_bytes": sum(f["bytes"] for f in files), "file_manifest_sha256": hashlib.sha256(json.dumps(files, sort_keys=True, separators=(",", ":")).encode()).hexdigest()})
    mapped = set()
    for line in Path("/proc/1/maps").read_text().splitlines():
        fields = line.split()
        if len(fields) >= 6 and fields[-1].startswith("/"):
            path = Path(fields[-1])
            if path.is_file():
                mapped.add(str(path))
    mapped_files = [file_record(path) for path in sorted(mapped)]
    parser = modules["utils.parser"].AnswerParser
    verifier = modules["utils.answer_verifier"].AnswerVerifier
    print(json.dumps({"observed_at_utc": datetime.now(timezone.utc).isoformat(), "python_version": sys.version,
        "python_executable": file_record(Path(sys.executable).resolve()), "daemon_executable": str(Path("/proc/1/exe").resolve()),
        "daemon_cmdline": Path("/proc/1/cmdline").read_bytes().decode().strip("\0").split("\0"),
        "public_modules": actual_modules, "distributions": distributions, "daemon_mapped_files": mapped_files,
        "official_methods": {"parse": parser.parse.__code__.co_filename, "tuple_parser": parser._parse_list_of_tuples.__code__.co_filename,
            "tuple_equality": verifier._check_list_of_tuples.__code__.co_filename,
            "checker": verifier.check_answer.__wrapped__.__code__.co_filename,
            "smiles_canonicalization": verifier._canonicalize_smiles.__code__.co_filename},
        "inspection_method": "Separate read-only process in the existing container with identical vendor import path; actual daemon executable/cmdline/maps also read. No daemon injection and no GT or candidate input read."}, ensure_ascii=False))


def main(container, port):
    started = datetime.now(timezone.utc)
    got = subprocess.run(["docker", "inspect", container], capture_output=True, text=True, encoding="utf-8", check=True, timeout=30)
    inspect = json.loads(got.stdout)[0]
    if not inspect["State"]["Running"]:
        raise RuntimeError("Declared grader container is not running")
    config = {v.split("=", 1)[0]: v.split("=", 1)[1] for v in inspect["Config"]["Env"] if "=" in v}
    if config.get("TGENGIN_CHEMIQ_OPSIN_PROFILE") != "local-2.8" or config.get("TGENGIN_CHEMIQ_LENGTH_POLICY") != "raw-input-length":
        raise RuntimeError("Unexpected scoring profile")
    with urllib.request.urlopen(f"http://127.0.0.1:{port}/health", timeout=10) as response:
        health = json.load(response)
    if health.get("opsin", {}).get("jar_sha256") != EXPECTED_JAR or health["opsin"].get("rest_fallback") is not False or health.get("length_policy") != "raw-input-length":
        raise RuntimeError("Health/profile mismatch")
    measured = subprocess.run(["docker", "exec", "-i", container, "python", "-", "--worker"], input=Path(__file__).read_text(encoding="utf-8"),
        text=True, encoding="utf-8", capture_output=True, check=True, timeout=90)
    runtime = json.loads(measured.stdout)
    public_sources = [ROOT / "examples/benchmark/chemiq/stand.py", ROOT / "scripts/benchmark-repair/legacy_opsin_bridge.py",
        ROOT / "scripts/benchmark-repair/legacy_chemiq_profile.py", Path(__file__).resolve(),
        ROOT / ".phase1-data/chemiq/vendor/ChemIQ/utils/parser.py", ROOT / ".phase1-data/chemiq/vendor/ChemIQ/utils/answer_verifier.py",
        ROOT / ".phase1-data/chemiq/vendor/ChemIQ/LICENCE", ROOT / ".phase1-data/chemiq/source.json", ROOT / ".phase1-data/opsin/source.json",
        ROOT / ".phase1-data/opsin/opsin-cli-2.8.0-jar-with-dependencies.jar"]
    records = [{"relative_path": path.relative_to(ROOT).as_posix(), **file_record(path)} for path in public_sources]
    public_by_relative = {r["relative_path"]: r for r in records}
    official_match = {}
    for module in ["utils.parser", "utils.answer_verifier"]:
        record = runtime["public_modules"][module]
        relative = ".phase1-data/chemiq/" + record["path"].removeprefix("/oracle/")
        official_match[module] = public_by_relative[relative]["sha256"] == record["sha256"]
    if not all(official_match.values()):
        raise RuntimeError("Host public grader source differs from runtime-resolved source")
    jar = ROOT / ".phase1-data/opsin/opsin-cli-2.8.0-jar-with-dependencies.jar"
    if sha(jar) != EXPECTED_JAR:
        raise RuntimeError("Pinned OPSIN jar changed")
    service = json.loads((OUT / "legacy-chemiq-local-profile-raw-length-service.json").read_text(encoding="utf-8"))
    stand = ROOT / "examples/benchmark/chemiq/stand.py"
    if sha(stand) != service["adapter_sha256"]:
        raise RuntimeError("Stand source differs from actual startup manifest")
    process_path = OUT / "chemiq-nextwave-host-bridge-process.json"
    process = json.loads(process_path.read_text(encoding="utf-8-sig"))
    bridge = ROOT / "scripts/benchmark-repair/legacy_opsin_bridge.py"
    bridge_created = datetime.fromisoformat(process["CreationDate"])
    bridge_mtime = datetime.fromtimestamp(bridge.stat().st_mtime, timezone.utc)
    java = shutil.which("java")
    java_version = subprocess.run([java, "-version"], text=True, encoding="utf-8", capture_output=True, check=True, timeout=20)
    queue = OUT / "legacy-opsin-bridge"
    profile = json.loads((queue / "profile.json").read_text(encoding="utf-8"))
    status = json.loads((queue / "status.json").read_text(encoding="utf-8"))
    if process["ProcessId"] != status["pid"] or status.get("stopped") or datetime.now().timestamp() - status["heartbeat"] > 30:
        raise RuntimeError("Actual host bridge PID/heartbeat mismatch")
    archive_path = OUT / "chemiq-nextwave-public-grader-source.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in public_sources:
            archive.write(path, path.relative_to(ROOT).as_posix())
        archive.writestr("archive-scope.json", json.dumps({"allowlisted_public_sources": [r["relative_path"] for r in records],
            "excluded": [".env and credentials", "questions/chemiq.jsonl GT", "opsin_cache.json", "private controls/references", "bridge queue request/response/name/smiles/log files", "API requests/responses"]}, indent=2))
    if archive_path.stat().st_size > 64 * 1024 * 1024:
        raise RuntimeError("Public provenance archive exceeded bounded size")
    dataset = ROOT / ".phase1-data/chemiq/vendor/ChemIQ/questions/chemiq.jsonl"
    manifest = {"observed_at_utc": datetime.now(timezone.utc).isoformat(), "observation_started_at_utc": started.isoformat(),
        "profile": health, "actual_grader_container": {"name": container, "id": inspect["Id"], "image_id": inspect["Image"],
            "started_at": inspect["State"]["StartedAt"], "command": [inspect["Path"], *inspect["Args"]],
            "selected_environment": {k:v for k,v in config.items() if k.startswith("TGENGIN_CHEMIQ") or k in {"PYTHONPATH", "PYTHONDONTWRITEBYTECODE"}},
            "mounts": [{"source": m["Source"], "destination": m["Destination"], "read_write": m["RW"]} for m in inspect["Mounts"]]},
        "runtime_observed_imports_and_dependencies": runtime, "host_official_sources_match_runtime_imports": official_match,
        "host_bridge": {"process": process, "python_executable": file_record(process["ExecutablePath"]), "script": file_record(bridge),
            "script_last_modified_at_utc": bridge_mtime.isoformat(), "script_unmodified_since_process_start": bridge_mtime <= bridge_created,
            "public_profile_metadata": profile, "observed_heartbeat_status": status,
            "java_executable": file_record(Path(java).resolve()), "java_version": (java_version.stdout + java_version.stderr).strip(),
            "java_version_agrees_with_bridge": (java_version.stdout + java_version.stderr).strip() == profile["java_version"]},
        "public_source_files": records, "opsin_jar": file_record(jar), "official_vendor_source": json.loads((ROOT / ".phase1-data/chemiq/source.json").read_text(encoding="utf-8")),
        "reference_dataset_identity_only": file_record(dataset), "reference_dataset_archived": False,
        "public_archive": file_record(archive_path), "model_calls": 0, "images_pulled": 0, "candidate_payloads_read_or_archived": 0,
        "complete_grading_code_scope": "Includes stand, actual host bridge, public official parser and full answer_verifier (tuple/RDKit/OPSIN branches), fixed official OPSIN jar and vendor metadata; actual Python import files, distribution/native hashes and image ID are separately enumerated.",
        "limits": ["The public code/JAR archive is not a full OS/Java/Python runtime bundle. Installed Python distributions and actual daemon mapped binaries are fingerprinted; reconstruct them separately using the fixed image and declared mounted package files.",
            "Pure Python modules are resolved in a separate process with the daemon's environment and vendor path; no daemon injection is performed. Host bridge code is fingerprinted now and its modification time is compared with observed process creation.",
            "No GT, control answer, candidate, model receipt or credential is archived. Private dataset identity is recorded only by SHA.",
            "This explicit local2.8/raw-input-length protocol does not certify equality to old REST or the official parsed-length score."]}
    path = OUT / "chemiq-nextwave-grader-provenance.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    packages = ", ".join(r["name"] + "=" + r["version"] for r in runtime["distributions"])
    (OUT / "chemiq-nextwave-grader-provenance.md").write_text(f'''# ChemIQ 下一波评分来源补充

观察时刻：{manifest["observed_at_utc"]}。实际服务 {container}，image ID `{inspect["Image"]}`，local OPSIN 2.8.0 + raw-input-length，REST 回退禁用。

不能只用主runner归档的 stand.py 声称全部评分代码已保存。本次另保存实际宿主 bridge、固定官方 JAR、公开官方 parser 与完整 answer_verifier 源码，含原子映射 `_check_list_of_tuples` 和 RDKit 规范化比较；运行容器实测导入路径/版本/文件摘要与宿主源文件一致。

宿主 bridge PID {status["pid"]}，Python executable `{process["ExecutablePath"]}`，脚本在其启动后未修改：{bridge_mtime <= bridge_created}。Java 版本与桥接启动记录一致：{manifest["host_bridge"]["java_version_agrees_with_bridge"]}。JAR SHA `{EXPECTED_JAR}`。

实测 Python 依赖：{packages}。manifest记录每个相关distribution文件的 SHA/字节数，并读取实际 daemon /proc/1 的 executable、cmdline、mapped native 文件，记录容器image ID与只读挂载。单独检查进程用相同 vendor 路径解析公开 Python 模块，未给运行daemon注入代码。

公开来源包：[chemiq-nextwave-public-grader-source.zip](chemiq-nextwave-public-grader-source.zip)，{archive_path.stat().st_size} 字节；[独立manifest](chemiq-nextwave-grader-provenance.json)记录所有摘要。白名单仅公开评分源码、JAR、LICENSE、来源元数据与helper；没有GT文件、opsin_cache、控制答案、桥接候选payload、API原件或key。

这是评分代码及依赖provenance，不是完整OS/JRE/Python环境打包。Python mounted依赖以实际文件清单和摘要固定，OS/image与Java executable另记身份；数据版本仅记来源commit及SHA，不归档答案。每个新campaign应在自己的manifest中引用此独立manifest和公开来源ZIP的SHA，并在执行前复核这些摘要。

可复跑只读核对，在项目目录执行：

```powershell
& '.phase1-data/venv/Scripts/python.exe' -B -X utf8 'scripts/benchmark-repair/chemiq-grader-provenance.py'
```

helper只执行现有容器的读取/公开模块导入和本机health，不pull、不调用LLM或grader，不读取任何候选/控制内容；只写本补充manifest和公开白名单archive。宿主process metadata来自已保存的单PID只读检查，若桥接重启，应先更新该PID记录再复跑。
''', encoding="utf-8")
    print(json.dumps({"container_id": inspect["Id"], "image_id": inspect["Image"], "official_source_matches": official_match,
        "public_archive_bytes": archive_path.stat().st_size, "dependency_distribution_count": len(runtime["distributions"]),
        "dependency_files_fingerprinted": sum(len(r["files"]) for r in runtime["distributions"]), "bridge_script_unmodified_since_start": bridge_mtime <= bridge_created,
        "java_version_agrees": manifest["host_bridge"]["java_version_agrees_with_bridge"], "candidate_or_gt_contents_archived": False}, ensure_ascii=False))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--worker", action="store_true")
    parser.add_argument("--container", default=CONTAINER)
    parser.add_argument("--port", type=int, default=17918)
    args = parser.parse_args()
    worker() if args.worker else main(args.container, args.port)
