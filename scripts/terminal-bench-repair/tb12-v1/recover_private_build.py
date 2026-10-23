"""Read-only Docker reconciliation of the first owned build's parser failure.

Preserves the failed report and SQLite exactly. Does not replay commit/removal,
retag images, change any shared registry/lock, or call a model.
"""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import uuid

from docker_owned import OwnedDocker, ROOT, INSPECT, sha

OLD_NONCE = "17a4a713cc01436d9da1c6b37cf14465"
OLD_NATIVE_SHA = "bd8529ac4a0410555d09c6ce36471cceaa904e6df39c036dc85cbbd4b7b66198"
CID = "d6e9b8c0c0c5186e930a6a3ccae2ed0a2e1f023c5cc91daecd541843339d5cd2"
IMAGE = "sha256:7ed55f0192315d98b3b322a581be9ac78e0ec7d6770c5631b801883760cbc096"


def main():
    original = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/private-builds" / OLD_NONCE
    report_path = original / "build.json"
    report_pin = {"path": str(report_path), "sha256": sha(report_path)}
    failed = json.loads(report_path.read_bytes())
    assert failed["ownerNonce"] == OLD_NONCE and failed["builderCid"] == CID
    assert failed["completed"] is False and failed["failureType"] == "AssertionError"
    assert failed["completedBuilderState"]["State"]["ExitCode"] == 0
    install = failed["installAndImportReceipt"]
    assert install["exitCode"] == 0 and install["closeObserved"]
    assert sha(Path(install["stdout"]["path"])) == install["stdout"]["sha256"]
    assert "tb12 offline imports completed" in Path(install["stdout"]["path"]).read_text()
    context_path = Path(failed["contextManifest"]["path"])
    assert sha(context_path) == failed["contextManifest"]["sha256"]
    context = json.loads(context_path.read_bytes())
    for file in context["files"]:
        assert sha(context_path.parent / file["path"]) == file["sha256"]
    db = sqlite3.connect(f"file:{original / 'owned-native.sqlite'}?mode=ro", uri=True)
    original_receipts = {number: json.loads(text) for number, text in db.execute("SELECT id,json FROM command")}
    db.close()
    commit, removal, absence = (original_receipts[number] for number in (8, 10, 11))
    tag = "objrun/tb12-private-offline-base:" + OLD_NONCE + "-0"
    assert commit["exitCode"] == 0 and commit["closeObserved"] and commit["argv"][-2:] == [CID, tag]
    assert sha(Path(commit["stdout"]["path"])) == commit["stdout"]["sha256"]
    assert Path(commit["stdout"]["path"]).read_text().strip().splitlines()[-1] == IMAGE
    assert removal["exitCode"] == 0 and removal["closeObserved"] and removal["argv"][-1] == CID
    assert absence["exitCode"] != 0 and CID in Path(absence["stderr"]["path"]).read_text()
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/private-build-reconciliations" / nonce
    native = OwnedDocker(output, nonce)
    image_receipt = native.checked(["image", "inspect", "--format", '{"Id":{{json .Id}},"RepoTags":{{json .RepoTags}},"Created":{{json .Created}},"RootFS":{{json .RootFS}},"Labels":{{json .Config.Labels}}}', IMAGE])
    image = json.loads(native.text(image_receipt))
    assert image["Id"] == IMAGE and tag in image["RepoTags"]
    assert image["Labels"]["objrun.tb12.owner"] == OLD_NONCE
    assert image["Labels"]["objrun.tb12.native-source"] == OLD_NATIVE_SHA
    assert image["Labels"]["objrun.tb12.role"] == "offline-base-builder"
    fresh_absence = native.command(["inspect", "--format", INSPECT, CID])
    absent_text = Path(fresh_absence["stderr"]["path"]).read_text().lower()
    assert fresh_absence["exitCode"] != 0 and "no such object:" in absent_text and CID in absent_text
    native.close()
    assert sha(report_path) == report_pin["sha256"]
    result = {"protocol": "tb12-private-build-parser-reconciliation-v1", "createdAtUtc": datetime.now(timezone.utc).isoformat(), "originalFailedReport": report_pin, "originalOwnerNonce": OLD_NONCE, "contextManifest": failed["contextManifest"], "actualPrivateImportsValidated": True, "immutablePrivateImageId": IMAGE, "originalCommitReceipt": commit, "freshImageInspect": image_receipt, "freshImageIdentity": image, "originalRemovalReceipt": removal, "freshBuilderAbsenceReceipt": fresh_absence, "allOwnedBuildersClosed": True, "originalFailurePreserved": True, "dockerMutations": 0, "modelCalls": 0, "privateScorerReady": False, "paidReady": False}
    target = output / "reconciliation.json"
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"report": str(target), "actualPrivateImportsValidated": True, "imageId": IMAGE, "allOwnedBuildersClosed": True, "originalFailurePreserved": True, "dockerMutations": 0, "modelCalls": 0, "paidReady": False}))


if __name__ == "__main__":
    main()
