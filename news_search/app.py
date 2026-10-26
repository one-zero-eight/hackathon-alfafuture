"""News search service: POST /search runs one NewsSearch method over the corpus. One search at a time (encoders need the memory)."""

import logging
import os
import threading
import time

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

from agents.client import Agents
from news_search.cache import PgCache
from news_search import DEFAULT_METHOD, METHODS, NewsSearch, TooFewNews, postgres_corpus
from news_search.search import NONLOCAL_WEIGHT, REFINE_LIMIT

log = logging.getLogger("uvicorn.error")
app = FastAPI(title="News search")
_lock = threading.Lock()
_search: list[NewsSearch] = []


class Request(BaseModel):
    company: str
    line: str
    region: str = ""
    method: str = DEFAULT_METHOD
    anonymised: bool = False  # the company text is a description from bank data, not a name: skip the own-company filter
    locality: float | None = Field(
        None, ge=0, le=1
    )  # 0..1 from the company's size (backend); a large company gets more federal news


class RefineRequest(BaseModel):
    company: str
    line: str
    region: str = ""
    kind: str
    text: str
    exclude_aids: list[int] = []
    removed_aids: list[int] = []
    limit: int = Field(REFINE_LIMIT, ge=1, le=30)
    method: str = DEFAULT_METHOD
    anonymised: bool = False
    page_line: str | None = (
        None  # perspective: the page's line/region when line/region carry the new ones
    )
    page_region: str | None = None


def search_instance() -> NewsSearch:
    if not _search:
        url = os.environ["DATABASE_URL"]
        _search.append(
            NewsSearch(
                postgres_corpus(url),
                Agents(),
                os.environ.get("NEWS_SEARCH_DATA", "/data"),
                cache=PgCache(url),
            )
        )
        _search[0].nonlocal_weight = float(
            os.environ.get("NEWS_SEARCH_NONLOCAL_WEIGHT", NONLOCAL_WEIGHT)
        )
    return _search[0]


def embed_loop(every: float) -> None:
    """Embed new corpus articles at start and then every `every` seconds, so a search never meets a backlog."""
    while True:
        try:
            with (
                _lock
            ):  # the vector file has one writer at a time: this loop or a search
                added = search_instance().embed_corpus()
            if added:
                log.info("embedded %d new articles", added)
        except Exception:
            log.exception("background embedding failed")
        time.sleep(every)


@app.on_event("startup")
def start_embedding() -> None:
    every = float(os.environ.get("NEWS_SEARCH_EMBED_EVERY", 900))
    if every > 0:
        threading.Thread(target=embed_loop, args=(every,), daemon=True).start()


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
            return search_instance().search(
                req.company,
                req.line,
                req.region,
                req.method,
                req.anonymised,
                req.locality,
            )
        except TooFewNews as e:
            raise HTTPException(422, str(e))


@app.post("/refine")
def refine(req: RefineRequest) -> dict:
    if req.method != "dense_xquad":
        raise HTTPException(422, "only dense_xquad supports refine")
    with _lock:
        try:
            return search_instance().refine(
                req.company,
                req.line,
                req.kind,
                req.text,
                req.region,
                req.exclude_aids,
                req.removed_aids,
                req.limit,
                req.anonymised,
                req.page_line,
                req.page_region,
            )
        except ValueError as e:
            raise HTTPException(422, str(e))
