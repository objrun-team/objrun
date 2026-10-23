import numpy as np
def encode(v):
    if isinstance(v,np.generic): return encode(v.item())
    if v is None or isinstance(v,(str,bool,int,float)): return v
    if isinstance(v,complex): return {'kind':'complex','real':v.real,'imag':v.imag}
    if isinstance(v,np.ndarray): return {'kind':'array','dtype':str(v.dtype),'items':encode(v.tolist())}
    if isinstance(v,(tuple,list,set,frozenset)): return {'kind':type(v).__name__,'items':[encode(x) for x in v]}
    if isinstance(v,dict): return {'kind':'dict','items':[[encode(k),encode(x)] for k,x in v.items()]}
    raise TypeError('UnsupportedRPCObject')
def decode(v):
    if not isinstance(v,dict): return v
    k=v['kind']
    if k=='complex': return complex(v['real'],v['imag'])
    if k=='array': return np.array(decode(v['items']),dtype=v['dtype'])
    if k=='dict': return {decode(a):decode(b) for a,b in v['items']}
    return {'tuple':tuple,'list':list,'set':set,'frozenset':frozenset}[k](decode(x) for x in v['items'])
