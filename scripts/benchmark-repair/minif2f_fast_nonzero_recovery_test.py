"""Necessary F-only controls; no E, daemon, decoder, provider or candidate."""
import copy
import importlib.util
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch
import uuid

PATH = Path(__file__).with_name('minif2f_fast_nonzero_recovery.py')
spec = importlib.util.spec_from_file_location('nonzero_recovery_control', PATH)
r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)
FROOT = r.REPO / '.scratch/minif2f-nonzero-recovery-controls' / uuid.uuid4().hex
FROOT.mkdir(parents=True, exist_ok=False)


def encoded(value): return r.canonical(value) + b'\n'


class Controls(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.records, cls.rows, cls.receipts, cls.commits = [], [], [], []
        end = 0
        for i in range(r.TOTAL):
            name = r.LTAR if i == r.TARGET - 1 else f'{i:016x}.ltar'
            source = {'ltar': name, 'sha256': 'a' * 64, 'bytes': 1,
                      'url': 'https://lakecache.blob.core.windows.net/mathlib4/f/' + name}
            cls.records.append(source)
            if i >= r.TARGET: continue
            files = [{'path': f'.lake/build/lib/Fixture/{i}.trace', 'bytes': 1, 'sha256': 'b' * 64}]
            if i == r.TARGET - 1:
                files = [{'path': f'.lake/build/lib/Fixture/Pending/{j}.trace', 'bytes': 1, 'sha256': 'c' * 64} for j in range(7)]
            row = {'protocol': r.FAST, 'ltar': name, 'source_sha256': source['sha256'],
                   'source_bytes': 1, 'source_url': source['url'], 'files': files, 'outputs_fsynced': True}
            raw = encoded(row); cls.rows.append(row); cls.receipts.append(raw); end += len(raw)
            if i < r.COMMITTED:
                cls.commits.append(encoded({'protocol': r.FAST, 'ltar': name,
                    'receipt_end': end, 'receipt_line_sha256': r.digest(raw), 'receipt_fsync_returned': True}))
        cls.item = {'protocol': r.FAST, 'ltar': r.LTAR, 'state': 'materialized_and_fsynced', 'files': cls.rows[-1]['files']}
        cls.rb, cls.cb = b''.join(cls.receipts), b''.join(cls.commits)
        cls.bs = r.digest(b''.join(cls.receipts[:r.BASE])); cls.bc = r.digest(b''.join(cls.commits[:r.BASE]))

    def check(self, receipts=None, commits=None, item=None):
        return r.verify_boundary(receipts or self.rb, commits or self.cb, self.records,
                                 self.bs, self.bc, item or self.item)

    def test_01_exact_20plus1_boundary(self):
        rows, cs = self.check()
        self.assertEqual((len(rows), len(cs), len(self.records)), (3927, 3926, 5826))
        self.assertEqual(len(rows[-1][1]['files']), 7)

    def test_02_tail_and_base_corruption_rejected(self):
        with self.assertRaisesRegex(r.Fault, 'complete final'): self.check(receipts=self.rb[:-1])
        altered = list(self.receipts); first = copy.deepcopy(self.rows[0]); first['source_bytes'] = 2; altered[0] = encoded(first)
        with self.assertRaisesRegex(r.Fault, '3906 raw'): self.check(receipts=b''.join(altered))

    def test_03_commit_hash_and_intent_rejected(self):
        cs = list(self.commits); c = json.loads(cs[-1]); c['receipt_line_sha256'] = '0' * 64; cs[-1] = encoded(c)
        with self.assertRaisesRegex(r.Fault, 'Commit hash'): self.check(commits=b''.join(cs))
        item = copy.deepcopy(self.item); item['files'][0]['sha256'] = '0' * 64
        with self.assertRaisesRegex(r.Fault, 'materialization intent'): self.check(item=item)

    def test_04_actor_present_and_wrong_cid_rejected(self):
        ids = [{'pid': 109444, 'present': False}, {'pid': 124128, 'present': False}]
        r.verify_actor_observation(ids, {'requested_cid': r.CID, 'absent': True})
        ids[1]['present'] = True
        with self.assertRaisesRegex(r.Fault, 'still present'): r.verify_actor_observation(ids, {'requested_cid': r.CID, 'absent': True})
        ids[1]['present'] = False
        with self.assertRaisesRegex(r.Fault, 'Exact historical'): r.verify_actor_observation(ids, {'requested_cid': '0' * 64, 'absent': True})
        with self.assertRaisesRegex(r.Fault, 'Exact historical'): r.verify_actor_observation(ids, {'requested_cid': r.CID, 'absent': False})

    def test_05_actual_source_drift_rejected(self):
        p = FROOT / 'controlled-source.txt'; p.write_bytes(b'one'); expected = r.pin(p)
        r.verify_pins([expected]); p.write_bytes(b'two')
        with self.assertRaisesRegex(r.Fault, 'identity changed'): r.verify_pins([expected])

    def leaf(self, suffix):
        home = FROOT / suffix; home.mkdir(); outputs = home / 'mathlib4'; outputs.mkdir()
        files = []
        for i in range(7):
            path = f'.lake/build/lib/Fixture/{i}.trace'; data = f'fixture-{i}'.encode()
            dest = outputs / path; dest.parent.mkdir(parents=True, exist_ok=True); dest.write_bytes(data)
            files.append({'path': path, 'bytes': len(data), 'sha256': r.digest(data)})
        blob = home / r.LTAR; blob.write_bytes(b'fixture compressed bytes, not LTAR')
        row = {'protocol': r.FAST, 'ltar': r.LTAR, 'files': files, 'outputs_fsynced': True,
               'source_bytes': blob.stat().st_size, 'source_sha256': r.sha(blob),
               'source_url': 'https://lakecache.blob.core.windows.net/mathlib4/f/' + r.LTAR}
        receipt = home / 'receipts.jsonl'; receipt.write_bytes(encoded(row))
        commits = home / 'commits.jsonl'; commits.write_bytes(b'')
        return home, outputs, blob, row, receipt, commits

    def close_leaf(self, case):
        home, outputs, blob, row, receipt, commits = case
        return r.close_pending(receipt, commits, blob, outputs, row, r.sha(receipt), r.sha(commits),
                               receipt.read_bytes(), 'f' * 32, home)

    def test_06_actual_native_fsync_then_one_delete(self):
        case = self.leaf('native-success'); before = case[4].read_bytes()
        result = self.close_leaf(case)
        self.assertFalse(case[2].exists()); self.assertEqual(case[4].read_bytes(), before)
        c = json.loads(case[5].read_bytes()); self.assertTrue(c['receipt_fsync_returned'])
        self.assertEqual(c['recovery_protocol'], r.PROTOCOL)
        self.assertEqual(c['receipt_line_sha256'], r.digest(before))
        self.assertEqual(c['receipt_end'], len(before))
        self.assertTrue(Path(result['commit_witness_pin']['path']).exists())

    def test_07_actual_output_mismatch_no_commit_or_delete(self):
        case = self.leaf('native-mismatch')
        (case[1] / case[3]['files'][0]['path']).write_bytes(b'corrupted')
        with self.assertRaisesRegex(r.Fault, 'Actual pending output'): self.close_leaf(case)
        self.assertTrue(case[2].exists()); self.assertEqual(case[5].read_bytes(), b'')

    def test_08_actual_commit_fsync_failure_preserves_input(self):
        case = self.leaf('native-append-fault'); real = os.fsync; calls = 0
        def failed(fd):
            nonlocal calls
            calls += 1
            if calls == 11: raise OSError('injected commit fsync failure')
            return real(fd)
        with patch.object(r.os, 'fsync', side_effect=failed):
            with self.assertRaisesRegex(OSError, 'commit fsync'): self.close_leaf(case)
        self.assertTrue(case[2].exists()); self.assertEqual(calls, 11)
        self.assertFalse((case[0] / 'pending-commit-witness.json').exists())
        # A written-but-uncommitted line may persist; do not discard or retry it.
        self.assertGreater(case[5].stat().st_size, 0)

    @unittest.skipUnless(os.name == 'nt', 'Requires real Windows native handles')
    def test_09_actual_native_exclusion_and_stage_identity(self):
        p = FROOT / 'original-marker.json'; raw = b'{"held":false}\n'; p.write_bytes(raw)
        with r.WinFile(p) as first:
            self.assertEqual(first.raw(), raw)
            with self.assertRaises(r.Fault):
                with r.WinFile(p): pass
        self.assertEqual(p.read_bytes(), raw)
        fresh = FROOT / 'fresh-owned.lock'
        with r.WinFile(fresh, fresh=True) as own: own.write({'held': False, 'nonce': 'fixtureOnly'})
        with r.WinFile(fresh) as reopened: self.assertFalse(json.loads(reopened.raw())['held'])
        with self.assertRaises(r.Fault):
            with r.WinFile(fresh, fresh=True): pass
        stage = FROOT / 'fresh-stage'; stage.mkdir()
        for path in r.BUILD_ROOTS: (stage / 'mathlib4' / path).mkdir(parents=True, exist_ok=True)
        ids = r.stage_ids(stage); self.assertEqual(len(ids), 29)
        dest = FROOT / 'stage-history'; stage.rename(dest)
        self.assertEqual(r.stage_ids(dest), ids)

    def test_10_unsafe_paths_and_prepared_authorization_rejected(self):
        for p in ['../escape', '.lake/build/../../escape', '.lake/build/a:b', '.lake/build//a', '.lake/build/./a', 'foreign/a']:
            with self.assertRaises(r.Fault): r.output_path(p)
        with self.assertRaisesRegex(r.Fault, 'Prepared F'): r.production({'production_authorization': None})

    def test_11_missing_or_false_final_witness_rejected(self):
        b, p = {'fixtureOnly': True, 'sha256': 'a' * 64}, {'fixtureOnly': True, 'sha256': 'b' * 64}
        c = {'protocol': r.PROTOCOL, 'nonce': 'fixtureOnly', 'baseline_pin': b, 'recovery_receipt_pin': p,
             'source_sha256': r.sha(PATH), 'baseline_fsync_returned': True, 'all_native_exclusion_handles_closed': True}
        r.verify_baseline_commit(c, b, p, 'fixtureOnly', r.sha(PATH))
        with self.assertRaisesRegex(r.Fault, 'Mandatory actual'): r.verify_baseline_commit(None, b, p, 'fixtureOnly', r.sha(PATH))
        bad = dict(c); bad['baseline_fsync_returned'] = False
        with self.assertRaisesRegex(r.Fault, 'Mandatory actual'): r.verify_baseline_commit(bad, b, p, 'fixtureOnly', r.sha(PATH))
        bad = dict(c); bad['baseline_pin'] = p
        with self.assertRaisesRegex(r.Fault, 'Mandatory actual'): r.verify_baseline_commit(bad, b, p, 'fixtureOnly', r.sha(PATH))


if __name__ == '__main__':
    result = unittest.TextTestRunner(verbosity=2).run(unittest.defaultTestLoader.loadTestsFromTestCase(Controls))
    total = sum(p.stat().st_size for p in FROOT.rglob('*') if p.is_file())
    certificate = {'protocol': r.PROTOCOL + '-offline-controls', 'fixtureOnly': True,
        'sourceSha256': r.sha(PATH), 'testSourceSha256': r.sha(__file__), 'tests': result.testsRun,
        'failures': len(result.failures), 'errors': len(result.errors), 'skipped': len(result.skipped),
        'fixturePath': str(FROOT), 'fixtureBytes': total, 'productionCount': r.TOTAL,
        'actualRootRecovered': False, 'officialDecoderExecuted': False, 'modelCalls': 0, 'EWrites': 0}
    print(json.dumps(certificate))
    raise SystemExit(0 if result.wasSuccessful() else 1)
