"""Final light pipeline: fused dense retrieval (bge-m3 + e5-large) + keyword bonus, theme-capped top-10, theme cards.
Usage: python exp/pipeline.py <name> [key=value ...]   writes exp/runs/<name>/{top.json,P*_news.txt}"""
import sys, json, os, numpy as np
args = dict(a.split("=") for a in sys.argv[2:]); NAME = sys.argv[1]; sys.argv = sys.argv[:1]
sys.path.insert(0, "exp"); import retrieve as R, packets as P
W_E5 = float(args.get("w_e5", 0.5)); KW = float(args.get("kw", 0.02)); CAP = int(args.get("cap", 1))
THEME = float(args.get("theme", 0.74)); REL = float(args.get("rel", 0.62)); NREL = int(args.get("nrel", 4))
SEL = args.get("sel", "plain"); POOL = int(args.get("pool", 300)); RELFMT = args.get("relfmt", "title"); RELN = int(args.get("reln", 220))
ids = list(R.corpus.id); EB = R.doc_emb("bgem3"); EL = R.doc_emb("large")
def z(x): return (x - x.mean()) / x.std()
top, d = {}, f"exp/runs/{NAME}"; os.makedirs(d, exist_ok=True)
for p in R.personas:
    q, kw, _ = R.profile(p, "queries")
    SB = EB @ R.encode("bgem3", q, "query").T; SL = EL @ R.encode("large", q, "query").T
    t3 = lambda S: np.sort(S, 1)[:, -3:].mean(1)
    hits = np.minimum(R.keyword_hits(kw), 5)
    score = (1 - W_E5) * z(t3(SB)) + W_E5 * z(t3(SL)) + KW * 10 * hits
    theme = R.pool_themes(EB, score, THEME, POOL)
    if SEL == "facet":
        Sq = (1 - W_E5) * (SB - SB.mean()) / SB.std() + W_E5 * (SL - SL.mean()) / SL.std()
        chosen = R.facet_select(Sq, KW * 10 * hits, theme, 30, CAP)
    else:
        chosen, used = [], {}
        for i in np.argsort(-score):
            if used.get(theme[i], 0) < CAP:
                chosen.append(i); used[theme[i]] = used.get(theme[i], 0) + 1
            if len(chosen) == 60: break
    top[p] = [ids[i] for i in chosen]
    cand = list(np.argsort(-score)[:POOL]); cards = chosen[:10]; taken = set(cards); out = []
    for ci in cards:
        rel = [j for j in sorted(cand, key=lambda j: -(EB[ci] @ EB[j])) if j not in taken and EB[ci] @ EB[j] >= REL][:NREL]
        taken |= set(rel); txt = P.item(ids[ci])
        if rel and RELFMT == "lead":
            txt += "\n    Related this week:" + "".join(f"\n     - [{ids[j]}] {R.corpus.title[j]} — {R.corpus.lead[j][:RELN]}" for j in rel)
        elif rel: txt += "\n    Related this week: " + " ; ".join(f"[{ids[j]}] {R.corpus.title[j]}" for j in rel)
        out.append(txt)
    if int(args.get("tail", 0)):
        rest = [i for i in chosen[10:] if i not in taken][:int(args["tail"])]
        if len(rest) < int(args["tail"]):
            extra, used2 = [], {theme[i] for i in chosen}
            for i in np.argsort(-score):
                if len(rest) + len(extra) >= int(args["tail"]): break
                if i not in taken and i not in rest and theme[i] not in used2: extra.append(i); used2.add(theme[i])
            rest += extra
        out.append("OTHER RELEVANT HEADLINES THIS WEEK (one line each, lower priority):\n" + "\n".join(f"  [{ids[j]}] {R.corpus.title[j]} — {R.corpus.lead[j][:120]}" for j in rest))
    open(f"{d}/{p}_news.txt", "w").write("\n\n".join(out))
json.dump(top, open(f"{d}/top.json", "w")); json.dump(args, open(f"{d}/cfg.json", "w")); print("done", NAME)
