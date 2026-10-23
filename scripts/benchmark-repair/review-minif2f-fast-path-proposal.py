"""F-only diagnosis/proposal controls; never decode, launch, recover or write E.

The prototype changes only the two output_path calls inside a copied AST of
ltar_paths. Production output_path/source and all other call sites stay frozen.
"""
from pathlib import Path
import ast
import datetime
import hashlib
import importlib.util
import inspect
import json
import os
import stat
import struct

PROJECT = Path(__file__).resolve().parents[2]
DOCS = PROJECT / "docs/repair-2026-10-08"
SOURCE = PROJECT / "scripts/benchmark-repair/minif2f_fast_unpack.py"
ROOT = Path("E:/objrun-experiment-cache/01a119ed-fdf7-7c32-b323-de9bab1290b6/minif2f-v415")
SHA = "3e4d3f5ac688eca0e4b9b3a8afdcf710448d1816451f64dcaa1051a5750c44cb"


def pin(path):
    path = Path(path)
    b = path.read_bytes()
    return {"path": str(path), "bytes": len(b), "sha256": hashlib.sha256(b).hexdigest()}


def write_new(path, raw):
    assert path.drive.upper() == "F:"
    with open(path, "xb") as f:
        f.write(raw)
        f.flush()
        os.fsync(f.fileno())
    assert path.read_bytes() == raw
    return pin(path)


def main():
    began = datetime.datetime.now(datetime.timezone.utc).isoformat()
    assert pin(SOURCE)["sha256"] == SHA
    spec = importlib.util.spec_from_file_location("original_fast_readonly", SOURCE)
    fast = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(fast)
    original_output_path = fast.output_path
    visited = []
    def archive_output_path(value):
        canonical = value[2:] if value.startswith("./") else value
        result = original_output_path(canonical)
        visited.append({"raw": value, "canonical": result})
        return result
    tree = ast.parse(inspect.getsource(fast.ltar_paths))
    changed = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "output_path":
            node.func.id = "archive_output_path"
            changed += 1
    assert changed == 2
    prototype = ast.unparse(tree) + "\n"
    namespace = dict(fast.__dict__, archive_output_path=archive_output_path)
    exec(compile(tree, "<F-only archive ingress proposal>", "exec"), namespace)
    parse = namespace["ltar_paths"]
    with (ROOT / "audit/module-cache-manifest.jsonl").open("rb") as stream:
        keys = [json.loads(stream.readline()) for _ in range(2)]
    names = {k["ltar"] for k in keys}
    records = {}
    with (ROOT / "audit/cache-downloads.jsonl").open("rb") as stream:
        for line in stream:
            v = json.loads(line)
            if v["ltar"] in names:
                records[v["ltar"]] = v
    failures = []
    originals = []
    inputs = []
    for key in keys:
        path = ROOT / "downloads/mathlib-cache" / key["ltar"]
        before = pin(path)
        data = path.read_bytes()
        record = records[key["ltar"]]
        assert before["sha256"] == record["sha256"] and before["bytes"] == record["bytes"]
        try:
            fast.ltar_paths(data)
            old = {"rejected": False}
        except fast.InfraError as e:
            old = {"rejected": True, "kind": e.kind, "message": str(e)}
        assert old == {"rejected": True, "kind": "archive_path", "message": "Archive path is not a bounded canonical relative path"}
        visited.clear()
        paths = parse(data)
        assert visited and len(paths) == len(visited) and all(v["raw"].startswith("./") for v in visited)
        assert before == pin(path)
        first_end = data.find(b"\0", 12)
        outputs = []
        for value in paths:
            actual = ROOT / "mathlib4" / value
            outputs.append({"canonicalPath": value, "currentTargetExists": os.path.lexists(actual),
                "currentTargetPin": pin(actual) if actual.is_file() else None})
        originals.append(before)
        inputs.append({"key": key, "originalPin": before, "originalRejected": old,
            "headerMagic": data[:4].decode("ascii"), "initialU64": str(struct.unpack_from("<Q", data, 4)[0]),
            "firstCStringOffset": 12, "firstCStringEnd": first_end, "firstCStringRaw": data[12:first_end].decode("utf-8"),
            "proposalPaths": paths, "rawToCanonical": list(visited), "existingTargets": outputs,
            "officialDecoderCalled": False})
    def archive(trace=".lake/build/lib/Fixture.trace", others=(".lake/build/lib/Fixture.hash",)):
        b = b"LTR2" + struct.pack("<Q", 37) + trace.encode() + b"\0\3" + struct.pack("<Q", 37)
        for name in others:
            b += name.encode() + b"\0\2" + struct.pack("<Q", 71)
        return b
    controls = []
    positives = [
        ("canonical-input-still-accepted", archive()),
        ("one-leading-dot-slash-at-archive-ingress", archive("./.lake/build/lib/Fixture.trace", ("./.lake/build/lib/Fixture.hash",))),
        ("package-build-tree-preserved", archive("./.lake/packages/aesop/.lake/build/lib/A.trace", ())),
    ]
    for label, data in positives:
        values = parse(data)
        assert values and all(not v.startswith("./") for v in values)
        controls.append({"name": label, "passed": True, "result": values})
    bad = [
        ("double-prefix-refused", "././.lake/build/lib/A.trace"),
        ("absolute-refused", "/.lake/build/lib/A.trace"),
        ("dot-prefixed-absolute-refused", ".//.lake/build/lib/A.trace"),
        ("parent-escape-refused", "./../source.lean"),
        ("internal-parent-refused", "./.lake/build/../source.lean"),
        ("internal-dot-refused", "./.lake/build/lib/./A.trace"),
        ("double-separator-refused", "./.lake//build/lib/A.trace"),
        ("backslash-refused", "./.lake/build/lib/..\\A.trace"),
        ("colon-refused", "./.lake/build/lib/A:B.trace"),
        ("control-byte-refused", "./.lake/build/lib/A\nB.trace"),
        ("outside-build-tree-refused", "./Mathlib/Fixture.lean"),
        ("package-source-refused", "./.lake/packages/aesop/Aesop.lean"),
        ("byte-cap-still-refused", "./.lake/build/lib/" + "A" * 260),
        ("depth-cap-still-refused", "./.lake/build/" + "a/" * 17 + "A.trace"),
    ]
    for label, trace in bad:
        try:
            parse(archive(trace, ()))
            raise AssertionError("Expected rejection: " + label)
        except fast.InfraError as e:
            controls.append({"name": label, "passed": True, "rejectedWith": e.kind})
    for label, data in [
        ("normalized-alias-duplicate-refused", archive("./.lake/build/lib/A.trace", (".lake/build/lib/A.trace",))),
        ("casefold-alias-duplicate-refused", archive("./.lake/build/lib/A.trace", ("./.lake/build/lib/a.trace",))),
        ("truncated-payload-still-refused", archive()[:-1]),
    ]:
        try:
            parse(data)
            raise AssertionError("Expected rejection: " + label)
        except fast.InfraError as e:
            controls.append({"name": label, "passed": True, "rejectedWith": e.kind})
    try:
        original_output_path("./.lake/build/lib/Fixture.trace")
        raise AssertionError("Receipt/output strict canonical validator was loosened")
    except fast.InfraError:
        controls.append({"name": "non-archive-output-and-receipt-validator-remains-strict", "passed": True})
    stage = ROOT / "audit/cache-fast-stage-06bec841f3c84e198447b63716a3a4d6"
    stage_entries = []
    for current, ds, ns in os.walk(stage, followlinks=False):
        for name in [*ds, *ns]:
            f = Path(current) / name
            s = f.lstat()
            stage_entries.append({"relativePath": f.relative_to(stage).as_posix(), "directory": stat.S_ISDIR(s.st_mode),
                "regularFile": stat.S_ISREG(s.st_mode), "reparse": bool(s.st_file_attributes & 0x400), "bytes": s.st_size})
    assert stage.exists() and not any(v["regularFile"] or v["reparse"] for v in stage_entries)
    snapshot = DOCS / "minif2f-fast-first-failure-readonly-snapshot"
    snapshot.mkdir(exist_ok=False)
    artifact_paths = [ROOT / ("audit/" + name) for name in ["cache-fast-progress.json", "cache-fast-container.json", "cache-fast-unpack.lock", "cache-fast-commits.jsonl", "cache-unpacked.jsonl", "bootstrap.json"]]
    artifact_paths += [SOURCE, PROJECT / "scripts/benchmark-repair/minif2f_fast_unpack.ps1", DOCS / "minif2f-fast-unpack-review.json"]
    artifact_paths += [Path(v["path"]) for v in originals]
    saved = []
    for path in artifact_paths:
        before = pin(path)
        target = snapshot / (path.name + (".snapshot" if path.suffix in {".py", ".ps1"} else ""))
        saved.append({"original": before, "saved": write_new(target, path.read_bytes())})
        assert before == pin(path)
    prototype_pin = write_new(snapshot / "archive-parser-prototype.txt", prototype.encode())
    owner = json.loads((ROOT / "audit/cache-fast-container.json").read_text())
    lease = json.loads((ROOT / "audit/cache-fast-unpack.lock").read_text())
    progress = json.loads((ROOT / "audit/cache-fast-progress.json").read_text())
    assert owner["state"] == "removed" and lease["held"] is False and progress["processed_prefix"] == progress["prefix_before"] == 0
    assert (ROOT / "audit/cache-fast-commits.jsonl").stat().st_size == (ROOT / "audit/cache-unpacked.jsonl").stat().st_size == 0
    assert pin(SOURCE)["sha256"] == SHA
    report = {"protocol": "minif2f-fast-first-archive-readonly-diagnosis-v1", "startedAtUtc": began,
        "completedAtUtc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "productionSourceEdited": False,
        "sourcePin": pin(SOURCE), "diagnosticSourcePin": pin(Path(__file__).resolve()),
        "E_C_D_modified": False, "modelRequests": 0, "decoderOrDockerOrNetworkCalls": 0,
        "rootCause": "Original first archive CString begins ./; raw split includes dot component rejected by canonical guard before decoder. Both actual first two objects reproduce and pass only archive-ingress one-prefix prototype.",
        "parserLayoutChanged": False, "prototypeChangedArchiveCallsites": changed,
        "strictOutputValidatorChanged": False, "inputs": inputs, "controls": controls,
        "controlsPassed": len(controls), "sourceAndOriginalObjectsUnchangedAfterRead": True,
        "stageInventory": stage_entries, "stageRegularFiles": 0, "stageReparses": 0,
        "ownerReceiptState": owner["state"], "ownerCid": owner["container_id"], "leasePid": lease["pid"],
        "leaseHeld": lease["held"], "independentCurrentDaemonOrHostPidProbePerformed": False,
        "processedPrefix": 0, "commitAndReceiptBytes": 0, "preservedSnapshots": saved,
        "prototypePin": prototype_pin, "actualOfficialPositiveControlStillRequired": True,
        "actualRecoveryOrRetryPerformed": False}
    out = DOCS / "minif2f-fast-first-archive-diagnosis.json"
    print(json.dumps({"reportPin": write_new(out, (json.dumps(report, ensure_ascii=False, indent=2) + "\n").encode()),
        "controlsPassed": len(controls), "realObjectsRead": len(inputs), "stageRegularFiles": 0}))


if __name__ == "__main__":
    main()
