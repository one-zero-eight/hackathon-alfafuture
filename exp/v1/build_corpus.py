"""One line per story (cluster representative) with stable id, for gold labelling and retrieval."""
import pandas as pd, json
d = pd.read_csv("routed_news.csv", encoding="utf-8-sig")
full = pd.read_csv("/Users/fih/Downloads/Telegram Desktop/news_full.csv", encoding="utf-8-sig").fillna("")
full.columns = ["title","source","snippet","url","date","full_text"]
ft = dict(zip(full.url, full.full_text))
d["full_text"] = d.url.map(ft).fillna("")
# representative: longest full text in the story
d["ftlen"] = d.full_text.str.len()
rep = d.sort_values("ftlen", ascending=False).drop_duplicates("story").sort_values("date")
grp = d.groupby("story").agg(n=("url","size"), sources=("source", lambda s: ", ".join(sorted(set(s)))))
rep = rep.join(grp, on="story").reset_index(drop=True)
rep["date"] = rep.date.fillna("").astype(str)
rep["id"] = ["A%04d" % i for i in range(len(rep))]
def lead(r, n):
    t = r.full_text or r.snippet
    t = t.replace(r.title, "", 1).strip() if t.startswith(r.title) else t
    return " ".join(t.split())[:n]
rep["lead"] = [lead(r, 600) for r in rep.itertuples()]
rep[["id","story","date","source","n","sources","title","lead","url","full_text"]].to_parquet("exp/corpus.parquet")
with open("exp/corpus.txt","w") as f:
    for r in rep.itertuples():
        f.write(f"[{r.id}] {str(r.date)[:10]} | {r.source} (x{r.n}) | {r.title}\n    {r.lead}\n")
print(len(rep), "stories")
