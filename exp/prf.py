"""Rocchio pseudo-relevance feedback on bge-m3: q' = a*q + b*mean(top-k docs) per query; then top3 agg + kw."""
import sys, json, os, numpy as np
sys.path.insert(0, "exp"); import retrieve as R
A, B, K = float(os.environ.get("A", 1)), float(os.environ.get("B", 0.5)), int(os.environ.get("K", 10))
E = R.doc_emb("bgem3"); ids = list(R.corpus.id); out = {}
for p in R.personas:
    q, kw, _ = R.profile(p, "queries"); Q = R.encode("bgem3", q, "query")
    S = E @ Q.T
    Q2 = np.stack([A * Q[j] + B * E[np.argsort(-S[:, j])[:K]].mean(0) for j in range(len(q))])
    Q2 /= np.linalg.norm(Q2, axis=1, keepdims=True)
    S2 = E @ Q2.T
    score = np.sort(S2, 1)[:, -3:].mean(1) + 0.02 * np.minimum(R.keyword_hits(kw), 5)
    out[p] = [ids[i] for i in np.argsort(-score)[:30]]
name = f"prf_b{B}_k{K}"; os.makedirs(f"exp/runs/{name}", exist_ok=True)
json.dump(out, open(f"exp/runs/{name}/top.json", "w")); print("done", name)
