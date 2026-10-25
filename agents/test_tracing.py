"""Trace boundaries, concurrent context propagation, retries, and HTTP lifecycle."""
import contextvars
import uuid
from concurrent.futures import ThreadPoolExecutor

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from agents import app as service, tracing


def collecting(section="agents"):
    events = []
    return tracing.Trace(uuid.uuid4().hex, "capability", section, sender=events.append), events


def test_events_reject_unstructured_sensitive_payload_and_unsupported_names():
    for extra in ({"prompt": "secret"}, {"error_code": "secret"}, {"model": "unapproved"}, {"counts": {"salary": 10}},
                  {"queries": ["https://secret.example?token=123"]}, {"source_ids": ["secret raw response"]}):
        with pytest.raises(ValidationError):
            tracing.Event(section="agents", step="llm", **extra)
    assert tracing.usage_fields({}).total_tokens is None
    assert tracing.usage_fields({}).cost is None


def test_spans_preserve_parent_in_explicitly_copied_thread_contexts():
    trace, events = collecting()
    with tracing.activate(trace), tracing.span("analytics"):
        with ThreadPoolExecutor(4) as pool:
            futures = [pool.submit(contextvars.copy_context().run, tracing.emit, "decision", counts={"decisions": 1}) for _ in range(8)]
            for future in futures:
                future.result()
    parent = next(e.span_id for e in events if e.step == "analytics" and e.status == "started")
    assert all(e.parent_id == parent for e in events if e.step == "decision")
    assert tracing.CURRENT.get() is None


def test_llm_validation_retries_are_failed_spans_without_raw_text(monkeypatch):
    trace, events = collecting()
    answers = iter(["secret invalid response", '{"needs":["query"]}'])
    monkeypatch.setattr(service, "chat", lambda *args: (next(answers), {"total_tokens": 10}))
    with tracing.activate(trace):
        assert service.run("needs", {"company": "private", "line": "private"}) == {"needs": ["query"]}
    attempts = [e for e in events if e.step == "llm" and e.status != "started"]
    assert [e.status for e in attempts] == ["failed", "completed"]
    assert [e.attempt for e in attempts] == [1, 2]
    assert "secret invalid" not in str(events) and "private" not in str(events)


def test_gateway_attempts_count_transport_errors_and_preserve_unknown_usage(monkeypatch):
    trace, events = collecting()
    monkeypatch.setenv("LLM_BASE_URL", "https://gateway.invalid")
    monkeypatch.setenv("LLM_API_KEY", "secret-key")
    monkeypatch.delenv("LLM_BASE_URL_BACKUP", raising=False)
    count = []

    class Stream:
        def __enter__(self):
            count.append(1)
            if len(count) == 1:
                raise httpx.ConnectError("secret-key")
            return self
        def __exit__(self, *args): pass
        def raise_for_status(self): pass
        def iter_lines(self):
            yield 'data: {"choices":[{"delta":{"content":"{\\"needs\\":[\\"query\\"]}"}}],"usage":{"total_tokens":12,"cost":0.1}}'

    monkeypatch.setattr(httpx, "stream", lambda *a, **kw: Stream())
    used = {}
    with tracing.activate(trace):
        assert service.run("needs", {"company": "private", "line": "private"}, used) == {"needs": ["query"]}
    attempts = [e for e in events if e.step == "gateway" and e.status != "started"]
    assert used["calls"] == 2 and used["tokens"] == 12 and used["cost"] == 0.1
    assert [e.status for e in attempts] == ["failed", "completed"]
    assert attempts[0].usage.total_tokens is None and attempts[0].usage.cost is None
    assert "secret-key" not in str(events)


def test_direct_http_run_and_inherited_run_finish_only_their_own_lifecycle(monkeypatch):
    app = FastAPI()
    tracing.install(app, "news_search", ("/search",))
    calls = []
    run_id = uuid.uuid4().hex

    def request(path, body, trace=None):
        calls.append((path, body))
        return {"run_id": run_id, "capability": "private-capability"}

    monkeypatch.setenv("TRACE_BACKEND_URL", "http://backend")
    monkeypatch.setattr(tracing, "_request", request)

    @app.post("/search")
    def search():
        tracing.emit("ranking", counts={"selected": 5})
        return {"top": []}

    client = TestClient(app)
    direct = client.post("/search", json={"company": "private-company"})
    assert direct.headers["X-Run-ID"] == run_id and direct.headers["X-Trace-Incomplete"] == "false"
    assert calls[-1][0].endswith("/finish") and "private-company" not in str(calls)
    calls.clear()
    inherited = client.post("/search", json={}, headers={"X-Run-ID": run_id, "X-Trace-Capability": "cap"})
    assert inherited.status_code == 200 and not any(p.endswith("/finish") for p, _ in calls)
    assert "X-Trace-Capability" not in inherited.headers


def test_unreachable_journal_marks_http_response_incomplete(monkeypatch):
    app = FastAPI()
    tracing.install(app, "analytics", ("/page",))
    monkeypatch.setenv("TRACE_BACKEND_URL", "http://backend")
    monkeypatch.setattr(tracing, "_request", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("secret")))

    @app.post("/page")
    def page(): return {"ok": True}

    response = TestClient(app).post("/page", json={})
    assert response.status_code == 200 and response.headers["X-Trace-Incomplete"] == "true"


def test_description_endpoint_enforces_gate_and_public_event_boundary(monkeypatch):
    from agents.app import app
    client = TestClient(app)
    monkeypatch.delenv("TRACE_AI_ENABLED", raising=False)
    assert client.post("/agents/trace_description", json={"input": {"events": []}}).status_code == 503
    monkeypatch.setenv("TRACE_AI_ENABLED", "true")
    for events in ([{}], [{}] * 41, [{"section": "agents", "step": "llm", "usage": {"cost": 1}}]):
        assert client.post("/agents/trace_description", json={"input": {"events": events}}).status_code == 422


def test_delivery_failure_avoids_repeating_network_wait_for_each_event(monkeypatch):
    trace = tracing.Trace(uuid.uuid4().hex, "cap", "news_search")
    attempts = []

    def fail(*args, **kwargs):
        attempts.append(1)
        raise RuntimeError("secret")

    monkeypatch.setattr(tracing, "_request", fail)
    with tracing.activate(trace):
        for _ in range(10):
            tracing.emit("ranking", counts={"selected": 1})
    assert trace.incomplete and len(attempts) == 1
