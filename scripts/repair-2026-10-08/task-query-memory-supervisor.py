"""Bounded native Windows F-only diagnosis; no HTTP/LLM/original database access."""
import ctypes
import ctypes.wintypes as wt
import datetime
import json
import os
import pathlib
import subprocess
import sys
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
BUN = pathlib.Path(r"C:\Users\y1252\AppData\Roaming\npm\node_modules\bun\bin\bun.exe")
assert ROOT.drive.casefold() == "f:"
OUT = ROOT / ".scratch" / ("task-query-memory-" + uuid.uuid4().hex[:12])
OUT.mkdir()
env = dict(os.environ, NODE_PATH=str(ROOT / "app/node_modules"),
           BUN_RUNTIME_TRANSPILER_CACHE_PATH=str(ROOT / ".scratch/bun-cache-task-query"))
kernel = ctypes.WinDLL("kernel32", use_last_error=True)
psapi = ctypes.WinDLL("psapi", use_last_error=True)
kernel.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
kernel.OpenProcess.restype = wt.HANDLE
kernel.CloseHandle.argtypes = [wt.HANDLE]
kernel.GetProcessTimes.argtypes = [wt.HANDLE] + [ctypes.POINTER(wt.FILETIME)] * 4
kernel.GetProcessTimes.restype = wt.BOOL

class Memory(ctypes.Structure):
    _fields_ = [("cb", wt.DWORD), ("PageFaultCount", wt.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
            "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage", "PrivateUsage")]

psapi.GetProcessMemoryInfo.argtypes = [wt.HANDLE, ctypes.POINTER(Memory), wt.DWORD]
psapi.GetProcessMemoryInfo.restype = wt.BOOL

def native_sample(handle):
    memory = Memory()
    memory.cb = ctypes.sizeof(memory)
    if not psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        raise OSError(ctypes.get_last_error(), "owned process memory unavailable")
    times = [wt.FILETIME() for _ in range(4)]
    if not kernel.GetProcessTimes(handle, *(ctypes.byref(value) for value in times)):
        raise OSError(ctypes.get_last_error(), "owned process CPU time unavailable")
    ticks = lambda value: (value.dwHighDateTime << 32) | value.dwLowDateTime
    return {"rssBytes": memory.WorkingSetSize, "privateBytes": memory.PrivateUsage,
            "cpuSeconds": (ticks(times[2]) + ticks(times[3])) / 10_000_000}

report = {"schemaVersion": 1, "diagnosticOnly": True, "modelCalls": 0,
          "createdAt": datetime.datetime.now(datetime.timezone.utc).isoformat(), "directory": str(OUT),
          "limits": {"cpuSecondsPerChild": 30, "wallSecondsPerChild": 28,
                     "nativeRssOrPrivateBytesPerChild": 512 * 1024 * 1024,
                     "supervisorSoftStopBytes": 480 * 1024 * 1024,
                     "syntheticFixtureBytes": 128 * 1024 * 1024}, "children": []}
groups = (("status", "source"),) if sys.argv[1:] == ["--green-status"] else (("full", "prepare"), ("full", "finalize"), ("light", "prepare"), ("light", "finalize"))
for count in (256, 512):
    for shape, lifecycle in groups:
        directory = OUT / f"{count}-{shape}-{lifecycle}"
        directory.mkdir()
        started = time.monotonic()
        with (directory / "stdout.log").open("wb") as stdout, (directory / "stderr.log").open("wb") as stderr:
            child = subprocess.Popen([str(BUN), str(ROOT / "scripts/repair-2026-10-08/task-query-memory-fixture.ts"),
                                      str(directory), shape, lifecycle, str(count)], stdout=stdout, stderr=stderr,
                                     cwd=ROOT, env=env, creationflags=subprocess.CREATE_NO_WINDOW)
            handle = kernel.OpenProcess(0x0400 | 0x0010, False, child.pid)
            peak_rss = peak_private = 0
            cpu = 0.0
            stop = None
            try:
                if not handle:
                    raise OSError(ctypes.get_last_error(), "cannot monitor owned fixture child")
                while child.poll() is None:
                    sample = native_sample(handle)
                    peak_rss = max(peak_rss, sample["rssBytes"])
                    peak_private = max(peak_private, sample["privateBytes"])
                    cpu = max(cpu, sample["cpuSeconds"])
                    if max(peak_rss, peak_private) > 480 * 1024 * 1024:
                        stop = "native_memory_guard"
                    elif cpu > 28:
                        stop = "native_cpu_guard"
                    elif time.monotonic() - started > 27:
                        stop = "wall_guard"
                    if stop:
                        child.kill()
                        break
                    time.sleep(.05)
                child.wait(timeout=3)
            except BaseException:
                if child.poll() is None:
                    child.kill()
                    child.wait(timeout=3)
                raise
            finally:
                if handle:
                    kernel.CloseHandle(handle)
        result = json.loads((directory / "result.json").read_text()) if (directory / "result.json").exists() else None
        points = [json.loads(line) for line in (directory / "stdout.log").read_text().splitlines() if line.startswith('{"event":')]
        record = {"count": count, "shape": shape, "lifecycle": lifecycle, "pid": child.pid,
                  "exitCode": child.returncode, "supervisorStop": stop, "peakRssBytes": peak_rss,
                  "peakPrivateBytes": peak_private, "cpuSecondsObserved": cpu,
                  "wallSeconds": time.monotonic() - started, "resultPath": str(directory / "result.json"),
                  "lastStdoutPoint": points[-1] if points else None,
                  "result": {k: result.get(k) for k in ("outcome", "error", "polls", "queries", "chainSteps", "elapsedMs", "responseBytes")} if result else None}
        report["children"].append(record)
        (OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(json.dumps(record), flush=True)
        occupied = sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file())
        if occupied > 128 * 1024 * 1024:
            raise RuntimeError("synthetic fixture byte limit exceeded; all owned children already exited")
report["finishedAt"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
report["fixtureBytes"] = sum(path.stat().st_size for path in OUT.rglob("*") if path.is_file())
(OUT / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
print(json.dumps({"reportPath": str(OUT / "report.json"), "fixtureBytes": report["fixtureBytes"]}), flush=True)
