"""Backend-owned run journal, public projection, retention, and constrained descriptions."""
import logging
import hashlib
import secrets
import uuid

from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from agents import tracing
from backend import store

log = logging.getLogger("backend.journal")

DDL = """
CREATE TABLE IF NOT EXISTS trace_runs (
  id text PRIMARY KEY, profile_key text, company_ref text NOT NULL, kind text NOT NULL,
  capability_hash text NOT NULL, status text NOT NULL DEFAULT 'queued', incomplete boolean NOT NULL DEFAULT false,
  created_at timestamptz NOT NULL DEFAULT now(), finished_at timestamptz,
  descriptions jsonb, describing_at timestamptz);
CREATE INDEX IF NOT EXISTS trace_runs_profile ON trace_runs(profile_key, created_at DESC);
CREATE TABLE IF NOT EXISTS trace_events (
  seq bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, run_id text NOT NULL REFERENCES trace_runs(id) ON DELETE CASCADE,
  event_id text NOT NULL, event jsonb NOT NULL, UNIQUE(run_id, event_id));
CREATE INDEX IF NOT EXISTS trace_events_run ON trace_events(run_id, seq);
"""
LABELS = {"run": "Выполнение запроса", "queued": "Запрос поставлен в очередь", "profile": "Подготовка профиля",
          "queries": "Поисковые запросы", "needs": "Потребности компании", "hyde": "Поисковые гипотезы",
          "search": "Поиск новостей", "retrieval": "Поиск кандидатов", "deduplication": "Удаление повторов и новостей о самой компании",
          "ranking": "Отбор новостей", "analytics": "Анализ источников", "decision": "Подготовка решений",
          "verification": "Проверка выводов", "publication": "Подготовка страницы", "chat": "Обработка обращения",
          "cache": "Использование кэша", "refine": "Дополнительный поиск", "description": "Описание журнала"}
COUNT_LABELS = {"before": "до", "after": "после", "duplicates": "повторов", "own_removed": "о самой компании",
                "selected": "отобрано", "queries": "запросов", "notes": "обоснований", "decisions": "решений",
                "claims": "выводов", "unsupported": "не подтверждено", "excluded": "исключено", "removed": "удалено", "regional": "региональных"}


def init(conn):
    conn.execute(DDL)
    conn.execute("UPDATE trace_runs SET status='failed', incomplete=true, finished_at=now() WHERE status='running'")
    conn.execute("UPDATE trace_runs SET describing_at=NULL WHERE describing_at IS NOT NULL")
    cleanup(conn)


def cleanup(conn=None):
    if conn is None:
        with store.connect() as conn:
            return cleanup(conn)
    conn.execute("DELETE FROM trace_runs WHERE finished_at < now() - interval '7 days' AND describing_at IS NULL")


def create(kind, company_ref, profile_key=None, conn=None):
    if conn is None:
        with store.connect() as conn, conn.transaction():
            return create(kind, company_ref, profile_key, conn)
    run_id, capability = uuid.uuid4().hex, secrets.token_urlsafe(32)
    conn.execute("INSERT INTO trace_runs(id, profile_key, company_ref, kind, capability_hash, status) VALUES (%s,%s,%s,%s,%s,%s)",
                 (run_id, profile_key, company_ref, kind, digest(capability), "queued" if kind == "profile" else "running"))
    record(run_id, tracing.Event(section="backend", step="queued"), conn)
    return {"run_id": run_id, "capability": capability}


def digest(capability):
    return hashlib.sha256(capability.encode()).hexdigest()


def authorised(run_id, capability):
    with store.connect() as conn:
        row = conn.execute("SELECT capability_hash FROM trace_runs WHERE id=%s", (run_id,)).fetchone()
    return bool(row and secrets.compare_digest(row[0], digest(capability)))


def context(run_id):
    # Only the backend can rotate a capability; persisted journals contain its hash, never its value.
    capability = secrets.token_urlsafe(32)
    with store.connect() as conn:
        row = conn.execute("UPDATE trace_runs SET capability_hash=%s WHERE id=%s RETURNING id", (digest(capability), run_id)).fetchone()
    if row is None:
        return None
    return tracing.Trace(run_id, capability, "backend", sender=lambda event: record(run_id, event))


def record(run_id, event, conn=None):
    if conn is None:
        with store.connect() as conn:
            return record(run_id, event, conn)
    conn.execute("INSERT INTO trace_events(run_id,event_id,event) VALUES (%s,%s,%s) ON CONFLICT(run_id,event_id) DO NOTHING",
                 (run_id, event.event_id, Jsonb(event.model_dump(mode="json"))))


def finish(run_id, status, incomplete=False, conn=None):
    if conn is None:
        with store.connect() as conn:
            return finish(run_id, status, incomplete, conn)
    conn.execute("UPDATE trace_runs SET status=%s, finished_at=now(), incomplete=incomplete OR %s WHERE id=%s AND finished_at IS NULL",
                 (status, incomplete, run_id))


def safe_context(run_id):
    try:
        return context(run_id)
    except Exception:
        log.warning("journal context unavailable run=%s", run_id)
        return tracing.Trace(run_id, "", "backend", sender=lambda event: record(run_id, event), incomplete=True)


def safe_finish(run_id, status, incomplete=False):
    try:
        finish(run_id, status, incomplete)
    except Exception:
        log.warning("journal completion unavailable run=%s", run_id)
        try:
            with store.connect() as conn:
                conn.execute("UPDATE trace_runs SET incomplete=true WHERE id=%s", (run_id,))
        except Exception:
            pass  # The next startup marks the interrupted run incomplete.


def run_cleanup(stop):
    while not stop.wait(60):
        try:
            cleanup()
            from backend import feedback_store
            feedback_store.cleanup()
        except Exception:
            log.warning("journal cleanup unavailable")


def get(run_id):
    with store.connect() as conn:
        return conn.cursor(row_factory=dict_row).execute(
            "SELECT id AS run_id,profile_key,status,incomplete,created_at,finished_at,descriptions FROM trace_runs WHERE id=%s", (run_id,)).fetchone()


def profile_company_ref(profile_key):
    with store.connect() as conn:
        row = conn.execute("SELECT company_id,company FROM profiles WHERE key=%s", (profile_key,)).fetchone()
    return tracing.company_ref((row[0] or row[1]) if row else profile_key)


def runs(profile_key):
    with store.connect() as conn:
        return conn.cursor(row_factory=dict_row).execute(
            "SELECT id AS run_id,status,incomplete,created_at,finished_at FROM trace_runs WHERE profile_key=%s ORDER BY created_at DESC,id", (profile_key,)).fetchall()


def text(event, phrasing="detail", facts=("counts", "queries", "sources")):
    label = LABELS.get(event["step"], "Шаг системы")
    status = {"started": "начат", "completed": "завершён", "failed": "ошибка", "cached": "из кэша", "skipped": "пропущен"}[event["status"]]
    parts = [f"{label}: {status}." if phrasing == "detail" else f"{label} ({status})."]
    if "counts" in facts and event.get("counts"):
        parts.append("; ".join(f"{COUNT_LABELS[k]}: {v}" for k, v in event["counts"].items()) + ".")
    if "queries" in facts and event.get("queries"):
        parts.append("Запросы: " + "; ".join(event["queries"]) + ".")
    if "sources" in facts and event.get("source_ids"):
        parts.append("Источники: " + ", ".join(event["source_ids"]) + ".")
    return " ".join(parts)


def public(event, descriptions=None):
    if event["step"] in ("llm", "gateway"):
        return None
    visible = {k: v for k, v in event.items() if k not in ("agent", "model", "attempt", "usage")}
    visible["text"] = (descriptions or {}).get(event["event_id"]) or text(event)
    return visible


def events(run_id, after=0, limit=100, descriptions=None):
    with store.connect() as conn:
        rows = conn.execute("""SELECT seq,event FROM trace_events WHERE run_id=%s AND seq>%s
                              AND event->>'step' NOT IN ('llm','gateway') ORDER BY seq LIMIT %s""", (run_id, after, limit)).fetchall()
    return [{"cursor": seq, **public(event, descriptions)} for seq, event in rows]


def description_input(run_id):
    with store.connect() as conn:
        # Only completed public steps are narrated. One bounded batch keeps prompt and output costs finite.
        rows = conn.execute("""SELECT event FROM trace_events WHERE run_id=%s AND event->>'step' NOT IN ('llm','gateway','description')
                              AND event->>'status'<>'started' ORDER BY seq LIMIT 40""", (run_id,)).fetchall()
    return [public(row[0]) for row in rows]


def validate_descriptions(answer, inputs):
    items = answer.get("descriptions")
    expected = {event["event_id"]: event for event in inputs}
    if not isinstance(items, list) or len(items) != len(expected):
        raise ValueError("description count mismatch")
    result = {}
    for item in items:
        if not isinstance(item, dict) or set(item) != {"event_id", "phrasing", "facts"}:
            raise ValueError("invalid description fields")
        eid, phrasing, facts = item["event_id"], item["phrasing"], item["facts"]
        if not isinstance(eid, str) or not isinstance(phrasing, str) or eid not in expected or eid in result or phrasing not in ("compact", "detail"):
            raise ValueError("invalid description reference")
        if not isinstance(facts, list) or any(f not in ("counts", "queries", "sources") for f in facts):
            raise ValueError("invalid description facts")
        required = {name for name, key in (("counts", "counts"), ("queries", "queries"), ("sources", "source_ids")) if expected[eid].get(key)}
        if not required <= set(facts) or len(facts) != len(set(facts)):
            raise ValueError("description omits event facts")
        result[eid] = text(expected[eid], phrasing, facts)
    return result


def claim_descriptions(run_id):
    with store.connect() as conn:
        return bool(conn.execute("""UPDATE trace_runs SET describing_at=now() WHERE id=%s AND finished_at IS NOT NULL
                                 AND descriptions IS NULL AND (describing_at IS NULL OR describing_at<now()-interval '5 minutes') RETURNING id""",
                                 (run_id,)).fetchone())


def save_descriptions(run_id, descriptions):
    with store.connect() as conn:
        conn.execute("UPDATE trace_runs SET descriptions=%s, describing_at=NULL WHERE id=%s", (Jsonb(descriptions) if descriptions is not None else None, run_id))
