"""Cache of the steps of a search run (queries, needs, HyDE, results) in PostgreSQL, table search_cache (owned by news_search)."""

import time

import psycopg
from psycopg.types.json import Jsonb

DDL = """CREATE TABLE IF NOT EXISTS search_cache (
  run_key text NOT NULL, name text NOT NULL, data jsonb NOT NULL, created_at timestamptz NOT NULL DEFAULT now(), PRIMARY KEY (run_key, name))"""


class PgCache:
    """get(run_key, name, max_age) -> the stored object, or None if there is none or it is older than max_age seconds."""

    def __init__(self, database_url):
        self.url = database_url
        with psycopg.connect(self.url, autocommit=True) as conn:
            conn.execute(DDL)

    def get(self, run_key, name, max_age=None):
        with psycopg.connect(self.url) as conn:
            row = conn.execute(
                "SELECT data, extract(epoch FROM now() - created_at) FROM search_cache WHERE run_key = %s AND name = %s",
                (run_key, name),
            ).fetchone()
        return row[0] if row and (max_age is None or row[1] < max_age) else None

    def put(self, run_key, name, data):
        with psycopg.connect(self.url) as conn:
            conn.execute(
                "INSERT INTO search_cache (run_key, name, data) VALUES (%s, %s, %s) "
                "ON CONFLICT (run_key, name) DO UPDATE SET data = excluded.data, created_at = now()",
                (run_key, name, Jsonb(data)),
            )


class MemoryCache:
    """Same interface in a dict; for tests and for NewsSearch used as a library without a database. Lost with the process."""

    def __init__(self):
        self.items = {}

    def get(self, run_key, name, max_age=None):
        found = self.items.get((run_key, name))
        return (
            found[0]
            if found and (max_age is None or time.time() - found[1] < max_age)
            else None
        )

    def put(self, run_key, name, data):
        self.items[(run_key, name)] = (data, time.time())
