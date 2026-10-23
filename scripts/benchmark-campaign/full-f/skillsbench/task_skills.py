"""Original public task skills only; never private verifier/oracle content."""
import hashlib
import io
import json
from pathlib import Path,PurePosixPath
import tarfile
import uuid
import yaml
from prepare import HOME,VENDOR,public,save,utc
TARGET='/root/.claude/skills'
MIRROR='/root/.agents/skills'
APP='/app/skills'

def inventory(tid):
    row=json.loads((HOME/'task-descriptors'/(tid+'.json')).read_bytes())
    source=VENDOR/'tasks'/tid/'environment/skills';expected=row['skillSource']
    assert public.tree(source)==expected,'original_skill_source_drift'
    assert expected['fileCount']>0,'original_skills_required'
    assert all(not p.is_symlink() for p in source.rglob('*')),'skill_source_links_denied'
    metadata=[]
    for p in sorted(source.glob('*/SKILL.md')):
        raw=p.read_text(encoding='utf8');parts=raw.split('---',2);assert len(parts)==3 and not parts[0].strip()
        front=yaml.safe_load(parts[1]);assert isinstance(front,dict)
        metadata.append({'name':str(front['name']),'description':str(front['description']),
            'location':TARGET+'/'+p.relative_to(source).as_posix(),'sourcePin':public.pin(p)})
    assert metadata,'original_skill_catalog_missing'
    return source,expected,metadata

def verify_archive(raw,expected,target=TARGET):
    files={r['path']:r for r in expected['files']};seen=set();actual=[]
    assert len(raw)<=expected['fileBytes']+(expected['fileCount']+32)*4096
    with tarfile.open(fileobj=io.BytesIO(raw),mode='r:') as archive:
        for member in archive:
            name=member.name
            if name.startswith('./'):name=name[2:]
            assert name=='skills' or name.startswith('skills/')
            assert not any(p in ('','..','.') for p in name.split('/')) and '\\' not in name
            if member.isdir():continue
            assert member.isfile() and not member.issym() and not member.islnk()
            relative=name[len('skills/'):];assert relative in files and relative not in seen
            seen.add(relative);body=archive.extractfile(member).read(member.size+1)
            row=files[relative];assert len(body)==member.size==row['bytes'] and hashlib.sha256(body).hexdigest()==row['sha256']
            actual.append({'path':target+'/'+relative,'bytes':len(body),'sha256':row['sha256']})
    assert seen==set(files),'deployed_skill_tree_incomplete'
    return actual

def deploy(command,cid,tid,home):
    source,expected,metadata=inventory(tid)
    command(['exec',cid,'mkdir','-p','/root/.claude','/root/.agents','/app'])
    deployed=[]
    for target in (TARGET,MIRROR,APP):
        command(['cp',str(source),cid+':'+str(PurePosixPath(target).parent)+'/'])
        raw=command(['cp',cid+':'+target,'-'],stdout_limit=expected['fileBytes']+(expected['fileCount']+32)*4096)
        deployed+=verify_archive(raw,expected,target)
    proof={'protocol':'skillsbench-original-public-skills-deployment-v1','taskId':tid,'candidateContainerId':cid,'atUtc':utc(),
        'originalSourceTreeSha256':expected['treeSha256'],'metadata':metadata,'deployedFiles':deployed,'canonicalRoot':TARGET,'mirrorRoot':MIRROR,
        'additionalOfficialRoot':APP,'deployedFileCount':len(deployed),'originalFileCount':expected['fileCount'],'sourcePin':public.pin(Path(__file__)),'verified':True,
        'privateVerifierCopied':False,'privateOracleCopied':False,'hostCandidateCodeExecuted':False,'sourceBeforeAfterEqual':public.tree(source)==expected}
    return save(Path(home)/('skill-deployment-'+uuid.uuid4().hex+'.json'),proof,True)

def catalog(tid):
    _,expected,metadata=inventory(tid)
    return {'taskId':tid,'sourceTreeSha256':expected['treeSha256'],'metadata':metadata,
        'body':'Original task skills are installed in the candidate workspace. Read the relevant SKILL.md with the read tool before using its guidance or bundled scripts.\n'+json.dumps([{k:m[k] for k in ('name','description','location')} for m in metadata],ensure_ascii=False)}

if __name__=='__main__':
    import sys
    print(json.dumps(catalog(sys.argv[1]),ensure_ascii=True))
