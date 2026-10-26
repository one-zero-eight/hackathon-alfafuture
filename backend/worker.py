"""Orchestration of one profile: company data -> news_search -> analytics -> page. Runs in a thread of the backend process."""
import hashlib
import logging
import re
import threading
import time

import httpx

from backend import config, feedback_pages, pages, store, journal
from agents import tracing
from backend.companies import CompanyBook, CompanyUnavailable
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
        r = httpx.post(url, json=body, headers=tracing.headers(), timeout=config.REQUEST_TIMEOUT)
        tracing.observe(r)
    except httpx.HTTPError as e:
        if tracing.CURRENT.get():
            tracing.CURRENT.get().mark_incomplete()
        raise ProfileError(f"{what} is unreachable: {e!r}") from e
    if r.status_code != 200:
        raise ProfileError(f"{what}: HTTP {r.status_code}: {r.text[:300]}")
    return r.json()


def build_page(key: str, company: str, company_id: str, role: str, region: str, method: str) -> tuple[dict, dict]:
    """(page, feedback state): the state remembers which article each news widget was written from."""
    with tracing.span("profile"):
        profile, query_company, region = prepare_profile(company, company_id, role, region)
    focus = interpret(role)
    store.progress(key, "search")
    with tracing.span("search") as event:
        found = _post(f"{config.NEWS_SEARCH_URL}/search", {"company": query_company, "line": role, "region": region, "method": method, "anonymised": bool(company_id)}, "news_search")
        event["counts"] = {"selected": len(found["top"])}
    stats = found.get("stats", {})
    store.progress(key, "rank", stats.get("candidates") or stats.get("unique") or len(found["top"]))
    store.progress(key, "analysis", selected=len(found["top"]))
    with tracing.span("analytics") as event:
        page = _post(f"{config.ANALYTICS_URL}/page", {"profile": profile, "role": focus.role or "CFO", "sphere": focus.sphere, "news": found["top"], "pairs": found["pairs"]}, "analytics")
        event["counts"] = {"after": sum(w["column"] == "analytics" for w in page["widgets"]), "decisions": sum(w["column"] == "decisions" for w in page["widgets"])}
    meta = {"method": method, "search_cost": found["cost"], "search_stats": stats, "facts": profile.get("facts", ""), "journal": page.get("journal", [])}
    with tracing.span("publication") as event:
        published = pages.publish(key, page, meta)
        event["widget_ids"] = [w["id"] for w in published["widgets"]][:200]
        return published, feedback_pages.initial_state(published, found["top"])


def prepare_profile(company, company_id, role, region):
    if company_id:  # anonymised bank record: the description, region and products come from the data, not from the user
        try:
            profile = book.profile(company_id)
        except CompanyUnavailable as e:
            raise ProfileError(str(e)) from e
        query_company, region = profile["description"], profile["region"]
    else:
        profile = {"label": company, "region": region}
        query_company = company
    return profile, query_company, region


def run_once() -> bool:
    row = store.take()
    if not row:
        return False
    key, company, company_id, role, region, method, run_id = row
    trace = journal.safe_context(run_id)
    log.info("profile %s: %r / %r / %r via %s", key, company or company_id, role, region, method)
    try:
        with tracing.activate(trace), tracing.span("run"):
            store.finish(key, *build_page(key, company, company_id, role, region, method))
        journal.safe_finish(run_id, "completed", trace.incomplete)
        log.info("profile %s: ready", key)
    except Exception as e:  # any failure is reported on the profile, the loop goes on
        log.exception("profile %s failed", key)
        store.fail(key, str(e) if isinstance(e, ProfileError) else repr(e))
        journal.safe_finish(run_id, "failed", trace.incomplete)
    return True


def run_forever(stop: threading.Event) -> None:
    while not stop.is_set():
        try:
            if run_once():
                continue
        except Exception:
            log.exception("worker step failed")
        stop.wait(3)
