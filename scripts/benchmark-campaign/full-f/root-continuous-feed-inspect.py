"""One-shot, zero-model acceptance evidence. Never schedules or changes actors."""
import hashlib
import json
import subprocess
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
HOME = ROOT / 'docs/repair-2026-10-10/full-f-rerun'

def read(path, default=None):
    try:
        return json.loads(Path(path).read_text(encoding='utf-8-sig'))
    except FileNotFoundError:
        return default

def pin(path):
    p = Path(path)
    return {'path': str(p), 'sha256': hashlib.sha256(p.read_bytes()).hexdigest()}

now = datetime.now(timezone.utc)
# Raw command lines stay inside this process; receipts contain only hashes and entry names.
cmd = "Get-CimInstance Win32_Process | Where-Object {$_.Name -in @('bun.exe','python.exe') -and $_.CommandLine -like '*repair-2026-10-10*full-f*'} | Select-Object ProcessId,ParentProcessId,@{n='birth';e={$_.CreationDate.ToUniversalTime().ToString('o')}},CommandLine | ConvertTo-Json -Depth 3 -Compress"
r = subprocess.run(['powershell', '-NoProfile', '-Command', cmd], capture_output=True, text=True, check=True)
rows = json.loads(r.stdout) if r.stdout.strip() else []
if isinstance(rows, dict):
    rows = [rows]
processes = {}
task_ids = {}
for bench in ('skillsbench', 'terminal-bench'):
    manifest = read(HOME / bench / 'manifest.json', {})
    task_ids[bench] = manifest.get('taskIds') or [x['taskId'] for x in manifest.get('taskSchedule', [])]
for row in rows:
    command = row['CommandLine'] or ''
    entries = [x.strip('"\'') for x in command.split() if x.rstrip('"\'').endswith(('.ts', '.py'))]
    bench = next((b for b in task_ids if any('/' + b + '/' in s.replace('\\', '/') for s in entries)), None)
    tasks = [task for task in task_ids.get(bench, []) if re.search(r'(?<![\w-])' + re.escape(task) + r'(?![\w-])', command)]
    if not tasks and bench == 'terminal-bench':
        tasks = [task for task in task_ids[bench] if any(re.match(r'^(prepare|import|build|launch)-' + re.escape(task) + r'-producer(?:-|\.)', Path(e).name) for e in entries)]
    processes[row['ProcessId']] = {'pid': row['ProcessId'], 'parentPid': row['ParentProcessId'], 'birth': row['birth'], 'commandSha256': hashlib.sha256(command.encode()).hexdigest(), 'entries': entries, 'bench': bench, 'taskIds': tasks}

# Immutable scheduler registrations bind shortened entry names (e.g. sanitize)
# to official task IDs. Descendants inherit this binding, not an inferred score.
tb_state = read(HOME / 'terminal-bench/event-scheduler/process.json', {})
for job_id, state in tb_state.get('jobs', {}).items():
    pid = state.get('childPid')
    if state.get('state') != 'running' or pid not in processes:
        continue
    reg = read(HOME / 'terminal-bench/event-registrations' / (job_id + '.json'), {})
    entry = reg.get('entryPin', {})
    path = Path(entry.get('path', ''))
    if path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry.get('sha256') and str(path) in processes[pid]['entries']:
        at = datetime.fromisoformat(state['atUtc'].replace('Z', '+00:00'))
        birth = datetime.fromisoformat(processes[pid]['birth'].replace('Z', '+00:00'))
        if abs((at - birth).total_seconds()) < 10:
            processes[pid]['taskIds'] = [state['taskId']]
            processes[pid]['registrationPin'] = pin(HOME / 'terminal-bench/event-registrations' / (job_id + '.json'))
for _ in range(len(processes)):
    changed = False
    for proc in processes.values():
        parent = processes.get(proc['parentPid'])
        if not proc['taskIds'] and parent and len(parent['taskIds']) == 1 and proc['bench'] == parent['bench']:
            proc['taskIds'] = parent['taskIds'][:]
            proc['inheritedTaskBindingFromPid'] = parent['pid']
            changed = True
    if not changed:
        break

health_path = HOME / 'broker/repair-2026-10-11T11-50-05-363Z/broker-status.json'
health = read(health_path)
resources = [{'pid': x.get('pid'), 'slug': x.get('slug')} for x in health.get('resourceSlots', [])]
formals = []
for lane in health.get('lanes', []):
    if lane.get('closed') is not False:
        continue
    output = Path(lane['output']) if lane.get('output') else None
    matches = [x for x in resources if x['slug'] == lane.get('slug') and x['pid'] in processes]
    # Binding requires the run ID in the live command, not just a Bench-wide lease.
    bound = []
    native_path = output / 'process.json' if output else None
    if native_path and not native_path.exists():
        native_path = output / 'parent-process.json'
    native = read(native_path, {}) if native_path else {}
    for x in matches:
        raw = next(row['CommandLine'] for row in rows if row['ProcessId'] == x['pid'])
        if lane.get('runId') and (lane['runId'] in raw or (output and str(output) in raw) or (native.get('pid') == x['pid'] and native.get('runId') == lane['runId'])):
            bound.append(processes[x['pid']])
    generations = set()
    cash_path = output / 'cash/cash-events.jsonl' if output else None
    if cash_path and cash_path.exists():
        for line in cash_path.read_bytes().splitlines():
            row = json.loads(line)
            data = row.get('data', {})
            if row.get('kind') == 'finish' and data.get('generationId'):
                generations.add(data['generationId'])
    formals.append({'bench': lane.get('slug'), 'runId': lane.get('runId'), 'dispatched': lane.get('dispatched'), 'uniqueGenerationIds': len(generations), 'nativeProcessPin': pin(native_path) if native_path and native_path.exists() else None, 'billedUsdSnapshot': lane.get('billedUsd'), 'unknownCountSnapshot': lane.get('unknownCount'), 'liveBoundProcesses': bound, 'certifiedLiveFormal': bool(bound and generations)})

actors = []
for proc in processes.values():
    if any('/skillsbench/' in s.replace('\\', '/') or '/terminal-bench/' in s.replace('\\', '/') for s in proc['entries']):
        actors.append({**proc, 'ownsResourceNow': any(x['pid'] == proc['pid'] for x in resources)})
ledger = read(HOME / 'official-valid-score-events-root.json', {})
events = ledger.get('events', []) if isinstance(ledger, dict) else ledger
rolling = {'skillsbench': 0, 'terminal-bench': 0}
for e in events:
    timestamp = e.get('completionAtUtc')
    if timestamp:
        at = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        if now - timedelta(hours=1) <= at <= now and e.get('bench') in rolling:
            rolling[e['bench']] += e.get('newValid', 0)
counts = {bench: sum(x['certifiedLiveFormal'] for x in formals if x['bench'] == bench) for bench in rolling}
formal_pids = {p['pid'] for f in formals for p in f['liveBoundProcesses']}
preparations = [a for a in actors if a['ownsResourceNow'] and a['pid'] not in formal_pids and len(a['taskIds']) == 1 and any('prepar' in e or 'cold' in e for e in a['entries'])]
receipt = {'atUtc': now.isoformat(), 'modelCalls': 0, 'executionMutations': 0, 'healthPin': pin(health_path), 'healthy': health.get('healthy'), 'stopReason': health.get('stopReason'), 'resources': resources, 'liveOwnActors': actors, 'openPaidLanes': formals, 'actualFormal': counts, 'actualFormalTotal': sum(counts.values()), 'resourceBoundPreparations': preparations, 'rollingOfficialValid': rolling, 'acceptancePassed': False, 'note': 'One-shot evidence only. Preparations, mock tests, and open lanes without a fresh bound live actor are not formal concurrency.'}
evidence = HOME / 'root-continuous-feed-live-evidence' / now.strftime('%Y%m%dT%H%M%S%fZ')
evidence.mkdir(parents=True)
safe_health = {key: health.get(key) for key in ('atUtc', 'pid', 'runId', 'healthy', 'stopReason', 'localMock', 'maxInFlight', 'perBenchLimits', 'availableResourceSlots')}
safe_health['resourceSlots'] = resources
safe_health['lanes'] = [{key: lane.get(key) for key in ('slug', 'runId', 'output', 'closed', 'dispatched', 'billedUsd', 'unknownCount')} for lane in health.get('lanes', [])]
safe_path = evidence / 'health-observed-safe.json'
safe_path.write_text(json.dumps(safe_health, indent=2), encoding='utf-8')
receipt['healthObservedSafeSnapshotPin'] = pin(safe_path)
receipt['healthPinIsObservationOfMutableOriginal'] = True
source_path = evidence / Path(__file__).name
source_path.write_bytes(Path(__file__).read_bytes())
receipt['inspectorSourceArchivePin'] = pin(source_path)
immutable_path = evidence / 'receipt.json'
immutable_path.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
receipt['immutableReceiptPin'] = pin(immutable_path)
out = HOME / 'root-continuous-feed-live-latest.json'
out.write_text(json.dumps(receipt, indent=2), encoding='utf-8')
with (HOME / 'root-continuous-feed-live-observations.jsonl').open('a', encoding='utf-8') as f:
    f.write(json.dumps(receipt) + '\n')
print(json.dumps({'atUtc': receipt['atUtc'], 'actualFormal': counts, 'total': sum(counts.values()), 'rolling': rolling, 'preparations': [{'pid': a['pid'], 'birth': a['birth'], 'bench': a['bench'], 'taskIds': a['taskIds']} for a in preparations], 'unboundResourcePids': [r['pid'] for r in resources if r['pid'] not in processes]}))
