"""Hybrid: BM25 over lemmas (per query, max) fused with dense top3 via reciprocal rank fusion."""
import sys, json, os, numpy as np
sys.path.insert(0, "exp"); import retrieve as R
from collections import Counter
M = os.environ.get("M", "small"); K = 60
docs = [R.lemma_seq(t) for t in R.doc_texts()]
N = len(docs); avg = np.mean([len(d) for d in docs])
df = Counter(w for d in docs for w in set(d)); tfs = [Counter(d) for d in docs]
def bm25(q, k1=1.5, b=0.75):
    s = np.zeros(N)
    for w in set(R.lemma_seq(q)):
        if w not in df: continue
        idf = np.log(1 + (N - df[w] + .5) / (df[w] + .5))
        for i, tf in enumerate(tfs):
            f = tf.get(w, 0)
            if f: s[i] += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(docs[i]) / avg))
    return s
E = R.doc_emb(M); out = {}
for p in R.personas:
    q, kw, _ = R.profile(p, "queries")
    S = E @ R.encode(M, q, "query").T
    dense = np.sort(S, 1)[:, -3:].mean(1) + 0.02 * np.minimum(R.keyword_hits(kw), 5)
    B = np.stack([bm25(x) for x in q + [" ".join(kw)]], 1)
    lex = np.sort(B / (B.max(0, keepdims=True) + 1e-9), 1)[:, -3:].mean(1)
    rr = lambda s: 1 / (K + (-s).argsort().argsort())
    fused = rr(dense) + rr(lex)
    out[p] = [R.corpus.id.iloc[i] for i in np.argsort(-fused)[:30]]
d = f"exp/runs/h1_hybrid_{M}"; os.makedirs(d, exist_ok=True); json.dump(out, open(d + "/top.json", "w")); print("done", d)
