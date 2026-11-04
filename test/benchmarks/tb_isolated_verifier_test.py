"""Protocol guards for the live TB verifier; actual Docker proof is separate."""
import importlib.util
import json
from pathlib import Path
import shutil
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
from container_isolation_test import definitions

ROOT = Path(__file__).resolve().parents[2]
MODULE = ROOT / "examples/benchmark/terminal-bench/isolated_verifier.py"
SPEC = importlib.util.spec_from_file_location("tb_isolation_guard", MODULE)
V = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(V)
SOURCE = ROOT / ".phase1-data/terminal-bench/vendor/terminal-bench-2-1/tasks" / V.TASK_ID


class LiveVerifierGuards(unittest.TestCase):
    def test_changed_test_or_definition_is_not_admitted(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for file in V.SOURCE_HASHES:
                (root / file).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(SOURCE / file, root / file)
            task = {"id": V.TASK_ID, "dir": str(root)}
            self.assertTrue(V.supports(task))
            with (root / "tests/test_outputs.py").open("a", encoding="utf-8") as output:
                output.write("\n# a changed verifier must be re-audited\n")
            self.assertFalse(V.supports(task))
            self.assertFalse(V.supports({**task, "id": "other-task"}))

    def test_broker_is_tls_authenticated_and_has_no_arbitrary_io(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(V, "docker") as execute:
            execute.return_value = subprocess.CompletedProcess([], 0, "", "")
            broker = V.StateBroker("owned-probe-only", Path(directory))
            try:
                url = broker.url.replace("host.docker.internal", "localhost")
                context = ssl.create_default_context(cafile=str(broker.certificate))
                def request(body, token=None):
                    headers = {"content-type": "application/json"}
                    if token:
                        headers["X-ObjRun-State-Token"] = token
                    req = urllib.request.Request(url, json.dumps(body).encode(), headers)
                    try:
                        with urllib.request.urlopen(req, context=context, timeout=5) as response:
                            return response.status, json.load(response)
                    except urllib.error.HTTPError as error:
                        return error.code, json.load(error)
                self.assertEqual(request({"op": "read", "path": "/etc/nginx/nginx.conf"})[0], 401)
                self.assertEqual(request({"op": "read", "path": "/tests/test_outputs.py"}, broker.token)[0], 422)
                self.assertEqual(request({"op": "command", "argv": ["sh", "-c", "cat /tests/*"]}, broker.token)[0], 422)
                self.assertEqual(request({"op": "exists", "path": "/etc/nginx/nginx.conf", "extra": True}, broker.token)[0], 422)
                execute.assert_not_called()
                self.assertEqual(request({"op": "exists", "path": "/etc/nginx/nginx.conf"}, broker.token), (200, {"exists": True}))
                self.assertEqual(execute.call_args.args, ("exec", "owned-probe-only", "test", "-e", "/etc/nginx/nginx.conf"))
                with self.assertRaises(urllib.error.URLError):
                    urllib.request.urlopen(url, timeout=5)  # a system CA cannot authenticate the ephemeral broker
            finally:
                broker.close()

    def test_narrow_io_does_not_allow_traversal_or_non_objects(self):
        owner = object.__new__(V.StateBroker)
        with patch.object(V, "docker") as execute:
            for value in (["read"], {"op": "read", "path": "/etc/nginx/../passwd"}, {"op": "command", "argv": "nginx -t"}):
                with self.subTest(value=value), self.assertRaises(ValueError):
                    owner.query(value)
            execute.assert_not_called()

    def test_untrusted_process_output_is_bounded_before_capture_completes(self):
        spawn = subprocess.Popen
        def redirected(_argv, **options):
            return spawn([sys.executable, "-c", "import os;\nwhile True: os.write(1,b'X'*8192)"], **options)
        with patch.object(V.subprocess, "Popen", side_effect=redirected), self.assertRaises(V.ResourceBoundaryError):
            V.docker("exec", "owned-probe-only", "cat", "/etc/nginx/nginx.conf", timeout=3)

    def test_process_timeout_does_not_become_model_failure(self):
        spawn = subprocess.Popen
        with patch.object(V.subprocess, "Popen", side_effect=lambda _argv, **options: spawn([sys.executable, "-c", "import time;time.sleep(10)"], **options)):
            with self.assertRaises(subprocess.TimeoutExpired):
                V.docker("exec", "owned-probe-only", "nginx", "-t", timeout=.1)

    def test_operational_space_overflow_is_an_infrastructure_fault(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(V.shutil, "disk_usage") as usage, patch.object(V, "checked") as inspect:
            usage.return_value = Mock(free=V.MIN_HOST_FREE_BYTES + 1)
            inspect.return_value = Mock(stdout=str(V.MAX_WRITABLE_BYTES + 1) + "\n")
            with self.assertRaises(V.ResourceBoundaryError):
                V.check_resources("owned-probe-only", None, Path(directory))
            usage.return_value = Mock(free=V.MIN_HOST_FREE_BYTES - 1)
            inspect.reset_mock()
            with self.assertRaises(V.ResourceBoundaryError):
                V.check_resources("owned-probe-only", None, Path(directory))
            inspect.assert_not_called()

    def test_unsupported_task_never_creates_a_grader(self):
        with patch.object(V, "docker") as execute, self.assertRaises(RuntimeError):
            V.run_verifier({"id": "unsupported"}, "owned-probe-only", Path("not-used"))
        execute.assert_not_called()

    def test_formal_admission_serializes_two_distinct_live_candidates(self):
        names, failures = [], []
        def shell(*argv):
            if argv[:2] == ("docker", "inspect"):
                return subprocess.CompletedProcess(argv, 1, "", "")
            if argv[:2] == ("docker", "ps"):
                return subprocess.CompletedProcess(argv, 0, "\n".join(names), "")
            if argv[:2] == ("docker", "run"):
                time.sleep(.05)
                names.append(argv[argv.index("--name") + 1])
            return subprocess.CompletedProcess(argv, 0, "", "")
        task = {"cpus": "1", "memory_mb": 2048, "image": "unused"}
        env = {"BACKEND": "docker", "ALLOW_UNSAFE_DIAGNOSTIC": False, "BOOK": {V.TASK_ID: task},
               "require_isolation": lambda _tid: None, "container_of": lambda place: "owned-" + place.split(":")[1].split("/")[0],
               "task_id_of": lambda place: place.split("/")[-1], "sh": shell, "shutil": shutil,
               "LOGS": Path(tempfile.gettempdir()), "isolated_verifier": Mock(IMAGE_ID=V.IMAGE_ID, MIN_HOST_FREE_BYTES=0),
               "runtime_ready": lambda: True, "UP_LOCK": threading.Lock(), "CREATED_CONTAINERS": set(),
               "ship_runtime": lambda _name: None, "remove": lambda _name: None}
        env["isolated_verifier"].supports.return_value = True
        definitions("terminal-bench", {"container_up", "docker_container_up"}, env)
        def attempt(place):
            try:
                env["container_up"](place)
            except RuntimeError as error:
                failures.append(str(error))
        threads = [threading.Thread(target=attempt, args=("tb:" + run + "/" + V.TASK_ID,)) for run in ("a", "b")]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=2)
            self.assertFalse(thread.is_alive())
        self.assertEqual(len(names), 1)
        self.assertEqual(len(failures), 1)
        self.assertIn("capacity is occupied", failures[0])

    def test_formal_stand_does_not_delete_a_foreign_same_name_container(self):
        shell = Mock(return_value=subprocess.CompletedProcess([], 0, "exists", ""))
        env = {"BACKEND": "docker", "ALLOW_UNSAFE_DIAGNOSTIC": False, "CREATED_CONTAINERS": set(), "sh": shell}
        definitions("terminal-bench", {"remove"}, env)
        with self.assertRaises(RuntimeError):
            env["remove"]("foreign-container")
        self.assertEqual(shell.call_count, 1)
        self.assertEqual(shell.call_args.args[:2], ("docker", "inspect"))
        env["CREATED_CONTAINERS"].add("owned-container")
        env["remove"]("owned-container")
        self.assertEqual(shell.call_args.args, ("docker", "rm", "-f", "owned-container"))
        self.assertNotIn("owned-container", env["CREATED_CONTAINERS"])

    def test_preseed_profile_checks_versions_environment_and_asset_hashes(self):
        cache = ROOT / "examples/benchmark/terminal-bench/.verifier-deps/uv095-python3137-v1"
        with patch.object(V, "DEPENDENCIES", cache):
            profile = V.dependency_profile()
            self.assertEqual(profile["python"], "3.13.7")
            self.assertEqual(profile["packages"]["requests"], "2.32.4")
            actual = V.file_digest
            with patch.object(V, "file_digest", side_effect=lambda file: "wrong" if file.name == "uv" else actual(file)):
                self.assertFalse(V.dependency_ready())
        with tempfile.TemporaryDirectory() as temporary:
            altered = {**profile, "offlineEnvironment": {**profile["offlineEnvironment"], "LD_PRELOAD": "/unsafe"}}
            directory = Path(temporary)
            (directory / "manifest.json").write_text(json.dumps(altered), encoding="utf-8")
            with patch.object(V, "DEPENDENCIES", directory):
                self.assertFalse(V.dependency_ready())
                with self.assertRaises(RuntimeError):
                    V.dependency_profile()


if __name__ == "__main__":
    unittest.main()
