"""Implementation B: SymPy exact algebraic geometry, bitset SAT and proof replay.
Does not import checker A or any search code. Run standalone for independent audit.
"""
import json,itertools,sys
from pathlib import Path
import sympy as s

def verify(candidate,graphpath,proofpath):
    obj=json.loads(Path(candidate).read_text(encoding='utf-8-sig'));d=obj.get('field_d',2)
    assert type(d) is int and d>0 and not s.sqrt(d).is_Integer
    r=s.sqrt(d)
    def rat(v):
        assert type(v) in (int,str)
        assert not isinstance(v,str) or all(c in '0123456789+-/' for c in v)
        return s.Rational(v)
    def num(v):return rat(v[0])+rat(v[1])*r if isinstance(v,list) and len(v)==2 else rat(v)
    vv=[];canonical=set()
    for raw in obj['vectors']:
        assert len(raw)==3
        v=[num(x) for x in raw];pivot=next((x for x in v if x!=0),None);assert pivot is not None
        key=tuple(s.simplify(x/pivot) for x in v);assert key not in canonical,'Independent duplicate';canonical.add(key);vv.append(v)
    n=len(vv);adj=[[False]*n for _ in range(n)];edges=[];triples=[]
    for i in range(n):
        for j in range(i+1,n):
            if s.expand(sum(vv[i][k]*vv[j][k] for k in range(3)))==0:adj[i][j]=adj[j][i]=True;edges.append([i,j])
    for i in range(n):
        for j in range(i+1,n):
            if adj[i][j]:
                for k in range(j+1,n):
                    if adj[j][k] and adj[k][i]:triples.append([i,j,k])
    for i,j in obj.get('declared_edges',[]):assert type(i) is int and type(j) is int and 0<=i<n and 0<=j<n and adj[i][j]
    clauses=[[-(i+1),-(j+1)] for i,j in edges]+[[i+1,j+1,k+1] for i,j,k in triples]
    graph=json.loads(Path(graphpath).read_text());assert graph=={'n':n,'edges':edges,'triples':triples,'clauses':clauses},'Graph/CNF mismatch'
    masks=[(sum(1<<(l-1) for l in c if l>0),sum(1<<(-l-1) for l in c if l<0)) for c in clauses]
    full=(1<<n)-1;nodes=0
    def sat(t,f):
        nonlocal nodes
        nodes+=1
        while True:
            change=False;unassigned=full&~(t|f)
            for pos,neg in masks:
                if pos&t or neg&f:continue
                available=(pos|neg)&unassigned
                if not available:return False
                if available&(available-1)==0:
                    if available&pos:t|=available
                    else:f|=available
                    change=True;break
            if not change:break
        remaining=full&~(t|f)
        if not remaining:return True
        v=remaining&-remaining
        return sat(t|v,f) or sat(t,f|v)
    independent_sat=sat(0,0)
    proof=json.loads(Path(proofpath).read_text());replayed=0
    def replay(node,t,f):
        nonlocal replayed
        replayed+=1;assert isinstance(node,dict)
        for l in node['units']:
            assert type(l) is int and 1<=abs(l)<=n
            bit=1<<(abs(l)-1);assert not bit&(t|f)
            unassigned=full&~(t|f)
            assert any(not(pos&t or neg&f) and ((pos|neg)&unassigned)==bit and ((l>0 and pos&bit) or (l<0 and neg&bit)) for pos,neg in masks),'Non-unit propagation'
            if l>0:t|=bit
            else:f|=bit
        if 'conflict' in node:
            ix=node['conflict'];assert type(ix) is int and 0<=ix<len(masks)
            pos,neg=masks[ix];assert not(pos&t or neg&f) and not((pos|neg)&~(t|f));return
        v=node['split'];assert type(v) is int and 1<=v<=n
        bit=1<<(v-1);assert not bit&(t|f)
        replay(node['zero'],t,f|bit);replay(node['one'],t|bit,f)
    if proof['tree'] is not None:
        replay(proof['tree'],0,0);assert not independent_sat
    else:
        colors=proof['coloring'];assert independent_sat and len(colors)==n and all(type(x) is int and x in [0,1] for x in colors)
        assert all(any(colors[abs(l)-1]==int(l>0) for l in c) for c in clauses)
    return {'valid':not independent_sat,'n':n,'geometry':'independent SymPy exact rational/radical normalization and dot products','boolean':'independent bitmask exhaustive SAT plus DPLL tree replay','sat_nodes':nodes,'proof_nodes':replayed}

if __name__=='__main__':print(json.dumps(verify(*sys.argv[1:4]),indent=2))
