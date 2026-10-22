# S1: K1 keys vs current doc vectors, with current queries (Q1+Q2).
import numpy as np, r1
from r1 import QS, evaluate, enc, A0, A1
K1 = np.load('s1/keys_k1.npy')
def top3(Q, X): S = enc(Q) @ X.T; return np.sort(S, 0)[-3:].mean(0)
q = lambda p: QS['Q1'](p) + QS['Q2'](p)
ARMS = {'A2 (current)': lambda p: np.maximum(top3(q(p), A0), top3(q(p), A1)),
        'K1 only': lambda p: top3(q(p), K1),
        'max(A0,K1)': lambda p: np.maximum(top3(q(p), A0), top3(q(p), K1)),
        'max(A0,A1,K1)': lambda p: np.maximum.reduce([top3(q(p), X) for X in (A0, A1, K1)])}
for n, f in ARMS.items():
    r, _ = evaluate(f); print(f"{n:16s} andcg={r['all_andcg']} dev={r['dev_ndcg']} test={r['test_ndcg']} dev_p10={r['dev_p10']} test_p10={r['test_p10']}", flush=True)
