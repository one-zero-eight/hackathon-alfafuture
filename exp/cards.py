"""Theme cards: each of the variant's top-10 items + up to N related headlines from the persona's top-300 candidates."""
import sys, json, os, numpy as np
V, OUT = sys.argv[1], sys.argv[2]
sys.argv = sys.argv[:1]; sys.path.insert(0, "exp")
import retrieve as R, packets as P
M = "large"; N_REL = 4; REL_SIM = 0.84
E = R.doc_emb(M); ids = list(R.corpus.id)
top = json.load(open(f"exp/runs/{V}/top.json")); os.makedirs(f"exp/runs/{OUT}", exist_ok=True)
for p, lst in top.items():
    q, kw, _ = R.profile(p, "queries"); S = E @ R.encode(M, q, "query").T
    score = np.sort(S, 1)[:, -3:].mean(1) + 0.02 * np.minimum(R.keyword_hits(kw), 5)
    cand = [i for i in np.argsort(-score)[:300]]
    cards = [ids.index(x) for x in lst[:10]]; used = set(cards); out = []
    for ci in cards:
        rel = [j for j in sorted(cand, key=lambda j: -(E[ci] @ E[j])) if j not in used and E[ci] @ E[j] >= REL_SIM][:N_REL]
        used |= set(rel)
        txt = P.item(ids[ci])
        if rel:
            txt += "\n    Related this week: " + " ; ".join(f"[{ids[j]}] {R.corpus.title[j]}" for j in rel)
        out.append(txt)
    open(f"exp/runs/{OUT}/{p}_news.txt", "w").write("\n\n".join(out))
json.dump(top, open(f"exp/runs/{OUT}/top.json", "w")); print(OUT, "cards written")
