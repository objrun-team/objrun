"""Read fixed-candidate preparation and source Pins; do not run the TS entry."""
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUN = 'repair-2026-10-08T18-32-57-118Z'
ENTRY = ROOT / '.scratch/root-preserved-science-regrade.ts'
PREP = ROOT / 'docs/repair-2026-10-08/preserved-science-regrade-c357edbf-29ae-4676-9456-a5fdd40e7315/prepare.json'
ENTRY_SHA = '159f38df62257e98b3f470b7127fca815f78926f5d848b15819a12110e397652'
PREP_SHA = '59615aaff32279f41b7e9a71ecd348d4b2d4bee8680bc61e071bd1d3768ed09b'

def sha(raw):
    return hashlib.sha256(raw).hexdigest()

def pin(path):
    path = Path(path)
    assert path.is_file() and not path.is_symlink()
    raw = path.read_bytes()
    return dict(path=str(path), bytes=len(raw), sha256=sha(raw))

def verify(p):
    actual = pin(p['path'])
    assert actual['bytes'] == p['bytes'] and actual['sha256'] == p['sha256'], p['path']

def main():
    assert pin(ENTRY)['sha256'] == ENTRY_SHA and pin(PREP)['sha256'] == PREP_SHA
    p = json.loads(PREP.read_text(encoding='utf-8'))
    assert p['protocol'] == 'preserved-science-fixed-candidates-v1' and p['runId'] == RUN
    assert p['modelCalls'] == p['graderCalls'] == 0 and p['originalFilesModified'] is False
    verify(p['entry'])
    original = p['original']
    for name in ('manifest', 'progress'):
        verify(original[name])
    manifest = json.loads(Path(original['manifest']['path']).read_text(encoding='utf-8'))
    plan = manifest['taskSchedule']
    assert len(plan) == 1220 and len(original['rows']) == 789
    seen, tuples = set(), set()
    group_rows = {}
    for row in original['rows']:
        verify(row['inputPin'])
        r = json.loads(Path(row['inputPin']['path']).read_text(encoding='utf-8'))
        i = row['index']
        assert i not in seen and 0 <= i < len(plan)
        seen.add(i)
        for field in ('index', 'benchmark', 'arm', 'replica', 'officialId', 'taskId', 'candidateHow', 'candidateSha256', 'promptSha256', 'traceSha256'):
            assert r[field] == row[field], (i, field)
        for field in ('index', 'benchmark', 'arm', 'replica', 'officialId'):
            assert r[field] == plan[i][field], (i, field)
        assert sha(r['answer'].encode('utf-8')) == r['candidateSha256']
        assert r['generationValid'] is True and r['generationClassification']['valid'] is True
        assert r['acceptance']['valid'] is False and r['acceptance']['outcome'] == 'pending_after_all_generation'
        key = '/'.join(map(str, (r['benchmark'], r['arm'], r['replica'])))
        tup = key + '/' + r['officialId']
        assert tup not in tuples
        tuples.add(tup)
        group_rows.setdefault(key, []).append(r['officialId'])
    groups = []
    for g in original['groups']:
        required = sorted(t['officialId'] for t in plan if '/'.join(map(str, (t['benchmark'], t['arm'], t['replica']))) == g['key'])
        retained = sorted(group_rows[g['key']])
        assert required == g['requiredOfficialIds'] and retained == g['retainedOfficialIds']
        assert g['originalKeysetComplete'] == (required == retained)
        assert g['planned'] == len(required) and g['retained'] == len(retained)
        groups.append({k:g[k] for k in ('key', 'planned', 'retained', 'originalKeysetComplete')})
    assert len(p['source']['sources']) == 81
    verify(p['source']['recipe'])
    for s in p['source']['sources']:
        verify(s)
    assert pin(ENTRY)['sha256'] == ENTRY_SHA and pin(PREP)['sha256'] == PREP_SHA
    result = dict(protocol='preserved-science-regrade-independent-static-review-v1', validated=True,
        reviewScope='static source and exact prepared candidate/group/81 source Pins',
        entry=pin(ENTRY), prepare=pin(PREP), reviewer=pin(__file__), verifiedTaskPins=789,
        verifiedExecutionSourcePins=81, plannedTaskRuns=1220, groups=groups,
        missingPublishedIndexesWithin0To791=sorted(set(range(792))-seen),
        modelCalls=0, graderCalls=0, entryExecuted=False, originalFilesModified=False,
        originalCampaignCompleted=False, full1220ScoreCertificateValid=False,
        actualScoreAuditPerformed=False, concreteBlockingFindingInScope=None,
        limitations=['Financial raw audit is the Root actual 4722 certificate; not rerun here.',
                     'Actual freshness of owned proof must be checked at execution, TTL 5 minutes.',
                     'Proxy cc799 prior observation lacks original DB Pins; this is no financial release proof.',
                     'Only complete AIME/CMT keysets can become eligible, after actual grading and independent group audit.',
                     'A reviewed preparation is trusted by its explicit SHA; this script does not authorize a modified preparation.'])
    output = ROOT / 'docs/repair-2026-10-08/preserved-science-regrade-independent-static-review.json'
    raw = (json.dumps(result, ensure_ascii=False, indent=2)+'\n').encode('utf-8')
    with output.open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    assert output.read_bytes() == raw
    print(json.dumps(pin(output)))

if __name__ == '__main__':
    main()
