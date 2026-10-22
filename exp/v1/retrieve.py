"""Light algorithmic retrieval: rank stories for each persona, write top-K ids per variant.

Usage: .venv/bin/python exp/retrieve.py <variant> [<variant> ...]   (see VARIANTS)
Writes exp/runs/<variant>/top.json = {"P1": ["A0123", ...30 ids], ...}
"""
import json
import os
import re
import sys
from functools import lru_cache

import numpy as np
import pandas as pd
import pymorphy3

ROOT = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(ROOT, "cache")
os.makedirs(CACHE, exist_ok=True)

corpus = pd.read_parquet(os.path.join(ROOT, "corpus.parquet"))
personas = json.load(open(os.path.join(ROOT, "personas.json")))
DOC_CHARS = 300

# V0 baseline: persona -> existing route_news group
sys.path.insert(0, os.path.dirname(ROOT))
from route_news import GROUPS  # noqa: E402
GROUP_OF = {"P1": "Finance & Risk", "P2": "Supply Chain & Operations", "P3": "Legal & Compliance",
            "P4": "Tech & Product", "P5": "Supply Chain & Operations", "P6": "Comms, People & Security"}

VARIANTS = {
    # name: model, profile source, keyword weight, importance weight, MMR lambda (1 = none), rerank, query aggregation
    "v0_group":       dict(model="small", profile="group",   kw=0.02, imp=0.0,  mmr=1.0, rerank=False, agg="max"),
    "v1_persona":     dict(model="small", profile="persona", kw=0.0,  imp=0.0,  mmr=1.0, rerank=False, agg="max"),
    "v2_queries":     dict(model="small", profile="queries", kw=0.01, imp=0.0,  mmr=1.0, rerank=False, agg="max"),
    "v3_q_imp_mmr":   dict(model="small", profile="queries", kw=0.01, imp=0.01, mmr=0.7, rerank=False, agg="max"),
    "v4_large":       dict(model="large", profile="queries", kw=0.01, imp=0.01, mmr=0.7, rerank=False, agg="max"),
    "v5_bgem3":       dict(model="bgem3", profile="queries", kw=0.01, imp=0.01, mmr=0.7, rerank=False, agg="max"),
    "v6_large_rr":    dict(model="large", profile="queries", kw=0.01, imp=0.01, mmr=0.7, rerank=True,  agg="max"),
    "v7_bgem3_rr":    dict(model="bgem3", profile="queries", kw=0.01, imp=0.01, mmr=0.7, rerank=True,  agg="max"),
    "v8_large_nommr": dict(model="large", profile="queries", kw=0.01, imp=0.0,  mmr=1.0, rerank=False, agg="max"),
    "v9_bgem3_nommr": dict(model="bgem3", profile="queries", kw=0.01, imp=0.0,  mmr=1.0, rerank=False, agg="max"),
    "v10_small_rr":   dict(model="small", profile="queries", kw=0.01, imp=0.0,  mmr=1.0, rerank=True,  agg="max"),
    "v11_small_top3": dict(model="small", profile="queries", kw=0.01, imp=0.0,  mmr=1.0, rerank=False, agg="top3"),
    "v12_small_kw0":  dict(model="small", profile="queries", kw=0.0,  imp=0.0,  mmr=1.0, rerank=False, agg="max"),
    "v13_small_kw3":  dict(model="small", profile="queries", kw=0.03, imp=0.0,  mmr=1.0, rerank=False, agg="max"),
    "f1_facet":       dict(model="small", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="max", select="facet", theme_sim=0.88),
    "f2_facet_t90":   dict(model="small", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="max", select="facet", theme_sim=0.90),
    "f3_facet_t86":   dict(model="small", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="max", select="facet", theme_sim=0.86),
    "f4_facet_imp":   dict(model="small", profile="queries", kw=0.02, imp=0.01, mmr=1.0, rerank=False, agg="max", select="facet", theme_sim=0.88),
    "r1_small_rr150": dict(model="small", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=True, agg="top3", pool=150),
    "r2_large_top3":  dict(model="large", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3"),
    "r3_bgem3_top3":  dict(model="bgem3", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3"),
    "r4_large_rr150": dict(model="large", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=True, agg="top3", pool=150),
    "f5_large_facet88": dict(model="large", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3", select="facet", theme_sim=0.88),
    "f6_large_facet86": dict(model="large", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3", select="facet", theme_sim=0.86),
    "f7_small_facet87": dict(model="small", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3", select="facet", theme_sim=0.87),
    "f8_bgem3_facet72": dict(model="bgem3", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3", select="facet", theme_sim=0.72),
    "f9_bgem3_facet68": dict(model="bgem3", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3", select="facet", theme_sim=0.68),
    "f10_bgem3_facet76": dict(model="bgem3", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="top3", select="facet", theme_sim=0.76),
    "r5_bgem3_kw4":   dict(model="bgem3", profile="queries", kw=0.04, imp=0.0, mmr=1.0, rerank=False, agg="top3"),
    "r6_bgem3_max":   dict(model="bgem3", profile="queries", kw=0.02, imp=0.0, mmr=1.0, rerank=False, agg="max"),
}
MODELS = {"small": "intfloat/multilingual-e5-small", "large": "intfloat/multilingual-e5-large", "bgem3": "BAAI/bge-m3"}

morph = pymorphy3.MorphAnalyzer()
WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")


@lru_cache(maxsize=200_000)
def lemma(w):
    return w.lower() if (w.isupper() and len(w) <= 4) else morph.parse(w.lower())[0].normal_form


def lemma_seq(text):
    return [lemma(w) for w in WORD.findall(text)]


def doc_texts():
    return (corpus.title + ". " + corpus.lead.str[:DOC_CHARS]).tolist()


_models = {}


def model(name):
    if name not in _models:
        from sentence_transformers import SentenceTransformer
        _models[name] = SentenceTransformer(MODELS[name])
    return _models[name]


def encode(name, texts, kind):
    prefix = {"passage": "passage: ", "query": "query: "}[kind] if name != "bgem3" else ""
    return model(name).encode([prefix + t for t in texts], batch_size=32, normalize_embeddings=True)


def doc_emb(name):
    path = os.path.join(CACHE, f"docs_{name}_{DOC_CHARS}.npy")
    if not os.path.exists(path):
        np.save(path, encode(name, doc_texts(), "passage"))
    return np.load(path)


def profile(pid, kind):
    if kind == "group":
        g = GROUPS[GROUP_OF[pid]]
        return g["profile"], g["keywords"], []
    if kind == "persona":
        p = personas[pid]
        return [f"{p['role']} в компании: {p['company']} Решения: {p['authority']}"], [], []
    q = json.load(open(os.path.join(ROOT, "queries.json")))[pid]
    return q["queries"], q["keywords"], q.get("negative", [])


def keyword_hits(keywords):
    """Count distinct keyword (or multi-word phrase) matches in title + lead per doc."""
    kws = [" ".join(lemma_seq(k)) for k in keywords]
    docs = [" " + " ".join(lemma_seq(t)) + " " for t in doc_texts()]
    return np.array([sum((" " + k + " ") in d for k in kws if k) for d in docs])


def mmr(scores, emb, k, lam):
    if lam >= 1.0:
        return list(np.argsort(-scores)[:k])
    cand = list(np.argsort(-scores)[:200])
    chosen = []
    while cand and len(chosen) < k:
        if chosen:
            red = (emb[cand] @ emb[chosen].T).max(axis=1)
        else:
            red = np.zeros(len(cand))
        val = lam * scores[cand] - (1 - lam) * red
        j = int(np.argmax(val))
        chosen.append(cand.pop(j))
    return chosen


def themes(emb, sim):
    """Greedy theme grouping: a doc joins the first seed it is >= sim to (looser than story dedup)."""
    theme = np.full(len(emb), -1)
    seeds = []
    for i in range(len(emb)):
        if seeds:
            s = emb[seeds] @ emb[i]
            j = int(np.argmax(s))
            if s[j] >= sim:
                theme[i] = theme[seeds[j]]
                continue
        theme[i] = len(seeds)
        seeds.append(i)
    return theme


def pool_themes(emb, score, sim, pool=300):
    """Single-link themes among the persona's top-`pool` candidates (union-find); others get their own theme."""
    cand = np.argsort(-score)[:pool]
    parent = {int(i): int(i) for i in cand}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x
    S = emb[cand] @ emb[cand].T
    a, b = np.where(np.triu(S, 1) >= sim)
    for i, j in zip(a, b):
        parent[find(int(cand[i]))] = find(int(cand[j]))
    theme = np.arange(len(emb)) + len(emb)
    for i in cand:
        theme[i] = find(int(i))
    return theme


def facet_select(sims, bonus, theme, k, per_theme=1):
    """Round-robin over queries (facets): each facet in turn takes its best doc from an unused theme.
    Facets are ordered by the strength of their best match, so weak facets don't pull in noise first."""
    S = sims + bonus[:, None]
    order_per_q = np.argsort(-S, axis=0)
    q_order = list(np.argsort(-S.max(axis=0)))
    ptr = [0] * S.shape[1]
    chosen, used = [], {}
    floor = np.percentile(S.max(axis=1), 97)  # never take docs below the top-3% overall
    while len(chosen) < k:
        progressed = False
        for q in q_order:
            while ptr[q] < len(S):
                i = order_per_q[ptr[q], q]
                ptr[q] += 1
                if S[i, q] < floor:
                    ptr[q] = len(S)
                    break
                if i in chosen or used.get(theme[i], 0) >= per_theme:
                    continue
                chosen.append(i)
                used[theme[i]] = used.get(theme[i], 0) + 1
                progressed = True
                break
            if len(chosen) >= k:
                break
        if not progressed:
            break
    # top up with best remaining by max score if facets ran dry
    for i in np.argsort(-S.max(axis=1)):
        if len(chosen) >= k:
            break
        if i not in chosen:
            chosen.append(i)
    return chosen


_reranker = None


def rerank(pid, idx, k):
    global _reranker
    from sentence_transformers import CrossEncoder
    if _reranker is None:
        _reranker = CrossEncoder("BAAI/bge-reranker-v2-m3", max_length=512)
    p = personas[pid]
    q = (f"Новость, которая повлияет на решения руководителя ({p['role']}). Компания: {p['company']} "
         f"Полномочия: {p['authority']}")
    texts = doc_texts()
    s = _reranker.predict([(q, texts[i]) for i in idx], batch_size=16)
    order = np.argsort(-np.asarray(s))
    return [idx[i] for i in order[:k]]


def run(name):
    cfg = VARIANTS[name]
    E = doc_emb(cfg["model"])
    imp = np.log1p(corpus.n.values - 1)
    out = {}
    for pid in personas:
        queries, keywords, negative = profile(pid, cfg["profile"])
        Q = encode(cfg["model"], queries, "query")
        sims = E @ Q.T
        score = sims.max(axis=1) if cfg["agg"] == "max" else np.sort(sims, axis=1)[:, -3:].mean(axis=1)
        if negative:
            N = encode(cfg["model"], negative, "query")
            score = score - 0.5 * np.clip((E @ N.T).max(axis=1) - score, 0, None) * 0  # placeholder: off
        if keywords and cfg["kw"]:
            score = score + cfg["kw"] * np.minimum(keyword_hits(keywords), 5)
        score = score + cfg["imp"] * imp
        if cfg.get("select") == "facet":
            bonus = score - (sims.max(axis=1) if cfg["agg"] == "max" else np.sort(sims, axis=1)[:, -3:].mean(axis=1))
            th = pool_themes(E, sims.max(axis=1) + bonus, cfg.get("theme_sim", 0.88))
            top = facet_select(sims, bonus, th, 30)
            out[pid] = corpus.id.iloc[top].tolist()
            continue
        pool = mmr(score, E, cfg.get("pool", 50) if cfg["rerank"] else 30, cfg["mmr"])
        top = rerank(pid, pool, 30) if cfg["rerank"] else pool[:30]
        out[pid] = corpus.id.iloc[top].tolist()
    d = os.path.join(ROOT, "runs", name)
    os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, "top.json"), "w"), ensure_ascii=False, indent=1)
    print(name, "done", flush=True)


if __name__ == "__main__":
    for v in sys.argv[1:]:
        run(v)
