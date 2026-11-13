"""Initial real-pilot ZIP. Reuses V5 filesystem guards; does not run models or certification audits."""
from datetime import datetime, timezone
import gzip
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import zipfile

ROOT=Path(__file__).resolve().parents[2]
DOC=ROOT/'docs/repair-2026-10-08'
HOME=DOC/'chemiq-f-journal-implementation-v3'
RUN='repair-2026-10-09T12-21-50-354Z'
OLD='repair-2026-10-09T09-40-03-707Z'
OUTPUT=DOC/'chemiq-f-journal-campaigns-v3'/RUN
spec=importlib.util.spec_from_file_location('chemiq_existing_packager_v5',ROOT/'scripts/benchmark-repair/package-chemiq-pilot-v5.py')
existing=importlib.util.module_from_spec(spec);spec.loader.exec_module(existing)

VERIFY=r'''"""Offline ZIP integrity check only; no model, grader, network or SQLite access."""
import argparse, hashlib, json, pathlib, zipfile
def verify(path):
    with zipfile.ZipFile(path) as bundle:
        names=bundle.namelist()
        assert len(names)==len(set(names)), 'Duplicate ZIP member'
        assert all(not n.startswith(('/', '\\')) and '..' not in pathlib.PurePosixPath(n).parts for n in names), 'Unsafe ZIP member'
        manifest=json.loads(bundle.read('package-manifest.json'))
        records=manifest['members']
        assert set(names)=={r['member'] for r in records}|{'package-manifest.json'}, 'Member set mismatch'
        for record in records:
            raw=bundle.read(record['member'])
            assert len(raw)==record['bytes'] and hashlib.sha256(raw).hexdigest()==record['sha256'], 'Changed member: '+record['member']
        summary=json.loads(bundle.read('summary.json'))
        assert summary['executionCompletedTasks']==16 and summary['finalGradePassedTasks']==16
        assert summary['originalScoreCertificateValid'] is False and summary['recoveredPilotValidated'] is False
        assert summary['full816Executed'] is False
    digest=hashlib.sha256()
    with pathlib.Path(path).open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):digest.update(block)
    return {'verified':True,'memberCount':len(names),'bytes':pathlib.Path(path).stat().st_size,'sha256':digest.hexdigest(),'modelCalls':0,'graderCalls':0,'certificationReplayed':False}
if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('archive');args=parser.parse_args()
    print(json.dumps(verify(args.archive),ensure_ascii=False))
'''

def encoded(value):return (json.dumps(value,ensure_ascii=False,indent=2)+'\n').encode('utf-8')
def main():
    initial=HOME/'initial-delivery-v1'/RUN
    summary=json.loads((initial/'chemiq-pilot16-initial-results.json').read_bytes())
    assert summary['runId']==RUN and summary['executionCompletedTasks']==16 and summary['finalGradePassedTasks']==16
    assert summary['originalScoreCertificateValid'] is False and summary['recoveredPilotValidated'] is False
    manifest=json.loads((OUTPUT/'manifest.json').read_bytes());recipe=json.loads(Path(manifest['recipePin']['path']).read_bytes())
    gate=json.loads(Path(recipe['runtimeGate']['path']).read_bytes());provenance=json.loads((DOC/'chemiq-nextwave-grader-provenance.json').read_bytes())
    target=HOME/'pilot-packages'/(RUN+'-initial-v1');target.mkdir(parents=True,exist_ok=False)
    archive=target/'ChemIQ-pilot16-F900-initial-results.zip'
    items={};generated={}
    def add(member,path):
        path=existing.ordinary(Path(path).resolve())
        assert member not in items and member not in generated
        assert path.name.lower()!='.env' and path.suffix.lower() not in {'.key','.pem'}, 'Credential file prohibited'
        items[member]=path
    def folder(label,path):
        for p in sorted(Path(path).rglob('*')):
            if p.is_file():add(label+'/'+p.relative_to(path).as_posix(),p)
    folder('tasks/run-records',OUTPUT)
    folder('raw/owned-model-store',Path(recipe['store']))
    folder('source/paid-preparation',Path(manifest['recipePin']['path']).parent)
    folder('provenance/cold-runtime-controls',Path(recipe['runtimeGate']['path']).parent)
    folder('provenance/cold-materials',Path(gate['materialPin']['path']).parent)
    folder('provenance/source-review-07',HOME/'source-review-07')
    folder('provenance/completed-task-and-runtime-error-reviews',HOME/'independent-v3-runtime-abort-review-v1')
    folder('provenance/recovery-observation-not-certified',HOME/'independent-v3-closed-runtime-recovery-v1'/RUN)
    folder('provenance/recovery-source-review-pending',HOME/'independent-v3-closed-runtime-recovery-source-review-v1')
    folder('failed-attempts/'+OLD+'/records',DOC/'chemiq-f-journal-campaigns-v2'/OLD)
    folder('failed-attempts/'+OLD+'/raw-store',ROOT/'.phase1-data/chemiq-f-journal-v2'/OLD)
    folder('failed-attempts/'+OLD+'/financial-recovery',DOC/'chemiq-f-financial-recoveries-v2'/OLD)
    add('summary.json',initial/'chemiq-pilot16-initial-results.json')
    add('results.zh.txt',initial/'chemiq-pilot16-initial-results.zh.txt')
    add('selection.json',Path(manifest['recipePin']['path']).parent/'public-tasks.json')
    add('provenance/frozen-grader-provenance.json',DOC/'chemiq-nextwave-grader-provenance.json')
    add('source/dependencies/opsin-cli-2.8.0-jar-with-dependencies.jar',Path(provenance['opsin_jar']['path']))
    for label,pin in [('account-balance',recipe['balance']),('official-prices',recipe['prices']),('available-models',recipe['modelAvailability'])]:
        add('provenance/provider-observations/'+label+'.json',pin['path'])
    prices=json.loads(Path(recipe['prices']['path']).read_bytes());add('provenance/provider-observations/official-pricing.html',prices['officialResponsePin']['path'])
    recovery=json.loads((HOME/'independent-v3-closed-runtime-recovery-v1'/RUN/'recovery-observation.json').read_bytes())
    for label in ('inspectPin','bridgePin','resourcePin'):add('provenance/recovery-native-inputs/'+label+'.json',recovery[label]['path'])
    for name in ['package-chemiq-pilot-v5.py','package-chemiq-pilot-initial-v1.py','chemiq-v3-shutdown-native-diagnostic-01.ts','chemiq-v3-closed-runtime-recovery-v1.ts']:
        add('source/packaging-and-recovery-helpers/'+name,ROOT/'scripts/benchmark-repair'/name)
    counts={'taskRecords':len(list(OUTPUT.glob('task-*.json'))),'taskTraces':len(list(OUTPUT.glob('trace-*.jsonl'))),'rawModelRequests':len(list(Path(recipe['store']).glob('provider-*-request.json.gz'))),'rawModelResponses':len(list(Path(recipe['store']).glob('provider-*-response.json.gz')))}
    assert counts=={'taskRecords':16,'taskTraces':16,'rawModelRequests':46,'rawModelResponses':46}
    generated['README.md']=('''# Initial ChemIQ 16-task F900 pilot results package

The fixed 16 tasks were actually executed and finally graded; all 16 passed. Each had a 900-second budget, F arm, concurrency 4; there were 46 actual model requests. This package contains initial actual results. The original V3 closure certificate remains runtime-abort / score=false; this is not completed certification of everything, and results cannot be extrapolated to 816 tasks.

| Item | Result |
| --- | ---: |
| Planned / executed / finally graded | 16 / 16 / 16 |
| Final grading passed / failed / incomplete | 16 / 0 / 0 |
| Valid generations | 16 |
| Actual model requests | 46 |
| Actual physical grading receipts / independent final receipts | 106 / 32 |
| Estimated new cost for this round | CNY 0.20077968 |

See summary.json for run parameters, per-task answers, official indices, and IDs; the per-task Chinese table is results.zh.txt. Estimated costs of CNY 5.32224116 from earlier failed rounds are listed separately; tasks and scores from the two rounds are not combined. Costs are estimates computed from usage and official rates, not bills.

## Completed and outstanding checks

Candidates for all 16 tasks, 900-second deadlines, complete traces, 32 final parsed/correct raw receipts, usage for 46 requests, and the cash chain have been independently verified; 131 actual source files match frozen archive members. The original closure check retained only the SystemError name; its specific error code and failed subcommand are unknown, so the original failed certificate, digests, and records are all preserved. The supplemental full original-runtime audit and observations that 17 processes and 18 ports from this round disappeared have passed, with original file hashes unchanged before and after.

An independent recovery certificate has not been issued; review of the completed full predicates for the recovery helper's bridge-process/disk fields is still pending. This package does not alter the original failure state or pose as a frozen V3 results certificate. The package itself has undergone one offline member-integrity check, with no additional repeated two-axis review. The 816-task run has not started.

## File layout

- tasks/run-records: 16 actual task records, complete traces, candidate answers, final grades, and original closure/cost evidence.
- raw/owned-model-store: 46 pairs of original gzipped model requests/responses, complete usage events and cash ledger, actual grading requests/responses/receipts, 16 stopped DB/WAL/SHM sets, and this round's frozen source ZIP.
- source: actual paid recipe/configuration/source manifests and existing source snapshots, packager and recovery-observation source, and pinned OPSIN dependencies. Complete sources and Node dependencies are in raw/owned-model-store/frozen-source.zip; public grading source is also in that store's grader-provenance directory.
- provenance: cold grading controls, private grader environment and dependency manifests, existing independent reviews, and uncertified recovery observations.
- failed-attempts: actual tasks, traces, original model requests/responses, cash, and exact lock-release evidence from earlier failed/interrupted rounds; excluded from this round's 16 tasks.

Original evidence retains the absolute paths recorded at capture; actual files are included in the ZIP under the member directories above. package-manifest.json maps sourcePath to the corresponding member. Historical references to other benchmarks, OS interpreters, or container images do not mean those objects are included. External executors such as Bun, Python, and Java are represented only by existing version/hash manifests; Docker images are not exported.

## Offline verification

Extract verify-package.py from the ZIP and run `python verify-package.py <PATH_TO_THIS_ZIP>`. It checks the complete member set, CRC, size, and SHA256 without accessing models, grading services, the network, or SQLite. package-manifest.json lists every member except itself; its own hash and the ZIP hash are recorded in the external package-receipt.json. The package-receipt.json inside the ZIP is a packaging-process receipt; the final ZIP hash appears only in the external receipt to avoid circular hashing.

No .env, authentication headers, private keys, or actual API key values are included. When writing this package, the current actual provider key is scanned for, including expanded gzip and nested ZIP contents. This round's original sealed secret-audit separately proves that scans for the provider/grader values used then passed. The temporary grader token from earlier rounds is no longer available, so no claim is made that its actual value was rescanned.
''').encode('utf-8')
    generated['verify-package.py']=VERIFY.encode('utf-8')
    generated['package-receipt.json']=encoded({'protocol':'chemiq-pilot16-initial-package-internal-receipt-v1','runId':RUN,'deliveryStage':'initial-real-results','executedTasks':16,'finalPassedTasks':16,'failedTasks':0,'uncompletedTasks':0,'actualPayloadCounts':counts,'originalScoreCertificateValid':False,'recoveredPilotValidated':False,'modelCallsByPackager':0,'graderCallsByPackager':0,'manifestMember':'package-manifest.json','finalArchiveHashInExternalReceipt':True,'recoveryCertification':'pending','newIndependentPackageReview':'pending'})
    env_file=(ROOT/'.env').read_text(encoding='utf-8-sig');secret=None
    for line in env_file.splitlines():
        if line.startswith('DEEPSEEK_API_KEY='):secret=line.split('=',1)[1].strip().strip('"\'').encode('utf-8')
    assert secret and len(secret)>=16,'Provider secret unavailable for safe packaging'
    scanned=0;expanded=0
    def scan(raw,member,depth=0):
        nonlocal scanned,expanded
        scanned+=1;assert secret not in raw,'Sensitive credential found in '+member
        assert depth<5,'Unexpected nested archive depth'
        if raw.startswith(b'\x1f\x8b'):
            expanded+=1;scan(gzip.decompress(raw),member+'::gzip',depth+1)
        elif raw.startswith(b'PK\x03\x04'):
            with zipfile.ZipFile(io.BytesIO(raw)) as nested:
                for info in nested.infolist():
                    if not info.is_dir():expanded+=1;scan(nested.read(info),member+'::'+info.filename,depth+1)
    member_records=[]
    with archive.open('xb') as destination:
        with zipfile.ZipFile(destination,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=3) as bundle:
            for member,path in sorted(items.items()):
                raw=path.read_bytes();scan(raw,member);bundle.writestr(member,raw)
                member_records.append({'member':member,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'sourcePath':str(path)})
            for member,raw in generated.items():
                scan(raw,member);bundle.writestr(member,raw);member_records.append({'member':member,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest(),'generated':True})
            manifest_bytes=encoded({'protocol':'chemiq-pilot16-initial-package-manifest-v1','runId':RUN,'members':member_records,'memberCountExcludingManifest':len(member_records),'excludedSelfMember':'package-manifest.json','initialResultsOnly':True,'originalScoreCertificateValid':False,'recoveredPilotValidated':False,'full816Executed':False})
            bundle.writestr('package-manifest.json',manifest_bytes)
        destination.flush();os.fsync(destination.fileno())
    namespace={};exec(compile(VERIFY,'verify-package.py','exec'),namespace);verification=namespace['verify'](archive)
    receipt={'protocol':'chemiq-pilot16-initial-package-receipt-v1','runId':RUN,'createdAtUtc':datetime.now(timezone.utc).isoformat(),'archive':{'path':str(archive),'bytes':verification['bytes'],'sha256':verification['sha256']},'memberCount':verification['memberCount'],'manifestSha256':hashlib.sha256(manifest_bytes).hexdigest(),'zipCrcAndMemberHashesVerified':True,'verificationPasses':1,'actualPayloadCounts':counts,'credentialScan':{'actualProviderValuesChecked':1,'checkedPayloads':scanned,'expandedPayloads':expanded,'findings':0,'originalPaidRunTwoValueAuditIncluded':True,'oldGraderSecretRescanClaimed':False},'originalScoreCertificateValid':False,'recoveredPilotValidated':False,'full816Executed':False,'modelCallsByPackager':0,'graderCallsByPackager':0,'packagerSourcePin':{'path':str(Path(__file__).resolve()),'bytes':Path(__file__).stat().st_size,'sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()},'pending':['independent recovery certificate','new independent final-package review']}
    proof=target/'package-receipt.json'
    with proof.open('x',encoding='utf-8') as stream:json.dump(receipt,stream,ensure_ascii=False,indent=2);stream.write('\n');stream.flush();os.fsync(stream.fileno())
    print(json.dumps({'archive':receipt['archive'],'receiptPath':str(proof),'memberCount':verification['memberCount'],'verificationPasses':1,'providerCredentialFindings':0,'modelCalls':0,'graderCalls':0},ensure_ascii=False))
if __name__=='__main__':main()
