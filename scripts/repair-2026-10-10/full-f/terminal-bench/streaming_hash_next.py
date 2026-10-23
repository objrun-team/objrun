import hashlib
from pathlib import Path
def sha(p):
 h=hashlib.sha256()
 with Path(p).open("rb") as s:
  for b in iter(lambda:s.read(1024**2),b""):h.update(b)
 return h.hexdigest()
def pin(p):
 p=Path(p).resolve()
 return {"path":str(p),"bytes":p.stat().st_size,"sha256":sha(p)}
