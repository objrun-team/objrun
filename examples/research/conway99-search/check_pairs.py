"""Independent checker 1: explicit neighbour sets and unordered pair enumeration."""
import json,sys,hashlib
from pathlib import Path

def check(path,n=99,k=14,lam=1,mu=2):
    raw=Path(path).read_bytes(); obj=json.loads(raw)
    a=obj['matrix'] if isinstance(obj,dict) else obj
    if not isinstance(a,list) or len(a)!=n or any(not isinstance(r,list) or len(r)!=n for r in a):
        return {'valid':False,'shape':False,'sha256':hashlib.sha256(raw).hexdigest()}
    binary=all(type(x) is int and x in (0,1) for row in a for x in row)
    if not binary:return {'valid':False,'shape':True,'binary':False}
    loops=sum(a[i][i]!=0 for i in range(n))
    asym=sum(a[i][j]!=a[j][i] for i in range(n) for j in range(i))
    neighbors=[set(j for j in range(n) if a[i][j]==1) for i in range(n)]
    deg=[len(s) for s in neighbors]; dv=sum(d!=k for d in deg)
    av=nv=l1=l2=0; hist={}; witnesses=[]
    for u in range(n):
        for v in range(u+1,n):
            common=0
            for w in neighbors[u]:
                if w in neighbors[v]:common+=1
            target=lam if v in neighbors[u] else mu
            d=common-target; l1+=abs(d); l2+=d*d
            hist[str(common)]=hist.get(str(common),0)+1
            if d:
                if a[u][v]:av+=1
                else:nv+=1
                witnesses.append([u,v,common,target])
    return {'valid':not(loops or asym or dv or av or nv),'shape':True,'binary':True,
            'n':n,'parameters':[n,k,lam,mu],'loops':loops,'asymmetric_pairs':asym,
            'degree_violations':dv,'adjacent_pair_violations':av,'nonadjacent_pair_violations':nv,
            'constraint_violations':dv+av+nv,'pair_l1':l1,'pair_l2':l2,'degrees':deg,
            'common_count_histogram':hist,'violations':witnesses,'sha256':hashlib.sha256(raw).hexdigest()}

if __name__=='__main__':
    try:r=check(sys.argv[1],*(map(int,sys.argv[2:6]) if len(sys.argv)>=6 else ()))
    except Exception as e:r={'valid':False,'parse_error':str(e)}
    print(json.dumps(r))
