"""Descriptor-bound original task build through the existing remote primitive.

The original generic asset600 interface is untouched. This typed native stage
uses its signed descriptor clock under the same absolute parent deadline.
SQLite below is new owned evidence, never the shared scheduler database.
"""
import argparse,base64,hashlib,json,os,pathlib,re,sqlite3,time,urllib.request,urllib.error
from native_process import pin,capture
import _bench_original_owned_guard as guard
from server_owned_asset import SERVER
from remote_native_capture import REMOTE_CAPTURE
from dockerfile_source_binding import normalize_shell_heredocs

ROOT=pathlib.Path.cwd().resolve()


def checked(value):
    assert pin(value['path'])==value,'original_task_build_source_pin_changed'
    return pathlib.Path(value['path'])


def validate_request(request):
    descriptor_path=checked(request['originalDescriptorPin'])
    descriptor=json.loads(descriptor_path.read_bytes())
    task=request['taskId'];assert descriptor['taskId']==task
    environment=descriptor['originalResources']['environment']
    seconds=environment['build_timeout_sec']
    assert isinstance(seconds,(int,float)) and int(seconds)==seconds and 0<seconds<=12000
    assert type(request['originalBuildSeconds'])is int and request['originalBuildSeconds']==seconds,'exact_original_task_build_clock'
    if request['neutralOnly']:
        assert task=='zero-model-owned-sb-asset' and descriptor['protocol']=='bench-neutral-original-build-descriptor-v1'
        assert descriptor['noBenchContent'] is True and seconds<=600
    else:
        expected=ROOT/'docs/repair-2026-10-10/full-f-rerun/skillsbench/task-descriptors'/(task+'.json')
        assert descriptor_path.resolve()==expected.resolve(),'actual_canonical_task_descriptor_required'
    resource=request['resource']
    assert resource==dict(bench='skillsbench',slots=1,cpu=environment['cpus'],memoryMb=environment['memory_mb'],growthBytes=environment['storage_mb']*1024**2)
    assert environment.get('gpus',0)==0 and environment['os']=='linux'
    assert request['operation']=='build' and type(request['neutralCleanup'])is bool
    assert not request['neutralCleanup'] or request['neutralOnly']
    assert re.fullmatch('[a-f0-9]{32}',request['nonce']) and re.fullmatch('sha256:[a-f0-9]{64}',request['baseImage'])
    expected=request['expectedBaseIdentity'];assert expected['Id']==request['baseImage'] and expected['Os']=='linux' and expected['Architecture']=='amd64'
    original=checked(request['originalDockerfilePin']).read_bytes()
    source_members={row['path']:row for row in descriptor['environmentSource']['files']}
    assert request['originalDockerfilePin']['bytes']==source_members['Dockerfile']['bytes'] and request['originalDockerfilePin']['sha256']==source_members['Dockerfile']['sha256']
    seen=set();files=[]
    for row in request['files']:
        name=pathlib.PurePosixPath(row['relative']);assert name.parts and not name.is_absolute() and '..'not in name.parts and str(name)not in seen
        seen.add(str(name));path=checked(row['pin']);assert not path.is_symlink() and not path.is_junction()
        body=path.read_bytes();assert len(body)==row['pin']['bytes'] and hashlib.sha256(body).hexdigest()==row['pin']['sha256']
        if str(name)=='Dockerfile':
            bound_body=checked(request['boundOriginalDockerfilePin']).read_bytes() if request.get('executionDockerfileNormalizationPin') else body
            first,rest=bound_body.split(b'\n',1);old_first,old_rest=original.split(b'\n',1)
            assert rest.replace(b'\r\n',b'\n')==old_rest.replace(b'\r\n',b'\n') and first.strip()==b'FROM '+request['baseImage'].encode(),'only_original_immutable_from_binding_allowed'
            assert old_first.strip().upper().startswith(b'FROM ')
            if request.get('executionDockerfileNormalizationPin'):
                audit=json.loads(checked(request['executionDockerfileNormalizationPin']).read_bytes())
                recomputed=normalize_shell_heredocs(bound_body.decode(),request)
                assert audit==recomputed and audit['dockerfile'].encode()==body and audit['changes'],'exact_accepted_heredoc_normalization_required'
        else:
            member=source_members[str(name)];assert (len(body),row['pin']['sha256'])==(member['bytes'],member['sha256'])
        files.append(dict(relative=str(name),bytes=len(body),sha256=row['pin']['sha256'],base64=base64.b64encode(body).decode()))
    assert seen==set(source_members) and sum(row['bytes']for row in files)<=resource['growthBytes']
    if environment['network_mode']=='no-network':
        assert request['network']=='none' and not request.get('networkPolicyPin');network=['--network','none']
    else:
        assert environment['network_mode']=='public' and request['network']=='default'
        policy=json.loads(checked(request['networkPolicyPin']).read_bytes())
        assert policy['protocol']=='bench-original-task-public-build-network-v1' and policy['originalDescriptorPin']==request['originalDescriptorPin']
        assert policy['originalBuildSeconds']==seconds and policy['proxyUrl']=='http://172.30.89.1:10809'
        assert policy['hostNetworkAdded'] is False and policy['hostMountAdded'] is False and policy['credentialsAdded'] is False
        for proof in policy['trustedExistingProxyEvidencePins']:checked(proof)
        assert policy['trustedExistingProxyEvidencePins']
        network=['--network','default']
        for key in ['HTTP_PROXY','HTTPS_PROXY','http_proxy','https_proxy']:network+=['--build-arg',key+'='+policy['proxyUrl']]
        for key in ['NO_PROXY','no_proxy']:network+=['--build-arg',key+'=localhost,127.0.0.1']
    return descriptor,files,network


def run_original_build(request,output):
    descriptor,files,network=validate_request(request)
    assert _bench_authorized_history(request['taskId'])is True
    resource=request['resource'];guard.require_lease(resource['memoryMb'],resource['growthBytes'],'skillsbench',1);guard.guard()
    config=json.loads(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes())
    bound=config['originalTaskBuild'];assert bound['requestPin']['sha256']==request['_requestSha256']
    parent=pathlib.Path(bound['parentOutput']).resolve();output=pathlib.Path(output).resolve();assert output.is_relative_to(parent)
    limit=json.loads((parent/'absolute-deadline.json').read_bytes());assert limit['pid']==int(os.environ['NOVAEVE_RESOURCE_LEASE_PID'])
    deadline=limit['deadline']/1000;remaining=deadline-time.time();assert remaining>0
    # Neutral coordination may be600 while its fixture build is smaller. Genuine
    # task whole-stage3600 is never reset when entering this child.
    deadline=min(deadline,time.time()+request['originalBuildSeconds'])
    output.mkdir(parents=True,exist_ok=False)
    r={**request,'files':files,'deadline':deadline,'typedBuildNetworkArguments':network,'taskBuildTimeoutSeconds':request['originalBuildSeconds']}
    server=SERVER
    old="return captured_remote(docker+args,min(600,remaining))";new="return captured_remote(docker+args,min(r['taskBuildTimeoutSeconds'],remaining))";assert server.count(old)==1;server=server.replace(old,new)
    old="['build','--network',r['network'],'--memory'";new="['build',*r['typedBuildNetworkArguments'],'--memory'";assert server.count(old)==1;server=server.replace(old,new)
    old="before=json.loads(run(['image','inspect',r['baseImage']]))[0];assert before['Id']==r['baseImage']"
    new=old+"\n   assert all(before[k]==r['expectedBaseIdentity'][k]for k in ['Id','Config','RootFS','Os','Architecture']),'exact_original_base_full_identity'";assert server.count(old)==1;server=server.replace(old,new)
    compile(REMOTE_CAPTURE+'\nimport re\n'+server,'<descriptor-bound-original-server>','exec')
    program=REMOTE_CAPTURE+'\nimport re\n'+server+'\nasset(json.loads('+repr(json.dumps(r))+'))\n'
    (output/'server-program.bound.py').write_text(program)
    ssh=checked(request['sshPin']);execution=capture([str(ssh),'-T','-o','BatchMode=yes','-o','ConnectTimeout=20','-o','ClearAllForwardings=yes','novaeve','python3','-'],output/'original-build-transport',max(.1,deadline-time.time()),input_bytes=program.encode())
    assert execution['closeObserved'] and execution['exitCode']==0 and not execution['timedOut'] and execution['error']is None,'actual_original_task_build_transport_failed'
    frames=[json.loads(line)for line in pathlib.Path(execution['stdoutPin']['path']).read_text().splitlines()if line.strip()]
    commands=[row['remoteCommand']for row in frames if 'remoteCommand'in row];result=frames[-1]
    assert result['complete'] and result['temporaryContextRemoved'] and commands
    database=sqlite3.connect(output/'owned-native.sqlite')
    database.execute('create table command(id integer primary key,json text not null)');database.execute('create table actor(cid text primary key,closed integer not null)')
    raw_pins=[]
    for index,row in enumerate(commands):
        assert row['pid'] and row['incarnation'] and row['closeObserved'] and row['exitCode']==0 and not row['timedOut'] and row['error']is None
        for key in ['stdout','stderr']:
            stream=row[key];raw=base64.b64decode(stream['rawBase64']);assert len(raw)==stream['bytes'] and hashlib.sha256(raw).hexdigest()==stream['sha256']
            path=output/('remote-%04d.%s'%(index,key))
            with path.open('xb')as file:file.write(raw)
            row[key]=dict(path=str(path),bytesStored=len(raw),bytesObserved=len(raw),sha256=stream['sha256']);raw_pins.append(pin(path))
        database.execute('insert into command(json)values(?)',(json.dumps(row),))
    intermediate=result.get('intermediateContainers',[]);assert intermediate and set(intermediate)<=set(result['removedIntermediateContainers'])
    host=os.environ['DOCKER_HOST'].replace('tcp:','http:')
    for cid in set(intermediate):
        try:urllib.request.urlopen(host+'/containers/'+cid+'/json',timeout=10);raise AssertionError('original_build_intermediate_present')
        except urllib.error.HTTPError as error:assert error.code==404
        database.execute('insert into actor(cid,closed)values(?,1)',(cid,))
    database.commit();database.close()
    image=result['image']
    if request['neutralCleanup']:
        try:urllib.request.urlopen(host+'/images/'+image+'/json',timeout=10);raise AssertionError('neutral_build_image_present')
        except urllib.error.HTTPError as error:assert error.code==404
    else:
        fresh=json.load(urllib.request.urlopen(host+'/images/'+image+'/json',timeout=10));assert all(fresh[k]==result['identity'][k]for k in ['Id','Config','RootFS','Os','Architecture'])
    guard.guard()
    value=dict(complete=True,taskId=request['taskId'],originalDescriptorPin=request['originalDescriptorPin'],originalBuildSeconds=request['originalBuildSeconds'],parentAbsoluteDeadline=limit['deadline'],actualBuildDeadline=deadline,originalTaskBuildClockBound=True,resource=resource,actualTransportPin=pin(output/'original-build-transport.json'),rawStreamPins=raw_pins,serverResult=result,descriptorBoundStageOnly=True,formalReady=False,modelCalls=0,referenceCalls=0,gradeCalls=0)
    (output/'result.json').write_text(json.dumps(value,indent=2)+'\n')
    return value


def main():
    p=argparse.ArgumentParser();p.add_argument('--request',required=True);p.add_argument('--output',required=True);a=p.parse_args()
    config=json.loads(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes());binding=config['originalTaskBuild']['requestPin'];path=checked(binding);assert path.resolve()==pathlib.Path(a.request).resolve()
    request=json.loads(path.read_bytes());request['_requestSha256']=binding['sha256'];run_original_build(request,a.output)


if __name__=='__main__':main()
