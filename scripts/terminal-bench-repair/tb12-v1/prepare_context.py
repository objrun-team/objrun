"""Stage a new TB12 private offline context on F. No Docker/model operations."""
import ast
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import tarfile
import uuid

from profiles import PROFILES

ROOT = Path(__file__).resolve().parents[3]
DOC = ROOT / "docs/repair-2026-10-08"
SELF = Path(__file__).resolve().parent
SCOPE_SHA = "79756c3601092682a9b19e733f84caebc4ab70d5bf3738faa1c1ce1e5ec6a729"
DEPOT_SHA = "c5d936affb8a132179daa0b0a59c2bb88b7db815cd4cf246b53b262c38e3be44"


def sha(path):
    value = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 ** 2):
            value.update(chunk)
    return value.hexdigest()


def main():
    scope_path = DOC / "tb-multitask-twelve-scope-v1/task-scope.json"
    depot_path = DOC / "tb-multitask-offline-depot-v2/manifest.json"
    assert sha(scope_path) == SCOPE_SHA and sha(depot_path) == DEPOT_SHA
    scope, depot = json.loads(scope_path.read_bytes()), json.loads(depot_path.read_bytes())
    assert set(scope["taskIds"]) == set(PROFILES)
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/contexts" / nonce
    output.mkdir(parents=True, exist_ok=False)
    files = []

    def copy(source, relative, expected=None):
        assert source.is_file() and not source.is_symlink()
        if expected:
            assert source.stat().st_size == expected["bytes"] and sha(source) == expected["sha256"]
        target = output / relative
        assert target.resolve().is_relative_to(output.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert sha(source) == sha(target)
        files.append({"source": str(source), "path": relative, "bytes": target.stat().st_size, "sha256": sha(target)})

    for asset in depot["assets"]:
        source = depot_path.parent / asset["path"]
        assert source.stat().st_size == asset["bytes"] and sha(source) == asset["sha256"]
        if source.suffix == ".whl":
            copy(source, "wheels/" + source.name, asset)
        if asset.get("distribution") == "chess":
            with tarfile.open(source, "r:gz") as archive:
                for pin in asset["modulePins"]:
                    module = Path(pin["path"])
                    member = archive.getmember("chess-1.11.2/chess/" + module.name)
                    assert member.isfile() and member.size == pin["bytes"]
                    assert hashlib.sha256(archive.extractfile(member).read()).hexdigest() == pin["sha256"]
                    copy(module, "chess/" + module.name, pin)
    assert sum(row["path"].startswith("wheels/") for row in files) == 18
    tasks = []
    for row in scope["records"]:
        task = row["taskId"]
        source_root = Path(row["publicInputs"][0]["path"]).parent
        original_tests = source_root / "tests"
        for group in ("publicInputs", "environmentSourcePins", "rubricSourcePins"):
            for pin in row[group]:
                path = Path(pin["path"])
                assert path.stat().st_size == pin["bytes"] and sha(path) == pin["sha256"]
        test_hashes = {}
        for path in sorted(original_tests.rglob("*")):
            if path.is_file():
                relative = path.relative_to(original_tests).as_posix()
                copy(path, "tasks/" + task + "/tests/" + relative)
                test_hashes[relative] = sha(path)
        input_root = source_root / "environment/inputs"
        if input_root.exists():
            for path in sorted(input_root.rglob("*")):
                if path.is_file():
                    copy(path, "tasks/" + task + "/inputs/" + path.relative_to(input_root).as_posix())
        tree = ast.parse((original_tests / "test_outputs.py").read_bytes())
        names = [node.name for node in tree.body if isinstance(node, ast.FunctionDef) and node.name.startswith("test_")]
        tasks.append({"taskId": task, "profile": PROFILES[task], "agentSeconds": row["agentSeconds"], "verifierSeconds": row["verifierSeconds"], "officialEnvironment": row["officialEnvironment"], "officialTestHashes": test_hashes, "staticTestNames": names})
    for name in ("private_checker.py", "profiles.py"):
        copy(SELF / name, "checker/" + name)
    copy(ROOT / "examples/benchmark/terminal-bench/nginx_client.py", "checker/nginx_client.py")
    packages = [name + "==" + version for name, version in depot["packages"].items() if name != "chess"]
    install = "#!/bin/sh\nset -eu\npython3 -m venv /opt/checker\n/opt/checker/bin/python -m pip install --no-index --no-deps --find-links=/opt/tb12/wheels " + " ".join(packages) + "\ncp -R /opt/tb12/chess /opt/checker/lib/python3.13/site-packages/chess\ncp /opt/tb12/checker/nginx_client.py /opt/checker/lib/python3.13/site-packages/nginx_client.py\n/opt/checker/bin/python -I -B -c 'import sys,numpy,pandas,pyarrow,chess,pytest,requests; assert sys.version_info[:3] == (3,13,7); assert chess.__version__ == \"1.11.2\"; print(\"tb12 offline imports completed\")'\n"
    (output / "install-offline.sh").write_text(install, encoding="utf-8", newline="\n")
    files.append({"path": "install-offline.sh", "bytes": (output / "install-offline.sh").stat().st_size, "sha256": sha(output / "install-offline.sh"), "source": "generated from pinned depot package list"})
    manifest = {"protocol": "tb12-private-offline-context-v1", "nonce": nonce, "createdAtUtc": datetime.now(timezone.utc).isoformat(), "scopeSha256": SCOPE_SHA, "depotSha256": DEPOT_SHA, "privateBaseImageId": depot["privateImage"], "Python": depot["Python"], "packages": depot["packages"], "tasks": tasks, "files": files, "actualPrivateImportsValidated": False, "actualCollectionValidated": False, "actualColdControlsValidated": False, "newModelCalls": 0, "DockerMutations": 0, "oldSourcesUnchanged": True, "paidReady": False}
    target = output / "context-manifest.json"
    target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"context": str(output), "manifest": str(target), "manifestSha256": sha(target), "files": len(files), "privateTasks": len(tasks), "staticOfficialTests": sum(len(task["staticTestNames"]) for task in tasks), "contextBytes": sum(item["bytes"] for item in files), "newModelCalls": 0, "DockerMutations": 0, "paidReady": False}))


if __name__ == "__main__":
    main()
