"""Offline checks of news_search with a fake corpus, encoder and agents; run: pytest news_search
The corpus test talks to PostgreSQL and is skipped unless TEST_DATABASE_URL is set."""
import datetime
import os
import random
from email.utils import format_datetime

import numpy as np
import pytest

from news_search import METHODS, NewsSearch, TooFewNews, postgres_corpus, scoring
from news_search.dedup import dd_hybrid
from news_search.embed import VectorCache
from news_search.search import PARAPHRASE_SIM, REMOVED_FACTOR, REMOVED_SIM
from news_search.text import match_items

NOW = datetime.datetime(2026, 10, 24, tzinfo=datetime.timezone.utc)
VOCAB = [f"слово{n}" for n in range(300)]


def make_corpus(n=120, own=0):
    rng = random.Random(1)
    items = []
    for k in range(n):
        title = " ".join(rng.sample(VOCAB, 6))
        if k < own:
            title += " Ромашка"
        date = format_datetime(NOW - datetime.timedelta(days=rng.randint(0, 20)))
        items.append({"aid": k + 1, "title": title, "link": f"https://example.ru/{k}", "date": date, "outlet": f"СМИ{k % 4}", "summary": ""})
    return items


def hash_encoder(name, max_len):
    """Deterministic bag-of-words vectors: similar texts get similar vectors."""
    def encode(texts):
        out = np.zeros((len(texts), 64), np.float32)
        for r, t in enumerate(texts):
            for w in t.lower().replace("instruct:", "").split():
                out[r, hash(w) % 64] += 1
        return out / (np.linalg.norm(out, axis=1, keepdims=True) + 1e-9)
    return encode


class FakeAgents:
    def __init__(self):
        self.cost, self.calls = 0.0, []

    def run(self, name, data):
        self.calls.append(name)
        self.cost += 0.1
        if name == "queries":
            blocks = {"company_self": ["Ромашка суд"]}
            for b in range(4):
                blocks[f"block{b}"] = [VOCAB[b * 10 + k] + " " + VOCAB[b * 10 + k + 1] for k in range(8)]
            return blocks
        if name == "needs":
            return {"needs": [f"Как {VOCAB[k]} {VOCAB[k + 1]} повлияет на бизнес?" for k in range(0, 40, 4)]}
        if name == "hyde":
            return {"headlines": [f"{VOCAB[k]} {VOCAB[k + 2]} {VOCAB[k + 3]}" for k in range(0, 80, 4)]}
        if name == "pick":
            return {"top": [c["id"] for c in data["candidates"]][: data["top"]]}
        raise AssertionError(name)


def searcher(tmp_path, corpus):
    agents = FakeAgents()
    return NewsSearch(lambda days: corpus, agents, str(tmp_path), hash_encoder, now=lambda: NOW), agents


@pytest.mark.parametrize("method", METHODS)
def test_every_method_returns_unique_news_and_caches_the_result(tmp_path, method):
    s, agents = searcher(tmp_path, make_corpus())
    res = s.search("Ромашка", "Закупки", "Тверь", method)
    assert 0 < len(res["top"]) <= 30 and res["method"] == method
    assert len({it["link"] for it in res["top"]}) == len(res["top"])
    assert all("vec" not in it and "aspects" not in it and it["aid"] for it in res["top"])
    calls = len(agents.calls)
    assert s.search("Ромашка", "Закупки", "Тверь", method) == res and len(agents.calls) == calls


def test_dense_xquad_reports_blocks_and_related_pairs(tmp_path):
    res = searcher(tmp_path, make_corpus())[0].search("Ромашка", "Закупки", method="dense_xquad")
    assert res["blocks"] == ["block0", "block1", "block2", "block3"] and len(res["top"]) == 30
    assert all(isinstance(i, int) and isinstance(j, int) for i, j in res["pairs"])


def test_news_about_the_company_itself_are_dropped_unless_anonymised(tmp_path):
    corpus = make_corpus(own=40)
    own = {it["link"] for it in corpus if "Ромашка" in it["title"]}
    named = searcher(tmp_path / "a", corpus)[0].search("Ромашка", "Закупки", method="dense_xquad")
    assert not own & {it["link"] for it in named["top"]}
    anon = searcher(tmp_path / "b", corpus)[0].search("компания, ОКВЭД 49", "Закупки", method="dense_xquad", anonymised=True)
    assert len(anon["top"]) == 30


def test_too_few_news_and_unknown_method(tmp_path):
    s, _ = searcher(tmp_path, make_corpus(n=10))
    with pytest.raises(TooFewNews):
        s.search("Ромашка", "Закупки", method="lexical")
    with pytest.raises(ValueError):
        s.search("Ромашка", "Закупки", method="graph")


def test_refine_skips_shown_removed_and_their_duplicates(tmp_path):
    corpus = make_corpus()
    corpus.append({**corpus[0], "aid": 999, "link": "https://copy.ru/0"})  # a copy of a shown news item from another outlet
    s, agents = searcher(tmp_path, corpus)
    topic = corpus[0]["title"]
    first = s.refine("Ромашка", "Закупки", "topic", topic, limit=5)
    assert first["top"][0]["aid"] in (1, 999) and len(first["top"]) == 5 and first["kind"] == "topic"
    shown, removed = [it["aid"] for it in first["top"][:3]], [first["top"][3]["aid"]]
    again = s.refine("Ромашка", "Закупки", "topic", topic, exclude_aids=shown, removed_aids=removed, limit=5)
    got = {it["aid"] for it in again["top"]}
    assert not got & (set(shown) | set(removed) | {1, 999})
    assert agents.calls.count("queries") == 1 and "hyde" not in agents.calls  # the profile's query blocks are reused, no HyDE


def test_refine_demotes_news_close_to_a_removed_one(tmp_path):
    corpus = make_corpus()
    # close to the removed item (>= REMOVED_SIM) but not its paraphrase (< PARAPHRASE_SIM); hash() differs per process, so search
    words, encode = corpus[5]["title"].split(), hash_encoder("x", 1)
    extra = [w for w in VOCAB if w not in words]
    title = next(t for k in range(0, 200, 2) for t in [" ".join(words[:5] + extra[k:k + 2])]
                 if REMOVED_SIM <= float(encode([t])[0] @ encode([corpus[5]["title"]])[0]) < PARAPHRASE_SIM)
    near = {**corpus[5], "aid": 500, "title": title, "link": "https://near.ru/1"}
    s, _ = searcher(tmp_path, corpus + [near])
    score = lambda res: next(it["score"] for it in res["top"] if it["aid"] == 500)  # limit above the corpus: every item is returned
    plain = s.refine("Ромашка", "Закупки", "claim", title, exclude_aids=[1], limit=500)
    penal = s.refine("Ромашка", "Закупки", "claim", title, exclude_aids=[1], removed_aids=[6], limit=500)
    assert score(penal) == pytest.approx(score(plain) * REMOVED_FACTOR)


def test_refine_drops_paraphrases_of_shown_news(tmp_path):
    corpus = make_corpus()
    # same words, other order and link: no shared URL/title for dd_hybrid, but the same vector
    para = {**corpus[5], "aid": 700, "title": " ".join(reversed(corpus[5]["title"].split())), "link": "https://para.ru/1"}
    s, _ = searcher(tmp_path, corpus + [para])
    res = s.refine("Ромашка", "Закупки", "topic", corpus[5]["title"], exclude_aids=[6], limit=10)
    assert 700 not in {it["aid"] for it in res["top"]} and res["stats"]["duplicates"] >= 1


def test_perspective_changes_the_result_and_reuses_the_page_queries(tmp_path):
    s, agents = searcher(tmp_path, make_corpus())
    topic = s.refine("Ромашка", "Закупки", "topic", f"{VOCAB[0]} {VOCAB[1]}", region="Тверь", limit=10)
    other = s.refine("Ромашка", "Закупки", "perspective", f"{VOCAB[0]} {VOCAB[1]}", region=f"{VOCAB[50]} {VOCAB[51]}",
                     page_region="Тверь", limit=10)
    assert [it["aid"] for it in topic["top"]] != [it["aid"] for it in other["top"]]
    assert agents.calls.count("queries") == 1 and other["region"] == f"{VOCAB[50]} {VOCAB[51]}"


def test_perspective_gives_up_to_three_places_to_close_news_naming_the_region(tmp_path):
    corpus = make_corpus()
    near = [{**corpus[0], "aid": 800 + k, "link": f"https://tver.ru/{k}",
             # a real word each: all VOCAB words share the stem "слово", so dedup would merge these titles
             "title": f"{VOCAB[0]} {VOCAB[1]} Тверской {w} {VOCAB[100 + 2 * k]} {VOCAB[101 + 2 * k]}"}
            for k, w in enumerate(["зерно", "молоко", "сталь", "нефть", "уголь"])]
    far = {**corpus[0], "aid": 900, "link": "https://tver.ru/far", "title": f"В Тверской области {VOCAB[200]} {VOCAB[201]}"}
    s, _ = searcher(tmp_path, corpus + near + [far])
    res = s.refine("Ромашка", "Закупки", "perspective", f"{VOCAB[0]} {VOCAB[1]}", region="Тверская область", page_region="Москва")
    regional = [it for it in res["top"] if it["regional"]]
    assert len(regional) == res["stats"]["regional"] == 3 and len(res["top"]) == 10
    assert all(800 <= it["aid"] < 805 for it in regional) and res["top"][:3] == regional
    topic = s.refine("Ромашка", "Закупки", "topic", f"{VOCAB[0]} {VOCAB[1]}", region="Москва")
    assert not any(it["regional"] for it in topic["top"])


def test_refine_rejects_unknown_kind_and_empty_text(tmp_path):
    s, _ = searcher(tmp_path, make_corpus())
    with pytest.raises(ValueError):
        s.refine("Ромашка", "Закупки", "graph", "текст")
    with pytest.raises(ValueError):
        s.refine("Ромашка", "Закупки", "topic", "  ")


def test_dedup_merges_same_url_same_title_and_near_duplicates_only():
    items = [{"link": "https://a.ru/x?utm_source=t", "title": "ЦБ повысил ключевую ставку до 17 процентов"},
             {"link": "https://www.a.ru/x", "title": "Что-то совсем другое про зерно"},
             {"link": "https://b.ru/1", "title": "ЦБ повысил ключевую ставку до 17%"},
             {"link": "https://c.ru/2", "title": "Экспорт пшеницы вырос на треть"},
             {"link": "https://d.ru/3", "title": "Экспорт пшеницы вырос на треть"}]
    labels = dd_hybrid(items)
    assert labels[0] == labels[1] == labels[2] and labels[3] == labels[4] and labels[0] != labels[3]


def test_match_items_needs_enough_shared_stems():
    items = [{"title": "Ключевая ставка Банка России выросла"}, {"title": "Погода в Твери"}]
    got = match_items(items, ["ключевая ставка ЦБ", "погода"])
    assert [j for _, j in got["ключевая ставка ЦБ"]] == [0] and [j for _, j in got["погода"]] == [1]


def test_xquad_takes_a_less_relevant_item_that_covers_a_new_block():
    rows = [(1.0, [1, 0]), (0.9, [1, 0]), (0.8, [1, 0]), (0.7, [0, 1]), (0.0, [1, 0])]
    assert scoring.xquad([{"score": s, "aspects": a} for s, a in rows], k=2) == [0, 3]


def test_vector_cache_encodes_only_new_articles(tmp_path):
    seen = []
    def encode(texts):
        seen.extend(texts)
        return hash_encoder("x", 1)(texts)
    cache, items = VectorCache(str(tmp_path / "v.npz")), make_corpus(5)
    a = cache.vectors(items, encode)
    b = cache.vectors(items + make_corpus(7)[5:], encode)
    assert len(seen) == 7 and np.allclose(a, b[:5], atol=1e-2) and b.shape == (7, 64)


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to read a real PostgreSQL corpus")
def test_postgres_corpus_reads_articles_with_outlet_and_skips_old_ones():
    import psycopg
    dsn = os.environ["TEST_DATABASE_URL"]
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("DROP SCHEMA IF EXISTS ns_test CASCADE; CREATE SCHEMA ns_test")
        conn.execute("SET search_path = ns_test")
        conn.execute("CREATE TABLE sources (id text PRIMARY KEY, name text)")
        conn.execute("CREATE TABLE articles (id bigserial PRIMARY KEY, source_id text, url text, title text, text text, published_at timestamptz)")
        conn.execute("INSERT INTO sources VALUES ('s', 'РБК')")
        conn.execute("INSERT INTO articles (source_id, url, title, text, published_at) VALUES ('s','https://a','Свежая',repeat('x',500),now()), ('s','https://b','Старая','',now() - interval '400 days'), ('s','https://c','Без даты','',NULL)")
        try:
            load = postgres_corpus(dsn + ("&" if "?" in dsn else "?") + "options=-csearch_path%3Dns_test")
            rows = load(365)
        finally:
            conn.execute("DROP SCHEMA ns_test CASCADE")
    assert {r["title"] for r in rows} == {"Свежая", "Без даты"} and all(r["outlet"] == "РБК" for r in rows)
    assert next(r for r in rows if r["title"] == "Свежая")["summary"] == "x" * 300


def test_steps_and_results_go_to_the_cache_and_not_to_the_data_folder(tmp_path):
    s, agents = searcher(tmp_path, make_corpus())
    s.search("Ромашка", "Закупки", "Тверь", "dense_xquad")
    key = s.run_key("Ромашка", "Закупки", "Тверь")
    assert {name for (k, name) in s.cache.items if k == key} == {"queries", "needs", "hyde", "result_dense_xquad"}
    assert not (tmp_path / "runs").exists()  # nothing but the vector cache is written to the folder


def test_cache_entries_expire_by_age():
    from news_search.cache import MemoryCache
    cache = MemoryCache()
    cache.put("k", "n", {"a": 1})
    assert cache.get("k", "n") == {"a": 1} and cache.get("k", "n", 3600) == {"a": 1} and cache.get("k", "n", 0) is None and cache.get("k", "x") is None


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to use a real PostgreSQL cache")
def test_postgres_cache_survives_a_new_instance_and_updates_in_place():
    from news_search.cache import PgCache
    dsn, key = os.environ["TEST_DATABASE_URL"], "test_" + str(random.random())
    PgCache(dsn).put(key, "queries", {"a": ["б"]})
    again = PgCache(dsn)
    assert again.get(key, "queries") == {"a": ["б"]} and again.get(key, "queries", 0) is None and again.get(key, "hyde") is None
    again.put(key, "queries", {"a": []})
    assert PgCache(dsn).get(key, "queries", 3600) == {"a": []}


def test_region_index_finds_regions_by_outlet_and_inflected_names():
    from news_search.region import RegionIndex
    r = RegionIndex()
    assert r.find("В Новосибирске открыли завод") == {"Новосибирская область"}
    assert r.find("Власти Татарстана и Казанский суд") == {"Республика Татарстан"}
    assert r.find("ЦБ сохранил ключевую ставку") == set()
    assert r.find("Выборы прошли спокойно, читайте подробности") == set()  # Выборг, Чита: city names need a capital letter
    assert r.find("В воронежской области выпал снег") == {"Воронежская область"}  # region names match in any case
    assert r.of({"aid": 1, "title": "Пожар на складе", "summary": "", "source": "ngs"}) == {"Новосибирская область"}
    assert r.of({"aid": 2, "title": "В Казани открыли мост", "summary": "", "source": "ngs"}) == {"Республика Татарстан"}  # a named place wins


def test_low_locality_brings_news_from_outside_the_region(tmp_path):
    corpus = make_corpus()
    for it in corpus[: len(corpus) * 2 // 3]:  # two thirds of the corpus is about the profile's region
        it["summary"] = "Новосибирск"
    local = {it["aid"] for it in corpus if it["summary"]}
    s, _ = searcher(tmp_path, corpus)

    def outside(locality):
        top = s.search("Ромашка", "Закупки", "Новосибирская область", "dense_xquad", locality=locality)["top"][:10]
        return sum(it["aid"] not in local for it in top)
    assert outside(0.0) > outside(1.0) and outside(1.0) == outside(None)
    assert all("source" not in it for it in s.search("Ромашка", "Закупки", "Новосибирская область", "dense_xquad", locality=0.0)["top"])
