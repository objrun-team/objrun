"""Exercise the production Bridge cache with real mutable files and snapshots.

Only the external solver/grader are test doubles. This does not certify Docker
isolation or the official verifier; the separate container control covers those.
"""
import hashlib
import base64
import contextlib
import importlib.util
import json
import io
from pathlib import Path
import sys
import tempfile
import threading
import unittest
import uuid
from unittest.mock import patch
from openpyxl import load_workbook

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / 'scripts/repair-2026-10-08'
sys.path.insert(0, str(SCRIPTS))
spec = importlib.util.spec_from_file_location('refresh_stand', SCRIPTS / 'skb-artifact-stand-v2.py')
stand = importlib.util.module_from_spec(spec)
spec.loader.exec_module(stand)


class FileSolver:
    def __init__(self, home):
        self.home = home
        self.artifact = home / 'candidate.txt'
        self.artifact.write_text('wrong', encoding='utf-8')
        self.dp = {'sha256': 'a' * 64}
        self.nonce = 'b' * 32
        self.cid = 'c' * 64
        self.running = True
        self.stopped_at = None
        self.capture_count = 0

    def call(self, tool, args):
        assert tool == 'write'
        self.artifact.write_text(args['content'], encoding='utf-8')
        return {'ok': True}

    def capture(self, final):
        self.capture_count += 1
        self.running = False
        body = self.artifact.read_bytes()
        snapshot = self.home / ('snapshot-%d.json' % self.capture_count)
        snapshot.write_text(json.dumps({'state': 'captured', 'bytes': body.decode(), 'artifactSha256': hashlib.sha256(body).hexdigest()}), encoding='utf-8')
        return stand.task.pin(snapshot)

    def resume(self):
        self.running = True


class RefreshTests(unittest.TestCase):
    def fixture(self, home):
        bridge = stand.Bridge.__new__(stand.Bridge)
        bridge.lock = threading.RLock()
        bridge.place = 'skb:refresh/skillsbench/F/0/jpg-ocr-stat'
        bridge.solver = FileSolver(home)
        bridge.lp = {}
        bridge.db = None
        bridge.counter = 0
        bridge.latest = None
        bridge.captures = []
        bridge.grade_pins = []
        bridge.sealed = False
        bridge.create = lambda place: self.assertEqual(place, bridge.place)
        return bridge

    def test_same_place_and_label_refresh_wrong_correct_wrong(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch') as folder:
            bridge = self.fixture(Path(folder))
            body = {'place': bridge.place, 'said': 'same-answer-label'}

            def grade(_descriptor, _layout, capture):
                # Derive each decision from that capture's actual bytes, rather
                # than returning a scripted list of answers.
                snapshot = stand.task.read_json(capture)
                return {'result': {'evaluation': {'valid': True, 'allTestsPassed': snapshot['bytes'] == 'correct'}}}

            decisions = []
            with patch.object(stand, 'grade_captured', side_effect=grade), patch.object(stand, 'validate_grade_report', side_effect=lambda _dp, owner, _strict: owner):
                for value in ['wrong', 'correct', 'wrong']:
                    bridge.call({'place': bridge.place, 'tool': 'write', 'args': {'content': value}})
                    verified, _ = bridge.objective(body, 'verified')
                    passed, _ = bridge.objective(body, 'passed')
                    self.assertEqual(verified, passed)
                    decisions.append(int(passed['allTestsPassed']))
            self.assertEqual(decisions, [0, 1, 0])
            self.assertEqual(bridge.solver.capture_count, 3)
            self.assertEqual(len(bridge.grade_pins), 3)
            self.assertEqual(len({row['capturePin']['path'] for row in bridge.captures}), 3)
            self.assertTrue(bridge.solver.running)

    def test_new_verified_refreshes_even_without_a_tool_counter_change(self):
        with tempfile.TemporaryDirectory(dir=ROOT / '.scratch') as folder:
            bridge = self.fixture(Path(folder))
            body = {'place': bridge.place, 'said': 'same-answer-label'}
            with patch.object(stand, 'grade_captured', side_effect=lambda _dp, _lp, cp: {'result': {'evaluation': {'valid': True, 'allTestsPassed': stand.task.read_json(cp)['bytes'] == 'correct'}}}), patch.object(stand, 'validate_grade_report', side_effect=lambda _dp, owner, _strict: owner):
                self.assertFalse(bridge.objective(body, 'verified')[0]['allTestsPassed'])
                bridge.solver.artifact.write_text('correct', encoding='utf-8')
                self.assertTrue(bridge.objective(body, 'verified')[0]['allTestsPassed'])
            self.assertEqual(bridge.counter, 0)
            self.assertEqual(bridge.solver.capture_count, 2)

    def test_real_xlsx_original_predicate_through_production_bridge(self):
        home = ROOT / 'docs/repair-2026-10-10/skillsbench-refresh' / ('native-' + uuid.uuid4().hex)
        home.mkdir(parents=True)
        verifier = ROOT / '.phase1-data/skillsbench/vendor/skillsbench/tasks/jpg-ocr-stat/verifier/test_outputs.py'
        original = verifier.read_text(encoding='utf-8')
        original_sha = hashlib.sha256(verifier.read_bytes()).hexdigest()
        oracle = verifier.with_name('stat_oracle.xlsx').read_bytes()
        workbook = load_workbook(io.BytesIO(oracle))
        workbook.active.cell(2, 3).value = 'deliberately-wrong-refresh-control'
        buffer = io.BytesIO()
        workbook.save(buffer)
        workbook.close()
        wrong = buffer.getvalue()
        bridge = self.fixture(home)

        # Preserve the original predicate byte-for-byte except for relocating
        # its Linux candidate path to each actual native snapshot. This is a
        # native integration control, not private Docker certification.
        marker = 'OUTPUT_FILE = "/app/workspace/stat_ocr.xlsx"'
        self.assertEqual(original.count(marker), 1)
        decisions = []
        steps = []

        def grade(_descriptor, _layout, capture):
            snapshot = stand.task.read_json(capture)
            artifact = home / ('grade-' + str(bridge.solver.capture_count) + '.xlsx')
            artifact.write_bytes(base64.b64decode(snapshot['bytes']))
            derived = original.replace(marker, 'OUTPUT_FILE = ' + repr(str(artifact)), 1)
            namespace = {'__file__': str(verifier), '__name__': 'native_original_predicate_control'}
            exec(compile(derived, str(verifier), 'exec'), namespace)
            tests = [value for name, value in namespace.items() if name.startswith('test_') and callable(value)]
            self.assertEqual(len(tests), 1)
            passed = True
            with contextlib.redirect_stdout(io.StringIO()):
                try:
                    tests[0]()
                except AssertionError:
                    passed = False
            steps.append({'capturePin': capture, 'artifactSha256': hashlib.sha256(artifact.read_bytes()).hexdigest(), 'derivedPredicateSha256': hashlib.sha256(derived.encode()).hexdigest(), 'passed': passed})
            return {'result': {'evaluation': {'valid': True, 'allTestsPassed': passed}}}

        with patch.object(stand, 'grade_captured', side_effect=grade), patch.object(stand, 'validate_grade_report', side_effect=lambda _dp, owner, _strict: owner):
            for artifact in [wrong, oracle, wrong]:
                bridge.call({'place': bridge.place, 'tool': 'write', 'args': {'content': base64.b64encode(artifact).decode()}})
                body = {'place': bridge.place, 'said': 'same-answer-label'}
                bridge.objective(body, 'verified')
                decisions.append(int(bridge.objective(body, 'passed')[0]['allTestsPassed']))
        self.assertEqual(decisions, [0, 1, 0])
        self.assertEqual(len(steps), 3)
        self.assertEqual(hashlib.sha256(verifier.read_bytes()).hexdigest(), original_sha)
        (home / 'result.json').write_text(json.dumps({'protocol': 'skillsbench-native-original-predicate-refresh-control-v1', 'decisions': decisions, 'verified': True, 'productionBridgeUsed': True, 'originalPredicateSourceSha256': original_sha, 'candidatePathRelocated': True, 'originalPredicateFileModified': False, 'dockerGraderUsed': False, 'solverCaptureIsTestDouble': True, 'modelCalls': 0, 'scoreCertificate': False, 'steps': steps}, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main(verbosity=2)
