"""Frozen host checker A: exact Q(sqrt(d)) geometry and replayable DPLL tree.
No search program is imported. Floats, zero rays and proportional rays rejected.
"""
import json, sys, math, hashlib, itertools
from pathlib import Path
from fractions import Fraction as F

def scalar(x):
    if isinstance(x,bool) or not isinstance(x,(str,int)): raise ValueError('Rational must be integer or fraction string, never float')
    if isinstance(x,str) and any(c not in '0123456789+-/' for c in x): raise ValueError('Use exact a/b syntax')
    return F(x)

def geometry(obj):
    d=obj.get('field_d',2)
    if type(d) is not int or d<=0 or math.isqrt(d)**2==d: raise ValueError('field_d must be a positive nonsquare integer')
    def parse(x): return (scalar(x[0]),scalar(x[1])) if isinstance(x,list) and len(x)==2 else (scalar(x),F(0))
    def add(x,y):return (x[0]+y[0],x[1]+y[1])
    def mul(x,y):return (x[0]*y[0]+d*x[1]*y[1],x[0]*y[1]+x[1]*y[0])
    def sub(x,y):return (x[0]-y[0],x[1]-y[1])
    zero=(F(0),F(0))
    vectors=obj['vectors']
    if not isinstance(vectors,list) or not vectors:raise ValueError('Nonempty vectors required')
    vv=[]
    for v in vectors:
        if not isinstance(v,list) or len(v)!=3:raise ValueError('Exactly three coordinates')
        w=list(map(parse,v))
        if all(x==zero for x in w):raise ValueError('Zero vector')
        vv.append(w)
    edges=[]
    for i,j in itertools.combinations(range(len(vv)),2):
        u,v=vv[i],vv[j]
        if all(sub(mul(u[a],v[b]),mul(u[b],v[a]))==zero for a,b in [(0,1),(0,2),(1,2)]):raise ValueError(f'Duplicate ray {i},{j}')
        dot=zero
        for a,b in zip(u,v):dot=add(dot,mul(a,b))
        if dot==zero:edges.append([i,j])
    eset=set(map(tuple,edges))
    for pair in obj.get('declared_edges',[]):
        if len(pair)!=2 or any(type(x) is not int for x in pair) or tuple(sorted(pair)) not in eset:raise ValueError('False declared orthogonality')
    triples=[list(t) for t in itertools.combinations(range(len(vv)),3) if all(e in eset for e in itertools.combinations(t,2))]
    return len(vv),edges,triples

def solve(n,clauses):
    def rec(assign):
        units=[]
        while True:
            chosen=None
            for c in clauses:
                if any(assign.get(abs(l))==(l>0) for l in c):continue
                rem=[l for l in c if abs(l) not in assign]
                if not rem:return None,{'units':units,'conflict':clauses.index(c)}
                if len(rem)==1:chosen=rem[0];break
            if chosen is None:break
            assign[abs(chosen)]=chosen>0;units.append(chosen)
        pending=[c for c in clauses if not any(assign.get(abs(l))==(l>0) for l in c)]
        if not pending:return [int(assign.get(i,False)) for i in range(1,n+1)],None
        freq={}
        for c in pending:
            for l in c:
                if abs(l) not in assign:freq[abs(l)]=freq.get(abs(l),0)+1
        var=max(freq,key=freq.get)
        left,lp=rec(dict(assign,**{})|{var:False})
        if left is not None:return left,None
        right,rp=rec(assign|{var:True})
        if right is not None:return right,None
        return None,{'units':units,'split':var,'zero':lp,'one':rp}
    return rec({})

def check(path,out,baseline=31):
    path=Path(path);out=Path(out);out.parent.mkdir(parents=True,exist_ok=True)
    report={'valid':False,'strict_success':False,'evidence_level':'rejected','sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    try:
        obj=json.loads(path.read_text(encoding='utf-8-sig'));n,edges,triples=geometry(obj)
        clauses=[[-i-1,-j-1] for i,j in edges]+[[i+1,j+1,k+1] for i,j,k in triples]
        graph={'n':n,'edges':edges,'triples':triples,'clauses':clauses}
        graphpath=out.with_suffix('.graph.json');proofpath=out.with_suffix('.proof.json');cnfpath=out.with_suffix('.cnf')
        graphpath.write_text(json.dumps(graph,indent=2))
        cnfpath.write_text(f'p cnf {n} {len(clauses)}\n'+''.join(' '.join(map(str,c))+' 0\n' for c in clauses))
        witness,proof=solve(n,clauses)
        proofpath.write_text(json.dumps({'format':'dpll-unit-split-v1','tree':proof,'coloring':witness},separators=(',',':')))
        report.update(n=n,orthogonal_pairs=len(edges),orthogonal_triples=len(triples),geometry_valid=True,unsat=witness is None,graph=str(graphpath),cnf=str(cnfpath),proof=str(proofpath))
        # Import only the separately implemented verifier, never optimizer code.
        from independent import verify
        independent=verify(path,graphpath,proofpath)
        ip=out.with_suffix('.independent.json');ip.write_text(json.dumps(independent,indent=2))
        report.update(independent=independent,valid=bool(witness is None and independent['valid']),strict_success=bool(n<baseline and witness is None and independent['valid']),evidence_level='exact geometry + complete DPLL UNSAT certificate + independent symbolic geometry and Boolean replay' if witness is None and independent['valid'] else 'colorable exact geometry')
        report['evidence_sha256']={p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in [graphpath,cnfpath,proofpath,ip]}
    except Exception as exc:report['error']=str(exc)
    tmp=Path(str(out)+'.tmp');tmp.write_text(json.dumps(report,indent=2));tmp.replace(out)
    return report

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('candidate');p.add_argument('--output',required=True);p.add_argument('--baseline',type=int,default=31);a=p.parse_args()
    print(json.dumps(check(a.candidate,a.output,a.baseline)))
