"""Profiles (a company + a role line = one request) and their finished pages, in PostgreSQL.

status: queued -> running -> ready | failed. The page is a jsonb: {version, company, widgets, links, meta}.
"""

import psycopg

from agents import tracing
from psycopg.types.json import Jsonb

from backend import config

DDL = """CREATE TABLE IF NOT EXISTS profiles (
  key text PRIMARY KEY, company text NOT NULL, company_id text NOT NULL DEFAULT '', role text NOT NULL, region text NOT NULL DEFAULT '',
  method text NOT NULL, status text NOT NULL DEFAULT 'queued', error text NOT NULL DEFAULT '', page jsonb,
  created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())"""
# Progress of a running profile for the UI timeline: stage search -> rank -> analysis, with the news counts known at that stage.
MIGRATE = """ALTER TABLE profiles ADD COLUMN IF NOT EXISTS stage text NOT NULL DEFAULT 'search',
  ADD COLUMN IF NOT EXISTS news_found int, ADD COLUMN IF NOT EXISTS news_selected int, ADD COLUMN IF NOT EXISTS run_id text"""
# A ready page younger than the TTL is served as is; anything else (failed, stale) goes to the queue again.
SUBMIT = """INSERT INTO profiles (key, company, company_id, role, region, method) VALUES (%(key)s, %(company)s, %(company_id)s, %(role)s, %(region)s, %(method)s)
  ON CONFLICT (key) DO UPDATE SET status = CASE
      WHEN profiles.status IN ('queued', 'running') THEN profiles.status
      WHEN profiles.status = 'ready' AND profiles.updated_at > now() - make_interval(hours => %(ttl)s) THEN 'ready'
      ELSE 'queued' END, error = '',
    updated_at = CASE WHEN profiles.status = 'ready' AND profiles.updated_at > now() - make_interval(hours => %(ttl)s) THEN profiles.updated_at ELSE now() END
  RETURNING key, status, error, run_id"""
TAKE = """UPDATE profiles SET status = 'running', stage = 'search', news_found = NULL, news_selected = NULL, updated_at = now()
  WHERE key = (SELECT key FROM profiles WHERE status = 'queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
  RETURNING key, company, company_id, role, region, method, run_id"""


def connect():
    return psycopg.connect(config.DATABASE_URL, connect_timeout=5, autocommit=True)


def init() -> None:
    with connect() as conn:
        conn.execute(DDL)
        conn.execute(MIGRATE)
        from backend import journal, feedback_store
        feedback_store.init(conn)
        journal.init(conn)
        conn.execute("UPDATE profiles SET status = 'queued', run_id = NULL WHERE status = 'running'")


def submit(force=False, **fields):
    from backend import journal
    with connect() as conn, conn.transaction():
        row = conn.execute(SUBMIT, {**fields, "ttl": 0 if force else config.PROFILE_TTL_HOURS}).fetchone()
        key, state, error, run_id = row
        active = conn.execute("SELECT status FROM trace_runs WHERE id=%s", (run_id,)).fetchone() if run_id else None
        if state == "queued" and (active is None or active[0] not in ("queued", "running")):
            run_id = journal.create("profile", tracing.company_ref(fields["company_id"] or fields["company"]), key, conn)["run_id"]
            conn.execute("UPDATE profiles SET run_id=%s WHERE key=%s", (run_id, key))
        return key, state, error, run_id


def status(key: str):
    with connect() as conn:
        return conn.execute("SELECT status, error, stage, news_found, news_selected, run_id FROM profiles WHERE key = %s", (key,)).fetchone()


def progress(key: str, stage: str, found: int | None = None, selected: int | None = None) -> None:
    with connect() as conn:
        conn.execute("UPDATE profiles SET stage = %s, news_found = coalesce(%s, news_found), news_selected = coalesce(%s, news_selected) WHERE key = %s",
                     (stage, found, selected, key))


def take():
    from backend import journal
    with connect() as conn, conn.transaction():
        row = conn.execute(TAKE).fetchone()
        if row:
            *fields, run_id = row
            if not run_id:
                run_id = journal.create("profile", tracing.company_ref(row[2] or row[1]), row[0], conn)["run_id"]
                conn.execute("UPDATE profiles SET run_id=%s WHERE key=%s", (run_id, row[0]))
            conn.execute("UPDATE trace_runs SET status='running' WHERE id=%s", (run_id,))
            return (*fields, run_id)
        return None


def finish(key: str, page: dict, expected_version=None) -> None:
    from backend import feedback_pages as fp, feedback_store as fs
    with connect() as conn, conn.transaction():
        row = fs.profile(key, conn, lock=True)
        if expected_version is not None and (row["page"] or {}).get("version", 0) != expected_version:
            raise fs.Conflict("page changed during generation")
        news = page.get("meta", {}).get("news", [])
        state = fp.initial_state(row["page"], row["feedback_state"]) if row["page"] else {}
        if row["page"]:
            fs.snapshot(conn, key, row["page"], row["feedback_state"])
            incoming_meta = page.get("meta", {})
            page = fp.compose(key, row["page"], page, news, state, replace=True)
            page["meta"].update(incoming_meta)
            page["version"] = row["page"]["version"] + 1
        else:
            state = fp.initial_state(page, news=news)
        fp.compact(page, state)
        page.get("meta", {}).pop("news", None)
        conn.execute("UPDATE profiles SET status='ready', page=%s, feedback_state=%s, error='', updated_at=now() WHERE key=%s",
                     (Jsonb(page), Jsonb(state), key))


def fail(key: str, error: str) -> None:
    with connect() as conn:
        conn.execute("UPDATE profiles SET status = 'failed', error = %s, updated_at = now() WHERE key = %s", (error[:500], key))


def load_page(key: str):
    with connect() as conn:
        row = conn.execute("SELECT page FROM profiles WHERE key = %s AND page IS NOT NULL", (key,)).fetchone()
    return row[0] if row else None


def save_page(key: str, page: dict) -> None:
    """Chat edits. shortcut: last write wins; add a version check here if two people edit one page at once."""
    with connect() as conn:
        conn.execute("UPDATE profiles SET page = %s WHERE key = %s", (Jsonb(page), key))


