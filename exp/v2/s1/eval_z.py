# S1 check: per-query z-normalisation (against hubness of generic queries), doc vectors max(A0, K1).
import numpy as np, r1, eval_lib as L
from r1 import QS, evaluate, enc, A0
K1 = np.load('s1/keys_k1.npy')
def zs(Q, X): S = enc(Q) @ X.T; return (S - S.mean(1, keepdims=True)) / S.std(1, keepdims=True)
def score(Q): return np.maximum(np.sort(zs(Q, A0), 0)[-3:].mean(0), np.sort(zs(Q, K1), 0)[-3:].mean(0))
ARMS = {'Q1+Q2 z': lambda p: score(QS['Q1'](p) + QS['Q2'](p)), 'L1 z': lambda p: score(L.l1(p)), 'L1+Q2 z': lambda p: score(L.l1(p) + QS['Q2'](p))}
for n, f in ARMS.items():
    r, _ = evaluate(f); print(f"{n:10s} andcg={r['all_andcg']} dev={r['dev_ndcg']} test={r['test_ndcg']} dev_p10={r['dev_p10']}", flush=True)
