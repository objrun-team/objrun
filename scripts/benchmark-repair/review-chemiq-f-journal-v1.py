"""Freeze the already-executed zero-network controls and new ChemIQ source. No experiment is run."""
from pathlib import Path
import hashlib
import json
import os
import re

ROOT = Path(__file__).resolve().parents[2]
HOME = ROOT / 'docs/repair-2026-10-08/chemiq-f-journal-implementation-v1'
FIXTURE = ROOT / '.scratch/chemiq-f-journal-tests/0f85bbad-e0cd-4815-b0bf-bffa3af7a70c'
CONTROL = HOME / 'controls-source-archive-final'
PEER_RECIPE = ROOT / 'docs/repair-2026-10-08/jpg-D-journal-preparations/repair-2026-10-09T06-57-26-283Z/recipe.json'
NAMES = ['chemiq-f-journal-campaign.ts', 'chemiq-f-journal-contract.ts', 'chemiq-f-paid-admission-v1.ts', 'chemiq-f-owned.ts',
         'chemiq-f-grading-recorder.ts', 'chemiq-f-model-witness.ts', 'audit-chemiq-f-journal.ts']

def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()

def pin(path):
    p = Path(path).resolve()
    return {'path': str(p), 'bytes': p.stat().st_size, 'sha256': digest(p)}

def write(path, value):
    p = Path(path); p.parent.mkdir(parents=True, exist_ok=True)
    raw = ((json.dumps(value, ensure_ascii=False, indent=2) + '\n') if not isinstance(value, str) else value).encode('utf-8')
    with p.open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    assert p.read_bytes() == raw
    return pin(p)

def text(path):
    raw = Path(path).read_bytes()
    return raw.decode('utf-16') if raw[:2] in (b'\xff\xfe', b'\xfe\xff') else raw.decode('utf-8-sig')

boundary = json.loads((FIXTURE / 'source-and-boundary.json').read_bytes())
stdout, stderr = text(CONTROL / 'stdout.txt'), text(CONTROL / 'stderr.txt')
assert re.search(r'\b20 pass\b', stderr) and re.search(r'\b0 fail\b', stderr) and '124 expect() calls' in stderr
assert str(FIXTURE).lower() in stdout.lower()
for p in boundary['currentSourcePins'] + boundary['protected81Before']:
    assert pin(p['path']) == p, p['path']
old_pin = pin(ROOT / 'docs/repair-2026-10-08/campaigns/repair-2026-10-08T18-32-57-118Z/source.json')
old = json.loads(Path(old_pin['path']).read_bytes())
protected = old['files'] + old['repairFiles']
assert len(protected) == 81
for p in protected:
    got = pin(ROOT / p['path'])
    assert got['bytes'] == p['bytes'] and got['sha256'] == p['sha256'], p['path']
peer = json.loads(PEER_RECIPE.read_bytes()); assert len(peer['sourcePins']) == 95
for p in peer['sourcePins']:
    assert pin(p['path']) == p
own_paths = [ROOT / 'scripts/benchmark-repair' / n for n in NAMES] + [ROOT / 'test/chemiq-f-journal-contract.test.ts']
own = [pin(p) for p in own_paths]
snapshots = []
for p in own_paths:
    target = HOME / 'source-snapshots' / p.name
    target.parent.mkdir(parents=True, exist_ok=True)
    raw = p.read_bytes()
    with target.open('xb') as f:
        f.write(raw); f.flush(); os.fsync(f.fileno())
    assert target.read_bytes() == raw and digest(target) == digest(p)
    snapshots.append({'original': pin(p), 'snapshot': pin(target)})

frozen_path = FIXTURE / 'source-archive/metadata/frozen-source.json'
frozen = json.loads(frozen_path.read_bytes())
source_path = FIXTURE / 'source-archive/metadata/source.json'
source = json.loads(source_path.read_bytes())
archive_pin = pin(frozen['archive'])
assert archive_pin['sha256'] == frozen['archiveSha256'] and archive_pin['bytes'] == frozen['archiveBytes']
assert frozen['sourceFiles'] == 109 and len(frozen['dependencyFiles']) == 4100 and frozen['archiveFsyncReturned'] is True
for p in source['files'] + source['repairFiles'] + frozen['dependencyFiles']:
    got = pin(ROOT / p['path']); assert got['sha256'] == p['sha256'] and got['bytes'] == p['bytes']
readiness = json.loads((ROOT / 'docs/repair-2026-10-08/chemiq-f-formal-readiness-v2-900s/readiness.json').read_bytes())
pilot = readiness['minimumRepresentativeFPilot']['taskRecords']
assert len(pilot) == 16
controls_pin = write(HOME / 'controls.json', {'protocol': 'chemiq-f-zero-network-controls-v1', 'validated': True, 'childExitObserved': 0,
    'sourcePins': own, 'pass': 20, 'fail': 0, 'assertions': 124, 'stdoutPin': pin(CONTROL / 'stdout.txt'), 'stderrPin': pin(CONTROL / 'stderr.txt'),
    'fixtureRoot': str(FIXTURE), 'boundaryPin': pin(FIXTURE / 'source-and-boundary.json'), 'actualNativeSourceFreeze': {'archivePin': archive_pin,
        'sourcePin': pin(source_path), 'frozenPin': pin(frozen_path), 'transcriptPin': pin(FIXTURE / 'source-archive/native-transcript.json'), 'sourceFiles': 109, 'dependencyFiles': 4100},
    'externalModelCalls': 0, 'realProviderRequests': 0, 'dockerCalls': 0, 'productionLockTaken': False, 'httpServersStarted': 0,
    'providerAttemptedSemantics': 'Only synthetic in-memory transport; not a real provider invocation.', 'formalPaidReady': False,
    'historicalDraftLogs': [{'directory': str(HOME / n), 'stdoutPin': pin(HOME / n / 'stdout.txt'), 'stderrPin': pin(HOME / n / 'stderr.txt')} for n in ['controls-first', 'controls-second', 'controls-third', 'controls-final', 'controls-frozen']],
    'limits': ['First draft13pass4fail and second14pass3fail remain unchanged. Later17/18/19 green logs are tied to their own recorded draft source Pins; not auto-upgraded to this final source.',
               'Earlier draft source bytes were not archived at each draft edit; final20 source bytes are archived now.',
               'Real cold grader/model engine/owned PID-port closure and a real-provider full closing chain remain unexecuted.']})
peer_module = next(p for p in peer['sourcePins'] if p['path'].endswith('jpg-D-paid-resource-admission-v1.ts'))
seed_pin = write(HOME / 'resource-seed-template.json', {'workers': 4, 'headroomCny': '30', 'balance': None, 'prices': None, 'runtimeGate': None,
    'requestedNewEnvelopeCny': None, 'capUsd': None, 'priorCampaignCostUpperBoundUsd': None,
    'financialBoundary': {'acknowledgementPin': pin(ROOT / 'docs/repair-2026-10-08/scientific-financial-releases/repair-2026-10-08T18-32-57-118Z-root-v1/release-ack.json'),
                          'originalLockArchivePin': pin(ROOT / 'docs/repair-2026-10-08/scientific-financial-releases/repair-2026-10-08T18-32-57-118Z-root-v1/root-original-lock-bytes.json')},
    'jpgDScanner': {'module': peer_module, 'executionPins': peer['sourcePins'], 'exportName': 'scanJpgDRegistries'},
    'templateOnly': True, 'formalPaidReady': False, 'providerForwardingEnabled': False})
pending = [
    'Root must review the final source and run a genuine cold environment/model-engine/HTTP grading gate before any real provider request; no native lifecycle or Docker boundary was probed by these controls.',
    'Root must supply a fresh <=30min GET-only CNY balance after actual recharge, <=24h official price Pin, requested CNY envelope, USD reporting guard and exact verified prior. CNY30 headroom and original4 unknown8.39218 remain reserved separately.',
    'The new JPG D scanner and its95 conservative execution Pins are frozen; unknown/unclosed cross-family scopes remain blockers. A future new TB paid-family scanner must be coordinated before treating this as a universal all-family registry.',
    'The legacy USD prior baseline excludes the old TB nginx$0.019480980 pilot; fresh CNY balance already reflects actual posted charges. The USD report is not an invoice or an exchange-rate calculation.',
    'The16 selected tasks have old same-source positive controls, but a fresh typed HTTP wire/runtime gate still must be produced. New34 extension/reference and204HTTP controls are not silently injected into the current0d/ffda original private profile.',
    'Full816 requires a separate explicit user confirmation and a reviewed effective private extension/profile+816 coverage graph. Root new34 results include26 PubChem-backed names and8 Root-constructed names; they are not all database-returned names.',
    'All new provider pending/unknown must close; only score-complete or an exactly budget-only financial abort can release this fresh canonical nonce. Any other invalid source/raw/owned/audit condition retains the lock.',
    'The private shared grader stays live and is re-audited, not removed as an owned model worker. Host PID/port absence is a later actual observation; it is not certified by these pure frame tests.',
    'FreshMachine-per-task and cycleMaxUnits12 define a new F900 environment; legacy0731/0929 complete runtime/model checkpoint equivalence is not certified.',
    'Frozen cash count() remains O(N) per call; metadata256MiB and JSON128MiB limits remain. Full816/900,24h hot price TTL and60s final-certificate freshness need a separate actual resource/performance review, not extrapolation from20 local tests.'
]
review = {'protocol': 'chemiq-f-journal-implementation-review-v1', 'family': 'chemiq-f-journal-v1', 'validated': True, 'implementationFrozen': True,
    'formalPaidReady': False, 'whole816Executed': False, 'trial16Executed': False, 'realModelCalls': 0,
    'taskScope': {'scopePin': pin(ROOT / 'docs/repair-2026-10-08/chemiq-f-formal-readiness-v1/task-scope.json'),
                  'readiness900Pin': pin(ROOT / 'docs/repair-2026-10-08/chemiq-f-formal-readiness-v2-900s/readiness.json'),
                  'originalDenominator': 816, 'trialCount': 16, 'arm': 'F', 'solveSeconds': 900, 'minimumDifferentTasks': 10,
                  'categories': 8, 'strata': 14, 'gradingMethods': 5, 'pilotOfficialIds': [r['officialId'] for r in pilot]},
    'settings': {'model': 'deepseek-flash', 'temperature': 0, 'seed': 42, 'maxTokens': 8192, 'reasoningEffort': 'none', 'search': False,
                 'checks': 5, 'explicitChecksAreAllPhysicalG': False, 'maxBranches': 4, 'maxDeadSiblings': 100000, 'readable': False, 'reuse': 'text', 'freshMachinePerTask': True, 'cycleMaxUnits': 12},
    'sourcePins': own, 'sourceSnapshots': snapshots, 'controlPin': controls_pin, 'sourceArchiverWitness': archive_pin,
    'protectedOriginal81SourcePin': old_pin, 'protectedOriginal81Unchanged': True, 'protectedOriginal81ExpectedCount': 81,
    'crossFamilyGraph': {'modulePin': peer_module, 'preparationRecipePin': pin(PEER_RECIPE), 'conservativeExecutionPins': peer['sourcePins'], 'verifiedCount': 95,
                        'scanner': 'async scanChemiqFPaidRuns(root,currentRun)->{family,closedRecordedCostUpperBoundUsd,inputPins,closedRunIds}', 'jpgDScanner': 'scanJpgDRegistries(samefields);await compatible'},
    'resourceSeedTemplatePin': seed_pin, 'producerPin': pin(__file__), 'remainingConditions': pending,
    'commands': {'zeroNetworkControlsAlreadyExecuted': "& 'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe' test 'test/chemiq-f-journal-contract.test.ts'",
                 'metadataOnlyPrepare': "& 'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe' 'scripts/benchmark-repair/chemiq-f-journal-campaign.ts' prepare pilot16",
                 'reviewedSeedPrepare': "& 'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe' 'scripts/benchmark-repair/chemiq-f-journal-campaign.ts' prepare pilot16 '<completed-resource-seed.json>'",
                 'notExecutedPaidRun': "& 'C:/Users/y1252/AppData/Roaming/npm/node_modules/bun/bin/bun.exe' 'scripts/benchmark-repair/chemiq-f-journal-campaign.ts' run '<reviewed-recipe.json>'"}}
review_pin = write(HOME / 'review.json', review)
md = '# ChemIQ 独立 F900 入口\n\n已完成七个独立执行源及本地20项控制/124断言，实际native子进程退出0。控制未调用真实模型、HTTP服务、Docker或生产锁；原科学81个执行文件逐SHA未变。复用冻结journal、CNY shadow、proxy、固定候选及官方判卷模块。\n\n'
md += '预选16个不同官方题，按原816顺序、8类/14 strata/5判法，单题900秒；模型deepseek-flash、temp0、seed42、8192输出、无search、显式verify5、branch4、K100000。verify5不是全部物理G；宿主记录parsed/correct、runtime自动G及最后独立验收原始响应。whole816仍需未来用户专项确认。\n\n'
md += '先原始request gzip/start行/fsync、现金峰价预留，再真实forward；晚回与poison保留实际响应和未知责任。模型请求封口后drain、停止各自冷engine，按原finalCandidate只选限时内提交，固定全组候选后统一验收。stored-only审计重验trace与新owned数据库、完整journal导出/费用/模型/判卷wire、source和真实PID/port记录；不打开任何旧SQLite。\n\n'
md += '跨family使用同canonical wx且只释放自己的nonce。已闭合旧科学74.31931532400054 USD加一次，旧4未知8.39218 CNY不settle；JPG F/D及本family闭合费用分别按真实typed证书计账。USD是原峰价估算报告，与CNY cash独立。旧TB单题USD不在legacy prior基础中，不能称全账户账单。\n\n'
md += f'实际F source-freeze控制生成{archive_pin["bytes"]:,}B ZIP、109 source/4100 dependency成员，SHA `{archive_pin["sha256"]}`，flush/fsync/读回已过。只绑定公开执行依赖，不包含题库答案、worker私有配置、真实凭据或其他benchmark任务日志。正式环境cold和真实nonce关闭仍未执行，formalPaidReady=false。\n\n'
md += '准备命令仅创建metadata，不能触发模型。`resource-seed-template.json` 的余额、价格、cold gate、envelope/cap/prior字段故意未填；Root另填实际Pin后复核。当前gate仍绑定旧stand0d/provenanceffda；新34补证及参考extension需要另明确effective私有配置，不能当已接入现服务。\n\n'
md += '剩余条件：\n\n' + '\n'.join(f'- {x}' for x in pending) + '\n\n'
md += f'最终控制：[{controls_pin["path"]}]({controls_pin["path"].replace(chr(92), "/")})。源码及历史红/绿日志均原态保留；原draft每步源码bytes未全部归档，最终20项源已按SHA逐文件归档。\n\n复核：[review.json]({review_pin["path"].replace(chr(92), "/")})。\n'
md_pin = write(HOME / 'README.md', md)
for p in own + boundary['protected81Before'] + peer['sourcePins']:
    assert pin(p['path']) == p
print(json.dumps({'reviewPin': review_pin, 'readmePin': md_pin, 'controlsPin': controls_pin, 'sourcePins': own, 'modelCalls': 0}, ensure_ascii=False))
