"""Fresh read-only exact PID/CID and exclusive port observations."""
import argparse
import ctypes
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
    parser.add_argument("--include-closed-owner", action="store_true")
    args = parser.parse_args()
    home = Path(args.run_directory).resolve()
    assert home.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-runs-v1")
    output = home / "fresh-absence" / uuid.uuid4().hex
    native = OwnedDocker(output)
    admission = json.loads((home / "paid-admission.json").read_bytes())
    assert admission["runId"] == args.run_id and admission["owned"]["ownerNonce"] == args.owner_nonce
    family = admission["family"]
    assert family in {"terminal-bench-twelve-journal-v1", "terminal-bench-twelve-journal-v2"}
    pids, ports, cids, closures = set(), set(), set(), []
    latest_close, expected_names = {}, {}
    def add_pid(pid, closed_at, executable):
        pids.add(pid)
        expected_names.setdefault(pid, set()).add(Path(executable).name.lower())
        parsed = datetime.fromisoformat(closed_at.replace("Z", "+00:00"))
        latest_close[pid] = max(latest_close.get(pid, parsed), parsed)
    if args.include_closed_owner:
        # The original owner existed before it wrote this acquisition frame.
        # A newer creation time therefore cannot be that original instance.
        manifest = json.loads((home / "manifest.json").read_bytes())
        add_pid(admission["owned"]["pid"], admission["owned"]["startedAt"], manifest["hostBun"]["path"])
    for target in sorted(home.glob("workers/*/engine-close.json")) + list(home.glob("stand-process/stand-close.json")):
        value = json.loads(target.read_bytes())
        assert value["exitObserved"] and value["closeObserved"]
        add_pid(value["pid"], value["closedAtUtc"], value["argv"][0])
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
                add_pid(value["nativePid"], value["finishedAtUtc"], value["argv"][0])
        finally:
            connection.close()
    # OpenProcess is one bounded native query per *exact* PID. Windows reuses
    # numeric PIDs, so a creation time after the recorded close proves a new
    # unrelated process instance. No command lines or environment are read.
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_ulong, ctypes.c_int, ctypes.c_ulong]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.GetProcessTimes.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p]
    class FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_ulong), ("high", ctypes.c_ulong)]
    class ProcessEntry(ctypes.Structure):
        _fields_ = [("size", ctypes.c_ulong), ("usage", ctypes.c_ulong), ("pid", ctypes.c_ulong),
                    ("heap", ctypes.c_size_t), ("module", ctypes.c_ulong), ("threads", ctypes.c_ulong),
                    ("parent", ctypes.c_ulong), ("priority", ctypes.c_long), ("flags", ctypes.c_ulong),
                    ("exe", ctypes.c_wchar * 260)]
    kernel.CreateToolhelp32Snapshot.argtypes = [ctypes.c_ulong, ctypes.c_ulong]
    kernel.CreateToolhelp32Snapshot.restype = ctypes.c_void_p
    kernel.Process32FirstW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry)]
    kernel.Process32NextW.argtypes = [ctypes.c_void_p, ctypes.POINTER(ProcessEntry)]
    def executable_snapshot(pid):
        snapshot = kernel.CreateToolhelp32Snapshot(2, 0)
        assert snapshot and snapshot != ctypes.c_void_p(-1).value
        try:
            entry = ProcessEntry()
            entry.size = ctypes.sizeof(entry)
            assert kernel.Process32FirstW(snapshot, ctypes.byref(entry))
            while True:
                if entry.pid == pid:
                    return entry.exe.lower()
                if not kernel.Process32NextW(snapshot, ctypes.byref(entry)):
                    assert ctypes.get_last_error() == 18
                    return None
        finally:
            assert kernel.CloseHandle(snapshot)
    observations = []
    for pid in sorted(pids):
        ctypes.set_last_error(0)
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            error = ctypes.get_last_error()
            if error == 87:
                observations.append({"pid": pid, "numericPidAbsent": True, "win32Error": error})
            else:
                assert error == 5, ("PID identity cannot be observed", pid, error)
                current_exe = executable_snapshot(pid)
                assert current_exe is None or current_exe not in expected_names[pid], ("Protected PID may still be owned", pid)
                observations.append({"pid": pid, "numericPidAbsent": current_exe is None,
                                     "originalInstanceAbsent": True, "win32Error": error,
                                     "currentExeName": current_exe, "originalExeNames": sorted(expected_names[pid]),
                                     "differentExecutableInstance": current_exe is not None})
            continue
        try:
            creation, exit_at, system, user = FileTime(), FileTime(), FileTime(), FileTime()
            assert kernel.GetProcessTimes(handle, ctypes.byref(creation), ctypes.byref(exit_at), ctypes.byref(system), ctypes.byref(user))
            ticks = (creation.high << 32) | creation.low
            started = datetime.fromtimestamp((ticks - 116444736000000000) / 10000000, timezone.utc)
            exit_ticks = (exit_at.high << 32) | exit_at.low
            if exit_ticks:
                exit_time = datetime.fromtimestamp((exit_ticks - 116444736000000000) / 10000000, timezone.utc)
                observations.append({"pid": pid, "numericPidAbsent": False, "originalInstanceAbsent": True,
                                     "observedCreationAtUtc": started.isoformat(), "observedExitAtUtc": exit_time.isoformat(), "terminatedProcessObjectRetained": True})
            else:
                assert started > latest_close[pid], ("An original owned process may remain", pid, started.isoformat())
                observations.append({"pid": pid, "numericPidAbsent": False, "originalInstanceAbsent": True,
                                     "observedCreationAtUtc": started.isoformat(), "originalLifetimeUpperBoundUtc": latest_close[pid].isoformat(), "pidReused": True})
        finally:
            assert kernel.CloseHandle(handle)
    pid_receipt = output / "pid-observation.json"
    pid_receipt.write_text(json.dumps({"requestedPids": sorted(pids), "observations": observations,
                                      "method": "OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION) and GetProcessTimes",
                                      "observerSourceSha256": sha(Path(__file__)), "allOriginalOwnedInstancesAbsent": True}) + "\n", encoding="utf-8")
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
    target.write_text(json.dumps({"protocol": "tb12-fresh-owned-absence-v1", "family": family,
                                  "runId": args.run_id, "ownerNonce": args.owner_nonce,
                                  "observedAtUtc": datetime.now(timezone.utc).isoformat(), "allAbsent": True,
                                  "exactPids": sorted(pids), "exactCids": sorted(cids), "exclusiveBoundAndClosedPorts": sorted(ports),
                                  "allExactPidNumbersAbsent": all(row["numericPidAbsent"] for row in observations),
                                  "allOriginalOwnedProcessInstancesAbsent": True,
                                  "closurePins": closures, "nativeReceiptPins": receipts,
                                  "modelCalls": 0, "sourceSha256": sha(Path(__file__))}, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"observation": str(target), "allAbsent": True, "modelCalls": 0}))


if __name__ == "__main__":
    main()
