"""Offline contract regressions; these do not certify a real image/control run."""
import importlib.util
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import tarfile
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock
import zipfile

PATH = Path(__file__).resolve().parents[2] / "scripts/benchmark-repair/software-jpg-private-grader.py"
spec = importlib.util.spec_from_file_location("jpg_private", PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class ContractTests(unittest.TestCase):
    def test_exact_official_one_test_contract_and_full_denominator(self):
        source = module.sources()
        self.assertEqual(len(source), 6)
        self.assertEqual(module.ARTIFACT, "/app/workspace/stat_ocr.xlsx")
        self.assertEqual(source["verifier/test.sh"], "013e2ee5d258c992c360d5b0d48a39e3efece51d49fad9c84c66fd211905df77")

    def test_normal_output_transfer_is_only_file_bytes(self):
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode="w") as archive:
            item = tarfile.TarInfo("stat_ocr.xlsx")
            item.size = 11
            archive.addfile(item, io.BytesIO(b"normal-file"))
        self.assertEqual(module.read_output_tar(buffer.getvalue()), b"normal-file")

    def test_wrong_workbook_is_readable_schema_fixture_without_ground_truth(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "stat_ocr.xlsx"
            module.write_wrong_workbook(path)
            with zipfile.ZipFile(path) as archive:
                text = archive.read("xl/worksheets/sheet1.xml").decode()
                self.assertIn("filename", text)
                self.assertIn("2001-01-01", text)
                self.assertNotIn("stat_oracle", str(archive.namelist()))

    def test_image_base_and_planning_estimate_never_satisfy_build_gate(self):
        source = module.sources()
        manifest = {"taskId": module.TASK_ID, "imageId": module.BASE_ID, "environmentSha256": module.ENV_HASH,
                    "baseImageId": module.BASE_ID, "completeOriginalTaskImage": True, "sourceHashes": source}
        with self.assertRaises(module.InvalidGrading):
            module.require_build(manifest, {"validated": True}, source)
        manifest["imageId"] = "sha256:" + "a"*64
        with self.assertRaises(module.InvalidGrading):
            module.require_build(manifest, {"validated": True, "actualBuildCompleted": False}, source)

    def test_successful_dependency_build_without_original_copy_certificate_is_rejected(self):
        evidence = PATH.parents[2]/"docs/repair-2026-10-08/software-jpg-build-c2d2fa5952"
        manifest = json.loads((evidence/"image-manifest-original-as-recorded.json").read_text())
        proof = json.loads((evidence/"build-proof.json").read_text())
        self.assertTrue(proof["validated"])
        with self.assertRaisesRegex(module.InvalidGrading, "public workspace"):
            module.require_build(manifest, proof, module.sources())

    def test_profile_tampering_is_invalid_before_docker(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            profile = root / "manifest.json"
            profile.write_text(json.dumps({"protocol": module.PROTOCOL, "imageId": "fixture", "uv": "0.9.7", "python": "3.12.3",
                "packages": {"pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "openpyxl": "3.1.5"},
                "assets": [{"path": "uv", "bytes": 2, "sha256": "0"*64}]}))
            (root / "uv").write_bytes(b"uv")
            with self.assertRaises(module.InvalidGrading):
                module.require_dependencies(profile, "fixture")

    def test_complete_negative_is_valid_but_zero_tests_is_infrastructure_invalid(self):
        profile = {"packages": {"pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "openpyxl": "3.1.5"}}
        versions = {"python": "3.12.3", "baseExecutable": "/usr/bin/python3.12", "uv": "uv 0.9.7", "uvSha256": "fixture", "packages": profile["packages"]}
        verdict = module.accepted_result("0", {"results": {"tests": [{"name": "test_outputs.py::test_outputs", "status": "failed"}]}}, versions, profile, "fixture")
        self.assertEqual(verdict["completedTests"], 1)
        self.assertTrue(verdict["valid"])
        self.assertEqual(verdict["reward"], 0)
        with self.assertRaises(module.InvalidGrading):
            module.accepted_result("0", {"results": {"tests": []}}, versions, profile, "fixture")

    def test_real_fixed_collector_empty_result_uses_qualified_node_name(self):
        evidence = PATH.parents[2]/"docs/repair-2026-10-08/software-jpg-controls-actual-v1/empty"
        profile = {"packages": {"pytest": "8.4.1", "pytest-json-ctrf": "0.3.5", "iniconfig": "2.1.0", "pluggy": "1.6.0",
                                "pygments": "2.19.2", "openpyxl": "3.1.5", "packaging": "26.3", "et-xmlfile": "2.0.0"}}
        versions = json.loads((evidence/"dependency-versions.json").read_text())
        verdict = module.accepted_result((evidence/"reward.txt").read_text(), json.loads((evidence/"ctrf.json").read_text()), versions, profile, versions["uvSha256"])
        self.assertTrue(verdict["valid"])
        self.assertEqual(verdict["completedTests"], 1)
        self.assertEqual(verdict["reward"], 0)

    def test_create_postcheck_failure_retains_exact_owned_cleanup_receipt(self):
        # A transport/resource failure after Docker create must not lose the
        # identity required for bounded host recovery. This test uses no Docker.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            docker = module.Docker(root)
            image = "sha256:"+"a"*64
            with mock.patch.object(docker, "checked", side_effect=module.InvalidGrading("post-create resource check failed")):
                with self.assertRaises(module.InvalidGrading):
                    docker.create(image, "grader", "none", ["-c", "sleep infinity"])
            receipt = json.loads((root/"operation-owner.json").read_text())
            pending = receipt["containers"][0]
            self.assertIn(pending["name"], docker.owned)
            self.assertEqual(pending["state"], "creation_pending")
            self.assertEqual(pending["expectedImageId"], image)
            config = {"Id": "b"*64, "Name": "/"+pending["name"], "Image": image,
                      "Config": {"Labels": {"objrun.jpg-owner": docker.prefix}}}
            calls = []
            def completed(argv, **kwargs):
                calls.append(argv)
                return SimpleNamespace(returncode=0, stdout=json.dumps([config]).encode() if argv[1] == "inspect" else b"", stderr=b"")
            with mock.patch.object(module.subprocess, "run", side_effect=completed):
                docker.remove(pending["name"])
            self.assertEqual(calls[-1], ["docker", "rm", "-f", config["Id"]])
            self.assertEqual(docker.owned, set())
            self.assertEqual(json.loads((root/"operation-owner.json").read_text())["containers"][0]["state"], "removed")

    def test_operation_lease_blocks_a_second_cli_until_the_owner_releases(self):
        with tempfile.TemporaryDirectory() as tmp:
            first, second = module.OwnedInstanceLease(), module.OwnedInstanceLease()
            first.path = second.path = Path(tmp)/"lease.lock"
            first.acquire()
            with self.assertRaises(module.InvalidGrading):
                second.acquire()
            self.assertTrue(first.path.is_file())
            first.release()
            second.acquire()
            second.release()
            self.assertFalse(first.path.exists())

    def test_nonzero_official_oracle_retains_its_output_before_cleanup(self):
        with tempfile.TemporaryDirectory() as tmp:
            docker = mock.Mock()
            docker.create.return_value = "this-operation-only"
            docker.run.return_value = SimpleNamespace(stdout="original oracle stdout", stderr="normal execution error", returncode=1)
            with self.assertRaisesRegex(module.InvalidGrading, "Original oracle failed"):
                module.oracle_workbook(docker, "fixture-image", Path(tmp))
            self.assertIn("normal execution error", (Path(tmp)/"oracle-execution.txt").read_text())
            docker.remove.assert_called_once_with("this-operation-only")

    def test_trusted_absent_and_declared_format_modes_reach_same_clean_empty_grader(self):
        # Mock transport/image only: this regression proves CLI classification,
        # not real grading, dependency validity, or a formal LLM closed loop.
        for state in ["absent", "directory", "symlink", "too_large"]:
            with self.subTest(state=state), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                image = "sha256:"+"a"*64
                for name in ["image.json", "build.json", "deps.json"]:
                    (root/name).write_text("{}")
                receipt = {"taskId": module.TASK_ID, "protocol": module.PROTOCOL, "ownedContainerID": "b"*64,
                           "containerStopped": True, "artifactPath": module.ARTIFACT, "state": state,
                           "daemonEvidence": {"containerId": "b"*64, "missingFileDiagnosticMatched": True}}
                (root/"capture.json").write_text(json.dumps(receipt))
                docker = mock.Mock()
                docker.owned = set(); docker.samples = []
                docker.checked.return_value = SimpleNamespace(stdout=json.dumps([{"Id": image, "Config": {"Labels": {
                    "objrun.skb.task-id": module.TASK_ID, "objrun.skb.environment-sha256": module.ENV_HASH}}}]))
                scorer = mock.Mock()
                scorer.grade.return_value = {"valid": True, "ran": True, "reward": 0, "completedTests": 1}
                flags = ["--captured-absent"] if state == "absent" else ["--captured-format-failure", state]
                argv = [str(PATH), "--grade", *flags, "--capture-receipt", str(root/"capture.json"),
                        "--image-manifest", str(root/"image.json"), "--build-proof", str(root/"build.json"),
                        "--dependency-profile", str(root/"deps.json"), "--output", str(root/"result")]
                with mock.patch("sys.argv", argv), mock.patch.object(module, "Docker", return_value=docker), \
                     mock.patch.object(module, "PrivateGrader", return_value=scorer), \
                     mock.patch.object(module, "require_build", return_value=image), \
                     mock.patch.object(module, "require_dependencies", return_value=({}, {})), redirect_stdout(io.StringIO()):
                    module.main()
                scorer.grade.assert_called_once_with(None, "candidate")
                result = json.loads((root/"result/report.json").read_text())
                self.assertTrue(result["candidateVerdict"]["valid"])
                self.assertEqual(result["candidateVerdict"]["reward"], 0)
                self.assertFalse(result["formalLlmClosedLoopValidated"])
                self.assertEqual(result["readyTaskIds"], [])
                if state != "absent":
                    self.assertEqual(result["candidateVerdict"]["outcome"], "budget_exhausted" if state == "too_large" else "invalid_artifact")


if __name__ == "__main__":
    unittest.main()
