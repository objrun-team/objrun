"""Original candidate and separate trusted private image preparation, no models."""
import argparse
import time
from datetime import datetime,timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import uuid
import re
from verifier_dependency_scope import uvx_verifier_requirements
from prepare import ROOT,HOME,VENDOR,public,save,utc
from artifact_policies import policy as artifact_policy,runner_name
from bounded_child import run as bounded_run
from apt_build_proxy import build_args as apt_build_args

DOCKER='D:/Program/resources/bin/docker.exe'
ENV={k:v for k,v in os.environ.items() if k in ('SystemRoot','WINDIR','PATH','PATHEXT','TEMP','TMP','USERPROFILE','APPDATA','LOCALAPPDATA','PROGRAMDATA')}
ENV['DOCKER_HOST']='npipe:////./pipe/dockerDesktopLinuxEngine'

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--task',required=True);a=parser.parse_args()
    row=json.loads((HOME/'task-descriptors'/ (a.task+'.json')).read_bytes())
    # General code/execution tasks require their separate untrusted sandbox.
    # Existing reviewed data policies are the first environments to prepare.
    assert a.task=='mario-coin-counting'
    policy={'format': 'ordinary CSV and grayscale PNG data', 'output': '/root/counting_results.csv', 'kind': 'files', 'outputs': [{'path': '/root/counting_results.csv', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_001.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_002.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_003.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_004.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_005.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_006.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_007.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}, {'path': '/root/keyframes_008.png', 'kind': 'file', 'maximumFiles': 1, 'maximumBytes': 8388608}], 'maximumFiles': 9, 'maximumBytes': 75497472, 'maximumSingleFileBytes': 8388608, 'approvedDataOnly': True, 'inputs': [], 'origin': 'Exact original CSV and timeline keyframe PNG paths; private original OpenCV and pandas verifier; original tests and answer fixture unchanged; full cold required'}
    if not policy:raise ValueError('ordinary_artifact_policy_review_pending')
    if row['verifierExecutionCalls'] and a.task!='court-form-filling':
        if a.task!='mario-coin-counting':raise ValueError('candidate_execution_adapter_pending')
        calls=row['verifierExecutionCalls'];assert len(calls)==1 and {c['literalArgv0'] for c in calls}=={'glm'} and all(c['function']=='subprocess.run' and c['shellTrue'] is False and c['source']=='test_outputs.py' for c in calls)

    nonce=uuid.uuid4().hex;home=HOME/'environment-preparation'/a.task/nonce;home.mkdir(parents=True)
    assert a.task=='mario-coin-counting','scoped_original_glm_preparation_only'
    cli_config=home/'private-docker-cli';cli_config.mkdir()
    save(cli_config/'config.json',{'cliPluginsExtraDirs':['D:/Program/resources/cli-plugins']},True)
    ENV['DOCKER_CONFIG']=str(cli_config);ENV['DOCKER_BUILDKIT']='1'
    plugin=Path('D:/Program/resources/cli-plugins/docker-buildx.exe');assert plugin.is_file()
    save(home/'private-build-engine.json',{'privateConfigPin':public.pin(cli_config/'config.json'),'buildxPluginPin':public.pin(plugin),'globalDockerSettingsUnmodified':True,'originalDockerfilePackagesAndBudgetsUnmodified':True,'modelCalls':0},True)
    prep_started=time.monotonic()
    serial=0
    def command(args,timeout):
        nonlocal serial
        remaining=3600-(time.monotonic()-prep_started);assert remaining>0,'heavy_preparation_60min_expired';timeout=min(timeout,remaining)
        serial+=1;prefix=home/('command-%03d'%serial);start=utc()
        outcome=bounded_run([DOCKER,*args],ENV,prefix.with_suffix('.stdout'),prefix.with_suffix('.stderr'),timeout,stdout_limit=32*1024**2,stderr_limit=4*1024**2)
        save(prefix.with_suffix('.json'),{'argv':[DOCKER,*args],**outcome,'parentPid':os.getpid(),'startedAtUtc':start,'finishedAtUtc':utc(),
            'stdoutPin':public.pin(prefix.with_suffix('.stdout')),'stderrPin':public.pin(prefix.with_suffix('.stderr')),'modelCalls':0})
        if outcome['exitCode'] or outcome['faults']:raise RuntimeError('Docker preparation command failed; see '+str(prefix.with_suffix('.json')))
        return prefix.with_suffix('.stdout').read_bytes()
    source=VENDOR/'tasks'/a.task;before=public.tree(source)
    candidate_tag='objrun-skb-full-f-candidate:'+a.task+'-'+nonce
    latest=HOME/'environment-preparation'/a.task/'latest.json'
    previous=json.loads(Path(json.loads(latest.read_bytes())['builtImagesPin']['path']).read_bytes()) if latest.exists() else None
    candidate_cache=HOME/'environment-preparation'/a.task/'candidate-cache.latest.json'
    if previous is None and candidate_cache.exists():
        cp=json.loads(candidate_cache.read_bytes())['imageCachePin'];assert public.pin(Path(cp['path']))==cp;previous=json.loads(Path(cp['path']).read_bytes())
    if previous and previous['environmentTreeSha256']==row['environmentSource']['treeSha256']:
        candidate=json.loads(command(['image','inspect',previous['candidateImageId']],30))[0]
    else:
        command(['build','--force-rm=true','--pull=false',*apt_build_args(),'--label','objrun.skb.role=full-f-pristine','--label','objrun.skb.task-id='+a.task,
                 '-t',candidate_tag,str(source/'environment')],3600)
        candidate=json.loads(command(['image','inspect',candidate_tag],30))[0]
    command(['image','tag',candidate['Id'],candidate_tag],30)
    tagged=json.loads(command(['image','inspect',candidate_tag],30))[0];assert tagged['Id']==candidate['Id']
    candidate_pin=save(home/'candidate-image-cache.json',{'taskId':a.task,'candidateImageId':candidate['Id'],'environmentTreeSha256':row['environmentSource']['treeSha256'],'candidateTag':candidate_tag,'originalTaskSourcePin':public.pin(source/'environment'/'Dockerfile'),'pristineCandidateOnly':True,'modelCalls':0},True)
    save(candidate_cache,{'imageCachePin':candidate_pin})
    context=home/'private-context';context.mkdir();shutil.copytree(source/'verifier',context/'verifier')
    runner_path=Path(__file__).with_name('private_eval_multi.py');runner_pin=public.pin(runner_path)
    shutil.copyfile(runner_path,context/'private_eval.py')
    if public.pin(context/'private_eval.py')['sha256']!=runner_pin['sha256']:raise ValueError('Private runner copy/source drift')
    output_parent=str(Path(policy['output']).parent).replace('\\','/')
    output_policies=policy.get('outputs',[{'path':policy['output'],'kind':'file','maximumFiles':1,'maximumBytes':8*1024**2}])
    parents=sorted(set(o['path'] if o['kind']=='directory' else str(Path(o['path']).parent).replace('\\','/') for o in output_policies))
    parents=[p for p in parents if not any(p.startswith(other+'/') for other in parents if other!=p)]
    if any(p in ('/','/verifier','/usr','/bin','/etc','/opt') for p in parents):raise ValueError('Output tmpfs would replace trusted namespace')
    fixture_copies=[{'source':'/opt/objrun/public-fixtures-'+str(i),'destination':parent} for i,parent in enumerate(parents)]
    trusted={'taskId':a.task,'outputPath':policy['output'],'workingDirectory':row['workdir'],'fixtureDestination':output_parent,'fixtureSource':'/opt/objrun/public-fixtures',
        'files':[{'path':'/verifier/'+p.relative_to(context/'verifier').as_posix(),'sha256':hashlib.sha256(p.read_bytes()).hexdigest()} for p in sorted((context/'verifier').rglob('*')) if p.is_file()]}
    trusted['files'].append({'path':'/opt/objrun/private_eval.py','sha256':hashlib.sha256((context/'private_eval.py').read_bytes()).hexdigest()})
    trusted.update(outputPolicies=output_policies,fixtureCopies=fixture_copies,maximumArtifactBytes=policy['maximumBytes'],maximumArtifactFiles=policy['maximumFiles'])
    save(context/'trusted.json',trusted)
    (context/'empty.ini').write_text('[pytest]\n',encoding='utf-8')
    # Identical pinned test/dependency requirements as the ordinary v2 data
    # runtime; all installation occurs before candidate output is admitted.
    deps=['pytest==8.3.5','pytest-json-ctrf==0.3.5','openpyxl==3.1.5','pypdf==5.1.0','python-docx==1.1.2','lxml==5.3.0','defusedxml==0.7.1','six==1.17.0','rapidfuzz==3.14.3','numpy==1.26.4','pandas==2.2.2']
    # Preserve exact official package pins when present; original pristine
    # image packages are visible in this immutable private venv as well.
    exact={token.split('==',1)[0].lower():token for token in row['originalPackageTokens']}
    deps=['pytest==8.3.5','pytest-json-ctrf==0.3.5',*exact.values()]
    # An original uvx pytest invocation has its own dependency namespace.
    # Dockerfile install steps describe the candidate environment, and merging
    # them here changes official verifier semantics (e.g. NumPy/OpenCV).
    original_test=(source/'verifier/test.sh').read_text(encoding='utf-8')
    verifier_scope=None
    if re.search(r'^\s*uvx\s',original_test,re.MULTILINE):
        verifier_scope=uvx_verifier_requirements(original_test)
        deps=verifier_scope['primaryRequirements']
    venv_site_option='' if verifier_scope else '--system-site-packages '
    verifier_fixture_steps=[]
    if verifier_scope:
        for source_path,destination in re.findall(r'^cp\s+(/verifier/[A-Za-z0-9_.-]+)\s+(/root/[A-Za-z0-9_.-]+)\s*$',original_test,re.MULTILINE):
            original_file=context/'verifier'/Path(source_path).name
            assert original_file.is_file() and not original_file.is_symlink()
            verifier_fixture_steps.append('RUN cp '+source_path+' '+destination)
    # The Civ6 verifier and vendored rule modules use only the standard library
    # plus its original pytest/CTRF pins. Its pristine Python image has venv;
    # installing unrelated PDF tools adds an unnecessary network failure gate.
    if a.task=='civ6-adjacency-optimizer':
        assert exact.get('pytest')=='pytest==8.3.4' and exact.get('pytest-json-ctrf')=='pytest-json-ctrf==0.3.5'
        deps=list(exact.values())
    if a.task=='threejs-to-obj':
        # Original input and generator only; never a solver-mutated scene.
        scene=source/'environment/data/object.js';generator=source/'verifier/gen_ground_truth.mjs'
        assert public.pin(scene)['sha256']==next(p['sha256'] for p in row['environmentSource']['files'] if p['path']=='data/object.js')
        assert 'three@0.175.0' in (source/'environment/Dockerfile').read_text() and "'/root/data/object.js'" in generator.read_text()
        shutil.copyfile(scene,context/'original-scene.js')
        trusted['files'].append({'path':'/root/data/object.js','sha256':hashlib.sha256(scene.read_bytes()).hexdigest()})
        save(context/'trusted.json',trusted)
        (context/'Dockerfile').write_text('\n'.join([
            'FROM node:20-bookworm-slim',
            'RUN apt-get update && apt-get install -y --no-install-recommends python3 python3-venv && rm -rf /var/lib/apt/lists/*',
            'RUN python3 -m venv /opt/objrun-verifier && /opt/objrun-verifier/bin/pip install --no-cache-dir pytest==8.4.1 pytest-json-ctrf==0.3.5 numpy==2.1.3',
            'WORKDIR /root',
            'RUN npm init -y && npm pkg set type=module && npm install --save-exact three@0.175.0',
            'COPY original-scene.js /root/data/object.js',
            'COPY verifier /verifier',
            'RUN cp /verifier/gen_ground_truth.mjs /root/gen_ground_truth.mjs && node /root/gen_ground_truth.mjs && rm /root/gen_ground_truth.mjs',
            'RUN mkdir -p /opt/objrun/public-fixtures /root/output',
            'COPY private_eval.py trusted.json empty.ini /opt/objrun/',
            'ENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1',
            'ENTRYPOINT ["/opt/objrun-verifier/bin/python","-I","-B","/opt/objrun/private_eval.py"]','']),encoding='utf-8')
    else:
        private_system_steps=[] if a.task=='civ6-adjacency-optimizer' else ['RUN apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y python3-venv poppler-utils && rm -rf /var/lib/apt/lists/*']
        multi=runner_path.name in ('private_eval_multi.py','private_eval_score.py')
        fixture_steps=['RUN mkdir -p '+f['source']+' '+f['destination']+' && cp -a '+f['destination']+'/. '+f['source']+'/' for f in fixture_copies] if multi else ['RUN mkdir -p /opt/objrun/public-fixtures '+output_parent+' && cp -a '+output_parent+'/. /opt/objrun/public-fixtures/']
        (context/'Dockerfile').write_text('\n'.join(['FROM '+candidate_tag,
            *private_system_steps,
            'RUN python3 -m venv '+venv_site_option+'/opt/objrun-verifier && /opt/objrun-verifier/bin/pip install --no-cache-dir '+' '.join(deps),
            'COPY verifier /verifier',*verifier_fixture_steps,*fixture_steps,
            'COPY private_eval.py trusted.json empty.ini /opt/objrun/',
            'ENV PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONDONTWRITEBYTECODE=1',
            'ENTRYPOINT ["/opt/objrun-verifier/bin/python","-I","-B","/opt/objrun/private_eval.py"]','']),encoding='utf-8')
    private_tag='objrun-skb-full-f-private:'+a.task+'-'+nonce
    command(['build','--force-rm=true','--pull=false',*apt_build_args(),'--label','objrun.skb.role=full-f-private','--label','objrun.skb.task-id='+a.task,
             '-t',private_tag,str(context)],3600)
    private=json.loads(command(['image','inspect',private_tag],30))[0]
    for image in (candidate,private):
        assert not any(value.lower().startswith(('http_proxy=','https_proxy=')) for value in image['Config'].get('Env',[]))
    after=public.tree(source)
    if before!=after or public.pin(runner_path)!=runner_pin:raise ValueError('Official/runner sources changed during actual image build')
    result={'protocol':'skillsbench-full-f-built-images-v1','taskId':a.task,'nonce':nonce,'createdAtUtc':utc(),
        'candidateImageId':candidate['Id'],'privateImageId':private['Id'],'candidateInspect':candidate,'privateInspect':private,
        'sourceBeforeAfterEqual':True,'environmentTreeSha256':row['environmentSource']['treeSha256'],
        'verifierTreeSha256':row['verifierSource']['treeSha256'],'privateRunnerSourcePin':runner_pin,
        'privateContextTrustedPin':public.pin(context/'trusted.json'),'originalResources':row['originalResources'],
        'dataArtifactPolicy':policy,'workingDirectory':row['workdir'],'artifactTmpfsParent':output_parent,'artifactTmpfsBytes':max(256*1024**2,row['environmentSource']['fileBytes']+32*1024**2),
        'artifactTmpfsParents':parents if multi else [output_parent],'outputPolicies':output_policies,
        'verifierDependencyScope':verifier_scope,'verifierFixtureSteps':verifier_fixture_steps,
        'modelCalls':0,'coldControlsReady':False,'formalScoreCertified':False}
    pin=save(home/'built-images.json',result,True);save(HOME/'environment-preparation'/a.task/'latest.json',{'builtImagesPin':pin})
    print(json.dumps({'taskId':a.task,'builtImagesPin':pin,'modelCalls':0}))

if __name__=='__main__':main()
