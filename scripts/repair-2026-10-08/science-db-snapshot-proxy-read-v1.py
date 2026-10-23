"""Select only api.base_url in four verified raw immutable copies. Never open originals."""
import argparse
import importlib.util
import json
import os
from pathlib import Path
import sqlite3
import sys
from urllib.parse import quote, urlsplit
import uuid

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'scripts/repair-2026-10-08/science-worker-db-snapshot-v1.py'
SOURCE_SHA = '3d3c408fa18cc76569f841bf3af68366fb68d4adcb167781a7b030dd65573d32'
SNAPSHOT_REVIEW_SHA = 'c382728966b8ecae1c2e934dd22404ee40483948e9d6c10f24125003870a574e'
FINANCIAL_SHA = '4722f1e9d25ed2f2ed061cf6d37fa89d4c5816625f15809b8309cccfdbcbc4d4'
spec = importlib.util.spec_from_file_location('snapshot_reader_contract', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
QUERY = 'SELECT base_url FROM api WHERE model=?'
MODEL = 'deepseek-flash'
MANIFEST = m.META/'manifest.json'
MANIFEST_SHA = '4e4cde3bdc879b2b1c721e7e6ae812807893fe9835e8bd2c45d943c93e9aa78d'
_FIXTURES = set()
_OPENED_DATABASES = []

def minimal(p):
    return {k:p[k] for k in ('path','bytes','sha256')}

def manifest_routes():
    m.need(m.pin(MANIFEST)['sha256'] == MANIFEST_SHA,'original_manifest_changed')
    manifest = json.loads(MANIFEST.read_bytes())
    schedule = manifest['taskSchedule']
    m.need(manifest['campaign'] == m.RUN and len(schedule) == 1220,'original_manifest_schedule')
    routes = set()
    for row in schedule:
        m.need(row['benchmark'] in ('chembench','aime','cmt') and row['arm'] in ('U','F') and row['replica'] == 0,'original_route_tuple')
        routes.add('/'+m.RUN+'/'+row['benchmark']+'/'+row['arm']+'/0/'+quote(row['officialId'],safe="~!*'()-._")+'/v1')
    m.need(len(routes) == 1220,'original_routes_unique')
    return routes

def origin(value, allowed_routes):
    m.need(isinstance(value,str), 'proxy_origin_type')
    u = urlsplit(value)
    m.need(u.scheme == 'http' and u.hostname == '127.0.0.1' and not u.username and not u.password
           and not u.query and not u.fragment and u.path in allowed_routes and u.port is not None
           and 0 < u.port < 65536 and u.netloc == f'127.0.0.1:{u.port}', 'noncanonical_or_nonlocal_proxy_origin')
    return f'http://127.0.0.1:{u.port}'

def copy_pins(raw_root, expected, *, fixture=False):
    raw_root = Path(raw_root).absolute()
    if fixture:
        m.need(raw_root in _FIXTURES, 'fixture_not_self_created')
    else:
        m.need(raw_root.parent.parent == m.OWNER and raw_root.name == 'raw'
               and raw_root.parent.name.startswith('scientific-db-snapshot-' + m.RUN + '-'), 'snapshot_raw_owned_scope')
    m.ordinary(raw_root)
    wanted = m.files(raw_root)
    m.need(len(expected) == 12 and {Path(p['path']).absolute() for p in expected} == set(wanted), 'exact_raw_twelve_pins')
    by_path = {Path(p['path']).absolute():minimal(p) for p in expected}
    for path in wanted:
        m.ordinary(path,file=True)
        m.verify(by_path[path])
    return by_path

def query_raw(raw_root, expected, *, fixture=False):
    routes = manifest_routes()
    before = copy_pins(raw_root, expected, fixture=fixture)
    rows = []
    for worker in range(4):
        path = Path(raw_root).absolute() / f'worker-{worker}/data/h2h.sqlite'
        connection = None
        try:
            # immutable disables journal/WAL/SHM access and cannot create database side files.
            connection = sqlite3.connect(path.as_uri()+'?mode=ro&immutable=1',uri=True,timeout=5)
            _OPENED_DATABASES.append(str(path))
            values = connection.execute(QUERY,(MODEL,)).fetchmany(17)
            m.need(0 < len(values) <= 16, 'missing_or_excess_proxy_origin_for_worker')
            values = {v[0] for v in values}
            for value in values:
                origin(value,routes)
            m.need(len(values) == 1, 'nonunique_proxy_origin_for_worker')
            rows.append({'worker':worker,'base_url':values.pop(),'rawDatabasePin':before[path]})
        finally:
            if connection is not None:
                connection.close()
    m.need(len({origin(r['base_url'],routes) for r in rows}) == 1, 'workers_disagree_proxy_origin')
    copy_pins(raw_root, expected, fixture=fixture)
    return rows

def create_fixture(*, missing_worker=None, different_worker=None):
    root = m.FIXTURE_BASE / ('proxy-' + uuid.uuid4().hex) / 'raw'
    paths = sorted(manifest_routes())[:4]
    for i,path in enumerate(m.files(root)):
        m.new_dirs(path.parent)
        if path.name == 'h2h.sqlite':
            connection = sqlite3.connect(path)
            try:
                connection.execute('CREATE TABLE api(model TEXT,base_url TEXT)')
                worker = i // 3
                if worker != missing_worker:
                    value = ('http://127.0.0.1:49322' if worker == different_worker else 'http://127.0.0.1:49321')+paths[worker]
                    connection.execute('INSERT INTO api VALUES(?,?)',(MODEL,value))
                connection.commit()
            finally:
                connection.close()
        else:
            # Deliberately not a valid WAL/SHM: successful immutable query must ignore these.
            path.write_bytes(b'own-F-fixture-not-a-sqlite-side-file'+bytes([i]))
    _FIXTURES.add(root.absolute())
    return root.absolute(), [m.pin(p) for p in m.files(root)]

def review_guard(path, expected):
    m.ordinary(path,file=True)
    m.need(m.pin(path)['sha256'] == expected, 'proxy_reader_review_changed')
    review = json.loads(Path(path).read_bytes())
    m.need(review['protocol'] == 'science-db-snapshot-proxy-reader-review-v1' and review['validated'] is True
           and review['productionQueryPerformed'] is False, 'proxy_reader_review_profile')
    for key in ('sourcePin','snapshotSourcePin','controlsPin','interpreterPin','sqliteExtensionPin'):
        m.verify(review[key])
    m.need(Path(review['sourcePin']['path']).absolute() == Path(__file__).resolve(), 'reader_source_identity')
    m.need(m.pin(SOURCE)['sha256'] == SOURCE_SHA and Path(sys.executable).resolve() == m.NATIVE_EXE
           and m.pin(m.NATIVE_EXE)['sha256'] == m.NATIVE_SHA, 'snapshot_or_native_interpreter_changed')
    return m.pin(path)

def main():
    p = argparse.ArgumentParser()
    p.add_argument('--snapshot-receipt',type=Path,required=True)
    p.add_argument('--snapshot-sha',required=True)
    p.add_argument('--financial-audit',type=Path,required=True)
    p.add_argument('--review',type=Path,required=True)
    p.add_argument('--review-sha',required=True)
    p.add_argument('--output-directory',type=Path,required=True)
    args = p.parse_args()
    out = args.output_directory.absolute()
    m.need(out.is_relative_to(ROOT/'docs/repair-2026-10-08/science-db-snapshots') and not out.exists(), 'fresh_F_proxy_output_scope')
    review_pin = review_guard(args.review,args.review_sha)
    m.new_dirs(out.parent)
    out.mkdir(exist_ok=False)
    proof = dict(protocol='financial-interruption-proxy-port-identity-v1',runId=m.RUN,validated=False,
                 snapshotOnly=True,originalSqliteOpened=False,modelCalls=0,gradingCalls=0,
                 readerReviewPin=review_pin,extractorSourcePin=m.pin(__file__),immutable=True,walRead=False,
                 financialReleaseAuthorized=False)
    try:
        m.ordinary(args.snapshot_receipt,file=True)
        snapshot_pin = m.pin(args.snapshot_receipt)
        m.need(snapshot_pin['sha256'] == args.snapshot_sha,'snapshot_receipt_changed')
        snapshot = json.loads(args.snapshot_receipt.read_bytes())
        m.need(snapshot['protocol'] == 'science-worker-db-snapshot-v1' and snapshot['runId'] == m.RUN
               and snapshot['fixtureOnly'] is False and snapshot['validated'] is True
               and snapshot['snapshotComplete'] is True and snapshot['sourceHandlesClosed'] is True
               and snapshot['sourceBefore'] == snapshot['sourceAfter'] and len(snapshot['sourceBefore']) == 12
               and snapshot['originalSqliteOpened'] is False and len(snapshot['rawCopies']) == 12
               and len(snapshot['workingCopies']) == 12,'production_completed_snapshot_required')
        m.need(snapshot['sourcePin']['sha256'] == SOURCE_SHA and snapshot['reviewPin']['sha256'] == SNAPSHOT_REVIEW_SHA,'snapshot_executor_profile')
        m.verify(snapshot['sourcePin']); m.verify(snapshot['reviewPin'])
        target = Path(snapshot['target']).absolute()
        suffix = target.name.removeprefix('scientific-db-snapshot-'+m.RUN+'-')
        m.need(target.parent == m.OWNER and len(suffix) == 32 and all(c in '0123456789abcdef' for c in suffix),'snapshot_uuid_sibling_scope')
        m.ordinary(target)
        m.ordinary(args.financial_audit,file=True)
        financial_pin = m.pin(args.financial_audit)
        m.need(financial_pin['sha256'] == FINANCIAL_SHA,'actual_fullraw_financial_pin')
        financial = json.loads(args.financial_audit.read_bytes())
        m.need(financial['validated'] is True and financial['financialOnly'] is True and financial['runId'] == m.RUN
               and financial['releasePermitted'] is False and financial['ownerClosureCertified'] is False,'financial_profile')
        original_lock = m.original_lock()
        raw_pins = [minimal(v) for v in snapshot['rawCopies']]
        rows = query_raw(target/'raw',raw_pins)
        route_manifest_pin = m.pin(MANIFEST)
        m.verify(snapshot_pin); m.verify(financial_pin); m.verify(original_lock['pin'])
        m.need(review_guard(args.review,args.review_sha) == review_pin,'reader_sources_changed_during_query')
        raw_query = dict(protocol='financial-interruption-readonly-proxy-query-v1',runId=m.RUN,query=QUERY,model=MODEL,
            rows=rows,snapshotPins=raw_pins,snapshotRoot=str(target),snapshotReceiptPin=snapshot_pin,
            extractorSourcePin=m.pin(__file__),originalSqliteOpened=False,immutable=True,walRead=False,
            rawCopiesUnchangedAfterQuery=True,sqliteVersion=sqlite3.sqlite_version,queryInputMode='raw-immutable-main-only')
        raw_query.update(routeManifestPin=route_manifest_pin,routePolicy='original1220-exact-run-benchmark-arm-replica-officialId-v1',
                         sharedProxyOrigin=origin(rows[0]['base_url'],manifest_routes()))
        query_pin = m.save_new(out/'raw-query.json',raw_query)
        proof.update(validated=True,financialAuditPin=financial_pin,originalLockPin=original_lock['pin'],hostPid=104376,
                     proxyPort=urlsplit(rows[0]['base_url']).port,rawQueryPin=query_pin,snapshotPins=raw_pins,
                     snapshotRoot=str(target),snapshotReceiptPin=snapshot_pin,proxyOrigin=origin(rows[0]['base_url'],manifest_routes()),
                     routeManifestPin=route_manifest_pin,
                     originalSourcePins=[minimal(v) for v in snapshot['sourceBefore']],rawCopiesUnchangedAfterQuery=True)
    except Exception as e:
        proof['error'] = type(e).__name__+':'+str(e)
        proof['noFallbackToOriginalOrWorking'] = True
    evidence = m.save_new(out/'proxy-port-identity.json',proof)
    print(json.dumps({'proof':evidence,'validated':proof['validated'],'originalSqliteOpened':False}))
    return 0 if proof['validated'] else 1

if __name__ == '__main__':
    raise SystemExit(main())
