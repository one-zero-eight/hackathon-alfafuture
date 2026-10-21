"""Mock of the UI API (contract: docs/ENDPOINTS.md). State is in memory. Chat replies are canned;
only "добавь" / "измени" change the page, and they tag the result source=human."""
import copy
import json
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

SEED = json.loads((Path(__file__).parent / "seed.json").read_text(encoding="utf-8"))
WIDGETS = {w["id"]: copy.deepcopy(w) for w in SEED["widgets"]}
LINKS = {l["id"]: copy.deepcopy(l) for l in SEED["links"]}
STATE = {"version": 1, "n": 0}
NEXT = {"news": "analytics", "analytics": "decisions"}

app = FastAPI(title="News analytics mock API")


class ChatContext(BaseModel):
    type: Literal["widget", "link"]
    id: str


class ChatRequest(BaseModel):
    context: ChatContext
    session_id: str | None = None
    message: str | None = None  # null = open the chat
    page_version: int


def get_or_404(store: dict, key: str) -> dict:
    if key not in store:
        raise HTTPException(404, f"{key} not found")
    return store[key]


@app.get("/api/page")
def page() -> dict:
    return {
        "version": STATE["version"],
        "company": SEED["company"],
        "widgets": [{k: w[k] for k in ("id", "column", "title", "url", "tags") if k in w} for w in WIDGETS.values()],
        "links": [{k: l[k] for k in ("id", "from", "to")} for l in LINKS.values()],
    }


@app.get("/api/widgets/{wid}")
def widget(wid: str) -> dict:
    return {"id": wid, **get_or_404(WIDGETS, wid)["details"]}


@app.get("/api/widgets/{wid}/risks")
def risks(wid: str) -> dict:
    w = get_or_404(WIDGETS, wid)
    if "risks" not in w:
        raise HTTPException(404, f"{wid} has no risk matrix")
    return {"id": wid, **w["risks"]}


@app.get("/api/links/{lid}")
def link(lid: str) -> dict:
    l = get_or_404(LINKS, lid)
    return {k: l[k] for k in ("id", "from", "to", "text")}


def edit(ctx: ChatContext, message: str) -> tuple[str, list[dict]]:
    """Canned edits. Anything derived from the user's own words gets source=human."""
    msg = message.lower()
    if "добавь" in msg:
        if ctx.type == "link":
            l = LINKS[ctx.id]
            col, src, dst = WIDGETS[l["to"]]["column"], l["from"], None
        else:
            col = WIDGETS[ctx.id]["column"]
            src, dst = (None, ctx.id) if col == "decisions" else (ctx.id, None)
            col = "analytics" if col == "decisions" else NEXT[col]
        STATE["n"] += 1
        wid, lid = f"w_demo_{STATE['n']}", f"l_demo_{STATE['n']}"
        tags = {"confidence": "possible", "source": "human", **({"urgency": "medium_term"} if col == "decisions" else {})}
        w = {"id": wid, "column": col, "title": "Новый виджет (демо)", "tags": tags,
             "details": {"text": "Виджет добавлен по запросу пользователя. Содержимое сгенерирует ИИ-модуль."},
             "chat": {"text": "Это новый виджет. Что именно вы хотите уточнить?", "basis": [], "followups": []}}
        WIDGETS[wid] = w
        l = {"id": lid, "from": src or wid, "to": dst or wid, "text": "Связь добавлена по запросу пользователя (демо)."}
        LINKS[lid] = l
        skeleton = {k: w[k] for k in ("id", "column", "title", "tags")}
        return "Добавил новый виджет и связь.", [{"op": "add_widget", "widget": skeleton},
                                               {"op": "add_link", "link": {k: l[k] for k in ("id", "from", "to")}}]
    if "измени" in msg and ctx.type == "widget":
        w = WIDGETS[ctx.id]
        w["title"] += " (обновлено)"
        w["tags"] = {**w.get("tags", {}), "source": "human"}
        return "Обновил виджет.", [{"op": "update_widget", "id": ctx.id, "fields": {"title": w["title"], "tags": w["tags"]}}]
    return "Демо-режим: ответ ИИ-агента будет подключён позже. Попробуйте «добавь…» или «измени…».", []


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    ctx = req.context
    if ctx.type == "widget":
        c = get_or_404(WIDGETS, ctx.id)["chat"]
    else:
        l = get_or_404(LINKS, ctx.id)
        c = {"text": l["text"], "basis": [WIDGETS[l["from"]]["title"], WIDGETS[l["to"]]["title"]],
             "followups": ["Почему эти события связаны?", "Какие данные лежат в основе вывода?"]}
    session_id = req.session_id or uuid.uuid4().hex
    if req.message is None:
        return {"session_id": session_id, "reply": c, "patch": None}
    if req.page_version != STATE["version"]:
        raise HTTPException(409, f"page version is {STATE['version']}, client has {req.page_version}")
    text, ops = edit(ctx, req.message)
    patch = None
    if ops:
        STATE["version"] += 1
        patch = {"base_version": req.page_version, "version": STATE["version"], "ops": ops}
    return {"session_id": session_id, "reply": {"text": text, "basis": [], "followups": []}, "patch": patch}
