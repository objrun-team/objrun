"""Independent Decimal checker: backward Williamson conversion and explicit trees."""
from decimal import Decimal,localcontext

def check(raw,reference,digits=160):
    with localcontext() as ctx:
        ctx.prec=digits
        def number(x):
            parts=str(x).split('/')
            return Decimal(parts[0])/(Decimal(parts[1]) if len(parts)==2 else 1)
        a=list(map(number,raw['alpha'])); B=list(map(number,raw['beta']))
        A=[[Decimal(0) for j in range(5)] for i in range(5)]
        for i in range(1,5):
            A[i][i-1]=B[i-1]
            for j in range(i-2,-1,-1): A[i][j]=B[j]+a[j+1]*A[i][j+1]
        b=[Decimal(0)]*5;b[4]=B[4]
        for j in range(3,-1,-1): b[j]=B[j]+a[j+1]*b[j+1]
        def dot(x,y):return sum((u*v for u,v in zip(x,y)),Decimal(0))
        def mat(x):return [dot(row,x) for row in A]
        c=[sum(row) for row in A];ac=mat(c);aac=mat(ac)
        order=[sum(b)-1,dot(b,c)-number('1/2'),dot(b,[x*x for x in c])-number('1/3'),dot(b,ac)-number('1/6')]
        tau=[(dot(b,[x**3 for x in c])-number('1/4'))/6,(dot(b,mat([x*x for x in c]))-number('1/12'))/2,dot(b,[c[i]*ac[i] for i in range(5)])-number('1/8'),dot(b,aac)-number('1/24')]
        v=[Decimal(1)]*5;poly=[Decimal(1)]
        for k in range(5):poly.append(dot(b,v));v=mat(v)
        resid=max(map(abs,order+[x-number(y) for x,y in zip(poly,reference)]))
        return {'precision_digits':digits,'max_constraint_residual':str(resid),'error_norm':str(sum(t*t for t in tau).sqrt()),'error_coefficients_bush_Ac2_cAc_chain':list(map(str,tau)),'A':[[str(v) for v in row] for row in A],'b':list(map(str,b)),'c':list(map(str,c)),'stability_ascending':list(map(str,poly))}
