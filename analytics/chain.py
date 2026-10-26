"""Per-news causal chain: plan -> analytics (IRCoT) -> decision (playbook + TRIZ) -> verification -> page JSON.

One selected news item produces its own analytics widget and its own decision. The page is the set of those chains.
News search is an input, not this module. Every LLM call goes through the agents service (`agents.run(name, input)`).
"""
import datetime
import json
import logging
import os
import re
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from email.utils import parsedate_to_datetime
from pathlib import Path

from analytics.search import Index, stems

log = logging.getLogger("analytics")
ROLES = json.loads((Path(__file__).parent / "data" / "roles.json").read_text(encoding="utf-8"))

# Fixed list: the model may apply these, it may not invent new ones. Business reading, not the engineering original.
MOVES = {
    "предварительное действие": "сделать шаг до того, как условие ухудшится",
    "дробление": "разбить одно действие на части с разными сроками или долями",
    "посредник": "переложить часть риска или операции на уже доступный инструмент банка",
    "заранее подложенная подушка": "заранее зарезервировать покрытие риска",
    "идеальный конечный результат": "как задача решается сама имеющимися ресурсами компании",
}
HORIZON = {"days": "urgent", "weeks": "urgent", "months": "medium_term", "years": "not_urgent"}
ROLE_RU = {"CEO": "Генеральный директор", "CFO": "Финансовый директор",
           "chief_accountant": "Главный бухгалтер", "treasury_head": "Руководитель казначейства"}
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
EVENTS, STEPS = 10, 3  # news analysed per page; analytics iterations per news
TITLE_MAX = 120  # card title length; the cut is on a word boundary, never mid-word unless the first word itself is longer
WORKERS = int(os.environ.get("ANALYTICS_WORKERS", 6))  # news analysed at once; the chain of one news stays sequential (each thought feeds the next search)


def norm(text: str) -> str:
    return " ".join(str(text).split())


def clip_title(text: str, limit: int = TITLE_MAX) -> str:
    """A card title of at most `limit` characters, ending on a word. The ellipsis counts toward the limit."""
    text = norm(text)
    if len(text) <= limit:
        return text
    room = max(1, limit - 1)
    cut = text[:room]
    space = cut.rfind(" ")
    if space > 0:
        cut = cut[:space]
    return cut.rstrip(".,;:—-– ") + "…"


def grounded(evidence: list, blobs: dict) -> list:
    """Keep only citations whose id exists and whose quote is a verbatim fragment of that source."""
    ok = []
    for e in evidence or []:
        blob = blobs.get(e.get("id", ""))
        quote = norm(e.get("quote", ""))
        if blob and quote and quote in blob:
            ok.append({"id": e["id"], "quote": quote})
    return ok


def plan(card: dict | None, profile: dict) -> list[str]:
    """How the event can reach this company. Rules, no LLM call. Without an event card (live news) it is always "direct"."""
    card = card or {}
    kinds, et = [], card.get("event_type")
    if profile.get("okved") in card.get("okved", []):
        kinds.append("direct")
    if et in ("monetary_policy", "fx") and set(profile.get("products", [])) & {"credit", "leasing", "deposits"}:
        kinds.append("product")
    if et == "commodity_prices":
        kinds.append("resource")
    if et in ("sanctions_trade", "fx"):
        kinds.append("trade")
    return kinds or ["direct"]


def _blob(item: dict) -> str:
    return norm(" ".join(str(item.get(k, "")) for k in ("title", "text", "claim", "quote")))


def _show(ids: list, items: dict) -> str:
    return "\n".join(f"[{i}] {items[i].get('title', '')} — {_blob(items[i])[:500]}" for i in ids if i in items)


# ---------------- bank theses ----------------
GENERIC = {"вырос", "роста", "росто", "основ", "показ", "дости", "макси", "уровн", "связа", "объем", "льгот", "значе"}
WEAK = {"число"}
FX = {"долла", "курс", "рубл", "рубля"}
_FX4 = {"рубл", "курс", "долл", "став"}
_THESIS = re.compile(r"alfa:(.+):p(\d+):t\d+")


def bank_related(headline: str, thesis: str) -> bool:
    """A bank thesis is shown only when it shares a real word with the headline, or the same currency move.

    "число" alone does not count: it attached a labour thesis to a headline about the number of firms.
    """
    shared = (set(stems(headline)) & set(stems(thesis))) - GENERIC - WEAK
    if shared:
        return True
    q4 = {w[:4] for w in stems(headline)}
    b4 = {w[:4] for w in stems(thesis)}
    return bool((q4 & b4) & _FX4)


def bank_position(index: Index, event: dict, items: dict, embeds=None) -> dict | None:
    """Alfa thesis for this headline.

    With embeds, the nearest bge-m3 thesis that still shares the headline's subject.
    Without embeds, two shared content words.
    A thesis about another year is dropped in both cases when the overlap is only FX words.
    """
    query = event["title"]
    hits = embeds.search(query, k=1, prefix="alfa:") if embeds else index.search(query, k=1, prefix="alfa:")
    if not hits:
        return None
    item = items[hits[0]]
    quote = norm(item.get("text") or "")
    body = (item.get("title") or "") + " " + quote
    shared = (set(stems(query)) & set(stems(body))) - GENERIC
    years = set(re.findall(r"20\d\d", body)) - set(re.findall(r"20\d\d", query))
    if not quote or quote not in _blob(item) or (years and shared <= FX):
        return None
    if embeds is None and len(shared) < 2:
        return None
    if embeds is not None and not bank_related(query, body):
        return None
    return {"role": "alfa", "thought": item.get("title") or quote, "evidence": [{"id": hits[0], "quote": quote}]}


def alfa_embed(items: dict):
    """bge-m3 over Alfa theses only. None when this page has no theses, so the search stays lexical.

    The encoded string is the claim plus the quote, the same text the comparison scored.
    """
    docs = {i: f"{it.get('claim') or it.get('title') or ''}. {it.get('text') or it.get('quote') or ''}" for i, it in items.items() if str(i).startswith("alfa:")}
    if not docs:
        return None
    from analytics.embed import Bge
    log.info("bge-m3 encodes %d bank theses", len(docs))
    return Bge(docs)


# ---------------- hops ----------------
def hop2(agents, event: dict, items: dict, index: Index, ctx: dict, kinds: list[str], embeds=None, first_hits: list[str] = ()) -> list[dict]:
    """Up to STEPS iterations: write one thought, then search again with that thought. Ungrounded thoughts are dropped.

    first_hits: related news (pairs from the search) that are always shown to the writer in the first iteration.
    """
    blobs = {i: _blob(it) for i, it in items.items()}
    notes, seen = [], {event["id"]}
    thought = event["title"]
    for n in range(STEPS):
        hits = (list(first_hits) if n == 0 else []) + index.search(thought, k=2, prefix="alfa:") + index.search(thought, k=3, exclude=seen)
        hits = list(dict.fromkeys(h for h in hits if h != event["id"]))
        seen.update(hits)
        ans = agents.run("analytics_step", {
            "company": ctx["company"], "facts": ctx["facts"], "sphere": ctx["sphere"], "kinds": kinds,
            "title": event["title"], "text": event.get("text", ""), "thoughts": [x["thought"] for x in notes],
            "materials": _show([event["id"], *hits], items)})
        ev = grounded(ans.get("evidence"), blobs)
        if not ans.get("relevant") or not ev:
            break
        notes.append({"thought": ans.get("thought", ""), "evidence": ev})
        thought = ans.get("thought") or thought
        if ans.get("done"):
            break
    bank = bank_position(index, event, items, embeds)
    already = {e["id"] for note in notes for e in note["evidence"]}
    if bank and bank["evidence"][0]["id"] not in already:
        notes.insert(0, bank)
    return notes


def hop3(agents, event: dict, notes: list[dict], role: dict, triz: bool, sphere: str = "") -> dict | None:
    ans = agents.run("decision", {"sphere": sphere, "role": role, "moves": MOVES if triz else {}, "title": event["title"], "notes": notes})
    if not ans.get("title") or not ans.get("text"):
        return None
    if ans.get("move") not in MOVES:
        ans["move"] = None
    ans["risks"] = [r for r in ans.get("risks") or []
                    if isinstance(r, dict) and isinstance(r.get("probability"), int) and isinstance(r.get("impact"), int)
                    and 1 <= r["probability"] <= 4 and 1 <= r["impact"] <= 4][:4]
    return ans


def verify(agents, claims: list[dict]) -> set[int]:
    """Returns indexes the other model marks unsupported. The caller already dropped bad quotes.

    One call for every claim makes this model spend the whole token cap on reasoning, so claims go in fours.
    A failed batch is kept: the quotes were already checked against the source text.
    """
    def batch(start: int):
        try:
            return start, agents.run("verify", {"claims": claims[start:start + 4]})
        except RuntimeError as e:
            log.warning("verify %d failed: %s", start, e)
            return start, {}

    bad = set()
    with ThreadPoolExecutor(max(1, WORKERS)) as pool:
        for start, ans in pool.map(batch, range(0, len(claims), 4)):
            for j, verdict in enumerate(ans.get("verdicts") or []):
                if verdict != "supported":
                    bad.add(start + j)
    return bad


def _years(text: str) -> set[str]:
    return set(re.findall(r"20\d\d", text or ""))


def _analysis_text(notes: list[dict], event: dict) -> str:
    """Bank thesis and model conclusion stay separate. A year clash is written out and is not treated as the current view."""
    parts = []
    news_years = _years(event.get("date", "")) | _years(event.get("title", ""))
    for note in notes:
        if note.get("role") == "alfa":
            body = note.get("thought", "") + " " + " ".join(e.get("quote", "") for e in note.get("evidence") or [])
            bank_years = _years(body)
            line = "Позиция банка: " + note["thought"]
            if bank_years and news_years and bank_years.isdisjoint(news_years):
                line += (f" Расхождение по дате: тезис банка {min(bank_years)}, новость {max(news_years)}. "
                         "Устаревшую позицию банка не считаем текущей.")
            parts.append(line)
        else:
            parts.append("Вывод модели, не позиция банка: " + note["thought"])
    return " ".join(parts)


# ---------------- page ----------------
def _ru_date(rfc2822: str) -> str:
    """The search keeps feed dates as RFC 2822 strings; the screen shows 24.10.2026. An unknown date stays empty."""
    try:
        return parsedate_to_datetime(rfc2822).strftime("%d.%m.%Y")
    except (TypeError, ValueError):
        return ""


def events_from(news: list[dict], pairs: list[list[int]]):
    """Search results -> (events, items for the text search, related event ids per event). The summary is the quotable text."""
    events, items, ids = [], {}, []
    for n, it in enumerate(news):
        eid = f"N{it['aid']}" if it.get("aid") else f"N{n}"
        ids.append(eid)
        event = {"id": eid, "title": it["title"], "text": it.get("summary") or "", "source": (it.get("outlets") or [""])[0],
                 "date": _ru_date(it.get("date") or ""), "url": it.get("link") or ""}
        events.append(event)
        items[eid] = dict(event)
    related = defaultdict(list)
    for i, j in pairs:
        if 0 <= i < len(ids) and 0 <= j < len(ids):
            related[ids[i]].append(ids[j])
            related[ids[j]].append(ids[i])
    return events, items, related


def company_text(profile: dict) -> str:
    parts = []
    if profile.get("okved_name"):
        parts.append(f"ОКВЭД {profile.get('okved_code') or profile.get('okved') or ''} ({profile['okved_name']})".replace("  ", " "))
    else:
        parts.append(f"«{profile.get('label') or 'компания'}»")
    if profile.get("region"):
        parts.append(f"регион {profile['region']}")
    if profile.get("products_ru") or profile.get("products"):
        parts.append("продукты банка: " + ", ".join(profile.get("products_ru") or profile["products"]))
    return ", ".join(parts)


def build(profile: dict, role: dict, events: list[dict], items: dict, agents, related=None, triz: bool = True, limit: int = EVENTS,
          sphere: str = "", role_label: str = "") -> dict:
    index = Index({i: _blob(it) for i, it in items.items()})
    embeds = alfa_embed(items)
    ctx = {"company": company_text(profile), "facts": profile.get("facts") or "", "sphere": sphere}
    widgets, links, journal, claims = [], [], [], []
    chosen = events[:limit]

    def analyse(n: int, event: dict):
        card = items.get(event["id"], {}).get("card")
        kinds = plan(card, profile)
        log.info("%d/%d %s %s", n, len(chosen), event["id"], event["title"][:70])
        try:
            notes = hop2(agents, event, items, index, ctx, kinds, embeds, (related or {}).get(event["id"], [])[:2])
        except RuntimeError as e:
            log.warning("analytics for %s failed: %s", event["id"], e)
            notes = []
        decision = None
        if notes:
            try:
                decision = hop3(agents, event, notes, role, triz, sphere)
            except RuntimeError as e:
                log.warning("decision for %s failed: %s", event["id"], e)
        return card, kinds, notes, decision

    with ThreadPoolExecutor(max(1, min(WORKERS, len(chosen) or 1))) as pool:  # results come back in the order of the news
        analysed = list(pool.map(lambda args: analyse(*args), enumerate(chosen, 1)))
    for n, (event, (card, kinds, notes, decision)) in enumerate(zip(chosen, analysed), 1):
        journal.append({"event": event["id"], "plan": kinds, "notes": len(notes), "decision": bool(decision),
                        "move": (decision or {}).get("move"), "evidence": [e["id"] for note in notes for e in note["evidence"]]})
        news_id = f"n{n}"
        text = event.get("text") or event["title"]
        news_tags = {"kind": "fact"}
        if (card or {}).get("event_type"):
            news_tags["industry"] = card["event_type"]
        widgets.append({"id": news_id, "column": "news", "title": clip_title(event["title"]), "url": event.get("url") or None,
                        "tags": news_tags,
                        "details": {"text": text, "src": event.get("source", ""), "date": event.get("date", "")},
                        "chat": {"text": text, "basis": [f"{event.get('source', '')}, {event.get('date', '')}".strip(", ")], "followups": []}})
        if not notes:
            continue
        src = "alfa" if any(note.get("role") == "alfa" for note in notes) else "ai"
        ana_id = f"a{n}"
        company = next((note["thought"] for note in notes if note.get("role") != "alfa"), notes[-1]["thought"])
        widgets.append({"id": ana_id, "column": "analytics", "title": clip_title(company),
                        "tags": {"confidence": "reliable" if src == "alfa" else "probable", "source": src},
                        "details": {"text": _analysis_text(notes, event)}})
        links.append({"id": f"l{n}a", "from": news_id, "to": ana_id, "text": notes[-1]["thought"]})
        for note in notes:
            claims.append({"widget": ana_id, "text": note["thought"], "quote": note["evidence"][0]["quote"]})
        if not decision:
            continue
        dec_id = f"d{n}"
        widgets.append({"id": dec_id, "column": "decisions", "title": clip_title(decision["title"]),
                        "tags": {"confidence": "possible" if decision.get("move") else "probable", "source": "ai",
                                 "urgency": HORIZON.get((card or {}).get("horizon"), "medium_term")},
                        "details": {"text": decision["text"] + (f" Приём: {decision['move']}." if decision.get("move") else "")},
                        "risks": {"steps": [decision["text"]], "bank_offer": None, "risks": decision["risks"]}})
        links.append({"id": f"l{n}d", "from": ana_id, "to": dec_id,
                      "text": decision.get("why") or decision.get("contradiction") or decision["text"]})
    # The quote is already checked against the source. A company conclusion is wider than that quote,
    # so a failed second opinion lowers confidence and stays on the page.
    weak = {claims[i]["widget"] for i in verify(agents, claims) if i < len(claims)}
    for w in widgets:
        tags = w.setdefault("tags", {})
        if w["id"] in weak:
            tags["confidence"] = "possible"
        if w.get("column") == "news":
            tags["kind"] = "fact"
        elif tags.get("confidence") == "possible":
            tags["kind"] = "hypothesis"
        else:
            tags["kind"] = "conclusion"
    today = datetime.date.today()
    page = {
        "version": 1,
        "company": {"name": profile.get("label") or "Компания",
                    "okved": f"{profile.get('okved_code') or ''} {profile.get('okved_name') or ''}".strip() or "не указан",
                    "role": role_label or role["title"],
                    "date": profile.get("date_label") or f"{today.day} {MONTHS[today.month - 1]} {today.year}"},
        "widgets": widgets, "links": links, "journal": journal,
    }
    return sources(page)


def paper_href(thesis_id: str) -> str | None:
    """Link to the Alfa PDF page; the backend serves the PDFs under /api/papers."""
    m = _THESIS.fullmatch(thesis_id or "")
    return f"/api/papers/{m.group(1)}.pdf#page={m.group(2)}" if m else None


def _ask(widget: dict) -> str | None:
    rows = (widget.get("risks") or {}).get("risks") or []
    name = ((rows[0].get("name") if rows else "") or "").strip().rstrip("?")
    if not name:
        return "Что будет, если это действие не сделать?" if widget.get("column") == "decisions" else None
    return "Что меняется, если " + name[:1].lower() + name[1:] + "?"


def sources(page: dict) -> dict:
    """Publication on the news, PDF link on the bank thesis, one follow-up from the first risk. No LLM call."""
    by = {w["id"]: w for w in page.get("widgets", [])}
    news = [w for w in page.get("widgets", []) if w.get("column") == "news"]
    for w, step in zip(news, page.get("journal") or []):
        n = w["id"][1:]
        alfa = [e for e in step.get("evidence") or [] if str(e).startswith("alfa:")]
        ana = by.get(f"a{n}")
        href = paper_href(alfa[0]) if alfa else None
        if ana and href:
            ana["url"] = href
        host = by.get(f"d{n}") or ana
        if not host:
            continue
        q = _ask(host)
        if not q:
            continue
        basis = []
        src, date = (w.get("details") or {}).get("src"), (w.get("details") or {}).get("date")
        if src:
            basis.append(f"{src}, {date}" if date else src)
        for e in alfa:
            m = _THESIS.fullmatch(e)
            if m:
                basis.append(f"{m.group(1)}, стр. {m.group(2)}")
        host["chat"] = {"text": host.get("title") or "", "basis": basis, "followups": [q]}
    return page


def hide_loose_bank(page: dict) -> dict:
    """Drop a bank sentence that does not share the headline's subject. The company conclusion stays."""
    by = {w["id"]: w for w in page.get("widgets", [])}
    for news in page.get("widgets", []):
        if news.get("column") != "news":
            continue
        ana = by.get("a" + news["id"][1:])
        text = ((ana or {}).get("details") or {}).get("text") or ""
        if not ana or not text.startswith("Позиция банка:"):
            continue
        rest = text[len("Позиция банка:"):].strip()
        clause, sep, tail = rest.partition(" Вывод модели, не позиция банка:")
        if bank_related(news.get("title") or "", clause):
            continue
        ana.pop("url", None)
        if ana.get("tags", {}).get("source") == "alfa":
            ana["tags"]["source"] = "ai"
        if sep and tail:
            ana["details"]["text"] = "Вывод модели, не позиция банка: " + tail.strip()
        else:
            ana["details"]["text"] = "В материалах банка нет тезиса по этой новости. Ниже вывод модели по тексту новости и карточке компании."
    return page


def make_page(agents, profile: dict, role_id: str, sphere: str, news: list[dict], pairs: list[list[int]], theses: list[dict] = (),
              triz: bool = True, limit: int = EVENTS) -> dict:
    """The whole job: search results + company profile + role id + sphere -> page (widgets and links with ids n1, a1, d1 ...).

    role_id picks the decision playbook (see data/roles.json); sphere, if any, is shown to the writer as the subject to write about.
    """
    events, items, related = events_from(news, pairs)
    for t in theses:  # bank theses are searchable like news, ids "alfa:<doc>:p<page>:t<n>"
        items[t["id"]] = {"id": t["id"], "title": t["claim"], "text": t["quote"], "claim": t["claim"]}
    page = build(profile, ROLES[role_id], events, items, agents, related, triz=triz, limit=limit, sphere=sphere, role_label=sphere or ROLE_RU[role_id])
    return hide_loose_bank(page)


def reply(agents, question: str, widget: dict, facts: str) -> dict:
    """One follow-up. The answer has to come from the widget text and the company card already on the page."""
    ans = agents.run("reply", {"question": question, "facts": facts, "title": widget.get("title", ""),
                               "text": (widget.get("details") or {}).get("text", ""),
                               "risks": (widget.get("risks") or {}).get("risks") or []})
    return {"text": ans.get("text") or "", "basis": [b for b in (ans.get("basis") or []) if isinstance(b, str)][:4]}
