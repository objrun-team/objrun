"""Actual empty-candidate grading; model-free transport and rejection controls."""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import uuid
import traceback

from docker_owned import OwnedDocker, ROOT, sha
from snapshot_grader import grade_snapshot
from control_fixtures import install_control
from live_nginx import grade_live


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", required=True)
    parser.add_argument("--base-proof", required=True)
    parser.add_argument("--control", choices=("empty", "positive", "wrong", "malformed-worker", "ascii-worker"), default="empty")
    args = parser.parse_args()
    proof_path = Path(args.base_proof).resolve()
    assert proof_path.is_relative_to(ROOT / "docs/repair-2026-10-09/tb12-preparation-v1")
    proof = json.loads(proof_path.read_bytes())
    assert proof["actualPrivateImportsValidated"] and proof["allOwnedBuildersClosed"]
    context_path = Path(proof["contextManifest"]["path"])
    assert sha(context_path) == proof["contextManifest"]["sha256"]
    context = json.loads(context_path.read_bytes())
    task = next(row for row in context["tasks"] if row["taskId"] == args.task)
    live = task["profile"]["kind"] == "live-nginx"
    image_index = ROOT / "docs/repair-2026-10-08/tb-twelve-public-image-pulls-fd2e444e83ca407ebc1e172e10b16ac8/images.json"
    assert sha(image_index) == "f0f8e6419d55ff395725125a3c709d190368e494c1e2e33aa5b14fb238b0fc4b"
    images = json.loads(image_index.read_bytes())
    image = next(row["immutableImageId"] for row in images["records"] if row["taskId"] == args.task)
    nonce = uuid.uuid4().hex
    output = ROOT / "docs/repair-2026-10-09/tb12-preparation-v1/cold-snapshots" / nonce
    native = OwnedDocker(output, nonce)
    receipt, fatal, closures = None, None, []
    try:
        cid, initial, create = native.create("control-candidate-" + args.task, image, "/bin/sh", ["-c", "sleep 3600"], network="bridge" if live else "none", drop_capabilities=not live)
        native.start(cid)
        running = native.assert_actor(cid)
        assert running["State"]["Pid"] > 0
        namespaces = {}
        namespace_receipts = {}
        for namespace in ("pid", "mnt", "net"):
            observed = native.execute(cid, ["/usr/bin/readlink", "/proc/self/ns/" + namespace])
            namespaces[namespace] = native.text(observed)
            namespace_receipts[namespace] = observed
        if args.control != "empty":
            if args.control in ("malformed-worker", "ascii-worker"):
                assert args.task == "openssl-selfsigned-cert"
                install_control(native, cid, args.task, "positive", output / "control-fixtures")
                injected = output / "malformed-worker.py"
                code = """import errno, os
for path in ('/tests/test_outputs.py', '/opt/tb12/checker/private_checker.py', '/opt/tb12/worker-result.json'):
    assert not os.path.exists(path), 'Private scorer file leaked to untrusted worker'
assert 'DEEPSEEK_API_KEY' not in os.environ and 'OBJRUN_STATE_TOKEN' not in os.environ
try:
    open('/app/tb12-worker-write-probe', 'w').write('unexpected')
except OSError as error:
    assert error.errno == errno.EROFS
else:
    raise AssertionError('Untrusted worker root was writable')
print('worker-private-files-absent; provider-key-absent; root-write-blocked')
"""
                if args.control == "malformed-worker":
                    code += "os.write(1, b'\\xff')\n"
                code += "print('Certificate verification successful')\nprint('Certificate Common Name: dev-internal.company.local')\nprint('Certificate Expiration Date: 2027-10-09')\n"
                injected.write_text(code, encoding="utf-8")
                native.upload(injected, cid, "/app/check_cert.py")
            else:
                install_control(native, cid, args.task, args.control, output / "control-fixtures")
        grader = grade_live if live else grade_snapshot
        receipt = grader(native, cid, task, context, context_path.parent, proof["immutablePrivateImageId"], output / "grade")
        assert all(namespaces[name] != receipt["result"]["privateNamespaces"][name] for name in ("pid", "mnt")), "Candidate/private PID/mount namespace boundary failed"
        assert (namespaces["net"] == receipt["result"]["privateNamespaces"]["net"]) == live, "Task-specific network boundary failed"
        receipt["candidateBeforeGrade"] = {"runningState": running, "namespaces": namespaces, "namespaceReceipts": namespace_receipts}
        (output / "grade/grade.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        assert receipt["result"]["reward"] == int(args.control in ("positive", "ascii-worker")), "Control reward mismatch"
    except BaseException as error:
        fatal = {"type": type(error).__name__, "message": str(error), "traceback": traceback.format_exc()}
        if hasattr(error, "receipt"):
            fatal["nativeReceipt"] = error.receipt
    finally:
        for cid, role, name in native.open_actors():
            try:
                removal, absence = native.remove(cid)
                closures.append({"cid": cid, "role": role, "removal": removal, "absence": absence})
            except BaseException as error:
                closures.append({"cid": cid, "failure": type(error).__name__, "message": str(error)})
        closed = not native.open_actors()
        if closed:
            native.close()
        report = {"protocol": "tb12-actual-empty-snapshot-control-v1", "ownerNonce": nonce,
                  "taskId": args.task, "control": args.control, "createdAtUtc": datetime.now(timezone.utc).isoformat(),
                  "baseProof": {"path": str(proof_path), "sha256": sha(proof_path)},
                  "grade": receipt, "fatal": fatal, "closures": closures,
                  "allOwnedContainersClosed": closed, "validated": fatal is None and receipt is not None,
                  "modelCalls": 0, "paidReady": False}
        target = output / "control.json"
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({"report": str(target), "task": args.task, "validated": report["validated"], "fatal": fatal, "allClosed": closed}), flush=True)
    if fatal is not None or not closed:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
