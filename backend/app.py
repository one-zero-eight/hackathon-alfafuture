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

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from backend import config, feedback, feedback_pages, feedback_store, pages, store, worker
from backend.companies import CompanyUnavailable

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
        threading.Thread(target=feedback.run_forever, args=(stop,), daemon=True, name="feedback").start()
    yield
    stop.set()


app = FastAPI(title="News analytics backend", lifespan=lifespan)


class ChatContext(BaseModel):
    type: Literal["widget", "link", "page"]
    id: str  # a widget or link id; for "page" the profile key


class ChatRequest(BaseModel):
    context: ChatContext
    session_id: str | None = None
    message: str | None = None  # null = open the chat
    page_version: int
    request_id: str | None = Field(None, max_length=64)  # retries with the same id return the first operation instead of paying twice


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
    k, status, error = store.submit(key=key, company=company, company_id=company_id, role=role, region=region, method=config.NEWS_SEARCH_METHOD)
    return {"key": k, "status": status, "error": error, "cached": status == "ready"}  # ready right at submit = served from the database


@app.get("/api/profile/{key}")
def profile_status(key: str) -> dict:
    row = store.status(key)
    if not row:
        raise HTTPException(404, f"profile {key} not found")
    return {"key": key, "status": row[0], "error": row[1], "stage": row[2], "found": row[3], "selected": row[4]}


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
    """The one entry of the user's feedback. Opening a chat answers at once; a message becomes a queued operation (202), read at /api/feedback/{id}."""
    ctx = req.context
    if ctx.type == "page":
        key, prefix, page = ctx.id, "", store.load_page(ctx.id)
        card = {"text": "Спросите о странице целиком или попросите изменить её.", "basis": [], "followups": []}
        if page is None:
            raise HTTPException(404, f"profile {ctx.id} has no page yet")
    else:
        key, prefix, page = locate(ctx.id)
        card = pages.chat_card(page, ctx.type, ctx.id)
        if card is None:
            raise HTTPException(404, f"{ctx.id} not found")
    session_id = req.session_id or uuid.uuid4().hex
    if req.message is None:
        return {"session_id": session_id, "reply": card, "patch": None}
    if not key:
        return demo_chat(req, prefix, page, session_id)
    message = req.message.strip()
    if not message or len(message) > 4000:
        raise HTTPException(422, "message must be 1..4000 characters")
    if req.page_version != page["version"]:
        raise HTTPException(409, f"page version is {page['version']}, client has {req.page_version}")
    payload = {"context": ctx.model_dump(), "message": message, "session_id": session_id, "page_version": req.page_version}
    op, created = feedback_store.enqueue(key, req.request_id or uuid.uuid4().hex, payload)
    if not created and (op["payload"]["message"], op["payload"]["context"]) != (message, payload["context"]):
        raise HTTPException(409, "request_id was already used for another request")
    response.status_code = 202 if created else 200
    return {"session_id": session_id, "operation_id": op["id"], "status": op["status"]}


@app.get("/api/feedback/{operation_id}")
def feedback_result(operation_id: str) -> dict:
    """Poll until status is not queued/running. result: {scenario, reply, patch, changes, sources, version} or {error, ...}."""
    op = feedback_store.operation(operation_id)
    if op is None:
        raise HTTPException(404, f"operation {operation_id} not found")
    return {"operation_id": op["id"], "status": op["status"], "result": op["result"]}


class UndoRequest(BaseModel):
    page_version: int


@app.post("/api/profile/{key}/undo")
def undo(key: str, req: UndoRequest) -> dict:
    """Restore the page before the last change as a new version. Repeating steps further back (last 20 revisions)."""
    try:
        done = feedback_store.undo(key, req.page_version)
    except feedback_store.Conflict:
        raise HTTPException(409, "page changed, reload it")
    if done is None:
        raise HTTPException(404, "nothing to undo")
    old, restored = done
    ops, changes = feedback_pages.diff(old, restored)
    return {"patch": {"base_version": old["version"], "version": restored["version"], "ops": ops}, "changes": changes, "version": restored["version"]}


def demo_chat(req, prefix, page, session_id):
    """The demo page (no profile): canned edits in memory, as before the feedback queue."""
    ctx = req.context
    if req.page_version != page["version"]:
        raise HTTPException(409, f"page version is {page['version']}, client has {req.page_version}")
    reply_text, ops = pages.edit(page, prefix, ctx.type, ctx.id, req.message)
    patch = None
    if ops:
        page["version"] += 1
        patch = {"base_version": req.page_version, "version": page["version"], "ops": ops}
    return {"session_id": session_id, "reply": {"text": reply_text, "basis": [], "followups": []}, "patch": patch}


if os.path.isdir(config.PAPERS_DIR):
    app.mount("/api/papers", StaticFiles(directory=config.PAPERS_DIR), name="papers")
