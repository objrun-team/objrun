"""F readiness: current selected Pins, bounded public log scan, original audit binding."""
import gzip
import importlib.util
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'scripts/repair-2026-10-08/package-tb-real-pilot-v1.py'
spec=importlib.util.spec_from_file_location('tb_package_plan_review',SOURCE)
p=importlib.util.module_from_spec(spec);spec.loader.exec_module(p)

def main():
    plan_pin=p.pin(p.DOC/'plan.json');plan=p.load(plan_pin['path'])
    p.verify(plan['writerPin']);p.verify(plan['sourceArchive'])
    selected=[];suspected=[]
    for item in plan['directFiles']:
        p.verify(item['source']);path=Path(item['source']['resolvedPath'])
        if path.suffix=='.gz':
            with gzip.open(path,'rb') as f:
                raw=f.read(64*1024**2+1)
            p.need(len(raw)<=64*1024**2,'public_gzip_expansion_bound')
        else:raw=path.read_bytes()
        if p.SUSPICIOUS.search(raw):suspected.append(item['target'])
        selected.append(item['source'])
    p.need(not suspected,'public_credential_shape_detected')
    for value in selected+[plan['sourceArchive'],plan['writerPin'],plan['independent49AuditPin']]:p.verify(value)
    text=(p.DOC/'controls.stderr.txt').read_bytes()
    text=text.decode('utf-16' if text.startswith(b'\xff\xfe') else 'utf-8-sig')
    p.need('Ran 3 tests' in text and text.rstrip().endswith('OK'),'actual_F_controls_incomplete')
    controls_pin=p.save_new(p.DOC/'controls.json',dict(protocol='tb-real-package-native-controls-v1',validated=True,
        actualPass=3,actualFail=0,childExit=0,sourcePin=p.pin(SOURCE),testPin=p.pin(ROOT/'test/tb_real_pilot_package_test.py'),
        stdoutPin=p.pin(p.DOC/'controls.stdout.txt'),stderrPin=p.pin(p.DOC/'controls.stderr.txt'),
        controlScope='Own F regular file fsync/copy/readback, real fsync EBADF partial preservation and strict TB/private path selection',
        DProductionWrites=0,modelCalls=0,graderCalls=0,DockerCalls=0,originalSqliteOpened=False))
    audit=p.load(plan['independent49AuditPin']['path'])
    review=dict(protocol='tb-real-nginx-handoff-readiness-v1',validated=True,planPin=plan_pin,writerPin=p.pin(SOURCE),
        reviewerPin=p.pin(__file__),controlsPin=controls_pin,directInputPinsBeforeAfter=selected,
        currentSourceArchiveBeforeAfterPin=plan['sourceArchive'],original49AuditPin=plan['independent49AuditPin'],
        selectedSourceMembers=len(plan['zipMembers']),excludedArchiveMembers=plan['excludedArchiveSourceMemberCount'],
        noForeignBenchmarkSpecificArchivePaths=True,publicFileCount=len(selected),publicRegexSuspicionCount=0,
        exactCredentialRescanPerformed=False,privateConfigAndSqliteExcluded=True,sourceArchiveBytes=plan['sourceArchive']['bytes'],
        projectedDirectBytes=plan['projectedPublicCopyBytes'],sourceExpandedBytes=plan['selectedZipExpandedBytes'],
        safeDPackageUpperBytes=plan['safePackageUpperBytes'],reserveDBytes=p.RESERVE_D,maximumPackageBytes=p.MAX_PACKAGE,
        proposedDTarget=plan['proposedTarget'],productionPackageCreated=False,modelCalls=0,graderCalls=0,DockerCalls=0,
        originalSqliteOpened=False,oldSecretScope=audit['secretScan'],
        limitations=['This readiness is not a D copy certificate; Root must review exact add-only target/source/plan.',
                     'Regex public-body scan is not an exact-value check for unavailable secrets.',
                     'Source ZIP contains4194 already TB/shared-dependency-only selected paths. Rebuilt ZIP is still explicitly derived.',
                     'Runtime image bodies are not bundled; source/runtime/dependency identities and actual evidence are.',
                     'No new run, full89 score, equal-budget causal claim or new model authorization.'])
    review_pin=p.save_new(p.DOC/'review.json',review)
    commands=f"""$ErrorActionPreference='Stop'
& 'D:/ProgramData/anaconda3/python.exe' -B -X utf8 '{SOURCE}' --mode apply --plan '{p.DOC/'plan.json'}' --plan-sha '{plan_pin['sha256']}' --source-sha '{p.pin(SOURCE)['sha256']}' --target '{plan['proposedTarget']}'
# After natural successful copy only, offline verification (no network/model/grader):
& 'D:/ProgramData/anaconda3/python.exe' -B -X utf8 '{Path(plan['proposedTarget'])/'verification/verify-package.py'}'
"""
    command_pin=p.save_new(p.DOC/'root-commands.ps1.txt',commands)
    print(json.dumps({'review':review_pin,'controls':controls_pin,'commands':command_pin,'source':p.pin(SOURCE),
        'files':len(selected),'archiveMembers':len(plan['zipMembers']),'safeUpper':plan['safePackageUpperBytes'],'DTarget':plan['proposedTarget']}))

if __name__=='__main__':main()
