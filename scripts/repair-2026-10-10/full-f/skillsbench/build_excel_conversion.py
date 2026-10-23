"""Prepare pristine conversion and private assertion namespaces, zero models.

Invoke only through a wrapper holding the shared heavy-container resource.
These new profiles are not published into the active frozen preparation queue.
"""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import uuid
from prepare import HOME,VENDOR,public,save,utc
from build_environment import DOCKER,ENV
from bounded_child import run
from excel_conversion_protocol import PROFILES
from apt_build_proxy import build_args as apt_build_args

def private_runner(source):
    old="    assert set(incoming)=={'artifacts'} and len(incoming['artifacts'])<=1"
    new="    assert set(incoming)=={'artifacts','conversion'} and len(incoming['artifacts'])<=1"
    assert source.count(old)==1;source=source.replace(old,new)
    marker="    for pin in trusted['files']:\n        assert hashlib.sha256(Path(pin['path']).read_bytes()).hexdigest() == pin['sha256']"
    addition='''    # Conversion occurs in a separate immutable image without hidden tests.
    # Here only source-bound ordinary CSV bytes enter the private namespace.
    if '--collect' not in sys.argv:
        sys.path.insert(0,'/opt/objrun')
        from excel_conversion_protocol import decode,PROFILES
        workbook=Path(trusted['outputPath'])
        source_sha=hashlib.sha256(workbook.read_bytes()).hexdigest() if workbook.exists() else hashlib.sha256(b'').hexdigest()
        conversion=decode(json.dumps(incoming['conversion']).encode(),trusted['taskId'],source_sha)
        assert conversion['sourceExists']==workbook.exists() and conversion['converterSha256']==trusted['converterSha256']
        prefix=Path(PROFILES[trusted['taskId']]['csvPrefix'])
        for file in prefix.parent.glob('sheet.csv.*'):
            assert file.is_file() and not file.is_symlink();file.unlink()
        for row in conversion['derivedCsv']:
            destination=Path(row['path']);assert not destination.is_symlink()
            destination.write_bytes(base64.b64decode(row['base64'],validate=True));destination.chmod(0o644)
    else:
        assert incoming['conversion'] is None
'''
    assert source.count(marker)==2
    # Verify immutable sources before importing the helper/inserting data.
    source=source.replace(marker,marker+'\n'+addition,1)
    source=source.replace("'protocol':'skillsbench-full-f-private-data-evaluation-v2'","'protocol':'skillsbench-full-f-private-excel-evaluation-v1'")
    source=source.replace("'artifactInputs':[", "'formulaConversion':None if collect else {'sourceSha256':conversion['sourceSha256'],'converterExitCode':conversion['converterExitCode'],'converterSha256':conversion['converterSha256'],'derivedCsv':[{'path':r['path'],'sha256':r['sha256']} for r in conversion['derivedCsv']]},\n        'artifactInputs':[")
    return source

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',required=True,choices=PROFILES);a=parser.parse_args()
    row=json.loads((HOME/'task-descriptors'/(a.task+'.json')).read_bytes());original=VENDOR/'tasks'/a.task;before=public.tree(original)
    home=HOME/'excel-environment-preparation'/a.task/uuid.uuid4().hex;home.mkdir(parents=True)
    names=('build_excel_conversion.py','excel_conversion_protocol.py','pristine_excel_conversion.py','private_eval_v2.py','bounded_child.py')
    pins=[public.pin(Path(__file__).with_name(name)) for name in names];commands=[];owned=[]
    result={'protocol':'skillsbench-isolated-excel-images-v1','taskId':a.task,'createdAtUtc':utc(),'imagesBuilt':False,'modelCalls':0,'formalScoreCertified':False,'sourcePins':pins}
    serial=0
    def command(argv,timeout,stdin=None):
        nonlocal serial
        serial+=1;prefix=home/('command-%03d'%serial)
        outcome=run([DOCKER,*argv],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,stdin,stdout_limit=32*1024**2,stderr_limit=4*1024**2)
        pin=save(prefix.with_suffix('.json'),{'argv':[DOCKER,*argv],**outcome,'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0},True);commands.append(pin)
        if outcome['exitCode'] or outcome['faults']:raise RuntimeError('excel environment operation failed: '+pin['path'])
        return prefix.with_suffix('.stdout').read_bytes()
    def image(tag,context,role):
        command(['build','--force-rm=true','--pull=false',*apt_build_args(),'--label','objrun.skb.role='+role,'--label','objrun.skb.nonce='+home.name,'--label','objrun.skb.task-id='+a.task,'-t',tag,str(context)],row['originalResources']['environment']['build_timeout_sec'])
        built_image=json.loads(command(['image','inspect',tag],30))[0]
        assert not any(value.lower().startswith(('http_proxy=','https_proxy=')) for value in built_image['Config'].get('Env',[]))
        return built_image
    try:
        pristine=image('objrun-skb-excel-pristine:'+home.name,original/'environment','full-f-excel-pristine')
        e=row['originalResources']['environment'];limits=['--network','none','--cap-drop','ALL','--security-opt','no-new-privileges','--memory',str(e['memory_mb']*1024**2),'--memory-swap',str(e['memory_mb']*1024**2),'--cpus',str(e['cpus'])]
        witness_code="import hashlib,json;from pathlib import Path;p=Path("+repr(PROFILES[a.task]['workbook'])+");print(json.dumps({'converterSha256':hashlib.sha256(Path('/usr/bin/ssconvert').read_bytes()).hexdigest(),'initialWorkbookExists':p.exists(),'initialWorkbookSha256':hashlib.sha256(p.read_bytes() if p.exists() else b'').hexdigest()}))"
        cid=command(['create','--read-only',*limits,'--label','objrun.skb.role=full-f-excel-binary-witness','--label','objrun.skb.nonce='+home.name,'--entrypoint','python3',pristine['Id'],'-I','-B','-c',witness_code],30).decode().strip()
        assert len(cid)==64 and all(c in '0123456789abcdef' for c in cid);owned.append(cid)
        witness=json.loads(command(['start','-a',cid],30));binary_sha=witness['converterSha256'];assert len(binary_sha)==64 and all(c in '0123456789abcdef' for c in binary_sha)
        command(['rm',cid],30);owned.remove(cid)
        profile=PROFILES[a.task];parent=str(Path(profile['workbook']).parent);conversion=home/'conversion-context';conversion.mkdir()
        for name in ('pristine_excel_conversion.py','excel_conversion_protocol.py'):shutil.copyfile(Path(__file__).with_name(name),conversion/name)
        config={'taskId':a.task,'profile':profile,'workingDirectory':row['workdir'],'fixtureDestination':parent,'converterSha256':binary_sha,'originalVerifierSeconds':row['originalResources']['verifier']['timeout_sec'],
            'sourcePins':[{'path':'/opt/objrun/'+name,'sha256':public.pin(conversion/name)['sha256']} for name in ('pristine_excel_conversion.py','excel_conversion_protocol.py')]}
        save(conversion/'converter.json',config)
        (conversion/'Dockerfile').write_text('\n'.join(['FROM '+pristine['Id'],'RUN mkdir -p /opt/objrun/public-fixtures && cp -a '+parent+'/. /opt/objrun/public-fixtures/',
            'COPY pristine_excel_conversion.py excel_conversion_protocol.py converter.json /opt/objrun/',
            'ENTRYPOINT ["python3","-I","-B","/opt/objrun/pristine_excel_conversion.py"]','']))
        converter=image('objrun-skb-excel-conversion:'+home.name,conversion,'full-f-excel-conversion')
        private=home/'private-context';private.mkdir();shutil.copytree(original/'verifier',private/'verifier')
        (private/'private_eval.py').write_text(private_runner(Path(__file__).with_name('private_eval_v2.py').read_text()),encoding='utf-8')
        shutil.copyfile(conversion/'excel_conversion_protocol.py',private/'excel_conversion_protocol.py')
        (private/'empty.ini').write_text('[pytest]\n')
        trusted={'taskId':a.task,'outputPath':profile['workbook'],'workingDirectory':row['workdir'],'fixtureDestination':parent,'fixtureSource':'/opt/objrun/public-fixtures','converterSha256':binary_sha,
            'files':[{'path':'/verifier/'+p.relative_to(private/'verifier').as_posix(),'sha256':public.pin(p)['sha256']} for p in sorted((private/'verifier').rglob('*')) if p.is_file()]+[{'path':'/opt/objrun/'+name,'sha256':public.pin(private/name)['sha256']} for name in ('private_eval.py','excel_conversion_protocol.py')]}
        save(private/'trusted.json',trusted)
        (private/'Dockerfile').write_text('\n'.join(['FROM '+pristine['Id'],
            'RUN python3 -m venv --system-site-packages /opt/objrun-verifier && /opt/objrun-verifier/bin/pip install --no-cache-dir pytest==8.4.1 pytest-json-ctrf==0.3.5 openpyxl==3.1.5 defusedxml==0.7.1',
            'RUN mkdir -p /opt/objrun/public-fixtures && cp -a '+parent+'/. /opt/objrun/public-fixtures/',
            'COPY verifier /verifier','COPY private_eval.py excel_conversion_protocol.py trusted.json empty.ini /opt/objrun/',
            'ENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1','ENTRYPOINT ["/opt/objrun-verifier/bin/python","-I","-B","/opt/objrun/private_eval.py"]','']))
        private_image=image('objrun-skb-excel-private:'+home.name,private,'full-f-excel-private')
        assert len({pristine['Id'],converter['Id'],private_image['Id']})==3
        assert public.tree(original)==before and all(public.pin(Path(p['path']))==p for p in pins)
        result.update(imagesBuilt=True,candidateImageId=pristine['Id'],conversionImageId=converter['Id'],privateImageId=private_image['Id'],
            converterSha256=binary_sha,initialWorkbookExists=witness['initialWorkbookExists'],initialWorkbookSha256=witness['initialWorkbookSha256'],profile=profile,workingDirectory=row['workdir'],artifactTmpfsParent=parent,
            artifactTmpfsBytes=max(256*1024**2,row['environmentSource']['fileBytes']+32*1024**2),originalResources=row['originalResources'],
            privateRunnerPin=public.pin(private/'private_eval.py'),sourceBeforeAfterEqual=True)
    except Exception as error:result['failure']={'type':type(error).__name__,'detail':str(error)};raise
    finally:
        for cid in owned[:]:
            try:command(['rm','-f',cid],30);owned.remove(cid)
            except Exception:pass
        result.update(commandPins=commands,ownedContainersRemaining=len(owned),ownedContainerIds=owned)
        pin=save(home/'result.json',result,True);save(HOME/'excel-environment-preparation'/a.task/'latest.json',{'builtImagesPin':pin});print(json.dumps({'resultPin':pin,'imagesBuilt':result['imagesBuilt'],'modelCalls':0}))

if __name__=='__main__':main()
