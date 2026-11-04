"""New F-only copy/selection controls; no original evidence/SQLite/network/Docker."""
import importlib.util
from pathlib import Path
import os
import unittest
from unittest.mock import patch
import uuid

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'scripts/benchmark-repair/package-tb-real-pilot-v1.py'
spec=importlib.util.spec_from_file_location('tb_public_package_fixture',SOURCE)
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

class PackageControls(unittest.TestCase):
    def fixture(self):
        top=ROOT/'.scratch/tb-real-package-controls'/uuid.uuid4().hex
        p.new_dirs(top)
        source=top/'source-public.txt'
        with source.open('xb') as f:
            f.write(b'new F own public fixture\n'*1024);f.flush();os.fsync(f.fileno())
        return source,top/'copy-public.txt'

    def test_single_benchmark_source_selection_and_private_paths_reject(self):
        self.assertTrue(p.selected('examples/benchmark/terminal-bench/stand.py'))
        self.assertTrue(p.selected('app/src/engine/loop.ts'))
        self.assertFalse(p.selected('examples/benchmark/skillsbench/stand.py'))
        self.assertFalse(p.selected('scripts/benchmark-repair/skb-jpg-journal-campaign.ts'))
        for value in ('../escape','/absolute','worker-U/config.yaml','worker-U/data/h2h.sqlite','artifacts/.env'):
            with self.subTest(value=value):
                with self.assertRaises(RuntimeError):p.rel(value)

    def test_actual_new_regular_copy_fsync_readback_original_unchanged(self):
        source,target=self.fixture();before=p.pin(source)
        copied=p.copy_file(source,target,before)
        self.assertEqual(copied['sha256'],before['sha256'])
        self.assertEqual(copied['bytes'],before['bytes'])
        self.assertEqual(p.pin(source),before)
        with self.assertRaises(FileExistsError):p.copy_file(source,target,before)

    def test_actual_invalid_fsync_fault_leaves_owned_partial_and_original_unchanged(self):
        source,target=self.fixture();before=p.pin(source);native_fsync=os.fsync
        def bad_fsync(fd):
            invalid=os.dup(fd)
            os.close(invalid)
            return native_fsync(invalid)
        with patch.object(p.os,'fsync',bad_fsync):
            with self.assertRaises(OSError):p.copy_file(source,target,before)
        self.assertTrue(target.is_file())
        self.assertEqual(p.pin(source),before)
        self.assertTrue(p.SUSPICIOUS.search(b'Bearer '+b'x'*32))

if __name__=='__main__':unittest.main()
