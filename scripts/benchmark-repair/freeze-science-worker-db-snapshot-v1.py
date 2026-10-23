"""F-only source/real fixture closure. D original access is stat/free metadata only."""
import importlib.util
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / 'scripts/benchmark-repair/science-worker-db-snapshot-v1.py'
spec = importlib.util.spec_from_file_location('snapshot_freeze', SOURCE)
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)
DOC = ROOT / 'docs/repair-2026-10-08/science-db-snapshot-native-controls-v1'
TEST = ROOT / 'test/science_worker_db_snapshot_test.py'
PS = SOURCE.with_suffix('.ps1')

def save(path, value):
    if isinstance(value, dict):
        value = (json.dumps(value, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    path.parent.mkdir(exist_ok=True, parents=True)
    with path.open('xb') as f:
        f.write(value); f.flush(); os.fsync(f.fileno())
    assert path.read_bytes() == value
    return m.pin(path)

def main():
    log = (DOC / 'stderr.txt').read_bytes()
    text = log.decode('utf-16' if log.startswith(b'\xff\xfe') else 'utf-8-sig')
    assert 'Ran 4 tests' in text and text.rstrip().endswith('OK')
    results = list(m.FIXTURE_BASE.glob('*/control-result.json'))
    assert len(results) == 1
    native = json.loads(results[0].read_bytes())
    assert native['sourcePin'] == m.pin(SOURCE)
    result = native['result']
    assert result['validated'] and result['fixtureOnly'] and len(result['rawCopies']) == len(result['workingCopies']) == 12
    assert all(r['FlushFileBuffersReturned'] for r in result['rawCopies'] + result['workingCopies'])
    assert result['sourceBefore'] == result['sourceAfter'] and result['sourceHandlesClosed']
    source_pins = [m.pin(p) for p in (SOURCE, PS, TEST, Path(__file__).resolve())]
    copies = []
    for p in source_pins:
        copies.append(save(DOC / 'source-snapshots' / Path(p['path']).name, Path(p['path']).read_bytes()))
    controls = dict(protocol='science-worker-db-snapshot-native-controls-v1', validated=True,
        actualNativeChildExit=0, passedTests=4, failedTests=0, interpreter=m.pin(m.NATIVE_EXE),
        sourcePin=m.pin(SOURCE), launcherPin=m.pin(PS), testPin=m.pin(TEST),
        stdoutPin=m.pin(DOC/'stdout.txt'), stderrPin=m.pin(DOC/'stderr.txt'), nativeSuccessReceiptPin=m.pin(results[0]),
        nativeObservations=['24 independent files, FlushFileBuffers success and full bytes/SHA readback',
                            '12 source handles simultaneously block existing write and deletion: real WinError32',
                            'copy fault after 3 files retains partial, closes handles, and original source Pins unchanged',
                            'actual F junction, wrong scope and pre-existing target rejected before copy'],
        productionActorGuardExecuted=False, productionSnapshotPerformed=False, originalSqliteOpened=False,
        DProductionWrites=0, EAndCWrites=0, modelCalls=0, gradingCalls=0, lockOperations=0,
        limitations=['No power loss or physical disk failure simulated.', 'Production CIM/resource and source-handle guards must run fresh under Root.', 'F fixture actor guard is explicitly synthetic, never a production owned-closure certificate.'])
    controls_pin = save(DOC/'controls.json', controls)
    source_meta = m.metadata(m.STORE)
    original = m.original_lock()
    original_bytes = sum(r['bytes'] for r in source_meta)
    review = dict(protocol='science-worker-db-snapshot-review-v1', validated=True,
        sourcePin=m.pin(SOURCE), launcherPin=m.pin(PS), controlsPin=controls_pin, testPin=m.pin(TEST),
        freezerPin=m.pin(__file__), sourceSnapshots=copies, nativeInterpreterPin=m.pin(m.NATIVE_EXE),
        productionSnapshotPerformed=False, currentSourceMetadataOnly=source_meta, currentOriginalLogicalBytes=original_bytes,
        projectedRawAndWorkingLogicalBytes=2*original_bytes, maximumCopyLogicalBytes=m.LIMIT,
        DReserveBytes=m.D_RESERVE, snapshotReceiptMaximumBytes=m.REPORT_LIMIT,
        originalFirstPassPin=m.pin(m.FIRST), originalCanonicalLockPin=original['pin'],
        DFreeAtReviewBytes=m.free(m.OWNER), freshUUIDSiblingRequired=True, originalSQLDriverImports=0,
        noPaidRestartAuthorization=True, noFinancialReleaseAuthorization=True, proxyProvenanceEstablished=False,
        missing=[{'index':761,'arm':'F','officialId':'chb-a1d98f28-8387-bcd5-e2f6-ac0aa9db4b9b'},
                 {'index':771,'arm':'F','officialId':'chb-c9533024-6de9-6165-26c2-f34546631d67'},
                 {'index':775,'arm':'F','officialId':'chb-227460ce-f5ca-01e7-f8a8-cbbee7158e2a'}],
        missingWorkerMembership='Unknown until exact taskId/unit/trace query on working copies; no worker0 guess.',
        sourceSHAProcedure='All12 share-read/deny-write/delete handles, before SHA, 24 write+Flush+readback, source after SHA+identity, fresh actors again, finally close.',
        failureProcedure='Save invalid F evidence, preserve owned partial sibling; no original rename/delete or automatic retry.',
        subsequentReader='Only reviewed copied databases: raw immutable api.base_url unique origin, or working WAL-aware exact three tasks. No API-key columns or original SQLite.')
    review_pin = save(DOC/'review.json', review)
    commands = f"""$ErrorActionPreference='Stop'
$taskReview='{review_pin['path']}'
$taskReviewSha='{review_pin['sha256']}'
$taskScript='{PS}'
& $taskScript -Mode gate -Review $taskReview -ReviewSha $taskReviewSha -Receipt '{ROOT / 'docs/repair-2026-10-08/science-db-snapshots/root-gate-1.json'}'
# Only after Root source review and successful fresh Gate:
& $taskScript -Mode snapshot -Review $taskReview -ReviewSha $taskReviewSha -Receipt '{ROOT / 'docs/repair-2026-10-08/science-db-snapshots/root-snapshot-1.json'}'
"""
    command_pin = save(DOC/'root-commands.ps1.txt', commands.encode('utf-8'))
    md = f"""已完成 F 盘自建原生控制，4 项通过、0 项失败，子进程退出 0。未执行 D 盘生产 Gate 或复制，未打开原 SQLite；模型、评分、锁操作均为 0。

原 12 个普通文件当前合计 {original_bytes:,} bytes；raw12 与 working12 两份真实字节副本预计 {2*original_bytes:,} bytes，硬限制 512 MiB，生产阶段每次复制前实时保留 D 盘 1 GiB。snapshot 仅写本 thread owner 下独立 fresh UUID sibling；F 收据不超过 300 KiB。Gate 只查元数据、确切 5 PID / 4 个记录端口及原 canonical lock Pin，不复制，也不打开原数据库。

复制前同时取得 12 个 Windows GENERIC_READ / FILE_SHARE_READ 句柄，拒绝写入和删除共享；每个原件读前/读后 SHA 与文件身份一致，24 个新文件分别 CREATE_NEW、真实 FlushFileBuffers、关闭后读回 SHA。任何失败保留所属 partial、保存 invalid，不修改原件，不自动重试。

控制含实际写入/删除 WinError32、真实 F junction 拒绝与复制第三个文件后故障保留。fixture 的进程守卫明确是替身，不证明生产 5 PID 已关闭；没有断电模拟。源码、控制、日志与成功 native receipt 均绑定在 review.json（SHA {review_pin['sha256']}）。具体 Root 命令见 root-commands.ps1.txt（SHA {command_pin['sha256']}），只能另行使用 fresh 收据路径，不能把这个准备件当已复制证书。

761、771、775 均为 ChemBench F 缺少 published 记录，worker 归属仍未知；禁止借相邻 U 记录默认 worker0。后续仅在副本读取 api.base_url 一列与三个精确 taskId/trace。共享 proxy 须由副本唯一 localhost origin 与独立 Pin 建立，不能沿用猜测端口；本工具未建立其来源。原 1220 分母、789 原 candidate/acceptance、4 笔旧未知费用和 canonical 锁均保持原态，本收据不授权模型、计分或财务释放。
"""
    md_pin = save(DOC/'review.md', md.encode('utf-8'))
    for p in source_pins:
        m.verify(p)
    print(json.dumps({'review':review_pin,'controls':controls_pin,'report':md_pin,'rootCommands':command_pin}))

if __name__ == '__main__':
    main()
