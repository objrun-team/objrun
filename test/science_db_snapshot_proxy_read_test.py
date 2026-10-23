"""F-own SQLite controls; never read original databases or invoke network/locks."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT/'scripts/repair-2026-10-08/science-db-snapshot-proxy-read-v1.py'
spec = importlib.util.spec_from_file_location('proxy_reader_fixture',SOURCE)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)

class ProxyReaderTests(unittest.TestCase):
    def test_four_raw_immutable_mains_select_only_base_url_and_ignore_side_files(self):
        raw,pins = r.create_fixture()
        rows = r.query_raw(raw,pins,fixture=True)
        self.assertEqual([v['worker'] for v in rows],list(range(4)))
        self.assertEqual(len({v['base_url'] for v in rows}),4)
        self.assertEqual({r.origin(v['base_url'],r.manifest_routes()) for v in rows},{'http://127.0.0.1:49321'})
        self.assertEqual(pins,[r.m.pin(p) for p in r.m.files(raw)])
        self.assertEqual(len(rows),4)
        r.m.save_new(raw.parent/'control-result.json',{'sourcePin':r.m.pin(SOURCE),'rows':rows,'inputPins':pins,
            'immutable':True,'walRead':False,'originalSqliteOpened':False,'onlyFWrites':True,'modelCalls':0})

    def test_missing_value_and_disagreeing_workers_reject_no_port_guess(self):
        raw,pins = r.create_fixture(missing_worker=1)
        with self.assertRaisesRegex(RuntimeError,'missing_or_excess_proxy_origin_for_worker'):
            r.query_raw(raw,pins,fixture=True)
        raw,pins = r.create_fixture(different_worker=2)
        with self.assertRaisesRegex(RuntimeError,'workers_disagree_proxy_origin'):
            r.query_raw(raw,pins,fixture=True)

    def test_changed_pin_unknown_scope_and_secret_url_reject(self):
        raw,pins = r.create_fixture()
        count = len(r._OPENED_DATABASES)
        changed = [dict(p) for p in pins]
        changed[0]['sha256'] = '0'*64
        with self.assertRaisesRegex(RuntimeError,'pin_changed'):
            r.query_raw(raw,changed,fixture=True)
        with self.assertRaisesRegex(RuntimeError,'fixture_not_self_created'):
            r.query_raw(ROOT,[],fixture=True)
        self.assertEqual(len(r._OPENED_DATABASES),count)
        route = sorted(r.manifest_routes())[0]
        wrong = ['http://127.0.0.1:49321'+route.replace(r.m.RUN,r.m.RUN+'x'),
                 'http://example.invalid:49321'+route,
                 'http://127.0.0.1:49321'+route+'?unexpected=value',
                 'http://fixture-user@127.0.0.1:49321'+route,
                 'http://127.0.0.1:49321'+route+'/extra',
                 'http://127.0.0.1:49321',
                 'http://127.0.0.1:49321'+route.replace('/v1','-unknown/v1')]
        for value in wrong:
            with self.subTest(value=value):
                with self.assertRaisesRegex(RuntimeError,'noncanonical_or_nonlocal_proxy_origin'):
                    r.origin(value,r.manifest_routes())

if __name__ == '__main__':
    unittest.main()
