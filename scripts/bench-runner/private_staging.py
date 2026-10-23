"""Copy pinned trusted private inputs into the existing owned upload root."""
import hashlib,json,os,pathlib,shutil,stat

def _ordinary(path):
 s=path.lstat();assert not path.is_symlink() and not getattr(s,'st_file_attributes',0)&1024,'private_staging_reparse_forbidden'
 assert stat.S_ISDIR(s.st_mode) or stat.S_ISREG(s.st_mode),'private_staging_special_file_forbidden'

def tree(path):
 path=pathlib.Path(path);_ordinary(path);assert path.is_dir()
 for parent in path.parents:_ordinary(parent)
 directories=[];files=[]
 for item in sorted(path.rglob('*')):
  _ordinary(item);relative=item.relative_to(path).as_posix()
  if item.is_dir():directories.append(relative)
  else:
   raw=item.read_bytes();files.append({'path':relative,'bytes':len(raw),'sha256':hashlib.sha256(raw).hexdigest()})
 return {'directories':directories,'files':files}

def stage_private_upload(native,source,cid,destination,output):
 native.guard();native.assert_actor(cid)
 config_path=pathlib.Path(os.environ['NOVAEVE_PYTHON_MAPPING_CONFIG']);raw=config_path.read_bytes();assert hashlib.sha256(raw).hexdigest()==os.environ['NOVAEVE_PYTHON_MAPPING_SHA256']
 binding=json.loads(raw)['trustedPrivateStagingPin'];binding_raw=pathlib.Path(binding['path']).read_bytes();assert len(binding_raw)==binding['bytes'] and hashlib.sha256(binding_raw).hexdigest()==binding['sha256']
 contract=json.loads(binding_raw);assert contract['protocol']=='bench-pinned-private-staging-v1'
 source=pathlib.Path(source).absolute();approved=[x for x in contract['allowedSources'] if pathlib.Path(x['source']).absolute()==source and x['destination']==destination];assert len(approved)==1 and destination in ('/tests','/inputs'),'private_staging_source_not_bound'
 approved=approved[0];before=tree(source);assert before==approved['tree'],'private_staging_original_tree_changed'
 output=pathlib.Path(output);_ordinary(output)
 for parent in output.parents:_ordinary(parent)
 output=output.resolve();grade_root=native.directory/'grades';assert output.name=='staging' and output.parent.parent==grade_root and len(output.parent.name)==32 and all(x in '0123456789abcdef' for x in output.parent.name),'private_staging_output_not_this_grade'
 target=output/'trusted-upload'/destination[1:];assert not target.exists();target.parent.mkdir(parents=True,exist_ok=True);_ordinary(target.parent);shutil.copytree(source,target)
 copied=tree(target);after=tree(source);assert before==copied==after,'private_staging_copy_bytes_changed'
 receipt={'protocol':'bench-exact-private-staging-receipt-v1','source':str(source),'destination':destination,'staged':str(target),'originalBefore':before,'stagedTree':copied,'originalAfter':after,'sourceBeforeAfterEqual':True,'privateCodeExecuted':False}
 (output/('trusted-staging-'+destination[1:]+'.json')).write_text(json.dumps(receipt,indent=2)+'\n')
 return native.upload(target,cid,destination)
