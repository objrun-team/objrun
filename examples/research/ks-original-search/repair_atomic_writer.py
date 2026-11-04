"""One-time, attributed repair of the model's temporary-file collision."""
import pathlib,hashlib,json,datetime
r=pathlib.Path(__file__).resolve().parents[3]/'data/ks-original-search/run-20261031-a'
p=r/'work/kslib.py';old=p.read_bytes()
(r/'code-history'/(hashlib.sha256(old).hexdigest()+'-kslib.py')).write_bytes(old)
s=old.decode();needle="tmp = Path(str(path) + '.tmp')"
assert s.count(needle)==1
s=s.replace(needle,"tmp = Path(str(path) + '.' + __import__('uuid').uuid4().hex + '.tmp')")
p.write_text(s)
entry={'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'file':'work/kslib.py','before_sha256':hashlib.sha256(old).hexdigest(),'after_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'author':'host','scope':'repair cross-process temporary filename collision only'}
with (r/'host-code-patches.jsonl').open('a') as f:f.write(json.dumps(entry)+'\n')
print(json.dumps(entry))
