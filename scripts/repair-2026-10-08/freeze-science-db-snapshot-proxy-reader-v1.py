"""Freeze only F new reader/controls; production copied databases are not opened."""
import importlib.util
import json
from pathlib import Path
import _sqlite3

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'scripts/repair-2026-10-08/science-db-snapshot-proxy-read-v1.py'
TEST = ROOT/'test/science_db_snapshot_proxy_read_test.py'
DOC = ROOT/'docs/repair-2026-10-08/science-db-snapshot-proxy-reader-controls-v1'
spec = importlib.util.spec_from_file_location('reader_freeze',SOURCE)
r = importlib.util.module_from_spec(spec)
spec.loader.exec_module(r)
m = r.m

def main():
    text = (DOC/'final-green/stderr.txt').read_bytes()
    text = text.decode('utf-16' if text.startswith(b'\xff\xfe') else 'utf-8-sig')
    assert 'Ran 3 tests' in text and text.rstrip().endswith('OK')
    source_pin = m.pin(SOURCE)
    matches = []
    for p in m.FIXTURE_BASE.glob('proxy-*/control-result.json'):
        obj = json.loads(p.read_bytes())
        if obj['sourcePin'] == source_pin:
            assert obj['immutable'] is True and obj['walRead'] is False and len(obj['rows']) == 4
            matches.append(m.pin(p))
    assert len(matches) == 1
    old = [m.pin(p) for leaf in ('first-red','second-red') for p in sorted((DOC/leaf).iterdir()) if p.is_file()]
    m.save_new(DOC/'red-attempts-manifest.json',{'pins':old,'preserved':True,
        'first':'2pass1fail; negative fixture SQL context did not close its WAL connection, immutable correctly ignored WAL modification.',
        'second':'2pass1error; closing fixture connection removed its synthetic side files, causing missing fixture Pin.',
        'final':'Define each negative main at initial fixture creation and close connection before adding ignored side files.'})
    controls = dict(protocol='science-db-snapshot-proxy-reader-controls-v1',validated=True,passedTests=3,failedTests=0,
        actualNativeChildExit=0,sourcePin=source_pin,testPin=m.pin(TEST),stdoutPin=m.pin(DOC/'final-green/stdout.txt'),
        stderrPin=m.pin(DOC/'final-green/stderr.txt'),positiveFixtureReceipt=matches[0],
        redAttemptsManifestPin=m.pin(DOC/'red-attempts-manifest.json'),
        assertions=['Four immutable main databases yield same local base_url and leave all12 copied bytes/SHA unchanged.',
                    'Malformed owned WAL/SHM are not read by immutable queries.',
                    'Missing model/base_url, disagreeing worker origins, changed Pin, unknown scope and URL query rejected.'],
        onlyFWrites=True,productionQueryPerformed=False,originalSqliteOpened=False,APIKeyColumnsSelected=False,
        modelCalls=0,gradingCalls=0,DWrites=0,EAndCWrites=0,lockOperations=0)
    control_pin = m.save_new(DOC/'controls.json',controls)
    source_copies = []
    m.new_dirs(DOC/'source-snapshots')
    for source in (SOURCE,TEST,Path(__file__).resolve()):
        dest = DOC/'source-snapshots'/source.name
        raw = source.read_bytes()
        with dest.open('xb') as f:
            f.write(raw); f.flush(); r.os.fsync(f.fileno())
        assert dest.read_bytes() == raw
        source_copies.append(m.pin(dest))
    snapshot = ROOT/'docs/repair-2026-10-08/science-db-snapshots/root-snapshot-2026-10-09T04-10-v1.json'
    snapshot_pin = m.pin(snapshot)
    assert snapshot_pin['sha256'] == '8134c6e96ef8718615da901548f2c0c6ada7076ee15543c4723c555ba2a36220'
    obj = json.loads(snapshot.read_bytes())
    assert obj['validated'] is True and obj['snapshotComplete'] is True and obj['fixtureOnly'] is False
    review = dict(protocol='science-db-snapshot-proxy-reader-review-v1',validated=True,sourcePin=source_pin,
        snapshotSourcePin=m.pin(r.SOURCE),controlsPin=control_pin,testPin=m.pin(TEST),
        interpreterPin=m.pin(m.NATIVE_EXE),sqliteExtensionPin=m.pin(_sqlite3.__file__),sqliteVersion=r.sqlite3.sqlite_version,
        freezerPin=m.pin(__file__),sourceSnapshots=source_copies,actualSnapshotReceiptPin=snapshot_pin,
        snapshotRoot=obj['target'],productionQueryPerformed=False,originalSqliteOpened=False,
        SQL=r.QUERY,model=r.MODEL,immutable=True,walRead=False,workingCopiesOpened=False,
        missingRawBaseURLPolicy='Invalid and no fallback to original/working databases; separate reviewed WAL-aware protocol only if actual evidence requires it.',
        originalLockMustMatch=True,financialAuditExpectedSha256=r.FINANCIAL_SHA,releaseAuthorized=False,
        limitations=['Agent controls use new own F SQLite databases only; do not establish production port.',
                     'Only base_url column is selected; model is a WHERE predicate, no API-key fields.',
                     'This source does not mutate/release canonical lock or certify scores/ownership absence.'])
    review_pin = m.save_new(DOC/'review.json',review)
    # Resolve the already-created small financial certificate by its exact SHA, never raw provider files.
    audits = ROOT/'docs/repair-2026-10-08/scientific-financial-interruption-audits'
    financial = []
    if audits.exists():
        for p in audits.glob('*/audit.json'):
            if m.pin(p)['sha256'] == r.FINANCIAL_SHA:
                financial.append(p)
    md = f"""读取器 3 项 F 原生控制全部通过；保留此前 2 次夹具失败原件，最终 child exit0。读取器 SHA {source_pin['sha256']}，review SHA {review_pin['sha256']}。

实际 Root snapshot 8134c6e…已完成，但本 agent 没有打开任何生产副本或原数据库。Root 另行执行下面 CLI。只读 raw 四个 main，SQLite mode=ro&immutable=1，固定 SQL `{r.QUERY}`、参数 `{r.MODEL}`；WAL/SHM 与 working 不打开。每个 worker 必须有唯一相同 127.0.0.1 origin，否则 typed invalid、无端口猜测或自动回退。

成功时生成 raw-query.json 与 financial-interruption-proxy-port-identity-v1 的 proxy-port-identity.json，绑定实际 snapshot、raw12 Pins、source、actual financial4722、原lock31fa；保持 old4unknown，不操作锁或API，不授权重启/评分/释放。snapshot raw12 查询前后 SHA 相同；所有实际查询仅返回 base_url 一列。

Root 命令（financial 参数取 actual4722 完整证书绝对路径；输出必须 fresh）：

```powershell
& 'D:/ProgramData/anaconda3/python.exe' -B -X utf8 '{SOURCE}' --snapshot-receipt '{snapshot}' --snapshot-sha '{snapshot_pin['sha256']}' --financial-audit '<actual4722 audit.json absolute path>' --review '{DOC/'review.json'}' --review-sha '{review_pin['sha256']}' --output-directory '{ROOT/'docs/repair-2026-10-08/science-db-snapshots/root-proxy-identity-v1'}'
```
"""
    with (DOC/'review.md').open('xb') as f:
        f.write(md.encode('utf-8')); f.flush(); r.os.fsync(f.fileno())
    m.verify(source_pin)
    print(json.dumps({'review':review_pin,'controls':control_pin,'reader':source_pin,'test':m.pin(TEST),
                      'report':m.pin(DOC/'review.md'),'sqliteExtension':m.pin(_sqlite3.__file__),
                      'snapshot':snapshot_pin}))

if __name__ == '__main__':
    main()
