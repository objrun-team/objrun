"""Read-only physical disk observer for one declared JPG control run; no Docker/API calls."""
import argparse
import ctypes
import json
from pathlib import Path
import shutil
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--build-proof", type=Path, required=True)
    parser.add_argument("--controls", type=Path, required=True)
    args = parser.parse_args()
    proof = json.loads(args.build_proof.read_text())
    if not proof.get("validated") or not proof.get("actualBuildCompleted"):
        raise ValueError("No actual successful build baseline")
    baseline = proof["samples"][0]["vhdAllocatedBytes"]
    vhd = Path(proof["vhdBackingFile"])
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    measure = kernel.GetCompressedFileSizeW
    measure.argtypes = [ctypes.c_wchar_p, ctypes.POINTER(ctypes.c_uint32)]
    measure.restype = ctypes.c_uint32
    samples, last, start = [], None, time.monotonic()
    while time.monotonic()-start < 4200:
        high = ctypes.c_uint32()
        ctypes.set_last_error(0)
        low = measure(str(vhd), ctypes.byref(high))
        if low == 0xffffffff and ctypes.get_last_error():
            raise OSError(ctypes.get_last_error())
        value = low+(high.value << 32)
        path = args.controls/"operation-owner.json"
        owner = json.loads(path.read_text()) if path.is_file() else {}
        active = [{k: x[k] for k in ["name", "role", "state"]} for x in owner.get("containers", [])
                  if x["state"] not in ["removed", "absent_after_create_attempt"]]
        phases = [x for x in ["empty", "oracle", "wrong-workbook"] if (args.controls/x).is_dir()]
        stage = {"active": active, "phasesCreated": phases}
        samples.append({"at": time.time(), "freeCBytes": shutil.disk_usage("C:/").free,
            "freeFBytes": shutil.disk_usage("F:/").free, "vhdAllocatedBytes": value,
            "growthSinceBuildStartBytes": max(0, value-baseline), **stage})
        if stage != last:
            print(json.dumps({"stage": stage, "growthSinceBuildStartBytes": max(0, value-baseline),
                              "freeFBytes": samples[-1]["freeFBytes"]}), flush=True)
            last = stage
        if (args.controls/"report.json").is_file():
            break
        time.sleep(2)
    report = {"readOnlyObserver": True, "baselineFromBuildProof": str(args.build_proof),
        "baselineVhdAllocatedBytes": baseline, "controlsReportExists": (args.controls/"report.json").is_file(),
        "maxDockerGrowthSinceBuildStartBytes": max(x["growthSinceBuildStartBytes"] for x in samples),
        "minimumCFreeBytes": min(x["freeCBytes"] for x in samples),
        "minimumFFreeBytes": min(x["freeFBytes"] for x in samples), "samples": samples}
    (args.controls/"resource-observer.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}), flush=True)


if __name__ == "__main__":
    main()
