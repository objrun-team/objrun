"""Optional host seed: exact integer pool + randomized minimal UNSAT subset search.
This finite-pool heuristic is NOT a lower-bound proof. Model may replace it.
"""
import argparse,json,time,random,itertools,math,hashlib,os
from pathlib import Path
from pysat.solvers import Solver

def canon(v):
    g=math.gcd(*v)
    if not g:return None
    w=tuple(x//g for x in v)
    return w if next(x for x in w if x)>0 else tuple(-x for x in w)

def pool_graph(vectors):
    edges=[];adj=[set() for v in vectors]
    for i,u in enumerate(vectors):
        for j in range(i):
            if sum(a*b for a,b in zip(u,vectors[j]))==0:edges.append((j,i));adj[j].add(i);adj[i].add(j)
    triples=[(i,j,k) for i,j in edges for k in adj[i]&adj[j] if k>j]
    return edges,triples

def main():
    a=argparse.ArgumentParser();a.add_argument('--deadline',type=float,required=True);a.add_argument('--seed',type=int,default=20261031);a.add_argument('--radius',type=int,default=4);a.add_argument('--out',default='.');args=a.parse_args()
    out=Path(args.out);(out/'candidates').mkdir(parents=True,exist_ok=True)
    rng=random.Random(args.seed);start=time.time();steps=0;calls=0;best=10**9
    vv=sorted({canon(v) for v in itertools.product(range(-args.radius,args.radius+1),repeat=3) if any(v)})
    edges,triples=pool_graph(vv);n=len(vv)
    # First n vars are color values, next n vars activate rays.
    clauses=[[-n-i-1,-n-j-1,-i-1,-j-1] for i,j in edges]+[[-n-i-1,-n-j-1,-n-k-1,i+1,j+1,k+1] for i,j,k in triples]
    def write(p,obj):
        temp=Path(str(p)+'.tmp');temp.write_text(json.dumps(obj));temp.replace(p)
    write(out/'pool.json',{'vectors':vv,'edges':edges,'triples':triples,'seed':args.seed,'scope':'finite integer coordinate pool, no universal bound'})
    with Solver(name='g4',bootstrap_with=clauses) as solver:
        def unsat(active):
            nonlocal calls
            calls+=1
            return not solver.solve(assumptions=[n+i+1 if i in active else -n-i-1 for i in range(n)])
        while time.time()<args.deadline and not Path('/work/STOP').exists():
            active=set(range(n));order=list(active);rng.shuffle(order)
            for i in order:
                if time.time()>=args.deadline or Path('/work/STOP').exists():return
                active.remove(i)
                if not unsat(active):active.add(i)
            steps+=1
            if len(active)<=best:
                best=min(best,len(active));cand={'vectors':[vv[i] for i in sorted(active)],'seed':args.seed,'restart':steps,'method':'host randomized deletion seed, model-selected invocation','radius':args.radius}
                key=hashlib.sha256(json.dumps(cand['vectors']).encode()).hexdigest()[:16]
                write(out/'candidates'/f'n{len(active)}-{key}.json',cand);write(out/'candidate.json',cand)
            progress={'epoch':time.time(),'elapsed_seconds':time.time()-start,'iterations':steps,'sat_calls':calls,'best_n':best,'pool_n':n,'pairs':len(edges),'triples':len(triples),'radius':args.radius,'seed':args.seed,'solver_stats':solver.accum_stats()}
            write(out/'progress.json',progress)
            if steps==1 or steps%50==0:print(json.dumps(progress),flush=True)
            if best<=30:return
if __name__=='__main__':main()
