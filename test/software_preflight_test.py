"""Protect corpus identity, cached-image admission and local resource boundaries."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("software_preflight", ROOT / "scripts/benchmark-repair/software-preflight.py")
PREFLIGHT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PREFLIGHT)


class SoftwarePreflightTests(unittest.TestCase):
    def test_dockerfile_heredoc_imports_are_not_counted_as_missing_base_images(self):
        text = "FROM ubuntu:24.04 AS build\nRUN <<'EOF'\npython - <<'PY'\nfrom huggingface_hub import snapshot_download\nPY\nEOF\nFROM build AS final\n"
        bases = PREFLIGHT.dockerfile_bases(text, {})
        self.assertEqual([base["reference"] for base in bases], ["ubuntu:24.04", "build"])
        self.assertEqual(bases[1]["kind"], "local-build-stage")

    def make_corpus(self, root):
        task = root / "tasks/case"
        for name in ("environment", "oracle", "verifier"):
            (task / name).mkdir(parents=True)
        (task / "task.md").write_text("---\nenvironment:\n  cpus: 1\n  memory_mb: 2048\nagent:\n  timeout_sec: 300\nverifier:\n  timeout_sec: 300\n---\nSynthetic task\n", encoding="utf-8")
        (task / "environment/Dockerfile").write_text("FROM python:3.12.11-slim-bookworm\nWORKDIR /app\nCOPY input.txt /app/input.txt\n", encoding="utf-8")
        (task / "environment/input.txt").write_text("synthetic-input", encoding="utf-8")
        (task / "oracle/solve.sh").write_text("#!/bin/sh\ntrue\n", encoding="utf-8")
        (task / "verifier/test.sh").write_text("#!/bin/sh\nfalse\n", encoding="utf-8")
        return task

    def test_a_cached_generic_base_never_counts_as_a_task_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.make_corpus(root)
            cached = {"python:3.12.11-slim-bookworm": {"imageId": "sha256:base", "sizeBytes": 100}}
            row = PREFLIGHT.inspect_tasks(root, cached)[0]
            self.assertTrue(row["image"]["baseImages"][0]["cached"])
            self.assertFalse(row["image"]["cached"])
            self.assertIsNone(row["image"]["imageId"])
            self.assertEqual(row["preflight"]["status"], "blocked_missing_cached_task_image")
            self.assertIsNone(row["preflight"]["empty"])
            self.assertIsNone(row["preflight"]["oracle"])

    def test_only_the_real_environment_fingerprint_admits_a_cached_image(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            task = self.make_corpus(root)
            tag = "skb-task-case:" + PREFLIGHT.tree_digest(task / "environment")[:12]
            row = PREFLIGHT.inspect_tasks(root, {tag: {"imageId": "sha256:task", "sizeBytes": 100}})[0]
            self.assertTrue(row["image"]["cached"])
            self.assertEqual(row["image"]["imageId"], "sha256:task")
            (task / "environment/input.txt").write_text("changed-input", encoding="utf-8")
            changed = PREFLIGHT.inspect_tasks(root, {tag: {"imageId": "sha256:task", "sizeBytes": 100}})[0]
            self.assertFalse(changed["image"]["cached"])

    def runner(self):
        runner = PREFLIGHT.Runner.__new__(PREFLIGHT.Runner)
        runner.owned_containers = set()
        runner.owned_images = set()
        runner.deadline = time.monotonic() + 30
        runner.args = SimpleNamespace(max_memory_mb=2048, max_cpus=2, max_writable_mb=512)
        runner.check_resources = Mock()
        return runner

    def test_the_preflight_never_pulls_builds_or_removes_another_job_resource(self):
        runner = self.runner()
        for argv in (("docker", "pull", "any-image"), ("docker", "build", "."), ("docker", "rm", "-f", "user-container"), ("docker", "rmi", "user-image")):
            with self.subTest(argv=argv), self.assertRaises(RuntimeError):
                runner.shell(*argv)

    def test_official_resources_are_not_silently_lowered_to_make_a_task_fit(self):
        runner = self.runner()
        runner.score = Mock()
        row = {"image": {"cached": True}, "officialBudget": {"memoryMB": 4096, "cpus": "1"}, "preflight": {}}
        runner.run_task(row)
        self.assertEqual(row["preflight"]["status"], "blocked_official_resources_above_preflight_admission_limit")
        runner.score.assert_not_called()
        self.assertEqual(row["officialBudget"]["memoryMB"], 4096)

    def test_cli_output_is_bounded_before_it_can_exhaust_host_memory(self):
        runner = self.runner()
        result = runner.bounded_run([sys.executable, "-c", "import sys; sys.stdout.write('x' * (3 * 1024 * 1024))"], 5, cleanup=True)
        self.assertEqual(result.returncode, 0)
        self.assertEqual(len(result.stdout), 1024 * 1024)

    def test_the_overall_process_timeout_terminates_the_local_cli(self):
        runner = self.runner()
        with self.assertRaises(subprocess.TimeoutExpired):
            runner.bounded_run([sys.executable, "-c", "import time; time.sleep(10)"], .1, cleanup=True)


if __name__ == "__main__":
    unittest.main()
