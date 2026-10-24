"""Per-news causal chain: plan -> analytics (IRCoT) -> decision (playbook + TRIZ) -> verification -> page JSON.

One selected news item produces its own analytics widget and its own decision. The page is the set of those chains.
News collection and selection are inputs, not this module.
"""
import json
import os
import re
import time
from pathlib import Path

from reasoning.company import line as company_line
from reasoning.data import corpus, news_for, profiles, roles
from reasoning.search import Index, stems
from reasoning.view import bar

WRITER = "deepseek/deepseek-v4.1-flash"
VERIFIER = "qwen/qwen3.6-35b-a3b"  # a different family than the writer, so it is not grading its own text
OUT = Path(__file__).resolve().parent / "out"

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
_ROLE_ALIAS = {"cfo": "CFO", "финансовый директор": "CFO", "ceo": "CEO", "генеральный директор": "CEO",
               "собственник": "CEO", "главный бухгалтер": "chief_accountant",
               "казначей": "treasury_head", "руководитель казначейства": "treasury_head"}


def role_key(name: str) -> str:
    """Form text to a playbook id. An unknown role uses the CFO playbook."""
    return _ROLE_ALIAS.get((name or "").strip().lower(), "CFO")


def norm(text: str) -> str:
    return " ".join(str(text).split())


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
    """How the event can reach this company. Rules, no LLM call."""
    card = card or {}
    kinds, et = [], card.get("event_type")
    if profile["okved"] in card.get("okved", []):
        kinds.append("direct")
    if et in ("monetary_policy", "fx") and set(profile["products"]) & {"credit", "leasing", "deposits"}:
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


GENERIC = {"вырос", "роста", "росто", "основ", "показ", "дости", "макси", "уровн", "связа", "объем", "льгот", "значе"}
WEAK = {"число"}
FX = {"долла", "курс", "рубл", "рубля"}
_FX4 = {"рубл", "курс", "долл", "став"}


def display_role(name: str) -> str:
    """Known role to the Russian title. Any other text stays as the sphere the person typed."""
    raw = (name or "").strip()
    if raw.lower() in _ROLE_ALIAS:
        return ROLE_RU[role_key(raw)]
    return raw or ROLE_RU["CFO"]


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


def hop2(llm, event: dict, items: dict, index: Index, profile: dict, kinds: list[str], embeds=None) -> list[dict]:
    """Up to 3 iterations: write one thought, then search again with that thought. Ungrounded thoughts are dropped."""
    blobs = {i: _blob(it) for i, it in items.items()}
    notes, seen = [], {event["id"]}
    thought = event["title"]
    for n in range(3):
        hits = index.search(thought, k=2, prefix="alfa:") + index.search(thought, k=3, exclude=seen)
        hits = list(dict.fromkeys(hits))
        seen.update(hits)
        facts = company_line(profile.get("synthetic_u") or "")
        sphere = profile.get("sphere") or ""
        prompt = f"""Компания: ОКВЭД {profile['okved']} ({profile['okved_name']}), регион {profile['region']}, продукты банка: {', '.join(profile['products'])}.
{('Факты из карточки банка: ' + facts) if facts else ''}
{('Сфера анализа: ' + sphere + '. Пиши про неё, даже если слова введены с опечаткой.') if sphere else ''}
Связь события с компанией ищется так: {', '.join(kinds)}.
Новость: {event['title']}
{event.get('text', '')}
Уже выведено: {json.dumps([x['thought'] for x in notes], ensure_ascii=False)}
Материалы:
{_show([event['id'], *hits], items)}
Напиши ОДНО следующее предложение: что это значит именно для этой компании. Не выдумывай фактов.
Верни только JSON: {{"relevant": true, "done": false, "thought": "...", "evidence": [{{"id": "A0001", "quote": "дословный фрагмент из материала"}}]}}
relevant=false, если на компанию это не влияет. quote — дословная подстрока одного материала."""
        ans = llm.json(WRITER, prompt, f"hop2.{event['id']}.{n}", max_tokens=2500)
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


def _analysis_text(notes: list[dict]) -> str:
    chunks = []
    for note in notes:
        label = "Позиция банка" if note.get("role") == "alfa" else "Для компании"
        chunks.append(f"{label}: {note['thought']}")
    return " ".join(chunks)


def hop3(llm, event: dict, notes: list[dict], role: dict, triz: bool, sphere: str = "") -> dict | None:
    moves = "\n".join(f"- {k}: {v}" for k, v in MOVES.items()) if triz else "(ТРИЗ выключена — только правила роли)"
    prompt = f"""{('Сфера анализа: ' + sphere + '. Решение для этой сферы, по правилам роли.') if sphere else ''}
Роль: {role['title']}. Полномочия: {role['authority']}.
Правила роли:
{role['playbook']}
Приёмы (выбирай только из списка):
{moves}
Новость: {event['title']}
Аналитика: {json.dumps(notes, ensure_ascii=False)}
Дай одно решение для этой новости. Оно обязано ссылаться на аналитику. Приём ТРИЗ — только если его нет среди правил роли.
Первый символ ответа — {{. Без текста вокруг. probability и impact — целые 1..4, risks — от 2 до 4.
{{"title": "...", "text": "...", "why": "...", "move": null, "contradiction": null, "risks": [{{"name": "...", "probability": 2, "impact": 3, "mitigation": "..."}}]}}"""
    # 4000, not the default 1200: on the long role card this model spends ~1500 tokens reasoning before the JSON.
    ans = llm.json(WRITER, prompt, f"hop3.{event['id']}", max_tokens=4000)
    if not ans.get("title") or not ans.get("text"):
        return None
    if ans.get("move") not in MOVES:
        ans["move"] = None
    ans["risks"] = [r for r in ans.get("risks") or []
                    if isinstance(r.get("probability"), int) and isinstance(r.get("impact"), int)
                    and 1 <= r["probability"] <= 4 and 1 <= r["impact"] <= 4][:4]
    return ans


def verify(llm, claims: list[dict]) -> set[int]:
    """Returns indexes the other model marks unsupported. The caller already dropped bad quotes.

    One call for every claim makes this model spend the whole token cap on reasoning, so claims go in fours.
    A failed batch is kept: the quotes were already checked against the source text.
    """
    bad = set()
    for start in range(0, len(claims), 4):
        batch = claims[start:start + 4]
        prompt = ("По каждой цитате реши, следует ли из неё утверждение. "
                  "Первый символ ответа — {. Верни только JSON {\"verdicts\": [\"supported\" или \"unsupported\", ...]} "
                  "в том же порядке.\n"
                  + json.dumps([{"text": c["text"], "quote": c["quote"]} for c in batch], ensure_ascii=False))
        try:
            ans = llm.json(VERIFIER, prompt, f"verify.{start}", max_tokens=2000)
        except RuntimeError as e:
            print(f"verify {start} FAILED {e}", flush=True)
            continue
        for j, verdict in enumerate(ans.get("verdicts") or []):
            if verdict != "supported":
                bad.add(start + j)
    return bad


def _status(pid: str, done: int, total: int, event: dict, t0: float) -> None:
    spent = time.time() - t0
    left = round(spent / done * (total - done) / 60) if done else None
    OUT.mkdir(exist_ok=True)
    (OUT / "status.json").write_text(json.dumps({
        "profile": pid, "done": done, "total": total, "event": event["id"],
        "title": event["title"][:80], "elapsed_sec": round(spent), "left_min": left,
    }, ensure_ascii=False), encoding="utf-8")


def alfa_embed(items: dict):
    """bge-m3 over Alfa theses only. None when this page has no theses, so tests stay lexical.

    The encoded string is the claim plus the quote, the same text the comparison scored.
    """
    docs = {}
    for i, it in items.items():
        if not str(i).startswith("alfa:"):
            continue
        claim = it.get("claim") or it.get("title") or ""
        quote = it.get("text") or it.get("quote") or ""
        docs[i] = f"{claim}. {quote}"
    if not docs:
        return None
    from reasoning.embed import Bge
    print(f"bge-m3 кодирует {len(docs)} тезисов", flush=True)
    return Bge(docs)


def build(profile: dict, role: dict, events: list[dict], items: dict, llm, triz: bool = True, limit: int = 10) -> dict:
    index = Index({i: _blob(it) for i, it in items.items()})
    embeds = alfa_embed(items)
    widgets, links, journal = [], [], []
    claims = []
    chosen, t0 = events[:limit], time.time()
    for n, event in enumerate(chosen, 1):
        card = items.get(event["id"], {}).get("card")
        kinds = plan(card, profile)
        _status(profile["id"], n - 1, len(chosen), event, t0)
        print(f"[{bar(n - 1, len(chosen))}] {n}/{len(chosen)} {event['id']} {event['title'][:70]}", flush=True)
        try:
            notes = hop2(llm, event, items, index, profile, kinds, embeds)
        except RuntimeError as e:
            print(f"chain {n}/{len(chosen)} analytics FAILED {e}", flush=True)
            notes = []
        decision = None
        if notes:
            try:
                decision = hop3(llm, event, notes, role, triz, profile.get("sphere") or "")
            except RuntimeError as e:
                print(f"chain {n}/{len(chosen)} decision FAILED {e}", flush=True)
        left = round((time.time() - t0) / n * (len(chosen) - n) / 60)
        print(f"[{bar(n, len(chosen))}] {n}/{len(chosen)} {event['id']} analytics={len(notes)} decision={bool(decision)} left ~{left} min", flush=True)
        _status(profile["id"], n, len(chosen), event, t0)
        journal.append({"event": event["id"], "plan": kinds, "notes": len(notes), "decision": bool(decision),
                        "move": (decision or {}).get("move"),
                        "evidence": [e["id"] for note in notes for e in note["evidence"]]})
        news_id = f"n{n}"
        widgets.append({"id": news_id, "column": "news", "title": event["title"],
                        "tags": {"industry": (card or {}).get("event_type", "")},
                        "details": {"text": event.get("text") or event["title"], "src": event.get("source", ""), "date": event.get("date", "")}})
        if not notes:
            continue
        src = "alfa" if any(note.get("role") == "alfa" for note in notes) else "ai"
        ana_id = f"a{n}"
        company = next((note["thought"] for note in notes if note.get("role") != "alfa"), notes[-1]["thought"])
        widgets.append({"id": ana_id, "column": "analytics", "title": company[:120],
                        "tags": {"confidence": "reliable" if src == "alfa" else "probable", "source": src},
                        "details": {"text": _analysis_text(notes)}})
        links.append({"id": f"l{n}a", "from": news_id, "to": ana_id, "text": notes[-1]["thought"]})
        for note in notes:
            claims.append({"widget": ana_id, "text": note["thought"], "quote": note["evidence"][0]["quote"]})
        if not decision:
            continue
        dec_id = f"d{n}"
        widgets.append({"id": dec_id, "column": "decisions", "title": decision["title"],
                        "tags": {"confidence": "possible" if decision.get("move") else "probable", "source": "ai",
                                 "urgency": HORIZON.get((card or {}).get("horizon"), "medium_term")},
                        "details": {"text": decision["text"] + (f" Приём: {decision['move']}." if decision.get("move") else "")},
                        "risks": {"steps": [decision["text"]], "bank_offer": None, "risks": decision["risks"]}})
        links.append({"id": f"l{n}d", "from": ana_id, "to": dec_id,
                      "text": decision.get("why") or decision.get("contradiction") or decision["text"]})
    # The quote is already checked against the source. A company conclusion is wider than that quote,
    # so a failed second opinion lowers confidence and stays on the page.
    weak = {claims[i]["widget"] for i in verify(llm, claims) if i < len(claims)}
    for w in widgets:
        if w["id"] in weak:
            w.setdefault("tags", {})["confidence"] = "possible"
    page = {
        "version": 1,
        "company": {"name": profile.get("label") or f"Профиль {profile['id']}",
                    "okved": f"{profile.get('okved_code') or profile['okved']} {profile['okved_name']}",
                    "role": profile.get("sphere") or ROLE_RU.get(profile["role"], role["title"]),
                    "date": profile.get("date_label") or "неделя 13–21 октября 2026"},
        "widgets": widgets, "links": links, "journal": journal,
    }
    return sources(page)


_THESIS = re.compile(r"alfa:(.+):p(\d+):t\d+")
PAPERS = OUT.parent.parent / "analytical-papers"


def paper_href(thesis_id: str) -> str | None:
    """Link from reasoning/out/*.html to the Alfa PDF page. None if that file is not on disk."""
    m = _THESIS.fullmatch(thesis_id or "")
    if not m or not (PAPERS / f"{m.group(1)}.pdf").is_file():
        return None
    return f"../../analytical-papers/{m.group(1)}.pdf#page={m.group(2)}"


def _ask(widget: dict) -> str | None:
    rows = (widget.get("risks") or {}).get("risks") or []
    name = (rows[0].get("name") if rows else "") or ""
    name = name.strip().rstrip("?")
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


def reply(llm, question: str, widget: dict, facts: str) -> dict:
    """One follow-up. The answer has to come from the widget text and the company card already on the page."""
    prompt = f"""Ответь на вопрос только по этому разбору. Не добавляй фактов, которых нет ниже.
{('Факты из карточки банка: ' + facts) if facts else ''}
Заголовок: {widget.get('title', '')}
Текст: {(widget.get('details') or {}).get('text', '')}
Риски: {json.dumps((widget.get('risks') or {}).get('risks') or [], ensure_ascii=False)}
Вопрос: {question}
Верни только JSON {{"text": "ответ", "basis": ["короткая опора из текста выше"]}}"""
    ans = llm.json(WRITER, prompt, "reply", max_tokens=1200)
    basis = [b for b in (ans.get("basis") or []) if isinstance(b, str)][:4]
    return {"text": ans.get("text") or "", "basis": basis}


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
        clause, sep, tail = rest.partition(" Для компании:")
        if bank_related(news.get("title") or "", clause):
            continue
        ana.pop("url", None)
        if ana.get("tags", {}).get("source") == "alfa":
            ana["tags"]["source"] = "ai"
        if sep and tail:
            ana["details"]["text"] = "Для компании: " + tail.strip()
        else:
            ana["details"]["text"] = "В материалах банка нет тезиса по этой новости. Ниже вывод модели по тексту новости и карточке компании."
    return page


def run(pid: str, llm, triz: bool = True, role_name: str = "CFO", sphere: str = "") -> dict:
    uid = str(pid).split("__")[0]
    if uid.startswith("U_"):
        from reasoning.company import card
        from reasoning.focus import interpret
        profile = card(uid, role_key(role_name))
        if not profile:
            raise SystemExit(f"нет карточки {pid}")
        focus = interpret(sphere)
        if focus.topic or focus.section or focus.free:
            profile["sphere"] = sphere
        if focus.topic:
            profile["topic"] = focus.topic
        elif focus.section:
            profile["focus_section"] = focus.section
        elif focus.free:
            profile["focus_words"] = focus.words
        events, items = news_for(profile)
    else:
        profile = profiles()[pid]
        events, items = corpus(pid)
    role = roles()[profile["role"]]
    OUT.mkdir(exist_ok=True)
    (OUT / "run.lock").write_text(json.dumps({"pid": os.getpid(), "profile": str(pid)}), encoding="utf-8")
    theses = OUT / "theses.jsonl"
    if theses.exists():
        for row in theses.read_text(encoding="utf-8").splitlines():
            t = json.loads(row)
            items[t["id"]] = {"id": t["id"], "title": t["claim"], "text": t["quote"], "claim": t["claim"]}
    try:
        page = build(profile, role, events, items, llm, triz=triz)
    finally:
        lock = OUT / "run.lock"
        try:
            if json.loads(lock.read_text(encoding="utf-8")).get("pid") == os.getpid():
                lock.unlink()
        except (OSError, json.JSONDecodeError):
            pass
    hide_loose_bank(page)
    (OUT / f"{pid}.json").write_text(json.dumps(page, ensure_ascii=False, indent=1), encoding="utf-8")
    return page
