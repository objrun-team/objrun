import numpy as np
from scipy.linalg import solve_banded

def init_AB(N,L,h):
    c=1j*h*1.0545718e-34/(4*9.109e-31*(L/N)**2)
    A=np.diag(np.full(N-1,1+2*c,dtype=complex))
    B=np.diag(np.full(N-1,1-2*c,dtype=complex))
    if N>2:
        A+=np.diag(np.full(N-2,-c),1)+np.diag(np.full(N-2,-c),-1)
        B+=np.diag(np.full(N-2,c),1)+np.diag(np.full(N-2,c),-1)
    return A,B

def crank_nicolson(sigma,kappa,T,nstep,N,L):
    x=np.linspace(0,L,N+1)
    psi=np.exp(-(x-L/2)**2/(2*sigma*sigma))*np.exp(1j*kappa*x)
    psi[0]=psi[-1]=0
    c=1j*(T/nstep)*1.0545718e-34/(4*9.109e-31*(L/N)**2)
    band=np.zeros((3,N-1),dtype=complex)
    band[1]=1+2*c;band[0,1:]=-c;band[2,:-1]=-c
    for _ in range(nstep):
        rhs=(1-2*c)*psi[1:-1]+c*(psi[:-2]+psi[2:])
        psi[1:-1]=solve_banded((1,1),band,rhs)
    return psi.real
