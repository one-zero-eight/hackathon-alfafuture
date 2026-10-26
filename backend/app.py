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
from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from uuid import UUID

from backend import config, pages, store, worker, journal
from backend.journal_api import router as journal_router
from backend.feedback_api import router as feedback_router
from backend import feedback_store
from agents import tracing
from backend.companies import CompanyUnavailable

logging.basicConfig(level=logging.INFO)
DEMO = json.loads((Path(__file__).parent / "demo" / "seed.json").read_text(encoding="utf-8"))
DEMO_PAGE = {"version": 1, **copy.deepcopy(DEMO)}  # in memory: edits of the demo page are lost on restart
KEY = re.compile(r"([0-9a-f]{12})_")


@asynccontextmanager
async def lifespan(_: FastAPI):
    store.init()
    stop = threading.Event()
    threading.Thread(target=journal.run_cleanup, args=(stop,), daemon=True, name="journal-cleanup").start()
    if config.WORKER_ENABLED:
        threading.Thread(target=worker.run_forever, args=(stop,), daemon=True, name="profiles").start()
    yield
    stop.set()


app = FastAPI(title="News analytics backend", lifespan=lifespan)
app.include_router(journal_router)
app.include_router(feedback_router)


class ChatContext(BaseModel):
    type: Literal["widget", "link", "page"]
    id: str = Field(min_length=1, max_length=100)


class ChatRequest(BaseModel):
    context: ChatContext
    session_id: str | None = Field(None, max_length=100)
    message: str | None = Field(None, max_length=8000)  # null = open the chat
    page_version: int = Field(ge=1)
    request_id: UUID | None = None


class ProfileRequest(BaseModel):
    company: str = ""  # a name, or an anonymised id U_<digits> from the bank data
    role: str
    region: str = ""
    company_id: str = ""
    force: bool = False


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


@app.get("/api/companies")
def companies(q: str = "", offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=200)) -> dict:
    """The company picker of the start menu: a page of bank-data companies, optionally filtered by id or OKVED name."""
    try:
        return worker.book.listing(q, offset, limit)
    except CompanyUnavailable as e:
        raise HTTPException(503, str(e))


@app.post("/api/profile")
def set_profile(req: ProfileRequest) -> dict:
    company, role, region, company_id = (" ".join(x.split()) for x in (req.company, req.role, req.region, req.company_id))
    if worker.COMPANY_ID.fullmatch(company):
        company, company_id = "", company_id or company
    if not (company or company_id) or not role or any(len(x) > 200 for x in (company, role, region, company_id)) or (company_id and not worker.COMPANY_ID.fullmatch(company_id)):
        raise HTTPException(422, "role and company (or company_id U_<digits>) are required; fields at most 200 characters")
    key = worker.profile_key(company, company_id, role, region, config.NEWS_SEARCH_METHOD)
    k, status, error, run_id = store.submit(key=key, company=company, company_id=company_id, role=role, region=region, method=config.NEWS_SEARCH_METHOD, force=req.force)
    return {"key": k, "status": status, "error": error, "cached": status == "ready", "run_id": run_id}  # ready right at submit = served from the database


@app.get("/api/profile/{key}")
def profile_status(key: str) -> dict:
    row = store.status(key)
    if not row:
        raise HTTPException(404, f"profile {key} not found")
    return {"key": key, "status": row[0], "error": row[1], "stage": row[2], "found": row[3], "selected": row[4], "run_id": row[5]}


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
def chat(req: ChatRequest, response: Response) -> dict:
    ctx = req.context
    if req.message is not None and req.request_id:
        match = KEY.match(ctx.id)
        key = ctx.id if ctx.type == "page" else (match.group(1) if match else None)
        if key and feedback_store.request_exists(key, str(req.request_id)):
            return queue_chat(req, response, key, req.session_id or uuid.uuid4().hex)
    if ctx.type == "page":
        key, prefix, page = ctx.id, ctx.id + "_", store.load_page(ctx.id)
        if page is None:
            raise HTTPException(404, "profile page not found")
        card = {"text": "Что вы хотите узнать или изменить на странице?", "basis": [], "followups": []}
    else:
        key, prefix, page = locate(ctx.id)
        card = pages.chat_card(page, ctx.type, ctx.id)
        if card is None:
            raise HTTPException(404, "context not found")
    session_id = req.session_id or uuid.uuid4().hex
    if req.message is None:
        return {"session_id": session_id, "reply": card, "patch": None}
    if not req.message.strip():
        raise HTTPException(422, "message must not be empty")
    if not key:
        return {"session_id": session_id, "reply": {"text": "Для обработки запроса выберите компанию и создайте профиль. Демо-страница не изменена.", "basis": [], "followups": []}, "patch": None, "scenario": {"kind": "clarify", "reason": "Нужен сохранённый профиль."}}
    return queue_chat(req, response, key, session_id)


def queue_chat(req, response, key, session_id):
    payload = {"context": req.context.model_dump(), "message": req.message.strip(), "session_id": session_id, "page_version": req.page_version}
    try:
        operation_id = feedback_store.enqueue(key, payload, str(req.request_id) if req.request_id else None)
    except feedback_store.Missing as error:
        raise HTTPException(404, str(error)) from None
    except feedback_store.Conflict as error:
        raise HTTPException(409, str(error)) from None
    operation = feedback_store.get(operation_id)
    response.status_code = 202
    if operation["run_id"]:
        response.headers["X-Run-ID"] = operation["run_id"]
    else:
        response.headers["X-Trace-Incomplete"] = "true"
    return {"operation_id": operation_id, "run_id": operation["run_id"], "status": operation["status"],
            "session_id": operation["session_id"], "reply": {"text": "Запрос принят. Результат появится после обработки.", "basis": [], "followups": []}, "patch": None}


if os.path.isdir(config.PAPERS_DIR):
    app.mount("/api/papers", StaticFiles(directory=config.PAPERS_DIR), name="papers")
