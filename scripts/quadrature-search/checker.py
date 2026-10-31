"""Frozen G: all Cartesian moments through degree 7, strict PI, full S3 x C2.

Numerical construction only, not an exactness proof. Never imports candidate code.
"""
import argparse
import hashlib
import itertools
import json
import subprocess
import sys
from fractions import Fraction
from math import comb, factorial
from pathlib import Path
import mpmath as mp

DEGREE = 7
TOL = '1e-40'

def cartesian_moment(a, b, c):
    if c % 2:
        return Fraction(0)
    triangle = sum((Fraction(4 * comb(a, i) * comb(b, j) * 2**(i+j)
                            * (-1)**(a+b-i-j) * factorial(i) * factorial(j),
                            factorial(i+j+2))
                    for i in range(a+1) for j in range(b+1)), Fraction(0))
    return triangle * Fraction(2, c+1)

def check(path):
    mp.mp.dps = 100
    tol = mp.mpf(TOL)
    data = json.loads(Path(path).read_text(encoding='utf-8-sig'))
    if data.get('domain') != 'prism' or data.get('degree') != 7:
        raise ValueError('domain must be prism; degree must be 7')
    raw = data['nodes']
    if not isinstance(raw, list) or not raw:
        raise ValueError('nodes must be a nonempty list of [x,y,z,w] decimal strings')
    if any(not isinstance(r,list) or len(r)!=4 or any(not isinstance(v,str) for v in r) for r in raw):
        raise ValueError('each node must contain four decimal strings; do not round through binary64')
    nodes = [tuple(mp.mpf(v) for v in r) for r in raw]
    if any(not mp.isfinite(v) for r in nodes for v in r):
        raise ValueError('nonfinite coordinate or weight')
    margins = [min(x+1,y+1,-x-y,1-z,1+z) for x,y,z,w in nodes]
    positive = min(r[3] for r in nodes)>0
    interior = min(margins)>0
    distance = min((max(abs(nodes[i][k]-nodes[j][k]) for k in range(3))
                    for i in range(len(nodes)) for j in range(i)), default=mp.inf)
    distinct = distance > mp.mpf('1e-35')
    symmetry_error = mp.mpf(0)
    symmetric = True
    for permutation in itertools.permutations(range(3)):
        for sign in (-1,1):
            used = set()
            for x,y,z,w in nodes:
                bary = (-(x+y)/2,(x+1)/2,(y+1)/2)
                p = [bary[i] for i in permutation]
                target = (2*p[1]-1,2*p[2]-1,sign*z,w)
                errors = [max(abs(a-b) for a,b in zip(target,r)) for r in nodes]
                j = min(range(len(nodes)),key=errors.__getitem__)
                symmetry_error=max(symmetry_error,errors[j])
                if j in used or errors[j]>tol: symmetric=False
                used.add(j)
    moments=[]
    for a in range(DEGREE+1):
        for b in range(DEGREE+1-a):
            for c in range(DEGREE+1-a-b):
                exact=cartesian_moment(a,b,c)
                target=mp.mpf(exact.numerator)/exact.denominator
                value=mp.fsum(w*x**a*y**b*z**c for x,y,z,w in nodes)
                error=abs(value-target)
                moments.append({'powers':[a,b,c],'exact':str(exact),'absolute_error':mp.nstr(error,30)})
    worst=max(moments,key=lambda m:mp.mpf(m['absolute_error']))
    valid=positive and interior and distinct and symmetric and mp.mpf(worst['absolute_error'])<=tol
    return {'valid':bool(valid),'size':len(nodes),'domain':'prism','degree':7,
            'precision_digits':100,'tolerance':TOL,'moment_count':len(moments),
            'max_moment_error':worst['absolute_error'],'worst_monomial':worst['powers'],
            'min_weight':mp.nstr(min(r[3] for r in nodes),30),
            'min_boundary_slack':mp.nstr(min(margins),30),'min_node_separation':mp.nstr(distance,30),
            'positive':bool(positive),'interior':bool(interior),'distinct':bool(distinct),
            'symmetry':'S3 barycentric permutations x z reflection; equal weights',
            'symmetry_valid':bool(symmetric),'max_symmetry_error':mp.nstr(symmetry_error,30),
            'moments':moments,'evidence_strength':'high-precision numerical construction; no exactness certificate'}

def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('candidate')
    parser.add_argument('--threshold',type=int,default=36)
    parser.add_argument('--independent',action='store_true')
    args=parser.parse_args()
    try:
        report=check(args.candidate)
        if args.independent:
            p=subprocess.run([sys.executable,str(Path(__file__).with_name('independent_check.py')),args.candidate],capture_output=True,text=True,check=True)
            independent=json.loads(p.stdout)
            report['independent']=independent
            report['valid']=report['valid'] and independent['valid']
        report['improved']=report['valid'] and report['size']<args.threshold
        report['threshold']=args.threshold
        report['sha256']=hashlib.sha256(Path(args.candidate).read_bytes()).hexdigest()
    except (ValueError,KeyError,TypeError,ArithmeticError) as e:
        report={'valid':False,'improved':False,'error':str(e)}
    print(json.dumps(report))

if __name__=='__main__': main()
