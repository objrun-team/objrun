"""Real local IO and fixed official leantar toy controls; no E writes or GET.

Every fixture remains below the owned F .scratch directory for review. These
are archive transport controls, not mathematical candidates or grades.
"""
import errno
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tarfile
import unittest
from unittest.mock import patch
import uuid

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / 'scripts/repair-2026-10-08/minif2f_fast_unpack.py'
spec = importlib.util.spec_from_file_location('fast', SOURCE)
fast = importlib.util.module_from_spec(spec); spec.loader.exec_module(fast)
FIXTURES = PROJECT / '.scratch' / ('minif-fast-fixture-' + uuid.uuid4().hex[:12])
FIXTURES.mkdir()
EVIDENCE = {'candidate_run': False, 'llm_called': False, 'public_get': False, 'e_write': False,
            'fixture_root': str(FIXTURES), 'official_binary_sha256': fast.LEANTAR_SHA, 'controls': []}


def archive(version=b'LTR2', trace='.lake/build/lib/Fixture.trace', others=('.lake/build/lib/Fixture.hash',)):
    value = version + struct.pack('<Q', 37) + trace.encode() + b'\0'
    if version == b'LTR2': value += b'\3' + struct.pack('<Q', 37)
    for path in others: value += path.encode() + b'\0\2' + struct.pack('<Q', 71)
    return value


def put_blob(root, data, name='0000000000000001.ltar'):
    directory = root / 'downloads/mathlib-cache'; directory.mkdir(parents=True, exist_ok=True)
    path = directory / name; path.write_bytes(data)
    return {'ltar': name, 'url': fast.AZURE + name, 'bytes': len(data), 'sha256': fast.sha(path)}


def plain_root(name):
    root = FIXTURES / (name + '-' + uuid.uuid4().hex[:8]); root.mkdir()
    (root / 'audit').mkdir()
    return root


def progress(root, rows):
    fast.durable_json(root / 'audit/cache-fast-progress.json', {
        'protocol': fast.PROTOCOL, 'validated': True, 'processed_prefix': len(rows),
        'receipts_sha256': fast.sha(root / 'audit/cache-unpacked.jsonl'),
        'commits_sha256': fast.sha(root / 'audit/cache-fast-commits.jsonl')})


class ProtocolTests(unittest.TestCase):
    def test_actual_ltar_v1_v2_layout_and_comments(self):
        for magic in (b'LTAR', b'LTR2'):
            self.assertEqual(fast.ltar_paths(archive(magic) + b'\0benign comment\0'),
                             ['.lake/build/lib/Fixture.trace', '.lake/build/lib/Fixture.hash'])

    def test_truncated_paths_counts_tags_and_aliases_fail_closed(self):
        bad = [archive()[:-1], archive(trace='../source.lean'), archive(trace='/tmp/source.lean'),
               archive(trace='.lake/packages/aesop/Aesop.lean'), archive(trace='.lake/build/lib/A:B'),
               archive(trace='.lake/build/lib/A\nB'), archive(others=tuple('.lake/build/lib/F' + str(i) for i in range(8))),
               archive(trace='.lake/build/lib/F', others=('.lake/build/lib/f',)),
               b'LTAR' + struct.pack('<Q', 37) + b'bad-path-without-null']
        for data in bad:
            with self.subTest(sha=hashlib.sha256(data).hexdigest()):
                with self.assertRaises(fast.InfraError): fast.ltar_paths(data)
        bad_tag = archive()[:12] + b'.lake/build/F\0\4' + struct.pack('<Q', 1)
        with self.assertRaises(fast.InfraError): fast.ltar_paths(bad_tag)

    def test_real_fsync_failure_keeps_original_and_partial_receipt(self):
        root = plain_root('fsync-fault'); record = put_blob(root, b'owned synthetic input')
        receipt, commits = root / 'audit/cache-unpacked.jsonl', root / 'audit/cache-fast-commits.jsonl'
        with patch.object(fast.os, 'fsync', side_effect=OSError(errno.EIO, 'real IO fault injection at fsync')):
            with self.assertRaises(OSError): fast.commit_outputs(root, record, [], receipt, commits)
        self.assertEqual(fast.sha(root / 'downloads/mathlib-cache' / record['ltar']), record['sha256'])
        self.assertTrue(receipt.exists()); self.assertFalse(commits.exists())
        EVIDENCE['controls'].append({'label': 'fsync_error_preserves_exact_original', 'passed': True,
                                    'fixture': str(root), 'receipt_partial_retained': True})

    def test_real_receipt_prefix_and_modified_output_rejection(self):
        root = plain_root('prefix'); record = put_blob(root, b'owned synthetic input')
        target = root / 'mathlib4/.lake/build/lib/Fixture.hash'; target.parent.mkdir(parents=True); target.write_bytes(b'71')
        with target.open('r+b') as stream: stream.flush(); os.fsync(stream.fileno())
        files = [{'path': '.lake/build/lib/Fixture.hash', 'bytes': 2, 'sha256': fast.sha(target)}]
        receipt, commits = root / 'audit/cache-unpacked.jsonl', root / 'audit/cache-fast-commits.jsonl'
        native = os.fsync; calls = []
        def observed(fd):
            native(fd); calls.append('fsync_returned')
        with patch.object(fast.os, 'fsync', side_effect=observed): fast.commit_outputs(root, record, files, receipt, commits)
        self.assertEqual(calls, ['fsync_returned', 'fsync_returned'])
        self.assertFalse((root / 'downloads/mathlib-cache' / record['ltar']).exists())
        progress(root, [record])
        prior, _ = fast.verified_prefix(root, [record]); self.assertEqual(len(prior), 1)
        target.write_bytes(b'72')
        with self.assertRaises(fast.InfraError): fast.verified_prefix(root, [record])
        EVIDENCE['controls'].append({'label': 'durable_prefix_then_changed_actual_output_rejected', 'passed': True, 'fixture': str(root)})

    @unittest.skipUnless(os.name == 'nt', 'Actual Windows share-deny test')
    def test_actual_share_deny_acquisition_guard_preserves_bytes(self):
        root = plain_root('share-deny'); path = root / 'audit/original-acquisition.lock'
        value = {'protocol': 'public-cache-acquisition-v1', 'run_id': fast.RUN_ID, 'held': False, 'outcome': 'complete'}
        path.write_bytes(fast.canonical(value) + b'\n'); before = fast.sha(path)
        with fast.AcquisitionGuard(path):
            child = subprocess.run([sys.executable, '-B', '-c',
                'import sys; open(sys.argv[1], "r+b").close()', str(path)], capture_output=True,
                creationflags=subprocess.CREATE_NO_WINDOW, timeout=10)
            self.assertNotEqual(child.returncode, 0)
            self.assertIn(b'PermissionError', child.stderr)
        self.assertEqual(fast.sha(path), before)
        EVIDENCE['controls'].append({'label': 'readonly_share_deny_blocks_actual_child_writer', 'passed': True, 'fixture': str(root)})


class OfficialDockerTests(unittest.TestCase):
    def setUp(self):
        self.root = plain_root('official')
        tools = self.root / 'tools'; tools.mkdir()
        public = PROJECT / '.phase1-data/minif2f-restoration-public'
        lock = json.loads((public / 'public-lock.json').read_bytes())
        self.assertEqual(fast.sha(public / 'public-lock.json'), fast.LOCK_SHA)
        tar = public / 'leantar-linux.tar.gz'
        entry = next(e for e in lock['entries'] if e['file'] == tar.name)
        self.assertEqual(fast.sha(tar), entry['sha256'])
        with tarfile.open(tar, 'r:gz') as incoming:
            members = [m for m in incoming.getmembers() if m.isfile() and Path(m.name).name == 'leantar']
            self.assertEqual(len(members), 1)
            data = incoming.extractfile(members[0]).read()
        (tools / 'leantar').write_bytes(data); (tools / 'leantar').chmod(0o755)
        self.assertEqual(fast.sha(tools / 'leantar'), fast.LEANTAR_SHA)
        (self.root / 'unchanged-source.txt').write_bytes(b'fixture source must remain unchanged')
        self.source_sha = fast.sha(self.root / 'unchanged-source.txt')
        self.worker = fast.DockerWorker(self.root, PROJECT)
        self.worker.__enter__()
        self.control = {'container_id': self.worker.cid, 'image_id': fast.IMAGE, 'fixture': str(self.root),
                        'candidate_run': False, 'input_kind': 'synthetic LTAR; no mathematical proof'}

    def tearDown(self):
        self.worker.close()
        if getattr(self, 'discard_empty_stage', False):
            self.control['known_empty_stage_directories_removed'] = self.worker.discard_empty_stage()
            self.assertFalse(self.worker.stage.exists())
        self.assertEqual(fast.sha(self.root / 'unchanged-source.txt'), self.source_sha)
        self.assertEqual(fast.sha(self.root / 'tools/leantar'), fast.LEANTAR_SHA)
        self.control['cleanup_closed'] = True
        EVIDENCE['controls'].append(self.control)

    def docker(self, argv, cwd=None):
        command = ['docker', 'exec']
        if cwd: command += ['--workdir', cwd]
        return subprocess.run(command + [self.worker.cid] + argv, capture_output=True, text=True, timeout=30)

    def test_real_official_fresh_output_materialization_and_durable_delete(self):
        record = put_blob(self.root, archive())
        result = self.worker.call(record)
        self.assertTrue(result['fresh_staged_outputs']); self.assertEqual(len(result['files']), 2)
        self.worker.materialize(record, result['files'])
        self.assertEqual(fast.staged_files(self.worker.stage / 'mathlib4'), [])
        for file in result['files']:
            self.assertEqual(fast.sha(self.root / 'mathlib4' / file['path']), file['sha256'])
        receipt, commits = self.root / 'audit/cache-unpacked.jsonl', self.root / 'audit/cache-fast-commits.jsonl'
        fast.commit_outputs(self.root, record, result['files'], receipt, commits)
        self.assertFalse((self.root / 'downloads/mathlib-cache' / record['ltar']).exists())
        self.control.update(label='actual_official_fresh_two_outputs_fsync_materialize_receipt_delete', passed=True, result=result)
        self.discard_empty_stage = True

    def test_fresh_partial_is_never_reused_or_pruned(self):
        record = put_blob(self.root, archive())
        first = self.worker.call(record)
        paths = [self.worker.stage / 'mathlib4' / f['path'] for f in first['files']]
        before = [fast.sha(p) for p in paths]
        with self.assertRaises(fast.InfraError) as caught: self.worker.call(record)
        self.assertEqual(caught.exception.kind, 'stage_not_fresh')
        self.assertEqual([fast.sha(p) for p in paths], before)
        self.assertTrue((self.root / 'downloads/mathlib-cache' / record['ltar']).exists())
        self.control.update(label='actual_staged_partial_refuses_reuse_and_is_preserved', passed=True, green_error=caught.exception.kind)

    def test_actual_old_output_truncated_archive_red_then_green(self):
        trace = self.root / 'mathlib4/.lake/build/lib/Fixture.trace'; trace.parent.mkdir(parents=True); trace.write_bytes(b'37')
        old = self.root / 'mathlib4/.lake/build/lib/Fixture.hash'; old.write_bytes(b'legacy output')
        old_sha = fast.sha(old)
        corrupted = b'LTAR' + struct.pack('<Q', 37) + b'.lake/build/lib/Fixture.trace\0.lake/build/lib/Fixture.hash\0\0' + struct.pack('<Q', 50) + b'short'
        record = put_blob(self.root, corrupted)
        blob = '/cache/downloads/mathlib-cache/' + record['ltar']
        # This is the actual legacy no-force trace shortcut, not a substitute binary.
        red = self.docker(['/cache/tools/leantar', '--jobs', '1', '-x', blob], '/cache/mathlib4')
        self.control.update(legacy_exit=red.returncode, legacy_stdout=red.stdout, legacy_stderr=red.stderr)
        self.assertEqual(red.returncode, 0); self.assertEqual(fast.sha(old), old_sha)
        # Real forced corrupted input also demonstrates the documented exit-0 trap.
        eof = self.docker(['/cache/tools/leantar', '--jobs', '1', '-f', '-x', blob], '/stage/mathlib4')
        self.assertEqual(eof.returncode, 0); self.assertIn('removing corrupted file', eof.stderr)
        self.assertEqual(fast.staged_files(self.worker.stage / 'mathlib4'), [])
        self.assertEqual(fast.sha(self.root / 'downloads/mathlib-cache' / record['ltar']), record['sha256'])
        with self.assertRaises(fast.InfraError) as caught: self.worker.call(record)
        self.assertEqual(caught.exception.kind, 'archive_truncated')
        self.assertEqual(fast.sha(old), old_sha)
        self.control.update(label='legacy_old_output_eof_exit_zero_red_fresh_parser_invalid_green', passed=True,
                            legacy_exit=red.returncode, forced_eof_exit=eof.returncode, forced_eof_stderr=eof.stderr,
                            green_error=caught.exception.kind, original_blob_preserved=True)

    def test_actual_official_rlimit_preserves_partial_no_receipt(self):
        record = put_blob(self.root, archive(others=()))
        code = ('import importlib.util,json; s=importlib.util.spec_from_file_location("f","/plan/fast.py"); '
                'm=importlib.util.module_from_spec(s);s.loader.exec_module(m); '
                'm.bounded_official("/cache/tools/leantar","/cache/downloads/mathlib-cache/' + record['ltar'] + '","/stage/mathlib4",file_limit=8,wall=10)')
        result = self.docker(['python', '-B', '-c', code])
        self.control.update(rlimit_probe_exit=result.returncode, rlimit_probe_stdout=result.stdout, rlimit_probe_stderr=result.stderr)
        self.assertNotEqual(result.returncode, 0)
        path = self.worker.stage / 'mathlib4/.lake/build/lib/Fixture.trace'
        self.assertTrue(path.exists()); self.assertLessEqual(path.stat().st_size, 8)
        self.assertTrue((self.root / 'downloads/mathlib-cache' / record['ltar']).exists())
        self.assertFalse((self.root / 'audit/cache-unpacked.jsonl').exists())
        self.control.update(label='actual_official_fsize8_partial_invalid', passed=True, partial_bytes=path.stat().st_size,
                            original_blob_preserved=True, stderr=result.stderr)

    def test_structurally_complete_truncated_zstd_cannot_use_old_output(self):
        trace = self.root / 'mathlib4/.lake/build/lib/Fixture.trace'; trace.parent.mkdir(parents=True); trace.write_bytes(b'37')
        old = self.root / 'mathlib4/.lake/build/lib/Fixture.hash'; old.write_bytes(b'benign toy data ' * 200)
        old_sha = fast.sha(old)
        packed = self.worker.stage / 'mathlib4/.lake/build/packed.ltar'
        result = self.docker(['/cache/tools/leantar', '-C', '/cache/mathlib4',
            '/stage/mathlib4/.lake/build/packed.ltar', '.lake/build/lib/Fixture.trace', '.lake/build/lib/Fixture.hash'])
        self.assertEqual(result.returncode, 0, result.stderr)
        original = packed.read_bytes()
        saved = self.root / 'original-synthetic-packed.ltar'; saved.write_bytes(original)
        packed.unlink()  # Exact newly-created F toy, original bytes preserved above.
        marker = b'.lake/build/lib/Fixture.hash\0'; kind_at = original.index(marker) + len(marker)
        self.assertEqual(original[kind_at], 0)
        size_at = kind_at + 1; size = struct.unpack_from('<Q', original, size_at)[0]
        self.assertEqual(size_at + 8 + size, len(original)); self.assertGreater(size, 1)
        corrupted = original[:size_at] + struct.pack('<Q', size - 1) + original[size_at + 8:-1]
        self.assertEqual(len(fast.ltar_paths(corrupted)), 2)  # Header/path/payload lengths are structurally complete.
        record = put_blob(self.root, corrupted)
        blob = '/cache/downloads/mathlib-cache/' + record['ltar']
        legacy = self.docker(['/cache/tools/leantar', '--jobs', '1', '-x', blob], '/cache/mathlib4')
        self.assertEqual(legacy.returncode, 0); self.assertEqual(fast.sha(old), old_sha)
        direct = self.docker(['/cache/tools/leantar', '--jobs', '1', '-f', '-x', blob], '/stage/mathlib4')
        self.assertEqual(direct.returncode, 0); self.assertIn('removing corrupted file', direct.stderr)
        self.assertEqual(fast.staged_files(self.worker.stage / 'mathlib4'), [])
        with self.assertRaises(fast.InfraError) as caught: self.worker.call(record)
        self.assertEqual(caught.exception.kind, 'output_missing')
        self.assertEqual(fast.sha(old), old_sha)
        self.assertEqual(fast.sha(self.root / 'downloads/mathlib-cache' / record['ltar']), record['sha256'])
        self.control.update(label='actual_zstd_eof_exit_zero_fresh_output_missing_invalid', passed=True,
            archive_structural_paths_valid=True, legacy_exit=legacy.returncode, forced_eof_exit=direct.returncode,
            forced_eof_stderr=direct.stderr, green_error=caught.exception.kind, original_blob_preserved=True)


if __name__ == '__main__':
    suite = unittest.defaultTestLoader.loadTestsFromModule(sys.modules[__name__])
    result = unittest.TextTestRunner(verbosity=2).run(suite)
    EVIDENCE.update(tests_run=result.testsRun, failures=len(result.failures), errors=len(result.errors),
                    skipped=len(result.skipped), validated=result.wasSuccessful(), source_sha256=fast.sha(SOURCE))
    out = PROJECT / 'docs/repair-2026-10-08/minif2f-fast-unpack-fixture.json'
    out.write_text(json.dumps(EVIDENCE, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'validated': EVIDENCE['validated'], 'tests': result.testsRun, 'report': str(out), 'e_write': False}))
    sys.exit(0 if result.wasSuccessful() else 1)
