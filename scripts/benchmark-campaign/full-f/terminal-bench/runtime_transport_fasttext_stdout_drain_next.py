"""Frozen six-tool Node runtime, bounded one-shot MCP processes and receipts."""
import json
from pathlib import Path
import shutil
import os
import uuid
import time

from docker_owned import ROOT, sha
from profiles import SIX_TOOLS


def stage_runtime(output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = ROOT / "docs/repair-2026-10-10/full-f-rerun/terminal-bench/runtime-cache/91f4773388e8f5710a1ca42e1211cfe160c2d912b8d242ff73f987a27afd9d66"
    manifest = json.loads((original / "manifest.json").read_bytes())
    assert set(manifest["tools"]) == set(SIX_TOOLS)
    for name, expected in manifest["frozenSources"].items():
        assert sha(ROOT / name) == expected, "Actual runtime source differs: " + name
    files = []
    for name, expected in manifest["assets"].items():
        source, target = original / name, output / name
        assert sha(source) == expected
        assert not source.is_symlink() and source.resolve().parent == original.resolve()
        os.link(source, target)
        assert os.path.samefile(source, target)
        assert sha(target) == expected
        files.append({"path": str(target), "sha256": expected, "bytes": target.stat().st_size})
    launcher = output / "launcher.sh"
    launcher.write_text("#!/bin/sh\nexport LD_LIBRARY_PATH=/rt-lib\nexec /rt-node /rt-runtime.mjs\n", encoding="utf-8", newline="\n")
    receipt = {"protocol": "tb12-frozen-six-tool-runtime-v1", "sourceManifest": str(original / "manifest.json"),
               "sourceManifestSha256": sha(original / "manifest.json"), "manifest": manifest, "files": files,
               "launcher": {"path": str(launcher), "sha256": sha(launcher)}, "pythonReplacement": False}
    (output / "runtime.json").write_text(json.dumps(receipt, indent=2) + "\n", encoding="utf-8")
    return receipt


def ship_runtime(native, cid, staged):
    paths = {Path(item["path"]).name: Path(item["path"]) for item in staged["files"]}
    native.execute(cid, ["/bin/mkdir", "-p", "/rt-lib"])
    for name, destination in (("node", "/rt-node"), ("runtime.mjs", "/rt-runtime.mjs"),
                              ("libgcc_s.so.1", "/rt-lib/libgcc_s.so.1"),
                              ("libstdc++.so.6", "/rt-lib/libstdc++.so.6")):
        expected = staged["manifest"]["assets"][name]
        assert sha(paths[name]) == expected
        native.upload(paths[name], cid, destination)
    launcher = Path(staged["launcher"]["path"])
    assert sha(launcher) == staged["launcher"]["sha256"]
    native.upload(launcher, cid, "/rt")
    native.execute(cid, ["/bin/chmod", "0755", "/rt", "/rt-node"])
    # These observations occur before any candidate model action.
    proof = native.execute(cid, ["/bin/sh", "-c", "LD_LIBRARY_PATH=/rt-lib /rt-node --version"])
    assert native.text(proof) == "v22.22.2"
    running = native.assert_actor(cid)
    assert running["State"]["Pid"] > 0
    guest_code = 'const fs=require("node:fs"),s=fs.statfsSync("/app");console.log(JSON.stringify({availableStorageBytes:s.bavail*s.bsize,wallUnixMs:Date.now(),numericGuestPid:process.pid,numericParentPid:process.ppid,namespaces:Object.fromEntries(["pid","mnt","net"].map(n=>[n,fs.readlinkSync("/proc/self/ns/"+n)]))}));'
    host_start = time.time()
    calibration_receipt = native.execute(cid, ["/bin/sh", "-c", "LD_LIBRARY_PATH=/rt-lib /rt-node -e '" + guest_code + "'"])
    host_stop = time.time()
    guest = json.loads(native.text(calibration_receipt))
    assert guest["numericGuestPid"] > 0 and guest["wallUnixMs"] > 0
    assert guest["availableStorageBytes"] >= 10240 * 1024 ** 2
    calibration = {"hostStartUnixSeconds": host_start, "hostStopUnixSeconds": host_stop,
                   "guest": guest, "guestMinusHostSecondsInterval": [guest["wallUnixMs"] / 1000 - host_stop,
                                                                      guest["wallUnixMs"] / 1000 - host_start],
                   "receipt": calibration_receipt, "measuredBeforeAnyModel": True}
    return {"protocol": "tb12-shipped-runtime-before-model-v1", "candidateCid": cid,
            "runningState": running, "nodeVersionReceipt": proof, "runtimeManifest": staged,
            "numericPidAndClockCalibration": calibration}


def admitted_runtime_observation(native, cid):
    # Existing admitted actor only. Container startup still uses OwnedDocker.guard.
    assert sha(Path(__file__).with_name('docker_owned.py')) == native.source_sha, 'Owned native source changed'
    state = native.assert_actor(cid)
    assert state['State']['Running'] and not state['State']['Paused']
    observations = {}
    for drive in ('E:/', 'F:/'):
        try:
            observations[drive] = {'actualFreeBytes': shutil.disk_usage(drive).free}
        except Exception as error:
            observations[drive] = {'observationErrorType': type(error).__name__}
    return {'policy': 'observe_existing_admitted_actor', 'startupDiskGateUnchanged': True,
            'observations': observations}


def rpc(native, cid, method, params, timeout):
    observation = admitted_runtime_observation(native, cid)
    state = native.assert_actor(cid)
    assert state["State"]["Running"] and not state["State"]["Paused"]
    messages = [{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {"protocolVersion": "2026-07-28"}},
                {"jsonrpc": "2.0", "id": 2, "method": method, "params": params}]
    raw = ("\n".join(json.dumps(message, separators=(",", ":")) for message in messages) + "\n").encode()
    assert len(raw) <= 1024 ** 2
    guest_output='/tmp/tb12-rpc-'+uuid.uuid4().hex+'.jsonl'
    # Original Node stdout is synchronous to a regular file; cat drains it to Docker.
    command='umask 077; set -C; /rt > '+guest_output+'; code=$?; cat '+guest_output+'; rm -f '+guest_output+'; exit "$code"'
    receipt = native.checked(["exec", "-i", cid, "/bin/sh", "-c", command], stdin=raw, timeout=timeout)
    receipt['originalRuntimeStdoutDrain']={'guestFile':guest_output,'runtimeSourceUnchanged':True,'toolOutputLimitsUnchanged':True}
    receipt['admittedRuntimeDiskObservation'] = observation
    rows = [json.loads(line) for line in native.text(receipt).splitlines()]
    assert len(rows) == 2 and {row["id"] for row in rows} == {1, 2}
    assert all(row["jsonrpc"] == "2.0" for row in rows)
    initialized = next(row for row in rows if row["id"] == 1)
    assert initialized["result"]["serverInfo"]["name"] == "tgengin-runtime"
    return next(row for row in rows if row["id"] == 2), receipt


def call_tool(native, cid, tool, arguments, deadline):
    assert tool in SIX_TOOLS and isinstance(arguments, dict)
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise TimeoutError("Official candidate wall deadline elapsed")
    if tool == "bash":
        arguments = dict(arguments)
        arguments["timeout_ms"] = min(int(arguments.get("timeout_ms", 120000)), int(remaining * 1000))
        assert arguments["timeout_ms"] > 0
    result, receipt = rpc(native, cid, "tools/call", {"name": tool, "arguments": arguments}, min(remaining + 5, 3605))
    if "error" in result:
        raise RuntimeError("Runtime protocol error: " + str(result["error"]))
    value = result["result"]
    if value.get("isError"):
        return {"candidateToolError": True, "message": "".join(item.get("text", "") for item in value.get("content", []))}, receipt
    if "structuredContent" in value:
        return value["structuredContent"], receipt
    text = "".join(item.get("text", "") for item in value.get("content", []))
    try:
        return json.loads(text), receipt
    except ValueError:
        return text, receipt

