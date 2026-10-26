"""Benchmark of the region signal and of the regional mix by company size (locality) in dense_xquad (see region-boost.md). Paths are arguments; S = a scratch folder.
1. sample  (host, uv run):                      python news_search/benchmarks/region_boost_bench.py sample articles.jsonl S/sample.json
   label   (agents container, PYTHONPATH=/app): python region_boost_bench.py label S/sample.json S/labels.json
           an LLM names the region of ~300 articles of the regional dataset (the reference for the detector)
2. detect  (host, uv run):                      python news_search/benchmarks/region_boost_bench.py detect articles.jsonl S/labels.json
           precision / recall of outlet region, names in the text, and both
3. run     (news_search container, PYTHONPATH=/app): python region_boost_bench.py run articles.jsonl profiles.json S/runs.jsonl
           dense_xquad for every profile and NONLOCAL_WEIGHT (profiles carry their locality); the corpus = Postgres corpus + the
           regional dataset (aids shifted by OFFSET); queries, needs and HyDE are generated once per profile, all profiles in parallel
4. judge   (agents container): python region_boost_bench.py judge profiles.json S/runs.jsonl S/judged.json
           blind: per profile the union of every variant's top-10, shuffled; relevance 0/1/2 and own / other region / federal / foreign
5. report  (host): python news_search/benchmarks/region_boost_bench.py report profiles.json S/runs.jsonl S/judged.json"""
import json
import math
import os
import random
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))  # the repo root on the host
OFFSET = 10_000_000  # dataset aids are shifted so they never clash with the local corpus
WEIGHTS = (None, 0.25, 0.5, 1.0)  # NONLOCAL_WEIGHT of the run; None = search without locality (the baseline)
LARGE = 0.2  # profiles with locality below this are "large" in the report
K, BATCH = 10, 40
LABEL = """Для каждой новости определи, к какому месту она относится. Варианты: название региона России из списка; «федеральная» — общероссийская новость или новость про всю страну; «зарубежная».
Регион ставь, только если событие происходит в регионе или касается его властей, компаний, жителей; место редакции не считается.
Регионы: {regions}
Новости (номер | издание | заголовок | текст):
{lines}
Верни ТОЛЬКО JSON {{"labels": {{"номер": ["регион или «федеральная» или «зарубежная»", ...]}}}} для всех номеров."""
JUDGE = """Ты оцениваешь новости для руководителя. Компания: «{company}». Регион компании: «{region}». Сфера, за которую он отвечает: «{line}».
Для каждой новости дай две оценки:
- grade: 2 — прямо влияет на его решения (издержки, спрос, кредит, налоги, регулирование, поставщики, кадры, его регион); 1 — косвенно полезна, общий фон; 0 — не относится;
- place: own — про регион компании; other — про другой регион России; federal — общероссийская; foreign — зарубежная.
Новости (номер | дата | заголовок | аннотация):
{lines}
Верни ТОЛЬКО JSON {{"news": {{"номер": {{"grade": 0, "place": "own"}}, ...}}}} для всех номеров."""


def load_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def ask(prompt, model, max_tokens=16000):
    from agents import app  # the gateway of agents/app.py (approved models only)
    for _ in range(3):
        text, usage = app.chat(model, prompt, max_tokens)
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            try:
                return json.loads(match.group(0)), float(usage.get("cost") or 0)
            except json.JSONDecodeError:
                pass
    raise RuntimeError("no JSON from the model")


def sample(articles):
    """~300: 150 of regional outlets and 150 federal ones, half of them naming a place (the hard cases for the name detector)."""
    from news_search.region import RegionIndex
    rng, idx = random.Random(0), RegionIndex()
    regional = [a for a in articles if a.get("source_region")]
    federal = [a for a in articles if not a.get("source_region")]
    named = [a for a in federal if idx.find(a["title"] + " " + (a.get("text") or "")[:300])]
    rest = [a for a in federal if a not in named]
    return rng.sample(regional, min(150, len(regional))) + rng.sample(named, min(75, len(named))) + rng.sample(rest, min(75, len(rest)))


def write_sample(articles_path, out_path):
    with open("news_search/regions.json", encoding="utf-8") as f:
        regions = sorted(json.load(f)["regions"])
    json.dump({"regions": regions, "articles": sample(load_jsonl(articles_path))}, open(out_path, "w"), ensure_ascii=False)


def label(sample_path, out_path):
    data = load_json(sample_path)
    regions, picked, out, cost = data["regions"], data["articles"], {}, 0.0
    for b in range(0, len(picked), BATCH):
        part = picked[b:b + BATCH]
        lines = "\n".join(f"{i} | {a['outlet']} | {a['title']} | {(a.get('text') or '')[:300]}" for i, a in enumerate(part))
        # Gemma: DeepSeek spent ~7.7k reasoning tokens per 10 articles (0.56 per batch) and ran out of room on 40
        answer, c = ask(LABEL.format(regions=", ".join(regions), lines=lines), "google/gemma-4-26b-a4b-it", 4000)
        cost += c
        for i, names in answer["labels"].items():
            out[part[int(i)]["aid"]] = names if isinstance(names, list) else [names]
        print(f"labelled {len(out)}/{len(picked)}, cost {cost:.3f}", file=sys.stderr)
    json.dump(out, open(out_path, "w"), ensure_ascii=False)


def detect(articles_path, labels_path):
    from news_search.region import RegionIndex
    idx, labels = RegionIndex(), json.load(open(labels_path))
    known = {name[1] for name in idx.names}
    by_aid = {str(a["aid"]): a for a in load_jsonl(articles_path)}
    for name, pick in (("outlet", lambda a: {idx.outlets[a["source_id"]]} if a["source_id"] in idx.outlets else set()),
                       ("names", lambda a: idx.find(a["title"] + " " + (a.get("text") or "")[:300])),
                       ("union", lambda a: idx.find(a["title"] + " " + (a.get("text") or "")[:300]) | ({idx.outlets[a["source_id"]]} if a["source_id"] in idx.outlets else set())),
                       ("of()", lambda a: idx.of({"aid": a["aid"], "title": a["title"], "summary": (a.get("text") or "")[:300], "source": a["source_id"]}))):
        tp = fp = fn = 0
        for aid, truth in labels.items():
            truth = {t for t in truth if t in known}
            got = pick(by_aid[aid])
            tp, fp, fn = tp + len(got & truth), fp + len(got - truth), fn + len(truth - got)
        print(f"{name:7} precision {tp / max(tp + fp, 1):.2f} recall {tp / max(tp + fn, 1):.2f} (tp {tp}, fp {fp}, fn {fn})")


def run(articles_path, profiles_path, out_path):
    import os
    import shutil
    from news_search import NewsSearch, postgres_corpus
    from news_search.cache import MemoryCache
    from agents.client import Agents
    from email.utils import format_datetime
    import datetime
    extra = [{"aid": OFFSET + a["aid"], "title": a["title"], "link": a["url"], "outlet": a["outlet"], "summary": (a.get("text") or "")[:300],
              "source": a["source_id"], "date": format_datetime(datetime.datetime.fromisoformat(a["published_at"])) if a.get("published_at") else ""}
             for a in load_jsonl(articles_path)]
    base = postgres_corpus(os.environ["DATABASE_URL"])
    data = "/data/region_bench"  # its own folder in the search_data volume: survives a rebuild, never mixed with the service cache
    os.makedirs(data, exist_ok=True)
    if not os.path.exists(f"{data}/vectors_bgem3.npz"):  # a copy: the dataset's vectors never enter the service's cache
        shutil.copy("/data/vectors_bgem3.npz", f"{data}/vectors_bgem3.npz")
    cache = MemoryCache()
    s = NewsSearch(lambda days: base(days) + extra, Agents(), data, cache=cache)
    profiles = load_json(profiles_path)
    from concurrent.futures import ThreadPoolExecutor  # the LLM steps of every profile at once; ranking below is sequential
    steps = [(p, name) for p in profiles for name in ("queries", "needs", "hyde")]
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda job: s._cached(s.run_key(job[0]["company"], job[0]["line"], job[0]["region"]), job[1], lambda: s.agents.run(
            job[1], dict(company=job[0]["company"], line=job[0]["line"], region=job[0]["region"]))), steps))
    print(f"LLM steps done, cost {s.agents.cost:.3f}", file=sys.stderr)
    for p, prof in enumerate(profiles):
        for w in WEIGHTS:
            if w is not None:
                s.nonlocal_weight = w
            res = s.search(prof["company"], prof["line"], prof["region"], "dense_xquad", anonymised=True,
                           locality=None if w is None else prof["locality"])
            for key in [k for k in cache.items if k[1].startswith("result_")]:
                del cache.items[key]
            local = s.in_region([{"aid": it["aid"], "title": it["title"], "summary": it.get("summary", ""), "source": source_of(it, extra)}
                                 for it in res["top"]], prof["region"])
            row = {"profile": p, "weight": w, "locality": prof["locality"], "detected": local[:30].tolist(),
                   "top": [{k: it.get(k) for k in ("aid", "title", "date", "outlet", "summary")} for it in res["top"]]}
            with open(out_path, "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(f"profile {p} weight {w}: detected regional in top-10 {int(sum(local[:K]))}", file=sys.stderr)


def source_of(item, extra, _ids={}):
    if not _ids:
        _ids.update({e["aid"]: e["source"] for e in extra})
    return _ids.get(item["aid"])


def load_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def judge(profiles_path, runs_path, out_path):
    sys.path.insert(0, "/app")
    profiles, runs, out = load_json(profiles_path), load_jsonl(runs_path), []
    for p, prof in enumerate(profiles):
        pool = {it["aid"]: it for r in runs if r["profile"] == p for it in r["top"][:K]}
        aids = sorted(pool)
        random.Random(p).shuffle(aids)
        lines = "\n".join(f"{i} | {str(pool[a]['date'])[:16]} | {pool[a]['title']} | {(pool[a].get('summary') or '')[:300]}" for i, a in enumerate(aids))
        answer, cost = ask(JUDGE.format(company=prof["company"], region=prof["region"], line=prof["line"], lines=lines), "moonshotai/kimi-k2.6")
        out.append({"profile": p, "cost": cost, "news": {aids[int(i)]: v for i, v in answer["news"].items()}})
        print(f"profile {p}: judged {len(answer['news'])}/{len(aids)}, cost {cost:.3f}", file=sys.stderr)
    json.dump(out, open(out_path, "w"), ensure_ascii=False)


def report(profiles_path, runs_path, judged_path):
    profiles, runs, judged = load_json(profiles_path), load_jsonl(runs_path), load_json(judged_path)
    marks = {(j["profile"], int(a)): v for j in judged for a, v in j["news"].items()}
    dcg = lambda xs: sum((2 ** x - 1) / math.log2(i + 2) for i, x in enumerate(xs))
    table = {}
    for r in runs:
        m = [marks.get((r["profile"], it["aid"]), {"grade": 0, "place": "?"}) for it in r["top"][:K]]
        g = [x["grade"] for x in m]
        ideal = sorted((v["grade"] for (p, _), v in marks.items() if p == r["profile"]), reverse=True)[:K]
        row = (dcg(g) / max(dcg(ideal), 1e-9), sum(g) / K, sum(x["place"] == "own" for x in m), sum(x["place"] == "other" for x in m),
               sum(x["place"] == "federal" for x in m), sum(r["detected"][:K]))
        size = "large" if r["locality"] < LARGE else "small"
        table.setdefault((size, str(r["weight"])), []).append(row)
        print(f"{profiles[r['profile']]['region'][:22]:22} loc {r['locality']:<4} weight {str(r['weight']):<4} nDCG {row[0]:.3f} grade {row[1]:.2f} own {row[2]} other {row[3]} "
              f"federal {row[4]} detected {row[5]}")
    print("\nmean by size and weight: nDCG | grade | own | other region | federal | detected own")
    for (size, w), rows in sorted(table.items()):
        print(size, w, len(rows), " ".join(f"{sum(x[i] for x in rows) / len(rows):.2f}" for i in range(6)))


if __name__ == "__main__":
    {"sample": write_sample, "label": label, "detect": detect, "run": run, "judge": judge, "report": report}[sys.argv[1]](*sys.argv[2:])
