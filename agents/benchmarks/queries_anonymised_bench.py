"""Benchmark of queries_anonymised against queries for anonymised bank records (#37), see queries-anonymised.md.
1. Profiles (host, needs the bank CSVs): descriptions from backend.companies.CompanyBook -> profiles.json (see the .md for the ids).
2. Search, inside the news_search container (corpus, vector cache, agents service); needs and HyDE are generated once per profile
   and shared by both variants, so only the queries differ:
     docker cp agents/benchmarks/queries_anonymised_bench.py alfa-news_search-1:/tmp/b.py; docker cp profiles.json alfa-news_search-1:/tmp/
     docker exec -e PYTHONPATH=/app alfa-news_search-1 python /tmp/b.py search /tmp/profiles.json /tmp/runs.jsonl
3. Blind judge (Kimi-K2.6 through the agents gateway), inside the agents container:
     docker exec -e PYTHONPATH=/app alfa-agents-1 python /tmp/b.py judge /tmp/profiles.json /tmp/runs.jsonl > judged.json
4. Report (host): python agents/benchmarks/queries_anonymised_bench.py report profiles.json runs.jsonl judged.json"""

import json
import math
import os
import random
import re
import sys
import time

VARIANTS = (
    "before",
    "after",
)  # before: the named-company prompt `queries`; after: `queries_anonymised`
REGIONAL = ("competitors_direct", "customers", "supply_side", "government")
K, JUDGE_RUNS = 10, 2
GENERIC = {
    "область",
    "области",
    "край",
    "края",
    "республика",
    "республики",
    "город",
    "автономный",
    "округ",
}
JUDGE = """Ты оцениваешь новости для руководителя. Компания (название неизвестно, описание из банковских данных): «{company}». Сфера, за которую он отвечает: «{line}».
Оцени каждую новость по пользе для решений этого руководителя: 2 — прямо влияет на его решения (издержки, спрос, кредит, налоги, регулирование, поставщики, клиенты, кадры, события его региона); 1 — косвенно полезна, общий фон отрасли или экономики; 0 — не относится (в том числе события другого региона, не важные для этой компании).
Новости (номер | дата | заголовок | аннотация):
{lines}
Верни ТОЛЬКО JSON {{"grades": {{"номер": 0|1|2, ...}}}} для всех номеров."""


def region_stems(p):
    """shortcut: a query is regional when it has a 5-letter stem of the region or city name; misses capitals named otherwise
    and abbreviations (СПб, НСО), add them when a profile needs it."""
    words = re.findall(
        r"[а-яё]+", f"{p['region']} {p['city']}".lower().replace("г. ", " ")
    )
    return {w[:5] for w in words if len(w) >= 5 and w not in GENERIC} | (
        {"спб"} if "петербург" in p["region"].lower() else set()
    )


def is_regional(q, stems):
    return any(w[:5] in stems or w in stems for w in re.findall(r"[а-яё]+", q.lower()))


class Shared:
    """Agents client for one variant: needs/HyDE come from the profile's shared store, queries_anonymised maps to queries before."""

    def __init__(self, agents, variant, store):
        self.agents, self.variant, self.store, self.spent = agents, variant, store, {}

    @property
    def cost(self):
        return self.agents.cost

    def run(self, name, data):
        if name in ("needs", "hyde") and name in self.store:
            return self.store[name]
        if name == "queries_anonymised" and self.variant == "before":
            name = "queries"
        c0 = self.agents.cost
        for attempt in range(3):  # the gateway sometimes fails DNS for a moment
            try:
                out = self.agents.run(name, data)
                break
            except Exception as e:
                if attempt == 2:
                    raise
                print(f"retry {name}: {e}", file=sys.stderr)
                time.sleep(30)
        self.spent[name] = round(self.agents.cost - c0, 4)
        if name in ("needs", "hyde"):
            self.store[name] = out
        return out


def search(profiles_path, out_path):
    from news_search import NewsSearch, postgres_corpus
    from news_search.cache import MemoryCache
    from agents.client import Agents

    profiles = json.load(open(profiles_path))
    done = (
        {(r["uid"], r["variant"]) for r in map(json.loads, open(out_path))}
        if os.path.exists(out_path)
        else set()
    )
    s = NewsSearch(
        postgres_corpus(os.environ["DATABASE_URL"]),
        None,
        os.environ.get("NEWS_SEARCH_DATA", "/data"),
    )  # one bge-m3 for all runs
    for p in profiles:
        store = {}
        for variant in VARIANTS:
            if (p["uid"], variant) in done:
                continue
            client = Shared(Agents(), variant, store)
            s.agents, s.cache = client, MemoryCache()
            res = s.search(
                p["company"], p["line"], p["region"], "dense_xquad", anonymised=True
            )
            queries = s.cache.get(
                s.run_key(p["company"], p["line"], p["region"]), "queries"
            )
            row = {
                "uid": p["uid"],
                "variant": variant,
                "spent": client.spent,
                "queries": queries,
                "top": [
                    {
                        k: it.get(k)
                        for k in ("aid", "title", "date", "outlets", "summary")
                    }
                    for it in res["top"]
                ],
            }
            with open(out_path, "a") as f:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
            print(p["uid"], variant, client.spent, file=sys.stderr)


def judge(profiles_path, runs_path):
    from agents import app

    profiles, runs, out = (
        json.load(open(profiles_path)),
        list(map(json.loads, open(runs_path))),
        [],
    )
    for n, p in enumerate(profiles):
        pool = {
            it["aid"]: it for r in runs if r["uid"] == p["uid"] for it in r["top"][:K]
        }
        aids = sorted(pool)
        for rep in range(JUDGE_RUNS):
            random.Random(rep * 1000 + n).shuffle(
                aids
            )  # blind: no variant, a different order per run
            lines = "\n".join(
                f"{i} | {str(pool[a]['date'])[:10]} | {pool[a]['title']} | {(pool[a].get('summary') or '')[:300]}"
                for i, a in enumerate(aids)
            )
            text, usage = app.chat(
                "moonshotai/kimi-k2.6",
                JUDGE.format(company=p["company"], line=p["line"], lines=lines),
                16000,
            )
            grades = json.loads(re.search(r"\{.*\}", text, re.S).group(0))["grades"]
            out.append(
                {
                    "uid": p["uid"],
                    "run": rep,
                    "cost": usage.get("cost"),
                    "grades": {aids[int(i)]: int(g) for i, g in grades.items()},
                }
            )
            print(
                p["uid"],
                rep,
                f"{len(grades)}/{len(aids)}",
                usage.get("cost"),
                file=sys.stderr,
            )
    json.dump(out, sys.stdout, ensure_ascii=False)


def report(profiles_path, runs_path, judged_path=None):
    profiles = {p["uid"]: p for p in json.load(open(profiles_path))}
    runs = list(map(json.loads, open(runs_path)))
    mean = {}
    if judged_path:
        grades = {}
        for j in json.load(open(judged_path)):
            for aid, g in j["grades"].items():
                grades.setdefault((j["uid"], int(aid)), []).append(g)
        mean = {k: sum(v) / len(v) for k, v in grades.items()}
        pairs = [v for v in grades.values() if len(v) > 1]
        print(f"judge agreement: {sum(len(set(v)) == 1 for v in pairs)}/{len(pairs)}")
    dcg = lambda xs: sum((2**x - 1) / math.log2(i + 2) for i, x in enumerate(xs))
    total = {v: [] for v in VARIANTS}
    for r in runs:
        p, q = profiles[r["uid"]], r["queries"]
        stems = region_stems(p)
        main = [x for b in REGIONAL for x in q.get(b, [])]
        allq = [x for b, xs in q.items() if b != "company_self" for x in xs]
        row = {
            "regional_share": sum(is_regional(x, stems) for x in main)
            / max(len(main), 1),
            "regional_all": sum(is_regional(x, stems) for x in allq)
            / max(len(allq), 1),
            "self": len(q.get("company_self", [])),
            "word_company": sum(
                "компания" in x.lower().split()
                for x in allq + q.get("company_self", [])
            ),
            "okved_code": sum(
                bool(re.search(r"\d{2}\.\d{2}", x))
                for x in allq + q.get("company_self", [])
            ),
            "queries": len(allq),
            "cost": r["spent"].get("queries", r["spent"].get("queries_anonymised", 0)),
        }
        if mean:
            g = [mean.get((r["uid"], it["aid"]), 0) for it in r["top"][:K]]
            ideal = sorted(
                (v for (u, _), v in mean.items() if u == r["uid"]), reverse=True
            )[:K]
            row.update(ndcg=dcg(g) / dcg(ideal), grade=sum(g) / K)
        total[r["variant"]].append(row)
        print(r["uid"], r["variant"], {k: round(v, 3) for k, v in row.items()})
    for v, rows in total.items():
        print(
            v,
            "mean",
            {k: round(sum(r[k] for r in rows) / len(rows), 3) for k in rows[0]},
        )
    for v in (
        VARIANTS
    ):  # identical queries shared by different companies (outside company_self)
        seen = {}
        for r in runs:
            if r["variant"] == v:
                for x in {
                    x.lower().strip()
                    for b, xs in r["queries"].items()
                    if b != "company_self"
                    for x in xs
                }:
                    seen.setdefault(x, set()).add(r["uid"])
        shared = {x: u for x, u in seen.items() if len(u) > 1}
        print(
            v,
            f"queries shared by 2+ companies: {len(shared)} of {len(seen)}",
            sorted(shared)[:8],
        )
    for uid in profiles:
        a, b = ({it["aid"] for it in r["top"][:K]} for r in runs if r["uid"] == uid)
        print(uid, "top-10 overlap", len(a & b))


if __name__ == "__main__":
    {"search": search, "judge": judge, "report": report}[sys.argv[1]](*sys.argv[2:])
