"""F-only routed reader revision: freeze new source, exact controls and v1 evidence."""
import importlib.util
import json
from pathlib import Path
import _sqlite3

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'scripts/benchmark-repair/science-db-snapshot-proxy-read-v1.py'
TEST = ROOT/'test/benchmarks/science_db_snapshot_proxy_read_test.py'
DOC = ROOT/'docs/repair-2026-10-08/science-db-snapshot-proxy-reader-routed-v2'
spec = importlib.util.spec_from_file_location('routed_reader_freeze',SOURCE)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
m = r.m

def copy_new(source, target):
    raw = source.read_bytes()
    m.new_dirs(target.parent)
    with target.open('xb') as f:
        f.write(raw); f.flush(); r.os.fsync(f.fileno())
    assert target.read_bytes() == raw
    return m.pin(target)

def main():
    text = (DOC/'stderr.txt').read_bytes()
    text = text.decode('utf-16' if text.startswith(b'\xff\xfe') else 'utf-8-sig')
    assert 'Ran 3 tests' in text and text.rstrip().endswith('OK')
    source_pin = m.pin(SOURCE)
    receipts = [m.pin(p) for p in m.FIXTURE_BASE.glob('proxy-*/control-result.json')
                if json.loads(p.read_bytes())['sourcePin'] == source_pin]
    assert len(receipts) == 1
    positive = json.loads(Path(receipts[0]['path']).read_bytes())
    assert len({v['base_url'] for v in positive['rows']}) == 4
    assert {r.origin(v['base_url'],r.manifest_routes()) for v in positive['rows']} == {'http://127.0.0.1:49321'}
    archive = [m.pin(p) for p in sorted((DOC/'prior-v1').rglob('*')) if p.is_file()]
    archive_pin = m.save_new(DOC/'prior-v1-manifest.json',{'pins':archive,'archivedV1SourceSha256':'9a52d403ee579540bec8929bb6b7df3e192423a0a0fdf399b395e2972764a742',
        'v1ProductionQueryPerformed':False,'blocker':'v1 accepted only bare origin; actual source api.base_url contains different per-task /v1 routes.',
        'allOldControlsAndReviewsRetained':True})
    controls = dict(protocol='science-db-snapshot-proxy-reader-routed-controls-v2',validated=True,
        actualNativeChildExit=0,passedTests=3,failedTests=0,sourcePin=source_pin,testPin=m.pin(TEST),
        stdoutPin=m.pin(DOC/'stdout.txt'),stderrPin=m.pin(DOC/'stderr.txt'),positiveFixtureReceipt=receipts[0],
        priorV1ManifestPin=archive_pin,originalManifestPin=m.pin(r.MANIFEST),exactOriginalAllowedRoutes=1220,
        positive='Four distinct genuine original-manifest task path shapes; same independently parsed local origin; raw12 unchanged; WAL ignored.',
        negatives=['Wrong RUN','nonlocal host','query','URL credential','extra path','bare origin','unknown officialId',
                   'missing model value','different ports','changed copied Pin','unknown scope'],
        productionQueryPerformed=False,originalSqliteOpened=False,onlyFWrites=True,modelCalls=0,gradingCalls=0,lockOperations=0)
    controls_pin = m.save_new(DOC/'controls.json',controls)
    snaps = [copy_new(p,DOC/'source-snapshots'/p.name) for p in (SOURCE,TEST,Path(__file__).resolve())]
    source_json = json.loads((m.META/'source.json').read_bytes())
    plan = next(p for p in source_json['repairFiles'] if p['path'] == 'scripts/benchmark-repair/scientific-journal-plan.ts')
    original_plan = m.pin(ROOT/plan['path'])
    assert original_plan['sha256'] == plan['sha256']
    snapshot = ROOT/'.local-evidence/repository/test/fixtures/repair/science-db-snapshots/root-snapshot-2026-10-09T04-10-v1.json'
    snapshot_pin = m.pin(snapshot)
    assert snapshot_pin['sha256'] == '8134c6e96ef8718615da901548f2c0c6ada7076ee15543c4723c555ba2a36220'
    review = dict(protocol='science-db-snapshot-proxy-reader-review-v1',transportRevision='routed-v2',validated=True,
        sourcePin=source_pin,snapshotSourcePin=m.pin(r.SOURCE),controlsPin=controls_pin,testPin=m.pin(TEST),
        interpreterPin=m.pin(m.NATIVE_EXE),sqliteExtensionPin=m.pin(_sqlite3.__file__),sqliteVersion=r.sqlite3.sqlite_version,
        freezerPin=m.pin(__file__),sourceSnapshots=snaps,originalManifestPin=m.pin(r.MANIFEST),
        originalRouteProducerPin=original_plan,exactOriginalAllowedRoutes=1220,actualSnapshotReceiptPin=snapshot_pin,
        productionQueryPerformed=False,originalSqliteOpened=False,workingCopiesOpened=False,
        immutable=True,walRead=False,SQL=r.QUERY,model=r.MODEL,financialAuditExpectedSha256=r.FINANCIAL_SHA,
        rowsPreserveFullBaseURL=True,sharedOriginParsedSeparately=True,noBareOriginOnlyAssumption=True,
        noFallbackToOriginalOrWorking=True,releaseAuthorized=False,
        limitations=['Production copied main may lack a checkpointed value; reject instead of falling back to WAL/original.',
                     'This evidence prepares only fifth-port identity for later independent closure, not a release or score certificate.'])
    review_pin = m.save_new(DOC/'review.json',review)
    md = f"""Root's static review confirmed that v1's bare-origin assumption disagrees with the production UPDATE. The v1 9a52 source and all original controls/preparation artifacts are retained in prior-v1, pinned by manifest SHA {archive_pin['sha256']}. Original v1 did not execute production SQL.

New routed-v2 preserves the SQL and raw immutable read-only approach. It returns each worker's complete base_url, validates RUN/benchmark/arm/replica0/encodeURIComponent(officialId)/v1 against the 1220 exact routes pinned in the original manifest, then independently compares origin and port; the four URL paths may differ. Original SQL/api.base_url, original databases, WAL, working copies, and all 81 sources are unchanged.

All 3 actual F-native controls passed, child exit0: positive control with four distinct original manifest paths; rejection of wrong RUN, nonlocal host, query, credential, extra path, bare origin, and unknown officialID; original missing/different-port/pin/scope controls still pass. Reader SHA {source_pin['sha256']}, review SHA {review_pin['sha256']}.

Exact Root command (financial argument uses the actual4722 path; F output must be fresh):

```powershell
& 'D:/ProgramData/anaconda3/python.exe' -B -X utf8 '{SOURCE}' --snapshot-receipt '{snapshot}' --snapshot-sha '{snapshot_pin['sha256']}' --financial-audit '<actual4722 audit.json absolute path>' --review '{DOC/'review.json'}' --review-sha '{review_pin['sha256']}' --output-directory '{ROOT/'docs/repair-2026-10-08/science-db-snapshots/root-proxy-identity-routed-v2'}'
```

Prepares only raw-query and typed proxy-port evidence. This agent has not opened production copies or original SQLite, released locks, or run models/grading. If the raw checkpoint query cannot retrieve the correct value, the result is typed invalid, with no automatic retry or switch to a working copy.
"""
    with (DOC/'review.md').open('xb') as f:
        f.write(md.encode('utf-8')); f.flush(); r.os.fsync(f.fileno())
    m.verify(source_pin)
    print(json.dumps({'reader':source_pin,'review':review_pin,'controls':controls_pin,'report':m.pin(DOC/'review.md'),
                      'oldArchiveManifest':archive_pin,'test':m.pin(TEST)}))

if __name__ == '__main__':
    main()
