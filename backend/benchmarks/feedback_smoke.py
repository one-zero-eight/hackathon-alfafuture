"""Real HTTP/curl feedback acceptance with fixture gateway/encoders/articles; no paid calls."""
import copy
import json
import os
import tempfile
import time
import uuid

import psycopg

from agents import app as agents_app
from agents.client import Agents
from analytics import app as analytics_app
from backend import app as backend_app, config, feedback, feedback_store, store, worker
from backend.benchmarks.journal_smoke import curl, gateway as base_gateway, serve
from news_search import NewsSearch
from news_search import app as search_app
from news_search.test_search import NOW, hash_encoder, make_corpus

INTENTS = {"question": {"kind": "question"}, "extend": {"kind": "extend", "text": "слово12 слово13"},
           "perspective": {"kind": "perspective", "line": "Маркетинг", "region": "Казань", "text": "слово12 слово13"},
           "edit": {"kind": "edit", "text": "edit"}, "proposal": {"kind": "proposal", "text": "proposal"},
           "remove": {"kind": "remove"}, "clarify": {"kind": "clarify", "clarification": "Какой блок?"}}


def gateway(model, content, max_tokens, read_timeout=600):
    if agents_app.ACCOUNT.get()["name"] != "feedback_intent":
        return base_gateway(model, content, max_tokens, read_timeout)
    message, raw_context = content.split("User request:\n", 1)[1].split("\nDashboard context:\n", 1)
    context, message = json.loads(raw_context), message.strip()
    if message.startswith("https://"):
        intent = {"kind": "link", "url": message}
    else:
        intent = copy.deepcopy(INTENTS[message])
    if intent["kind"] in ("remove", "edit"):
        intent["target_id"] = context["selected"]["id"]
    return json.dumps({"reason": "Фикстурная классификация", **intent}, ensure_ascii=False), {"total_tokens": 10, "cost": 0}


def main():
    dsn, schema, servers = os.environ["TEST_DATABASE_URL"], "feedback_smoke_" + uuid.uuid4().hex[:8], []
    with psycopg.connect(dsn, autocommit=True) as admin, tempfile.TemporaryDirectory() as directory:
        admin.execute(f"CREATE SCHEMA {schema}")
        config.DATABASE_URL = dsn + ("&" if "?" in dsn else "?") + f"options=-csearch_path%3D{schema}"
        config.WORKER_ENABLED = False
        config.NEWS_SEARCH_METHOD = "dense_xquad"
        agents_app.chat = gateway
        analytics_app.load_theses = lambda: []
        source = {"source_id": "user:" + uuid.uuid4().hex, "title": "Новость пользователя", "summary": "слово12 слово13 слово14 слово15", "link": "https://example.org/article", "outlets": ["example.org"], "origin": "human"}
        feedback.article_fetch.fetch = lambda url: copy.deepcopy(source)
        try:
            backend, server, thread = serve(backend_app.app)
            servers.append((server, thread))
            os.environ["TRACE_BACKEND_URL"] = backend
            agents, server, thread = serve(agents_app.app)
            servers.append((server, thread))
            os.environ["AGENTS_URL"] = agents
            config.AGENTS_URL = agents
            search_app._search[:] = [NewsSearch(lambda days: make_corpus(), Agents(), directory, hash_encoder, now=lambda: NOW)]
            config.NEWS_SEARCH_URL, server, thread = serve(search_app.app)
            servers.append((server, thread))
            config.ANALYTICS_URL, server, thread = serve(analytics_app.app)
            servers.append((server, thread))
            profile = {"company": "Ромашка", "role": "CFO", "region": "Тверь"}
            submitted = curl(backend + "/api/profile", profile)
            assert worker.run_once()
            key = submitted["key"]

            def action(message, context=None, expected="completed"):
                page = curl(backend + f"/api/page?profile={key}")
                started = time.monotonic()
                accepted = curl(backend + "/api/chat", {"context": context or {"type": "page", "id": key}, "message": message,
                                "page_version": page["version"], "request_id": str(uuid.uuid4())})
                assert feedback.run_once()
                result = curl(backend + "/api/feedback/" + accepted["operation_id"])
                assert result["status"] == expected, result
                run = curl(backend + "/api/runs/" + accepted["run_id"])
                assert not run["incomplete"], run
                print(json.dumps({"scenario": result["result"].get("scenario"), "status": result["status"], "changes": len(result["result"].get("changes", [])), "elapsed_ms": round((time.monotonic() - started) * 1000, 1)}, ensure_ascii=False), flush=True)
                return result

            action("question")
            action("extend")
            action("perspective")
            action(source["link"])
            current = store.load_page(key)
            news = next(w for w in current["widgets"] if w.get("tags", {}).get("source") == "human")
            analysis = next(w for w in current["widgets"] if w["column"] == "analytics")
            action("edit", {"type": "widget", "id": analysis["id"]}, "blocked")
            action("proposal", expected="blocked")
            action("clarify", expected="needs_clarification")
            removed = action("remove", {"type": "widget", "id": news["id"]})
            before_version = removed["result"]["patch"]["base_version"]
            restored = curl(backend + f"/api/profile/{key}/undo", {"page_version": before_version + 1, "target_version": before_version})
            assert restored["page"]["version"] == before_version + 2
            refreshed = curl(backend + "/api/profile", {**profile, "force": True})
            assert not refreshed["cached"] and worker.run_once()
            saved = feedback_store.profile(key)
            assert saved["feedback_state"]["effective"]["region"] == "Казань"
            assert any(w["id"] == news["id"] for w in saved["page"]["widgets"])
            print("feedback curl smoke passed: queue/poll, seven scenarios, clarification, provenance, undo, refresh; real LLM spend: none", flush=True)
        finally:
            for server, thread in reversed(servers):
                server.should_exit = True
                thread.join(10)
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


if __name__ == "__main__":
    main()
