"""Reading the news corpus (tables sources and articles, filled by the collector) from PostgreSQL."""
from email.utils import format_datetime

import psycopg

ROWS = """SELECT a.id, a.title, a.url, a.published_at, s.name, left(a.text, 300), s.id FROM articles a JOIN sources s ON s.id = a.source_id
WHERE a.published_at IS NULL OR a.published_at > now() - make_interval(days => %s)"""


def postgres_corpus(database_url):
    """Returns load(days) -> feed-like items of the last `days` days (undated ones too); ~100-150k titles fit in memory."""
    def load(days):
        with psycopg.connect(database_url) as conn:
            rows = conn.execute(ROWS, (days,)).fetchall()
        return [{"aid": int(i), "title": t, "link": u, "date": format_datetime(d) if d else "", "outlet": o, "summary": x, "source": sid}
                for i, t, u, d, o, x, sid in rows]
    return load
