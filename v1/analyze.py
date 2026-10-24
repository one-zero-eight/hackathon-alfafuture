"""LLM analysis of the top news: analytics, decisions with risks, and links, as a page for the UI (docs/ENDPOINTS.md).

    build_page(key, company, role, top) -> {"company", "widgets": [full widget records], "links": [...]}

News widgets are built from the real items (title, url, outlet, date come from the corpus, never from the LLM);
the LLM only writes the explanations, analytics and decisions. Placeholder until the ranking/analysis module of the team replaces it."""
import datetime
from email.utils import parsedate_to_datetime

from pipeline import QUERY_MODEL, chat_json

N_NEWS = 8
CONF, URG = {"reliable", "probable", "possible"}, {"urgent", "medium_term", "not_urgent"}

SPEC = """Верни ТОЛЬКО JSON такой формы (ключи точно такие):
{
 "news": [{"i": <номер новости из списка>, "industry": "<отрасль/тема, 1-3 слова>", "why": "<1-2 предложения: что произошло и почему важно этому руководителю; только факты из заголовка>"}],  // ровно %(n)d, самые важные
 "analytics": [{"id": "a1", "title": "<короткий вывод>", "text": "<2-3 предложения: что это значит для компании; отдели факт от гипотезы>", "confidence": "reliable|probable|possible",
                "followups": ["<вопрос>", "<вопрос>"]}],  // 4-5 штук
 "decisions": [{"id": "d1", "title": "<действие>", "text": "<1-2 предложения>", "urgency": "urgent|medium_term|not_urgent", "confidence": "reliable|probable|possible",
                "steps": ["<шаг>", "<шаг>"],
                "risks": [{"name": "<риск>", "probability": <1-4>, "impact": <1-4>, "mitigation": "<как снизить>"}],  // 2-4 риска
                "bank_offer": null или "<уместное нативное предложение Альфа-Банка одной фразой>",
                "followups": ["<вопрос>", "<вопрос>"]}],  // 3-4 штуки
 "news_to_analytics": [{"news": <номер новости>, "analytics": "a1", "text": "<почему новость ведёт к выводу>"}],
 "analytics_to_decisions": [{"analytics": "a1", "decision": "d1", "text": "<почему вывод ведёт к решению>"}]
}
Правила: используй только факты из заголовков, не выдумывай числа, даты и названия; догадки помечай словом «вероятно» или «возможно».
У каждой аналитики должна быть хотя бы одна связь с новостью, у каждого решения хотя бы одна связь с аналитикой."""


def _date(s):
    try:
        return parsedate_to_datetime(s).strftime("%d.%m.%Y")
    except Exception:
        return ""


def _enum(v, allowed, default):
    return v if v in allowed else default


def _text(v, limit=600):
    return v.strip()[:limit] if isinstance(v, str) else ""


def build_page(key, company, role, top):
    top = top[:30]
    lines = "\n".join(f"{i} | {_date(t['date'])} | {', '.join(t['outlets'][:2])} | {t['title']}" for i, t in enumerate(top))
    try:
        from reasoning.company import line as company_line
        facts = company_line(company)
    except Exception:
        facts = ""
    prompt = (
        f"Компания: «{company}». Роль руководителя / сфера анализа: «{role}».\n"
        + (f"Факты из карточки банка: {facts}\n" if facts else "")
        + f"Ниже {len(top)} отобранных российских новостей (номер | дата | источник | заголовок).\n"
        + f"Сделай из них аналитику для принятия решений.\n{SPEC % {'n': N_NEWS}}\n\n{lines}"
    )
    d = chat_json(QUERY_MODEL, prompt, "news")
    pid = lambda x: f"{key}_{x}"
    widgets, links, news_ids, analytics_ids, decision_ids = [], [], {}, set(), set()
    for n in d.get("news", []):
        i = n.get("i") if isinstance(n, dict) else None
        if not isinstance(i, int) or not 0 <= i < len(top) or i in news_ids: continue
        t, why = top[i], _text(n.get("why")) or top[i]["title"]
        outlet, date = (t["outlets"] or ["?"])[0], _date(t["date"])
        news_ids[i] = pid(f"n{i}")
        widgets.append({"id": news_ids[i], "column": "news", "title": t["title"], "url": t["link"],
                        "tags": {"industry": _text(n.get("industry"), 40)} if _text(n.get("industry"), 40) else {},
                        "details": {"text": why, "src": outlet, "date": date},
                        "chat": {"text": why, "basis": [f"{outlet}, {date}".strip(", ")], "followups": []}})
    for a in d.get("analytics", []):
        if not isinstance(a, dict) or not _text(a.get("id")) or not _text(a.get("title")): continue
        wid = pid(_text(a["id"], 20)); analytics_ids.add(wid)
        widgets.append({"id": wid, "column": "analytics", "title": _text(a["title"], 200),
                        "tags": {"confidence": _enum(a.get("confidence"), CONF, "possible"), "source": "ai"},
                        "details": {"text": _text(a.get("text"))},
                        "chat": {"text": _text(a.get("text")), "basis": [], "followups": [_text(f, 200) for f in a.get("followups", [])[:3] if _text(f)]}})
    for x in d.get("decisions", []):
        if not isinstance(x, dict) or not _text(x.get("id")) or not _text(x.get("title")): continue
        wid = pid(_text(x["id"], 20)); decision_ids.add(wid)
        risks = [{"name": _text(r.get("name"), 200), "probability": min(4, max(1, int(r["probability"]))), "impact": min(4, max(1, int(r["impact"]))),
                  "mitigation": _text(r.get("mitigation"), 300)}
                 for r in x.get("risks", []) if isinstance(r, dict) and _text(r.get("name")) and isinstance(r.get("probability"), int) and isinstance(r.get("impact"), int)]
        widgets.append({"id": wid, "column": "decisions", "title": _text(x["title"], 200),
                        "tags": {"confidence": _enum(x.get("confidence"), CONF, "possible"), "source": "ai", "urgency": _enum(x.get("urgency"), URG, "medium_term")},
                        "details": {"text": _text(x.get("text"))},
                        "risks": {"steps": [_text(s, 300) for s in x.get("steps", []) if _text(s)], "bank_offer": _text(x.get("bank_offer"), 300) or None, "risks": risks},
                        "chat": {"text": _text(x.get("text")), "basis": [], "followups": [_text(f, 200) for f in x.get("followups", [])[:3] if _text(f)]}})
    for n, l in enumerate(d.get("news_to_analytics", []), 1):
        a = pid(_text(l.get("analytics"), 20)) if isinstance(l, dict) else ""
        if isinstance(l, dict) and l.get("news") in news_ids and a in analytics_ids:
            links.append({"id": pid(f"l{n}"), "from": news_ids[l["news"]], "to": a, "text": _text(l.get("text"))})
    for n, l in enumerate(d.get("analytics_to_decisions", []), 1):
        a, x = (pid(_text(l.get("analytics"), 20)), pid(_text(l.get("decision"), 20))) if isinstance(l, dict) else ("", "")
        if a in analytics_ids and x in decision_ids:
            links.append({"id": pid(f"m{n}"), "from": a, "to": x, "text": _text(l.get("text"))})
    # basis of analytics/decisions = titles of the widgets linked into them
    title = {w["id"]: w["title"] for w in widgets}
    for w in widgets:
        if w["column"] != "news": w["chat"]["basis"] = [title[l["from"]] for l in links if l["to"] == w["id"]]
    cols = {w["column"] for w in widgets}
    if cols != {"news", "analytics", "decisions"}: raise RuntimeError(f"analysis incomplete: columns {sorted(cols)}")
    return {"company": {"name": company, "okved": "не указан", "role": role, "date": datetime.date.today().strftime("%d.%m.%Y")},
            "widgets": widgets, "links": links}
