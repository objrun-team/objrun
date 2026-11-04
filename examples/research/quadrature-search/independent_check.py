"""Independent stdlib Decimal verifier; barycentric basis, separate exact integrals.

No imports from checker.py, the search, or author code. 120 full basis moments.
"""
import json
import sys
from decimal import Decimal, localcontext
from math import factorial
from pathlib import Path

def verify(path):
    with localcontext() as ctx:
        ctx.prec=110
        obj=json.loads(Path(path).read_text(encoding='utf-8-sig'))
        if obj['domain']!='prism' or obj['degree']!=7: raise ValueError('wrong problem')
        rows=[[Decimal(v) for v in r] for r in obj['nodes']]
        if not rows or any(len(r)!=4 or any(not v.is_finite() for v in r) for r in rows): raise ValueError('bad data')
        # Unit simplex coordinates; dx dy = 4 du dv; z remains in (-1,1).
        q=[((x+1)/2,(y+1)/2,z,w) for x,y,z,w in rows]
        zero=Decimal(0); one=Decimal(1); tol=Decimal('1e-40')
        margins=[min(u,v,1-u-v,1-abs(z),w) for u,v,z,w in q]
        distinct=all(max(abs(rows[i][k]-rows[j][k]) for k in range(3))>Decimal('1e-35') for i in range(len(rows)) for j in range(i))
        moments=[]
        # Different basis and enumeration from the Cartesian checker.
        for total in range(8):
            for c in range(total+1):
                for b in range(total-c+1):
                    a=total-b-c
                    expected=zero if c%2 else Decimal(8*factorial(a)*factorial(b))/Decimal(factorial(a+b+2)*(c+1))
                    actual=sum((w*(u**a if a else one)*(v**b if b else one)*(z**c if c else one) for u,v,z,w in q),zero)
                    moments.append({'powers':[a,b,c],'absolute_error':str(abs(actual-expected))})
        # Generators suffice for S3 x C2; each map must be a weight-preserving bijection.
        symmetric=True; symmetry_error=zero
        for op in range(3):
            indices=[]
            for u,v,z,w in q:
                transformed=(v,u,z,w) if op==0 else ((1-u-v,u,z,w) if op==1 else (u,v,-z,w))
                errors=[max(abs(a-b) for a,b in zip(transformed,p)) for p in q]
                idx=min(range(len(q)),key=errors.__getitem__)
                indices.append(idx); symmetry_error=max(symmetry_error,errors[idx])
            symmetric=symmetric and len(set(indices))==len(q)
        maximum=max(Decimal(m['absolute_error']) for m in moments)
        return {'valid':bool(min(margins)>0 and distinct and symmetric and symmetry_error<=tol and maximum<=tol),
                'implementation':'stdlib Decimal; simplex-factorial moments; generator bijections',
                'precision_digits':110,'moment_count':len(moments),'max_moment_error':str(maximum),
                'min_positive_margin':str(min(margins)),'max_symmetry_error':str(symmetry_error),
                'moments':moments}

if __name__=='__main__':
    try: result=verify(sys.argv[1])
    except Exception as e: result={'valid':False,'error':str(e)}
    print(json.dumps(result))
