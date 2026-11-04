import json,itertools,math,tempfile
from pathlib import Path
from checker import check
from independent import verify
ROOT=Path(__file__).resolve().parents[3];RUN=Path((ROOT/'data/ks-original-search/latest-run.txt').read_text().strip())
def canon(v):
    g=math.gcd(*v);w=tuple(x//g for x in v)
    return w if next(x for x in w if x)>0 else tuple(-x for x in w)
pool=sorted({canon(v) for v in itertools.product(range(-2,3),repeat=3) if 0<sum(x*x for x in v)<=6})
deleted={canon(v) for v in [(2,1,1),(2,1,0),(2,1,-1),(-1,2,1),(1,-2,0),(1,-2,1)]}
vectors=[list(v) for v in pool if v not in deleted];assert len(pool)==37 and len(vectors)==31
obj={'name':'Conway-Kochen31 via Trandafir-Cabello Appendix F/Theorem 2','source':'https://arxiv.org/html/2501.11640v3','field_d':2,'vectors':vectors}
p=RUN/'reference/ck31.json';p.write_text(json.dumps(obj,indent=2))
(RUN/'reference/ck37.json').write_text(json.dumps({'vectors':pool,'source':obj['source']},indent=2))
base=check(p,RUN/'baseline-audit.json');assert base['valid'] and base['n']==31 and not base['strict_success'],base
tests=[]
with tempfile.TemporaryDirectory(dir=RUN) as tmp:
    tmp=Path(tmp)
    def test(name,o,valid=False,geometry=None):
        f=tmp/(name+'.json');f.write_text(json.dumps(o));r=check(f,tmp/(name+'.report.json'));assert r['valid']==valid,(name,r)
        if geometry is not None:assert r.get('geometry_valid',False)==geometry,(name,r)
        tests.append({'name':name,'passed':True,'error':r.get('error'),'unsat':r.get('unsat')})
    test('zero',{'vectors':[[0,0,0]]},geometry=False)
    test('scaled-duplicate',{'vectors':[[1,2,3],[-2,-4,-6]]},geometry=False)
    test('orthogonal-basis-colorable',{'vectors':[[1,0,0],[0,1,0],[0,0,1]]},geometry=True)
    test('near-is-not-orthogonal',{'vectors':[[1,0,0],['1/10000000000000000000000000000000000000000',1,0]],'declared_edges':[[0,1]]},geometry=False)
    test('floats-rejected',{'vectors':[[1.0,0,0]]},geometry=False)
    test('complex-rejected',{'vectors':[['I',0,0]]},geometry=False)
    test('radical-scaled-duplicate',{'vectors':[[[0,1],1,0],[2,[0,1],0]]},geometry=False)
    test('radical-basis-colorable',{'vectors':[[[0,1],1,0],[1,[0,-1],0],[0,0,1]]},geometry=True)
    for i in range(31):test('delete-'+str(i),{'vectors':vectors[:i]+vectors[i+1:]},geometry=True)
    # Replacing a leaf by a false conflict must fail independent proof replay.
    proof=json.loads(Path(base['proof']).read_text());proof['tree']={'units':[],'conflict':0}
    bad=tmp/'corrupt-proof.json';bad.write_text(json.dumps(proof))
    try:verify(p,base['graph'],bad)
    except AssertionError:tests.append({'name':'corrupt-proof-rejected','passed':True})
    else:raise AssertionError('Corrupt proof accepted')
(RUN/'checker-selftest.json').write_text(json.dumps({'passed':True,'tests':tests,'baseline':base},indent=2))
print(json.dumps({'passed':True,'tests':len(tests),'baseline_n':31,'pairs':base['orthogonal_pairs'],'triples':base['orthogonal_triples'],'independent':base['independent']}))
