"""Actual authenticated hook/repair/seal lifecycle with no provider or model."""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import queue
import shlex
import socket
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.request
import uuid

from docker_owned import ROOT, sha


def main():
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/stand-probes" / nonce
    output.mkdir(parents=True, exist_ok=False)
    token = uuid.uuid4().hex + uuid.uuid4().hex
    proof = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/private-build-reconciliations/e83d7ee537be456fb1fc23f43cf8892d/reconciliation.json"
    command = [sys.executable, "-I", "-B", "-X", "utf8", str(Path(__file__).parent / "stand_v1.py"),
               "--base-proof", str(proof), "--output", str(output / "stand")]
    # -I intentionally excludes the script folder: add only this trusted module
    # directory with a fixed runpy launcher, rather than any candidate path.
    command = [sys.executable, "-B", "-X", "utf8", str(Path(__file__).parent / "stand_v1.py"),
               "--base-proof", str(proof), "--output", str(output / "stand")]
    process = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE, env={**os.environ, "OBJRUN_TB12_STAND_TOKEN": token})
    ready_queue, overflow = queue.Queue(), threading.Event()
    faults, total, paths = [], [0, 0], [output / "child.stdout", output / "child.stderr"]
    def drain(stream, number):
        try:
            with paths[number].open("xb") as target:
                while raw := stream.readline(2 * 1024 ** 2 + 1):
                    total[number] += len(raw)
                    if total[number] > 2 * 1024 ** 2:
                        overflow.set()
                        process.kill()
                        break
                    target.write(raw)
                    target.flush()
                    if number == 0 and raw.startswith(b'{"protocol": "tb12-stand-ready-v1"'):
                        ready_queue.put(json.loads(raw))
        except BaseException as error:
            faults.append(type(error).__name__)
    readers = [threading.Thread(target=drain, args=(stream, number), daemon=True) for number, stream in enumerate((process.stdout, process.stderr))]
    for reader in readers:
        reader.start()
    requests, fatal, ready, child_exit, port_closed = [], None, None, None, False
    started = datetime.now(timezone.utc).isoformat()
    def call(path, body, authorized=True, expected=200):
        raw = json.dumps(body).encode()
        headers = {"content-type": "application/json"}
        if authorized:
            headers["X-ObjRun-Grader-Token"] = token
        req = urllib.request.Request("http://127.0.0.1:" + str(ready["port"]) + path, raw, headers)
        before = time.time()
        try:
            response = urllib.request.urlopen(req, timeout=120)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            data = response.read(2 * 1024 ** 2 + 1)
            assert len(data) <= 2 * 1024 ** 2
            value = json.loads(data)
            requests.append({"path": path, "body": body, "authorized": authorized,
                             "httpStatus": response.status, "response": value, "hostStart": before,
                             "hostStop": time.time(), "rawRequestSha256": hashlib.sha256(raw).hexdigest(),
                             "rawResponseSha256": hashlib.sha256(data).hexdigest(), "tokenExcluded": True})
            assert response.status == expected, (path, response.status, value)
            return value
    try:
        ready = ready_queue.get(timeout=60)
        assert ready["pid"] == process.pid and ready["modelCalls"] == 0
        call("/up", {}, authorized=False, expected=401)
        place, attempt = "tb12:control/F/chess-best-move", "tb12-control/F/chess-best-move"
        call("/up", {"taskId": "chess-best-move", "place": place, "attemptId": attempt, "arm": "F"})
        call("/begin", {"place": place})
        base = "http://host.docker.internal:" + str(ready["port"])
        for forged in (False, True):
            script = 'fetch(' + json.dumps(base + "/place") + ',{method:"POST",headers:{"content-type":"application/json"' + (',"X-ObjRun-Grader-Token":"invalid-probe"' if forged else "") + '},body:"{}"}).then(async r=>{console.log(r.status);if(r.status!==401)process.exit(7)}).catch(()=>process.exit(8));'
            result = call("/place", {"place": place, "op": "tool", "tool": "bash",
                                    "args": {"command": "LD_LIBRARY_PATH=/rt-lib /rt-node -e " + shlex.quote(script), "timeout_ms": 10000}})
            assert result["code"] == 0 and "401" in result["stdout"]
        def evaluate(label, expected):
            body = {"input": {"task": {"id": attempt, "place": place}, "result": {"body": label}}, "feed": []}
            assert call("/ran", body)["value"] is True
            body["feed"] = [{"value": True}]
            assert call("/passed", body)["value"] is expected
        evaluate("control-empty", False)
        call("/place", {"place": place, "op": "tool", "tool": "write",
                        "args": {"file_path": "/app/move.txt", "content": "g2g4 e2e4\n"}})
        evaluate("control-repaired", True)
        call("/seal", {"place": place})
        call("/place", {"place": place, "op": "tool", "tool": "write",
                        "args": {"file_path": "/app/move.txt", "content": "a1a2\n"}}, expected=409)
        evaluate("control-final", True)
        call("/stop", {"place": place})
    except BaseException as error:
        fatal = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
    finally:
        if ready is not None and process.poll() is None:
            try:
                call("/close", {})
            except BaseException as error:
                faults.append("close:" + type(error).__name__)
        try:
            child_exit = process.wait(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            child_exit = process.wait(timeout=10)
            faults.append("child-close-timeout")
        for reader in readers:
            reader.join(timeout=10)
        for stream in (process.stdout, process.stderr):
            stream.close()
        if ready is not None:
            probe = socket.socket()
            try:
                probe.bind(("127.0.0.1", ready["port"]))
                port_closed = True
            except OSError:
                port_closed = False
            finally:
                probe.close()
        record = json.loads((output / "stand/stand-receipts.json").read_bytes()) if (output / "stand/stand-receipts.json").exists() else None
        closed = bool(record is not None and not record["openActors"] and child_exit == 0 and port_closed and all(not reader.is_alive() for reader in readers))
        validated = fatal is None and not faults and not overflow.is_set() and closed
        target = output / "probe.json"
        target.write_text(json.dumps({"protocol": "tb12-authenticated-stand-control-v1",
                                     "modelCalls": 0, "paidReady": False, "validated": validated,
                                     "childPid": process.pid, "childArgv": command, "startedAtUtc": started,
                                     "sourcePins": [{"path": str(path), "sha256": sha(path)} for path in Path(__file__).parent.glob("*.py")],
                                     "requests": requests, "fatal": fatal, "faults": faults, "childExit": child_exit,
                                     "allOwnedActorsClosed": closed, "portClosed": port_closed,
                                     "childCapture": [{"path": str(path), "sha256": sha(path), "bytes": path.stat().st_size} for path in paths],
                                     "tokenExcluded": True}, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(target), "validated": validated, "fatal": fatal, "faults": faults,
                          "allOwnedActorsClosed": closed, "modelCalls": 0}), flush=True)
    if not validated:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
