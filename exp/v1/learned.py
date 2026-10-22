"""Learned ranker per persona: logistic regression on [doc embedding, query sims, kw hits].
2-fold by story chunk (even/odd chunks) so no story is scored by a model trained on it."""
import sys, json, glob, os, numpy as np
sys.argv = sys.argv[:1] + sys.argv[1:]; sys.path.insert(0, "exp")
import retrieve as R
from sklearn.linear_model import LogisticRegression
M = os.environ.get("M", "small")
E = R.doc_emb(M); ids = list(R.corpus.id); n = len(ids)
fold = np.array([ (i // 251) % 2 for i in range(n)])
gold = {}
for f in glob.glob("exp/gold/map_*.json"):
    for p, its in json.load(open(f)).items():
        for it in its: gold.setdefault(p, {})[it["id"]] = max(it["rel"], gold.get(p, {}).get(it["id"], 0))
out = {}
for p in R.personas:
    q, kw, _ = R.profile(p, "queries"); Q = R.encode(M, q, "query"); S = E @ Q.T
    X = np.hstack([E, S, np.sort(S, 1)[:, -3:], R.keyword_hits(kw)[:, None] / 5])
    y = np.array([gold[p].get(i, 0) >= 2 for i in ids]).astype(int)
    score = np.zeros(n)
    for f in (0, 1):
        tr, te = fold != f, fold == f
        clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000).fit(X[tr], y[tr])
        score[te] = clf.predict_proba(X[te])[:, 1]
    out[p] = [ids[i] for i in np.argsort(-score)[:30]]
d = f"exp/runs/l1_learned_{M}"; os.makedirs(d, exist_ok=True)
json.dump(out, open(d + "/top.json", "w")); print("done", d)
