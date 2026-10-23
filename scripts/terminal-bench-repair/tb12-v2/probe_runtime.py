"""Actual frozen six-tool probes of immutable public task images; model-free."""
from datetime import datetime, timezone
import json
import time
import traceback
import uuid

from artifacts import capture_file
from docker_owned import OwnedDocker, ROOT, sha
from runtime_transport import stage_runtime, ship_runtime, call_tool, rpc


def main():
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/runtime-probes" / nonce
    native = OwnedDocker(output, nonce)
    staged = stage_runtime(output / "runtime")
    index_path = ROOT / "docs/repair-2026-10-08/tb-twelve-public-image-pulls-fd2e444e83ca407ebc1e172e10b16ac8/images.json"
    assert sha(index_path) == "f0f8e6419d55ff395725125a3c709d190368e494c1e2e33aa5b14fb238b0fc4b"
    images = json.loads(index_path.read_bytes())
    records, fatal, closures = [], None, []
    try:
        for task in images["records"]:
            task_id = task["taskId"]
            folder = output / task_id
            folder.mkdir()
            cid, initial, create = native.create("runtime-probe-" + task_id, task["immutableImageId"], "/bin/sh", ["-c", "sleep 3600"], network="none")
            native.start(cid)
            before = ship_runtime(native, cid, staged)
            definitions, listed = rpc(native, cid, "tools/list", {}, 30)
            available = {item["name"] for item in definitions["result"]["tools"]}
            assert set(staged["manifest"]["tools"]).issubset(available)
            public_image = None
            if task_id == "chess-best-move":
                public_image = capture_file(native, cid, "/app/chess_board.png", 2 * 1024 ** 2, folder / "public-input")
                assert public_image["exists"], "Public board image missing"
            calls = []
            actions = [
                ("bash", {"command": "printf 'before\\n' > /app/objrun-tb12-smoke.txt", "timeout_ms": 10000}),
                ("read", {"file_path": "/app/objrun-tb12-smoke.txt"}),
                ("write", {"file_path": "/app/objrun-tb12-smoke.txt", "content": "written\n"}),
                ("edit", {"file_path": "/app/objrun-tb12-smoke.txt", "old_string": "written", "new_string": "edited"}),
                ("glob", {"pattern": "objrun-tb12-smoke.txt", "path": "/app"}),
                ("grep", {"pattern": "edited", "path": "/app/objrun-tb12-smoke.txt"}),
            ]
            for tool, args in actions:
                value, receipt = call_tool(native, cid, tool, args, time.monotonic() + 30)
                assert not (isinstance(value, dict) and value.get("candidateToolError")), (tool, value)
                if tool == "read":
                    assert "before" in json.dumps(value)
                elif tool == "glob":
                    assert "objrun-tb12-smoke.txt" in json.dumps(value)
                elif tool == "grep":
                    assert "edited" in json.dumps(value)
                calls.append({"tool": tool, "args": args, "value": value, "receipt": receipt})
            verification, checked = call_tool(native, cid, "read", {"file_path": "/app/objrun-tb12-smoke.txt"}, time.monotonic() + 30)
            assert "edited" in json.dumps(verification) and "written" not in json.dumps(verification)
            removal, absence = native.remove(cid)
            records.append({"taskId": task_id, "cid": cid, "initialState": initial, "create": create,
                            "beforeAnyModel": before, "toolsList": listed, "publicImage": public_image,
                            "calls": calls, "finalRead": {"value": verification, "receipt": checked},
                            "removal": removal, "absence": absence})
            print(json.dumps({"taskId": task_id, "actualSixToolsValidated": True, "allClosed": True, "modelCalls": 0}), flush=True)
    except BaseException as error:
        fatal = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        if hasattr(error, "receipt"):
            fatal["nativeReceipt"] = error.receipt
    finally:
        for cid, role, name in native.open_actors():
            try:
                removal, absence = native.remove(cid)
                closures.append({"cid": cid, "removal": removal, "absence": absence})
            except BaseException as error:
                closures.append({"cid": cid, "failure": type(error).__name__, "message": str(error)})
        closed = not native.open_actors()
        if closed:
            native.close()
        target = output / "probes.json"
        target.write_text(json.dumps({"protocol": "tb12-actual-six-tool-runtime-probes-v1",
                                     "createdAtUtc": datetime.now(timezone.utc).isoformat(), "records": records,
                                     "runtime": staged, "fatal": fatal, "closures": closures,
                                     "allOwnedContainersClosed": closed, "validated": len(records) == 12 and fatal is None,
                                     "modelCalls": 0, "paidReady": False}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(target), "actualTasksValidated": len(records), "fatal": fatal, "allClosed": closed}), flush=True)
    if fatal or not closed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
