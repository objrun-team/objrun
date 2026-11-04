"""Independent interval verifier; does not import optimizer or certificate creator.
Rebuilds the polynomial Jacobian by a different block formula, and validates
exact dyadic witness data. Its affirmative claims rely only on Arb inequalities.
"""
import os,sys,json,hashlib,time
from pathlib import Path
if os.name!='nt':sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
from flint import arb,arb_mat,ctx

def I(n):return arb_mat(n,n,[int(i==j) for i in range(n) for j in range(n)])
def dyad(p):return arb(tuple(int(a) for a in p))
def norm(A):return max(sum((abs(A[i,j]).upper() for j in range(A.ncols())),arb(0)).upper() for i in range(A.nrows()))
def rot(v):
    columns=[]
    for a in range(6):
        for b in range(a):
            col=[arb(0) for _ in range(144)]
            for i in range(24):col[6*i+a]=v[6*i+b];col[6*i+b]=-v[6*i+a]
            columns.append(col)
    return arb_mat(columns).transpose()
def polynomial(v,base,R):
    X=arb_mat(24,6,v[:144]);G=X*X.transpose();G3=arb_mat(24,24,[G[i,j]**3 for i in range(24) for j in range(24)])
    grad=8*G3*X
    H=arb_mat(144,144)
    for i in range(24):
        diagonal=arb_mat(6,6,[24*sum((G[i,p]**2*X[p,a]*X[p,b] for p in range(24)),arb(0)) for a in range(6) for b in range(6)])
        for j in range(24):
            for a in range(6):
                for b in range(6):
                    z=24*G[i,j]**2*X[j,a]*X[i,b]
                    if a==b:z+=8*G[i,j]**3
                    if i==j:z+=diagonal[a,b]-(v[144+i] if a==b else 0)
                    H[6*i+a,6*j+b]=z
    F=arb_mat(183,1);J=arb_mat(183,183)
    for i in range(144):
        F[i,0]=grad[i//6,i%6]-v[144+i//6]*v[i]+sum((R[i,k]*v[168+k] for k in range(15)),arb(0))
        for j in range(144):J[i,j]=H[i,j]
        J[i,144+i//6]=J[144+i//6,i]=-v[i]
        for k in range(15):J[i,168+k]=J[168+k,i]=R[i,k]
    for i in range(24):F[144+i,0]=(1-G[i,i])/2
    for k in range(15):F[168+k,0]=sum((R[i,k]*(v[i]-base[i]) for i in range(144)),arb(0))
    E=sum((G[i,j]**4 for i in range(24) for j in range(24)),arb(0))-36
    return F,J,H,E

def verify(witness,reference,digits=220):
    ctx.dps=digits;w=json.loads(Path(witness).read_text());assert w['encoding'].startswith('Exact m*2^e')
    center=[dyad(p) for p in w['center']];base=[dyad(p) for p in w['base']]
    assert all(v.is_exact() for v in center+base),'Raise precision to preserve exact witness centers'
    C=arb_mat([[dyad(p) for p in row] for row in w['inverse_midpoint']]);Q=arb_mat([[dyad(p) for p in row] for row in w['congruence_matrix']])
    assert len(center)==183 and len(base)==144 and C.nrows()==C.ncols()==183 and Q.nrows()==Q.ncols()==144
    r=arb((1,-180));box=[arb(a.mid(),r) for a in center];R=rot(base)
    F0,_,_,_=polynomial(center,base,R);_,J,H,E=polynomial(box,base,R)
    q=norm(I(183)-C*J);eta=norm(C*F0);image=(eta+q*r).upper()
    # Fresh independent approximate inverse; all bounds enclose the full box.
    M=R.transpose()*rot(box[:144]);M0=R.transpose()*rot(center[:144]);trans=norm(I(15)-M0.inv().mid()*M)
    N=arb_mat(144,24)
    for i in range(144):N[i,i//6]=box[i]
    A=H+100*(N*N.transpose()+R*R.transpose());B=Q.transpose()*A*Q
    qinv=norm(I(144)-Q.transpose()*Q)
    gap=min((B[i,i]-sum((abs(B[i,j]).upper() for j in range(144) if j!=i),arb(0))).lower() for i in range(144))
    raw=json.loads(Path(reference).read_text())['vectors'];ref=[]
    for v in raw:
        z=[arb(str(a)) for a in v];s=sum((a*a for a in z),arb(0)).sqrt();ref.append([a/s for a in z])
    refE=sum((sum((a*b for a,b in zip(v,z)),arb(0))**4 for v in ref for z in ref),arb(0))-36
    tests={'contraction':bool(q<1),'strict_self_mapping':bool(image<r),'rotation_transversality':bool(trans<1),'congruence_nonsingular':bool(qinv<1),'positive_full_slice_hessian':bool(gap>0),'lower_feasible_reference':bool(refE.upper()<E.lower())}
    result={'independently_verified':all(tests.values()),'precision_digits':digits,'tests':tests,'contraction_bound':str(q),'newton_displacement':str(eta),'image_radius_bound':str(image),'box_radius':str(r),'transversality_bound':str(trans),'congruence_inverse_bound':str(qinv),'positive_margin':str(gap),'energy':str(E),'reference_energy':str(refE),'witness_sha256':hashlib.sha256(Path(witness).read_bytes()).hexdigest(),'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'reference_sha256':hashlib.sha256(Path(reference).read_bytes()).hexdigest(),'timestamp_epoch':time.time()}
    return result
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('witness');p.add_argument('reference');p.add_argument('--output',required=True);p.add_argument('--digits',type=int,default=220);a=p.parse_args()
    result=verify(a.witness,a.reference,a.digits);Path(a.output).write_text(json.dumps(result,indent=2));print(json.dumps(result,indent=2));assert result['independently_verified']
