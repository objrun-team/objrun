import numpy as np

def init_matrix(dim,noise):
    A=np.diag(np.arange(1,dim+1,dtype=float))+noise*np.random.normal(size=(dim,dim))
    return (A+A.T)/2

def davidson_solver(matrixA,num_eigenvalues,threshold):
    A=np.asarray(matrixA,dtype=float);n=len(A);k=int(num_eigenvalues)
    basis=np.eye(n)[:,:min(n,max(k,2))]
    diagonal=np.diag(A)
    for _ in range(2*n+2):
        basis=np.linalg.qr(basis,mode='reduced')[0]
        projected=basis.T@A@basis
        values,vectors=np.linalg.eigh(projected)
        values=values[:k];ritz=basis@vectors[:,:k]
        residual=A@ritz-ritz*values
        if np.max(np.linalg.norm(residual,axis=0))<threshold:return values
        corrections=[]
        for j in range(k):
            denom=diagonal-values[j]
            denom=np.where(np.abs(denom)<1e-12,1e-12,denom)
            q=-residual[:,j]/denom
            q-=basis@(basis.T@q)
            for old in corrections:q-=old*np.dot(old,q)
            length=np.linalg.norm(q)
            if length>1e-12:corrections.append(q/length)
        if not corrections:
            # Complete an orthonormal subspace when a preconditioner stagnates.
            for e in np.eye(n):
                q=e-basis@(basis.T@e);length=np.linalg.norm(q)
                if length>1e-12:corrections.append(q/length);break
        if not corrections: return values
        basis=np.column_stack([basis,*corrections])[:,:n]
    raise ValueError('Davidson did not converge')
