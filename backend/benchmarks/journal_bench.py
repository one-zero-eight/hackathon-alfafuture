"""Offline tracing overhead on fixture searches; no LLM calls or model downloads."""
import json
import os
import statistics
import tempfile
import time
import uuid
from pathlib import Path

import psycopg

from agents import tracing
from backend import config, journal, store
from news_search import METHODS
from news_search.test_search import make_corpus, searcher


def main():
    dsn = os.environ["TEST_DATABASE_URL"]
    schema = "journal_bench_" + uuid.uuid4().hex[:8]
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
        config.DATABASE_URL = dsn + ("&" if "?" in dsn else "?") + f"options=-csearch_path%3D{schema}"
        try:
            store.init()
            results = []
            with tempfile.TemporaryDirectory() as directory:
                for method in METHODS:
                    for mode in ("off", "memory", "postgres"):
                        durations, event_counts = [], []
                        for repeat in range(5):
                            data = Path(directory) / f"{method}-{mode}-{repeat}"
                            data.mkdir()
                            search, _ = searcher(data, make_corpus())
                            events = []
                            trace = None
                            if mode == "memory":
                                trace = tracing.Trace(uuid.uuid4().hex, "cap", "news_search", sender=events.append)
                            elif mode == "postgres":
                                created = journal.create("news_search", tracing.company_ref("fixture"))
                                trace = journal.context(created["run_id"])
                                trace.section = "news_search"
                            started = time.perf_counter()
                            with tracing.activate(trace):
                                search.search("Ромашка", "Закупки", "Тверь", method)
                            durations.append((time.perf_counter() - started) * 1000)
                            if mode == "postgres":
                                with store.connect() as conn:
                                    event_counts.append(conn.execute("SELECT count(*) FROM trace_events WHERE run_id=%s", (trace.run_id,)).fetchone()[0] - 1)
                                journal.finish(trace.run_id, "completed", trace.incomplete)
                            else:
                                event_counts.append(len(events))
                        results.append({"method": method, "mode": mode, "median_ms": round(statistics.median(durations), 2),
                                        "min_ms": round(min(durations), 2), "max_ms": round(max(durations), 2), "events": event_counts[0]})
            print(json.dumps(results, indent=2))
        finally:
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


if __name__ == "__main__":
    main()
