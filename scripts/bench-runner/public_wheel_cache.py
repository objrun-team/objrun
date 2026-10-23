"""Stage an inert, official-hash wheel cache through the Docker daemon.

Returns only a PIP_CACHE_DIR path. Index access and dependency selection remain
with the original pip command. No candidate program reads bytes onto the host.
"""
import gzip,hashlib,io,json,pathlib,re,tarfile,time,urllib.parse,zipfile,zlib
from pip._vendor import msgpack
from native_process import pin


def checked(value):
    assert pin(value['path'])==value,'public_wheel_cache_pin_changed'
    return pathlib.Path(value['path'])


def validate_cache_policy(policy,task_id):
    assert policy['protocol']=='bench-official-optional-public-wheel-cache-policy-v1'
    assert policy['taskId']==task_id,'public_wheel_cache_exact_case_required'
    assert type(policy['neutralOnly'])is bool
    assert policy['neutralOnly']==(task_id=='zero-model-owned-sb-asset')
    assert policy['originalIndexUrl']=='https://pypi.org/simple'
    assert policy['pipNoIndexEnabled'] is False and policy['originalDependencySelectionForced'] is False
    assert policy['originalCiCommandChanged'] is False and policy['candidateCodeChanged'] is False
    owner=pathlib.Path(policy['ownedArtifactRoot']).resolve()
    root=pathlib.Path(policy['cacheDirectory']).resolve()
    assert root.is_relative_to(owner) and not root.is_symlink() and not root.is_junction()
    proof=json.loads(checked(policy['officialSourceVerificationPin']).read_bytes())
    assert proof['complete'] and proof['cacheOnly'] and proof['noPackageInstalled'] and not proof['qualificationGranted']
    assert proof['originalIndexUrlUnchanged'] and proof['doesNotForceOriginalDependencySelection']
    assert 0<proof['totalBytes']<=policy['maximumBytes']<=64*1024**2
    rows={}
    for row in proof['files']:
        name=row['filename'];assert re.fullmatch(r'[A-Za-z0-9_.+!-]+\.whl',name) and name not in rows
        source=checked(row['pin'])
        assert source.resolve()==root/name and not source.is_symlink() and not source.is_junction()
        metadata=json.loads(checked(row['officialMetadataPin']).read_bytes())
        matches=[x for x in metadata['urls'] if x['filename']==name]
        assert len(matches)==1
        item=matches[0];url=urllib.parse.urlparse(item['url'])
        assert url.scheme=='https' and url.hostname=='files.pythonhosted.org'
        assert item['url']==row['officialUrl'] and item['digests']['sha256']==row['officialSha256']==row['pin']['sha256']
        assert item['size']==row['pin']['bytes']
        rows[name]=row
    assert set(rows)=={f.name for f in root.iterdir()} and sum(x['pin']['bytes']for x in rows.values())==proof['totalBytes']
    return owner,root,proof,rows


def seed_official_pip_cache(command,cid,policy,task_id,session,expected_image,expected_labels,receipt_directory,deadline):
    owner,_,wheel_proof,wheels=validate_cache_policy(policy,task_id)
    proof=json.loads(checked(policy['officialHttpCacheVerificationPin']).read_bytes())
    assert proof['protocol']=='bench-official-immutable-pip-http-cache-source-verification-v1' and proof['complete']
    assert proof['cacheControlFormat']=='cc=4' and proof['originalResponseHeadersUnchanged'] and proof['originalResponseDateAndAgePreserved'] and proof['indexResponsesIncluded'] is False
    assert proof['officialWheelSourceVerificationPin']==policy['officialSourceVerificationPin']
    root=pathlib.Path(proof['cacheDirectory']).resolve();assert root.is_relative_to(owner) and not root.is_symlink() and not root.is_junction()
    expected={};urls=set()
    for row in proof['entries']:
        assert row['wheelFilename'] in wheels and row['kind']in ('wheel','metadata')
        wheel=wheels[row['wheelFilename']];url=wheel['officialUrl']+('.metadata' if row['kind']=='metadata' else '')
        assert row['url']==url and url not in urls;urls.add(url)
        key=hashlib.sha224(url.encode()).hexdigest();relative=pathlib.PurePosixPath('http-v2',*key[:5],key)
        assert row['cacheKey']==key and row['relativePath']==str(relative)
        control=checked(row['entryPin']);body=checked(row['bodyPin'])
        assert control.resolve()==root/str(relative) and body.resolve()==root/(str(relative)+'.body')
        for item in [control,body]:assert not item.is_symlink() and not item.is_junction()
        raw=control.read_bytes();assert raw.startswith(b'cc=4,') and len(raw)<65536
        record=msgpack.loads(raw.split(b',',1)[1],raw=False);response=record['response'];headers={k.lower():v for k,v in response['headers'].items()}
        assert response['status']==200 and response['body']==b'' and record['vary']==row['responseVary']
        assert headers.get('date')==row['originalResponseDate'] and headers.get('age')==row['originalResponseAge'] and headers['cache-control']==row['originalCacheControl'] and 'immutable'in headers['cache-control']
        assert not any(k in headers for k in ['authorization','proxy-authorization','set-cookie'])
        if row['kind']=='wheel':wanted=checked(wheel['pin']).read_bytes()
        else:
            with zipfile.ZipFile(checked(wheel['pin']))as archive:
                names=[n for n in archive.namelist()if n.endswith('.dist-info/METADATA')];assert len(names)==1;wanted=archive.read(names[0]);assert len(wanted)<1000000
        raw_body=body.read_bytes();encoding=headers.get('content-encoding','identity');assert encoding==row['bodyEncoding']
        if encoding=='identity':decoded=raw_body
        elif encoding=='gzip':decoded=gzip.GzipFile(fileobj=io.BytesIO(raw_body)).read(len(wanted)+1)
        elif encoding=='deflate':decoded=zlib.decompressobj().decompress(raw_body,len(wanted)+1)
        else:raise AssertionError('unsupported_official_cache_encoding')
        assert decoded==wanted and hashlib.sha256(decoded).hexdigest()==row['decodedBodySha256']
        expected[str(relative)]=row['entryPin'];expected[str(relative)+'.body']=row['bodyPin']
    assert len(urls)==2*len(wheels) and 0<proof['totalBytes']==sum(x['bytes']for x in expected.values())<=policy['maximumBytes']
    assert {f.relative_to(root).as_posix()for f in root.rglob('*')if f.is_file()}==set(expected)
    assert re.fullmatch('[a-f0-9]{64}',cid) and re.fullmatch('[a-f0-9]{32}',session) and re.fullmatch('sha256:[a-f0-9]{64}',expected_image)
    owner_key='objrun.tb12.owner' if policy['neutralOnly'] else 'objrun.skb.nonsecurity-session';assert expected_labels.get(owner_key)==session
    receipt=pathlib.Path(receipt_directory).resolve();assert receipt.is_relative_to(owner) and receipt.is_dir()
    assert 0<deadline-time.monotonic()<=policy['originalVerifierSeconds']
    def remaining():
        seconds=deadline-time.monotonic();assert seconds>0,'original_verifier_deadline'
        return seconds
    actual=json.loads(command(['inspect',cid],remaining()))[0];assert actual['Id']==cid and actual['Image']==expected_image and all(actual['Config']['Labels'].get(k)==v for k,v in expected_labels.items())
    host=actual['HostConfig'];assert not host['ReadonlyRootfs'] and not host['Privileged'] and not host.get('Binds') and not host.get('Mounts') and host['NetworkMode']==policy['publicNetworkMode'] and host['NetworkMode']not in ('host','none')
    destination='/tmp/objrun-official-pip-cache-'+session;command(['cp',str(root),cid+':'+destination],remaining());maximum=proof['totalBytes']+(len(expected)*8+100)*2048
    raw=command(['cp',cid+':'+destination,'-'],remaining(),stdout_limit=maximum);assert len(raw)<=maximum
    saved=receipt/'official-pip-cache-readback.tar'
    with saved.open('xb')as out:out.write(raw)
    seen=set();prefix=destination.rsplit('/',1)[1];directories={'.'}
    for name in expected:
        directories.update(str(q)for q in pathlib.PurePosixPath(name).parents)
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*')as archive:
        for item in archive:
            path=pathlib.PurePosixPath(item.name);assert not path.is_absolute() and '..'not in path.parts and path.parts[0]==prefix
            relative=str(pathlib.PurePosixPath(*path.parts[1:]))
            if item.isdir():assert relative in directories;continue
            assert item.isfile() and relative in expected and relative not in seen;row=expected[relative];assert item.size==row['bytes'];body=archive.extractfile(item).read(item.size+1);assert len(body)==item.size and hashlib.sha256(body).hexdigest()==row['sha256'];seen.add(relative)
    assert seen==set(expected)
    value=dict(protocol='bench-official-immutable-pip-http-cache-seed-v1',taskId=task_id,cid=cid,destination=destination,session=session,expectedImage=expected_image,expectedLabels=expected_labels,officialHttpCacheVerificationPin=policy['officialHttpCacheVerificationPin'],actualDaemonReadbackPin=pin(saved),filesVerified=len(seen),originalIndexUrlUnchanged=True,originalResponseHeadersUnchanged=True,originalCacheDateAgeAndTtlUnchanged=True,indexResponsesIncluded=False,originalDependencySelectionForced=False,originalCiCommandChanged=False,noCandidateArchiverExecuted=True,modelCalls=0,gradeCalls=0,referenceCalls=0)
    with (receipt/'official-pip-cache-seed.json').open('x')as out:json.dump(value,out,indent=2);out.write('\n')
    return destination
