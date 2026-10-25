"""Analytics service: search results + company profile -> page of news, analytics and decisions with traceable evidence."""
import logging
import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.client import Agents
from agents import tracing
from analytics.alfa import load_theses
from analytics.chain import EVENTS, ROLES, make_page, reply

logging.basicConfig(level=logging.INFO)
app = FastAPI(title="Analytics")
tracing.install(app, "analytics", ("/page", "/reply"))
_lock = threading.Lock()  # one page at a time: the encoder for bank theses needs the memory


class PageRequest(BaseModel):
    profile: dict  # label, okved, okved_code, okved_name, region, products, products_ru, facts, date_label (all optional)
    role: str = "CFO"  # a playbook id from data/roles.json
    sphere: str = ""
    news: list[dict]  # `top` of a news_search result
    pairs: list[list[int]] = []
    triz: bool = True
    limit: int = EVENTS


class ReplyRequest(BaseModel):
    question: str
    widget: dict
    facts: str = ""


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post("/page")
def page(req: PageRequest) -> dict:
    if not req.news:
        raise HTTPException(422, "news must not be empty")
    if req.role not in ROLES:
        raise HTTPException(422, f"role must be one of {sorted(ROLES)}")
    with _lock:
        try:
            return make_page(Agents(), req.profile, req.role, req.sphere, req.news, req.pairs, load_theses(), req.triz, req.limit)
        except RuntimeError as e:
            raise HTTPException(502, str(e))


@app.post("/reply")
def answer(req: ReplyRequest) -> dict:
    try:
        return reply(Agents(), req.question, req.widget, req.facts)
    except RuntimeError as e:
        raise HTTPException(502, str(e))
