"""Host independent validation of model-adapted second-basin certificate.
Uses the independently derived block Hessian from verify_certificate, never
imports model or creator code. Only the exact witness is an input.
"""
import json,hashlib,sys,time
from pathlib import Path
from flint import arb,arb_mat,ctx
from verify_certificate import polynomial,rot,norm,I,dyad

def verify(witness,reference,augmentation=10000):
    ctx.dps=220;w=json.loads(Path(witness).read_text());assert w['encoding'].startswith('Exact m*2^e')
    c=[dyad(p) for p in w['center']];a=[dyad(p) for p in w['base']]
    C=arb_mat([[dyad(p) for p in row] for row in w['inverse_midpoint']]);L=arb_mat([[dyad(p) for p in row] for row in w['cholesky_factor']])
    assert len(c)==183 and len(a)==144 and C.nrows()==C.ncols()==183 and L.nrows()==L.ncols()==144
    assert all(z.is_exact() for z in c+a)
    assert all(L[i,j].is_exact() for i in range(144) for j in range(144))
    triangular=all(L[i,j]==0 for i in range(144) for j in range(i+1,144))
    diagonal=all(L[i,i]>0 for i in range(144));assert triangular and diagonal
    radius=arb((1,-180));box=[arb(z.mid(),radius) for z in c];R=rot(a)
    F0,_,_,_=polynomial(c,a,R);_,J,H,E=polynomial(box,a,R)
    q=norm(I(183)-C*J);eta=norm(C*F0);image=(eta+q*radius).upper()
    M=R.transpose()*rot(box[:144]);M0=R.transpose()*rot(c[:144]);trans=norm(I(15)-M0.inv().mid()*M)
    N=arb_mat(144,24)
    for i in range(144):N[i,i//6]=box[i]
    A=H+augmentation*(N*N.transpose()+R*R.transpose())
    Li=L.inv();B=Li*A*Li.transpose();defect=norm(I(144)-B)
    raw=json.loads(Path(reference).read_text())['vectors'];ref=[]
    for v in raw:
        z=[arb(str(t)) for t in v];s=sum((t*t for t in z),arb(0)).sqrt();ref.append([t/s for t in z])
    refE=sum((sum((s*t for s,t in zip(v,z)),arb(0))**4 for v in ref for z in ref),arb(0))-36
    tests={'contraction':bool(q<1),'strict_self_mapping':bool(image<radius),'rotation_transversality':bool(trans<1),'triangular_factor_nonsingular':bool(triangular and diagonal),'positive_full_slice_hessian':bool(defect<1),'lower_feasible_reference':bool(refE.upper()<E.lower())}
    return {'independently_verified':all(tests.values()),'precision_digits':220,'augmentation':augmentation,'tests':tests,'contraction_bound':str(q),'newton_displacement':str(eta),'image_radius_bound':str(image),'box_radius':str(radius),'transversality_bound':str(trans),'congruence_pd_defect_bound':str(defect),'energy':str(E),'reference_energy':str(refE),'witness_sha256':hashlib.sha256(Path(witness).read_bytes()).hexdigest(),'verifier_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'independent_polynomial_code_sha256':hashlib.sha256(Path(__file__).with_name('verify_certificate.py').read_bytes()).hexdigest(),'timestamp_epoch':time.time()}
if __name__=='__main__':
    import argparse
    p=argparse.ArgumentParser();p.add_argument('witness');p.add_argument('reference');p.add_argument('--output',required=True);a=p.parse_args();r=verify(a.witness,a.reference);Path(a.output).write_text(json.dumps(r,indent=2));print(json.dumps(r,indent=2));assert r['independently_verified']
