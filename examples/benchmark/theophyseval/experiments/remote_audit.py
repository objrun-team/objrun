"""Remote final artifact, resource, route and receipt audit; preserve raw evidence."""
from pathlib import Path
import hashlib
import json
import sqlite3
import sys
import tarfile
import os
import math
import time
import urllib.request
import urllib.parse
from audit import audit
from grade import evaluate
from remote_entry import freeze_check

ROOT=(Path(__file__).resolve().parents[4] / 'scripts')

def reconcile(out, errors):
    cfg=json.loads((out/'frozen-config.json').read_text())
    opener=urllib.request.build_opener(urllib.request.ProxyHandler({'https':cfg['proxy']}))
    folder=out/'billing';folder.mkdir(exist_ok=True)
    records=[];sampled=set()
    for p in sorted((out/'calls').rglob('receipt.json')):
        receipt=json.loads(p.read_text());arm=p.relative_to(out/'calls').parts[0]
        if not receipt.get('generationId') or (not receipt['unknownCost'] and arm in sampled):continue
        sampled.add(arm);generation=receipt['generationId'];record={'receipt':p.relative_to(out).as_posix(),'arm':arm,'generationId':generation,'wasUnknown':receipt['unknownCost'],'attempts':[]}
        for attempt in range(3):
            try:
                req=urllib.request.Request('https://openrouter.ai/api/v1/generation?id='+urllib.parse.quote(generation,safe=''),headers={'Authorization':'Bearer '+os.environ['OPENROUTER_API_KEY']})
                with opener.open(req,timeout=15) as response:raw=response.read();status=response.status
                data=json.loads(raw)['data'];cost=data.get('total_cost')
                if data.get('id')!=generation or data.get('provider_name')!='DigitalOcean' or not isinstance(cost,(int,float)) or not math.isfinite(cost) or cost<0:raise ValueError('GenerationMetadataBinding')
                (folder/(hashlib.sha256(str(p).encode()).hexdigest()+'.json')).write_bytes(raw)
                record.update(actualCostUsd=cost,verified=True)
                if receipt['actualCostUsd'] is not None and abs(receipt['actualCostUsd']-cost)>1e-9:errors.append('GenerationCostMismatch:'+str(p))
                break
            except Exception as e:
                record['attempts'].append({'type':type(e).__name__,'httpStatus':getattr(e,'code',None)})
                if getattr(e,'code',None) in [400,401,402,403,404]:break
                if attempt<2:time.sleep(attempt+1)
        records.append(record)
    (folder/'reconciliation.json').write_text(json.dumps({'modelCalls':0,'method':'GET generation metadata; original receipts unchanged','records':records},indent=2))
    return {r['receipt']:r['actualCostUsd'] for r in records if r.get('verified') and r['wasUnknown']}

def main():
    run=sys.argv[1];out=ROOT/'outputs'/run
    frozen=freeze_check();result=audit(run);errors=result['errors']
    catalog={u['id']:u for t in json.loads((ROOT/'data/catalog.json').read_text()) for u in t['units']}
    manifests={}
    for p in (ROOT/'outputs/snapshots').glob('*/*/manifest.json'):
        m=json.loads(p.read_text());manifests[m['candidate']]=p.parent/'output'
    for p in (out/'results').glob('*/*.json'):
        row=json.loads(p.read_text())
        if not row['valid']:continue
        rounds=json.loads((out/'tasks'/row['arm']/row['id']/'rounds.json').read_text())
        for round in rounds:
            for unit in round['units']:
                if unit['candidate'] not in manifests:
                    if unit['grade']['passed']:errors.append('MissingPassingCandidate:'+str(p))
                    continue
                again=evaluate(ROOT/'data/private',catalog[unit['id']],manifests[unit['candidate']])
                if any(again.get(k)!=unit['grade'].get(k) for k in ['valid','parsed','passed']):errors.append('GradeReproductionMismatch:'+str(p))
    db=sqlite3.connect(str(ROOT/'outputs/resource-ledger.sqlite'))
    containers=[json.loads(r[0]) for r in db.execute('select record from containers')]
    for c in containers:
        h=c['HostConfig'];labels=c['Config']['Labels']
        if h['NanoCpus']!=2000000000 or h['Memory']!=4096*1024**2 or h['StorageOpt'].get('size')!='10240M' or h['Binds'] or labels['tpe.run']!=run:
            errors.append('ContainerResourceOrOwnershipMismatch:'+c['Id'])
        if any(e.split('=',1)[0].endswith('_API_KEY') for e in c['Config']['Env']):errors.append('ContainerCredentialExposure:'+c['Id'])
    active=db.execute('select count(*) from leases where released is null').fetchone()[0]
    live=db.execute('select count(*) from containers where disposed is null').fetchone()[0]
    live_networks=db.execute('select count(*) from networks where removed is null').fetchone()[0]
    if active or live or live_networks:errors.append('UnreleasedOwnedResources')
    resource_events=[json.loads(r[0]) for r in db.execute("select record from events where kind='admit'")]
    peak=max([e['activeAfter'] for e in resource_events] or [0])
    model=json.loads((out/'model-concurrency.json').read_text())
    if peak>32 or model['peak']>32:errors.append('ConcurrencyAuthorizationExceeded')
    reconciled=reconcile(out,errors)
    receipt_paths=list((out/'calls').rglob('receipt.json'))
    receipts=[json.loads(p.read_text()) for p in receipt_paths]
    unsettled=[p for p in (out/'calls').rglob('dispatch.json') if not (p.parent/'receipt.json').exists()]
    if unsettled:errors.append('UnsettledModelDispatch')
    billing={'knownCostUsd':sum(r['actualCostUsd'] or 0 for r in receipts)+sum(reconciled.values()),'reconciledUnknownCount':len(reconciled),
        'unknownCostCount':sum(bool(r['unknownCost']) for r in receipts)-len(reconciled),
        'unknownCostUpperBoundUsd':sum(r['upperBoundUsd'] for p,r in zip(receipt_paths,receipts) if r['unknownCost'] and p.relative_to(out).as_posix() not in reconciled),
        'basis':'Original provider usage.cost at full precision plus verified unknown generation metadata costs; unresolved costs remain unknown. Account balance includes other experiments and is not attributed here.'}
    for arm,s in result['summary'].items():
        s['reconciledCostUsd']=sum(v for p,v in reconciled.items() if Path(p).parts[1]==arm)
        s['remainingUnknownCostCount']=s['unknownCostCount']-sum(1 for p in reconciled if Path(p).parts[1]==arm)
    result.update(passed=not errors,errors=errors,resourcePeak=peak,modelRequestPeak=model['peak'],billing=billing,
        executionLocations={'controller':'novaeve trusted host','ObjRun':'novaeve trusted host','grader':'novaeve trusted host','solver':'novaeve project-private Docker'},gitCommit=frozen['gitCommit'])
    (out/'final-audit.json').write_text(json.dumps(result,indent=2)+'\n')
    with (out/'REPORT.md').open('a',encoding='utf-8') as f:
        f.write('\nRemote final audit: '+('passed' if result['passed'] else 'unresolved anomalies')+'. Actual peak tasks: '+str(peak)+'; actual peak model requests: '+str(model['peak'])+'; both caps are 32.\n\n')
        f.write('Controller, ObjRun, grader, and scientific computation all run on novaeve. Each task retains 2 CPUs, 4096 MiB memory, and 10240 MiB container writable storage.\n\nBilling reconciliation: '+json.dumps(billing,ensure_ascii=False)+'\n\n')
        f.write('ObjRun receives stage-level feedback; binary receives only whole-task binary feedback. Do not interpret this comparison as a pure feedback-information ablation. Unknown costs and infrastructure failures are retained separately.\n')
        f.write('\n| Arm | Automated problems passed/49 | Confirmed cost USD | Remaining unknown charges |\n|---|---:|---:|---:|\n')
        for arm,s in result['summary'].items():f.write(f"| {arm} | {s['passedUnits']} | {s['knownCostUsd']+s['reconciledCostUsd']:.9f} | {s['remainingUnknownCostCount']} |\n")
    archive=ROOT.parents[1]/'archive'/(run+'.tar.gz')
    if archive.exists():raise RuntimeError('ExistingArchiveMustNotBeOverwritten')
    temp=archive.with_suffix('.partial')
    with tarfile.open(temp,'w:gz') as tar:
        for name in ['package','data','source','control','outputs']:
            tar.add(ROOT/name,arcname=name,filter=lambda t:None if 'node_modules' in t.name or '__pycache__' in t.name or t.name=='outputs/bridge.json' else t)
    temp.rename(archive)
    record={'path':str(archive),'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'bytes':archive.stat().st_size,'auditPassed':result['passed']}
    (out/'archive-receipt.json').write_text(json.dumps(record,indent=2))
    archive.with_suffix('.sha256.json').write_text(json.dumps(record,indent=2))
    print(json.dumps(result,ensure_ascii=False));raise SystemExit(0 if result['passed'] else 1)

if __name__=='__main__':main()
