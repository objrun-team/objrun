"""Original tests over passive captured data, with exact invocation binding."""
import json
from pathlib import Path
import uuid
import base64
import time

from artifacts_sanitize_next import sealed_capsule, stage_checker_image
from command_worker import caffe_worker
from pmars_worker import pmars_worker
from fixed_cli_worker import fixed_cli_worker
from povray_worker import povray_worker
from task_environment import task_packages, task_private_image
from polyglot_worker import polyglot_worker
from rust_polyglot_worker import rust_polyglot_worker
from git_leak_worker import git_leak_worker
from heap_worker import heap_worker
from gpt2_worker import gpt2_worker
from sanitize_untrusted_worker_next import sanitize_worker


def openssl_worker(native, candidate, output, verifier_seconds, deadline=None):
    """Preserve candidate-installed dependencies in an explicitly untrusted island."""
    deadline=deadline if deadline is not None else time.monotonic()+verifier_seconds
    source = native.assert_actor(candidate)
    assert source["State"]["Paused"]
    image, commit = native.commit(candidate, "untrusted-openssl-worker")
    cid, initial, create = native.create(
        "untrusted-openssl-worker", image, "python", ["/app/check_cert.py"],
        readonly=True, network="none",
    )
    # A nonzero script exit is ordinary candidate output, not transport success.
    native.assert_actor(cid)
    remaining=deadline-time.monotonic()
    if remaining<=0:raise TimeoutError('Official verifier budget exhausted before OpenSSL worker start')
    start = native.command(["start", "-a", cid], timeout=remaining, stdout_limit=1024 ** 2)
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
    private_base,environment_pin=task_private_image(context_directory,context,task,private_base)
    invocation = uuid.uuid4().hex
    verifier_deadline=time.monotonic()+task['verifierSeconds']
    capsule, capsule_path = sealed_capsule(native, candidate, task["taskId"], output / "capsule")
    config = {
        "protocol": "tb12-private-checker-config-v1", "invocationId": invocation,
        "taskId": task["taskId"], "verifierSeconds": task["verifierSeconds"],
        "packages": task_packages(context,task), "officialTestHashes": task["officialTestHashes"],
        "taskEnvironmentPin":environment_pin,
    }
    worker = None
    if task['taskId']=='sanitize-git-repo':
        public_proof=json.loads((Path(context_directory)/'public-dependency-proof.json').read_bytes())
        config['sanitizeWorkerResult'],worker=sanitize_worker(native,candidate,task,capsule,output/'sanitize-worker',public_proof,verifier_deadline)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Original circuit verifier deadline exhausted')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    if task['taskId']=='gpt2-codegolf':
        config['gpt2Result'],worker=gpt2_worker(native,candidate,task,verifier_deadline,capsule)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official GPT2 verifier deadline exhausted before assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    if task['taskId']=='custom-memory-heap-crash':
        config['heapResult'],worker=heap_worker(native,candidate,task,verifier_deadline,output/'heap-artifacts')
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official heap verifier deadline exhausted before assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    if task['taskId']=='git-leak-recovery':
        config['gitLeakResult'],worker=git_leak_worker(native,candidate,task,verifier_deadline)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official Git verifier deadline exhausted before assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    if task['taskId']=='polyglot-rust-c':
        config['rustPolyglotResult'],worker=rust_polyglot_worker(native,candidate,task,verifier_deadline,capsule)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official Rust polyglot verifier deadline exhausted before assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    if task['taskId']=='polyglot-c-py':
        config['polyglotResult'],worker=polyglot_worker(native,candidate,task,verifier_deadline,capsule)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official polyglot verifier deadline exhausted before assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    if task['taskId']=='build-pov-ray':
        config['povrayCliResult'],worker,generated=povray_worker(native,candidate,task,verifier_deadline,output/'generated')
        capsule['files'].extend(generated)
        capsule['workerGeneratedFiles']=True
        capsule_path.write_text(json.dumps(capsule,indent=2),encoding='utf-8')
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official POV-Ray verifier deadline exhausted before assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    if task["taskId"] == "openssl-selfsigned-cert":
        config["untrustedWorkerResult"], worker = openssl_worker(native, candidate, output, task["verifierSeconds"],verifier_deadline)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official verifier budget exhausted after OpenSSL worker')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    elif task['taskId']=='caffe-cifar-10':
        config['caffeWorkerResult'],worker=caffe_worker(native,candidate,task,capsule,verifier_deadline)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official Caffe verifier budget exhausted before private assertions')
        config['officialVerifierSeconds']=task['verifierSeconds']
        config['verifierSeconds']=remaining
    elif task['taskId']=='build-pmars':
        config['pmarsWorkerResult'],worker=pmars_worker(native,candidate,task,capsule,verifier_deadline)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official pMARS verifier budget exhausted before private assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    elif task['taskId'] in {'prove-plus-comm','rstan-to-pystan','winning-avg-corewars'}:
        config['fixedCliResult'],worker=fixed_cli_worker(native,candidate,task,verifier_deadline)
        remaining=int(verifier_deadline-time.monotonic())
        if remaining<=0:raise TimeoutError('Official fixed CLI verifier budget exhausted before private assertions')
        config['officialVerifierSeconds']=task['verifierSeconds'];config['verifierSeconds']=remaining
    image, staging = stage_checker_image(
        native, private_base, task, context_directory, capsule, config, output / "staging")
    cid, initial, create = native.create(
        "private-checker-" + task["taskId"], image, "/opt/checker/bin/python",
        ["-I", "-B", "/opt/tb12/checker/private_checker.py", "--config",
         "/opt/tb12/checker-config.json"], readonly=True, network="none", memory_mb=task["officialEnvironment"]["memory_mb"], cpus=task["officialEnvironment"]["cpus"])
    remaining=verifier_deadline-time.monotonic() if verifier_deadline is not None else task['verifierSeconds']
    if remaining<=0:raise TimeoutError('Official verifier budget exhausted before checker start')
    start = native.start(cid, attach=True, timeout=remaining + 30)
    final = native.assert_actor(cid)
    assert final["State"]["Status"] == "exited" and final["State"]["ExitCode"] == 0
    last = native.text(start).splitlines()[-1]
    assert last.startswith("TB12_RESULT:")
    result = json.loads(last[len("TB12_RESULT:"):])
    if verifier_deadline is not None and time.monotonic()>verifier_deadline:
        raise TimeoutError('Official verifier deadline exceeded; no late pass admitted')
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
