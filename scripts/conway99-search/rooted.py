"""Rooted reduction v1. No automorphism assumptions. Host supplied scaffold."""
import itertools,json,random

def labels(k):return [p for p in itertools.combinations(range(k),2) if p[0]//2!=p[1]//2]
def expand(b,k):
    pairs=labels(k); n=1+k+len(pairs); a=[[0]*n for _ in range(n)]
    def edge(i,j):a[i][j]=a[j][i]=1
    for i in range(k):edge(0,i+1)
    for i in range(0,k,2):edge(i+1,i+2)
    for u,pair in enumerate(pairs):
        for i in pair:edge(1+k+u,1+i)
    for u in range(len(pairs)):
        for v in range(u):
            if b[u][v]:edge(1+k+u,1+k+v)
    return a
def seed(k=14,seed=20261031):
    m=len(labels(k)); p=list(range(m)); random.Random(seed).shuffle(p); b=[[0]*m for _ in range(m)]
    for i in range(m):
        for d in range(1,(k-2)//2+1):b[p[i]][p[(i+d)%m]]=b[p[(i+d)%m]][p[i]]=1
    return expand(b,k)
def encode(k=14):
    from ortools.sat.python import cp_model
    pairs=labels(k); m=len(pairs); model=cp_model.CpModel()
    b=[[0]*m for _ in range(m)]
    for i in range(m):
        for j in range(i):b[i][j]=b[j][i]=model.new_bool_var(f'e_{j}_{i}')
    for i in range(m):model.add(sum(b[i])==k-2)
    for a in range(k):
        for u in range(m):
            rhs=(1 if a in pairs[u] else 2)-int((a^1) in pairs[u])
            model.add(sum(b[u][v] for v in range(m) if a in pairs[v])==rhs)
    for u in range(m):
        for v in range(u):
            terms=[]
            for w in range(m):
                if w in (u,v):continue
                t=model.new_bool_var(f'p_{v}_{u}_{w}')
                model.add(t<=b[u][w]);model.add(t<=b[v][w]);model.add(t>=b[u][w]+b[v][w]-1)
                terms.append(t)
            model.add(sum(terms)+b[u][v]==2-len(set(pairs[u])&set(pairs[v])))
    return model,b
