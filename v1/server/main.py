"""UI API of the v1 stack: the mock contract (mock_server, docs/ENDPOINTS.md) plus live news from the Postgres corpus.

Live news are appended to the "news" column as unlinked widgets (ids `db<article id>`); analytics, decisions
and chat still come from the mock seed. The mock module itself is not modified."""
import datetime
import hashlib
import logging
import os

import psycopg
from fastapi import HTTPException
from pydantic import BaseModel

from mock_server import main as mock

app = mock.app
app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/api/page"]  # replaced below

DATABASE_URL = os.environ["DATABASE_URL"]
# shortcut: the seed company is Газпром, so news are picked by a fixed regex; take it from the user profile once ranking exists
NEWS_REGEX = os.environ.get("NEWS_REGEX", "газпром|газов|нефт|энерг")
NEWS_LIMIT, NEWS_DAYS = int(os.environ.get("NEWS_LIMIT", "12")), int(os.environ.get("NEWS_DAYS", "7"))

QUERY = """
SELECT id, title, url, published_at, name, text FROM (
  SELECT DISTINCT ON (lower(a.title)) a.id, a.title, a.url, a.published_at, s.name, left(a.text, 600) AS text
  FROM articles a JOIN sources s ON s.id = a.source_id
  WHERE a.published_at > now() - make_interval(days => %s) AND a.published_at < now() + interval '1 day' AND a.title ~* %s
  ORDER BY lower(a.title), a.published_at DESC) t
ORDER BY published_at DESC LIMIT %s"""


def refresh_live_news() -> None:
    try:
        with psycopg.connect(DATABASE_URL, connect_timeout=5) as conn:
            rows = conn.execute(QUERY, (NEWS_DAYS, NEWS_REGEX, NEWS_LIMIT)).fetchall()
    except psycopg.Error:
        logging.exception("corpus unavailable, serving the seed only")
        return
    for wid in [w for w in mock.WIDGETS if w.startswith("db")]:
        del mock.WIDGETS[wid]
    for aid, title, url, published, source, text in rows:
        wid = f"db{aid}"
        mock.WIDGETS[wid] = {
            "id": wid, "column": "news", "title": title, "url": url,
            "details": {"text": text or title, "src": source, "date": published.astimezone(datetime.timezone.utc).strftime("%d.%m.%Y")},
            "chat": {"text": f"Новость из корпуса ({source}). Разбор ИИ будет подключён позже.", "basis": [title], "followups": []},
        }


class ProfileRequest(BaseModel):
    company: str
    role: str


PROFILE_IDS: set[str] = set()  # widget and link ids that belong to user profiles (the default page must not show them)
DDL = """CREATE TABLE IF NOT EXISTS v1_profiles (
  key text PRIMARY KEY, company text NOT NULL, role text NOT NULL, status text NOT NULL DEFAULT 'queued',
  error text NOT NULL DEFAULT '', page jsonb, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())"""
# A ready page younger than 24 h is served as is (same TTL as the pipeline cache); anything else is queued again.
UPSERT = """INSERT INTO v1_profiles (key, company, role) VALUES (%s, %s, %s)
  ON CONFLICT (key) DO UPDATE SET status = CASE
      WHEN v1_profiles.status IN ('queued', 'running') THEN v1_profiles.status
      WHEN v1_profiles.status = 'ready' AND v1_profiles.updated_at > now() - interval '24 hours' THEN 'ready'
      ELSE 'queued' END, error = '', updated_at = CASE WHEN v1_profiles.status = 'ready' AND v1_profiles.updated_at > now() - interval '24 hours' THEN v1_profiles.updated_at ELSE now() END
  RETURNING key, status, error"""


def db():
    return psycopg.connect(DATABASE_URL, connect_timeout=5, autocommit=True)


@app.on_event("startup")
def create_tables() -> None:
    with db() as conn:
        conn.execute(DDL)


@app.post("/api/profile")
def set_profile(req: ProfileRequest) -> dict:
    company, role = " ".join(req.company.split()), " ".join(req.role.split())
    if not company or not role or len(company) > 200 or len(role) > 200:
        raise HTTPException(422, "company and role must be non-empty and at most 200 characters")
    key = hashlib.sha1(f"{company.lower()}|{role.lower()}".encode()).hexdigest()[:12]
    with db() as conn:
        k, status, error = conn.execute(UPSERT, (key, company, role)).fetchone()
    return {"key": k, "status": status, "error": error}


@app.get("/api/profile/{key}")
def profile_status(key: str) -> dict:
    with db() as conn:
        row = conn.execute("SELECT status, error FROM v1_profiles WHERE key = %s", (key,)).fetchone()
    if not row:
        raise HTTPException(404, f"profile {key} not found")
    return {"key": key, "status": row[0], "error": row[1]}


@app.get("/api/page")
def page(profile: str | None = None) -> dict:
    if profile:
        with db() as conn:
            row = conn.execute("SELECT page FROM v1_profiles WHERE key = %s AND page IS NOT NULL", (profile,)).fetchone()
        if not row:
            raise HTTPException(404, f"profile {profile} has no page yet")
        data = row[0]
        for w in data["widgets"]:
            mock.WIDGETS[w["id"]] = w
        for l in data["links"]:
            mock.LINKS[l["id"]] = l
        PROFILE_IDS.update(w["id"] for w in data["widgets"])
        PROFILE_IDS.update(l["id"] for l in data["links"])
        widgets, links, company = data["widgets"], data["links"], data["company"]
    else:
        refresh_live_news()
        widgets = [w for w in mock.WIDGETS.values() if w["id"] not in PROFILE_IDS]
        links = [l for l in mock.LINKS.values() if l["id"] not in PROFILE_IDS]
        company = mock.SEED["company"]
    return {"version": mock.STATE["version"], "company": company,
            "widgets": [{k: w[k] for k in ("id", "column", "title", "url", "tags") if k in w} for w in widgets],
            "links": [{k: l[k] for k in ("id", "from", "to")} for l in links]}
