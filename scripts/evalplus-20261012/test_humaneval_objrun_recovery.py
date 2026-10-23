import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location("recovery", Path(__file__).with_name("prepare-humaneval-objrun-recovery.py"))
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.out = Path(self.directory.name)
        self.expected = ["HumanEval/0", "HumanEval/1"]
        self.result = self.out / "results/objrun/HumanEval-0.json"
        self.good = self.out / "results/objrun/HumanEval-1.json"
        recovery.save(self.result, {"officialId": "HumanEval/0", "interfaceFailure": True, "interfaceRetryExhausted": True, "grade": {"valid": False}})
        recovery.save(self.good, {"officialId": "HumanEval/1", "grade": {"valid": True, "passed": False}})
        self.good_bytes = self.good.read_bytes()
        self.calls = self.out / "calls/objrun/HumanEval-0/schema-v3"
        self.failed = self.calls / "bad/attempt-0"
        for directory in (self.failed, self.failed / "authorized-interface-retry-1"):
            recovery.save(directory / "dispatch.json", {"pid": 5})
            recovery.save(directory / "receipt.json", {"httpStatus": 200, "fault": "Provider timed out after 301000ms", "unknownCost": True, "actualCostUsd": None, "upperBoundUsd": .02})
        self.cached = self.calls / "good/attempt-0"
        recovery.save(self.cached / "dispatch.json", {"pid": 5})
        recovery.save(self.cached / "receipt.json", {"httpStatus": 200, "actualCostUsd": .001})
        recovery.save(self.cached / "response.json", {"id": "original-success"})
        self.task = self.out / "tasks/objrun/HumanEval-0"
        (self.task / "engine/data").mkdir(parents=True)
        (self.task / "engine/data/h2h.sqlite").write_bytes(b"preserved-native-evidence")

    def plan(self, live=None):
        return recovery.make_plan(self.out, self.expected, live or [])

    def test_live_runner_blocks_mutation(self):
        with self.assertRaisesRegex(RuntimeError, "OwnedRunnerOrEngineStillLive"):
            recovery.apply_plan(self.out, self.plan([{"ProcessId": 5}]))
        self.assertTrue(self.failed.exists())
        self.assertTrue(self.result.exists())

    def test_dispatch_without_receipt_blocks_mutation(self):
        (self.failed / "receipt.json").unlink()
        with self.assertRaisesRegex(RuntimeError, "DispatchWithoutReceipt"):
            recovery.apply_plan(self.out, self.plan())

    def test_waits_for_full_task_list(self):
        self.good.unlink()
        with self.assertRaisesRegex(RuntimeError, "EntireFixedTaskList"):
            recovery.apply_plan(self.out, self.plan())

    def test_recovery_retains_every_cost_and_valid_result(self):
        before = sorted(p.read_bytes() for p in (self.out / "calls").rglob("receipt.json"))
        response = (self.cached / "response.json").read_bytes()
        result = recovery.apply_plan(self.out, self.plan())
        after = sorted(p.read_bytes() for p in (self.out / "calls").rglob("receipt.json"))
        self.assertEqual(before, after)
        self.assertEqual(self.good_bytes, self.good.read_bytes())
        self.assertEqual(response, (self.cached / "response.json").read_bytes())
        self.assertFalse(self.failed.exists())
        self.assertFalse(self.result.exists())
        self.assertFalse((self.task / "engine").exists())
        self.assertEqual((self.task / "retained-recovery/validity-pass-0001/engine/data/h2h.sqlite").read_bytes(), b"preserved-native-evidence")
        self.assertTrue(result["launchRequired"])

    def test_successful_interface_retry_remains_cached(self):
        recovery.save(self.failed / "authorized-interface-retry-1/receipt.json", {"httpStatus": 200, "actualCostUsd": .002})
        plan = self.plan()
        self.assertEqual(plan["targets"], [])
        self.assertEqual(len(plan["blockedTasks"]), 1)
        self.assertTrue(self.failed.exists())

    def test_scoring_error_regrades_existing_candidate(self):
        recovery.save(self.result, {"officialId": "HumanEval/0", "answer": "def f(): return 1", "candidateHow": "submitted", "grade": {"valid": False, "errorType": "GraderTransport"}})
        before = self.result.read_bytes()
        plan = self.plan()
        self.assertEqual(plan["targets"][0]["action"], "regrade_existing_candidate")
        recovery.apply_plan(self.out, plan)
        self.assertEqual(before, self.result.read_bytes())
        self.assertTrue((self.task / "engine").exists())

    def test_auth_fault_requires_diagnosis(self):
        for directory in (self.failed, self.failed / "authorized-interface-retry-1"):
            recovery.save(directory / "receipt.json", {"httpStatus": 401, "fault": "invalid API key"})
        plan = self.plan()
        self.assertEqual(plan["targets"], [])
        self.assertEqual(len(plan["blockedTasks"]), 1)

    def test_unsubmitted_candidate_is_never_regraded(self):
        recovery.save(self.result, {"officialId": "HumanEval/0", "answer": "def f(): return 1", "candidateHow": "verified", "grade": {"valid": False}})
        plan = self.plan()
        self.assertEqual(plan["targets"], [])
        self.assertEqual(plan["blockedTasks"][0]["reason"], "CandidateIsNotNativeSubmittedNeedsDiagnosis")

    def test_move_outside_own_root_is_rejected(self):
        plan = self.plan()
        plan["targets"][0]["failedRequestGroups"] = [str(self.out.parent)]
        with self.assertRaises((ValueError, RuntimeError)):
            recovery.apply_plan(self.out, plan)
        self.assertTrue(self.result.exists())


if __name__ == "__main__":
    unittest.main()
