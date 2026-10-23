"""Capture a stop checkpoint without restarting or scheduling anything."""
import datetime
import hashlib
import json
import tomllib
from pathlib import Path

home = Path(__file__).resolve().parents[3] / 'docs/repair-2026-10-10/full-f-rerun'
def read(path):
    return json.loads(path.read_bytes())
def pin(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
control = read(home / 'control.json')
health = read(Path(control['broker']['healthPath']))
automations = {}
for identity in ('bench-f', 'skillsbench-f', 'terminal-bench-f', 'chembench-f', 'chemiq-f'):
    p = Path('C:/Users/y1252/.codex/automations') / identity / 'automation.toml'
    a = tomllib.loads(p.read_text(encoding='utf-8-sig'))
    automations[identity] = {'status': a['status'], 'rrule': a['rrule']}
live = read(home / 'root-continuous-feed-live-latest.json')
report = {
    'atUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'humanRequest': 'Stop both Bench runs after preserving shutdown evidence; resume only in a new human-authorized conversation.',
    'priorConcurrencyAcceptanceCancelledByHuman': True,
    'automations': automations,
    'broker': {k: health.get(k) for k in ('pid', 'runId', 'atUtc', 'healthy', 'dispatchPaused', 'activeRequests', 'queuedRequests')},
    'openPaidLanes': [{k: row.get(k) for k in ('slug', 'runId', 'output', 'billedUsd', 'unknownCount', 'dispatched')} for row in health['lanes'] if not row['closed']],
    'heldResources': [{k: row.get(k) for k in ('slug', 'pid', 'kind', 'slots')} for row in health['resourceSlots']],
    'lastLiveEvidencePin': live['immutableReceiptPin'],
    'officialCompletionLedgerPin': pin(home / 'official-valid-score-events-root.json'),
    'complete': False,
    'note': 'A zero live-formal count alone is not a cash/resource closure certificate. Original owners are performing native shutdown. No score inferred from failed SDK acceptance; unknown retained.',
    'rootModelCalls': 0,
}
out = home / 'root-human-stop-checkpoints' / (datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.json')
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(report, indent=2) + '\n', encoding='utf-8')
print(json.dumps({'pin': pin(out), 'openPaidLanes': len(report['openPaidLanes']), 'heldResources': len(report['heldResources']), 'automations': {k:v['status'] for k,v in automations.items()}}))
