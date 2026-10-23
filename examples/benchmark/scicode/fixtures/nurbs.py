import numpy as np

def Bspline(xi,i,p,Xi):
    j=int(i)-1;p=int(p);knots=np.asarray(Xi)
    if p==0:return float(knots[j]<=xi<knots[j+1])
    left=right=0.
    span=knots[j+p]-knots[j]
    if span: left=(xi-knots[j])/span*Bspline(xi,i,p-1,knots)
    span=knots[j+p+1]-knots[j+1]
    if span:right=(knots[j+p+1]-xi)/span*Bspline(xi,i+1,p-1,knots)
    return left+right

def NURBS_2D(xi_1,xi_2,i_1,i_2,p_1,p_2,n_1,n_2,Xi_1,Xi_2,w):
    first=np.array([Bspline(xi_1,i,p_1,Xi_1) for i in range(1,n_1+1)])
    second=np.array([Bspline(xi_2,i,p_2,Xi_2) for i in range(1,n_2+1)])
    weighted=np.outer(first,second)*np.reshape(w,(n_1,n_2))
    total=weighted.sum()
    return float(weighted[i_1-1,i_2-1]/total) if total else 0.
