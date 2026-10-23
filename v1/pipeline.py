"""News digest v1, one loop: (company, line) -> search queries -> news -> dedup -> embedding ranking -> LLM top-30.

    python pipeline.py "Делимобиль" "Глава найма"      # -> out/<slug>/{queries,corpus,result}.json + digest.md

Steps (each caches its result in out/<slug>/, delete the file to redo the step):
 1. DeepSeek turns prompt.md into search queries by blocks.
 2. Search the Postgres corpus (ingest.py + Go collector) with stemmed token overlap against the queries.
 3. Hybrid dedup, drop the company's own news.
 4. v3 retrieval: e5-large-instruct and bge-m3 score titles against queries + DeepSeek HyDE headlines, x freshness; top-50 each.
 5. Three LLMs (GLM, Qwen, DeepSeek) pick top-30 from the union; RRF fusion x freshness -> final top-30.
"""
import collections, datetime, json, os, re, subprocess, sys, time, urllib.error, urllib.parse, urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from email.utils import format_datetime, parsedate_to_datetime

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib import dd_hybrid, match_items, toks  # noqa

HERE = os.path.dirname(os.path.abspath(__file__))
QUERY_MODEL = "deepseek/deepseek-v4.1-flash"  # queries + HyDE
PICK_MODELS = {"deepseek": "deepseek/deepseek-v4.1-flash", "qwen": "qwen/qwen3.6-35b-a3b", "glm": "z-ai/glm-5.3-flash"}
EMBEDDERS = {  # name: (hf id, query wrapper)
    "e5-large-instruct": ("intfloat/multilingual-e5-large-instruct",
                          lambda q: "Instruct: Given a company profile or a news search query, retrieve relevant Russian news headlines\nQuery: " + q),
    "bge-m3": ("BAAI/bge-m3", lambda q: q),
}
PER_QUERY_CORPUS, CORPUS_DAYS = 30, 365  # matches per query, corpus window
CACHE_TTL = 24 * 3600  # corpus snapshot and final result are reused for a day; queries and HyDE are kept
PER_QUERY, TOP_EMB, MAX_CAND, TOP_OUT, RRF_K = 15, 50, 200, 30, 10
TODAY = datetime.datetime.now(datetime.timezone.utc)
UA = "Mozilla/5.0 (compatible; NewsResearchBot/0.1)"
COST = [0.0]


def env():
    cfg = {}
    for p in (os.path.join(HERE, "..", ".env"), os.path.join(HERE, ".env")):
        if os.path.exists(p):
            cfg.update(l.strip().split("=", 1) for l in open(p) if "=" in l and not l.startswith("#"))
    return {**cfg, **os.environ}


CFG = env()


# ---------------- LLM ----------------
def chat(model, prompt, max_tokens=32000):
    """Streaming call (long reasoning answers drop non-streaming connections); main gateway, then backup."""
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
                       "stream": True, "stream_options": {"include_usage": True}}).encode()
    err = None
    for base in (CFG["LLM_BASE_URL"], CFG.get("LLM_BASE_URL_BACKUP")):
        if not base: continue
        req = urllib.request.Request(base + "/chat/completions", data=body,
                                     headers={"Authorization": f"Bearer {CFG['LLM_API_KEY']}", "Content-Type": "application/json"})
        text, usage = "", None
        try:
            with urllib.request.urlopen(req, timeout=600) as r:
                for line in r:
                    line = line.decode("utf-8", "ignore").strip()
                    if not line.startswith("data:") or line.endswith("[DONE]"): continue
                    ev = json.loads(line[5:])
                    usage = ev.get("usage") or usage
                    for ch in ev.get("choices", []):
                        text += (ch.get("delta") or {}).get("content") or ""
            COST[0] += float((usage or {}).get("cost") or 0)
            return text
        except Exception as e:
            err = e
    raise RuntimeError(f"LLM {model} failed: {err!r}")


def chat_json(model, prompt, key, tries=3):
    """Reasoning models sometimes return empty/truncated answers: retry."""
    for _ in range(tries):
        try:
            m = re.search(r"\{.*\}", chat(model, prompt), re.S)
            d = json.loads(m.group(0))
            if d.get(key): return d
        except Exception:
            pass
    raise RuntimeError(f"{model}: no valid JSON with '{key}' after {tries} tries")


# ---------------- 1. queries ----------------
def gen_queries(company, line):
    prompt = (open(os.path.join(HERE, "prompt.md"), encoding="utf-8").read()
              .replace("{today}", datetime.date.today().isoformat()).replace("{company}", company).replace("{line}", line))
    d = chat_json(QUERY_MODEL, prompt, "company_self")  # prompt.md always asks for this block
    return {b: [x.strip() for x in v if isinstance(x, str) and x.strip()] for b, v in d.items() if isinstance(v, list)}


# ---------------- 2. collection ----------------
def google_news(q, limit=PER_QUERY):
    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": q, "hl": "ru", "gl": "RU", "ceid": "RU:ru"})
    for attempt in range(5):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=25) as r:
                root = ET.fromstring(r.read())
            out = []
            for it in root.iter("item"):
                src = it.find("source")
                name = (src.text or "").strip() if src is not None else ""
                title = (it.findtext("title") or "").strip()
                if name and title.endswith(" - " + name): title = title[: -len(name) - 3]
                out.append({"title": title, "link": it.findtext("link") or "", "date": it.findtext("pubDate") or "", "outlet": name or "?"})
                if len(out) >= limit: break
            return out
        except urllib.error.HTTPError as e:
            if e.code not in (429, 503): return []
            time.sleep(5 * (attempt + 1))
        except Exception:
            time.sleep(2)
    return []


def parse_feed(raw):
    root = ET.fromstring(raw)
    A = "{http://www.w3.org/2005/Atom}"
    out = []
    for it in list(root.iter("item")) + list(root.iter(A + "entry")):
        def g(*names):
            for n in names:
                e = it.find(n)
                if e is not None and (e.text or e.attrib.get("href")): return (e.text or e.attrib["href"]).strip()
            return ""
        out.append({"title": g("title", A + "title"), "link": g("link", A + "link"),
                    "date": g("pubDate", A + "updated", "{http://purl.org/dc/elements/1.1/}date"),
                    "summary": re.sub(r"<[^>]+>", " ", g("description", A + "summary"))[:400]})
    return out


def pull_feed(o):
    # curl, not urllib: several outlets fail TLS/UA checks with urllib
    raw = subprocess.run(["curl", "-sSL", "-m", "25", "-A", UA, "--compressed", o["feed"]], capture_output=True).stdout
    try:
        items = parse_feed(raw)
    except Exception:
        items = []
    return [{**it, "outlet": o["name"]} for it in items]


def corpus_items(days=CORPUS_DAYS):
    """All corpus rows of the last `days` days (undated ones too) as feed-like items; ~100-150k titles fit in memory."""
    import psycopg
    with psycopg.connect(CFG["DATABASE_URL"]) as conn:
        rows = conn.execute("SELECT a.title, a.url, a.published_at, s.name, left(a.text, 400) FROM articles a JOIN sources s ON s.id = a.source_id "
                            "WHERE a.published_at IS NULL OR a.published_at > now() - make_interval(days => %s)", (days,)).fetchall()
    return [{"title": t, "link": u, "date": format_datetime(d) if d else "", "outlet": o, "summary": x} for t, u, d, o, x in rows]


def collect(queries, d):
    """Candidates come from the Postgres corpus (filled by ingest.py and the Go collector), not from live RSS/Google."""
    items = corpus_items()
    blk = {q: b for b, qs in queries.items() for q in qs}
    pool = []
    # shortcut: lexical stem match like before; add embedding search over the whole corpus if recall is not enough
    for q, lst in match_items(items, sorted(blk), per_query=PER_QUERY_CORPUS).items():
        for _, j in lst:
            pool.append({**{k: items[j][k] for k in ("title", "link", "date", "outlet")}, "method": "B", "queries": [q], "blocks": [blk[q]]})
    return pool


# ---------------- 3. dedup + own-company filter ----------------
ALIASES = {"Магазин Мать и Дитя": r"мать и дит|мать и дочь|\bмд мед", "Инарктика": r"инарктик|интарктик|\baqua\b|inarctica",
           "Группа Астра": r"групп\w* астр|astra|астра линукс|\bастр[аыуе]\b", "Делимобиль": r"делимобил|delimobil",
           "Селектел": r"селектел|selectel"}


def own_pattern(company):
    if company in ALIASES: return ALIASES[company]
    # shortcut: unknown company -> its name stems must all appear in the title; add an ALIASES entry for better recall
    stems = [w[:5] for w in re.findall(r"[a-zа-я0-9]+", company.lower().replace("ё", "е")) if len(w) > 2 and w not in ("группа", "компания", "магазин")]
    return "".join(f"(?=.*{s})" for s in stems) if stems else re.escape(company.lower())


def dedup_filter(pool, company):
    lab = dd_hybrid(pool)
    cl = collections.defaultdict(list)
    for i, l in enumerate(lab): cl[l].append(pool[i])
    pat = re.compile(own_pattern(company), re.S)
    items, own = [], 0
    for mem in cl.values():
        if set(b for m in mem for b in m["blocks"]) == {"company_self"} or any(pat.search(m["title"].lower()) for m in mem):
            own += 1; continue
        items.append({"id": len(items), "title": mem[0]["title"], "link": mem[0]["link"], "date": mem[0]["date"],
                      "outlets": sorted({m["outlet"] for m in mem}), "methods": sorted({m["method"] for m in mem}),
                      "blocks": dict(collections.Counter(b for m in mem for b in m["blocks"])),
                      "queries": sorted({q for m in mem for q in m["queries"]})})
    return items, own


# ---------------- 4. v3 retrieval ----------------
def age_days(d):
    try:
        t = parsedate_to_datetime(d)
        return (TODAY - (t if t.tzinfo else t.replace(tzinfo=datetime.timezone.utc))).days
    except Exception:
        return 60  # unknown date: middling


def fresh(days):  # stale news is demoted, not dropped
    return 1.0 if days <= 30 else 0.85 if days <= 90 else 0.6 if days <= 365 else 0.3


def mean_top3(S):
    k = min(3, S.shape[1])
    return np.sort(np.partition(S, -k, axis=1)[:, -k:], axis=1).mean(1)


def norm01(x): x = np.asarray(x, dtype=np.float64); return (x - x.min()) / (x.max() - x.min() + 1e-9)


def hyde(company, line):
    p = (f"Компания: «{company}». Сфера анализа бизнеса: «{line}» (срез бизнеса, за который отвечает руководитель). "
         "Придумай 40 правдоподобных заголовков российских новостей, которые были бы полезны этому руководителю: "
         "про прямых и непрямых конкурентов, заменители, поставщиков, клиентов, регулирование и законы, макроэкономику, технологии, "
         "рынок труда, сезонность, риски и возможности. НЕ про саму компанию. Заголовки в стиле реальных новостных лент, 6-14 слов, без дат. "
         "Верни ТОЛЬКО JSON {\"headlines\": [...]}.")
    return chat_json(QUERY_MODEL, p, "headlines")["headlines"]


def embed_lists(items, queries, headlines):
    from sentence_transformers import SentenceTransformer
    import torch
    dev = "cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu"
    fr = np.array([fresh(age_days(it["date"])) for it in items])
    qs = sorted({q for b, l in queries.items() if b != "company_self" for q in l})
    lists = []
    for name, (hf, wrap) in EMBEDDERS.items():
        m = SentenceTransformer(hf, device=dev); m.max_seq_length = 96
        enc = lambda x: m.encode(x, batch_size=64, normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False).astype(np.float32)
        E = enc([it["title"] for it in items])
        s_raw = mean_top3(E @ enc([wrap(q) for q in qs]).T)
        SH = E @ enc([wrap(h) for h in headlines]).T
        s_hyde = mean_top3((SH - SH.mean(0)) / (SH.std(0) + 1e-6))  # z-norm per HyDE headline
        lists.append([int(i) for i in np.argsort(-(norm01(s_raw) + norm01(s_hyde)) * fr, kind="stable")[:TOP_EMB]])
        del m
    return lists


# ---------------- 5. LLM picks + fusion ----------------
def pick(model, company, line, items, cand):
    lines = "\n".join(f"{i} | {items[i]['date'][:16]} | {', '.join(items[i]['outlets'][:3])} | {items[i]['title']}" for i in cand)
    p = (f"Сегодня {datetime.date.today().isoformat()}. Компания: «{company}». Сфера анализа бизнеса: «{line}».\n"
         "Ниже список российских новостей (id | дата | источники | заголовок). Новости о самой компании исключены: ищи ВНЕШНИЕ факторы. "
         f"Выбери {TOP_OUT} самых полезных, релевантных и интересных для анализа руководителем этой сферы: и прямое влияние, и непрямое "
         "(конкуренты, заменители, регулирование, поставщики, технологии, макро, риски и возможности). Предпочитай разнообразие тем и свежесть.\n"
         f"Верни ТОЛЬКО JSON {{\"top\": [{{\"id\": <число>}}]}} ровно {TOP_OUT} элементов по убыванию полезности.\n\n" + lines)
    ok = set(cand)
    top = chat_json(model, p, "top")["top"]
    return [int(e["id"]) for e in top if isinstance(e, dict) and str(e.get("id", "")).isdigit() and int(e["id"]) in ok]


def fuse(lists, items):
    sc = collections.defaultdict(float)
    for lst in lists:
        for r, i in enumerate(lst, 1): sc[i] += 1 / (RRF_K + r)
    for i in sc:  # small bonus for cross-source corroboration, then freshness
        it = items[i]
        sc[i] = (sc[i] + 0.01 * min(len(it["outlets"]) - 1, 3) + (0.03 if len(it["methods"]) > 1 else 0)) * fresh(age_days(it["date"]))
    return sorted(sc, key=lambda i: -sc[i])[:TOP_OUT], sc


def step(path, fn, ttl=None):
    if os.path.exists(path) and (ttl is None or time.time() - os.path.getmtime(path) < ttl): return json.load(open(path, encoding="utf-8"))
    d = fn(); json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1); return d


def run(company, line):
    slug = re.sub(r"\W+", "_", company.lower()) + "__" + re.sub(r"\W+", "_", line.lower())
    d = os.path.join(HERE, "out", slug); os.makedirs(d, exist_ok=True)
    rf = f"{d}/result.json"
    if os.path.exists(rf) and time.time() - os.path.getmtime(rf) < CACHE_TTL: return json.load(open(rf, encoding="utf-8"))  # whole run cached
    t0 = time.time(); log = lambda *a: print(f"[{time.time() - t0:5.0f}s]", *a, flush=True)
    queries = step(f"{d}/queries.json", lambda: gen_queries(company, line))
    log("queries:", sum(len(v) for v in queries.values()))
    corpus = step(f"{d}/corpus.json", lambda: (lambda pool: (lambda r: {"raw": len(pool), "own_removed": r[1], "items": r[0]})(dedup_filter(pool, company)))(collect(queries, d)), CACHE_TTL)
    items = corpus["items"]
    log(f"news: raw {corpus['raw']}, unique {len(items)}, own removed {corpus['own_removed']}")
    if len(items) < TOP_OUT: raise SystemExit("too few news collected")
    headlines = step(f"{d}/hyde.json", lambda: {"headlines": hyde(company, line)})["headlines"]
    lists = embed_lists(items, queries, headlines)
    cand = list(dict.fromkeys(i for l in zip(*lists) for i in l))[:MAX_CAND]  # interleave so both embedders survive the cap
    log("candidates:", len(cand))
    with ThreadPoolExecutor(len(PICK_MODELS)) as ex:
        picks = dict(zip(PICK_MODELS, ex.map(lambda m: pick(PICK_MODELS[m], company, line, items, cand), PICK_MODELS)))
    final, sc = fuse(list(picks.values()), items)
    votes = {i: [m for m, l in picks.items() if i in l] for i in final}
    res = {"company": company, "line": line, "date": datetime.date.today().isoformat(), "cost": round(COST[0], 2),
           "top": [{**items[i], "score": round(sc[i], 4), "voted_by": votes[i]} for i in final], "picks": picks}
    json.dump(res, open(f"{d}/result.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    md = [f"# {company} — {line}", f"{res['date']} · {len(items)} уникальных новостей · стоимость LLM (по usage.cost) ≈ {res['cost']}\n"]
    md += [f"{n}. [{it['title']}]({it['link']}) — {', '.join(it['outlets'][:2])}, {it['date'][:16]}, голоса: {','.join(it['voted_by'])}" for n, it in enumerate(res["top"], 1)]
    open(f"{d}/digest.md", "w", encoding="utf-8").write("\n".join(md) + "\n")
    log(f"done -> {d}/digest.md, LLM cost {COST[0]:.2f}")
    return res


if __name__ == "__main__":
    if len(sys.argv) != 3: raise SystemExit(__doc__)
    run(sys.argv[1], sys.argv[2])
