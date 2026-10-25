"""NewsSearch: every way of turning (company, sphere, region) into a ranked list of news from the corpus.

Methods (choose one per call; the backend config decides which):
  lexical      stem match of keyword queries, deduplicated, ranked by the number of matched queries and freshness (baseline)
  dense_llm    v1: lexical pool, e5-large-instruct + bge-m3 on queries and HyDE headlines, an LLM picks the top 30, rank fusion
  dense_xquad  v2 (default): bge-m3 over the whole corpus with needs + HyDE, then xQuAD diversification over the query blocks
refine() adds news to a shown page (dense_xquad only): close to a topic, conclusion or pasted news, without shown or removed ones.

All LLM calls go through the agents service (the `agents` argument: anything with run(name, input) -> dict).
"""
import collections
import datetime
import hashlib
import json
import os
import re

import numpy as np

from agents import tracing

from news_search import scoring
from news_search.cache import MemoryCache
from news_search.dedup import UnionFind, dd_hybrid
from news_search.embed import VectorCache, sentence_transformer, wrap_query
from news_search.scoring import TOP_OUT, age_days, fresh, mean_top3, norm01
from news_search.text import match_items, norm_title

METHODS = ("lexical", "dense_llm", "dense_xquad")
DEFAULT_METHOD = "dense_xquad"
CORPUS_DAYS, CACHE_TTL = 365, 24 * 3600  # corpus window; a finished result is reused for a day
PER_QUERY_CORPUS = 30  # lexical matches per query
N_DENSE, TOP_CAND = 100, 150  # v2: dense candidates, and with the lexical second source
TOP_EMB, MAX_CAND = 50, 200  # v1: per embedder, and after interleaving
REFINE_KINDS, REFINE_LIMIT, REFINE_TTL = ("topic", "perspective", "claim", "link"), 10, 3600
REMOVED_SIM, REMOVED_FACTOR = 0.7, 0.5  # refine: news this close to a removed one get half the score
# shortcut: paraphrase threshold picked by eye on 3 topics (paraphrases 0.80-0.85, related news <= 0.73), tune on labelled pairs
PARAPHRASE_SIM = 0.8
# perspective: up to REGION_SLOTS of the results name the new region and are at least this close to the topic (raw cosine)
# shortcut: threshold picked by eye on 6 topics (relevant regional news 0.39-0.50), region found by its name only, not by
# the capital or the outlet's region; add source_regions of the collector when the corpus has it
REGION_SLOTS, REGION_SIM = 3, 0.42
REGION_GENERIC = {"область", "край", "республика", "автономный", "автономная", "округ", "город"}
# Names of companies the pipeline was tuned on; any other company falls back to its name stems (see own_pattern).
ALIASES = {"Магазин Мать и Дитя": r"мать и дит|мать и дочь|\bмд мед", "Инарктика": r"инарктик|интарктик|\baqua\b|inarctica",
           "Группа Астра": r"групп\w* астр|astra|астра линукс|\bастр[аыуе]\b", "Делимобиль": r"делимобил|delimobil",
           "Селектел": r"селектел|selectel"}


class TooFewNews(ValueError):
    pass


def own_pattern(company):
    if company in ALIASES:
        return ALIASES[company]
    # shortcut: an unknown company matches when all its name stems appear in the title; add an ALIASES entry for better recall
    stems = [w[:5] for w in re.findall(r"[a-zа-я0-9]+", company.lower().replace("ё", "е")) if len(w) > 2 and w not in ("группа", "компания", "магазин")]
    return "".join(f"(?=.*{s})" for s in stems) if stems else re.escape(company.lower())


def dedup_filter(pool, company, anonymised=False):
    with tracing.span("deduplication") as event:
        items, own = _dedup_filter(pool, company, anonymised)
        event["counts"] = {"before": len(pool), "after": len(items), "own_removed": own, "duplicates": len(pool) - len(items) - own}
        return items, own


def _dedup_filter(pool, company, anonymised=False):
    """Merge duplicates, drop news about the company itself. Returns (items, number of dropped own-company clusters)."""
    clusters = collections.defaultdict(list)
    for i, label in enumerate(dd_hybrid(pool)):
        clusters[label].append(pool[i])
    pattern = None if anonymised else re.compile(own_pattern(company), re.S)  # anonymised data has no company name to filter on
    items, own = [], 0
    for members in clusters.values():
        if {b for m in members for b in m["blocks"]} == {"company_self"} or (pattern and any(pattern.search(m["title"].lower()) for m in members)):
            own += 1
            continue
        first = members[0]
        items.append({"id": len(items), "aid": first["aid"], "title": first["title"], "link": first["link"], "date": first["date"],
                      "summary": first.get("summary", ""), "outlets": sorted({m["outlet"] for m in members}),
                      "methods": sorted({m["method"] for m in members}),
                      "blocks": dict(collections.Counter(b for m in members for b in m["blocks"])),
                      "queries": sorted({q for m in members for q in m["queries"]}),
                      **{k: first[k] for k in ("score", "aspects", "vec") if k in first}})  # ranking data of the best copy
    return items, own


class NewsSearch:
    def __init__(self, corpus, agents, data_dir, encoder_factory=sentence_transformer, now=None, cache=None):
        """corpus: load(days) -> items (see corpus.postgres_corpus); data_dir keeps the vector cache; cache keeps the run steps and results
        (cache.PgCache in the service). shortcut: the default MemoryCache forgets everything on exit, pass a PgCache where results must survive."""
        self._corpus, self.agents, self.data_dir = corpus, agents, data_dir
        self.cache = cache or MemoryCache()
        self.encoder_factory, self._now = encoder_factory, now
        self._bge = None

    def corpus(self, days):
        with tracing.span("retrieval") as event:
            items = self._corpus(days)
            event["counts"] = {"after": len(items)}
            return items

    def now(self):
        return self._now() if self._now else datetime.datetime.now(datetime.timezone.utc)

    def search(self, company, line, region="", method=DEFAULT_METHOD, anonymised=False):
        if method not in METHODS:
            raise ValueError(f"method must be one of {METHODS}")
        run_key = self.run_key(company, line, region)
        if (done := self.cache.get(run_key, f"result_{method}", CACHE_TTL)) is not None:
            tracing.emit("cache", status="cached", counts={"selected": len(done["top"])}, queries=tracing.query_sample(self.keyword_queries(self.cache.get(run_key, "queries") or {})))
            return done
        cost0 = self.agents.cost
        ask = dict(company=company, line=line, region=region)
        queries = self._cached(run_key, "queries", lambda: self.agents.run("queries", ask))
        if method == "dense_xquad":
            needs = self._cached(run_key, "needs", lambda: self.agents.run("needs", ask))["needs"]
        headlines = None if method == "lexical" else self._cached(run_key, "hyde", lambda: self.agents.run("hyde", ask))["headlines"]
        run = dict(company=company, line=line, region=region, anonymised=anonymised, queries=queries, headlines=headlines, now=self.now())
        if method == "dense_xquad":
            res = self._dense_xquad(run, needs)
        else:
            res = getattr(self, "_" + method)(run)
        tracing.emit("ranking", counts={"before": res["stats"]["unique"], "selected": len(res["top"])}, source_ids=[f"article:{it['aid']}" for it in res["top"]])
        res.update(company=company, line=line, region=region, method=method, date=datetime.date.today().isoformat(), cost=round(self.agents.cost - cost0, 4))
        self.cache.put(run_key, f"result_{method}", res)
        return res

    @staticmethod
    def run_key(company, line, region):
        slug = "__".join(re.sub(r"\W+", "_", x.lower())[:40] for x in (company, line, region) if x)
        return slug + "__" + hashlib.sha1(f"{company}|{line}|{region}".encode()).hexdigest()[:8]

    def refine(self, company, line, kind, text, region="", exclude_aids=(), removed_aids=(), limit=REFINE_LIMIT, anonymised=False,
               page_line=None, page_region=None):
        """Additional search on top of a shown page (dense_xquad only): news close to `text`, none of the shown or removed
        news or their duplicates or paraphrases, news close to removed ones demoted. kind: topic (a new topic),
        perspective (the topic seen from another region/line: line and region are the new ones, page_line/page_region
        the page's), claim (an edited conclusion), link (title + text of a news item the user pasted)."""
        if kind not in REFINE_KINDS:
            raise ValueError(f"kind must be one of {REFINE_KINDS}")
        if not text.strip():
            raise ValueError("text is empty")
        page_line = line if page_line is None else page_line
        page_region = region if page_region is None else page_region
        run_key = self.run_key(company, page_line, page_region)  # the page's query blocks are reused, no new queries call
        key = hashlib.sha1(json.dumps([kind, text, line, region, sorted(exclude_aids), sorted(removed_aids), limit, anonymised]).encode()).hexdigest()[:12]
        if (done := self.cache.get(run_key, f"refine_{key}", REFINE_TTL)) is not None:
            tracing.emit("cache", status="cached", counts={"selected": len(done["top"])}, queries=tracing.query_sample(self.keyword_queries(self.cache.get(run_key, "queries") or {})))
            return done
        cost0 = self.agents.cost
        queries = self._cached(run_key, "queries", lambda: self.agents.run("queries", dict(company=company, line=page_line, region=page_region)))
        items = self.corpus(CORPUS_DAYS)
        encode = self.bge()
        X = VectorCache(os.path.join(self.data_dir, "vectors_bgem3.npz")).vectors(items, encode)
        now = self.now()
        texts = [text] + ([f"{text}. {region}", f"{text}. {line}"] if kind == "perspective" else [])
        s = norm01(scoring.zscore_top3(X, encode(texts))) * np.array([fresh(age_days(it["date"], now)) for it in items])
        shown, removed = set(exclude_aids), set(removed_aids)
        rem = [j for j, it in enumerate(items) if it["aid"] in removed]
        if rem:  # shortcut: fixed threshold and factor, tune on news_search/benchmarks/refine.md
            s = np.where((X @ X[rem].T).max(1) >= REMOVED_SIM, s * REMOVED_FACTOR, s)
        top = [int(j) for j in np.argsort(-s, kind="stable") if items[j]["aid"] not in shown | removed][:TOP_CAND]
        regional = {}  # aid -> cosine with the topic, for news naming the perspective's region
        if kind == "perspective":
            stems = {w[:6] for w in norm_title(region).split() if len(w) > 3 and w not in REGION_GENERIC}
            cos = X @ encode([text])[0]
            for j in np.nonzero(cos >= REGION_SIM)[0]:
                it = items[j]
                if it["aid"] not in shown | removed and stems & {w[:6] for w in norm_title(it["title"] + " " + (it["summary"] or "")).split()}:
                    regional[it["aid"]] = float(cos[j])
                    if j not in top:
                        top.append(int(j))
        blocks = [b for b in queries if b != "company_self"]
        B = np.stack([(X[top] @ encode(queries[b]).T).max(1) for b in blocks], 1)
        pool = [{**{k: items[j][k] for k in ("aid", "title", "link", "date", "outlet", "summary")}, "method": "D", "queries": [], "score": float(s[j]),
                 "blocks": [blocks[int(B[r].argmax())]], "aspects": B[r].round(4).tolist(), "vec": X[j]} for r, j in enumerate(top)]
        # duplicates and paraphrases (cosine >= PARAPHRASE_SIM) of shown or removed news are dropped, and of each other
        # only the best scored copy is kept: dedup the pool together with the seen news
        seen_j = [j for j, it in enumerate(items) if it["aid"] in shown | removed]
        uf = UnionFind(len(pool) + len(seen_j))
        for i, label in enumerate(dd_hybrid(pool + [items[j] for j in seen_j])):
            uf.union(i, label)
        V = X[top + seen_j]
        for a, b in zip(*np.nonzero(np.triu(V @ V.T >= PARAPHRASE_SIM, 1))):
            uf.union(int(a), int(b))
        labels = uf.labels()
        taken = set(labels[len(pool):])
        kept = []
        for p, label in zip(pool, labels):  # pool is ordered by score
            if label not in taken:
                kept.append(p)
                taken.add(label)
        pool = kept
        unique, own = dedup_filter(pool, company, anonymised)
        reg = sorted((u for u in unique if u["aid"] in regional), key=lambda u: -regional[u["aid"]])[:min(REGION_SLOTS, limit)]
        reg_aids = {u["aid"] for u in reg}  # by aid: the items hold numpy vectors, dict equality would compare them
        rest = [u for u in unique if u["aid"] not in reg_aids]
        picked = reg + ([rest[i] for i in scoring.xquad(rest, k=limit - len(reg))] if rest else [])
        res = {"top": [{**self.public(it), "regional": it["aid"] in reg_aids} for it in picked], "pairs": scoring.pairs(picked) if picked else [], "blocks": blocks,
               "stats": {"candidates": len(top), "duplicates": len(top) - len(pool), "unique": len(unique), "own_removed": own,
                         "excluded": len(shown), "removed": len(removed), "regional": len(reg)},
               "company": company, "line": line, "region": region, "method": "dense_xquad", "kind": kind, "text": text,
               "date": datetime.date.today().isoformat(), "cost": round(self.agents.cost - cost0, 4)}
        tracing.emit("refine", counts={"before": len(top), "duplicates": len(top) - len(pool), "excluded": len(shown), "removed": len(removed), "regional": len(reg), "selected": len(picked)})
        tracing.emit("ranking", counts={"before": len(unique), "selected": len(picked)}, source_ids=[f"article:{it['aid']}" for it in picked])
        self.cache.put(run_key, f"refine_{key}", res)
        return res

    def _cached(self, run_key, name, make):
        """A generated step (queries, needs, HyDE) is kept with the result: repeated searches do not pay for it again."""
        with tracing.span(name) as event:
            out = self.cache.get(run_key, name)
            if out is None:
                out = make()
                self.cache.put(run_key, name, out)
            else:
                event["status"] = "cached"
            if name == "queries":
                queries = self.keyword_queries(out)
                event.update(counts={"queries": len(queries)}, queries=tracing.query_sample(queries))
            return out

    # ---------------- shared steps ----------------
    @staticmethod
    def keyword_queries(queries):
        return sorted({q for b, qs in queries.items() if b != "company_self" for q in qs})

    def lexical_pool(self, items, queries):
        """Stemmed token overlap of every query with the corpus."""
        block = {q: b for b, qs in queries.items() for q in qs}
        pool = []
        for q, found in match_items(items, sorted(block), per_query=PER_QUERY_CORPUS).items():
            for _, j in found:
                pool.append({**{k: items[j][k] for k in ("aid", "title", "link", "date", "outlet", "summary")}, "method": "B", "queries": [q], "blocks": [block[q]]})
        return pool

    def unique(self, pool, run):
        items, own = dedup_filter(pool, run["company"], run["anonymised"])
        if len(items) < TOP_OUT:
            raise TooFewNews(f"too few news collected: {len(items)} unique, need {TOP_OUT}")
        return items, own

    @staticmethod
    def public(item):
        return {k: v for k, v in item.items() if k not in ("vec", "aspects")}

    # ---------------- lexical ----------------
    def _lexical(self, run):
        items, own = self.unique(self.lexical_pool(self.corpus(CORPUS_DAYS), run["queries"]), run)
        for it in items:  # more distinct matching queries first, outlets confirming the story add a little, then freshness
            it["score"] = (len(it["queries"]) + 0.01 * min(len(it["outlets"]) - 1, 3)) * fresh(age_days(it["date"], run["now"]))
        top = sorted(items, key=lambda it: -it["score"])[:TOP_OUT]
        return {"top": [self.public(it) for it in top], "pairs": [], "blocks": [b for b in run["queries"] if b != "company_self"],
                "stats": {"unique": len(items), "own_removed": own}}

    # ---------------- dense_llm (v1) ----------------
    def _dense_llm(self, run):
        items, own = self.unique(self.lexical_pool(self.corpus(CORPUS_DAYS), run["queries"]), run)
        lists = self.embed_lists(items, run)
        cand = list(dict.fromkeys(i for pair in zip(*lists) for i in pair))[:MAX_CAND]  # interleave so both embedders survive the cap
        asked = self.agents.run("pick", {"company": run["company"], "line": run["line"], "top": TOP_OUT, "candidates": [
            {"id": i, "date": items[i]["date"], "outlets": items[i]["outlets"], "title": items[i]["title"]} for i in cand]})["top"]
        final, score = scoring.fuse([asked], items, run["now"])
        top = [{**self.public(items[i]), "score": round(score[i], 4), "voted_by": ["glm"]} for i in final]
        return {"top": top, "pairs": [], "blocks": [b for b in run["queries"] if b != "company_self"],
                "stats": {"unique": len(items), "own_removed": own, "candidates": len(cand)}}

    def embed_lists(self, items, run):
        """Per embedder: titles vs keyword queries and HyDE headlines, times freshness; the best TOP_EMB ids of each."""
        fr = np.array([fresh(age_days(it["date"], run["now"])) for it in items])
        queries = self.keyword_queries(run["queries"])
        lists = []
        for name in ("e5-large-instruct", "bge-m3"):
            encode = self.encoder_factory(name, 96)
            E = encode([it["title"] for it in items])
            s_raw = mean_top3(E @ encode([wrap_query(name, q) for q in queries]).T)
            SH = E @ encode([wrap_query(name, h) for h in run["headlines"]]).T
            s_hyde = mean_top3((SH - SH.mean(0)) / (SH.std(0) + 1e-6))  # z-norm per HyDE headline
            lists.append([int(i) for i in np.argsort(-(norm01(s_raw) + norm01(s_hyde)) * fr, kind="stable")[:TOP_EMB]])
            del encode
        return lists

    # ---------------- dense_xquad (v2) ----------------
    def bge(self):
        if self._bge is None:
            self._bge = self.encoder_factory("bge-m3", 128)
        return self._bge

    def _dense_xquad(self, run, needs):
        """Dense candidates from the whole corpus window, no lexical gate (the lexical match alone reached ~45% of relevant news)."""
        items = self.corpus(CORPUS_DAYS)
        encode = self.bge()
        X = VectorCache(os.path.join(self.data_dir, "vectors_bgem3.npz")).vectors(items, encode)
        fr = np.array([fresh(age_days(it["date"], run["now"])) for it in items])
        s = (norm01(scoring.zscore_top3(X, encode(needs))) + norm01(scoring.zscore_top3(X, encode(run["headlines"])))) * fr
        dense = [int(j) for j in np.argsort(-s, kind="stable")[:N_DENSE]]
        # second source, not a gate: the stem match over the keyword queries adds news that dense search misses (recall 0.59 -> 0.63)
        lex = {j for found in match_items(items, self.keyword_queries(run["queries"]), per_query=PER_QUERY_CORPUS).values() for _, j in found}
        top = np.array(dense + sorted(lex - set(dense), key=lambda j: -s[j])[:TOP_CAND - N_DENSE])
        blocks = [b for b in run["queries"] if b != "company_self"]
        B = np.stack([(X[top] @ encode(run["queries"][b]).T).max(1) for b in blocks], 1)  # aspect score: best keyword query of each block
        pool = [{**{k: items[j][k] for k in ("aid", "title", "link", "date", "outlet", "summary")}, "method": "D", "queries": [], "score": float(s[j]),
                 "blocks": [blocks[int(B[r].argmax())]], "aspects": B[r].round(4).tolist(), "vec": X[j]} for r, j in enumerate(top)]
        unique, own = self.unique(pool, run)
        shown = [unique[i] for i in scoring.xquad(unique)]
        return {"top": [self.public(it) for it in shown], "pairs": scoring.pairs(shown), "blocks": blocks,
                "stats": {"candidates": len(pool), "unique": len(unique), "own_removed": own}}
