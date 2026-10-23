import numpy as np


def tensor(*args):
    out=np.array([[1.]])
    for item in args:
        out=np.kron(out,item)
    return out


def ket(dim,args):
    if isinstance(args,(list,tuple,np.ndarray)):
        dimensions=[dim]*len(args) if np.isscalar(dim) else list(dim)
        return tensor(*(ket(d,j) for d,j in zip(dimensions,args)))
    out=np.zeros((int(dim),1),dtype=float)
    out[int(args),0]=1.
    return out


def multi_rail_encoding_state(rails):
    state=np.zeros((2**(2*rails),1),dtype=float)
    for i in range(rails):
        bits=[int(j==i) for j in range(rails)]
        state+=ket(2,bits+bits)
    state/=np.sqrt(rails)
    return state@state.T


def apply_channel(K,rho,sys=None,dim=None):
    if sys is None:
        return sum(op@rho@op.conj().T for op in K)
    dimensions=list(dim)
    count=len(dimensions)
    state=np.asarray(rho).reshape(dimensions+dimensions)
    for subsystem in sys:
        axis=subsystem-1
        result=np.zeros_like(state,dtype=np.result_type(state,*K))
        for op in K:
            left=np.tensordot(op,state,axes=(1,axis))
            left=np.moveaxis(left,0,axis)
            both=np.tensordot(op.conj(),left,axes=(1,count+axis))
            both=np.moveaxis(both,0,count+axis)
            result+=both
        state=result
    size=int(np.prod(dimensions))
    return state.reshape(size,size)


def generalized_amplitude_damping_channel(gamma,N):
    return [np.sqrt(1-N)*np.diag([1.,np.sqrt(1-gamma)]),
            np.sqrt(gamma*(1-N))*np.array([[0.,1.],[0.,0.]]),
            np.sqrt(N)*np.diag([np.sqrt(1-gamma),1.]),
            np.sqrt(gamma*N)*np.array([[0.,0.],[1.,0.]])]


def output_state(rails,gamma_1,N_1,gamma_2,N_2):
    dim=[2]*(2*rails)
    state=multi_rail_encoding_state(rails)
    state=apply_channel(generalized_amplitude_damping_channel(gamma_1,N_1),
                        state,list(range(1,rails+1)),dim)
    return apply_channel(generalized_amplitude_damping_channel(gamma_2,N_2),
                         state,list(range(rails+1,2*rails+1)),dim)


def measurement(rails):
    projector=np.zeros((2**rails,2**rails))
    for i in range(rails):
        projector[2**i,2**i]=1.
    return tensor(projector,projector)


def syspermute(X,perm,dim):
    n=len(dim)
    axes=[p-1 for p in perm]
    reordered=np.asarray(X).reshape(list(dim)+list(dim)).transpose(
        axes+[n+a for a in axes])
    size=int(np.prod(dim))
    return reordered.reshape(size,size)


def partial_trace(X,sys,dim):
    keep=[i for i in range(1,len(dim)+1) if i not in sys]
    traced=list(sys)
    ordered=syspermute(X,keep+traced,dim)
    kept=int(np.prod([dim[i-1] for i in keep]))
    removed=int(np.prod([dim[i-1] for i in traced]))
    return np.trace(ordered.reshape(kept,removed,kept,removed),axis1=1,axis2=3)


def entropy(rho):
    values=np.linalg.eigvalsh(rho)
    values=values[values>0]
    return float(-np.sum(values*np.log2(values)))


def coherent_inf_state(rho_AB,dimA,dimB):
    return entropy(partial_trace(rho_AB,[1],[dimA,dimB]))-entropy(rho_AB)


def rate(rails,gamma_1,N_1,gamma_2,N_2):
    state=output_state(rails,gamma_1,N_1,gamma_2,N_2)
    projector=measurement(rails)
    probability=float(np.trace(projector@state))
    if probability==0:
        return 0.
    post=projector@state@projector/probability
    return probability*coherent_inf_state(post,2**rails,2**rails)/rails
