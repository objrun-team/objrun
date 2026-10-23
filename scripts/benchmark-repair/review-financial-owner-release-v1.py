"""Static review closure only. Never import/run TS, raw gzip, native queries or locks."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT/'scripts/benchmark-repair/financial-interruption-release.ts'
DOC = ROOT/'docs/repair-2026-10-08'
REVIEW = DOC/'financial-release-readiness/final-v1/review.json'
SOURCE_SHA = '4f2f2aad2bcc0857b4cf73120bc48fb70b9632df408ed8f06c6b5ae5dfe2dd41'
REVIEW_SHA = '43b61559fbc952b1f2a8d9b3db6d69a9c79d24f4cbd306f5a81e7693af6771fc'

def pin(path):
    path = Path(path)
    raw = path.read_bytes()
    return dict(path=str(path),bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())

def verify(p):
    q = pin(p['path'])
    assert q['bytes'] == p['bytes'] and q['sha256'] == p['sha256']

def main():
    assert pin(SOURCE)['sha256'] == SOURCE_SHA and pin(REVIEW)['sha256'] == REVIEW_SHA
    r = json.loads(REVIEW.read_bytes())
    verify(r['sourcePin'])
    for key in ('nativeControlsPin','stdoutPin','stderrPin'):
        verify(r[key])
    for p in r['testPins']+r['originalScientificSourcePinsVerified']:
        verify(p)
    for pair in r['sourceSnapshots']:
        verify(pair['originalPin']); verify(pair['snapshotPin'])
    assert len(r['originalScientificSourcePinsVerified']) == 81
    assert r['actualPass'] == 14 and r['actualFail'] == 0 and r['actualAssertions'] == 64 and r['actualTestExitCode'] == 0
    assert r['ownedFixtureChildrenClosed'] and r['ownedFixturePortsClosed'] and not r['productionReleasePerformed']
    assert r['oldUnknownCarryNanoCny'] == '8392180000' and r['oldUnknownSettled'] is False
    manifest_path = DOC/'campaigns/repair-2026-10-08T18-32-57-118Z/manifest.json'
    manifest = json.loads(manifest_path.read_bytes())
    # Current original IDs are URI-safe; the literal release route set equals the encodeURIComponent set.
    from urllib.parse import quote
    assert all(quote(p['officialId'],safe="~!*'()-._") == p['officialId'] for p in manifest['taskSchedule'])
    reader_review = DOC/'science-db-snapshot-proxy-reader-routed-v2/review.json'
    report = dict(protocol='financial-owner-release-independent-static-review-v1',validated=True,
        sourcePin=pin(SOURCE),ownerReadinessPin=pin(REVIEW),reviewer=pin(__file__),
        nativeControlsPin=r['nativeControlsPin'],actualSourceBoundControls={'pass':14,'fail':0,'assertions':64,'native':10,'synthetic':4},
        protectedScienceSourcesVerified=81,readScope='source/current small metadata/previous F control evidence only',
        readerRoutedReviewPin=pin(reader_review),productionRawAuditRepeated=False,productionNativeQueries=0,
        originalSqliteOpened=False,modelCalls=0,graderCalls=0,lockOperations=0,
        findings=[],scopeConclusions=[
            'Explicit fixed RUN/canonical owner nonce/lock Pin; no automatic default release.',
            'Financial4722/indexcc1b are pinned, 23504 admissions/23503 real forward/last denial0 are required; exact3 fallback copies are checked without adding their fees again.',
            'Snapshot8134/raw12/source12 and four manifest exactroutes bind fifth port; full base_url paths may differ, origins/ports agree.',
            'Fresh exact5 PID/5 port native query must exit/close within10s; query failure, active/reused actor or listener refuse release.',
            'Release checks current financial/source/storage/nonce again, native lock descriptor identity, durable intent then exact unlink, and durable acknowledgement.',
            'Post-unlink acknowledgement failure retains typed failure with successorAdmissionPermitted:false; no boolean-only success.',
            'Original registry, sources and closing metadata never changed; original4 unknown8.39218CNY kept. FinancialOnly does not certify scores.'
        ],limitations=[
            'No production inspection/release/raw replay run by this reviewer; Root must run explicit source-pinned inspect then release.',
            'Fixture controls verify F private actors and locks, not production absence.',
            'Canonical unlink uses checked descriptor/path identity and fresh nonce under single-owner coordination; it is not a Windows transactional unlink against an adversarial concurrent host writer.',
            'Known CNY is a frozen price estimate, not an invoice or recharge confirmation.',
            'Owner readiness retains the historical pre-routed reader observation; current production reader proof must use routed-v2 separately pinned by Root.'
        ])
    raw = (json.dumps(report,ensure_ascii=False,indent=2)+'\n').encode()
    out = DOC/'financial-owner-release-independent-static-review.json'
    with out.open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    assert out.read_bytes() == raw and pin(SOURCE)['sha256'] == SOURCE_SHA and pin(REVIEW)['sha256'] == REVIEW_SHA
    print(json.dumps(pin(out)))

if __name__ == '__main__':
    main()
