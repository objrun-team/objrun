"""Build a bench-owned sealed offline interpreter from the fixed public image.

Uses Docker create/copy/run/commit, not a network installer or a fake test.sh.
The actual import receipt precedes the image pin. No provider calls or paid lock.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import traceback
import uuid

from docker_owned import OwnedDocker, ROOT, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--context-manifest", required=True)
    args = parser.parse_args()
    manifest_path = Path(args.context_manifest).resolve()
    assert manifest_path.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/contexts")
    manifest = json.loads(manifest_path.read_bytes())
    assert manifest["protocol"] == "tb12-private-offline-context-v1" and len(manifest["tasks"]) == 12
    for entry in manifest["files"]:
        path = manifest_path.parent / entry["path"]
        assert path.resolve().is_relative_to(manifest_path.parent)
        assert not path.is_symlink() and path.stat().st_size == entry["bytes"] and sha(path) == entry["sha256"]
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/private-builds" / nonce
    native = OwnedDocker(output, nonce)
    receipt = {"protocol": "tb12-private-offline-build-v1", "ownerNonce": nonce, "contextManifest": {"path": str(manifest_path), "sha256": sha(manifest_path)}, "startedAtUtc": datetime.now(timezone.utc).isoformat(), "completed": False, "modelCalls": 0, "privateScorerReady": False, "paidReady": False}
    try:
        receipt["resourcesBefore"] = native.guard()
        cid, state, create = native.create("offline-base-builder", manifest["privateBaseImageId"], "/bin/sh", ["/opt/tb12/install-offline.sh"], network="none")
        receipt.update({"builderCid": cid, "initialBuilderState": state, "createReceipt": create})
        receipt["contextCopyReceipt"] = native.upload(manifest_path.parent, cid, "/opt/tb12")
        receipt["installAndImportReceipt"] = native.start(cid, attach=True, timeout=600)
        final = native.assert_actor(cid)
        assert final["State"]["Status"] == "exited" and final["State"]["ExitCode"] == 0
        assert "tb12 offline imports completed" in native.text(receipt["installAndImportReceipt"])
        receipt["completedBuilderState"] = final
        image, commit = native.commit(cid, "private-offline-base")
        receipt.update({"immutablePrivateImageId": image, "commitReceipt": commit, "actualPrivateImportsValidated": True, "completed": True})
    except BaseException as error:
        receipt["failureType"] = type(error).__name__
        receipt["failure"] = str(error)
        receipt["failureTraceback"] = traceback.format_exc()
        if hasattr(error, "receipt"):
            receipt["failedNativeReceipt"] = error.receipt
    finally:
        closures = []
        for cid, role, name in native.open_actors():
            try:
                closed, absent = native.remove(cid)
                closures.append({"cid": cid, "role": role, "removal": closed, "absence": absent})
            except BaseException as error:
                closures.append({"cid": cid, "role": role, "closureFailed": True, "failureType": type(error).__name__, "failure": str(error)})
        receipt["closures"] = closures
        receipt["allOwnedBuildersClosed"] = not native.open_actors()
        receipt["finishedAtUtc"] = datetime.now(timezone.utc).isoformat()
        if receipt["allOwnedBuildersClosed"]:
            native.close()
        target = output / "build.json"
        target.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(target), "completed": receipt["completed"], "allOwnedBuildersClosed": receipt["allOwnedBuildersClosed"], "imageId": receipt.get("immutablePrivateImageId"), "failure": receipt.get("failure"), "newModelCalls": 0, "privateScorerReady": False, "paidReady": False}, ensure_ascii=False))
    if not receipt["completed"] or not receipt["allOwnedBuildersClosed"]:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
