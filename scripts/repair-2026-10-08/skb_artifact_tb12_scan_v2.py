"""Own read-only replay of closed TB12 native ownership. Never executes Docker.

All databases must already be checkpointed. immutable=1 avoids writing even
reader marks into the neighboring family's SQLite shared-memory side files.
"""
import argparse
from contextlib import closing
from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import skb_artifact_task_v2 as task
import skb_artifact_native_identity_v2 as identity

FAMILY='terminal-bench-twelve-journal-v1'
OBSERVERS={
    '75830ef73ead41d1440ef43a0c748e306a6254d8ca43670ae87e232a94012c56':'tb12-v1/fresh_absence.py',
    '215551808470331435bef073defa33cc4b6510ec56c364b84b71d814f686b3c2':'tb12-v2/fresh_absence.py',
}


def demand(value,code):task.demand(value,'tb12_scan_'+code,'Neighboring paid ownership/raw graph is not independently closed')


def immutable(path):
    wal=Path(str(path)+'-wal')
    demand(not wal.exists() or wal.stat().st_size==0,'uncheckpointed_database')
    return sqlite3.connect(path.resolve().as_uri()+'?mode=ro&immutable=1',uri=True)


def scan(home):
    home=home.resolve();demand(home.parent==task.REPO/'docs/repair-2026-10-09/tb12-runs-v1','home')
    inputs={}
    def pin(p):
        value=task.pin(p);inputs[value['path']]=value;return value
    def read(p):return task.read_json(pin(p),16*1024**2)
    def reference(p):
        key=p['path'];old=inputs.get(key)
        if old is None:old=pin(key)
        demand(old['sha256']==p['sha256'] and ('bytes' not in p or old['bytes']==p['bytes']),'conflicting_pin')
        return old
    reg=read(home/'tb12-paid-resource-run.json');ad=task.read_json(reference(reg['admissionPin']))
    cert=task.read_json(reference(reg['closedPin']),16*1024**2);ack=task.read_json(reference(reg['releaseAckPin']))
    run=home.name;owned=ad['owned']
    demand(reg['protocol']=='tb12-paid-resource-run-v1' and reg['released'] is True and reg['family']==FAMILY,'registry')
    demand(ad['runId']==cert['runId']==ack['runId']==reg['runId']==run and ad['family']==cert['family']==ack['family']==FAMILY,'run_binding')
    demand(ack['protocol']=='tb12-paid-release-ack-v1' and ack['owned']==owned and cert['ownerNonce']==owned['ownerNonce']
        and ack['certificatePin']==reg['closedPin'] and ack['exactCanonicalOwnerRemoved'] is True,'owner_binding')
    entry=read(home/'entry-closed.json')
    demand(entry['runId']==run and entry['family']==FAMILY and entry['canonicalOwnerReleased'] is True
        and entry['certificatePin']==reg['closedPin'] and entry['originalUnknownCarrySettled'] is False,'entry_close')
    demand(ad['carryNanoCny']=='8392180000' and owned['sourceExecutionDigest']==hashlib.sha256(json.dumps(ad['sourcePins'],separators=(',',':'),ensure_ascii=False).encode()).hexdigest(),'source_digest')
    manifest_path=home/'source-snapshots/manifest.json'
    manifest_pin=next((p for p in cert['inputPins'] if Path(p['path'])==manifest_path),None)
    demand(manifest_pin is not None,'source_manifest_binding');manifest=task.read_json(reference(manifest_pin),16*1024**2)
    demand([p['originalPin'] for p in manifest['files']]==ad['sourcePins'],'source_manifest_order')
    source_map={p['originalPin']['path']:p for p in manifest['files']};snapshot_substitutions=[]
    def executed_reference(p):
        row=source_map.get(p['path'])
        if row is None or row['originalPin']!=p:return reference(p)
        current=task.pin(p['path'])
        if current==p:return reference(p)
        saved=row['snapshotPin'];demand(Path(saved['path']).parent==home/'source-snapshots' and saved['sha256']==p['sha256'] and saved['bytes']==p['bytes'],'executed_source')
        reference(saved);snapshot_substitutions.append({'originalPin':p,'executedSnapshotPin':saved});return saved
    for p in cert['inputPins']:executed_reference(p)
    for p in ad['sourcePins']:executed_reference(p)
    secret=task.read_json(reference(cert['secretScanPin']),16*1024**2)
    demand(secret['protocol']=='tb12-actual-export-secret-scan-v1' and secret['passed'] is True
        and secret['actualSecretValueCount']>0 and secret['secretValuesExcluded'] is True and secret['compressedBodiesExpanded'] is True,'secret_scan')
    for p in secret['scannedFiles']:reference(p)
    # Mutable paid registry snapshots were scanned before release. The exact
    # final registry/ack above are verified separately, never against old hashes.
    latest={};executables={};pids=set();ports=set();cids=set();command_count=0;actor_count=0
    def add(pid,at,executable):
        demand(type(pid) is int and pid>0,'pid');stamp=datetime.fromisoformat(at.replace('Z','+00:00'))
        latest[pid]=max(latest.get(pid,stamp),stamp);executables.setdefault(pid,set()).add(Path(executable).name.lower());pids.add(pid)
    closures=[]
    for p in sorted((home/'workers').glob('*/engine-close.json'))+list(home.glob('stand-process/stand-close.json')):
        q=read(p);demand(q['exitObserved'] is True and q['closeObserved'] is True and not(q.get('captureFaults') or q.get('faults')),'process_close')
        add(q['pid'],q['closedAtUtc'],q['argv'][0]);closures.append(inputs[str(p.resolve())])
        if q.get('port'):demand(0<q['port']<65536,'process_port');ports.add(q['port'])
    provider=read(home/'provider-native-close.json')
    demand(provider['runId']==run and provider['serverClosed'] is True and provider['pendingCount']==0,'provider_close')
    if provider['port']:demand(0<provider['port']<65536,'provider_port');ports.add(provider['port'])
    for p in (home/'stand-process/stand/grades').glob('*/broker/broker-receipt.json'):
        q=read(p);demand(q['threadClosed'] is True and q['socketClosed'] is True and 0<q['port']<65536,'broker_close');ports.add(q['port'])
    db_path=home/'stand-process/stand/owned-native.sqlite'
    if db_path.exists():
        pin(db_path)
        with closing(immutable(db_path)) as db:
            demand(db.execute('PRAGMA integrity_check').fetchone()[0]=='ok','database_integrity')
            commands={}
            for index,raw in db.execute('SELECT id,json FROM command ORDER BY id'):
                q=json.loads(raw);demand(q['index']==index and q['closeObserved'] is True and not q['timedOut'] and not q['overflow']
                    and not q['captureFaults'] and type(q['exitCode']) is int and q['argv'][1:3]==['--host','npipe:////./pipe/dockerDesktopLinuxEngine'],'command_close')
                for name in ('stdout','stderr'):
                    r=q[name];reference(r);demand(r['bytesObserved']==r['bytesStored']==Path(r['path']).stat().st_size,'pipe_complete')
                add(q['nativePid'],q['finishedAtUtc'],q['argv'][0]);commands[index]=q;command_count+=1
            for cid,role,name,image,closed,raw in db.execute('SELECT cid,role,name,image,closed,json FROM actor'):
                a=json.loads(raw);initial=a['initialState'];h=initial['HostConfig']
                demand(closed==1 and re.fullmatch('[0-9a-f]{64}',cid) and initial['Id']==cid and initial['Image']==image
                    and initial['Labels']['objrun.tb12.role']==role and initial['Name'].lstrip('/')==name,'actor_identity')
                demand(not h.get('Binds') and not h['Privileged'] and h['Memory']==2048*1024**2 and h['NanoCpus']==10**9 and h['PidMode']!='host','actor_namespace')
                if role.startswith('private-checker') or role=='untrusted-openssl-worker':demand(h['ReadonlyRootfs'] and h['CapDrop']==['ALL'],'private_namespace')
                rm,absent=a['removalReceipt'],a['absenceReceipt']
                demand(commands.get(rm['index'])==rm and commands.get(absent['index'])==absent and rm['exitCode']==0 and absent['exitCode']!=0,'actor_actual_closure')
                stderr=Path(absent['stderr']['path']).read_text(encoding='utf8').lower()
                demand('no such object:' in stderr and cid in stderr and cid in rm['argv'] and cid in absent['argv'],'actor_absence')
                cids.add(cid);actor_count+=1
    fresh=task.read_json(reference(ack['freshOwnedObservationPin']))
    demand(fresh['protocol']=='tb12-fresh-owned-absence-v1' and fresh['family']==FAMILY and fresh['runId']==run
        and fresh['ownerNonce']==owned['ownerNonce'] and fresh['allAbsent'] is True and fresh['modelCalls']==0,'fresh_owner')
    source=task.REPO/'scripts/repair-2026-10-09'/OBSERVERS.get(fresh['sourceSha256'],'unknown')
    demand(source.is_file() and pin(source)['sha256']==fresh['sourceSha256'],'fresh_source')
    observed=datetime.fromisoformat(fresh['observedAtUtc'].replace('Z','+00:00'));released=datetime.fromisoformat(ack['observedAtUtc'].replace('Z','+00:00'))
    demand(0<=(released-observed).total_seconds()<=30,'fresh_release_time')
    if reg.get('recoveryPin'):
        demand(ack.get('recoveryPin')==reg['recoveryPin']==entry.get('recoveryPin'),'recovery_release_binding')
        recovery=task.read_json(reference(reg['recoveryPin']))
        demand(recovery['originalOwner']==owned and recovery['originalAdmissionPin']==reg['admissionPin'] and recovery['originalCertificatePin']==reg['closedPin']
            and recovery['freshOwnedObservationPin']==ack['freshOwnedObservationPin'] and recovery['modelCalls']==recovery['providerRequests']==0,'recovery_binding')
        observer=task.read_json(reference(recovery['nativeObserverClosePin']))
        demand(observer['exitObserved'] is True and observer['closeObserved'] is True and observer['exitCode']==0 and not observer['faults'],'fresh_observer_close')
        reference(observer['source']);reference(observer['executable'])
        demand(observer['source']['sha256']==fresh['sourceSha256'] and observer['argv'][4]==str(source)
            and datetime.fromisoformat(observer['startedAtUtc'].replace('Z','+00:00'))<=observed<=datetime.fromisoformat(observer['closedAtUtc'].replace('Z','+00:00')),'fresh_observer_execution')
        add(owned['pid'],owned['startedAt'],read(home/'manifest.json')['hostBun']['path'])
    demand(set(fresh['exactCids'])==cids and set(fresh['exactPids'])==pids and set(x for x in fresh['exclusiveBoundAndClosedPorts'] if x)==ports,'fresh_scope')
    receipts=[reference(p) for p in fresh['nativeReceiptPins']]
    pid_file=next((p for p in receipts if Path(p['path']).name=='pid-observation.json'),None)
    if pids:
        demand(pid_file is not None,'fresh_pid_receipt');pid=task.read_json(pid_file)
        demand(pid['requestedPids']==sorted(pids) and pid.get('observerSourceSha256',fresh['sourceSha256'])==fresh['sourceSha256'],'fresh_pid_scope')
        rows=pid['observations'];demand({q['pid'] for q in rows}==pids and len(rows)==len(pids),'fresh_pid_rows')
        for q in rows:
            n=q['pid']
            if q.get('numericPidAbsent'):
                demand(q.get('win32Error')==87 or q.get('win32Error')==5 and q.get('currentExeName') is None,'fresh_pid_absent')
            elif q.get('terminatedProcessObjectRetained'):
                demand(q.get('originalInstanceAbsent') is True and datetime.fromisoformat(q['observedExitAtUtc'])<=observed,'fresh_pid_exit')
            elif q.get('pidReused'):
                demand(q.get('originalInstanceAbsent') is True and datetime.fromisoformat(q['observedCreationAtUtc'])>latest[n],'fresh_pid_reuse')
            else:
                demand(q.get('win32Error')==5 and q.get('differentExecutableInstance') is True and q.get('originalInstanceAbsent') is True
                    and set(q['originalExeNames'])==executables[n] and q['currentExeName'] not in executables[n],'fresh_pid_other_executable')
    if cids:
        observer_db=Path(ack['freshOwnedObservationPin']['path']).parent/'owned-native.sqlite';pin(observer_db)
        with closing(immutable(observer_db)) as db:
            rows=[json.loads(x[0]) for x in db.execute('SELECT json FROM command ORDER BY id')]
            demand(len(rows)==len(cids),'fresh_container_count');seen=set()
            for q in rows:
                demand(q['argv'][3:6]==['inspect','--format','{{json .Id}}'] and q['argv'][-1] in cids and q['argv'][-1] not in seen
                    and q['closeObserved'] is True and not q['timedOut'] and not q['overflow'] and not q['captureFaults'] and q['exitCode']!=0,'fresh_container_command')
                seen.add(q['argv'][-1])
                for name in ('stdout','stderr'):reference(q[name])
                demand('no such object:' in Path(q['stderr']['path']).read_text(encoding='utf8').lower() and q['argv'][-1] in Path(q['stderr']['path']).read_text(encoding='utf8').lower(),'fresh_container_missing')
    # A port=0 historical record is not an original-listener observation. The
    # provider lived in this exact paid-entry process; observe its original
    # identity closed now, including retained exited objects and PID reuse.
    now_owner=identity.closed_identity(owned['pid'],int(datetime.fromisoformat(owned['startedAt'].replace('Z','+00:00')).timestamp()*1000))
    registry_db=home/'paid-registry.sqlite';pin(registry_db)
    with closing(immutable(registry_db)) as db:
        events=[(kind,json.loads(raw)) for kind,raw in db.execute('SELECT kind,json FROM event ORDER BY seq')]
        demand(events and events[0]==('acquired',{'owned':owned,'proofPin':reg['admissionPin']}),'registry_acquisition')
        closes=[q for kind,q in events if kind=='closed']
        if reg.get('recoveryPin'):
            recovered=[q for kind,q in events if kind=='financial-close-recovered']
            demand(not closes and len(recovered)==1 and recovered[0]=={'certificatePin':reg['closedPin'],'freshPin':ack['freshOwnedObservationPin'],'recoveryPin':reg['recoveryPin']},'registry_recovered_release')
        else:demand(len(closes)==1 and closes[0]['certificatePin']==reg['closedPin'] and closes[0]['freshOwnedObservationPin']==ack['freshOwnedObservationPin'],'registry_release')
    return {'protocol':'skillsbench-readonly-tb12-closed-native-scan-v2','runId':run,'family':FAMILY,'modelCalls':0,'DockerOperations':0,
        'neighboringWrites':0,'actualOriginalPaidOwnerClosed':now_owner,'nativeCommandsVerified':command_count,'ownedActorsVerifiedClosed':actor_count,
        'inputPinCount':len(inputs),'inputPinDigest':hashlib.sha256(task.canonical(sorted(inputs.values(),key=lambda p:p['path']))).hexdigest(),
        'registryPin':inputs[str((home/'tb12-paid-resource-run.json').resolve())],'executedSourceSubstitutions':snapshot_substitutions,
        'providerPortZeroProvedByClosedOwner':provider['port']==0,'sourcePin':task.pin(__file__)}


def main():
    p=argparse.ArgumentParser();p.add_argument('--run-directory',type=Path,required=True);a=p.parse_args();print(json.dumps(scan(a.run_directory)),flush=True)


if __name__=='__main__':main()
