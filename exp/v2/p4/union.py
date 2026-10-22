# Union of separately-run card (dense base) and graph (G1) retrieval: RRF, interleave, top-5+top-5.
import numpy as np, r1, r2
from r1 import evaluate, N
def interleave(a, b):  # alternate a, b rankings, skip duplicates; returns a score vector
    out, seen = [], set()
    for x, y in zip(np.argsort(-a), np.argsort(-b)):
        for i in (x, y):
            if i not in seen: seen.add(i); out.append(i)
    s = np.zeros(N); s[out] = np.arange(len(out), 0, -1); return s
def split5(a, b, k=5):  # top-k from each, then the rest by a
    s = a - a.max() - 1; top = list(np.argsort(-a)[:k]); top += [i for i in np.argsort(-b) if i not in top][:k]
    s[top] = 100 + np.arange(len(top), 0, -1); return s
if __name__ == "__main__":
  G = {'G1': r1.g1, 'X1': r1.x1}
  for g, gf in G.items():
    arms = {f'rrf(base,{g})': lambda p: r1.rrf(r2.base(p), gf(p)), f'interleave(base,{g})': lambda p: interleave(r2.base(p), gf(p)),
            f'5+5(base,{g})': lambda p: split5(r2.base(p), gf(p))}
    for n, f in arms.items():
        r, _ = evaluate(f); print(f"{n:22s} andcg={r['all_andcg']} dev={r['dev_ndcg']} test={r['test_ndcg']} test_r50={r['test_r50']}", flush=True)
