"""Original tests over passive captured data, with exact invocation binding."""
import json
from pathlib import Path
import uuid
import base64

from artifacts import sealed_capsule, stage_checker_image


def openssl_worker(native, candidate, output, verifier_seconds):
    """Preserve candidate-installed dependencies in an explicitly untrusted island."""
    source = native.assert_actor(candidate)
    assert source["State"]["Paused"]
    image, commit = native.commit(candidate, "untrusted-openssl-worker")
    cid, initial, create = native.create(
        "untrusted-openssl-worker", image, "python", ["/app/check_cert.py"],
        readonly=True, network="none",
    )
    # A nonzero script exit is ordinary candidate output, not transport success.
    native.assert_actor(cid)
    start = native.command(["start", "-a", cid], timeout=verifier_seconds, stdout_limit=1024 ** 2)
    final = native.assert_actor(cid)
    assert final["State"]["Status"] == "exited"
    encoding_error = None
    decoded = {}
    for name in ("stdout", "stderr"):
        raw = Path(start[name]["path"]).read_bytes()
        try:
            decoded[name] = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            decoded[name] = ""
            encoding_error = encoding_error or {"stream": name, "encoding": "utf-8",
                                                "objectBase64": base64.b64encode(raw).decode("ascii"),
                                                "start": error.start, "end": error.end, "reason": error.reason}
    stdout, stderr = decoded["stdout"], decoded["stderr"]
    assert len(stdout.encode()) <= 1024 ** 2 and len(stderr.encode()) <= 1024 ** 2
    removal, absence = native.remove(cid)
    result = {
        "protocol": "tb12-openssl-untrusted-worker-result-v1",
        "exitCode": final["State"]["ExitCode"], "stdout": stdout, "stderr": stderr,
        "encodingError": encoding_error,
    }
    receipt = {"sourceState": source, "image": image, "commit": commit,
               "cid": cid, "initialState": initial, "create": create, "start": start,
               "finalState": final, "removal": removal, "absence": absence,
               "classification": "untrusted candidate execution; output data only"}
    return result, receipt


def grade_snapshot(native, candidate, task, context, context_directory, private_base, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    invocation = uuid.uuid4().hex
    capsule, capsule_path = sealed_capsule(native, candidate, task["taskId"], output / "capsule")
    config = {
        "protocol": "tb12-private-checker-config-v1", "invocationId": invocation,
        "taskId": task["taskId"], "verifierSeconds": task["verifierSeconds"],
        "packages": context["packages"], "officialTestHashes": task["officialTestHashes"],
    }
    worker = None
    if task["taskId"] == "openssl-selfsigned-cert":
        config["untrustedWorkerResult"], worker = openssl_worker(native, candidate, output, task["verifierSeconds"])
    image, staging = stage_checker_image(
        native, private_base, task, context_directory, capsule, config, output / "staging")
    cid, initial, create = native.create(
        "private-checker-" + task["taskId"], image, "/opt/checker/bin/python",
        ["-I", "-B", "/opt/tb12/checker/private_checker.py", "--config",
         "/opt/tb12/checker-config.json"], readonly=True, network="none")
    start = native.start(cid, attach=True, timeout=task["verifierSeconds"] + 30)
    final = native.assert_actor(cid)
    assert final["State"]["Status"] == "exited" and final["State"]["ExitCode"] == 0
    last = native.text(start).splitlines()[-1]
    assert last.startswith("TB12_RESULT:")
    result = json.loads(last[len("TB12_RESULT:"):])
    assert result["invocationId"] == invocation and result["taskId"] == task["taskId"]
    assert result["exitCode"] in (0, 1) and result["reward"] == int(result["exitCode"] == 0)
    tests = result["ctrf"]["results"]["tests"]
    assert len(tests) == len(task["staticTestNames"])
    assert {test["name"].split("::")[-1] for test in tests} == set(task["staticTestNames"]), "Original test IDs differ"
    removal, absence = native.remove(cid)
    receipt = {"protocol": "tb12-snapshot-grade-v1", "invocationId": invocation,
               "taskId": task["taskId"], "candidateCid": candidate, "capsulePath": str(capsule_path),
               "worker": worker, "immutableCheckerImage": image, "staging": staging,
               "checkerCid": cid, "initialState": initial, "create": create, "start": start,
               "finalState": final, "result": result, "removal": removal, "absence": absence}
    (output / "grade.json").write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return receipt
