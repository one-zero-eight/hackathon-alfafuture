"""Persistence, privacy, lifecycle, and on-demand descriptions against disposable PostgreSQL."""
import uuid

import pytest
from fastapi.testclient import TestClient

from agents import tracing
from backend import app as backend_app, config, journal, store, worker
from backend.test_backend import db, needs_db, services  # reuse isolated-schema fixtures

client = TestClient(backend_app.app)


def start():
    return journal.create("news_search", tracing.company_ref("Example"))


@needs_db
def test_ingestion_is_capability_protected_idempotent_and_public_view_is_filtered(db):
    run = start()
    event = tracing.Event(section="agents", step="llm", agent="hyde", model="google/gemma-4-26b-a4b-it", usage=tracing.Usage(total_tokens=42, cost=0.2))
    path = f"/internal/trace/runs/{run['run_id']}/events"
    assert client.post(path, json={"event": event.model_dump(mode="json")}).status_code == 403
    header = {"X-Trace-Capability": run["capability"]}
    for _ in range(2):
        assert client.post(path, json={"event": event.model_dump(mode="json")}, headers=header).status_code == 200
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM trace_events WHERE event_id=%s", (event.event_id,)).fetchone()[0] == 1
        assert conn.execute("SELECT capability_hash FROM trace_runs WHERE id=%s", (run["run_id"],)).fetchone()[0] != run["capability"]
    public_event = tracing.Event(section="news_search", step="ranking", counts={"before": 50, "selected": 10}, source_ids=["article:1"], agent="pick", model="z-ai/glm-5.3-flash")
    journal.record(run["run_id"], public_event)
    first = client.get(f"/api/runs/{run['run_id']}?limit=1").json()
    second = client.get(f"/api/runs/{run['run_id']}?after={first['next_cursor']}").json()
    assert len(second["events"]) == 1 and second["events"][0]["counts"] == {"before": 50, "selected": 10}
    rendered = str(second)
    assert "usage" not in rendered and "capability" not in rendered and "google/" not in rendered and "agent" not in second["events"][0]
    assert client.get(f"/api/runs/{uuid.uuid4().hex}").status_code == 404
    assert client.get(f"/api/runs/{run['run_id']}?after=-1").status_code == 422


@needs_db
@pytest.mark.parametrize("method", config.METHODS)
def test_profile_runs_cache_retries_and_isolation(db, services, monkeypatch, method):
    monkeypatch.setattr(config, "NEWS_SEARCH_METHOD", method)
    body = {"company": "Example", "role": "CFO"}
    first = client.post("/api/profile", json=body).json()
    assert worker.run_once()
    cached = client.post("/api/profile", json=body).json()
    assert cached["cached"] and cached["run_id"] == first["run_id"]
    result = client.get(f"/api/runs/{first['run_id']}").json()
    assert result["status"] == "completed" and not result["incomplete"]
    assert {"profile", "search", "analytics", "publication"} <= {e["step"] for e in result["events"]}
    with store.connect() as conn:
        conn.execute("UPDATE profiles SET updated_at=now()-interval '2 days' WHERE key=%s", (first["key"],))
    again = client.post("/api/profile", json=body).json()
    assert again["run_id"] != first["run_id"]
    assert len(client.get(f"/api/profile/{first['key']}/runs").json()["runs"]) == 2
    assert client.get(f"/api/runs/{again['run_id']}").json()["status"] == "queued"


@needs_db
def test_restart_and_retention_preserve_active_runs(db, services):
    request = client.post("/api/profile", json={"company": "Example", "role": "CFO"}).json()
    store.take()
    store.init()
    old = journal.get(request["run_id"])
    assert old["status"] == "failed" and old["incomplete"]
    row = store.take()
    assert row[-1] != request["run_id"]
    active = start()
    with store.connect() as conn:
        conn.execute("UPDATE trace_runs SET finished_at=now()-interval '8 days' WHERE id=%s", (request["run_id"],))
        conn.execute("UPDATE trace_runs SET created_at=now()-interval '8 days' WHERE id=%s", (active["run_id"],))
    journal.cleanup()
    assert journal.get(request["run_id"]) is None
    assert journal.get(active["run_id"]) is not None


@needs_db
def test_description_gate_validation_claim_and_cache(db, monkeypatch):
    run = start()
    journal.record(run["run_id"], tracing.Event(section="news_search", step="ranking", counts={"selected": 3}))
    path = f"/api/runs/{run['run_id']}/descriptions"
    assert client.post(path).status_code == 409
    journal.finish(run["run_id"], "completed")
    assert client.post(path).status_code == 503
    monkeypatch.setattr(config, "TRACE_AI_ENABLED", True)
    calls = []

    def fake_run(self, name, data):
        calls.append(name)
        # Only public event facts reach the narration agent.
        assert "usage" not in str(data) and "capability" not in str(data)
        return {"descriptions": [{"event_id": e["event_id"], "phrasing": "compact", "facts": ["counts"]} for e in data["events"]]}

    monkeypatch.setattr("agents.client.Agents.run", fake_run)
    assert journal.claim_descriptions(run["run_id"])
    assert not journal.claim_descriptions(run["run_id"])
    assert client.post(path).status_code == 409
    journal.save_descriptions(run["run_id"], None)
    first = client.post(path)
    assert first.status_code == 200 and "3" in str(first.json()["descriptions"])
    assert client.post(path).json()["cached"] and calls == ["trace_description"]
    inputs = journal.description_input(run["run_id"])
    for answer in ({"descriptions": []}, {"descriptions": [{"event_id": "invented", "phrasing": "compact", "facts": []}]},
                   {"descriptions": [{"event_id": e["event_id"], "phrasing": "invented fact", "facts": []} for e in inputs]}):
        with pytest.raises(ValueError):
            journal.validate_descriptions(answer, inputs)


@needs_db
def test_delivery_failure_does_not_break_profile_and_marks_journal_incomplete(db, services, monkeypatch):
    request = client.post("/api/profile", json={"company": "Example", "role": "CFO"}).json()
    original = journal.record

    def failing(run_id, event, conn=None):
        if event.step == "search":
            raise RuntimeError("do not log this secret")
        return original(run_id, event, conn)

    monkeypatch.setattr(journal, "record", failing)
    assert worker.run_once()
    assert client.get(f"/api/profile/{request['key']}").json()["status"] == "ready"
    assert journal.get(request["run_id"])["incomplete"]


@needs_db
def test_chat_creates_separate_run_without_recording_message(db, services):
    request = client.post("/api/profile", json={"company": "Example", "role": "CFO"}).json()
    worker.run_once()
    response = client.post("/api/chat", json={"context": {"type": "widget", "id": f"{request['key']}_n1"}, "message": "добавь private-customer-value", "page_version": 1}).json()
    assert response["run_id"] != request["run_id"]
    journal_body = client.get(f"/api/runs/{response['run_id']}").json()
    assert "private-customer-value" not in str(journal_body)


@needs_db
def test_chat_is_queued_when_journal_creation_fails(db, services, monkeypatch):
    request = client.post("/api/profile", json={"company": "Example", "role": "CFO"}).json()
    worker.run_once()
    monkeypatch.setattr(journal, "create", lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("private")))
    response = client.post("/api/chat", json={"context": {"type": "widget", "id": f"{request['key']}_n1"}, "message": "что это?", "page_version": 1})
    assert response.status_code == 202 and response.json()["run_id"] is None
