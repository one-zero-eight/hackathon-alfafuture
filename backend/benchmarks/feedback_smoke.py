"""Real HTTP/curl smoke of the feedback orchestration (#26): backend, agents, news_search, analytics as uvicorn services over loopback with the
fixture corpus, encoders and gateway; the fetched article is a fixture. No paid requests. Prints the time of each scenario.
Run: TEST_DATABASE_URL=postgres://... PYTHONHASHSEED=0 uv run python -m backend.benchmarks.feedback_smoke"""

import json
import os
import re
import socket
import subprocess
import tempfile
import threading
import time
import uuid

import psycopg

from agents import app as agents_app
from agents.client import Agents
import uvicorn

from backend import app as backend_app, article_fetch, config, feedback, worker
from news_search import app as search_app
from news_search import NewsSearch
from news_search.test_search import FakeAgents, NOW, hash_encoder, make_corpus
from analytics import app as analytics_app


def fixture_gateway(name, content):
    """Answers of the LLM agents on fixtures: enough for search, analytics and replies to run end to end without a paid call."""
    if name in ("queries", "needs", "hyde"):
        return FakeAgents().run(name, {})
    if name == "pick":
        return {
            "top": [
                {"id": int(i)} for i in re.findall(r"^(\d+) \|", content, re.M)[:30]
            ]
        }
    if name == "analytics_step":
        match = re.search(r"^\[(N\d+)\] (.+?) —", content, re.M)
        return {
            "relevant": True,
            "done": True,
            "thought": "Вывод фикстуры с проверяемым источником.",
            "evidence": [{"id": match[1], "quote": match[2]}],
        }
    if name == "decision":
        return {
            "title": "Решение фикстуры",
            "text": "Проверить влияние новости.",
            "risks": [],
        }
    if name == "verify":
        return {"verdicts": ["supported"] * 4}
    if name == "reply":
        return {"text": "Ответ фикстуры", "basis": []}
    raise AssertionError(name)


def gateway(model, content, max_tokens, read_timeout=600):
    """The fixture gateway + feedback_intent: the scripted answer travels in the message as `!intent={json}` (a test double, not a product feature)."""
    name = agents_app.CALL.get()["agent"]
    if name == "feedback_intent":
        message = content.split("<<<\n", 1)[1].split("\n>>>", 1)[0]
        return re.search(r"!intent=(\{.*\})", message).group(1), {
            "total_tokens": 10,
            "cost": 0,
        }
    return json.dumps(fixture_gateway(name, content), ensure_ascii=False), {
        "total_tokens": 10,
        "cost": 0,
    }


def serve(app):
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(app, log_level="warning"))
    thread = threading.Thread(
        target=server.run, kwargs={"sockets": [sock]}, daemon=True
    )
    thread.start()
    deadline = time.monotonic() + 20
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError("fixture server did not start")
        time.sleep(0.01)
    return f"http://127.0.0.1:{sock.getsockname()[1]}", server, thread


def curl(url, body=None):
    args = ["curl", "--fail-with-body", "--silent", "--show-error", url]
    if body is not None:
        args += ["-H", "Content-Type: application/json", "--data", json.dumps(body)]
    return json.loads(
        subprocess.run(args, check=True, capture_output=True, text=True).stdout
    )


def main():
    dsn = os.environ["TEST_DATABASE_URL"]
    schema = "feedback_smoke_" + uuid.uuid4().hex[:8]
    servers, rows = [], []
    with (
        psycopg.connect(dsn, autocommit=True) as admin,
        tempfile.TemporaryDirectory() as directory,
    ):
        admin.execute(f"CREATE SCHEMA {schema}")
        config.DATABASE_URL = (
            dsn + ("&" if "?" in dsn else "?") + f"options=-csearch_path%3D{schema}"
        )
        config.WORKER_ENABLED = False
        config.NEWS_SEARCH_METHOD = "dense_xquad"
        agents_app.chat = gateway
        analytics_app.load_theses = lambda: []
        corpus = make_corpus()
        article = {
            "ref": "user:smoke",
            "title": "Статья пользователя про " + corpus[1]["title"],
            "link": "https://example.com/user-article",
            "original_url": "https://example.com/user-article",
            "summary": corpus[1]["title"] + ". " + "Текст статьи пользователя. " * 20,
            "outlets": ["example.com"],
            "date": "",
            "origin": "human",
        }
        article_fetch.fetch = lambda url: dict(article)
        try:
            backend, server, thread = serve(backend_app.app)
            servers.append((server, thread))
            agents, server, thread = serve(agents_app.app)
            servers.append((server, thread))
            os.environ["AGENTS_URL"] = config.AGENTS_URL = agents
            search_app._search[:] = [
                NewsSearch(
                    lambda days: make_corpus(),
                    Agents(),
                    directory,
                    hash_encoder,
                    now=lambda: NOW,
                )
            ]
            search, server, thread = serve(search_app.app)
            servers.append((server, thread))
            analytics, server, thread = serve(analytics_app.app)
            servers.append((server, thread))
            config.NEWS_SEARCH_URL, config.ANALYTICS_URL = search, analytics
            submitted = curl(
                backend + "/api/profile",
                {"company": "Ромашка", "role": "CFO", "region": "Тверь"},
            )
            assert worker.run_once()
            key = submitted["key"]

            def page():
                return curl(backend + f"/api/page?profile={key}")

            def chat(label, intent, message="сообщение", ctx=None, expect="completed"):
                current = page()
                ctx = ctx or {"type": "page", "id": key}
                started = time.perf_counter()
                queued = curl(
                    backend + "/api/chat",
                    {
                        "context": ctx,
                        "message": f"{message} !intent={json.dumps(intent, ensure_ascii=False)}",
                        "page_version": current["version"],
                    },
                )
                assert queued["status"] == "queued" and feedback.run_once()
                got = curl(backend + f"/api/feedback/{queued['operation_id']}")
                elapsed = (time.perf_counter() - started) * 1000
                assert got["status"] == expect, got
                changed = len(got["result"]["changes"])
                rows.append((label, got["status"], changed, round(elapsed, 1)))
                print(
                    json.dumps(
                        {
                            "scenario": label,
                            "status": got["status"],
                            "changes": changed,
                            "ms": round(elapsed, 1),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )
                return got

            before = page()
            news = [w for w in before["widgets"] if w["column"] == "news"]
            analytic = next(w for w in before["widgets"] if w["column"] == "analytics")
            chat(
                "question",
                {"kind": "question", "reason": "r"},
                ctx={"type": "widget", "id": news[0]["id"]},
            )
            chat(
                "clarify",
                {
                    "kind": "clarify",
                    "reason": "r",
                    "clarification": "Уточните, что изменить?",
                },
                expect="needs_clarification",
            )
            chat(
                "edit вывода (нет analytics/revise)",
                {
                    "kind": "edit",
                    "reason": "r",
                    "target_id": analytic["id"],
                    "text": "иначе",
                },
                expect="blocked",
            )
            chat(
                "proposal (нет analytics/revise)",
                {"kind": "proposal", "reason": "r", "text": "купить склад"},
                expect="blocked",
            )
            assert page() == before
            got = chat(
                "extend", {"kind": "extend", "reason": "r", "text": corpus[2]["title"]}
            )
            assert got["result"]["patch"]["version"] == 2 and got["result"]["changes"]
            got = chat(
                "perspective",
                {
                    "kind": "perspective",
                    "reason": "r",
                    "region": "Уральский федеральный округ",
                    "line": "CFO",
                },
            )
            got = chat(
                "link",
                {"kind": "link", "reason": "r", "url": article["link"]},
                message=f"вот {article['link']}",
            )
            # the fixture analytics may conclude nothing from the article: then the reply says so instead of silently reporting success
            assert (
                any(w["title"] == article["title"] for w in page()["widgets"])
                or "выводов" in got["result"]["reply"]["text"]
                or got["result"]["changes"]
            )
            victim = next(w for w in page()["widgets"] if w["column"] == "news")
            got = chat(
                "remove",
                {"kind": "remove", "reason": "r", "target_id": victim["id"]},
                ctx={"type": "widget", "id": victim["id"]},
            )
            assert victim["id"] not in {w["id"] for w in page()["widgets"]}
            version = page()["version"]
            started = time.perf_counter()
            undone = curl(
                backend + f"/api/profile/{key}/undo", {"page_version": version}
            )
            rows.append(
                (
                    "undo",
                    "completed",
                    len(undone["changes"]),
                    round((time.perf_counter() - started) * 1000, 1),
                )
            )
            assert (
                victim["id"] in {w["id"] for w in page()["widgets"]}
                and page()["version"] == version + 1
            )
            print(
                "curl smoke passed: question, clarify, blocked edit/proposal, extend, perspective, link, remove, undo; real LLM spend: none",
                flush=True,
            )
            print(
                "| Сценарий | Статус | Изменений | Время, мс |\n|---|---|---:|---:|\n"
                + "\n".join(
                    f"| {a} | {b} | {c} | {str(d).replace('.', ',')} |"
                    for a, b, c, d in rows
                )
            )
        finally:
            for server, thread in reversed(servers):
                server.should_exit = True
                thread.join(10)
            admin.execute(f"DROP SCHEMA {schema} CASCADE")


if __name__ == "__main__":
    main()
