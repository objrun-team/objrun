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
TEST = ROOT / 'test/benchmarks/science_worker_db_snapshot_test.py'
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
    md = f"""Self-created native controls on drive F are complete: 4 passed, 0 failed, subprocess exit 0. No production gate or copying on drive D was executed, and original SQLite was not opened; model, grading, and lock operations are all 0.

The original 12 regular files currently total {original_bytes:,} bytes; actual byte copies raw12 and working12 are expected to total {2*original_bytes:,} bytes. The hard limit is 512 MiB, and production must preserve 1 GiB of free space on drive D, checked immediately before each copy. Snapshots are written only to an independent fresh UUID sibling under this thread owner; the F receipt is at most 300 KiB. The gate checks only metadata, the exact 5 PIDs / 4 recorded ports, and the original canonical lock pin; it neither copies nor opens original databases.

Before copying, simultaneously acquire 12 Windows GENERIC_READ / FILE_SHARE_READ handles, denying write and delete sharing. Each original's SHA and file identity must match before and after reading. Each of the 24 new files uses CREATE_NEW, actual FlushFileBuffers, and a SHA reread after closing. On any failure, retain the owned partial files and save invalid; do not modify originals or retry automatically.

Controls include actual write/delete WinError32, rejection of a real F junction, and preservation after a fault following the third copied file. The fixture process guard is explicitly a substitute, not proof that the 5 production PIDs have closed; no power-loss simulation was performed. Source, controls, logs, and the successful native receipt are bound in review.json (SHA {review_pin['sha256']}). Exact Root commands are in root-commands.ps1.txt (SHA {command_pin['sha256']}); they must run separately using fresh receipt paths. This preparation artifact is not a certificate of completed copying.

761, 771, and 775 are all ChemBench F tasks missing published records, and worker ownership remains unknown; do not assume worker0 from adjacent U records. Subsequent reads on copies are limited to the api.base_url column and three exact taskId/trace values. The shared proxy must be established from a unique localhost origin in the copies and an independent pin, not a guessed port; this tool has not established its provenance. The original 1220 denominator, 789 original candidate/acceptance records, 4 earlier unknown costs, and canonical lock all remain unchanged. This receipt authorizes no model calls, scoring, or financial release.
"""
    md_pin = save(DOC/'review.md', md.encode('utf-8'))
    for p in source_pins:
        m.verify(p)
    print(json.dumps({'review':review_pin,'controls':controls_pin,'report':md_pin,'rootCommands':command_pin}))

if __name__ == '__main__':
    main()
