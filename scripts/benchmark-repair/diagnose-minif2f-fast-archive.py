"""Replay original parser against the first fixed cache object; read-only E.

No decoder/process/container/network/candidate invocation. JSON output only;
the error exit is a red-capable signal for the original archive_path symptom.
"""
from pathlib import Path
import hashlib
import importlib.util
import json
import sys

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / "scripts/benchmark-repair/minif2f_fast_unpack.py"
ROOT = Path("E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415")
EXPECTED_SOURCE_SHA = "3e4d3f5ac688eca0e4b9b3a8afdcf710448d1816451f64dcaa1051a5750c44cb"


def main():
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == EXPECTED_SOURCE_SHA
    first = json.loads((ROOT / "audit/module-cache-manifest.jsonl").open("rb").readline())
    name = first["ltar"]
    with (ROOT / "audit/cache-downloads.jsonl").open("rb") as stream:
        records = [json.loads(line) for line in stream]
    record = next(r for r in records if r["ltar"] == name)
    path = ROOT / "downloads/mathlib-cache" / name
    data = path.read_bytes()
    assert len(data) == record["bytes"] and hashlib.sha256(data).hexdigest() == record["sha256"]
    spec = importlib.util.spec_from_file_location("frozen_fast_readonly", SOURCE)
    fast = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fast)
    result = {"sourceSha256": EXPECTED_SOURCE_SHA, "firstRecord": first, "inputPath": str(path),
        "inputBytes": len(data), "inputSha256": record["sha256"], "E_modified": False,
        "decoderOrDockerOrNetworkOrModelCalled": False}
    try:
        result["paths"] = fast.ltar_paths(data)
        result["reproducedOriginalFailure"] = False
        print(json.dumps(result, ensure_ascii=False))
        return 0
    except fast.InfraError as error:
        result.update(reproducedOriginalFailure=error.kind == "archive_path" and str(error) == "Archive path is not a bounded canonical relative path",
            errorType=error.kind, error=str(error))
        print(json.dumps(result, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    sys.exit(main())
