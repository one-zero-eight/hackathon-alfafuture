# Raw vs key vs both, plain and z-normalised; queries Q1+Q2.
import numpy as np, r1
from r1 import QS, evaluate, enc, A0, A1
K1 = np.load('s1/keys_k1.npy')
def t3(S): return np.sort(S, 0)[-3:].mean(0)
def z(S): return (S - S.mean(1, keepdims=True)) / S.std(1, keepdims=True)
q = lambda p: enc(QS['Q1'](p) + QS['Q2'](p))
V = {'raw': [A0], 'card': [A1], 'key': [K1], 'raw+key': [A0, K1], 'raw+card+key': [A0, A1, K1]}
for name, Xs in V.items():
    for zn in (False, True):
        f = lambda p, Xs=Xs, zn=zn: np.maximum.reduce([t3(z(Q @ X.T) if zn else Q @ X.T) for Q in [q(p)] for X in Xs])
        r, per = evaluate(f); print(f"{name:13s} {'z' if zn else '-'} andcg={r['all_andcg']} dev={r['dev_ndcg']} test={r['test_ndcg']}", flush=True)
