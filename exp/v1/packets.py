"""Write news packets. gold: all items flagged for persona. run: top-10 of a variant."""
import json, glob, os, sys
import pandas as pd
ROOT = os.path.dirname(os.path.abspath(__file__))
c = pd.read_parquet(os.path.join(ROOT, "corpus.parquet")).set_index("id")
def item(i, n=600, why=None):
    r = c.loc[i]
    w = f"\n    (screening note: {why})" if why else ""
    return f"[{i}] {r.date[:10]} | {r.source} (covered by {r.n} outlets: {r.sources}) | {r.title}\n    {' '.join(str(r.full_text or r.lead).split())[:n]}{w}"
if __name__ != "__main__":
    pass
elif sys.argv[1] == "gold":
    gold = {}
    for f in sorted(glob.glob(os.path.join(ROOT, "gold", "map_*.json"))):
        for p, items in json.load(open(f)).items():
            for it in items: gold.setdefault(p, []).append(it)
    for p, items in gold.items():
        items.sort(key=lambda x: -x["rel"])
        open(os.path.join(ROOT, "gold", f"{p}_input.txt"), "w").write(
            "\n".join(f"(rel {it['rel']}) " + item(it["id"], 900, it["why"]) for it in items))
        print(p, len(items))
else:
    v, n = sys.argv[2], int(sys.argv[3]) if len(sys.argv) > 3 else 600
    top = json.load(open(os.path.join(ROOT, "runs", v, "top.json")))
    for p, ids in top.items():
        open(os.path.join(ROOT, "runs", v, f"{p}_news.txt"), "w").write("\n".join(item(i, n) for i in ids[:10]))
    print(v, "packets written")


def theme_cards(v, related_sim=0.84, extra=3):
    """10 cards; each = lead story + up to `extra` related headlines from the persona's top-50 that aren't cards themselves."""
    import numpy as np
    sys.path.insert(0, ROOT)
    import retrieve as R
    E = R.doc_emb(json.load(open(os.path.join(ROOT, "runs", v, "cfg.json")))["model"]) if os.path.exists(os.path.join(ROOT, "runs", v, "cfg.json")) else R.doc_emb("small")
    ids = list(R.corpus.id)
    top = json.load(open(os.path.join(ROOT, "runs", v, "top.json")))
    for p, lst in top.items():
        cards, pool = lst[:10], lst[10:50]
        out = []
        for cid in cards:
            ci = ids.index(cid)
            rel = sorted(((float(E[ci] @ E[ids.index(o)]), o) for o in pool), reverse=True)
            rel = [o for s, o in rel if s >= related_sim][:extra]
            pool = [o for o in pool if o not in rel]
            txt = item(cid)
            if rel:
                txt += "\n    Related this week: " + " ; ".join(f"[{o}] {c.loc[o].title}" for o in rel)
            out.append(txt)
        open(os.path.join(ROOT, "runs", v, f"{p}_news.txt"), "w").write("\n".join(out))
    print(v, "theme cards written")
