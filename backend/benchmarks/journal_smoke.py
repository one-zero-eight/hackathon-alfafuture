"""Real HTTP/curl journal smoke with fixture corpus, encoders, and gateway; no paid requests."""
import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid
from pathlib import Path

import psycopg
import uvicorn

from agents import app as agents_app
from agents.client import Agents
from backend import app as backend_app, config, feedback, store, worker
from news_search import app as search_app
from news_search import NewsSearch
from news_search.test_search import FakeAgents, NOW, hash_encoder, make_corpus
from analytics import app as analytics_app


def gateway(model, content, max_tokens, read_timeout=600):
    name = agents_app.ACCOUNT.get()["name"]
    if name in ("queries", "needs", "hyde"):
        out = FakeAgents().run(name, {})
    elif name == "pick":
        out = {"top": [{"id": int(i)} for i in re.findall(r"^(\d+) \|", content, re.M)[:30]]}
    elif name == "analytics_step":
        match = re.search(r"^\[(N\d+)\] (.+?) —", content, re.M)
        out = {"relevant": True, "done": True, "thought": "Вывод фикстуры с проверяемым источником.", "evidence": [{"id": match[1], "quote": match[2]}]}
    elif name == "decision":
        out = {"title": "Решение фикстуры", "text": "Проверить влияние новости.", "risks": []}
    elif name == "verify":
        out = {"verdicts": ["supported"] * 4}
    elif name == "reply":
        out = {"text": "Ответ фикстуры", "basis": []}
    elif name == "feedback_intent":
        out = {"kind": "question", "reason": "fixture"}
    elif name == "trace_description":
        events = json.loads(content.split("Events:\n", 1)[1])
        out = {"descriptions": [{"event_id": e["event_id"], "phrasing": "compact", "facts": ["counts", "queries", "sources"]} for e in events]}
    else:
        raise AssertionError(name)
    return json.dumps(out, ensure_ascii=False), {"total_tokens": 10, "cost": 0}


def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [sock]}, daemon=True)
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("fixture server did not start")
        time.sleep(0.01)
    return f"http://127.0.0.1:{port}", server, thread


def curl(url, body=None):
    args = ["curl", "--fail-with-body", "--silent", "--show-error", url]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "--data", json.dumps(body)]
    return json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)


def main():
    dsn = os.environ["TEST_DATABASE_URL"]
    schema = "journal_smoke_" + uuid.uuid4().hex[:8]
    servers = []
    with psycopg.connect(dsn, autocommit=True) as admin, tempfile.TemporaryDirectory() as directory:
        admin.execute(f"CREATE SCHEMA {schema}")
        config.DATABASE_URL = dsn + ("&" if "?" in dsn else "?") + f"options=-csearch_path%3D{schema}"
        config.WORKER_ENABLED = False
        agents_app.chat = gateway
        analytics_app.load_theses = lambda: []
        try:
            backend, server, thread = serve(backend_app.app)
            servers.append((server, thread))
            os.environ["TRACE_BACKEND_URL"] = backend
            agents, server, thread = serve(agents_app.app)
            servers.append((server, thread))
            os.environ["AGENTS_URL"] = agents
            config.AGENTS_URL = agents
            search_app._search[:] = [NewsSearch(lambda days: make_corpus(), Agents(), directory, hash_encoder, now=lambda: NOW)]
            search, server, thread = serve(search_app.app)
            servers.append((server, thread))
            analytics, server, thread = serve(analytics_app.app)
            servers.append((server, thread))
            config.NEWS_SEARCH_URL, config.ANALYTICS_URL = search, analytics
            for method in config.METHODS:
                config.NEWS_SEARCH_METHOD = method
                submitted = curl(backend + "/api/profile", {"company": "Ромашка", "role": "CFO", "region": "Тверь"})
                assert worker.run_once()
                run = curl(backend + f"/api/runs/{submitted['run_id']}?limit=200")
                assert run["status"] == "completed" and not run["incomplete"], run
                steps = {e["step"] for e in run["events"]}
                assert {"profile", "search", "deduplication", "ranking", "analytics", "decision", "verification", "publication"} <= steps, steps
                assert "usage" not in str(run) and "capability" not in str(run)
                with store.connect() as conn:
                    llm = conn.execute("SELECT count(*) FROM trace_events WHERE run_id=%s AND event->>'step'='llm' AND event->>'status'='completed'", (submitted["run_id"],)).fetchone()[0]
                print(json.dumps({"method": method, "run_id": submitted["run_id"], "public_events": len(run["events"]), "LLM_fixture_calls": llm, "status": run["status"], "incomplete": run["incomplete"]}), flush=True)
                cached = curl(backend + "/api/profile", {"company": "Ромашка", "role": "CFO", "region": "Тверь"})
                assert cached["cached"] and cached["run_id"] == submitted["run_id"]
            # Exercise direct /refine, direct cached /search, and direct /reply contexts via HTTP.
            direct = curl(search + "/refine", {"company": "Ромашка", "line": "CFO", "region": "Тверь", "kind": "topic", "text": make_corpus()[0]["title"]})
            assert direct["top"]
            curl(search + "/search", {"company": "Ромашка", "line": "CFO", "region": "Тверь", "method": "lexical"})
            curl(analytics + "/reply", {"question": "private question", "widget": {"title": "fixture"}})
            page = curl(backend + f"/api/page?profile={submitted['key']}")
            chat = curl(backend + "/api/chat", {"context": {"type": "widget", "id": page["widgets"][0]["id"]}, "message": "private question", "page_version": 1})
            assert chat["status"] == "queued" and feedback.run_once()
            assert curl(backend + f"/api/feedback/{chat['operation_id']}")["status"] in ("completed", "needs_clarification", "failed", "blocked")
            assert curl(backend + f"/api/runs/{chat['run_id']}")["status"] in ("completed", "failed")
            config.TRACE_AI_ENABLED = True
            os.environ["TRACE_AI_ENABLED"] = "true"
            descriptions = curl(backend + f"/api/runs/{submitted['run_id']}/descriptions", {})
            assert descriptions["descriptions"] and curl(backend + f"/api/runs/{submitted['run_id']}/descriptions", {})["cached"]
            print("curl smoke passed: all methods, profile cache, direct refine/search/reply, chat, constrained descriptions/cache; real LLM spend: none", flush=True)
        finally:
            for server, thread in reversed(servers):
                server.should_exit = True
                thread.join(10)
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


if __name__ == "__main__":
    main()
