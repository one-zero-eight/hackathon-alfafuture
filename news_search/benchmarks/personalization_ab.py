"""Offline A/B: full company profile against the same profile with one parameter removed.

Search is stem overlap of the profile text with headlines. Issue #16 is still open and the
news database is not reachable from here, so this is the headline search the issue allows
until the collector cards exist. dense_xquad is the backend default and is not what this run measures.

Usage:
  PYTHONPATH=. uv run python news_search/benchmarks/personalization_ab.py CARDS.jsonl [COMPANY.csv] [--judge 8]
"""
import csv
import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

from news_search.levels import diversity, news_level, overlap_at_k, rank_corr, top_ids, zone_of

LEVELS = ("same_region", "other_region", "federal", "international")
# Every column the issue names, plus the branch file and the payment file. One A/B drops exactly one of these.
FIELDS = ("okved", "region", "city", "workers_fns", "workers_spark", "age", "revenue", "org_type", "okfs",
          "eco", "negative", "cl_type", "products", "fts", "factoring", "group", "payments", "branch_rc", "branch_city")
K = 10


def load_news(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        card = json.loads(line)
        rows.append({"sid": card["sid"], "event": card.get("event") or "", "region": card.get("region") or [],
                     "okved": card.get("okved") or []})
    return rows


def load_companies(path: Path) -> list[dict]:
    out = []
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            try:
                revenue = float(row.get("REVENUE_COMPANY") or 0)
            except ValueError:
                revenue = 0
            code = (row.get("MAINOKVED_CODE") or "").split(".")[0]
            try:
                section_n = int(code)
            except ValueError:
                section_n = -1
            products = []
            for col, name in (("CL_PRODUCT_RKO_MARK", "расчётный счёт"), ("CL_PRODUCT_GAR_MARK", "гарантии"),
                              ("CL_PRODUCT_LOA_MARK", "кредит"), ("CL_PRODUCT_LEA_MARK", "лизинг"),
                              ("CL_PRODUCT_DEP_MARK", "депозиты"), ("CL_PRODUCT_ZPP_MARK", "зарплатный проект")):
                if _on(row.get(col)):
                    products.append(name)
            out.append({
                "id": row["SYNTHETIC_U"],
                "okved_code": row.get("MAINOKVED_CODE") or "",
                "okved_name": row.get("MAINOKVED_NAME") or "",
                "section": section_n,
                "region": row.get("REGION") or "",
                "zone": zone_of(row.get("REGION") or ""),
                "city": row.get("CITY") or "",
                "workers_fns": row.get("AMOUNT_WORKERS_FNS_GRADATION") or "",
                "workers_spark": row.get("AMOUNT_WORKERS_SPARK_GRADATION") or "",
                "age": row.get("COMPANY_AGE_YEARS_GRADATION") or "",
                "revenue": revenue,
                "org_type": row.get("ORG_TYPE") or "",
                "okfs": row.get("OKFS_NAME") or "",
                "eco": row.get("ECO_MARK_LABEL") or "",
                "negative": "негативная отметка" if _on(row.get("NEGATIVEMARK")) else "",
                "cl_type": row.get("CL_TYPE") or "",
                "products": ", ".join(products),
                "fts": ((row.get("FTS_COUNTRY_NAME") or "").strip() if _on(row.get("FTS_FLAG")) else ""),
                "factoring": "факторинг" if _on(row.get("FACTORING_MARK")) else "",
                "group": row.get("GROUP_ID") or "",
                "payments": "",
                "branch_rc": "",
                "branch_city": "",
            })
    return out


def _on(value) -> bool:
    try:
        return float(value or 0) > 0
    except ValueError:
        return False


def attach_branches(companies: list[dict], path: Path) -> None:
    """City and regional center of the linked person. The file is people, not companies, so a company can have several."""
    want = {c["id"] for c in companies}
    rc, city = defaultdict(Counter), defaultdict(Counter)
    if not path.is_file():
        return
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            uid = row.get("SYNTHETIC_U")
            if uid not in want:
                continue
            if row.get("RC_NAME"):
                rc[uid][row["RC_NAME"]] += 1
            if row.get("CITY_NAME"):
                city[uid][row["CITY_NAME"]] += 1
    for company in companies:
        if rc[company["id"]]:
            company["branch_rc"] = rc[company["id"]].most_common(1)[0][0]
        if city[company["id"]]:
            company["branch_city"] = city[company["id"]].most_common(1)[0][0]


def attach_payments(companies: list[dict], path: Path, names: dict[str, str]) -> None:
    """Top outside payer's industry, the same fact the company card already shows."""
    want = {c["id"] for c in companies}
    incoming = defaultdict(lambda: defaultdict(float))
    if not path.is_file():
        return
    with path.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f, delimiter=";"):
            payer, ben = row.get("PAYER"), row.get("BENEFICIARY")
            if ben not in want or payer == ben:
                continue
            try:
                amount = float(row.get("PAY_AMT") or 0)
            except ValueError:
                continue
            incoming[ben][payer] += amount
    for company in companies:
        payers = incoming.get(company["id"])
        if not payers:
            continue
        top = max(payers, key=payers.get)
        company["payments"] = names.get(top) or ""


def section_letter(n: int) -> str:
    bounds = ((3, "A"), (9, "B"), (33, "C"), (35, "D"), (39, "E"), (43, "F"), (47, "G"), (53, "H"), (56, "I"),
              (63, "J"), (66, "K"), (68, "L"), (75, "M"), (82, "N"), (84, "O"), (85, "P"), (88, "Q"), (93, "R"), (99, "U"))
    return next((letter for high, letter in bounds if n <= high), "")


def text_of(company: dict, drop: str = "") -> str:
    """The profile text the search would see. drop removes one parameter, which is the B side of the A/B."""
    bits = {
        "okved": f"ОКВЭД {company['okved_code']} {company['okved_name']}",
        "region": company["region"],
        "city": company["city"],
        "workers_fns": f"сотрудников {company['workers_fns']}" if company["workers_fns"] else "",
        "workers_spark": f"сотрудников {company['workers_spark']}" if company["workers_spark"] else "",
        "age": f"возраст {company['age']}" if company["age"] else "",
        "revenue": f"выручка {company['revenue'] / 1e9:.1f} млрд" if company["revenue"] else "",
        "org_type": company["org_type"],
        "okfs": company["okfs"],
        "eco": company["eco"],
        "negative": company["negative"],
        "cl_type": company["cl_type"],
        "products": f"продукты {company['products']}" if company["products"] else "",
        "fts": f"внешняя торговля {company['fts']}" if company["fts"] else "",
        "factoring": company["factoring"],
        "group": f"группа {company['group']}" if company["group"] else "",
        "payments": f"плательщик {company['payments']}" if company["payments"] else "",
        "branch_rc": f"филиал {company['branch_rc']}" if company["branch_rc"] else "",
        "branch_city": f"город филиала {company['branch_city']}" if company["branch_city"] else "",
    }
    return " ".join(text for key, text in bits.items() if text and key != drop)


def industry_news(company: dict, news: list[dict]) -> list[dict]:
    letter = section_letter(company["section"])
    return [it for it in news if letter and letter in it["okved"]]


def shares(company: dict, chosen: list[dict]) -> dict:
    count = Counter(news_level(it["region"], company["zone"]) for it in chosen)
    total = sum(count.values()) or 1
    return {level: count[level] / total for level in LEVELS}


def sample(companies: list[dict], n: int = 48) -> list[dict]:
    """One company from each zone, OKVED class and revenue band, walking the zones in turn."""
    bands = ((15e9, "15+"), (1e9, "1-15"), (0, "<1"))
    buckets = defaultdict(list)
    for company in companies:
        if not company["zone"] or company["section"] < 0:
            continue
        band = next(name for low, name in bands if company["revenue"] >= low)
        buckets[(company["zone"], company["section"], band)].append(company)
    queues = {key: sorted(group, key=lambda c: -c["revenue"]) for key, group in buckets.items()}
    picked = []
    while len(picked) < n and any(queues.values()):
        for key in sorted(queues):
            if queues[key] and len(picked) < n:
                picked.append(queues[key].pop(0))
    return picked


def cover_rare(chosen: list[dict], companies: list[dict]) -> list[dict]:
    """SPARK headcount and factoring are set on a few hundred companies, so a size-stratified 48 misses them."""
    have = {c["id"] for c in chosen}
    extra = []
    for pred in (lambda c: c["workers_spark"], lambda c: c["factoring"]):
        found = sorted((c for c in companies if c["id"] not in have and pred(c)), key=lambda c: -c["revenue"])
        for company in found[:4]:
            extra.append(company)
            have.add(company["id"])
    if not extra:
        return chosen
    return chosen[: len(chosen) - len(extra)] + extra


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def run(news: list[dict], chosen: list[dict], companies: list[dict]) -> dict:
    """A is the full profile text, B is the same text with one field removed. Same headlines both times."""
    by_id = {it["sid"]: it for it in news}
    rows = []
    buckets = {field: {"overlap": [], "rank": [], "div_b": [], "federal_a": [], "federal_b": [], "same_a": [], "same_b": []} for field in FIELDS}
    for company in chosen:
        full_ids = top_ids(text_of(company), news, K)
        full_items = [by_id[sid] for sid in full_ids]
        full_share = shares(company, full_items)
        full_div = diversity(full_items, company["zone"])
        per = {}
        for field in FIELDS:
            if text_of(company, field) == text_of(company):
                continue
            ids = top_ids(text_of(company, field), news, K)
            items = [by_id[sid] for sid in ids]
            got = shares(company, items)
            per[field] = {
                "overlap": overlap_at_k(full_ids, ids, K),
                "rank": rank_corr(full_ids, ids, K),
                "diversity": diversity(items, company["zone"]),
                "titles_a": [it["event"] for it in full_items],
                "titles_b": [it["event"] for it in items],
            }
            buckets[field]["overlap"].append(per[field]["overlap"])
            buckets[field]["rank"].append(per[field]["rank"])
            buckets[field]["div_b"].append(per[field]["diversity"])
            buckets[field]["federal_a"].append(full_share["federal"])
            buckets[field]["federal_b"].append(got["federal"])
            buckets[field]["same_a"].append(full_share["same_region"])
            buckets[field]["same_b"].append(got["same_region"])
        rows.append({"id": company["id"], "zone": company["zone"], "text": text_of(company), "diversity": full_div, "fields": per})
    table = {}
    for field in FIELDS:
        b = buckets[field]
        table[field] = {
            "n": len(b["overlap"]),
            "overlap": _mean(b["overlap"]),
            "rank": _mean(b["rank"]),
            "diversity_full": _mean([row["diversity"] for row in rows if field in row["fields"]]),
            "diversity_ablated": _mean(b["div_b"]),
            "federal_full": _mean(b["federal_a"]),
            "federal_ablated": _mean(b["federal_b"]),
            "same_region_full": _mean(b["same_a"]),
            "same_region_ablated": _mean(b["same_b"]),
        }
    large = [c for c in companies if c["revenue"] >= 15e9 and c["zone"]]
    large_shares = [shares(c, industry_news(c, news)) for c in large]
    return {
        "n": len(rows), "rows": rows, "table": table, "k": K,
        "diversity_full": _mean([row["diversity"] for row in rows]),
        "large_n": len(large_shares),
        "large_shares": {level: sum(s[level] for s in large_shares) / len(large_shares) for level in LEVELS} if large_shares else {},
        "unmapped": sum(1 for c in companies if c["region"] and not c["zone"]),
        "retrieval_tokens": 0,
    }


def judge_pair(company_text: str, field: str, titles_a: list[str], titles_b: list[str]) -> tuple[str, dict]:
    """Qwen, a different model from the one that would write the page. Returns A, B or same."""
    from agents.app import QWEN, chat

    def lines(titles):
        return "\n".join(f"{i}. {t}" for i, t in enumerate(titles, 1)) or "(пусто)"

    prompt = (
        "Сравни два списка новостей для одной компании. Список A собран по полному профилю. "
        f"Список B собран по тому же профилю без поля «{field}».\n"
        f"Компания: {company_text}\n\nСписок A:\n{lines(titles_a)}\n\nСписок B:\n{lines(titles_b)}\n\n"
        'Какой список полезнее для решений этой компании? Ответь только JSON: {"better": "A"} или {"better": "B"} или {"better": "same"}.'
    )
    text, usage = chat(QWEN, prompt, max_tokens=2000)
    found = re.search(r'"better"\s*:\s*"(A|B|same)"', text)
    better = found.group(1) if found else "same"
    return better, usage or {}


def judge(report: dict, n_companies: int, log_path: Path) -> dict:
    """Judge only fields that move the top-K. A means the full profile was more relevant, so the field helped.

    Each vote is appended to log_path, so a stopped run continues from the pairs already judged.
    """
    # A list that barely moves does not need a judge: relevance is the same. 0.85 is the cutoff used in the report.
    moving = [field for field, row in report["table"].items() if row["overlap"] is not None and row["overlap"] < 0.85]
    done = {}
    if log_path.is_file():
        for line in log_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                done[(row["id"], row["field"])] = row
    votes = {field: Counter() for field in moving}
    tokens, calls, cost = 0, 0, 0.0
    with log_path.open("a", encoding="utf-8") as log:
        for field in moving:
            have = [company for company in report["rows"] if field in company["fields"]][:n_companies]
            for company in have:
                got = company["fields"][field]
                saved = done.get((company["id"], field))
                if saved:
                    better, usage = saved["better"], saved.get("usage") or {}
                else:
                    better, usage = judge_pair(company["text"], field, got["titles_a"], got["titles_b"])
                    log.write(json.dumps({"id": company["id"], "field": field, "better": better,
                                          "usage": {"total_tokens": int((usage or {}).get("total_tokens") or 0),
                                                    "cost": float((usage or {}).get("cost") or 0)}}, ensure_ascii=False) + "\n")
                    log.flush()
                votes[field][better] += 1
                calls += 1
                tokens += int((usage or {}).get("total_tokens") or 0)
                cost += float((usage or {}).get("cost") or 0)
                print(f"judge {company['id']} {field} {better}", file=sys.stderr, flush=True)
    summary = {}
    for field, counts in votes.items():
        total = sum(counts.values()) or 1
        summary[field] = {"A": counts["A"], "B": counts["B"], "same": counts["same"], "full_better": counts["A"] / total}
    return {"companies": n_companies, "calls": calls, "tokens": tokens, "cost": round(cost, 4), "votes": summary}


def _load_env() -> None:
    path = Path(".env")
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    judge_n = 0
    if "--judge" in sys.argv:
        i = sys.argv.index("--judge")
        judge_n = int(sys.argv[i + 1])
    cards = Path(args[0])
    root = Path("external-docs/company")
    companies = Path(args[1] if len(args) > 1 else root / "df_Uid_data_hack.csv")
    news = load_news(cards)
    book = load_companies(companies)
    chosen = cover_rare(sample(book), book)
    names = {c["id"]: c["okved_name"] for c in book}
    attach_branches(chosen, root / "df_Fid_Uid_link_hack.csv")
    attach_payments(chosen, root / "df_Uid_payment_hack.csv", names)
    report = run(news, chosen, book)
    judged = None
    if judge_n:
        _load_env()
        judged = judge(report, judge_n, Path("news_search/benchmarks/.personalization-ab-judge.jsonl"))
    public_rows = []
    for field, row in report["table"].items():
        public_rows.append({"field": field, **{k: (round(v, 3) if isinstance(v, float) else v) for k, v in row.items()}})
    out = {
        "n": report["n"], "k": report["k"], "news": len(news), "companies": len(book),
        "unmapped_regions": report["unmapped"], "retrieval_tokens_per_profile": 0,
        "diversity_full": None if report["diversity_full"] is None else round(report["diversity_full"], 3),
        "large_n": report["large_n"], "large_industry_shares": {k: round(v, 3) for k, v in report["large_shares"].items()},
        "table": public_rows, "judge": judged,
    }
    print(json.dumps(out, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
