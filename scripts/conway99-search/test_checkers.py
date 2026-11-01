import sys,json,itertools,random,tempfile
from pathlib import Path
from check_pairs import check
from check_matrix import verify
from rooted import encode,expand,labels
from ortools.sat.python import cp_model

out=Path(sys.argv[1]);out.mkdir(parents=True,exist_ok=True); records=[]
def test(name,a,params,expect):
    p=out/(name+'.json');p.write_text(json.dumps({'matrix':a}))
    r=check(p,*params);s=verify(p,*params)
    assert r['valid']==s['valid']==expect,(name,r,s)
    if r.get('binary') and not r.get('loops') and not r.get('asymmetric_pairs'):
        assert r['adjacent_pair_violations']+r['nonadjacent_pair_violations']==s['upper_identity_violations']
    records.append({'name':name,'expected':expect,'pair':r['valid'],'matrix':s['valid']})
rook=[[int(i!=j and (i//3==j//3 or i%3==j%3)) for j in range(9)] for i in range(9)]
cycle=[[int((i-j)%5 in (1,4)) for j in range(5)] for i in range(5)]
sets=list(itertools.combinations(range(5),2));petersen=[[int(not(set(u)&set(v))) for v in sets] for u in sets]
residues={i*i%13 for i in range(1,13)};paley=[[int(i!=j and (i-j)%13 in residues) for j in range(13)] for i in range(13)]
for name,a,params in [('rook9',rook,(9,4,1,2)),('cycle5',cycle,(5,2,0,1)),('petersen10',petersen,(10,3,0,1)),('paley13',paley,(13,6,2,3))]:
    test(name,a,params,True)
    for kind in ('edge','asymmetry','loop','nonbinary','float','shape'):
        b=[row[:] for row in a]
        if kind=='edge':b[0][1]=b[1][0]=1-b[0][1]
        if kind=='asymmetry':b[0][1]=1-b[0][1]
        if kind=='loop':b[0][0]=1
        if kind=='nonbinary':b[0][1]=2
        if kind=='float':b[0][1]=float(b[0][1])
        if kind=='shape':b.pop()
        test(name+'-'+kind,b,params,False)
    perm=list(range(len(a)));random.Random(17).shuffle(perm)
    test(name+'-relabel',[[a[i][j] for j in perm] for i in perm],params,True)
# Exhaust all 1024 labelled order-five graphs. The independent known criterion
# for C5 is 2-regularity: on five vertices a simple 2-regular graph must be C5.
edges=list(itertools.combinations(range(5),2))
for mask in range(1<<10):
    a=[[0]*5 for _ in range(5)]
    for bit,(i,j) in enumerate(edges):a[i][j]=a[j][i]=(mask>>bit)&1
    test('exhaustive5-'+str(mask),a,(5,2,0,1),all(sum(row)==2 for row in a))
# Exact small encoding and each root of a known graph, checking the reduction.
model,b=encode(4);solver=cp_model.CpSolver();solver.parameters.num_search_workers=1
status=solver.solve(model);assert status in (cp_model.OPTIMAL,cp_model.FEASIBLE)
test('decoded-rooted-cpsat9',expand([[solver.value(x) if not isinstance(x,int) else x for x in row] for row in b],4),(9,4,1,2),True)
for root in range(9):
    ns=[i for i in range(9) if rook[root][i]];ordered=[]
    while ns:
        a=ns.pop(0); mate=next(j for j in ns if rook[a][j]);ns.remove(mate);ordered.extend([a,mate])
    outer=[]
    for pair in labels(4):outer.append(next(v for v in range(9) if v!=root and not rook[root][v] and {i for i,u in enumerate(ordered) if rook[u][v]}==set(pair)))
    full=[root]+ordered+outer;canon=[[rook[i][j] for j in full] for i in full]
    assert expand([[rook[i][j] for j in outer] for i in outer],4)==canon
    test('root-'+str(root),canon,(9,4,1,2),True)
(out/'summary.json').write_text(json.dumps({'passed':True,'cases':len(records),'records':records},indent=2))
print(json.dumps({'passed':True,'cases':len(records),'cp_sat_small_status':solver.status_name(status)}))
