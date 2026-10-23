"""Restore only the twelve previously frozen digests; retain scoped tag refs."""
from datetime import datetime, timezone
import json
from pathlib import Path
import traceback
import uuid

from docker_owned import OwnedDocker, ROOT, sha


def main():
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/public-cache-restorations" / nonce
    native = OwnedDocker(output, nonce)
    source = ROOT / "docs/repair-2026-10-08/tb-twelve-public-image-pulls-fd2e444e83ca407ebc1e172e10b16ac8/images.json"
    assert sha(source) == "f0f8e6419d55ff395725125a3c709d190368e494c1e2e33aa5b14fb238b0fc4b"
    rows, fatal = [], None
    try:
        for row in json.loads(source.read_bytes())["records"]:
            native.guard()
            initial = native.command(["image", "inspect", row["immutableImageId"], "--format", "{{json .Id}}"])
            pull = None
            if initial["exitCode"] != 0:
                stderr = Path(initial["stderr"]["path"]).read_text(encoding="utf-8").lower()
                assert "no such image:" in stderr
                assert len(row["repoDigests"]) == 1
                pull = native.checked(["pull", row["repoDigests"][0]], timeout=600)
            actual = native.checked(["image", "inspect", row["immutableImageId"], "--format", "{{json .Id}}"])
            assert json.loads(native.text(actual)) == row["immutableImageId"]
            # A new bench-local reference preserves this unchanged cache image.
            # This neither changes image bytes nor removes any existing tag.
            tag = "objrun/tb12-public-cache:" + nonce + "-" + row["taskId"]
            retained = native.checked(["image", "tag", row["immutableImageId"], tag])
            final = native.checked(["image", "inspect", tag, "--format", "{{json .Id}}"])
            assert json.loads(native.text(final)) == row["immutableImageId"]
            rows.append({"taskId": row["taskId"], "expectedImageId": row["immutableImageId"],
                         "originalRepoDigests": row["repoDigests"], "initial": initial, "pull": pull,
                         "actual": actual, "ownedRetentionTag": tag, "retained": retained, "final": final})
            print(json.dumps({"taskId": row["taskId"], "sameImmutableImageIdValidated": True,
                              "restoredFromOriginalDigest": pull is not None, "modelCalls": 0}), flush=True)
    except BaseException as error:
        fatal = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        if hasattr(error, "receipt"):
            fatal["nativeReceipt"] = error.receipt
    finally:
        native.close()
        target = output / "restoration.json"
        target.write_text(json.dumps({"protocol": "tb12-public-cache-restoration-v1", "ownerNonce": nonce,
                                     "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                                     "sourcePin": {"path": str(source), "sha256": sha(source)},
                                     "records": rows, "fatal": fatal, "validated": len(rows) == 12 and fatal is None,
                                     "modelCalls": 0, "containerMutations": 0, "globalPrunes": 0,
                                     "originalTagsRemoved": 0, "imageBytesChanged": False}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(target), "validatedImages": len(rows), "fatal": fatal, "modelCalls": 0}), flush=True)
    if fatal:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
