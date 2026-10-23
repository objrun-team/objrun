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
HOME=DOC/'chemiq-f-journal-implementation-v2'
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
    allowed=[HOME,store,*[folder for _,folder in groups]]
    included={};external={};pending=[path for _,folder in groups for path in folder.rglob('*.json') if path.is_file()]+extra
    scanned=set()
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
    return sorted(included.values(),key=lambda item:item['path']),sorted(external.values(),key=lambda item:item['path'])
def package(output):
    output=ordinary(output.resolve())
    manifest=json.loads((output/'manifest.json').read_bytes());run=manifest['runId']
    assert manifest['family']=='chemiq-f-journal-v2' and manifest['scope']=='pilot16' and manifest['plannedTaskRuns']==16 and manifest['taskSeconds']==900
    assert output==DOC/'chemiq-f-journal-campaigns-v2'/run
    registry=json.loads((output/'chemiq-paid-resource-run.json').read_bytes())
    assert registry['released'] is True and registry['certificationPin'] and registry['releaseCommittedPin']
    cert=json.loads(Path(registry['certificationPin']['path']).read_bytes());assert cert['kind']=='score' and cert['scoreCertificateValid'] is True
    recipe_path=Path(manifest['recipePin']['path']);recipe=json.loads(recipe_path.read_bytes());store=ordinary(Path(recipe['store']).resolve())
    assert store==ROOT/'.phase1-data/chemiq-f-journal-v2'/run
    gate_path=Path(recipe['runtimeGate']['path']);gate=json.loads(gate_path.read_bytes());cold=ordinary(gate_path.parent)
    materials_path=ordinary(Path(gate['materialPin']['path']));assert materials_path.read_bytes() and gate['actualHttpRequests']==96
    groups=[('pilot-records',output),('owned-model-store',store),('frozen-paid-preparation',recipe_path.parent)]
    groups += [('private-cold-attempts/'+folder.name,ordinary(folder)) for folder in sorted((HOME/'cold-executions').iterdir()) if folder.is_dir()]
    groups += [('independent-source-reviews/'+folder.name,ordinary(folder)) for folder in sorted(HOME.glob('independent-source-review-*')) if folder.is_dir()]
    groups += [('independent-packaging-source-reviews/'+folder.name,ordinary(folder)) for folder in sorted(HOME.glob('independent-package-source-review-*')) if folder.is_dir()]
    groups += [('implementation-controls/'+folder.name,ordinary(folder)) for folder in sorted(HOME.glob('controls-v2-*')) if folder.is_dir()]
    if (HOME/'revisions').is_dir():groups.append(('preserved-source-revisions',ordinary(HOME/'revisions')))
    groups.append(('owned-readonly-observations',ordinary(HOME/'observations')))
    preparation_home=DOC/'chemiq-f-journal-preparations-v2'
    for folder in sorted(preparation_home.iterdir()):
        if not folder.is_dir() or folder==recipe_path.parent:continue
        prior=json.loads((folder/'manifest.json').read_bytes())
        assert prior['protocol']=='chemiq-f-preparation-v2' and prior['modelCalls']==0 and prior['providerForwardingEnabled'] is False
        groups.append(('earlier-metadata-only-preparations/'+folder.name,ordinary(folder)))
    references,external=referenced_evidence(groups,[recipe_path,gate_path,materials_path,HOME/'user-resource-directive.json'],store)
    packager_source=ordinary(Path(__file__).resolve());packager_pin=pin(packager_source)
    references.append(packager_pin)
    external=[item for item in external if not (item['path']==packager_pin['path'] and item['sha256']==packager_pin['sha256'])]
    target=HOME/'pilot-packages'/run;target.mkdir(parents=True,exist_ok=False)
    archive=target/'chemiq-pilot16-F900-complete.zip';records=[];written={}
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
                'externalHistoricalPins':external,'externalPinsClaimedPackaged':False})
            generated_json('package-scope.json',{'protocol':'chemiq-pilot16-complete-package-v3','runId':run,'pilotOnly':True,'full816Executed':False,
                'privateReferencesIncludedForAudit':True,'privateReferenceExposureToSolver':False,'publicPublicationRequested':False,'credentialHeadersIncluded':False,'allOwnedPreparationHistoryIncluded':True})
        destination.flush();os.fsync(destination.fileno())
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for record in records:
            raw=bundle.read(record['member']);assert len(raw)==record['bytes'] and hashlib.sha256(raw).hexdigest()==record['sha256']
    report={'protocol':'chemiq-pilot16-package-receipt-v3','runId':run,'createdAtUtc':datetime.now(timezone.utc).isoformat(),'archive':pin(archive),
        'modelCallsByPackager':0,'graderCallsByPackager':0,'memberRecords':records,'memberCount':len(records),'zipCrcAndMemberHashesVerified':True,
        'referencedNewEvidenceCount':len(references),'externalHistoricalPinCount':len(external),
        'pilotOnly':True,'full816Executed':False,'independentReviewStillRequired':True,'packagerSourcePin':packager_pin}
    proof=target/'package-receipt.json'
    with proof.open('x',encoding='utf-8') as stream:json.dump(report,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'packageReceipt':pin(proof),'archive':pin(archive),'memberCount':len(records),'modelCallsByPackager':0},ensure_ascii=False))
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output');args=parser.parse_args();package(Path(args.output))
