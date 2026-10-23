import numpy as np

def lanczos(A, b, m):
    q = np.asarray(b, dtype=float).reshape(-1)
    Q = np.zeros((len(q), m + 1), dtype=float)
    Q[:, 0] = q / np.linalg.norm(q)
    beta = 0.0
    for j in range(m):
        w = A @ Q[:, j]
        if j:
            w = w - beta * Q[:, j - 1]
        alpha = np.dot(Q[:, j], w)
        w = w - alpha * Q[:, j]
        w = w - Q[:, :j + 1] @ (Q[:, :j + 1].T @ w)
        beta = np.linalg.norm(w)
        if beta == 0:
            break
        Q[:, j + 1] = w / beta
    return Q
