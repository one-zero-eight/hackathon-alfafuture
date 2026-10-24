"""Backend: the API of the UI (docs/backend.md). Keeps profiles and pages, and orchestrates search and analytics."""
import copy
import json
import logging
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from backend import config, pages, store, worker

logging.basicConfig(level=logging.INFO)
DEMO = json.loads((Path(__file__).parent / "demo" / "seed.json").read_text(encoding="utf-8"))
DEMO_PAGE = {"version": 1, **copy.deepcopy(DEMO)}  # in memory: edits of the demo page are lost on restart
KEY = re.compile(r"([0-9a-f]{12})_")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    stop = threading.Event()
    if config.WORKER_ENABLED:
        threading.Thread(target=worker.run_forever, args=(stop,), daemon=True, name="profiles").start()
    yield
    stop.set()


app = FastAPI(title="News analytics backend", lifespan=lifespan)


class ChatContext(BaseModel):
    type: Literal["widget", "link"]
    id: str


class ChatRequest(BaseModel):
    context: ChatContext
    session_id: str | None = None
    message: str | None = None  # null = open the chat
    page_version: int


class ProfileRequest(BaseModel):
    company: str = ""  # a name, or an anonymised id U_<digits> from the bank data
    role: str
    region: str = ""
    company_id: str = ""


def locate(element_id: str) -> tuple[str, str, dict]:
    """(profile key or "", id prefix, page) of the page that owns a widget or link id. Ids of profile pages start with "<key>_"."""
    m = KEY.match(element_id)
    if m:
        page = store.load_page(m.group(1))
        if page is not None:
            return m.group(1), m.group(0), page
    return "", "", DEMO_PAGE


def found(page: dict, collection: str, element_id: str) -> dict:
    item = pages.find(page[collection], element_id)
    if item is None:
        raise HTTPException(404, f"{element_id} not found")
    return item


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/api/profile")
def set_profile(req: ProfileRequest) -> dict:
    company, role, region, company_id = (" ".join(x.split()) for x in (req.company, req.role, req.region, req.company_id))
    if worker.COMPANY_ID.fullmatch(company):
        company, company_id = "", company_id or company
    if not (company or company_id) or not role or any(len(x) > 200 for x in (company, role, region, company_id)) or (company_id and not worker.COMPANY_ID.fullmatch(company_id)):
        raise HTTPException(422, "role and company (or company_id U_<digits>) are required; fields at most 200 characters")
    key = worker.profile_key(company, company_id, role, region, config.NEWS_SEARCH_METHOD)
    k, status, error = store.submit(key=key, company=company, company_id=company_id, role=role, region=region, method=config.NEWS_SEARCH_METHOD)
    return {"key": k, "status": status, "error": error}


@app.get("/api/profile/{key}")
def profile_status(key: str) -> dict:
    row = store.status(key)
    if not row:
        raise HTTPException(404, f"profile {key} not found")
    return {"key": key, "status": row[0], "error": row[1]}


@app.get("/api/page")
def get_page(profile: str | None = None) -> dict:
    if not profile:
        return pages.skeleton(DEMO_PAGE)
    page = store.load_page(profile)
    if page is None:
        raise HTTPException(404, f"profile {profile} has no page yet")
    return pages.skeleton(page)


@app.get("/api/widgets/{wid}")
def widget(wid: str) -> dict:
    return {"id": wid, **found(locate(wid)[2], "widgets", wid)["details"]}


@app.get("/api/widgets/{wid}/risks")
def risks(wid: str) -> dict:
    w = found(locate(wid)[2], "widgets", wid)
    if "risks" not in w:
        raise HTTPException(404, f"{wid} has no risk matrix")
    return {"id": wid, **w["risks"]}


@app.get("/api/links/{lid}")
def link(lid: str) -> dict:
    l = found(locate(lid)[2], "links", lid)
    return {k: l[k] for k in ("id", "from", "to", "text")}


@app.post("/api/chat")
def chat(req: ChatRequest) -> dict:
    ctx = req.context
    key, prefix, page = locate(ctx.id)
    card = pages.chat_card(page, ctx.type, ctx.id)
    if card is None:
        raise HTTPException(404, f"{ctx.id} not found")
    session_id = req.session_id or uuid.uuid4().hex
    if req.message is None:
        return {"session_id": session_id, "reply": card, "patch": None}
    text = req.message.lower()
    if key and ctx.type == "widget" and "добавь" not in text and "измени" not in text:
        return {"session_id": session_id, "reply": answer(page, ctx.id, req.message, card), "patch": None}
    if req.page_version != page["version"]:
        raise HTTPException(409, f"page version is {page['version']}, client has {req.page_version}")
    reply_text, ops = pages.edit(page, prefix, ctx.type, ctx.id, req.message)
    patch = None
    if ops:
        page["version"] += 1
        patch = {"base_version": req.page_version, "version": page["version"], "ops": ops}
        if key:
            store.save_page(key, page)
    return {"session_id": session_id, "reply": {"text": reply_text, "basis": [], "followups": []}, "patch": patch}


def answer(page: dict, widget_id: str, question: str, card: dict) -> dict:
    """A follow-up question on a profile page: the analytics service answers from the widget and the company facts only."""
    try:
        r = httpx.post(f"{config.ANALYTICS_URL}/reply", timeout=300,
                       json={"question": question, "widget": pages.find(page["widgets"], widget_id), "facts": page.get("meta", {}).get("facts", "")})
        r.raise_for_status()
        got = r.json()
    except (httpx.HTTPError, ValueError) as e:
        got = {"text": "Не удалось ответить: " + repr(e), "basis": []}
    return {"text": got["text"], "basis": got["basis"], "followups": card.get("followups", [])}


if os.path.isdir(config.PAPERS_DIR):
    app.mount("/api/papers", StaticFiles(directory=config.PAPERS_DIR), name="papers")
