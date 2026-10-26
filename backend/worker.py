"""Orchestration of one profile: company data -> news_search -> analytics -> page. Runs in a thread of the backend process."""
import hashlib
import logging
import re
import threading
import time

import httpx

from backend import config, feedback_pages, pages, store
from backend.companies import NAMED_LOCALITY, CompanyBook, CompanyUnavailable
from backend.focus import interpret, page_key_bits

log = logging.getLogger("backend.worker")
COMPANY_ID = re.compile(r"U_\d+")
book = CompanyBook()


class ProfileError(RuntimeError):
    """A failure the user can read: it becomes the profile's error text."""


def profile_key(company: str, company_id: str, role: str, region: str, method: str) -> str:
    """Same company, same canonical role/sphere, same region, same search method -> same page."""
    raw = f"{company_id or company.lower()}|{page_key_bits(interpret(role))}|{region.lower()}|{method}"
    return hashlib.sha1(raw.encode()).hexdigest()[:12]


def _post(url: str, body: dict, what: str) -> dict:
    try:
        r = httpx.post(url, json=body, timeout=config.REQUEST_TIMEOUT)
    except httpx.HTTPError as e:
        raise ProfileError(f"{what} is unreachable: {e!r}") from e
    if r.status_code != 200:
        raise ProfileError(f"{what}: HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def prepare_profile(company, company_id, role, region):
    """(analytics profile, company text for the search, region). An anonymised bank record gives the description, region and products from the data."""
    if company_id:
        try:
            profile = book.profile(company_id)
        except CompanyUnavailable as e:
            raise ProfileError(str(e)) from e
        return profile, profile["description"], profile["region"]
    return {"label": company, "region": region, "locality": NAMED_LOCALITY}, company, region


def build_page(key: str, company: str, company_id: str, role: str, region: str, method: str) -> tuple[dict, dict]:
    """(page, feedback state): the state remembers which article each news widget was written from."""
    focus = interpret(role)
    profile, query_company, region = prepare_profile(company, company_id, role, region)
    store.progress(key, "search")
    found = _post(f"{config.NEWS_SEARCH_URL}/search", {"company": query_company, "line": role, "region": region, "method": method,
                                                        "anonymised": bool(company_id), "locality": profile["locality"]}, "news_search")
    stats = found.get("stats", {})
    # shortcut: news_search ranks inside one /search call, so "rank" is only reported once it returns; upgrade when /search streams progress
    store.progress(key, "rank", stats.get("candidates") or stats.get("unique") or len(found["top"]))
    store.progress(key, "analysis", selected=len(found["top"]))
    page = _post(f"{config.ANALYTICS_URL}/page", {"profile": profile, "role": focus.role or "CFO", "sphere": focus.sphere,
                                                  "news": found["top"], "pairs": found["pairs"]}, "analytics")
    meta = {"method": method, "search_cost": found["cost"], "search_stats": found.get("stats", {}), "facts": profile.get("facts", ""), "journal": page.get("journal", [])}
    published = pages.publish(key, page, meta)
    return published, feedback_pages.initial_state(published, found["top"])


def run_once() -> bool:
    row = store.take()
    if not row:
        return False
    key, company, company_id, role, region, method = row
    log.info("profile %s: %r / %r / %r via %s", key, company or company_id, role, region, method)
    try:
        store.finish(key, *build_page(key, company, company_id, role, region, method))
        log.info("profile %s: ready", key)
    except Exception as e:  # any failure is reported on the profile, the loop goes on
        log.exception("profile %s failed", key)
        store.fail(key, str(e) if isinstance(e, ProfileError) else repr(e))
    return True


def run_forever(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            if run_once():
                continue
        except Exception:
            log.exception("worker step failed")
        stop.wait(3)
