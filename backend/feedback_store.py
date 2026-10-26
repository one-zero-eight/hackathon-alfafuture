"""Persistent feedback jobs and optimistic page revisions; all tables belong to backend."""
import logging
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agents import tracing
from backend import journal, store

DDL = """
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS feedback_state jsonb NOT NULL DEFAULT '{}';
CREATE TABLE IF NOT EXISTS feedback_operations (
 id text PRIMARY KEY, profile_key text NOT NULL REFERENCES profiles(key), request_id text,
 run_id text, payload jsonb NOT NULL, status text NOT NULL DEFAULT 'queued', result jsonb,
 created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
 UNIQUE(profile_key,request_id));
ALTER TABLE feedback_operations ALTER COLUMN run_id DROP NOT NULL;
CREATE INDEX IF NOT EXISTS feedback_queue ON feedback_operations(created_at) WHERE status='queued';
CREATE TABLE IF NOT EXISTS profile_revisions (
 profile_key text NOT NULL REFERENCES profiles(key), version int NOT NULL,
 page jsonb NOT NULL, state jsonb NOT NULL, PRIMARY KEY(profile_key,version));
"""


class Conflict(RuntimeError):
    pass


class Missing(RuntimeError):
    pass


def init(conn):
    conn.execute(DDL)
    conn.execute("""UPDATE feedback_operations SET status='failed', finished_at=now(),
                    result='{"error":{"code":"interrupted","message":"Операция прервана. Повторите запрос явно."}}'::jsonb
                    WHERE status='running'""")


def cleanup():
    with store.connect() as conn:
        conn.execute("DELETE FROM feedback_operations WHERE finished_at<now()-interval '7 days'")


def profile(key, conn=None, lock=False):
    if conn is None:
        with store.connect() as conn:
            return profile(key, conn)
    return conn.cursor(row_factory=dict_row).execute(
        "SELECT key,company,company_id,role,region,method,status,page,feedback_state FROM profiles WHERE key=%s" + (" FOR UPDATE" if lock else ""), (key,)).fetchone()


def get(operation_id):
    with store.connect() as conn:
        return conn.cursor(row_factory=dict_row).execute(
            "SELECT id AS operation_id,profile_key,run_id,status,payload->>'session_id' AS session_id,result,created_at,finished_at FROM feedback_operations WHERE id=%s", (operation_id,)).fetchone()


def request_exists(key, request_id):
    with store.connect() as conn:
        return bool(conn.execute("SELECT 1 FROM feedback_operations WHERE profile_key=%s AND request_id=%s", (key, request_id)).fetchone())


def enqueue(key, payload, request_id=None):
    with store.connect() as conn, conn.transaction():
        row = profile(key, conn, lock=True)
        if row is None or row["page"] is None:
            raise Missing("profile page not found")
        if request_id:
            prior = conn.execute("SELECT id,payload FROM feedback_operations WHERE profile_key=%s AND request_id=%s", (key, request_id)).fetchone()
            if prior:
                semantic = lambda p: {k: v for k, v in p.items() if k != "session_id"}
                if semantic(prior[1]) != semantic(payload):
                    raise Conflict("request_id was already used with another request")
                return prior[0]
        if row["status"] != "ready" or row["page"]["version"] != payload["page_version"]:
            raise Conflict("page changed or is rebuilding")
        operation_id = uuid.uuid4().hex
        run_id = None
        try:
            with conn.transaction():
                run_id = journal.create("feedback", tracing.company_ref(row["company_id"] or row["company"]), key, conn)["run_id"]
                conn.execute("UPDATE trace_runs SET status='queued' WHERE id=%s", (run_id,))
        except Exception:
            logging.getLogger("backend.feedback").warning("feedback journal unavailable")
            run_id = None
        conn.execute("INSERT INTO feedback_operations(id,profile_key,request_id,run_id,payload) VALUES (%s,%s,%s,%s,%s)",
                     (operation_id, key, request_id, run_id, Jsonb(payload)))
        return operation_id


def take():
    with store.connect() as conn, conn.transaction():
        row = conn.cursor(row_factory=dict_row).execute("""
          SELECT o.id,o.profile_key,o.run_id,o.payload FROM feedback_operations o JOIN profiles p ON p.key=o.profile_key
          WHERE o.status='queued' AND p.status IN ('ready','failed')
          AND NOT EXISTS (SELECT 1 FROM feedback_operations r WHERE r.profile_key=o.profile_key AND r.status='running')
          ORDER BY o.created_at,o.id LIMIT 1 FOR UPDATE OF p,o SKIP LOCKED""").fetchone()
        if row:
            # Recheck with a fresh READ COMMITTED snapshot after acquiring the profile lock.
            # Another consumer may have committed its claim after the selecting statement began.
            running = conn.execute("SELECT 1 FROM feedback_operations WHERE profile_key=%s AND status='running'", (row["profile_key"],)).fetchone()
            current = conn.execute("SELECT status FROM profiles WHERE key=%s", (row["profile_key"],)).fetchone()
            if running or current[0] not in ("ready", "failed"):
                return None
            conn.execute("UPDATE feedback_operations SET status='running' WHERE id=%s", (row["id"],))
            conn.execute("UPDATE trace_runs SET status='running' WHERE id=%s", (row["run_id"],))
        return row


def snapshot(conn, key, page, state):
    conn.execute("INSERT INTO profile_revisions(profile_key,version,page,state) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                 (key, page["version"], Jsonb(page), Jsonb(state)))
    conn.execute("""DELETE FROM profile_revisions WHERE profile_key=%s AND version NOT IN
                  (SELECT version FROM profile_revisions WHERE profile_key=%s ORDER BY version DESC LIMIT 20)""", (key, key))


def complete(operation, result, page=None, state=None, status="completed"):
    with store.connect() as conn, conn.transaction():
        if page is not None:
            row = profile(operation["profile_key"], conn, lock=True)
            expected = operation["payload"]["page_version"]
            if row["status"] != "ready" or row["page"]["version"] != expected:
                raise Conflict("page changed while processing")
            snapshot(conn, row["key"], row["page"], row["feedback_state"])
            page["version"] = expected + 1
            conn.execute("UPDATE profiles SET page=%s,feedback_state=%s WHERE key=%s", (Jsonb(page), Jsonb(state), row["key"]))
        conn.execute("UPDATE feedback_operations SET status=%s,result=%s,finished_at=now() WHERE id=%s",
                     (status, Jsonb(result), operation["id"]))


def undo(key, current_version, target_version):
    with store.connect() as conn, conn.transaction():
        row = profile(key, conn, lock=True)
        if row is None or row["page"] is None:
            raise Missing("profile page not found")
        if row["status"] != "ready" or row["page"]["version"] != current_version:
            raise Conflict("page changed or is rebuilding")
        target = conn.execute("SELECT page,state FROM profile_revisions WHERE profile_key=%s AND version=%s", (key, target_version)).fetchone()
        if target is None:
            raise Missing("revision not retained")
        snapshot(conn, key, row["page"], row["feedback_state"])
        page, state = target
        page["version"] = current_version + 1
        conn.execute("UPDATE profiles SET page=%s,feedback_state=%s WHERE key=%s", (Jsonb(page), Jsonb(state), key))
        return row["page"], page
