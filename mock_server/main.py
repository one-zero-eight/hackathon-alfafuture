"""Mock of the UI API (contract: docs/ENDPOINTS.md). State is in memory. Chat replies are canned;
only "добавь" / "измени" change the page, and they tag the result source=human."""
import copy
import json
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

SEED = json.loads((Path(__file__).parent / "seed.json").read_text(encoding="utf-8"))
WIDGETS = {w["id"]: copy.deepcopy(w) for w in SEED["widgets"]}
LINKS = {l["id"]: copy.deepcopy(l) for l in SEED["links"]}
STATE = {"version": 1, "n": 0}
NEXT = {"news": "analytics", "analytics": "decisions"}
PROFILE_IDS: set[str] = set()
PAGES: dict[str, dict] = {}

app = FastAPI(title="News analytics mock API")


class ChatContext(BaseModel):
    type: Literal["widget", "link"]
    id: str


class ProfileRequest(BaseModel):
    role: str
    company: str = ""  # empty, or anything other than U_…, uses the session company


class ChatRequest(BaseModel):
    context: ChatContext
    session_id: str | None = None
    message: str | None = None  # null = open the chat
    page_version: int


def get_or_404(store: dict, key: str) -> dict:
    if key not in store:
        raise HTTPException(404, f"{key} not found")
    return store[key]


def _reasoning_file(company: str) -> Path:
    root = Path(os.environ.get("REASONING_OUT", Path(__file__).resolve().parents[1] / "reasoning" / "out"))
    return root / f"{company}.json"


def _publish(key: str, raw: dict) -> dict:
    """Copy a reasoning page under prefixed ids so it does not replace the Gazprom demo."""
    widgets, links = [], []
    for src in raw.get("widgets", []):
        w = copy.deepcopy(src)
        w["id"] = f"{key}_{src['id']}"
        if w.get("url"):
            w["url"] = _paper_url(w["url"])
            if not (w.get("details") or {}).get("src"):
                w.setdefault("details", {})["src"] = "Материал банка"
        WIDGETS[w["id"]] = w
        PROFILE_IDS.add(w["id"])
        widgets.append(w)
    for src in raw.get("links", []):
        l = copy.deepcopy(src)
        l["id"] = f"{key}_{src['id']}"
        l["from"] = f"{key}_{src['from']}"
        l["to"] = f"{key}_{src['to']}"
        LINKS[l["id"]] = l
        PROFILE_IDS.add(l["id"])
        links.append(l)
    company = _hide_id(raw.get("company") or SEED["company"])
    page = {"version": raw.get("version", 1), "company": company, "widgets": widgets, "links": links}
    PAGES[key] = page
    return page


def _hide_id(company: dict) -> dict:
    """The synthetic id stays in the file. The screen shows the city."""
    shown = dict(company)
    if str(shown.get("name") or "").startswith("U_"):
        date = shown.get("date") or ""
        city = date.split(",")[-1].strip() if "," in date else ""
        shown["name"] = city or "Компания"
    return shown


def _paper_url(url: str) -> str:
    """The page file points at a PDF next to the repo. The UI loads it through the mock."""
    m = re.search(r"analytical-papers/([^#]+)", url)
    if not m:
        return url
    return "/api/papers/" + m.group(1) + (url[url.index("#"):] if "#" in url else "")


def _skeleton(page: dict) -> dict:
    return {
        "version": page.get("version", STATE["version"]),
        "company": page["company"],
        "widgets": [{k: w[k] for k in ("id", "column", "title", "url", "tags") if k in w} for w in page["widgets"]],
        "links": [{k: l[k] for k in ("id", "from", "to")} for l in page["links"]],
    }


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _lock() -> dict:
    path = Path(__file__).resolve().parents[1] / "reasoning" / "out" / "run.lock"
    if not path.is_file():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _busy(company: str) -> bool:
    lock = _lock()
    return lock.get("profile") == company and _alive(int(lock.get("pid") or 0))


def _spawn(company: str, role: str, sphere: str = "") -> None:
    if _busy(company):
        return
    out = Path(__file__).resolve().parents[1] / "reasoning" / "out"
    out.mkdir(exist_ok=True)
    log = open(out / f"{company}.log", "a", encoding="utf-8")
    cmd = [sys.executable, "-m", "reasoning.run", company, role]
    if sphere:
        cmd += ["--sphere", sphere]
    proc = subprocess.Popen(
        cmd, cwd=Path(__file__).resolve().parents[1], stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (out / "run.lock").write_text(json.dumps({"pid": proc.pid, "profile": company}), encoding="utf-8")


def _session(req: ProfileRequest) -> tuple[str, str]:
    """Company id and the sphere line.

    An empty company field uses the session company. A name that already has a page, including the demo, is kept.
    Any other text is not a company id: the session company is used and that text can still be read as a sphere.
    """
    role = " ".join(req.role.split())
    typed = " ".join((req.company or "").split())
    if not typed:
        return os.environ.get("DEMO_COMPANY", "U_9250"), role
    if typed.startswith("U_") or _reasoning_file(typed).is_file():
        return typed, role
    return os.environ.get("DEMO_COMPANY", "U_9250"), role


@app.post("/api/profile")
def set_profile(req: ProfileRequest) -> dict:
    from reasoning.chain import ROLE_RU
    from reasoning.company import card
    from reasoning.focus import Focus, cache_key, interpret
    company, role = _session(req)
    if not role:
        raise HTTPException(422, "role is required")
    focus = interpret(role)
    typed = " ".join((req.company or "").split())
    if typed and not typed.startswith("U_") and not (focus.section or focus.topic):
        extra = interpret(typed)
        if extra.section or extra.topic:
            focus = Focus(focus.role or extra.role, extra.section, extra.topic, extra.words, extra.label)
    found = card(company) if company.startswith("U_") else None
    key = cache_key(company, focus, (found or {}).get("okved") or "")
    path = _reasoning_file(key)
    play = focus.role or "CFO"
    sphere = focus.label if (focus.topic or focus.section or focus.free) else ""
    if not path.is_file():
        if company.startswith("U_") and (_busy(key) or _start_company(key, play, sphere)):
            return {"key": key, "status": "running", "error": ""}
        return {"key": key, "status": "failed", "error": "разбор для этой сферы ещё не собран"}
    raw = json.loads(path.read_text(encoding="utf-8"))
    page = _publish(key, raw)
    if sphere:
        page["company"]["role"] = focus.label
    elif focus.role:
        page["company"]["role"] = ROLE_RU.get(focus.role, focus.label)
    return {"key": key, "status": "ready", "error": ""}


def _start_company(key: str, role: str, sphere: str = "") -> bool:
    """Start a chain for the session company. False when the organizer file has no such id."""
    try:
        from reasoning.company import line
        if not line(key.split("__")[0]):
            return False
    except Exception:
        return False
    _spawn(key, role, sphere)
    return True


@app.get("/api/profile/{key}")
def profile_status(key: str) -> dict:
    if _reasoning_file(key).is_file() or key in PAGES:
        return {"key": key, "status": "ready", "error": ""}
    if _busy(key):
        return {"key": key, "status": "running", "error": ""}
    raise HTTPException(404, f"profile {key} not found")


@app.get("/api/page")
def page(profile: str | None = None) -> dict:
    if profile:
        data = PAGES.get(profile)
        if data is None and _reasoning_file(profile).is_file():
            data = _publish(profile, json.loads(_reasoning_file(profile).read_text(encoding="utf-8")))
        if data is None:
            raise HTTPException(404, f"profile {profile} has no page yet")
        return _skeleton(data)
    return _skeleton({
        "version": STATE["version"],
        "company": SEED["company"],
        "widgets": [w for w in WIDGETS.values() if w["id"] not in PROFILE_IDS],
        "links": [l for l in LINKS.values() if l["id"] not in PROFILE_IDS],
    })


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
        c = get_or_404(WIDGETS, ctx.id).get("chat") or {"text": "", "basis": [], "followups": []}
    else:
        l = get_or_404(LINKS, ctx.id)
        c = {"text": l["text"], "basis": [WIDGETS[l["from"]]["title"], WIDGETS[l["to"]]["title"]],
             "followups": ["Почему эти события связаны?", "Какие данные лежат в основе вывода?"]}
    session_id = req.session_id or uuid.uuid4().hex
    if req.message is None:
        return {"session_id": session_id, "reply": c, "patch": None}
    owner = next((k for k, p in PAGES.items() if any(w["id"] == ctx.id for w in p["widgets"])), "")
    if owner and ctx.type == "widget" and "добавь" not in req.message.lower() and "измени" not in req.message.lower():
        from reasoning.chain import reply
        from reasoning.company import line
        from reasoning.llm import LLM
        try:
            uid = owner.split("__")[0]
            ans = reply(LLM(), req.message, get_or_404(WIDGETS, ctx.id), line(uid) if uid.startswith("U_") else "")
        except Exception as e:
            ans = {"text": "Не удалось ответить: " + str(e), "basis": []}
        follow = (WIDGETS[ctx.id].get("chat") or {}).get("followups") or []
        return {"session_id": session_id, "reply": {"text": ans["text"], "basis": ans["basis"], "followups": follow}, "patch": None}
    if req.page_version != STATE["version"]:
        raise HTTPException(409, f"page version is {STATE['version']}, client has {req.page_version}")
    text, ops = edit(ctx, req.message)
    patch = None
    if ops:
        STATE["version"] += 1
        patch = {"base_version": req.page_version, "version": STATE["version"], "ops": ops}
    return {"session_id": session_id, "reply": {"text": text, "basis": [], "followups": []}, "patch": patch}


_papers = Path(__file__).resolve().parents[1] / "analytical-papers"
if _papers.is_dir():
    app.mount("/api/papers", StaticFiles(directory=_papers), name="papers")

_ui = Path(__file__).resolve().parents[1] / "ui" / "dist"
if _ui.is_dir():
    app.mount("/", StaticFiles(directory=_ui, html=True), name="ui")
