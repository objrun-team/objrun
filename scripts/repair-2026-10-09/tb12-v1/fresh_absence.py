"""Fresh read-only exact PID/CID and exclusive port observations."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import socket
import sqlite3
import subprocess
import uuid

from docker_owned import OwnedDocker, ROOT, sha


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-directory", required=True)
    parser.add_argument("--owner-nonce", required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    home = Path(args.run_directory).resolve()
    assert home.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-runs-v1")
    output = home / "fresh-absence" / uuid.uuid4().hex
    native = OwnedDocker(output)
    pids, ports, cids, closures = set(), set(), set(), []
    for target in sorted(home.glob("workers/*/engine-close.json")) + list(home.glob("stand-process/stand-close.json")):
        value = json.loads(target.read_bytes())
        assert value["exitObserved"] and value["closeObserved"]
        pids.add(value["pid"])
        if value.get("port"):
            ports.add(value["port"])
        closures.append({"path": str(target), "sha256": sha(target)})
    gateway = home / "provider-native-close.json"
    if gateway.exists():
        value = json.loads(gateway.read_bytes())
        assert value["serverClosed"]
        ports.add(value["port"])
        closures.append({"path": str(gateway), "sha256": sha(gateway)})
    for target in home.glob("stand-process/stand/grades/*/broker/broker-receipt.json"):
        value = json.loads(target.read_bytes())
        assert value["threadClosed"] and value["socketClosed"]
        ports.add(value["port"])
        closures.append({"path": str(target), "sha256": sha(target)})
    database = home / "stand-process/stand/owned-native.sqlite"
    if database.exists():
        connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
        try:
            for cid, closed in connection.execute("SELECT cid,closed FROM actor"):
                assert closed == 1 and re.fullmatch(r"[a-f0-9]{64}", cid)
                cids.add(cid)
            for raw, in connection.execute("SELECT json FROM command"):
                value = json.loads(raw)
                assert value["closeObserved"]
                pids.add(value["nativePid"])
        finally:
            connection.close()
    # JSON reports only numeric requested PIDs; never enumerate command lines.
    observed = subprocess.run(["powershell.exe", "-NoProfile", "-NonInteractive", "-Command",
                               "$p = @(" + ",".join(str(pid) for pid in sorted(pids)) + "); @($p | ForEach-Object { if (Get-Process -Id $_ -ErrorAction SilentlyContinue) { $_ } }) | ConvertTo-Json -Compress"],
                              capture_output=True, timeout=30, creationflags=subprocess.CREATE_NO_WINDOW)
    assert observed.returncode == 0 and not observed.stderr and not observed.stdout.strip(), "Exact PID remains or PID observation failed"
    pid_receipt = output / "pid-observation.json"
    pid_receipt.write_text(json.dumps({"requestedPids": sorted(pids), "nativeObservationExitCode": observed.returncode,
                                      "observerSourceSha256": sha(Path(__file__)), "allAbsent": True}) + "\n", encoding="utf-8")
    receipts = [{"path": str(pid_receipt), "sha256": sha(pid_receipt)}]
    for cid in sorted(cids):
        receipt = native.command(["inspect", "--format", "{{json .Id}}", cid])
        stderr = Path(receipt["stderr"]["path"]).read_text(encoding="utf-8").lower()
        assert receipt["exitCode"] != 0 and "no such object:" in stderr and cid in stderr
        receipts.extend(receipt[name] for name in ("stdout", "stderr"))
    listeners = []
    try:
        for port in sorted(ports):
            listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            listener.bind(("127.0.0.1", port))
            listener.listen(1)
            listeners.append(listener)
    finally:
        for listener in listeners:
            listener.close()
    native.close()
    target = output / "observation.json"
    target.write_text(json.dumps({"protocol": "tb12-fresh-owned-absence-v1", "family": "terminal-bench-twelve-journal-v1",
                                  "runId": args.run_id, "ownerNonce": args.owner_nonce,
                                  "observedAtUtc": datetime.now(timezone.utc).isoformat(), "allAbsent": True,
                                  "exactPids": sorted(pids), "exactCids": sorted(cids), "exclusiveBoundAndClosedPorts": sorted(ports),
                                  "closurePins": closures, "nativeReceiptPins": receipts,
                                  "modelCalls": 0, "sourceSha256": sha(Path(__file__))}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"observation": str(target), "allAbsent": True, "modelCalls": 0}))


if __name__ == "__main__":
    main()
