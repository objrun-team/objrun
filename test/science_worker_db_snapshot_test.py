"""New native F fixtures only. No original SQLite, D copies, API or paid lock."""
from pathlib import Path
import ctypes
import importlib.util
import json
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / 'scripts/benchmark-repair/science-worker-db-snapshot-v1.py'
spec = importlib.util.spec_from_file_location('snapshot_native_fixture', SOURCE)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SnapshotNativeTests(unittest.TestCase):
    def test_real_native_copy_flush_readback_and_source_identity(self):
        source, target = module.create_fixture()
        before = [module.pin(p) for p in module.files(source)]
        result = module.fixture_snapshot(source, target)
        self.assertTrue(result['validated'])
        self.assertTrue(result['allSourceHandlesAcquiredBeforeAnyCopy'])
        self.assertEqual(len(result['rawCopies']), 12)
        self.assertEqual(len(result['workingCopies']), 12)
        self.assertTrue(all(p['FlushFileBuffersReturned'] for p in result['rawCopies'] + result['workingCopies']))
        self.assertEqual(before, [module.pin(p) for p in module.files(source)])
        self.assertEqual(result['sourceBefore'], result['sourceAfter'])
        self.assertTrue(result['sourceHandlesClosed'])
        self.assertEqual(module._ACTIVE_HANDLES, set())
        self.assertFalse(result['originalSqliteOpened'])
        self.assertFalse(result['proxyPortEstablished'])
        self.assertLessEqual(result['copiedLogicalBytes'], module.LIMIT)
        module.save_new(source.parent / 'control-result.json', {'sourcePin': module.pin(SOURCE), 'result': result,
            'modelCalls': 0, 'DProductionCopies': 0, 'originalSqliteOpened': False, 'onlyFWrites': True})

    def test_all_source_handles_really_deny_existing_write_and_delete(self):
        source, target = module.create_fixture()
        observations = []
        def hook(stage, handles, target):
            if stage != 'all_handles':
                return
            self.assertEqual(len(handles), 12)
            path = module.files(source)[0]
            h = module.K.CreateFileW(str(path), module.WRITE, module.SHARE_READ, None,
                                    module.EXISTING, module.FLAGS, None)
            error = ctypes.get_last_error()
            self.assertIn(h, [None, module.INVALID])
            self.assertEqual(error, 32)
            delete = module.K.DeleteFileW
            delete.argtypes = [ctypes.c_wchar_p]
            delete.restype = ctypes.c_int
            ok = delete(str(path))
            self.assertEqual(ok, 0)
            self.assertEqual(ctypes.get_last_error(), 32)
            observations.append({'writeWinError': error, 'deleteWinError': ctypes.get_last_error()})
        result = module.fixture_snapshot(source, target, hook=hook)
        self.assertTrue(result['validated'])
        self.assertEqual(len(observations), 1)
        self.assertEqual(module._ACTIVE_HANDLES, set())

    def test_failure_preserves_owned_partial_and_closes_handles_without_source_change(self):
        source, target = module.create_fixture()
        before = [module.pin(p) for p in module.files(source)]
        count = 0
        def hook(stage, handles, path):
            nonlocal count
            if stage == 'copied_file':
                count += 1
                if count == 3:
                    raise RuntimeError('bounded_fixture_copy_fault')
        result = module.fixture_snapshot(source, target, hook=hook)
        self.assertFalse(result['validated'])
        self.assertTrue(result['partialOwnedTargetPreserved'])
        self.assertEqual(len(result['rawCopies']), 3)
        self.assertEqual(len(result['workingCopies']), 0)
        self.assertEqual(before, [module.pin(p) for p in module.files(source)])
        self.assertTrue(result['originalBytesUnchangedAfterFailure'])
        self.assertTrue(result['sourceHandlesClosed'])
        self.assertEqual(module._ACTIVE_HANDLES, set())

    def test_wrong_scope_existing_target_and_real_junction_reject_before_copy(self):
        source, target = module.create_fixture()
        with self.assertRaisesRegex(RuntimeError, 'fixture_root_not_self_created'):
            module.fixture_snapshot(ROOT, target)
        target.mkdir()
        with self.assertRaisesRegex(RuntimeError, 'fixture_root_not_self_created'):
            module.fixture_snapshot(source, target)
        source, target = module.create_fixture()
        parent = source / 'worker-0'
        held = source / 'held-worker-0'
        parent.rename(held)
        proc = subprocess.run([str(module.PS), '-NoProfile', '-NonInteractive', '-Command',
            "New-Item -ItemType Junction -Path '" + str(parent) + "' -Target '" + str(held) + "' | Out-Null"],
            stdin=subprocess.DEVNULL, capture_output=True, timeout=10, creationflags=subprocess.CREATE_NO_WINDOW)
        self.assertEqual(proc.returncode, 0)
        with self.assertRaisesRegex(RuntimeError, 'reparse'):
            module.fixture_snapshot(source, target)
        self.assertFalse(target.exists())
        self.assertEqual(module._ACTIVE_HANDLES, set())


if __name__ == '__main__':
    unittest.main()
