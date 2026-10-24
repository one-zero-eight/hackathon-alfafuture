"""Pages as the UI contract needs them (docs/backend.md): skeleton, widget/link lookup, ids, and the demo edits made in chat."""
import copy
import uuid

WIDGET_KEYS = ("id", "column", "title", "url", "tags")
NEXT = {"news": "analytics", "analytics": "decisions"}


def publish(key: str, raw: dict, meta: dict) -> dict:
    """Prefix every id with the profile key so that widget and link ids are unique across pages."""
    page = copy.deepcopy(raw)
    page["version"] = 1
    for w in page["widgets"]:
        w["id"] = f"{key}_{w['id']}"
    for l in page["links"]:
        l["id"], l["from"], l["to"] = f"{key}_{l['id']}", f"{key}_{l['from']}", f"{key}_{l['to']}"
    page["meta"] = meta
    return page


def skeleton(page: dict) -> dict:
    return {
        "version": page["version"], "company": page["company"],
        "widgets": [{k: w[k] for k in WIDGET_KEYS if w.get(k) is not None} for w in page["widgets"]],
        "links": [{k: l[k] for k in ("id", "from", "to")} for l in page["links"]],
    }


def find(items: list[dict], item_id: str):
    return next((x for x in items if x["id"] == item_id), None)


def chat_card(page: dict, ctx_type: str, ctx_id: str):
    """What opens in the chat for a widget or a link; None if it does not exist."""
    if ctx_type == "widget":
        w = find(page["widgets"], ctx_id)
        return None if w is None else w.get("chat") or {"text": "", "basis": [], "followups": []}
    l = find(page["links"], ctx_id)
    if l is None:
        return None
    titles = {w["id"]: w["title"] for w in page["widgets"]}
    return {"text": l["text"], "basis": [titles[l["from"]], titles[l["to"]]],
            "followups": ["Почему эти события связаны?", "Какие данные лежат в основе вывода?"]}


def edit(page: dict, prefix: str, ctx_type: str, ctx_id: str, message: str) -> tuple[str, list[dict]]:
    """Canned edits until an agent edits pages. Anything derived from the user's own words gets source=human."""
    msg = message.lower()
    if "добавь" in msg:
        if ctx_type == "link":
            l = find(page["links"], ctx_id)
            col, src, dst = find(page["widgets"], l["to"])["column"], l["from"], None
        else:
            col = find(page["widgets"], ctx_id)["column"]
            src, dst = (None, ctx_id) if col == "decisions" else (ctx_id, None)
            col = "analytics" if col == "decisions" else NEXT[col]
        wid, lid = f"{prefix}w_{uuid.uuid4().hex[:6]}", f"{prefix}l_{uuid.uuid4().hex[:6]}"
        tags = {"confidence": "possible", "source": "human", **({"urgency": "medium_term"} if col == "decisions" else {})}
        w = {"id": wid, "column": col, "title": "Новый виджет (демо)", "tags": tags,
             "details": {"text": "Виджет добавлен по запросу пользователя. Содержимое сгенерирует ИИ-модуль."},
             "chat": {"text": "Это новый виджет. Что именно вы хотите уточнить?", "basis": [], "followups": []}}
        l = {"id": lid, "from": src or wid, "to": dst or wid, "text": "Связь добавлена по запросу пользователя (демо)."}
        page["widgets"].append(w)
        page["links"].append(l)
        return "Добавил новый виджет и связь.", [{"op": "add_widget", "widget": {k: w[k] for k in ("id", "column", "title", "tags")}},
                                               {"op": "add_link", "link": {k: l[k] for k in ("id", "from", "to")}}]
    if "измени" in msg and ctx_type == "widget":
        w = find(page["widgets"], ctx_id)
        w["title"] += " (обновлено)"
        w["tags"] = {**w.get("tags", {}), "source": "human"}
        return "Обновил виджет.", [{"op": "update_widget", "id": ctx_id, "fields": {"title": w["title"], "tags": w["tags"]}}]
    return "Демо-режим: ответ ИИ-агента будет подключён позже. Попробуйте «добавь…» или «измени…».", []
