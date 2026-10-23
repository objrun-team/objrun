"""Complete task-tree input; paths and links never escape reviewed roots."""
import base64,hashlib,io,posixpath,tarfile
from pathlib import Path
from policy import TASKS,allowed,limits

def validate(task,artifacts,resources):
 bound=limits(task,resources);total=0;seen=set()
 assert type(artifacts) is list and len(artifacts)<=bound['maximumFiles']
 for item in artifacts:
  path=item['path'];assert allowed(task,path) and path not in seen;seen.add(path)
  if item.get('kind')=='symlink':
   assert set(item)=={'path','kind','target'} and type(item['target']) is str
   resolved=posixpath.normpath(posixpath.join(posixpath.dirname(path),item['target']))
   assert allowed(task,resolved),'symlink_outside_task_tree'
   continue
  assert set(item) in ({'path','base64','sha256'},{'path','base64','sha256','mode'})
  assert type(item.get('mode',0o600)) is int and 0<=item.get('mode',0o600)<=0o777
  assert type(item['base64']) is str and len(item['base64']) <= (bound['maximumBytes']+2)//3*4
  body=base64.b64decode(item['base64'],validate=True);total+=len(body)
  if task=='quantum-numerical-simulation':assert len(body)<=64*1024**2
  assert total<=bound['maximumBytes'] and hashlib.sha256(body).hexdigest()==item['sha256']
 return total

def install(task,artifacts,resources):
 validate(task,artifacts,resources)
 # Make regular files first; links are installed only after parent validation.
 for item in sorted(artifacts,key=lambda x:x.get('kind')=='symlink'):
  target=Path(item['path']);target.parent.mkdir(parents=True,exist_ok=True)
  assert all(not p.is_symlink() for p in [target,*target.parents]),'candidate_link_parent'
  if item.get('kind')=='symlink':target.symlink_to(item['target'])
  else:target.write_bytes(base64.b64decode(item['base64'],validate=True));target.chmod(item.get('mode',0o600))

def capture_tar(task,root,raw,resources):
 result=[];seen=set();bound=limits(task,resources);total=0
 with tarfile.open(fileobj=io.BytesIO(raw),mode='r:*') as archive:
  members=archive.getmembers()
  assert len(members)<=bound['maximumFiles']+100000
  for m in members:
   name=m.name.rstrip('/');parts=name.split('/')
   assert not name.startswith('/') and '..' not in parts
   suffix='/'.join(parts[1:]);path=root+('/'+suffix if suffix else '')
   if m.isdir():continue
   assert path not in seen and allowed(task,path);seen.add(path)
   if m.issym():result.append({'path':path,'kind':'symlink','target':m.linkname})
   elif m.isfile():
    total+=m.size;assert total<=bound['maximumBytes'];body=archive.extractfile(m).read(m.size+1);assert len(body)==m.size
    result.append({'path':path,'base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest(),'mode':m.mode & 0o777})
   elif m.islnk():
    linked=archive.getmember(m.linkname);assert linked.isfile();body=archive.extractfile(linked).read();total+=len(body);assert total<=bound['maximumBytes']
    result.append({'path':path,'base64':base64.b64encode(body).decode(),'sha256':hashlib.sha256(body).hexdigest(),'mode':m.mode & 0o777})
   else:raise ValueError('special_candidate_file')
 validate(task,result,resources);return result
