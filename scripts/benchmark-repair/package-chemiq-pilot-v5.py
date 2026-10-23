"""Package the completed owned ChemIQ pilot and all its preparation history; no rescoring."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import zipfile

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/repair-2026-10-08'
HOME=DOC/'chemiq-f-journal-implementation-v3'
PARENT_HOME=DOC/'chemiq-f-journal-implementation-v2'
FAILED='repair-2026-10-09T09-40-03-707Z'
FAILED_OUTPUT=DOC/'chemiq-f-journal-campaigns-v2'/FAILED
FAILED_STORE=ROOT/'.phase1-data/chemiq-f-journal-v2'/FAILED
RECOVERY=DOC/'chemiq-f-financial-recoveries-v2'/FAILED
def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()
def pin(path):return {'path':str(path),'bytes':path.stat().st_size,'sha256':sha(path)}
def ordinary(path):
    assert path.resolve().is_relative_to(ROOT)
    for value in [path,*path.parents]:
        if value==ROOT.parent:break
        assert not getattr(value.stat(follow_symlinks=False),'st_file_attributes',0)&1024, 'reparse path forbidden'
    return path
def referenced_evidence(groups, extra, store):
    # Only this implementation's new evidence and the current owned run are followed.
    # Historical provider caches, other campaigns, executables and credentials stay external.
    allowed=[HOME,PARENT_HOME,store,*[folder for _,folder in groups]]
    included={};external={};historical=[];pending=[path for _,folder in groups for path in folder.rglob('*.json') if path.is_file()]+[p for p in extra if p.suffix.lower()=='.json']
    scanned=set()
    resolution_path=FAILED_OUTPUT/'failed-task12-recovered-v1/copied-shm-transient-pin-resolution.json'
    resolution=json.loads(resolution_path.read_bytes());resolutions={}
    assert resolution['protocol']=='chemiq-owned-sqlite-copy-transient-pin-resolution-v1' and resolution['originalsUnchanged'] is True and resolution['scoreCertificateValid'] is False
    assert pin(Path(resolution['recoveredTaskProofPin']['path']))==resolution['recoveredTaskProofPin']
    for row in resolution['resolutions']:
        before=row['historicalCopiedPin'];after=row['currentCopiedPin'];original=row['byteEquivalentUnchangedOriginalPin']
        assert Path(before['path']).is_relative_to(FAILED_OUTPUT/'failed-task12-recovered-v1/copied-database') and Path(before['path']).name=='h2h.sqlite-shm'
        assert Path(original['path']).is_relative_to(FAILED_STORE/'task-12/data') and Path(original['path']).name=='h2h.sqlite-shm'
        assert before['bytes']==original['bytes'] and before['sha256']==original['sha256'] and pin(Path(original['path']))==original and pin(Path(after['path']))==after and after['path']==before['path']
        assert row['historicalBytesStoredInOriginalFile'] is True
        resolutions[(before['path'],before['bytes'],before['sha256'])]=original
    def visit(value):
        if isinstance(value,list):
            for child in value:visit(child)
        elif isinstance(value,dict):
            if isinstance(value.get('path'),str) and re.fullmatch('[0-9a-f]{64}',str(value.get('sha256',''))):
                path=Path(value['path'])
                if path.is_absolute():
                    path=path.resolve()
                    if any(path.is_relative_to(root.resolve()) for root in allowed):
                        ordinary(path);actual=pin(path)
                        replacement=resolutions.get((str(path),value.get('bytes'),value['sha256']))
                        if replacement and actual['sha256']!=value['sha256']:
                            historical.append({'historicalPin':value,'byteEquivalentMemberPin':replacement,'reason':'Only copied readonly-SQLite SHM changed; exact historical bytes remain in unchanged original SHM'})
                            included[replacement['path']]=replacement
                            return
                        assert actual['sha256']==value['sha256'] and ('bytes' not in value or actual['bytes']==value['bytes']), 'referenced evidence pin changed'
                        assert path.name!='.env' and path.suffix.lower() not in {'.key','.pem'}
                        included[str(path)]=actual
                        if path.suffix.lower()=='.json' and path not in scanned:pending.append(path)
                    else:external[str(path)]={**value,'reason':'historical_or_external_pin_not_new_owned_evidence'}
            for child in value.values():visit(child)
    while pending:
        path=pending.pop()
        if path in scanned:continue
        scanned.add(path);ordinary(path)
        visit(json.loads(path.read_bytes()))
    historical=list({(item['historicalPin']['path'],item['historicalPin']['sha256']):item for item in historical}.values())
    return sorted(included.values(),key=lambda item:item['path']),sorted(external.values(),key=lambda item:item['path']),historical
def package(output, diagnostic=False):
    output=ordinary(output.resolve())
    manifest=json.loads((output/'manifest.json').read_bytes());run=manifest['runId']
    family='chemiq-f-journal-v2' if diagnostic else 'chemiq-f-journal-v3'
    assert manifest['family']==family and manifest['scope']=='pilot16' and manifest['plannedTaskRuns']==16 and manifest['taskSeconds']==900
    assert output==(FAILED_OUTPUT if diagnostic else DOC/'chemiq-f-journal-campaigns-v3'/run)
    registry=json.loads((output/'chemiq-paid-resource-run.json').read_bytes())
    if diagnostic:
        assert run==FAILED and registry['released'] is False and registry['certificationPin'] is None
        recovery=json.loads((RECOVERY/'recovery-index.json').read_bytes());ack=json.loads(Path(recovery['releaseCommittedPin']['path']).read_bytes())
        assert recovery['financialClosed'] is True and recovery['scoreCertificateValid'] is False and recovery['originalRegistryPin']==pin(output/'chemiq-paid-resource-run.json')
        assert ack['released'] is True and ack['financialOnly'] is True and ack['scoreCertificateValid'] is False and ack['originalV2RegistryUnchanged'] is True
        assert pin(Path(recovery['releaseCommittedPin']['path']))==recovery['releaseCommittedPin']
    else:
        assert registry['released'] is True and registry['certificationPin'] and registry['releaseCommittedPin']
        cert=json.loads(Path(registry['certificationPin']['path']).read_bytes());assert cert['kind']=='score' and cert['scoreCertificateValid'] is True
    recipe_path=Path(manifest['recipePin']['path']);recipe=json.loads(recipe_path.read_bytes());store=ordinary(Path(recipe['store']).resolve())
    assert store==(FAILED_STORE if diagnostic else ROOT/'.phase1-data/chemiq-f-journal-v3'/run)
    gate_path=Path(recipe['runtimeGate']['path']);gate=json.loads(gate_path.read_bytes());cold=ordinary(gate_path.parent)
    materials_path=ordinary(Path(gate['materialPin']['path']));assert materials_path.read_bytes() and gate['actualHttpRequests']==96
    groups=[('pilot-records',output),('owned-model-store',store),('frozen-paid-preparation',recipe_path.parent)]
    if not diagnostic:groups += [('interrupted-attempt-records',ordinary(FAILED_OUTPUT)),('interrupted-attempt-model-store',ordinary(FAILED_STORE))]
    groups.append(('interrupted-attempt-financial-recovery',ordinary(RECOVERY)))
    extras=[recipe_path,gate_path,materials_path,PARENT_HOME/'user-resource-directive.json',ROOT/'scripts/benchmark-repair/recover-chemiq-failed-task12-v1.ts']
    for label,home in [('execution-v3',HOME),('preserved-v2',PARENT_HOME)]:
        for folder in sorted(home.iterdir()):
            if not folder.is_dir() or folder.name=='pilot-packages':continue
            if folder.name in {'cold-executions','cold-materials','observations','revisions'} or folder.name.startswith(('independent-','source-review-','package-source-review-','controls-')):
                groups.append((label+'/'+folder.name,ordinary(folder)))
        extras += [p for p in home.iterdir() if p.is_file() and p.suffix in {'.json','.log','.md'}]
    for version in ['v2','v3']:
        preparation_home=DOC/('chemiq-f-journal-preparations-'+version)
        for folder in sorted(preparation_home.iterdir()):
            if not folder.is_dir() or folder==recipe_path.parent:continue
            prior=json.loads((folder/'manifest.json').read_bytes())
            assert prior['protocol']=='chemiq-f-preparation-'+version and prior['modelCalls']==0 and prior['providerForwardingEnabled'] is False
            groups.append(('earlier-metadata-only-preparations/'+version+'/'+folder.name,ordinary(folder)))
    references,external,historical=referenced_evidence(groups,extras,store)
    # Explicit standalone own sources/logs join the reference graph too.
    references += [pin(ordinary(p)) for p in extras if str(p.resolve()) not in {r['path'] for r in references}]
    packager_source=ordinary(Path(__file__).resolve());packager_pin=pin(packager_source)
    references.append(packager_pin)
    external=[item for item in external if not (item['path']==packager_pin['path'] and item['sha256']==packager_pin['sha256'])]
    target=HOME/'pilot-packages'/(run+('-interrupted-diagnostic' if diagnostic else ''));target.mkdir(parents=True,exist_ok=False)
    archive=target/('chemiq-pilot16-F900-interrupted-diagnostic.zip' if diagnostic else 'chemiq-pilot16-F900-complete.zip');records=[];written={}
    with archive.open('xb') as destination:
        with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as bundle:
            for label,folder in groups:
                for path in sorted(folder.rglob('*')):
                    if not path.is_file():continue
                    ordinary(path);assert path.name!='.env' and path.suffix.lower() not in {'.key','.pem'}
                    member=label+'/'+path.relative_to(folder).as_posix();before=pin(path);bundle.write(path,member);assert pin(path)==before
                    records.append({'member':member,**before});written[str(path.resolve())]=member
            for reference in references:
                path=Path(reference['path'])
                if str(path) in written:continue
                member='referenced-evidence/'+path.relative_to(ROOT).as_posix();bundle.write(path,member);assert pin(path)==reference
                records.append({'member':member,**reference});written[str(path)]=member
            if str(materials_path.resolve()) not in written:
                member='private-cold-materials/private-materials.json';bundle.write(materials_path,member);records.append({'member':member,**pin(materials_path)})
            def generated_json(member,value):
                raw=json.dumps(value,ensure_ascii=False,indent=2).encode('utf-8')
                bundle.writestr(member,raw);records.append({'member':member,'generated':True,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
            generated_json('referenced-evidence-index.json',{'included':[{**item,'member':written[item['path']]} for item in references],
                'externalHistoricalPins':external,'externalPinsClaimedPackaged':False,'historicalTransientCopiedPinResolutions':[{**item,'member':written[item['byteEquivalentMemberPin']['path']]} for item in historical]})
            generated_json('package-scope.json',{'protocol':'chemiq-pilot16-complete-package-v5','runId':run,'pilotOnly':True,'full816Executed':False,
                'privateReferencesIncludedForAudit':True,'privateReferenceExposureToSolver':False,'publicPublicationRequested':False,'credentialHeadersIncluded':False,'allOwnedPreparationHistoryIncluded':True,
                'scoreCertificateValid':not diagnostic,'interruptedOriginalAttemptIncluded':True,'interruptedAttemptScoreCertificateValid':False,'diagnosticOnly':diagnostic,'failedRoundNeverPooledWithValidPilot':True})
        destination.flush();os.fsync(destination.fileno())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for record in records:
            raw=bundle.read(record['member']);assert len(raw)==record['bytes'] and hashlib.sha256(raw).hexdigest()==record['sha256']
    report={'protocol':'chemiq-pilot16-package-receipt-v5','runId':run,'createdAtUtc':datetime.now(timezone.utc).isoformat(),'archive':pin(archive),
        'modelCallsByPackager':0,'graderCallsByPackager':0,'memberRecords':records,'memberCount':len(records),'zipCrcAndMemberHashesVerified':True,
        'referencedNewEvidenceCount':len(references),'externalHistoricalPinCount':len(external),
        'pilotOnly':True,'full816Executed':False,'scoreCertificateValid':not diagnostic,'diagnosticOnly':diagnostic,'historicalTransientPinResolutionCount':len(historical),'independentReviewStillRequired':True,'packagerSourcePin':packager_pin}
    proof=target/'package-receipt.json'
    with proof.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'packageReceipt':pin(proof),'archive':pin(archive),'memberCount':len(records),'modelCallsByPackager':0},ensure_ascii=False))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output');parser.add_argument('--diagnostic',action='store_true');args=parser.parse_args();package(Path(args.output),args.diagnostic)
