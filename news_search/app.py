"""News search service: POST /search runs one NewsSearch method over the corpus. One search at a time (encoders need the memory)."""
import os
import threading

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agents.client import Agents
from news_search import DEFAULT_METHOD, METHODS, NewsSearch, TooFewNews, postgres_corpus

app = FastAPI(title="News search")
_lock = threading.Lock()
_search: list[NewsSearch] = []


class Request(BaseModel):
    company: str
    line: str
    region: str = ""
    method: str = DEFAULT_METHOD
    anonymised: bool = False  # the company text is a description from bank data, not a name: skip the own-company filter


def search_instance() -> NewsSearch:
    if not _search:
        _search.append(NewsSearch(postgres_corpus(os.environ["DATABASE_URL"]), Agents(), os.environ.get("NEWS_SEARCH_DATA", "/data")))
    return _search[0]


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/methods")
def methods() -> dict:
    return {"methods": list(METHODS), "default": DEFAULT_METHOD}


@app.post("/search")
def search(req: Request) -> dict:
    if req.method not in METHODS:
        raise HTTPException(422, f"method must be one of {list(METHODS)}")
    with _lock:
        try:
            return search_instance().search(req.company, req.line, req.region, req.method, req.anonymised)
        except TooFewNews as e:
            raise HTTPException(422, str(e))
