"""Benchmark of NewsSearch.refine against the running news_search service (see refine.md).
Run inside the news_search container (needs the corpus, the vector cache in NEWS_SEARCH_DATA and the HTTP service on :8000):
  docker compose --env-file .env -f docker/compose.yaml cp news_search/benchmarks/refine_bench.py news_search:/tmp/refine_bench.py
  docker compose --env-file .env -f docker/compose.yaml exec -T -e PYTHONPATH=/app news_search python /tmp/refine_bench.py > refine_runs.json
Prints one JSON with every run: inputs, results, automatic metrics, latency, cost."""
import json
import os
import sys
import time
import urllib.request

import numpy as np

from news_search import postgres_corpus
from news_search.dedup import dd_hybrid
from news_search.embed import VectorCache
from news_search.search import PARAPHRASE_SIM, REMOVED_SIM

URL = os.environ.get("NEWS_SEARCH_SELF", "http://localhost:8000")
U76 = ("компания, ОКВЭД 52.29 «Деятельность вспомогательная прочая, связанная с перевозками», г. Новосибирск, Новосибирская область, "
       "сотрудников: Менее 15, возраст 16-25 лет, основные поставщики: Торговля оптовая химическими продуктами; Торговля оптовая "
       "лесоматериалами, строительными материалами и санитарно-техническим оборудованием; Торговля оптовая автомобильными деталями")
# company, line, region, topic, perspective region, claim, anonymised (approved by the user 2026-10-25)
PROFILES = [
    ("Делимобиль", "Глава найма", "Москва", "электросамокаты и микромобильность", "Санкт-Петербург",
     "дефицит водителей-курьеров поднимет зарплаты в каршеринге", False),
    ("Группа Астра", "Финансовый директор", "Москва", "экспорт ПО в страны СНГ", "Новосибирская область",
     "субсидии на импортозамещение ПО сократят в 2027 году", False),
    ("Селектел", "Директор по развитию", "Санкт-Петербург", "дата-центры для ИИ и GPU-облака", "Республика Татарстан",
     "тарифы на электроэнергию для ЦОД вырастут сильнее инфляции", False),
    ("Инарктика", "Финансовый директор", "Мурманская область", "экспорт рыбы в Китай", "Республика Карелия",
     "квоты на аквакультуру лосося будут урезаны", False),
    ("Магазин Мать и Дитя", "Директор по закупкам", "Москва", "импорт медицинского оборудования", "Свердловская область",
     "рождаемость продолжит снижаться в 2027 году", False),
    (U76, "Финансовый директор", "Новосибирская область", "контейнерные перевозки из Китая через Казахстан", "Свердловская область",
     "индексация тарифов РЖД поднимет ставки на перевозку контейнеров", True),
]


def post(path, body):
    t0 = time.time()
    req = urllib.request.Request(URL + path, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=3600) as r:
        return json.load(r), round(time.time() - t0, 2)


def main():
    items = postgres_corpus(os.environ["DATABASE_URL"])(365)
    by_aid = {it["aid"]: k for k, it in enumerate(items)}
    # every vector is already cached by the service; no second encoder in memory next to it
    X = VectorCache(os.path.join(os.environ.get("NEWS_SEARCH_DATA", "/data"), "vectors_bgem3.npz")).vectors(items, None)

    def dups_of(result_aids, seen_aids):
        """Results that dedup puts into one cluster with a seen (shown or removed) news item."""
        rows = [items[by_aid[a]] for a in result_aids] + [items[by_aid[a]] for a in seen_aids if a in by_aid]
        labels = dd_hybrid(rows)
        seen = set(labels[len(result_aids):])
        return sum(label in seen for label in labels[:len(result_aids)])

    def near(result_aids, removed_aids):
        if not result_aids or not removed_aids:
            return 0
        S = X[[by_aid[a] for a in result_aids]] @ X[[by_aid[a] for a in removed_aids]].T
        return int((S.max(1) >= REMOVED_SIM).sum())

    def pairs_in(result_aids):
        """Pairs of results that are paraphrases of each other (cosine >= PARAPHRASE_SIM)."""
        V = X[[by_aid[a] for a in result_aids]]
        return int(np.triu(V @ V.T >= PARAPHRASE_SIM, 1).sum()) if result_aids else 0

    runs = []
    for company, line, region, topic, other_region, claim, anon in PROFILES:
        base = dict(company=company, line=line, region=region, anonymised=anon)
        page, t = post("/search", {**base, "method": "dense_xquad"})
        shown = [it["aid"] for it in page["top"]]
        name = company if not anon else "U_76"
        runs.append({"profile": name, "kind": "search", "latency": t, "cost": page["cost"], "top": [it["title"] for it in page["top"]]})
        # link: the last of 30 topic results (a relevant news item the page does not show), title + summary as the pasted text
        link_aid = post("/refine", {**base, "kind": "topic", "text": topic, "exclude_aids": shown, "limit": 30})[0]["top"][-1]["aid"]
        link_item = items[by_aid[link_aid]]
        cases = [("topic", topic, base, shown, []),
                 ("perspective", topic, {**base, "region": other_region, "page_region": region}, shown, []),
                 ("claim", claim, base, shown, []),
                 ("link", f"{link_item['title']}. {link_item['summary']}", base, shown + [link_aid], [])]
        first_topic = None
        for label, text, prof, exclude, removed in cases:
            res, t = post("/refine", {**prof, "kind": label, "text": text, "exclude_aids": exclude, "removed_aids": removed, "limit": 10})
            got = [it["aid"] for it in res["top"]]
            first_topic = first_topic or (got if label == "topic" else None)
            runs.append({"profile": name, "kind": label, "text": text[:200], "latency": t, "cost": res["cost"], "n": len(got),
                         "dups_of_shown": dups_of(got, shown), "in_shown": len(set(got) & set(shown)), "paraphrase_pairs": pairs_in(got),
                         "regional": [it["title"] for it in res["top"] if it.get("regional")],
                         "stats": res["stats"],
                         "top": [it["title"] for it in res["top"]]})
        # removed: the topic rerun with its first 3 results removed and the rest shown
        removed, rest = first_topic[:3], first_topic[3:]
        before = near(rest, removed)  # how many of the first run's remaining results are close to the removed ones
        res, t = post("/refine", {**base, "kind": "topic", "text": topic, "exclude_aids": shown + rest, "removed_aids": removed, "limit": 10})
        got = [it["aid"] for it in res["top"]]
        runs.append({"profile": name, "kind": "removed", "latency": t, "cost": res["cost"], "n": len(got),
                     "dups_of_shown": dups_of(got, shown + rest), "dups_of_removed": dups_of(got, removed),
                     "near_removed_before": f"{before}/{len(rest)}", "near_removed_after": f"{near(got, removed)}/{len(got)}",
                     "stats": res["stats"], "top": [it["title"] for it in res["top"]]})
        print(f"{name}: done", file=sys.stderr)
    json.dump(runs, sys.stdout, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
