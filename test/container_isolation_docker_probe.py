"""Small actual-Docker probe; never pulls images or touches user containers.

python test/container_isolation_docker_probe.py --expect-safe

Uses the existing python:3.12.11-slim-bookworm image, synthetic references, real
adapter grading functions, and one background candidate watcher. It deliberately
demonstrates why TB shared-live grading stays blocked, then checks SKB snapshots
and the actual HTTP credential boundary. No LLM or official task is used.
"""
import argparse
import ast
import hmac
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
IMAGE = "python:3.12.11-slim-bookworm"


def definitions(slug, names, namespace):
    path = ROOT / "examples" / "benchmark" / slug / "stand.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    if len(selected) != len(names):
        raise AssertionError("Expected actual adapter functions")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


def docker(*args, check=True, **kwargs):
    result = subprocess.run(["docker", *args], text=True, capture_output=True, timeout=30, **kwargs)
    if check and result.returncode:
        raise RuntimeError(f"docker {args[0]} failed: {result.stderr[-300:]}")
    return result


WATCHER = """
import json, os, time
from pathlib import Path
paths = {'tests': '/tests/reference.txt', 'stdout': '/logs/verifier/test-stdout.txt',
         'verifier': '/verifier/reference.txt', 'stage': '/stage/tests/reference.txt'}
seen = {}
Path('/app/ready').write_text('ready')
while True:
    for label, name in paths.items():
        try:
            if 'SYNTHETIC-HIDDEN-MARKER' in Path(name).read_text():
                seen[label] = True
                Path('/app/observations.json').write_text(json.dumps(seen))
        except (OSError, UnicodeError):
            pass
    time.sleep(.01)
"""


def wait_ready(name):
    for _ in range(30):
        if docker("exec", name, "test", "-f", "/app/ready", check=False).returncode == 0:
            return
        time.sleep(.05)
    raise RuntimeError("candidate watcher failed to start")


def observations(name):
    result = docker("exec", name, "cat", "/app/observations.json", check=False)
    return json.loads(result.stdout) if result.returncode == 0 else {}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-safe", action="store_true")
    args = parser.parse_args()
    docker("image", "inspect", IMAGE)
    prefix = "objrun-isolation-" + uuid.uuid4().hex[:10]
    names, snapshots = [], []
    evidence = {"image": IMAGE, "officialTask": False, "llmRequests": 0}
    try:
        with tempfile.TemporaryDirectory(prefix="isolation-", dir=ROOT / "test") as tmp:
            root = Path(tmp)
            task = {"dir": str(root), "cpus": "1", "memory": "128m", "workdir": "/app", "verify_seconds": 10}
            for folder in ("tests", "verifier"):
                fixture = root / folder
                fixture.mkdir()
                (fixture / "reference.txt").write_text("SYNTHETIC-HIDDEN-MARKER", encoding="utf-8")
                (fixture / "test.sh").write_text("#!/bin/sh\nmkdir -p /logs/verifier\necho SYNTHETIC-HIDDEN-MARKER\nsleep 1\necho 1 > /logs/verifier/reward.txt\n", encoding="utf-8", newline="\n")
            env = {"Path": Path, "json": json, "os": os, "shutil": shutil, "subprocess": subprocess, "threading": threading, "time": time, "hmac": hmac,
                   "BACKEND": "docker", "BOOK": {"case": task}, "TID_OF": {}, "LOGS": root / "logs", "LEVEL": 2,
                   "ALLOW_UNSAFE_DIAGNOSTIC": True, "GRADER_TOKEN": "synthetic-host-only-grader-token", "BaseHTTPRequestHandler": BaseHTTPRequestHandler,
                   "network_of": lambda _: "bridge", "task_id_of": lambda tid: tid.split("/")[-1], "require_result": lambda got: got,
                   "fault_payload": lambda _: {"valid": False}, "note_of": lambda *_: ""}

            tb = dict(env)
            tb_names = {"sh", "apptainer_host_env", "exec_argv", "cexec", "upload", "download_verifier", "parse_reward", "run_verifier"}
            source = (ROOT / "examples" / "benchmark" / "terminal-bench" / "stand.py").read_text(encoding="utf-8")
            if any(isinstance(n, ast.FunctionDef) and n.name == "require_isolation" for n in ast.parse(source).body):
                tb_names.add("require_isolation")
            definitions("terminal-bench", tb_names, tb)
            name = prefix + "-tb"
            names.append(name)
            docker("run", "--pull", "never", "-d", "--name", name, "--network", "bridge", "--memory", "128m", "--cpus", "1", "-w", "/app", IMAGE, "python", "-u", "-c", WATCHER)
            wait_ready(name)
            reward = tb["run_verifier"]("case", name)
            evidence["tbSharedLiveDiagnosticReward"] = reward["reward"]
            evidence["tbSharedLiveObservedBySolver"] = observations(name)
            evidence["tbOfficialModeBlocked"] = False
            if "require_isolation" in tb:
                tb["ALLOW_UNSAFE_DIAGNOSTIC"] = False
                try:
                    tb["require_isolation"]()
                except RuntimeError:
                    evidence["tbOfficialModeBlocked"] = True

            skb = dict(env)
            definitions("skillsbench", {"sh", "apptainer_host_env", "require_isolation", "wipe", "run_verifier", "judge", "Handler", "task_of"}, skb)
            name = prefix + "-skb"
            names.append(name)
            docker("run", "--pull", "never", "-d", "--name", name, "--network", "bridge", "--memory", "128m", "--cpus", "1", "-w", "/app", IMAGE, "python", "-u", "-c", WATCHER)
            wait_ready(name)
            snap = prefix + ":snapshot"
            snapshots.append(snap)
            docker("commit", name, snap)
            reward = skb["run_verifier"]("case", snap, prefix)
            evidence["skbSnapshotReward"] = reward["reward"]
            evidence["skbObservedByLiveSolver"] = observations(name)

            # Same changed paths, different contents: old docker-diff tags
            # could collide across runs. Exercise the actual concurrent judge.
            (root / "verifier" / "test.sh").write_text("#!/bin/sh\nmkdir -p /logs/verifier\necho SYNTHETIC-HIDDEN-MARKER\nsleep 1\nif [ \"$(cat /app/answer)\" = A ]; then echo 1; else echo 0; fi > /logs/verifier/reward.txt\n", encoding="utf-8", newline="\n")
            other = prefix + "-skb-b"
            names.append(other)
            docker("run", "--pull", "never", "-d", "--name", other, "--network", "bridge", "--memory", "128m", "--cpus", "1", "-w", "/app", IMAGE, "python", "-u", "-c", WATCHER)
            wait_ready(other)
            docker("exec", name, "sh", "-c", "printf A > /app/answer")
            docker("exec", other, "sh", "-c", "printf B > /app/answer")
            diffs = [sorted(docker("diff", container).stdout.splitlines()) for container in (name, other)]
            evidence["concurrentCandidatesHaveSamePathDiff"] = diffs[0] == diffs[1]
            if diffs[0] != diffs[1]:
                evidence["syntheticCandidatePathDiffs"] = diffs
            skb.update({"ALLOW_UNSAFE_DIAGNOSTIC": False, "uuid": uuid, "CACHE_LOCK": threading.Lock(), "INFLIGHT": {}, "GATE": threading.Semaphore(2), "container_up": lambda place: place})
            concurrent = {}
            graders = [threading.Thread(target=lambda label=label, container=container: concurrent.update({label: skb["judge"](container, "case")["reward"]})) for label, container in (("A", name), ("B", other))]
            for grader in graders:
                grader.start()
            for grader in graders:
                grader.join(timeout=20)
                if grader.is_alive():
                    raise RuntimeError("concurrent synthetic grading exceeded its bound")
            evidence["skbConcurrentPrivateSnapshotRewards"] = concurrent
            evidence["skbOtherLiveSolverObservations"] = observations(other)

            # Exercise a real HTTP handler from the Docker bridge, proving reachability
            # even when the stand binds the Windows host's loopback address.
            skb["ALLOW_UNSAFE_DIAGNOSTIC"] = False
            grade_calls = []
            skb["judge"] = lambda *_: grade_calls.append(True) or {"reward": 1, "ran": True}
            server = ThreadingHTTPServer(("127.0.0.1", 0), skb["Handler"])
            thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
            thread.start()
            try:
                code = "import json,os,urllib.request,urllib.error; url='http://host.docker.internal:%s/grade'; req=urllib.request.Request(url,b'{\"place\":\"skb:case\"}',{'content-type':'application/json'});\ntry:\n r=urllib.request.urlopen(req,timeout=5); status=r.status; r.close()\nexcept urllib.error.HTTPError as e:\n status=e.code; e.close()\nprint(json.dumps({'status':status,'hostCredentialsPresent':any(k.startswith(('TGENGIN_', 'OPENAI_', 'ANTHROPIC_')) for k in os.environ)}))" % server.server_port
                with_env = os.environ.copy()
                with_env["TGENGIN_GRADER_TOKEN"] = "host-marker-never-copied-to-docker"
                with_env["OPENAI_API_KEY"] = "host-marker-never-copied-to-docker"
                result = docker("exec", name, "python", "-c", code, env=with_env)
                evidence["dockerToHostHttp"] = json.loads(result.stdout)
                evidence["unauthenticatedGradeCalls"] = len(grade_calls)
            finally:
                server.shutdown()
                server.server_close()
                thread.join(timeout=2)
            print(json.dumps(evidence, indent=2))
            if args.expect_safe:
                assert evidence["tbSharedLiveObservedBySolver"].get("tests"), "The diagnostic failed to reproduce the live-container leak"
                assert evidence["tbOfficialModeBlocked"], "Unsafe TB shared-live grading is still enabled"
                assert not evidence["skbObservedByLiveSolver"], "SKB live solver read isolated verifier files"
                assert evidence["skbSnapshotReward"] == 1, "The isolated fixture did not score correctly"
                assert evidence["concurrentCandidatesHaveSamePathDiff"], "The concurrency collision fixture is not comparable"
                assert evidence["skbConcurrentPrivateSnapshotRewards"] == {"A": 1, "B": 0}, "Concurrent candidate states contaminated their grades"
                assert not evidence["skbOtherLiveSolverObservations"], "A concurrent solver read verifier files"
                assert evidence["dockerToHostHttp"]["status"] == 401, "Docker bypassed grader authentication"
                assert not evidence["dockerToHostHttp"]["hostCredentialsPresent"], "Host credentials reached the solver"
                assert evidence["unauthenticatedGradeCalls"] == 0, "An unauthenticated call consumed a grade"
    finally:
        for name in names:
            docker("rm", "-f", name, check=False)
        # The verifier's name is generated by the actual adapter from our unique key.
        docker("rm", "-f", "skb-verify-case-" + prefix, check=False)
        for snap in snapshots:
            docker("rmi", snap, check=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
