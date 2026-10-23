"""Pipeline worker: takes queued profiles from Postgres, runs pipeline.py (cached for a day) and analyze.py, stores the page.

Profiles live in `v1_profiles` (created by the api service too); status: queued -> running -> ready | failed."""
import os
import time
import traceback

import psycopg
from psycopg.types.json import Jsonb

import analyze
import pipeline

DDL = """CREATE TABLE IF NOT EXISTS v1_profiles (
  key text PRIMARY KEY, company text NOT NULL, role text NOT NULL, status text NOT NULL DEFAULT 'queued',
  error text NOT NULL DEFAULT '', page jsonb, created_at timestamptz NOT NULL DEFAULT now(), updated_at timestamptz NOT NULL DEFAULT now())"""
TAKE = """UPDATE v1_profiles SET status = 'running', updated_at = now()
  WHERE key = (SELECT key FROM v1_profiles WHERE status = 'queued' ORDER BY created_at LIMIT 1 FOR UPDATE SKIP LOCKED)
  RETURNING key, company, role"""


def main():
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute(DDL)
        conn.execute("UPDATE v1_profiles SET status = 'queued' WHERE status = 'running'")  # the previous worker died mid-run
        print("worker ready", flush=True)
        while True:
            row = conn.execute(TAKE).fetchone()
            if not row:
                time.sleep(3)
                continue
            key, company, role = row
            print(f"profile {key}: {company!r} / {role!r}", flush=True)
            try:
                page = analyze.build_page(key, company, role, pipeline.run(company, role)["top"])
                conn.execute("UPDATE v1_profiles SET status = 'ready', page = %s, error = '', updated_at = now() WHERE key = %s", (Jsonb(page), key))
                print(f"profile {key}: ready, LLM cost so far {pipeline.COST[0]:.2f}", flush=True)
            except (Exception, SystemExit) as e:  # pipeline raises SystemExit when the corpus has too few matches
                traceback.print_exc()
                conn.execute("UPDATE v1_profiles SET status = 'failed', error = %s, updated_at = now() WHERE key = %s", (repr(e)[:500], key))


if __name__ == "__main__":
    main()
