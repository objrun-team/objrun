"""Flatten only pinned baseline external file links through daemon archive reads.

No path from the candidate is opened on the host. The private artifact validator
is unchanged, and still rejects every unrecognized external link. The stopped
candidate/snapshot is never changed and remains the execution authority.
"""
import copy,hashlib,io,json,os,pathlib,posixpath,tarfile,uuid
from native_process import pin


def materialize_baseline_file_links(raw,cid,command,task,root,maximum_bytes,allowed,receipt_directory):
    assert _bench_authorized_history(task) is True
    config=json.loads(pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']).read_bytes())
    bound=config['baselineArtifactLinksPolicyPin'];assert pin(bound['path'])==bound
    policy=json.loads(pathlib.Path(bound['path']).read_bytes())
    assert policy['protocol']=='bench-daemon-baseline-file-link-policy-v1' and policy['taskId']==task
    assert policy['candidateSnapshotUnmodified'] is True and policy['privateExternalSymlinksPermitted'] is False
    directory=pathlib.Path(receipt_directory).resolve()
    assert directory.is_relative_to(pathlib.Path(policy['receiptRoot']).resolve())
    authorized={row['path']:row['target']for row in policy['originalBaselineLinks']}
    records=[];replacement={};materialized_bytes=0
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
        members=archive.getmembers()
        for member in members:
            if not member.issym():continue
            parts=member.name.rstrip('/').split('/')
            assert not member.name.startswith('/') and '..' not in parts
            logical=root+('/'+'/'.join(parts[1:]) if len(parts)>1 else '')
            target=posixpath.normpath(posixpath.join(posixpath.dirname(logical),member.linkname))
            if allowed(task,target):continue
            # Unknown links remain unchanged and reach the original strict guard.
            if authorized.get(logical)!=member.linkname:continue
            visited=set();chain=[]
            for depth in range(40):
                assert target.startswith('/') and target not in visited,'baseline_link_cycle_or_nonabsolute_target'
                visited.add(target)
                fetched=command(['cp',cid+':'+target,'-'],120,stdout_limit=maximum_bytes+1024*1024)
                with tarfile.open(fileobj=io.BytesIO(fetched),mode='r:*') as source:
                    entries=[row for row in source.getmembers()if not row.isdir()]
                    assert len(entries)==1,'baseline_link_must_resolve_to_single_file'
                    entry=entries[0];chain.append(dict(candidatePath=target,daemonArchiveSha256=hashlib.sha256(fetched).hexdigest(),daemonArchiveBytes=len(fetched),kind='symlink' if entry.issym() else 'file',target=entry.linkname))
                    if entry.issym():
                        target=posixpath.normpath(posixpath.join(posixpath.dirname(target),entry.linkname));continue
                    assert entry.isfile() and 0<=entry.size<=maximum_bytes-materialized_bytes,'baseline_link_file_bound'
                    body=source.extractfile(entry).read(entry.size+1);assert len(body)==entry.size
                    materialized_bytes+=len(body);replacement[member.name]=(body,entry.mode&0o777)
                    records.append(dict(path=logical,originalTarget=member.linkname,materializedBytes=len(body),materializedSha256=hashlib.sha256(body).hexdigest(),daemonResolutionChain=chain));break
            else:raise AssertionError('baseline_link_chain_bound')
        if not replacement:return raw
        output=io.BytesIO()
        with tarfile.open(fileobj=output,mode='w',format=tarfile.PAX_FORMAT) as target_archive:
            for member in members:
                rewritten=copy.copy(member)
                if member.name in replacement:
                    body,mode=replacement[member.name];rewritten.type=tarfile.REGTYPE;rewritten.linkname='';rewritten.size=len(body);rewritten.mode=mode;rewritten.pax_headers={k:v for k,v in rewritten.pax_headers.items()if k not in ('size','linkpath')}
                    target_archive.addfile(rewritten,io.BytesIO(body))
                else:target_archive.addfile(rewritten,archive.extractfile(member)if member.isfile()else None)
    result=output.getvalue();directory.mkdir(parents=True,exist_ok=True)
    receipt=dict(protocol='bench-daemon-baseline-file-links-v1',taskId=task,candidateCid=cid,policyPin=bound,candidateSnapshotUnmodified=True,privateExternalSymlinksPermitted=False,originalArchiveSha256=hashlib.sha256(raw).hexdigest(),originalArchiveBytes=len(raw),materializedArchiveSha256=hashlib.sha256(result).hexdigest(),materializedArchiveBytes=len(result),materializedFileLinks=records)
    with (directory/('baseline-links-'+uuid.uuid4().hex+'.json')).open('x')as stream:json.dump(receipt,stream,indent=2);stream.write('\n')
    return result
