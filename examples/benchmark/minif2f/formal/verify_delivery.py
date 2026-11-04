"""Independent local receipt/event replay, complete-log hashes and credential scan."""
import hashlib
import io
import json
from pathlib import Path
import re
import shutil
import sys
import tarfile

HERE=Path(__file__).resolve().parent;REPO=HERE.parents[1];WORKSPACE=REPO.parent
DEST=REPO/'docs/minif2f/test244-deepinfra-20261019-v1'
STAGE=WORKSPACE/'tmp/minif2f-test244-deepinfra-20261019-v1'

def read(p):return json.loads(p.read_text(encoding='utf-8-sig'))
def sha(p):
    with p.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()
def save(p,v):p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

def main():
    full=DEST/'full-results';out=full/'outputs';integrity=read(DEST/'archive-integrity.json')
    assert sha(DEST/'results.tar.gz')==integrity['sha256']
    pins=read(out/'source-pins.json')
    assert all(sha(full/p)==h for p,h in pins.items())
    for name,h in pins.items():
        p=Path(name)
        if p.parts[0]=='package':assert sha(HERE/p.name)==h,'Local source differs from frozen formal package'
    cfg=read(full/'package/experiment.json');catalog=read(full/'data/public-test.json')
    assert cfg['modelConcurrency']==16 and cfg['graderConcurrency']==4 and cfg['requestSpacingSeconds']==0
    assert cfg['batchDollarCap']==48.80 and cfg['perTaskDollarCap']==.10 and len(catalog)==244
    assert all(q['split']=='test' and q['id']=='test/'+q['name'] for q in catalog)
    assert read(full/'data/catalog-manifest.json')['publicTestSha256']==sha(full/'data/public-test.json')
    sys.path.insert(0,str(full/'package'))
    from sequence import check_messages
    receipts=[];per_group={};calls=set();begins={};ends={};active=set();peak=0
    for line in (out/'model-concurrency.jsonl').read_text().splitlines():
        e=json.loads(line);call=e['callDirectory']
        if e['event']=='http_begin':
            assert call not in begins;begins[call]=e;active.add(call)
        else:
            assert call in active and call not in ends;ends[call]=e;active.remove(call)
        assert e['active']==len(active)<=16;peak=max(peak,len(active))
    assert not active and begins.keys()==ends.keys()
    for arm in ['independent','binary']:
        for q in catalog:
            group=arm+'/'+q['name'];d=out/'tasks'/group
            history=read(d/'samples.json') if (d/'samples.json').exists() else []
            result=read(out/'results'/arm/(q['name']+'.json'))
            assert result['sampleCount']==len(history)<=5
            for dispatch_path in (out/'calls'/group).rglob('dispatch.json'):
                directory=dispatch_path.parent;call=str(directory.relative_to(full));calls.add(call)
                dispatch=read(dispatch_path);receipt=read(directory/'receipt.json')
                request=read(directory/'request.json');index=int(directory.parent.name[8:])
                assert dispatch['requestSha256']==receipt['requestSha256']==sha(directory/'request.json')
                assert check_messages(request['messages'],cfg['systemPrompt'],q,arm,history[:index])
                assert request['provider']['only']==['deepinfra/fp8'] and request['provider']['allow_fallbacks'] is False
                assert not request.get('tools') and request['model']==cfg['model']
                assert receipt['networkStartedAtEpoch']==begins[call]['atEpoch'] and receipt['networkEndedAtEpoch']==ends[call]['atEpoch']
                if receipt['success']:assert (receipt['provider'],receipt['model'])==('DeepInfra',cfg['model'])
                receipts.append(receipt);per_group.setdefault(group,[]).append(receipt)
    assert calls==begins.keys()
    actual=sum(r['actualCostUsd'] or 0 for r in receipts)
    exposure=sum(r['actualCostUsd'] if r['actualCostUsd'] is not None else r['reservationUsd'] for r in receipts)
    unknown=sum(r['unknownCost'] for r in receipts)
    assert exposure<=48.80+1e-9
    assert all(sum(r['actualCostUsd'] if r['actualCostUsd'] is not None else r['reservationUsd'] for r in group)<=.10+1e-9 for group in per_group.values())
    summary=read(out/'summary.json');audit=read(out/'audit.json')
    assert audit['protocolAndIntegrityChecksPassed'] and audit['all488RecordsPresent']
    assert summary['records']==488 and len(summary['rows'])==488 and not summary['pilotExpensesIncluded']
    assert len(receipts)==summary['modelRequests'] and peak==summary['concurrency']['actualHttpPeak']
    assert abs(actual-summary['actualCostUsd'])<1e-10 and abs(exposure-summary['budgetChargedUsd'])<1e-10
    assert unknown==summary['unknownCostCount']
    process_count=0
    for p in (out/'grades').glob('*/invocation-*/execution-*/process.json'):
        v=read(p);process_count+=1
        assert v['memoryGiB']==12 and v['compileTimeoutSeconds']==300 and v['freshProcess']
        assert v['credentialsInherited'] is False and v['network']=='new empty namespace'
        assert 'OPENROUTER_API_KEY' not in v['environment'] and '--unshare-all' in v['args'] and '-i' in v['args']
    operations=DEST/'local-operations';operations.mkdir(exist_ok=True)
    for p in STAGE.iterdir():
        if p.is_file() and p.name!='package.tar.gz':shutil.copy2(p,operations/p.name)
    text=(WORKSPACE/'TgEngin.env').read_text(encoding='utf-8-sig')
    key=re.search(r'^\s*OPENROUTER_API_KEY\s*=\s*(.+?)\s*$',text,re.M)[1].strip().strip('"\'').encode()
    assert len(key)>12
    hits=[];entries=0
    def scan(stream,prefix):
        nonlocal entries
        with tarfile.open(fileobj=stream,mode='r:gz') as archive:
            for member in archive.getmembers():
                if not member.isfile():continue
                data=archive.extractfile(member).read();entries+=1;name=prefix+member.name
                if key in data:hits.append(name)
                if member.name.endswith('.tar.gz'):scan(io.BytesIO(data),name+'!/')
    with (DEST/'results.tar.gz').open('rb') as stream:scan(stream,'results.tar.gz!/')
    for p in operations.iterdir():
        if p.is_file():
            entries+=1
            if key in p.read_bytes():hits.append('local-operations/'+p.name)
    assert not hits,'Actual workspace credential found in delivery'
    save(DEST/'credential-scan.json',{'actualWorkspaceKeyAbsent':True,'scannedFileEntriesIncludingNestedArchives':entries,'hits':hits})
    deps=WORKSPACE/'tmp/minif2f-valid-pilot-20261019-v1/lean-dependencies.tar.gz'
    assert sha(deps)==integrity['dependencyBundleSeparate']
    save(DEST/'delivery-index.json',{'remoteArchive':integrity,'dependencyBundleAlreadyLocal':str(deps),
        'dependencyBundleSha256':integrity['dependencyBundleSeparate'],
        'localOperationFiles':{p.name:sha(p) for p in operations.iterdir() if p.is_file()}})
    verification={'archiveSha256Verified':True,'archiveSha256':integrity['sha256'],
        'completeLogsReturnedLocally':True,'allFrozenSourcePinsVerified':True,'actualHttpPeak':peak,
        'allHttpSlotsClosed':True,'all488RecordsVerified':True,'messageIsolationPassed':True,
        'independentLedgerAgreesWithSummary':True,'confirmedCostUsd':actual,'unknownCostCount':unknown,
        'budgetExposureUsd':exposure,'credentialsAbsent':True,'workerResourceRecordsVerified':process_count,
        'separateDependencyBundleHashVerified':True}
    save(DEST/'local-verification.json',verification);print(json.dumps(verification))

if __name__=='__main__':main()
