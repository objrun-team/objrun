"""Archive closed real TB trial and verify every exported byte without execution."""
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


def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 ** 2):
            result.update(block)
    return result.hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    args = parser.parse_args()
    home = Path(args.run_directory).resolve()
    assert home.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-runs-v1")
    def read(path):
        return json.loads(Path(path).read_bytes())
    summary, manifest = read(home / "summary.json"), read(home / "manifest.json")
    certificate = read(home / "independent/close-certificate.json")
    admission = read(home / "paid-admission.json")
    audit = read(home / "independent/raw-audit.json")
    deep_review = read(home / "independent/deep-review.json")
    assert summary["operationalComplete"] and summary["providerKind"] == "real-provider"
    assert audit["integrityValid"] and certificate["kind"] == "score-and-financial"
    assert deep_review["integrityValid"] and len(deep_review["tasks"]) == 24
    assert audit["result"]["distinctTaskCount"] == 12 and audit["result"]["taskRuns"] == 24
    assert len(summary["taskPins"]) == 24 and summary["modelCalls"] > 0
    assert read(home / "entry-closed.json")["canonicalOwnerReleased"]
    assert read(home / "tb12-paid-resource-run.json")["released"]
    assert int(admission["selectedNewEnvelopeNanoCny"]) == 9000000000
    assert int(admission["carryNanoCny"]) == 8392180000
    output = ROOT / "docs/repair-2026-10-09/tb12-packages-v1" / manifest["runId"]
    output.mkdir(parents=True, exist_ok=False)
    staging = output / "package"
    staging.mkdir()
    mappings, exclusions = [], []
    actual_secrets = []
    for line in (ROOT / ".env").read_text(encoding="utf-8-sig").splitlines():
        match = re.match(r"^\s*(?:export\s+)?([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$", line)
        if match and re.search(r"KEY|TOKEN|SECRET|PASSWORD", match[1], re.I):
            value = match[2].strip()
            if len(value) > 1 and value[:1] in {"'", '"'} and value[-1:] == value[:1]:
                value = value[1:-1]
            if len(value) >= 6:
                actual_secrets.append(value.encode())
    preparation = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1"
    for path in list(home.glob("workers/*/config.yaml")) + list(preparation.rglob("config.yaml")):
        config = read(path)
        assert isinstance(config.get("api", {}).get("token"), str) and isinstance(config.get("api", {}).get("publisherToken"), str)
        actual_secrets.extend(config["api"][key].encode() for key in ("token", "publisherToken"))
    assert actual_secrets
    def scan(path):
        opener = gzip.open if path.name.endswith(".json.gz") else open
        carry = b""
        maximum = max(map(len, actual_secrets))
        with opener(path, "rb") as stream:
            while block := stream.read(1024 ** 2):
                value = carry + block
                assert all(secret not in value for secret in actual_secrets), "Actual credential value in export"
                carry = value[-maximum:]
    def include(source, name, expected=None):
        source = Path(source).resolve()
        assert source.is_file() and not source.is_symlink() and source.is_relative_to(ROOT)
        assert ".env" not in source.parts
        checksum = digest(source)
        if expected is not None:
            assert checksum == expected
        target = staging / name
        assert target.is_relative_to(staging) and not target.exists()
        scan(source)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        assert digest(target) == checksum
        mappings.append({"originalPath": str(source), "archivePath": name.replace("\\", "/"),
                         "bytes": target.stat().st_size, "sha256": checksum})
    for source in sorted(home.rglob("*")):
        if not source.is_file():
            continue
        name = str(source.relative_to(home)).replace("\\", "/")
        if re.fullmatch(r"workers/\d+-[UF]/config.yaml", name) or name.endswith("/broker/broker-key.pem"):
            exclusions.append({"originalPath": str(source), "reason": "private runtime credential or TLS private key"})
            continue
        include(source, "trial/" + name)
    preparation = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1"
    for source in sorted(preparation.rglob("*")):
        if not source.is_file():
            continue
        name = str(source.relative_to(preparation)).replace("\\", "/")
        if source.name == "config.yaml" or name.endswith("/broker/broker-key.pem"):
            exclusions.append({"originalPath": str(source), "reason": "private preparation runtime credential or TLS private key"})
            continue
        include(source, "preparation/" + name)
    for control in sorted(home.parent.iterdir()):
        if control == home or not (control / "zero-forward-control.json").exists():
            continue
        assert read(control / "entry-closed.json")["canonicalOwnerReleased"]
        for source in sorted(control.rglob("*")):
            if source.is_file():
                include(source, "zero-forward-controls/" + control.name + "/" + str(source.relative_to(control)))
    references = [manifest["officialScope"], manifest["contextManifest"], manifest["baseProof"],
                  admission["balancePin"], admission["pricesPin"], admission["crossFamilyPin"],
                  admission["readinessPin"], admission["headroomDirective"]]
    included = {row["originalPath"] for row in mappings}
    for pin in references:
        if pin["path"] not in included:
            source = Path(pin["path"])
            include(source, "references/" + str(source.relative_to(ROOT)), pin["sha256"])
            included.add(pin["path"])
    context_path = Path(manifest["contextManifest"]["path"])
    for value in read(context_path)["files"]:
        source = context_path.parent / value["path"]
        if str(source) not in included:
            include(source, "dependencies/context/" + value["path"], value["sha256"])
            included.add(str(source))
    depot_path = ROOT / "docs/repair-2026-10-08/tb-multitask-offline-depot-v2/manifest.json"
    include(depot_path, "dependencies/depot/manifest.json")
    for value in read(depot_path)["assets"]:
        include(depot_path.parent / value["path"], "dependencies/depot/" + value["path"], value["sha256"])
    for task_id in manifest["taskIds"]:
        task_root = ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks" / task_id
        for source in sorted(task_root.rglob("*")):
            if source.is_file():
                include(source, "official-tasks/" + task_id + "/" + str(source.relative_to(task_root)))
    for filename in ("source.json",):
        include(ROOT / ".phase1-data/terminal-bench" / filename, "official-tasks/" + filename)
    include(ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/README.md", "PREPARATION.md")
    include(Path(__file__), "review/package_builder.py")
    include(ROOT / "scripts/terminal-bench-repair/tb12-deep-review-v1.py", "review/deep_review.py")
    include(ROOT / "scripts/terminal-bench-repair/tb12-verify-package-v1.py", "review/verify_package.py")
    by_original = {row["originalPath"]: row for row in mappings}
    source_aliases = []
    for row in read(home / "source-snapshots/manifest.json")["files"]:
        original_pin, snapshot = row["originalPin"], row["snapshotPin"]
        exported = by_original[snapshot["path"]]
        assert original_pin["sha256"] == snapshot["sha256"] == exported["sha256"]
        source_aliases.append({"originalPath": original_pin["path"], "archivePath": exported["archivePath"],
                               "sha256": original_pin["sha256"], "bytes": original_pin["bytes"]})
    metadata = {"protocol": "tb12-complete-real-package-v1", "runId": manifest["runId"],
                "createdAtUtc": datetime.now(timezone.utc).isoformat(), "distinctTaskCount": 12, "realTaskRuns": 24,
                "modelRequests": summary["modelCalls"], "rawAuditResult": audit["result"],
                "userBudgetCny": "9", "retainedOriginalUnknownCarryCny": "8.39218",
                "actualCredentialValuesChecked": len(actual_secrets), "credentialValuesNotPrinted": True,
                "files": mappings, "sourceAliases": source_aliases, "excludedPrivateFiles": exclusions,
                "fullRunExecuted": False, "oldSingleNginxIncluded": False,
                "hardStorageQuotaEnforced": False, "publicSelectionNotPerformanceSelection": True}
    index = staging / "package-manifest.json"
    index.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    archive = output / (manifest["runId"] + ".zip")
    with zipfile.ZipFile(archive, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as bundle:
        for source in sorted(staging.rglob("*")):
            if source.is_file():
                bundle.write(source, str(source.relative_to(staging)).replace("\\", "/"))
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert set(bundle.namelist()) == {row["archivePath"] for row in mappings} | {"package-manifest.json"}
        for row in mappings:
            result = hashlib.sha256()
            with bundle.open(row["archivePath"]) as stream:
                while block := stream.read(1024 ** 2):
                    result.update(block)
            assert result.hexdigest() == row["sha256"]
    target = output / "package-receipt.json"
    target.write_text(json.dumps({"protocol": "tb12-complete-package-byte-review-v1", "runId": manifest["runId"],
                                 "package": str(staging), "archive": str(archive), "archiveBytes": archive.stat().st_size,
                                 "archiveSha256": digest(archive), "manifestSha256": digest(index),
                                 "allExportedBytesIndependentlyVerified": True, "fileCount": len(mappings),
                                 "modelCallsByPackager": 0, "candidateCodeExecuted": False}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"receipt": str(target), "archive": str(archive), "fileCount": len(mappings), "modelCalls": 0}))


if __name__ == "__main__":
    main()
