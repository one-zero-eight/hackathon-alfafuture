"""News level (own region, another region, federal, international) and which company parameter moves it.

The week cards label a story russia_all, foreign, or one macro-zone. Appendix 1 has no market cap;
revenue is the size field. A parameter "moves the level" only when dropping it from the profile text
changes which headlines a stem match would keep.
"""
import re

ZONES = ("moscow", "northwest", "south", "volga", "ural", "siberia_fe")
# First matching hint wins. Hints are substrings of the region name in the company file.
_HINTS = (
    ("moscow", ("москва", "московск")),
    ("central", ("воронеж", "ярослав", "белгород", "липецк", "тульск", "калуж", "тверск", "рязан", "иванов", "смолен", "владимир", "брянск", "тамбов", "орлов", "курск")),
    ("northwest", ("петербург", "ленинград", "карел", "коми", "архангел", "вологод", "мурман", "новгород", "псков", "калининград", "ненец")),
    ("south", ("краснодар", "ростов", "волгоград", "астрахан", "адыге", "крым", "севастопол", "ставропол", "дагестан", "чечен", "ингуш", "кабардин", "карача", "осетия", "калмык", "донецк", "луганск", "сириус")),
    ("volga", ("татарстан", "башкортостан", "нижегород", "самар", "саратов", "пермск", "оренбург", "удмурт", "чуваш", "марий", "мордов", "киров", "пензен", "ульянов")),
    ("ural", ("свердлов", "челябин", "тюмен", "курган", "ханты", "ямало", "югра")),
    ("siberia_fe", ("новосибир", "краснояр", "иркут", "кемеров", "омск", "томск", "алтай", "хакас", "тыва", "бурят", "забайкал", "примор", "хабаров", "якут", "саха", "камчат", "сахалин", "магадан", "амурск", "чукот", "еврейск")),
)


def zone_of(region: str) -> str:
    """Company region from the bank file to the same macro-zone the news cards use. Empty if it is not one of them."""
    name = (region or "").lower().replace("ё", "е")
    for zone, hints in _HINTS:
        if any(h in name for h in hints):
            return zone
    return ""


def news_level(regions: list, company_zone: str) -> str:
    """same_region, other_region, federal or international. A named zone beats the federal label."""
    named = [r for r in regions or [] if r in ZONES]
    if company_zone and company_zone in named:
        return "same_region"
    if named:
        return "other_region"
    if "russia_all" in (regions or []):
        return "federal"
    if "foreign" in (regions or []):
        return "international"
    return "other"


def stems(text: str) -> set[str]:
    words = re.findall(r"[a-zа-яё0-9]+", (text or "").lower().replace("ё", "е"))
    return {w[:5] for w in words if len(w) > 3}


def top_ids(profile_text: str, news: list[dict], k: int = 20) -> list[str]:
    """Headlines with the most shared stems, stable by id. The stand-in for a search when the model is not called."""
    want = stems(profile_text)
    scored = []
    for it in news:
        shared = len(want & stems(it.get("event") or ""))
        if shared:
            scored.append((-shared, it["sid"]))
    scored.sort()
    return [sid for _, sid in scored[:k]]


def jaccard(a: list, b: list) -> float:
    x, y = set(a), set(b)
    return len(x & y) / len(x | y) if x or y else 1.0


def overlap_at_k(full: list, ablated: list, k: int = 10) -> float:
    """Share of the full top-K that is still in the ablated top-K. 1 means the parameter did not change the set."""
    if k <= 0:
        return 1.0
    return len(set(full[:k]) & set(ablated[:k])) / k


def rank_corr(full: list, ablated: list, k: int = 10) -> float:
    """Spearman of the full top-K against its places in the ablated list. A missing item is ranked just after K."""
    ids = full[:k]
    n = len(ids)
    if n < 2:
        return 1.0
    place = {sid: i for i, sid in enumerate(ablated[:k])}
    xs = list(range(n))
    ys = [place.get(sid, k) for sid in ids]
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    if not den:
        return 1.0 if ids == list(ablated[:n]) else 0.0
    return num / den


def diversity(chosen: list[dict], company_zone: str) -> float:
    """How many news levels the top contains, from 0 to 1. Four levels exist: own region, other, federal, abroad."""
    if not chosen:
        return 0.0
    levels = {news_level(it.get("region") or [], company_zone) for it in chosen}
    return len(levels) / 4
