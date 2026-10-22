"""Retrieval metrics vs gold labels. Usage: python exp/metrics.py v0_group v1_persona ..."""
import json, glob, os, sys
import numpy as np
ROOT = os.path.dirname(os.path.abspath(__file__))
gold = {}
for f in sorted(glob.glob(os.path.join(ROOT, "gold", "map_*.json"))):
    for p, items in json.load(open(f)).items():
        for it in items:
            gold.setdefault(p, {})[it["id"]] = max(it["rel"], gold.get(p, {}).get(it["id"], 0))
def ndcg(ranked, rel, k=10):
    g = [2 ** rel.get(i, 0) - 1 for i in ranked[:k]]
    ideal = sorted((2 ** r - 1 for r in rel.values()), reverse=True)[:k]
    dcg = sum(x / np.log2(i + 2) for i, x in enumerate(g))
    idcg = sum(x / np.log2(i + 2) for i, x in enumerate(ideal))
    return dcg / idcg if idcg else 0
print(f"gold sizes rel>=2: " + " ".join(f"{p}={sum(r>=2 for r in v.values())}" for p, v in sorted(gold.items())))
print(f"{'variant':16} {'nDCG@10':>8} {'P@10(>=2)':>10} {'R@10(rel3)':>11} {'R@30(>=2)':>10}")
for v in sys.argv[1:]:
    top = json.load(open(os.path.join(ROOT, "runs", v, "top.json")))
    rows = []
    for p, rel in gold.items():
        r = top[p]
        r3 = [i for i, x in rel.items() if x == 3]; r2 = [i for i, x in rel.items() if x >= 2]
        rows.append((ndcg(r, rel), np.mean([rel.get(i, 0) >= 2 for i in r[:10]]),
                     len(set(r[:10]) & set(r3)) / max(len(r3), 1), len(set(r[:30]) & set(r2)) / max(len(r2), 1)))
    m = np.mean(rows, axis=0)
    per = " ".join(f"{p}:{x[0]:.2f}" for p, x in zip(gold, rows))
    print(f"{v:16} {m[0]:8.3f} {m[1]:10.3f} {m[2]:11.3f} {m[3]:10.3f}   nDCG per persona {per}")
oracle = json.load(open(os.path.join(ROOT, "runs", "oracle", "top.json")))
print("overlap@10 with gold ideal top-10:")
for v in sys.argv[1:]:
    top = json.load(open(os.path.join(ROOT, "runs", v, "top.json")))
    o = [len(set(top[p][:10]) & set(oracle[p])) for p in sorted(oracle)]
    print(f"  {v:16} mean {np.mean(o):.1f}/10  per persona {o}")
