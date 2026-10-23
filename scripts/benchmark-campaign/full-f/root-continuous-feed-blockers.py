"""One-shot immutable supply inventory. No model or runtime actions."""
import collections
import datetime
import hashlib
import json
from pathlib import Path

home = Path(__file__).resolve().parents[3] / 'docs/repair-2026-10-10/full-f-rerun'

def read(path):
    return json.loads(path.read_bytes())

def pin(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}

now = datetime.datetime.now(datetime.timezone.utc)
owner = read(home / 'skillsbench/event-ready-scheduler-owner.json')
sb_path = Path(owner['folder']) / 'pending-interface-inventory.json'
tb_path = home / 'terminal-bench/continuous-producer-inventory.json'
sb, tb = read(sb_path), read(tb_path)
live = read(home / 'root-continuous-feed-live-latest.json')
rows = {
    'skillsbench': [{'taskId': r['taskId'], 'reason': r['reason']} for r in sb['unscored']],
    'terminal-bench': [{k: r.get(k) for k in ('taskId', 'completed', 'active', 'phase', 'paidAttempts', 'blocked', 'privateInterfaceBlock')} for r in tb['rows'] if not r['completed']],
}
result = {
    'atUtc': now.isoformat(), 'modelCalls': 0, 'runtimeMutations': 0,
    'sourceObservations': {'skillsbench': pin(sb_path), 'terminal-bench': pin(tb_path)},
    'sourceSnapshots': {'skillsbench': sb, 'terminal-bench': tb},
    'liveEvidencePin': live['immutableReceiptPin'],
    'actualFormal': live['actualFormal'], 'actualFormalTotal': live['actualFormalTotal'],
    'rows': rows,
    'reasonCounts': {b: dict(collections.Counter(r.get('reason') or r.get('blocked') or ('active' if r.get('active') else r.get('phase') or 'unclassified') for r in items)) for b, items in rows.items()},
    'acceptancePassed': False,
    'remainingAcceptance': ['cached environment must continuously produce private qualification', 'post-repair natural formal closure followed by automatic next formal admission', 'owner handoff acknowledgement'],
}
out = home / 'root-continuous-feed-blockers' / (now.strftime('%Y%m%dT%H%M%S%fZ') + '.json')
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'atUtc': result['atUtc'], 'pin': pin(out), 'reasonCounts': result['reasonCounts'], 'actualFormal': result['actualFormal']}))
