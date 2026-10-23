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
md = '''# SB / TB 停止接续记录

2026-10-12，人类明确取消本轮继续运行及并发验收，要求收尾后停止。

已停止两 Bench 的供题、正式派发、准备/正式执行进程及本任务容器；原 owner 已核实租约清零。共享 broker 在活跃请求、排队请求和资源均为 0 后按原 PID/出生时间/源码身份核验停止。bench-f、skillsbench-f、terminal-bench-f 全部 PAUSED，CB/CQ 保持 PAUSED，其他已取消 Bench 不恢复。

原成绩保持 SB 35/87 有效（30 通过、5 错），TB 25/89 有效（25 通过）。原候选、评分、源版本、尝试、缓存和费用记录保留。此前并发修复未完成全部真实验收，不宣称达到 16 正式或完成交接验收。

费用未决：Exoplanet 最后 1 请求缺 finish，已知实际 USD 0.131657385；0.1704684 USD 是该未知请求的预留，不是实际费用。原 journal/cash、原 canonical 记录保留，未伪造正常现金闭合或账单。新对话须先核查原停止状态、费用补证及固定版本，再按新授权接续；有效成绩不重跑。

完整证据与两 owner 接续包的 SHA 位于 [ROOT-STOPPED-HANDOFF-20261012.json](ROOT-STOPPED-HANDOFF-20261012.json)。TB 原包编码附有 UTF-8 接续副本，原文件未改写。
'''
(home / 'ROOT-STOPPED-HANDOFF-20261012.md').write_text(md, encoding='utf-8')
print(json.dumps({'stopped': True, 'actualFormal': report['actualFormal'], 'actualPreparation': 0, 'automations': statuses, 'summaryPath': str(home / 'ROOT-STOPPED-HANDOFF-20261012.md'), 'cashFinancialResolved': False}))
