"""Ball-arithmetic KKT contraction + full transverse Hessian certificate.

183 unknowns: 144 coordinates, 24 norm multipliers, 15 gauge multipliers.
Equations: grad E - lambda_i*x_i + R*mu = 0; (1-|x_i|^2)/2 = 0;
R^T(x-a)=0, with R the fixed rotation generators at the saved base a.
All decimal inputs are enclosed by Arb; only midpoint Newton is nonrigorous.
Proof uses an outward-rounded box, contraction and congruence Gershgorin tests.
"""
import os,sys,json,time,threading,hashlib
from pathlib import Path
os.environ['OPENBLAS_NUM_THREADS']='1';os.environ['OMP_NUM_THREADS']='1'
if os.name!='nt':sys.path.insert(0,str(Path(__file__).resolve().parent/'vendor'))
import numpy as np
from flint import arb,arb_mat,ctx

N=183
def scalar(v):return arb(str(v))
def eye(n):return arb_mat([[int(i==j) for j in range(n)] for i in range(n)])
def rotation(x):
    out=arb_mat(144,15);k=0
    for a in range(6):
        for b in range(a):
            for i in range(24):out[6*i+a,k]=x[6*i+b];out[6*i+b,k]=-x[6*i+a]
            k+=1
    return out
def norminf(a):return max(sum((abs(a[i,j]).upper() for j in range(a.ncols())),arb(0)).upper() for i in range(a.nrows()))
def system(y,base,R):
    x=[[y[6*i+k] for k in range(6)] for i in range(24)]
    gram=[[sum((a*b for a,b in zip(v,w)),arb(0)) for w in x] for v in x]
    grad=[[8*sum((gram[i][j]**3*x[j][k] for j in range(24)),arb(0)) for k in range(6)] for i in range(24)]
    H=arb_mat(144,144)
    for i in range(24):
        a=x[i];rr=gram[i][i]
        for k in range(6):
            for l in range(6):H[6*i+k,6*i+l]=48*rr**2*a[k]*a[l]+(8*rr**3-y[144+i] if k==l else 0)
        for j in range(i):
            b=x[j];g=gram[i][j]
            for k in range(6):
                for l in range(6):
                    H[6*i+k,6*i+l]+=24*g*g*b[k]*b[l]
                    H[6*j+k,6*j+l]+=24*g*g*a[k]*a[l]
                    c=24*g*g*b[k]*a[l]+(8*g**3 if k==l else 0)
                    H[6*i+k,6*j+l]+=c;H[6*j+l,6*i+k]+=c
    F=arb_mat(N,1);J=arb_mat(N,N)
    for i in range(144):
        F[i,0]=grad[i//6][i%6]-y[144+i//6]*y[i]+sum((R[i,k]*y[168+k] for k in range(15)),arb(0))
        for j in range(144):J[i,j]=H[i,j]
        J[i,144+i//6]=-y[i];J[144+i//6,i]=-y[i]
        for k in range(15):J[i,168+k]=R[i,k];J[168+k,i]=R[i,k]
    for i in range(24):F[144+i,0]=(1-gram[i][i])/2
    for k in range(15):F[168+k,0]=sum((R[i,k]*(y[i]-base[i]) for i in range(144)),arb(0))
    E=sum((g**4 for row in gram for g in row),arb(0))-36
    return F,J,H,E

def main(candidate,reference,output,deadline):
    start=time.time();ctx.dps=120
    raw=json.loads(Path(candidate).read_text());x=np.array(raw['vectors'],float);x/=np.linalg.norm(x,axis=1)[:,None]
    # The gauge base is a fixed vector of exact dyadic numbers, no uncertain input.
    base=[arb(float(v)).mid() for v in x.ravel()];R=rotation(base)
    gram=x@x.T;g=8*(gram**3)@x;lam=(g*x).sum(axis=1)
    y=base+[arb(float(v)).mid() for v in lam]+[arb(0)]*15
    trace=[]
    for digits,target in [(120,'1e-95'),(180,'1e-150')]:
        ctx.dps=digits;previous=None
        while True:
            if time.time()>=deadline:raise TimeoutError('Original campaign deadline')
            F,J,H,E=system(y,base,R);res=norminf(F)
            trace.append({'digits':digits,'residual_upper':str(res),'energy':str(E),'elapsed_seconds':time.time()-start})
            print(json.dumps(trace[-1]),flush=True)
            if res<arb(target):break
            delta=J.solve(F);y=[(y[i]-delta[i,0]).mid() for i in range(N)]
            if previous is not None and res>=previous and res>arb(target):raise ArithmeticError('Newton residual did not decrease')
            previous=res
    output=Path(output);output.parent.mkdir(parents=True,exist_ok=True)
    refined={'vectors':[[y[6*i+k].str(170,radius=False) for k in range(6)] for i in range(24)],'method':'183-variable gauge KKT midpoint Newton; separate rigorous certificate follows','precision_digits':180,'multipliers':[v.str(170,radius=False) for v in y[144:]],'source':str(candidate)}
    output.with_name(output.stem+'.refined.json').write_text(json.dumps(refined,indent=2))
    # Uniform exact dyadic radius; arithmetic evaluation encloses this entire box.
    radius=arb((1,-180));Y=[arb(v.mid(),radius) for v in y]
    F0,J0,_,_=system(y,base,R);FY,JY,HY,EY=system(Y,base,R)
    C=J0.inv().mid();defect=eye(N)-C*JY;q=norminf(defect)
    eta=norminf(C*F0);kbound=(eta+q*radius).upper()
    contraction=bool(q<1 and kbound<radius)
    # Rotational invariance implies M^T mu=0 at any KKT root, where M=R^T Rot(x).
    M=R.transpose()*rotation(Y[:144]);M0=R.transpose()*rotation(y[:144]);MI=M0.inv().mid()
    rotation_defect=norminf(eye(15)-MI*M);transverse=bool(rotation_defect<1)
    # On the constraint/gauge tangent, both positive augmentations vanish.
    normals=arb_mat(144,24)
    for i in range(144):normals[i,i//6]=Y[i]
    A=HY+100*(normals*normals.transpose())+100*(R*R.transpose())
    Af=np.array([[float(A[i,j].mid()) for j in range(144)] for i in range(144)])
    eig,Qf=np.linalg.eigh((Af+Af.T)/2);Q=arb_mat([[arb(float(v)).mid() for v in row] for row in Qf])
    Qdef=norminf(eye(144)-Q.transpose()*Q);B=Q.transpose()*A*Q
    margins=[(B[i,i]-sum((abs(B[i,j]).upper() for j in range(144) if i!=j),arb(0))).lower() for i in range(144)]
    margin=min(margins);positive=bool(Qdef<1 and margin>0)
    # Explicit feasible reference: exactly normalize each saved decimal row.
    ref=json.loads(Path(reference).read_text())['vectors'];xr=[]
    for row in ref:
        v=[scalar(a) for a in row];norm=sum((a*a for a in v),arb(0)).sqrt();xr.append([a/norm for a in v])
    Er=sum((sum((a*b for a,b in zip(v,w)),arb(0))**4 for v in xr for w in xr),arb(0))-36
    lower=bool(EY.lower()>Er.upper());certified=contraction and transverse and positive and lower
    result={'certified':certified,'evidence_level':'rigorous_ball_arithmetic_certificate' if certified else 'certification_incomplete','software':'python-flint 0.9.0 Arb, 180 decimal digits','checker_source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'candidate_source_sha256':hashlib.sha256(Path(candidate).read_bytes()).hexdigest(),'started_epoch':start,'finished_epoch':time.time(),'original_deadline_epoch':deadline,'completed_within_window':time.time()<deadline,'dimension':N,'radius':str(radius),'contraction_norm_upper':str(q),'newton_displacement_upper':str(eta),'krawczyk_image_radius_upper':str(kbound),'self_map_strict':contraction,'rotation_transversality_defect_upper':str(rotation_defect),'rotation_rank_15_certified':transverse,'congruence_invertibility_defect_upper':str(Qdef),'gershgorin_positive_margin_lower':str(margin),'full_slice_hessian_positive_certified':positive,'candidate_energy_interval':str(EY),'reference_energy_interval':str(Er),'strictly_lower_reference_certified':lower,'refinement_trace':trace,'theorem':'Banach contraction of y -> y-C F(y) in the 183-dimensional closed box gives a unique KKT root. Invertibility of R^T Rot(x) and rotational invariance force all 15 gauge multipliers to vanish. The 24 norm equations give an exactly feasible configuration. Positive definiteness of H_L+100 NN^T+100 RR^T on the full 144-space implies positive Hessian on the 105-dimensional constraint/gauge slice. Transversality gives a local slice to common O(6) rotations, hence a local minimum in the entire product of spheres (strict modulo rotations). The interval energy comparison proves it is non-global.'}
    output.write_text(json.dumps(result,indent=2))
    # Full exact dyadic centers and approximate-inverse matrix support reproduction.
    def dyadic(v):return [str(a) for a in v.mid().man_exp()]
    output.with_name(output.stem+'.witness.json').write_text(json.dumps({'encoding':'Exact m*2^e, pair of decimal integer strings [m,e]','center':[dyadic(v) for v in y],'base':[dyadic(v) for v in base],'radius_exact':'2^-180','inverse_midpoint':[[dyadic(C[i,j]) for j in range(N)] for i in range(N)],'congruence_matrix':[[dyadic(Q[i,j]) for j in range(144)] for i in range(144)]},indent=2))
    print(json.dumps(result,indent=2),flush=True)

if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('candidate');p.add_argument('--reference',required=True);p.add_argument('--output',required=True);p.add_argument('--deadline',required=True,type=float);a=p.parse_args()
    # Independent wall-clock watchdog also covers a long C-library solve.
    def stop():time.sleep(max(0,a.deadline-time.time()));os._exit(124)
    threading.Thread(target=stop,daemon=True).start()
    main(a.candidate,a.reference,a.output,a.deadline)
