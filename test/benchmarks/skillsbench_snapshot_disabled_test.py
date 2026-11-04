"""No Docker needed: deny formal snapshot scoring before candidate access."""
import ast
from http.server import BaseHTTPRequestHandler
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / "examples/benchmark/skillsbench/stand.py"


def namespace(backend="docker", diagnostic=False):
    names = {"require_isolation", "isolation_status", "judge", "Handler"}
    nodes = [n for n in ast.parse(PATH.read_text(encoding="utf-8")).body if isinstance(n, (ast.FunctionDef, ast.ClassDef)) and n.name in names]
    values = {"BACKEND": backend, "LEVEL": 2, "ALLOW_UNSAFE_DIAGNOSTIC": diagnostic, "BaseHTTPRequestHandler": BaseHTTPRequestHandler}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(PATH), "exec"), values)
    return values


class DisabledTests(unittest.TestCase):
    def test_formal_docker_rejected_before_container_or_snapshot(self):
        value = namespace()
        calls = []
        value["container_up"] = lambda place: calls.append(place)
        result = value["judge"]("skb:run/task", "task")
        self.assertTrue(result["crashed"])
        self.assertIn("candidate-controlled", result["why"])
        self.assertEqual(calls, [])

    def test_only_explicit_diagnostic_can_enter_old_backend(self):
        for backend in ["docker", "apptainer"]:
            with self.subTest(backend=backend):
                value = namespace(backend, True)
                value["require_isolation"]()
                self.assertFalse(value["isolation_status"]()["isolationReady"])
                self.assertFalse(value["isolation_status"]()["formalGradingEnabled"])

    def test_health_status_never_claims_snapshot_ready(self):
        for diagnostic in [False, True]:
            value = namespace("docker", diagnostic)
            status = value["isolation_status"]()
            self.assertFalse(status["isolationReady"])
            self.assertEqual(status["supportedTaskIds"], [])
            self.assertEqual(status["unsafeDiagnostic"], diagnostic)
            self.assertIn("candidate-controlled", status["isolationReason"])
            # Exercise the production Handler branch, not just its helper.
            value.update(BOOK={str(i): {} for i in range(87)}, SKIP=[str(i) for i in range(11)],
                         SKILLS="with", NETWORK=True, GRADERS=1, GRADER_TOKEN="fixture")
            handler = object.__new__(value["Handler"])
            handler.path = "/health"
            responses = []
            handler._send = lambda body, *args: responses.append(body)
            handler.do_GET()
            self.assertEqual(responses[0]["tasks"], 87)
            self.assertEqual(responses[0]["usable"], 0)
            self.assertEqual(responses[0]["diagnosticUsable"], 76)
            self.assertFalse(responses[0]["isolationReady"])

    def test_apptainer_formal_still_rejected(self):
        value = namespace("apptainer")
        with self.assertRaises(RuntimeError):
            value["require_isolation"]()


if __name__ == "__main__":
    unittest.main()
