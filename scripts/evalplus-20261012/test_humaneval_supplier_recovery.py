import importlib.util
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('supplier_report', Path(__file__).with_name('verify-humaneval-supplier-recovery.py'))
report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(report)


class SupplierRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.ids = ['HumanEval/' + str(n) for n in range(164)]
        self.old = {tid: ({'grade': {'valid': True, 'passed': True}}, 'old/' + tid) for tid in self.ids}
        self.old[self.ids[41]] = ({'grade': {'valid': False, 'passed': False}}, 'old/41')

    def test_only_invalid_task_can_be_recovered_fixed_denominator(self):
        new = {self.ids[41]: ({'grade': {'valid': True, 'passed': False}}, 'new/41')}
        selected = report.select_effective(self.ids, self.old, new, [self.ids[41]])
        self.assertEqual(len(selected), 164)
        self.assertEqual(sum(r['valid'] for r in selected), 164)
        self.assertEqual(sum(r['passed'] for r in selected), 163)
        self.assertEqual(selected[41]['provider'], 'Fireworks')

    def test_even_wrong_valid_answer_is_never_resampled(self):
        self.old[self.ids[0]][0]['grade']['passed'] = False
        new = {self.ids[0]: ({'grade': {'valid': True, 'passed': True}}, 'new/0')}
        with self.assertRaisesRegex(RuntimeError, 'RecoveryCannotReplacePriorValid'):
            report.select_effective(self.ids, self.old, new, [self.ids[0]])

    def test_unknown_cost_and_retained_receipts_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for name, cost in [('current', .1), ('retained-recovery/old', None)]:
                path = out / 'calls' / name
                path.mkdir(parents=True)
                (path / 'dispatch.json').write_text('{}')
                (path / 'receipt.json').write_text(report.json.dumps({'actualCostUsd': cost, 'unknownCost': cost is None, 'upperBoundUsd': .02}))
            value = report.ledger(out)
            self.assertEqual(value['receipts'], 2)
            self.assertEqual(value['knownCostUsd'], .1)
            self.assertEqual(value['unknownCostCount'], 1)
            self.assertEqual(value['unknownCostUpperBoundUsd'], .02)

    def test_cached_protocol_replay_is_counted_once(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)
            for name in ['current', 'retained-recovery/old']:
                path = out / 'tasks' / name
                path.mkdir(parents=True)
                (path / 'submit-response-attempts.json').write_text('[{"protocolAttempt":1,"requestHash":"same","generationId":"same"}]')
            self.assertEqual(report.protocol_repairs(out)['protocolRepairCalls'], 1)


if __name__ == '__main__':
    unittest.main()
