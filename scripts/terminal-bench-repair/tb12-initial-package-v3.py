"""Create a real partial/full ZIP from corrected-run receipts, stdlib only."""
import argparse
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import shutil
import sqlite3
import zipfile

ROOT = Path(__file__).resolve().parents[2]


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        while block := stream.read(1024 ** 2):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--master", required=True)
    args = parser.parse_args()
    master = Path(args.master).resolve()
    assert master.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-fast-runs-v3")
    def doc(path):
        return json.loads(Path(path).read_bytes())
    manifest = doc(master / "manifest.json")
    lane_paths = [ROOT / "docs/repair-2026-10-09/tb12-runs-v1" / (manifest["runId"] + "-1")]
    repair = master / "process-lane-0.json"
    if repair.exists():
        lane_paths.append(Path(doc(repair)["output"]))
    else:
        lane_paths.append(ROOT / "docs/repair-2026-10-09/tb12-runs-v1" / (manifest["runId"] + "-0"))
    records, diagnostics = [], []
    for home in lane_paths:
        for path in sorted(home.glob("task-*.json")):
            value = doc(path)
            if not value.get("acceptance"):
                continue
            value["rawRecordPath"] = str(path)
            if value["acceptance"].get("valid"):
                records.append(value)
            else:
                diagnostics.append(value)
    diagnostic_home = ROOT / "docs/repair-2026-10-09/tb12-runs-v1" / (manifest["runId"] + "-0")
    if diagnostic_home not in lane_paths:
        for path in diagnostic_home.glob("task-*.json"):
            value = doc(path)
            value["rawRecordPath"] = str(path)
            diagnostics.append(value)
    pairs = {(value["officialId"], value["arm"]): value for value in records}
    assert len(pairs) == len(records) and all(task in manifest["taskIds"] and arm in ("U", "F") for task, arm in pairs)
    assert records, "A preparation-only archive is not a trial result package"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = master / "deliveries" / stamp
    output.mkdir(parents=True, exist_ok=False)
    staging = output / "package"
    staging.mkdir()
    exported, excluded, included = [], [], set()
    secrets = []
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        found = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if found and re.search("KEY|TOKEN|SECRET|PASSWORD", found[1], re.I):
            value = found[2].strip().strip("'\"")
            if len(value) >= 6:
                secrets.append(value.encode())
    for home in set(lane_paths + [diagnostic_home]):
        for config_path in home.glob("workers/*/config.yaml"):
            config = doc(config_path)
            secrets.extend(config["api"][key].encode() for key in ("token", "publisherToken"))
    assert secrets
    def scan(source):
        opener = gzip.open if source.name.endswith(".json.gz") else open
        carry = b""
        maximum = max(map(len, secrets))
        with opener(source, "rb") as stream:
            while block := stream.read(1024 ** 2):
                value = carry + block
                assert all(needle not in value for needle in secrets), "Credential value in export"
                carry = value[-maximum:]
    def include(source, name, expected=None):
        source = Path(source).resolve()
        if (str(source), name) in included:
            return
        assert source.is_file() and not source.is_symlink() and source.is_relative_to(ROOT)
        if source.name == "config.yaml" or source.name == "broker-key.pem" or source.name == ".env":
            excluded.append({"source": str(source), "reason": "private credential/config/TLS key"})
            return
        scan(source)
        checksum = sha(source)
        assert expected is None or checksum == expected
        target = staging / name
        assert target.is_relative_to(staging) and not target.exists()
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert sha(target) == checksum
        included.add((str(source), name))
        exported.append({"path": name.replace("\\", "/"), "bytes": target.stat().st_size, "sha256": checksum, "source": str(source)})
    def tree(folder, prefix):
        if folder.exists():
            for source in sorted(folder.rglob("*")):
                if source.is_file():
                    include(source, prefix + "/" + str(source.relative_to(folder)))
    def referenced_receipts(value, home):
        if isinstance(value, dict):
            if isinstance(value.get("path"), str) and isinstance(value.get("sha256"), str):
                source = Path(value["path"])
                if source.is_file() and source.resolve().is_relative_to(home.resolve()):
                    include(source, "receipts/" + home.name + "/" + str(source.relative_to(home)), value["sha256"])
            for child in value.values():
                referenced_receipts(child, home)
        elif isinstance(value, list):
            for child in value:
                referenced_receipts(child, home)
    for value in records + diagnostics:
        path = Path(value["rawRecordPath"])
        home = path.parent
        prefix = ("tasks" if value in records else "diagnostics") + "/" + value["officialId"] + "/" + value["arm"]
        include(path, prefix + "/record.json")
        referenced_receipts(value, home)
        engine_close = doc(value["engineClosePin"]["path"])
        referenced_receipts(engine_close, home)
        tree(home / "workers" / (str(value["index"]) + "-" + value["arm"]), prefix + "/engine")
        for call in value["calls"]:
            for key in ("coreRequestPin", "providerRequestPin", "failedResponsePin"):
                if call.get(key):
                    pin = call[key]
                    include(Path(pin["path"]), "raw/" + home.name + "/" + Path(pin["path"]).name, pin["sha256"])
            for key in ("requestFile", "responseFile"):
                if call.get(key):
                    source = Path(call[key])
                    if source.is_file():
                        checksum = call.get("requestCompressedSha256" if key == "requestFile" else "responseCompressedSha256")
                        include(source, "raw/" + home.name + "/" + source.name, checksum)
        # Finished grade directories are immutable and contain original pytest
        # stdout, captured artifacts and the trusted final result frame.
        for grade in (home / "stand-process/stand/grades").glob("*/grade.json"):
            body = doc(grade)
            if body["candidateCid"] == value["candidateCid"]:
                tree(grade.parent, "grading/" + home.name + "/" + grade.parent.name)
                referenced_receipts(body, home)
    for home in set(lane_paths + [diagnostic_home]):
        # A SQLite backup is a consistent point-in-time snapshot even while
        # another task is running. Only closed native command streams follow.
        database = home / "stand-process/stand/owned-native.sqlite"
        if database.exists():
            source_db = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
            backup_path = output / (home.name + "-native-snapshot.sqlite")
            backup_db = sqlite3.connect(backup_path)
            try:
                source_db.backup(backup_db)
                native_rows = [json.loads(row[0]) for row in backup_db.execute("SELECT json FROM command")]
            finally:
                backup_db.close()
                source_db.close()
            # Stage the backup directly; its source remains the trusted native
            # journal and no candidate code is run during the snapshot.
            target_backup = staging / "provenance" / home.name / "owned-native-snapshot.sqlite"
            target_backup.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(backup_path, target_backup)
            exported.append({"path": str(target_backup.relative_to(staging)).replace("\\", "/"),
                             "bytes": target_backup.stat().st_size, "sha256": sha(target_backup),
                             "source": str(database), "liveConsistentSqliteBackup": True})
            for value in native_rows:
                if value.get("closeObserved") and isinstance(value.get("exitCode"), int):
                    referenced_receipts(value, home)
        tree(home / "source-snapshots", "source/" + home.name)
        tree(home / "frozen-engine", "source/" + home.name + "/frozen-engine")
        for name in ("manifest.json", "summary.json", "fast-admission.json", "fast-cash-registration.json", "provider-native-close.json"):
            if (home / name).exists():
                include(home / name, "provenance/" + home.name + "/" + name)
                referenced_receipts(doc(home / name), home)
        for name in ("stand-close.json", "stand.stdout", "stand.stderr"):
            source = home / "stand-process" / name
            if source.exists() and (home / "stand-process/stand-close.json").exists():
                include(source, "provenance/" + home.name + "/stand-process/" + name)
        for name in ("cash-config.json", "cash-close.json"):
            source = home / "cash" / name
            if source.exists():
                include(source, "provenance/" + home.name + "/cash/" + name)
        for folder, name in (("provider", "api-events.jsonl"), ("cash", "cash-events.jsonl")):
            source = home / folder / name
            if source.exists():
                raw = source.read_bytes()
                raw = raw[:raw.rfind(b"\n")+1]
                assert all(needle not in raw for needle in secrets)
                target_prefix = staging / "raw" / home.name / name
                target_prefix.parent.mkdir(parents=True, exist_ok=True)
                target_prefix.write_bytes(raw)
                exported.append({"path": str(target_prefix.relative_to(staging)).replace("\\", "/"),
                                 "bytes": len(raw), "sha256": sha(target_prefix), "source": str(source), "appendOnlyPrefixSnapshot": True})
    include(master / "manifest.json", "provenance/master-manifest.json")
    for name in ("all-process-lanes-closed.json", "bench-lock-release.json", "process-lane-0.json", "process-lane-0-closed.json"):
        if (master / name).exists():
            include(master / name, "provenance/" + name)
    selection_path = Path(manifest["scopePin"]["path"])
    include(selection_path, "selection.json", manifest["scopePin"]["sha256"])
    original_tasks = ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks"
    for task_id in manifest["taskIds"]:
        tree(original_tasks / task_id, "original-tasks/" + task_id)
    include(ROOT / ".phase1-data/terminal-bench/source.json", "provenance/benchmark-source.json")
    include(Path(manifest["directivePin"]["path"]), "provenance/speed-user-directive.json", manifest["directivePin"]["sha256"])
    context = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/contexts/21a1519e23d04c83bed16a636b7e3f19/context-manifest.json"
    include(context, "provenance/environment-and-dependencies.json")
    include(ROOT / "docs/repair-2026-10-08/tb-multitask-offline-depot-v2/manifest.json", "provenance/offline-dependency-manifest.json")
    include(ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/paired-cold/repair-2026-10-09T12-27-20-995Z/independent-audit.json", "provenance/existing-corrected-cold-review.json")
    rows = []
    for task_id in manifest["taskIds"]:
        rows.append({"taskId": task_id, **{arm: {"status": ("通过" if value["acceptance"]["passed"] else value["acceptance"]["outcome"]),
          "passed": value["acceptance"]["passed"], "modelRequests": len(value["calls"])} if (value := pairs.get((task_id, arm))) else {"status": "未完成"} for arm in ("U", "F")}})
    score = {arm: sum(value["acceptance"]["passed"] for value in records if value["arm"] == arm) for arm in ("U", "F")}
    summary = {"protocol": "tb12-initial-delivery-summary-v3", "runId": manifest["runId"], "plannedTaskRuns": 24,
               "completedValidTaskRuns": len(records), "diagnosticInvalidRuns": len(diagnostics), "incompleteTaskRuns": 24-len(records),
               "score": score, "rows": rows, "initialDelivery": True, "allCertificationsComplete": False,
               "fullIndependentReview": "pending", "old17RecordsIncludedInComparison": False,
               "modelRequestsInIncludedCompletedRecords": sum(len(value["calls"]) for value in records),
               "candidateArtifactLimitations": "No-candidate/expired generations may have no final artifact snapshot; complete tools and model traces are preserved.",
               "sourceConfigSecretsExcluded": True, "actualCredentialValuesChecked": len(secrets)}
    summary_path = staging / "summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    lines = ["# Terminal-Bench 修正版初版结果包", "", "部分结果" if len(records)<24 else "固定清单运行结果已齐备；完整认证尚未完成", "",
             f"固定 12 题 U/F，共计划 24 次；已完成有效记录 {len(records)} 次，未完成 {24-len(records)} 次。当前 U {score['U']}，F {score['F']}。评分认证错误单独列入 diagnostics，不作为模型失败。", "",
             "| 题目 | U | F |", "|---|---|---|"]
    for row in rows:
        lines.append(f"| {row['taskId']} | {row['U']['status']} | {row['F']['status']} |")
    lines += ["", "参数：deepseek-flash；temperature 0；seed 42；thinking disabled；每请求输出 8192 token；原任务 agent/verifier 时限保留。两个独立进程通道，每题 U 后 F。旧 17 条记录不混入本包对照。", "",
              "实际任务记录、完整轨迹、已有候选产物、工具/最终评分原始回执、原始模型请求响应均装入 ZIP。原生评分器 stdout 与原 CTRF 保留在 grading；完整 trace 与关闭后的引擎数据库在 tasks。", "",
              "局限：本包是初版；额外独立审阅、全生命周期认证仍 pending。nginx 使用窄活态接口；Docker 无 10 GiB 硬配额，仅边界采样；无候选等情况不代表原测试已执行。模型服务别名不是固定底层检查点。保留真实失败与原测试输出，不把未完成项当作通过。", "",
              "运行仍在继续时，包仅包含已有完整任务记录，不对仍在写入的全局账本作最终认证。源码/环境/依赖清单及已有离线联调审阅收入 provenance、source。敏感运行配置和 TLS 私钥排除。离线入口 verify-package.py 只检查成员大小与 SHA256，不运行候选或模型。", ""]
    (staging / "README.md").write_text("\n".join(lines), encoding="utf-8")
    verifier = "import hashlib,json,sys,zipfile\nfrom pathlib import Path\np=Path(sys.argv[1]);z=zipfile.ZipFile(p);m=json.loads(z.read('package-manifest.json'));assert z.testzip() is None\nfor r in m['files']:\n b=z.read(r['path']);assert len(b)==r['bytes'] and hashlib.sha256(b).hexdigest()==r['sha256']\nprint('PASS: '+str(len(m['files']))+' members; no model or candidate execution')\n"
    (staging / "verify-package.py").write_text(verifier, encoding="utf-8")
    for name in ("README.md", "summary.json", "verify-package.py"):
        path = staging / name
        exported.append({"path": name, "bytes": path.stat().st_size, "sha256": sha(path), "source": "generated from actual included records"})
    index = {"protocol": "tb12-initial-package-manifest-v3", "runId": manifest["runId"], "createdAtUtc": datetime.now(timezone.utc).isoformat(),
             "partial": len(records)<24, "files": exported, "excludedPrivateFiles": excluded, "modelCallsByPackager": 0}
    (staging / "package-manifest.json").write_text(json.dumps(index, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output / ("Terminal-Bench-corrected-" + ("partial" if len(records)<24 else "complete") + "-" + stamp + ".zip")
    with zipfile.ZipFile(archive,"x",zipfile.ZIP_DEFLATED,compresslevel=3,allowZip64=True) as bundle:
        for path in sorted(staging.rglob("*")):
            if path.is_file():
                bundle.write(path,str(path.relative_to(staging)).replace("\\","/"))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == {value["path"] for value in exported} | {"package-manifest.json"}
    receipt = {"protocol": "tb12-initial-package-receipt-v3", "archive": str(archive), "bytes": archive.stat().st_size,
               "sha256": sha(archive), "members": len(exported)+1, "completedValidTaskRuns": len(records), "score": score,
               "partial": len(records)<24, "readableAndMembersVerifiedOnce": True, "modelCallsByPackager": 0}
    (output / "package-receipt.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    (master / "latest-delivery.json").write_text(json.dumps(receipt,indent=2)+"\n",encoding="utf-8")
    (master / "修正版初版结果.md").write_text("\n".join(lines), encoding="utf-8")
    (master / "修正版初版结果.json").write_text(json.dumps(summary,ensure_ascii=False,indent=2)+"\n",encoding="utf-8")
    print(json.dumps(receipt))


if __name__ == "__main__":
    main()
