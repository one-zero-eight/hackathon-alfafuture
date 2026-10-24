"""Which embedder finds the Alfa thesis for a headline.

Gold is a handful of U01 headlines whose right and wrong theses were read by hand.
A hit is a thesis about the same event. A miss is a thesis about another year, another market, or another industry.
The lexical stem search is the baseline. Quote checking stays verbatim and is not part of this comparison.

    .venv/bin/python -m reasoning.compare_embed
"""
import json
from reasoning.chain import OUT
from reasoning.data import corpus
from reasoning.search import Index

# accept: id fragments that count as the same event. avoid: fragments that are a wrong event.
GOLD = [
    ("A1081", ["Policy_Rate_11Sep:p1:t1", "Policy_Rate_11Sep:p1:t4", "FI_Strategy_3Q26_22072026:p9:t3",
               "FI_Strategy_3Q26_22072026:p5:t2", "FI_Strategy_3Q26_22072026:p12:t3"], ["Gold_digest"]),
    ("A0649", ["Бонд_Бриф_14092026:p4:t1", "FI_Strategy_3Q26_22072026:p13:t1"], ["Gold_digest", "p13:t4"]),
    ("A0311", ["ALFA-macro_stat1H26:p1:t4", "Бонд_Бриф_14092026:p4:t2"], ["p2:t3"]),
    ("A0618", ["ALFA-macro_stat1H26:p1:t4", "Бонд_Бриф_14092026:p4:t2"], ["p2:t3"]),
    ("A1060", ["Policy_Rate_11Sep:p3:t1", "ALFA-macro_stat1H26:p4:t3"], ["Gold_digest"]),
    ("A0126", [], ["Policy_Rate", "Gold_digest", "нефт", "ставк"]),
    ("A1830", [], ["Policy_Rate", "Gold_digest", "нефт", "ставк"]),
]
MODELS = {
    "bge-m3": ("BAAI/bge-m3", None),
    "user-bge-m3": ("deepvk/USER-bge-m3", None),
    "e5-large-instruct": ("intfloat/multilingual-e5-large-instruct",
                          "Instruct: Given a Russian business news headline, retrieve the Alfa-Bank research thesis about the same event\nQuery: "),
}


def theses() -> list[dict]:
    rows = []
    for line in (OUT / "theses.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def titles() -> dict[str, str]:
    events, _ = corpus("U01")
    return {e["id"]: e["title"].split("//")[0].strip() for e in events[:10]}


def ok(hit: str, accept: list[str], avoid: list[str]) -> bool:
    if any(bad in hit for bad in avoid):
        return False
    if not accept:
        return True
    return any(good in hit for good in accept)


def lexical(docs: dict[str, str], queries: dict[str, str]) -> dict[str, list[str]]:
    index = Index(docs)
    return {qid: index.search(text, k=3, prefix="alfa:") for qid, text in queries.items()}


def dense(name: str, docs: dict[str, str], queries: dict[str, str]) -> dict[str, list[str]]:
    import torch
    from sentence_transformers import SentenceTransformer
    hf, prefix = MODELS[name]
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    model = SentenceTransformer(hf, device=device)
    keys = list(docs)
    print(f"{name} кодирует {len(keys)} тезисов", flush=True)
    passage = model.encode(list(docs.values()), normalize_embeddings=True, batch_size=32, show_progress_bar=True)
    qtext = [(prefix or "") + queries[k] for k in queries]
    q = model.encode(qtext, normalize_embeddings=True, batch_size=16, show_progress_bar=False)
    out = {}
    for i, qid in enumerate(queries):
        scores = passage @ q[i]
        order = scores.argsort()[::-1][:3]
        out[qid] = [keys[j] for j in order]
    return out


def report(name: str, ranked: dict[str, list[str]], claims: dict[str, str]) -> tuple[int, int]:
    hit = bad = 0
    print(f"\n{name}")
    for qid, accept, avoid in GOLD:
        top = ranked.get(qid) or []
        if not top:
            print(f"  {qid} NONE")
            bad += 1
            continue
        good = ok(top[0], accept, avoid)
        hit += good
        bad += not good
        mark = "ok" if good else "MISS"
        print(f"  {qid} {mark} {claims.get(top[0], '')[:70]}")
    print(f"  {hit}/{len(GOLD)}")
    return hit, len(GOLD)


def main() -> None:
    rows = theses()
    claims = {t["id"]: t["claim"] for t in rows}
    docs = {t["id"]: t["claim"] + ". " + t["quote"] for t in rows}
    want = {qid for qid, _, _ in GOLD}
    queries = {i: t for i, t in titles().items() if i in want}
    scores = {"stems": report("stems", lexical(docs, queries), claims)}
    for name in MODELS:
        try:
            print(f"\n{name} загрузка", flush=True)
            scores[name] = report(name, dense(name, docs, queries), claims)
        except Exception as e:
            print(f"\n{name} FAILED {e}")
    print("\nsummary")
    for name, (hit, n) in scores.items():
        print(f"  {name} {hit}/{n}")


if __name__ == "__main__":
    main()
