"""Archive the exact nginx execution files and declared artifacts, without credentials."""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[2]
campaign, directory, store = sys.argv[1:4]
directory, store = Path(directory), Path(store)
snapshot = json.loads((directory / "source.json").read_text(encoding="utf-8"))
archive = store / "frozen-source.zip"
grader_files = {"examples/benchmark/terminal-bench/" + name for name in
                ["stand.py", "isolated_verifier.py", "nginx_client.py", "prepare_runtime.py", "prepare_verifier_dependencies.py", "objective.ts"]}
grader_files.add("examples/benchmark/_lib/grader_status.py")
selected = []
for item in snapshot["files"] + snapshot["repairFiles"]:
    name = item["path"]
    if (name.startswith("app/src/") or name.startswith("scripts/benchmark-repair/")
        or name in ["test/_lib.ts", "app/package.json", "app/bun.lock", "app/tsconfig.json",
                    "scripts/phase1/source-snapshot.ts"] or name in grader_files):
        raw = (ROOT / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise RuntimeError("Cannot archive changed executed source: " + name)
        selected.append((name, raw))
for item in snapshot["artifacts"]:
    path = Path(item["path"])
    if path.name == ".env" or "secret" in item["name"].lower():
        raise RuntimeError("Credential artifacts cannot enter the archive")
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != item["sha256"]:
        raise RuntimeError("Artifact hash changed: " + item["name"])
    selected.append(("artifacts/" + item["name"], raw))
dependencies = []
for file in sorted((ROOT / "app/node_modules").rglob("*")):
    if file.is_file() and file.suffix in [".js", ".cjs", ".mjs", ".json", ".wasm", ".node", ".ts"] and ".bin" not in file.parts:
        raw = file.read_bytes()
        name = file.relative_to(ROOT).as_posix()
        dependencies.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        selected.append((name, raw))
if not dependencies:
    raise RuntimeError("Actual engine dependencies must be archived")
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for name, raw in selected:
        output.writestr(name, raw)
record = {"campaign": campaign, "archive": str(archive), "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
          "archiveBytes": archive.stat().st_size, "sourceExecutionDigest": snapshot["executionDigest"],
          "dependencyFiles": dependencies, "artifacts": snapshot["artifacts"],
          "scope": "Frozen engine/runner/grader source, actual engine dependencies, six-tool executor assets and three official nginx files; no .env or host/broker tokens."}
(directory / "frozen-source.json").write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"archived": len(selected), "archiveBytes": record["archiveBytes"], "sha256": record["archiveSha256"]}))
