import numpy as np

def WJ(A,b,eps,x_true,x0,omega):
    A=np.asarray(A,dtype=float);b=np.asarray(b,dtype=float);x=np.asarray(x0,dtype=float).copy()
    diagonal=np.diag(A)
    for _ in range(1000000):
        next_x=x+omega*(b-A@x)/diagonal
        change=np.linalg.norm(next_x-x)
        x=next_x
        if change<eps:break
    else:raise ValueError('Jacobi did not converge')
    return float(np.linalg.norm(A@x-b)),float(np.linalg.norm(x-np.asarray(x_true)))
