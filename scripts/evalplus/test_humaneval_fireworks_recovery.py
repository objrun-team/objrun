import importlib.util
import unittest
from pathlib import Path


def load(name, file):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(file))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


recovery = load("recovery_v2", "prepare-humaneval-objrun-fireworks-recovery.py")
base_tests = load("recovery_base_tests", "test_humaneval_objrun_recovery.py")
base_tests.recovery = recovery


class RecoveryV2Tests(base_tests.RecoveryTests):
    def test_http200_network_lost_recovery_preserves_cost(self):
        recovery.save(self.failed / "authorized-interface-retry-1/receipt.json", {"httpStatus": 200, "fault": "Network connection lost.", "unknownCost": True, "actualCostUsd": None, "upperBoundUsd": .02})
        before = sorted(p.read_bytes() for p in (self.out / "calls").rglob("receipt.json"))
        plan = self.plan()
        self.assertEqual(len(plan["targets"]), 1)
        self.assertEqual(plan["blockedTasks"], [])
        recovery.apply_plan(self.out, plan)
        self.assertEqual(before, sorted(p.read_bytes() for p in (self.out / "calls").rglob("receipt.json")))

    def test_reused_non_bun_pid_does_not_block(self):
        self.assertFalse(recovery.process_is_owned({"ProcessId": 7, "Name": "conhost.exe", "CreationUtc": "2026-10-12T11:37:00+00:00", "CommandLine": "conhost.exe 0x4"}, [{"pid": 7, "atUtc": "2026-10-12T11:02:00Z"}]))

    def test_reused_bun_pid_is_identified_by_birth(self):
        row = {"ProcessId": 7, "Name": "bun.exe", "CreationUtc": "2026-10-12T11:37:00+00:00", "CommandLine": str(recovery.ROOT / "app/src/main.ts")}
        self.assertFalse(recovery.process_is_owned(row, [{"pid": 7, "atUtc": "2026-10-12T11:02:00Z"}]))

    def test_live_engine_is_still_blocked(self):
        row = {"ProcessId": 7, "Name": "bun.exe", "CreationUtc": "2026-10-12T11:01:59.5+00:00", "CommandLine": str(recovery.ROOT / "app/src/main.ts")}
        self.assertTrue(recovery.process_is_owned(row, [{"pid": 7, "atUtc": "2026-10-12T11:02:00Z"}]))

    def test_any_live_own_runner_is_blocked(self):
        self.assertTrue(recovery.process_is_owned({"ProcessId": 8, "Name": "bun.exe", "CommandLine": "bun run scripts/evalplus/run-humaneval-objrun-fireworks.ts humaneval full recovery"}, []))

    def test_ambiguous_bun_identity_is_blocked(self):
        self.assertTrue(recovery.process_is_owned({"ProcessId": 7, "Name": "bun.exe", "CreationUtc": "2026-10-12T11:37:00+00:00", "CommandLine": None}, [{"pid": 7, "atUtc": "2026-10-12T11:02:00Z"}]))


if __name__ == "__main__":
    unittest.main()
