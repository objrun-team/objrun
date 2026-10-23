"""Measure actual support for the official 10 GiB Docker writable-layer quota."""
from datetime import datetime, timezone
import json
from pathlib import Path
import traceback
import uuid

from docker_owned import OwnedDocker, ROOT


def main():
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/storage-probes" / nonce
    native = OwnedDocker(output, nonce)
    result, failure, closures = None, None, []
    try:
        cid, state, create = native.create("quota-probe", "sha256:7082de4dab44888b5b5e9c0f9de09b30bc8cd28b329edc6d153fb5ce3dca5f24",
                                          "/bin/sh", ["-c", "sleep 120"], network="none", storage_mb=10240)
        assert state["HostConfig"]["StorageOpt"]["size"] == "10240m"
        result = {"cid": cid, "initialState": state, "create": create, "hardStorageOptionAccepted": True}
    except BaseException as error:
        failure = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        if hasattr(error, "receipt"):
            failure["nativeReceipt"] = error.receipt
    finally:
        for cid, role, name in native.open_actors():
            removal, absence = native.remove(cid)
            closures.append({"cid": cid, "removal": removal, "absence": absence})
        # Also observe failed-create namespace explicitly; do not delete a
        # guessed name if the daemon did not return/register an exact CID.
        namespace = native.checked(["ps", "-a", "--no-trunc", "--filter", "label=objrun.tb12.owner=" + nonce,
                                    "--format", "{{json .ID}}"])
        assert not native.text(namespace), "Unregistered exact owned CID requires separate recovery"
        native.close()
        target = output / "probe.json"
        target.write_text(json.dumps({"protocol": "tb12-actual-storage-quota-probe-v1", "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                                     "ownerNonce": nonce, "result": result, "failure": failure, "closures": closures,
                                     "emptyOwnedNamespaceReceipt": namespace, "allOwnedActorsClosed": True,
                                     "hardQuotaAccepted": result is not None, "modelCalls": 0}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(target), "hardQuotaAccepted": result is not None,
                          "allOwnedActorsClosed": True, "failure": failure, "modelCalls": 0}))


if __name__ == "__main__":
    main()
