"""Regression checks for the actual TB/SKB adapter security seams.

AST loading avoids requiring private corpora. The real upload/launch/HTTP
definitions are exercised; subprocesses are replaced only where this machine
cannot run Apptainer. Actual Docker evidence is recorded separately.
"""
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
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import uuid

ROOT = Path(__file__).resolve().parents[1]
BENCHES = ("terminal-bench", "skillsbench")


def definitions(slug, names, namespace):
    path = ROOT / "examples" / "benchmark" / slug / "stand.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    selected = [n for n in tree.body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    if len(selected) != len(names):
        raise AssertionError("Expected the real adapter definitions")
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


class ContainerIsolationTests(unittest.TestCase):
    def test_formal_feedback_does_not_expose_reference_bearing_pytest_names(self):
        got = {"reward": 0, "_tests": [{"name": "normal", "status": "passed"}, {"name": "answer[PRIVATE-REFERENCE-MARKER]", "status": "failed", "message": "PRIVATE-REFERENCE-MARKER"}]}
        for slug in BENCHES:
            with self.subTest(slug=slug):
                env = {"LEVEL": 2, "ALLOW_UNSAFE_DIAGNOSTIC": False}
                definitions(slug, {"note_of"}, env)
                note = env["note_of"]("case", got) if slug == "skillsbench" else env["note_of"](got)
                self.assertNotIn("PRIVATE-REFERENCE-MARKER", json.dumps(note))
                self.assertEqual(note["failing"], ["test#2"])

    def test_concurrent_candidates_with_identical_path_diff_get_private_snapshots(self):
        commits = []
        barrier = threading.Barrier(2)

        def shell(*argv):
            if argv[:2] == ("docker", "commit"):
                commits.append((argv[2], argv[3]))
            return subprocess.CompletedProcess(argv, 0, "", "")

        def verify(_tid, image, key):
            barrier.wait(timeout=2)
            return {"reward": 1, "image": image, "logKey": key}

        env = {"time": time, "uuid": uuid, "threading": threading, "subprocess": subprocess, "CACHE_LOCK": threading.Lock(), "INFLIGHT": {}, "GATE": threading.Semaphore(2), "BOOK": {"case": {"verify_seconds": 1}}, "BACKEND": "docker", "container_up": lambda place: place, "state_key": lambda _: "same-diff", "sh": shell, "run_verifier": verify}
        # Old snapshot naming is a diagnostic-only boundary check. It does not
        # establish that the cloned interpreter or scorer is trusted.
        env["ALLOW_UNSAFE_DIAGNOSTIC"] = True
        definitions("skillsbench", {"judge", "require_isolation"}, env)
        results = []
        threads = [threading.Thread(target=lambda place=place: results.append(env["judge"](place, "case"))) for place in ("solver-a", "solver-b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=4)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(results), 2)
        self.assertEqual(len(commits), 2)
        self.assertNotEqual(commits[0][1], commits[1][1], "Different solver states can overwrite one snapshot tag")
        self.assertNotEqual(results[0]["logKey"], results[1]["logKey"], "Different solver states share the verifier container and log directory")

    def test_apptainer_upload_never_keeps_a_readable_hidden_stage_copy(self):
        for slug in BENCHES:
            for fail in (False, True):
                with self.subTest(slug=slug, fail=fail), tempfile.TemporaryDirectory() as tmp:
                    root = Path(tmp)
                    src = root / "tests"
                    src.mkdir()
                    (src / "reference.txt").write_text("PRIVATE-REFERENCE-MARKER", encoding="utf-8")
                    observed = []

                    def copy(*_args):
                        observed.append((root / "stage" / "solver" / "tests" / "reference.txt").read_text())
                        if fail:
                            raise RuntimeError("copy failed")
                        return subprocess.CompletedProcess([], 0, "", "")

                    env = {"Path": Path, "shutil": shutil, "subprocess": subprocess, "BACKEND": "apptainer", "STAGE": root / "stage", "cexec": copy}
                    definitions(slug, {"upload"}, env)
                    if fail:
                        with self.assertRaises(RuntimeError):
                            env["upload"]("solver", src, "/tests")
                    else:
                        env["upload"]("solver", src, "/tests")
                    self.assertEqual(observed, ["PRIVATE-REFERENCE-MARKER"])
                    self.assertFalse((root / "stage" / "solver" / "tests").exists(), "hidden tests remain readable through /stage")

    def test_apptainer_exec_cannot_inherit_grader_or_llm_environment(self):
        for slug in BENCHES:
            with self.subTest(slug=slug):
                env = {"BACKEND": "apptainer", "BOOK": {"case": {"workdir": "/app"}}, "TID_OF": {"solver": "case"}}
                definitions(slug, {"exec_argv"}, env)
                self.assertIn("--cleanenv", env["exec_argv"]("solver", "env"))

    def test_apptainer_cli_drops_environment_injection_and_host_bind_overrides(self):
        for slug in BENCHES:
            with self.subTest(slug=slug):
                env = {"os": os, "subprocess": subprocess}
                definitions(slug, {"sh", "apptainer_host_env"}, env)
                hostile = {"APPTAINERENV_PRIVATE_KEY": "do-not-pass", "SINGULARITYENV_GRADER_TOKEN": "do-not-pass", "APPTAINER_BINDPATH": "/host:/secret", "SINGULARITY_BIND": "/host:/secret", "PATH": os.environ.get("PATH", "")}
                with patch.dict(os.environ, hostile, clear=True), patch.object(subprocess, "run", return_value=subprocess.CompletedProcess([], 0)) as run:
                    env["sh"]("apptainer", "exec", "--cleanenv", "image", "env")
                    launched = run.call_args.kwargs.get("env", {})
                    self.assertIn("PATH", launched)
                    self.assertFalse(any(k.startswith(("APPTAINERENV_", "SINGULARITYENV_")) or k in ("APPTAINER_BINDPATH", "SINGULARITY_BIND") for k in launched))

    def test_unisolated_apptainer_is_rejected_before_starting_solver(self):
        for slug in BENCHES:
            with self.subTest(slug=slug):
                started = Mock(return_value="solver")
                env = {"BACKEND": "apptainer", "LEVEL": 2, "ALLOW_UNSAFE_DIAGNOSTIC": False, "container_of": lambda _: "solver", "task_id_of": lambda _: "case", "instance_up": started, "BOOK": {"case": {}}, "os": os}
                # Include the enforcement helper when implemented, while the old
                # version reaches instance_up and fails this behavior check.
                tree = ast.parse((ROOT / "examples" / "benchmark" / slug / "stand.py").read_text(encoding="utf-8"))
                names = {"container_up"}
                if any(isinstance(n, ast.FunctionDef) and n.name == "require_isolation" for n in tree.body):
                    names.add("require_isolation")
                definitions(slug, names, env)
                with self.assertRaisesRegex(RuntimeError, "isolation"):
                    env["container_up"]("bench:case")
                started.assert_not_called()

    def test_unauthenticated_http_cannot_call_grader_or_solver_tools(self):
        for slug in BENCHES:
            with self.subTest(slug=slug):
                judge = Mock(return_value={"reward": 1, "ran": True})
                runtime = Mock()
                env = {"json": json, "hmac": hmac, "BaseHTTPRequestHandler": BaseHTTPRequestHandler, "BOOK": {"case": {}}, "task_id_of": lambda tid: tid.split("/")[-1], "container_of": lambda place: place, "judge": judge, "judged": lambda *_: None, "runtime_of": runtime, "note_of": lambda *_: "", "GRADER_TOKEN": "host-only-fixture-token", "ALLOW_UNSAFE_DIAGNOSTIC": False, "require_result": lambda got: got, "fault_payload": lambda _: {"valid": False}}
                definitions(slug, {"Handler", "task_of"}, env)
                server = ThreadingHTTPServer(("127.0.0.1", 0), env["Handler"])
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
                thread.start()
                try:
                    for route in ("/grade", "/place", "/stop", "/passed"):
                        req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}{route}", b'{"place":"bench:case"}', {"content-type": "application/json"})
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(req, timeout=2)
                        self.assertEqual(error.exception.code, 401)
                        error.exception.close()
                    judge.assert_not_called()
                    runtime.assert_not_called()
                    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/grade", b'{"place":"bench:case"}', {"content-type": "application/json", "X-ObjRun-Grader-Token": env["GRADER_TOKEN"]})
                    with urllib.request.urlopen(req, timeout=2) as response:
                        self.assertEqual(response.status, 200)
                    judge.assert_called_once()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)

    def test_missing_auth_configuration_fails_closed_and_legacy_mode_is_explicit(self):
        for slug in BENCHES:
            with self.subTest(slug=slug):
                judge = Mock(return_value={"reward": 1, "ran": True})
                env = {"json": json, "hmac": hmac, "BaseHTTPRequestHandler": BaseHTTPRequestHandler, "BOOK": {"case": {}}, "task_id_of": lambda tid: tid.split("/")[-1], "container_of": lambda place: place, "judge": judge, "GRADER_TOKEN": "", "ALLOW_UNSAFE_DIAGNOSTIC": False, "require_result": lambda got: got, "fault_payload": lambda _: {"valid": False}}
                definitions(slug, {"Handler", "task_of"}, env)
                server = ThreadingHTTPServer(("127.0.0.1", 0), env["Handler"])
                thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
                thread.start()
                try:
                    req = urllib.request.Request(f"http://127.0.0.1:{server.server_port}/grade", b'{"place":"bench:case"}', {"content-type": "application/json"})
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(req, timeout=2)
                    self.assertEqual(error.exception.code, 503)
                    error.exception.close()
                    judge.assert_not_called()
                    env["ALLOW_UNSAFE_DIAGNOSTIC"] = True
                    with urllib.request.urlopen(req, timeout=2) as response:
                        self.assertEqual(response.status, 200)
                    judge.assert_called_once()
                finally:
                    server.shutdown()
                    server.server_close()
                    thread.join(timeout=2)


class SenderIsolationTests(unittest.TestCase):
    """Run the actual senders against a fake stand and fake engine, with no LLM."""
    def test_publication_requires_isolation_and_keeps_the_key_out_of_task_json(self):
        bun = shutil.which("bun")
        if not bun:
            self.skipTest("Bun is required for actual sender integration")
        for slug, prefix in (("terminal-bench", "TB"), ("skillsbench", "SKB")):
            for ready in (False, True):
                with self.subTest(slug=slug, ready=ready):
                    seen = []

                    class Fixture(BaseHTTPRequestHandler):
                        def log_message(self, *_args):
                            pass

                        def send(self, payload):
                            data = json.dumps(payload).encode()
                            self.send_response(200)
                            self.send_header("content-length", str(len(data)))
                            self.end_headers()
                            self.wfile.write(data)

                        def do_GET(self):
                            seen.append((self.path, self.headers.get("X-ObjRun-Grader-Token"), None))
                            if self.path == "/health":
                                self.send({"isolationReady": ready, "authenticated": True, "unsafeDiagnostic": False})
                            else:
                                self.send([{"id": "case", "instruction": "synthetic task", "seconds": 60, "workdir": "/app", "skills": []}])

                        def do_POST(self):
                            data = json.loads(self.rfile.read(int(self.headers["content-length"])))
                            seen.append((self.path, self.headers.get("X-ObjRun-Grader-Token"), data))
                            self.send({"ids": ["isolation-test/case"]})

                    server = ThreadingHTTPServer(("127.0.0.1", 0), Fixture)
                    thread = threading.Thread(target=server.serve_forever, kwargs={"poll_interval": .01}, daemon=True)
                    thread.start()
                    try:
                        origin = f"http://127.0.0.1:{server.server_port}"
                        env = {k: v for k, v in os.environ.items() if not k.startswith("TGENGIN_")}
                        env.update({"TGENGIN_GRADER_TOKEN": "host-only-fixture-marker", "TGENGIN_GRADER_ORIGINS": json.dumps([origin]), f"TGENGIN_{prefix}_STAND": origin, "TGENGIN_BASE": origin + "/api"})
                        result = subprocess.run([bun, str(ROOT / "examples" / "benchmark" / slug / "send.ts"), "1", "isolation-test", "0"], env=env, cwd=ROOT, capture_output=True, text=True, timeout=10)
                        if ready:
                            self.assertEqual(result.returncode, 0, result.stderr)
                            problems = [item for item in seen if item[0].startswith("/problems")]
                            self.assertEqual(problems[0][1], env["TGENGIN_GRADER_TOKEN"])
                            published = [item for item in seen if item[0] == "/api/bench"]
                            self.assertEqual(len(published), 1)
                            self.assertNotIn(env["TGENGIN_GRADER_TOKEN"], json.dumps(published[0][2]))
                        else:
                            self.assertNotEqual(result.returncode, 0)
                            self.assertEqual([item[0] for item in seen], ["/health"], result.stderr)
                    finally:
                        server.shutdown()
                        server.server_close()
                        thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
