"""Independent checker 2: integer matrix multiplication, no checker 1 imports."""
import json,sys

def verify(filename,order=99,valency=14,adjacent=1,nonadjacent=2):
    with open(filename,encoding='utf-8') as f:data=json.load(f)
    matrix=data.get('matrix') if isinstance(data,dict) else data
    if type(matrix)!=list or len(matrix)!=order:return {'valid':False,'error':'order'}
    for row in matrix:
        if type(row)!=list or len(row)!=order:return {'valid':False,'error':'row length'}
        for entry in row:
            if type(entry)!=int or entry<0 or entry>1:return {'valid':False,'error':'not a binary integer'}
    symmetric=True; diagonal=True; degree_errors=0
    for i in range(order):
        if matrix[i][i]!=0:diagonal=False
        if sum(matrix[i])!=valency:degree_errors+=1
        for j in range(order):
            if matrix[i][j]!=matrix[j][i]:symmetric=False
    product=[[0]*order for _ in range(order)]
    for i in range(order):
        for t in range(order):
            for j in range(order):product[i][j]+=matrix[i][t]*matrix[t][j]
    bad=0; square=0; upper_bad=0; residual=[]
    for i in range(order):
        for j in range(order):
            rhs=(valency-nonadjacent if i==j else 0)+(adjacent-nonadjacent)*matrix[i][j]+nonadjacent
            delta=product[i][j]-rhs
            if delta:bad+=1;residual.append([i,j,delta])
            if delta and i<j:upper_bad+=1
            square+=delta*delta
    return {'valid':symmetric and diagonal and degree_errors==0 and bad==0,
            'symmetric':symmetric,'zero_diagonal':diagonal,'degree_violations':degree_errors,
            'identity_violations':bad,'upper_identity_violations':upper_bad,
            'identity_squared_residual':square,'residual':residual,
            'equation':'A*A=(k-mu)I+(lambda-mu)A+mu*J; exact Python integers'}

if __name__=='__main__':
    try:out=verify(sys.argv[1],*(map(int,sys.argv[2:6]) if len(sys.argv)>=6 else ()))
    except Exception as e:out={'valid':False,'error':str(e)}
    print(json.dumps(out))
