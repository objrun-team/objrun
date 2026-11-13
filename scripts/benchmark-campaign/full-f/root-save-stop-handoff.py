"""Save shutdown handoff after original owner receipts; no runtime actions."""
import datetime
import hashlib
import json
import tomllib
from pathlib import Path

home = Path(__file__).resolve().parents[3] / 'docs/repair-2026-10-10/full-f-rerun'
def pin(path):
    data = path.read_bytes()
    return {'path': str(path), 'bytes': len(data), 'sha256': hashlib.sha256(data).hexdigest()}
def read(path):
    return json.loads(path.read_bytes())
sb_latest = read(home / 'skillsbench/human-stop-closeout-latest.json')
sb_path = Path(sb_latest['resultPin']['path'])
assert pin(sb_path)['sha256'] == sb_latest['resultPin']['sha256']
sb = read(sb_path)
tb_path = home / 'terminal-bench/STOPPED-HANDOFF-20261012.json'
try:
    tb = read(tb_path)
    tb_encoding = 'utf-8'
except UnicodeDecodeError:
    tb = json.loads(tb_path.read_text(encoding='gb18030'))
    tb_encoding = 'gb18030'
assert sb['ownExecutionStopped'] and sb['ownRunningContainerCount'] == 0 and not sb['ownResources'] and not sb['ownLiveProcesses']
assert tb['newDispatchStopped'] and tb['uniqueSchedulerStopped'] and not tb['actualOwnRunningProcesses'] and not tb['ownResourceSlots'] and not tb['ownOpenPaidLanes'] and tb['actualAllRecordedOwnContainersAbsent']
broker_path = sorted((home / 'root-human-stop-broker').glob('*/stop-receipt.json'))[-1]
broker = read(broker_path)
assert broker['processAbsentVerified'] and broker['activeRequests'] == 0 and broker['queuedRequests'] == 0 and broker['resources'] == 0
statuses = {i: tomllib.loads((Path('C:/Users/y1252/.codex/automations') / i / 'automation.toml').read_text(encoding='utf-8-sig'))['status'] for i in ('bench-f','skillsbench-f','terminal-bench-f','chembench-f','chemiq-f')}
assert all(v == 'PAUSED' for v in statuses.values())
tb_copy = home / 'root-human-stop-TB-handoff-utf8.json'
tb_copy.write_text(json.dumps({'originalPin': pin(tb_path), 'originalEncoding': tb_encoding, 'unchangedParsedOwnerHandoff': tb}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
report = {
    'atUtc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'humanRequestedStopComplete': True, 'priorConcurrencyAcceptanceCancelled': True,
    'actualFormal': {'skillsbench': 0, 'terminal-bench': 0}, 'actualPreparation': 0,
    'brokerProcessStopped': True, 'brokerActiveRequests': 0, 'heldResources': 0,
    'automations': statuses, 'modelCallsByRootShutdown': 0,
    'originalOwnerPins': {'skillsbench': pin(sb_path), 'terminal-bench': pin(tb_path)},
    'terminalBenchUtf8SupplementPin': pin(tb_copy), 'brokerStopReceiptPin': pin(broker_path),
    'officialLedgerPin': pin(home / 'official-valid-score-events-root.json'),
    'officialEffective': {'skillsbench': 35, 'terminal-bench': 25},
    'cashFinancialResolved': False, 'normalCashReleaseClaimed': False,
    'remainingCash': {'taskId': 'exoplanet-detection-period', 'knownActualUsd': 0.131657385, 'unfinishedRequestCount': 1, 'reservationUsdNotActual': 0.1704684, 'originalJournalUnmodified': True, 'originalCanonicalRecordRetained': True},
    'resumption': 'New explicit human authorization in a new conversation. First audit original stopped owner/cash state and immutable source pins; do not reuse stale live broker metadata or repeat official valid tasks. No automatic resumption.',
}
(home / 'ROOT-STOPPED-HANDOFF-20261012.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
md = '''# SB / TB stop and continuation record

On 2026-10-12, the human explicitly canceled further execution and concurrency acceptance checks for this round, requesting shutdown after wrap-up.

Task supply, formal dispatch, preparation/formal execution processes, and task containers for both benchmarks have stopped; the original owners verified that leases are zero. The shared broker was stopped after active requests, queued requests, and resources all reached 0, with its original PID, birth time, and source identity verified. bench-f, skillsbench-f, and terminal-bench-f are all PAUSED; CB/CQ remain PAUSED, and other canceled benchmarks will not resume.

Original results remain valid for SB 35/87 (30 passes, 5 incorrect) and TB 25/89 (25 passes). Original candidates, grades, source versions, attempts, caches, and cost records are retained. The earlier concurrency repair did not complete all live acceptance checks; this record does not claim 16 formal runs or completed handoff acceptance.

Unresolved costs: the final Exoplanet request lacks a finish record; known actual cost is USD 0.131657385. USD 0.1704684 is the reservation for that unknown request, not actual cost. Original journal/cash and canonical records are retained; no normal cash closure or bill has been fabricated. A new conversation must first check the original stopped state, supplemental cost evidence, and pinned versions, then continue under new authorization; valid results must not be rerun.

Complete evidence and SHA hashes for both owners' continuation packages are in [ROOT-STOPPED-HANDOFF-20261012.json](ROOT-STOPPED-HANDOFF-20261012.json). A UTF-8 continuation copy accompanies the original TB package encoding; the original file was not rewritten.
'''
(home / 'ROOT-STOPPED-HANDOFF-20261012.md').write_text(md, encoding='utf-8')
print(json.dumps({'stopped': True, 'actualFormal': report['actualFormal'], 'actualPreparation': 0, 'automations': statuses, 'summaryPath': str(home / 'ROOT-STOPPED-HANDOFF-20261012.md'), 'cashFinancialResolved': False}))
