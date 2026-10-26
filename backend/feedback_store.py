"""PostgreSQL side of the feedback: the operation queue, the user's state of a profile, page revisions (last 20) and undo.

operation status: queued -> running -> completed | needs_clarification | blocked | failed | conflict. A paid run is never retried after
a failure: an operation found `running` after a restart becomes `failed`.
"""

import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from backend import store

DDL = """
ALTER TABLE profiles ADD COLUMN IF NOT EXISTS feedback_state jsonb;
CREATE TABLE IF NOT EXISTS feedback_operations (
  id text PRIMARY KEY, profile_key text NOT NULL, request_id text NOT NULL, payload jsonb, status text NOT NULL DEFAULT 'queued',
  result jsonb, created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz, UNIQUE(profile_key, request_id));
CREATE INDEX IF NOT EXISTS feedback_queue ON feedback_operations(created_at) WHERE status = 'queued';
CREATE TABLE IF NOT EXISTS page_revisions (
  id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, profile_key text NOT NULL, version int NOT NULL, page jsonb NOT NULL, state jsonb,
  created_at timestamptz NOT NULL DEFAULT now());
CREATE INDEX IF NOT EXISTS page_revisions_profile ON page_revisions(profile_key, id DESC);
"""
KEEP_REVISIONS, KEEP_DAYS = 20, 7


class Conflict(RuntimeError):
    pass


def init(conn):
    conn.execute(DDL)
    conn.execute(
        "UPDATE feedback_operations SET status='failed', finished_at=now(), result=%s WHERE status='running'",
        (
            Jsonb(
                {
                    "error": {
                        "code": "interrupted",
                        "message": "Обработка прервана перезапуском. Повторите запрос.",
                    },
                    "patch": None,
                }
            ),
        ),
    )


def cleanup():
    """Finished operations and their inputs live 7 days."""
    with store.connect() as conn:
        conn.execute(
            "DELETE FROM feedback_operations WHERE finished_at < now() - make_interval(days => %s)",
            (KEEP_DAYS,),
        )


def enqueue(profile_key: str, request_id: str, payload: dict):
    """(operation, created). The same (profile, request_id) returns the first operation: a retried request does not pay twice."""
    with store.connect() as conn, conn.transaction():
        cur = conn.cursor(row_factory=dict_row)
        row = cur.execute(
            "INSERT INTO feedback_operations(id, profile_key, request_id, payload) VALUES (%s,%s,%s,%s) "
            "ON CONFLICT(profile_key, request_id) DO NOTHING RETURNING id, status",
            (uuid.uuid4().hex, profile_key, request_id, Jsonb(payload)),
        ).fetchone()
        if row is None:
            return cur.execute(
                "SELECT id, status, payload FROM feedback_operations WHERE profile_key=%s AND request_id=%s",
                (profile_key, request_id),
            ).fetchone(), False
        return row, True


def take():
    with store.connect() as conn, conn.transaction():
        return (
            conn.cursor(row_factory=dict_row)
            .execute(
                "UPDATE feedback_operations SET status='running' WHERE id = (SELECT id FROM feedback_operations WHERE status='queued' "
                "ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED) RETURNING id, profile_key, payload"
            )
            .fetchone()
        )


def operation(op_id: str):
    with store.connect() as conn:
        return (
            conn.cursor(row_factory=dict_row)
            .execute(
                "SELECT id, profile_key, status, result, created_at, finished_at FROM feedback_operations WHERE id=%s",
                (op_id,),
            )
            .fetchone()
        )


def profile(key: str):
    with store.connect() as conn:
        return (
            conn.cursor(row_factory=dict_row)
            .execute(
                "SELECT key, company, company_id, role, region, method, status, page, feedback_state FROM profiles WHERE key=%s",
                (key,),
            )
            .fetchone()
        )


def complete(
    op: dict,
    result: dict,
    status: str = "completed",
    page: dict | None = None,
    state: dict | None = None,
) -> None:
    """Finish the operation; with a page, publish it in the same transaction if its version is still the one the work started from."""
    with store.connect() as conn, conn.transaction():
        if page is not None:
            publish(conn, op["profile_key"], page, state, page["version"] - 1)
        conn.execute(
            "UPDATE feedback_operations SET status=%s, result=%s, finished_at=now() WHERE id=%s",
            (status, Jsonb(result), op["id"]),
        )


def publish(conn, key: str, page: dict, state: dict | None, base_version: int) -> None:
    row = conn.execute(
        "SELECT page, feedback_state FROM profiles WHERE key=%s FOR UPDATE", (key,)
    ).fetchone()
    if row is None or row[0] is None or row[0]["version"] != base_version:
        raise Conflict("page changed before publication")
    conn.execute(
        "INSERT INTO page_revisions(profile_key, version, page, state) VALUES (%s,%s,%s,%s)",
        (key, base_version, Jsonb(row[0]), Jsonb(row[1]) if row[1] else None),
    )
    conn.execute(
        "DELETE FROM page_revisions WHERE profile_key=%s AND id NOT IN (SELECT id FROM page_revisions WHERE profile_key=%s ORDER BY id DESC LIMIT %s)",
        (key, key, KEEP_REVISIONS),
    )
    conn.execute(
        "UPDATE profiles SET page=%s, feedback_state=%s WHERE key=%s",
        (
            Jsonb(page),
            Jsonb(state) if state is not None else row[1] and Jsonb(row[1]),
            key,
        ),
    )


def undo(key: str, base_version: int):
    """Restore the latest revision as a NEW version (repeated undo steps further back). Returns (old page, new page) or None when there is nothing to undo."""
    with store.connect() as conn, conn.transaction():
        cur = conn.execute(
            "SELECT page, feedback_state FROM profiles WHERE key=%s FOR UPDATE", (key,)
        ).fetchone()
        if cur is None or cur[0] is None:
            return None
        if cur[0]["version"] != base_version:
            raise Conflict("page changed")
        rev = conn.execute(
            "DELETE FROM page_revisions WHERE id = (SELECT max(id) FROM page_revisions WHERE profile_key=%s) RETURNING page, state",
            (key,),
        ).fetchone()
        if rev is None:
            return None
        restored = {**rev[0], "version": cur[0]["version"] + 1}
        conn.execute(
            "UPDATE profiles SET page=%s, feedback_state=%s WHERE key=%s",
            (Jsonb(restored), Jsonb(rev[1]) if rev[1] else None, key),
        )
        return cur[0], restored
