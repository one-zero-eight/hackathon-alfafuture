"""Route news articles to company role groups: keyword filter + embedding similarity.

Usage: .venv/bin/python route_news.py <news_full.csv> [top_n]
Writes routed_news.csv (every article x group score) and digest.md (top N per group).
"""
import re
import sys
from functools import lru_cache

import numpy as np
import pandas as pd
import pymorphy3
from sentence_transformers import SentenceTransformer

MODEL = "intfloat/multilingual-e5-small"
KW_WEIGHT = 0.02      # bonus per distinct keyword hit
KW_CAP = 5            # max keyword hits counted
MIN_SCORE = 0.83      # combined score needed to land in a digest
GENERIC_PENALTY = 2.0 # how hard to penalize articles that look similar to every group
MULTI_MARGIN = 0.03   # an article also goes to groups within this margin of its best group
DUP_SIM = 0.93        # embedding similarity at which two articles are the same story
SNIPPET_CHARS = 300   # lead length used for keywords and embeddings
DUP_HOURS = 72        # ...if published within this window

# URL fragments of sections no business group cares about
SKIP_URL = re.compile(r"/(sport|sports|culture|kultura|lifestyle|style|afisha|showbiz|cinema|auto-moto)/", re.I)

# Each group: a profile (what they care about, used for embeddings) + seed keywords (lemmatized at load).
GROUPS = {
    "Executive": {
        "profile": [
            "геополитика, международные отношения и переговоры лидеров стран",
            "макроэкономика: рост ВВП, рецессия, экономический кризис",
            "крупные сделки, слияния и поглощения, стратегия компаний",
        ],
        "keywords": ["ВВП", "рецессия", "кризис", "саммит", "переговоры", "слияние", "поглощение",
                     "стратегия", "экономика", "геополитика"],
    },
    "Finance & Risk": {
        "profile": [
            "ключевая ставка центрального банка и денежно-кредитная политика",
            "инфляция, курс рубля и валютные рынки",
            "фондовый рынок, облигации, акции и инвесторы",
            "санкции против банков и финансовые риски",
        ],
        "keywords": ["ставка", "ЦБ", "Центробанк", "инфляция", "курс", "рубль", "доллар", "юань",
                     "биржа", "акция", "облигация", "банк", "кредит", "санкция", "бюджет", "налог"],
    },
    "Supply Chain & Operations": {
        "profile": [
            "поставки, логистика и перевозки грузов",
            "цены на нефть, газ, металлы и сырьё",
            "пошлины, импорт и экспорт, торговые ограничения",
            "перебои в работе портов, железных дорог и производства",
        ],
        "keywords": ["поставка", "логистика", "груз", "порт", "импорт", "экспорт", "пошлина",
                     "нефть", "газ", "сырьё", "металл", "дефицит", "производство", "завод", "ОПЕК"],
    },
    "Legal & Compliance": {
        "profile": [
            "новые законы и законопроекты, принятые Госдумой",
            "регулирование бизнеса, требования регуляторов и штрафы",
            "судебные решения и иски против компаний",
        ],
        "keywords": ["закон", "законопроект", "Госдума", "регулирование", "штраф", "суд", "иск",
                     "запрет", "лицензия", "постановление", "Минюст", "прокуратура"],
    },
    "Commercial (Marketing & Sales)": {
        "profile": [
            "потребительский спрос, розничные продажи и цены для покупателей",
            "рынок и конкуренты, запуск новых продуктов",
            "маркетинг, реклама и поведение потребителей",
        ],
        "keywords": ["спрос", "продажа", "розница", "потребитель", "покупатель", "маркетплейс",
                     "реклама", "бренд", "рынок", "конкурент", "цена", "подорожание"],
    },
    "Comms, People & Security": {
        "profile": [
            "рынок труда, зарплаты, увольнения и занятость",
            "забастовки, протесты и беспорядки",
            "чрезвычайные ситуации, теракты, стихийные бедствия и безопасность людей",
        ],
        "keywords": ["зарплата", "увольнение", "занятость", "безработица", "сотрудник", "забастовка",
                     "протест", "ЧС", "теракт", "эвакуация", "землетрясение", "пожар", "наводнение"],
    },
    "Tech & Product": {
        "profile": [
            "искусственный интеллект и новые технологии",
            "кибератаки, утечки данных и информационная безопасность",
            "полупроводники, чипы и технологические компании",
        ],
        "keywords": ["ИИ", "нейросеть", "технология", "кибератака", "хакер", "утечка",
                     "чип", "полупроводник", "смартфон", "приложение", "IT", "стартап"],
    },
}

morph = pymorphy3.MorphAnalyzer()
WORD = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+")


@lru_cache(maxsize=200_000)
def lemma(word: str) -> str:
    if word.isupper() and len(word) <= 4:  # abbreviations: ИИ, ЦБ, ЧС, IT
        return word.lower()
    return morph.parse(word.lower())[0].normal_form


def lemmas(text: str) -> set[str]:
    return {lemma(w) for w in WORD.findall(text)}


def cluster_stories(emb: np.ndarray, dates: pd.Series) -> np.ndarray:
    """Greedy clustering: walk articles by time, join the first earlier cluster whose seed is close enough."""
    order = np.argsort(dates.values)
    cluster = np.full(len(emb), -1)
    seeds: list[int] = []
    for i in order:
        for s in reversed(seeds):
            if (dates.iloc[i] - dates.iloc[s]).total_seconds() > DUP_HOURS * 3600:
                break  # older seeds are out of the window
            if emb[i] @ emb[s] >= DUP_SIM:
                cluster[i] = cluster[s]
                break
        if cluster[i] == -1:
            cluster[i] = len(seeds)
            seeds.append(i)
    return cluster


def main(path: str, top_n: int) -> None:
    df = pd.read_csv(path, encoding="utf-8-sig").fillna("")
    df.columns = ["title", "source", "snippet", "url", "date", "full_text"]
    n0 = len(df)
    # Some sources put the whole article into the snippet; keep only the lead so every article is judged on equal length
    df["snippet"] = df["snippet"].str[:SNIPPET_CHARS]

    df = df.drop_duplicates(subset="full_text").drop_duplicates(subset="title")
    df = df[~df["url"].str.contains(SKIP_URL.pattern, flags=re.I, regex=True)].reset_index(drop=True)
    print(f"{n0} articles -> {len(df)} after dedup and section filter")

    # Keywords: title + snippet only, so long reads don't collect hits just by being long
    body = df["title"] + ". " + df["snippet"]
    doc_lemmas = [lemmas(t) for t in body]
    group_kw = {g: {lemma(k) for k in spec["keywords"]} for g, spec in GROUPS.items()}

    # Embeddings: article = title + snippet; group = max similarity over its profile lines
    model = SentenceTransformer(MODEL)
    docs = ("passage: " + df["title"] + ". " + df["snippet"]).tolist()
    doc_emb = model.encode(docs, batch_size=64, normalize_embeddings=True, show_progress_bar=True)

    sims = {}
    for g, spec in GROUPS.items():
        prof = model.encode(["query: " + p for p in spec["profile"]], normalize_embeddings=True)
        sims[g] = (doc_emb @ prof.T).max(axis=1)

    # Generic articles (essays, reviews) sit close to every profile; penalize how far their
    # average similarity across all groups is above the typical article's average.
    mean_sim = np.mean(list(sims.values()), axis=0)
    generic = np.clip(mean_sim - np.median(mean_sim), 0, None)
    df["generic_penalty"] = (GENERIC_PENALTY * generic).round(3)

    for g in GROUPS:
        hits = [sorted(dl & group_kw[g]) for dl in doc_lemmas]
        kw = np.array([min(len(h), KW_CAP) for h in hits])
        df[f"{g}|sim"] = sims[g].round(3)
        df[f"{g}|kw"] = [", ".join(h) for h in hits]
        df[f"{g}|score"] = (sims[g] + KW_WEIGHT * kw - df["generic_penalty"]).round(3)

    score_cols = [f"{g}|score" for g in GROUPS]
    df["best_group"] = df[score_cols].idxmax(axis=1).str.split("|").str[0]
    df["best_score"] = df[score_cols].max(axis=1)
    # Route to best group plus near-ties only, not to every group above threshold
    for g in GROUPS:
        df[f"{g}|routed"] = (df[f"{g}|score"] >= MIN_SCORE) & (df[f"{g}|score"] >= df["best_score"] - MULTI_MARGIN)

    # Duplicate stories: one cluster per event; the best-scoring article represents it
    dates = pd.to_datetime(df["date"], utc=True, errors="coerce").fillna(pd.Timestamp("1970-01-01", tz="UTC"))
    df["story"] = cluster_stories(doc_emb, dates)
    df["story_size"] = df.groupby("story")["story"].transform("size")
    print(f"{df['story'].nunique()} distinct stories, {(df['story_size'] > 1).sum()} articles in multi-source stories")
    df.to_csv("routed_news.csv", index=False, encoding="utf-8-sig")

    lines = [f"# News digest by role group\n\n{len(df)} articles, {df['story'].nunique()} distinct stories. "
             f"Score = embedding similarity + {KW_WEIGHT} x keyword hits − generic penalty; "
             f"shown if >= {MIN_SCORE} and within {MULTI_MARGIN} of the article's best group.\n"]
    for g in GROUPS:
        sel = df[df[f"{g}|routed"]].sort_values(f"{g}|score", ascending=False)
        stories = sel.drop_duplicates("story")
        lines.append(f"\n## {g} — {len(stories)} stories ({len(sel)} articles)\n")
        for _, r in stories.head(top_n).iterrows():
            kw = f" · kw: {r[f'{g}|kw']}" if r[f"{g}|kw"] else ""
            others = sel[(sel["story"] == r["story"]) & (sel.index != r.name)]
            more = f" · **+{len(others)} more:** {', '.join(others['source'].unique())}" if len(others) else ""
            lines.append(f"- **{r[f'{g}|score']:.3f}** [{r['title']}]({r['url']}) — {r['source']}{kw}{more}")
    irrelevant = (df["best_score"] < MIN_SCORE).sum()
    lines.append(f"\n---\n{irrelevant} articles matched no group (noise).\n")
    open("digest.md", "w", encoding="utf-8").write("\n".join(lines))
    print("\n".join(lines))


if __name__ == "__main__":
    main(sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 10)
