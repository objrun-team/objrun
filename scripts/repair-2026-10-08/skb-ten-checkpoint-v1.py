"""Update only this independent SkillsBench chat's truthful progress checkpoint."""
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import shutil
import skb_artifact_task_v2 as task

ROOT=task.REPO
HOME=ROOT/'docs/repair-2026-10-08/skillsbench-ten-takeover-v1'
STATUS=ROOT/'docs/repair-2026-10-08/parallel-bench-handoff-2026-10-09/skillsbench-status.json'


def main():
    current=json.loads(STATUS.read_bytes())
    old=HOME/'status-history';old.mkdir(exist_ok=True)
    now=datetime.now(timezone.utc);name=now.strftime('%Y%m%dT%H%M%S%fZ')+'.json'
    with (old/name).open('xb') as f:f.write(STATUS.read_bytes());f.flush();os.fsync(f.fileno())
    free={k:shutil.disk_usage(k+':/').free for k in ('C','D','F')}
    controls=[]
    for kind in ('python','core'):
        runs=sorted((HOME/'local-control-runs').glob(kind+'-*/run.json'),key=lambda p:p.stat().st_mtime_ns)
        controls.append({'kind':kind,'runPin':task.pin(runs[-1]),'exitCode':json.loads(runs[-1].read_bytes())['exitCode'],'scope':'pure source controls; no actual task trials'})
    lock=ROOT/'.phase1-data/owned-paid-campaign.lock.json'
    runtime=HOME/'runtime-preparations/54133c790d074587a1fb0eb338577cd3'
    layout=json.loads((runtime/'storage-descriptor.json').read_bytes())
    catalog=Path(layout['directories']['taskmeta'])/'environment-builds-acb40c2c60ae447fb8ccf8d3738f7306/build-closed-catalog.json'
    balance=HOME/'resource-observations/0c783dcaa6171ec46cbd439c/balance.json'
    b=json.loads(balance.read_bytes())
    collections=sorted((HOME/'actual-collections').glob('*/index.json'),key=lambda p:p.stat().st_mtime_ns)
    from skb_artifact_ram_executor_v2 import sources
    current_sources=sources();source_replay_pending=True
    if collections:
        ci=json.loads(collections[-1].read_bytes())
        owners=[json.loads(Path(json.loads(Path(p['path']).read_bytes())['ownedClosurePin']['path']).read_bytes()) for p in ci['collectionPins']]
        source_replay_pending=not all([x['originalPin'] for x in o['sourceSnapshots']]==current_sources for o in owners)
    actual=[]
    for cp in (HOME/'actual-cold-controls').glob('*/control.json'):
        v=json.loads(cp.read_bytes())
        if v['controlMatched'] and collections and v['taskDescriptorPin'] in ci['taskDescriptorPins']:
            actual.append({'taskId':v['taskId'],'mode':v['mode'],'strictG':v['strictG'],'officialReward':v['officialReward'],'controlPin':task.pin(cp)})
    triplets=[tid for tid in task.TASK_IDS if {x['mode'] for x in actual if x['taskId']==tid}=={'empty','oracle','wrong'}]
    real_calls=0;real_runs=0;paired=0;certified=0;own_acquired=False;pilot_pins=[];pending=0
    for pointer in (HOME/'pilot-recipes').glob('*/recipe-pointer.json'):
        q=json.loads(pointer.read_bytes());recipe=json.loads(Path(q['recipePin']['path']).read_bytes())
        if recipe['providerKind']!='real-provider':continue
        output=Path(recipe['output']);s=json.loads(Path(recipe['storageDescriptorPin']['path']).read_bytes());journal=Path(s['directories']['journal'])/'api-events.jsonl'
        own_acquired=own_acquired or (output/'skb-admission.json').exists();starts=set();finishes=set()
        if journal.exists():
            for line in journal.read_bytes().splitlines():
                e=json.loads(line)
                if e['kind']=='start':starts.add(e['requestSeq'])
                elif e['kind']=='finish':
                    finishes.add(e['requestSeq']);real_calls+=int(e['record'].get('providerAttempted') is True)
        pending+=len(starts-finishes)
        if (output/'summary.json').exists():
            summary=json.loads((output/'summary.json').read_bytes());real_runs+=summary['realInferenceTaskRuns'];paired=max(paired,summary.get('completedPairedRealTrials',0))
        if (output/'final-certificate.json').exists():
            c=json.loads((output/'final-certificate.json').read_bytes());certified=max(certified,c['completedRealDistinctTasks']);pilot_pins.append(task.pin(output/'final-certificate.json'))
    phase='awaiting-ten-task-pilot-confirmation' if paired==10 and pilot_pins else 'executing-fixed-ten-paired-pilot' if own_acquired else 'validating-current-source-cold-runtime'
    current.update({'updatedAtUtc':now.isoformat(),'phase':phase,'completedRealDistinctTasks':certified,
        'completedRealTaskRuns':real_runs,'completedPairedRealTrials':paired,'realModelCalls':real_calls,'newProjectLlmRequests':real_calls,
        'unclosedModelJournalAdmissions':pending,'pilotCertificatePins':pilot_pins,'volumeFreeBytes':free,'CResourceGatePassed':free['C']>=1024**3,
        'paidLockExistsAtObservation':lock.exists(),'paidReady':False,'localControlReceipts':controls,
        'verifiedOfflineWheelCount':21,'actualNewSolverImagesCompleted':9,'actualCachedSolverImagesVerified':1,'actualPrivateRuntimeImagesCompleted':1,
        'actualTestCollections':10,'actualCollectedNodeCount':186,'actualCollectionIndexPin':task.pin(collections[-1]) if collections else None,
        'currentSourceCollectionReplayPending':source_replay_pending,'actualColdControlTriplets':len(triplets),'actualColdControlReceipts':actual,'modelInferenceCallsMadeByThisChat':real_calls,
        'resourceCheckTimeUtc':now.isoformat(),'lastKnownBalanceCNY':float(next(x['total_balance'] for x in b['balances'] if x['currency']=='CNY')),'balanceObservationUtc':b['observedAtUtc'],
        'balanceObservationPin':task.pin(balance),'balanceIsPaidPrecondition':False,'userBalanceOverride':'直接试跑 忽略余额',
        'historicalUnknownExposureCNY':8.39218,'reserveCNY':0,'previousReserveCNY':30,'reserveOverriddenByUser':True,
        'closedBuildCatalogPin':task.pin(catalog),
        'buildFailures':['CLI125 unsupported legacy --progress','BuildKit APT100 repository502','native guard FileNotFoundError on transient owned temp','actual HTTPS APT502 retry failure','Docker backend EOF during private build; failed raw retained'],
        'sharedPaidLockAcquiredByThisChat':own_acquired,'full87Authorized':False,'historical85_1Certified':False,
        'remaining':['current-source full collection and actual empty/oracle/wrong controls','original shell vs offline cold oracle comparison and lab fractional control',
            'actual six-tool bridge and engine/factory controls','source-bound cash/resource/lock admission with user balance override','ten same-task U/F real trials',
            'complete package and independent final review'], 'checkpointSourcePin':task.pin(__file__)})
    raw=json.dumps(current,ensure_ascii=False,indent=2).encode()+b'\n'
    with STATUS.open('wb') as f:f.write(raw);f.flush();os.fsync(f.fileno())
    task.demand(STATUS.read_bytes()==raw,'status_readback','Own checkpoint readback differs')
    print(json.dumps({'statusPin':task.pin(STATUS),'volumeFreeBytes':free,'confirmedRealProviderForwards':real_calls,'completedPairedRealTrials':paired,'paidReady':False}))


if __name__=='__main__':main()
