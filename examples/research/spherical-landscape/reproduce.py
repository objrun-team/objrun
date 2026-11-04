import json,hashlib,sys
from pathlib import Path
import numpy as np
from scipy.io import loadmat
from checker import check
from checker_selftest import run as selftest
root=Path(__file__).resolve().parents[3]
run=Path(sys.argv[1])
src=next((run/'sources').rglob('run_002_006_024.mat'))
m=loadmat(src);x=m['result'].T
assert x.shape==(24,6) and int(m['d'][0,0])==6 and int(m['n'][0,0])==24 and int(m['t'][0,0])==2
out=run/'reference/author-reference.json'
out.write_text(json.dumps({'vectors':x.tolist(),'source':'Zenodo 8126277 version 2','archive_member':str(src.relative_to(run/'sources')),'source_sha256':hashlib.sha256(src.read_bytes()).hexdigest()},indent=2))
r=check(out,run/'baseline-audit.json')
assert abs(float(r['high_precision']['normalized_energy']))<1e-8
rep={'source_url':'https://zenodo.org/records/8126277','arxiv_version':'2405.19353v1','journal_doi':'10.1002/jcd.21979','mat_sha256':hashlib.sha256(src.read_bytes()).hexdigest(),'source_dimensions':{'t':2,'d':6,'n':24},'operation':'read MATLAB result; transpose to row vectors; checker also evaluates exact normalization of decimal inputs','normalization':'c_2(R^6)=3/(6*8)=1/16; unit columns imply c*24^2=36; all ordered pairs include diagonals','raw_norm_error':r['unit_error'],'energy':r['energy'],'high_precision':r['high_precision'],'gradient_norm':r['gradient_norm'],'quotient_min':r['quotient_spectrum'][0],'nonrotational_near_zero_count':r['near_zero_count']}
(run/'reference/reproduction.json').write_text(json.dumps(rep,indent=2))
(run/'checker-selftest.json').write_text(json.dumps(selftest(),indent=2))
print(json.dumps(rep,indent=2))
