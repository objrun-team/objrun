"""Preserve executed source and installed dependencies, excluding credentials and task data."""
import hashlib
import json
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
campaign = sys.argv[1]
path = ROOT / "docs/repair-2026-10-08/campaigns" / campaign
snapshot = json.loads((path / "source.json").read_text(encoding="utf-8"))
manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
archive = ROOT / ".phase1-data/repair" / campaign / "frozen-source.zip"
archive.parent.mkdir(parents=True, exist_ok=True)
selected = []
grader_files = [f"examples/benchmark/{slug}/{'grader.py' if slug == 'cmt' else 'stand.py'}" for slug in manifest["benchmarks"]] + ["examples/benchmark/_lib/gradelib.py"]
for item in snapshot["files"] + snapshot["repairFiles"]:
    name = item["path"]
    used = name.startswith("app/src/") or name in ["app/package.json", "app/bun.lock", "app/tsconfig.json", "test/_lib.ts", "scripts/phase1/source-snapshot.ts"] or name in grader_files or name.startswith("scripts/repair-2026-10-08/")
    if used:
        raw = (ROOT / name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise RuntimeError(f"Cannot backfill changed source: {name}")
        selected.append((name, raw))
dependencies = ROOT / "app/node_modules"
dependency_files = []
if not dependencies.is_dir():
    raise RuntimeError("Locate the actual installed runtime dependencies before archiving")
for file in sorted(dependencies.rglob("*")):
    if file.is_file() and file.suffix in [".js", ".cjs", ".mjs", ".json", ".wasm", ".node", ".ts"] and ".bin" not in file.parts:
        name = file.relative_to(ROOT).as_posix()
        raw = file.read_bytes()
        dependency_files.append({"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)})
        selected.append((name, raw))
with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as output:
    for name, raw in selected:
        output.writestr(name, raw)
evidence = {"campaign": campaign, "sourceExecutionDigest": snapshot["executionDigest"],
    "archive": str(archive), "archiveSha256": hashlib.sha256(archive.read_bytes()).hexdigest(), "archiveBytes": archive.stat().st_size,
    "sourceFiles": len(selected) - len(dependency_files), "dependencyFiles": dependency_files,
    "dependencyDigest": hashlib.sha256(json.dumps(dependency_files, separators=(",", ":")).encode()).hexdigest(),
    "scope": "Verified executed source and the actual installed Node dependencies; no .env, API credential, reference answers or historical stores are copied.",
    "limits": "This preserves current software, not a frozen provider checkpoint. Run data, dataset provenance and grader image ID remain separate artifacts."}
(path / "frozen-source.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
print(json.dumps({"campaign": campaign, "sourceFiles": evidence["sourceFiles"], "dependencies": len(dependency_files), "archiveBytes": evidence["archiveBytes"], "archiveSha256": evidence["archiveSha256"]}))
