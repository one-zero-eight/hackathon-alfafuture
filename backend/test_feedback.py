"""Feedback queue, publication, provenance, dependencies, and revision integration checks."""
import copy
import uuid

import pytest
from fastapi.testclient import TestClient

from backend import app as app_module, config, feedback, feedback_pages as fp, feedback_store as fs, store, worker
from backend.test_backend import db, needs_db, services, request_page, PAGE, NEWS

client = TestClient(app_module.app)


@pytest.fixture
def intent(monkeypatch):
    chosen = {"kind": "question", "reason": "Запрос пользователя"}
    calls = []

    def run(self, name, data):
        assert name == "feedback_intent"
        calls.append(data)
        return copy.deepcopy(chosen)

    monkeypatch.setattr("agents.client.Agents.run", run)
    return chosen, calls


def submit(key, message="Запрос", version=1, context=None, **extra):
    return client.post("/api/chat", json={"context": context or {"type": "page", "id": key}, "message": message, "page_version": version, **extra})


def process(accepted):
    assert accepted.status_code == 202, accepted.text
    assert feedback.run_once()
    return client.get("/api/feedback/" + accepted.json()["operation_id"]).json()


@needs_db
def test_question_is_async_nonmutating_and_sources_are_server_derived(db, services, intent, monkeypatch):
    key = request_page()
    before = store.load_page(key)
    original = feedback.post
    monkeypatch.setattr(feedback, "post", lambda path, body, service: {"text": "Ответ", "basis": ["invented"]} if path == "/reply" else original(path, body, service))
    result = process(submit(key))
    assert result["status"] == "completed"
    assert result["result"]["scenario"]["kind"] == "question"
    assert result["result"]["reply"]["basis"] == ["ЦБ сохранил ставку"]
    assert result["result"]["sources"][0]["id"] == "article:1"
    assert store.load_page(key) == before
    assert len(intent[1]) == 1


@needs_db
def test_delete_exclusive_chain_persists_exclusion_and_undo_restores_state(db, services, intent):
    key = request_page()
    intent[0].update(kind="remove", target_id=f"{key}_n1")
    operation = process(submit(key, "Удали новость"))
    assert operation["status"] == "completed"
    assert store.load_page(key)["widgets"] == []
    assert fs.profile(key)["feedback_state"]["removed_aids"] == [1]
    undo = client.post(f"/api/profile/{key}/undo", json={"page_version": 2, "target_version": 1})
    assert undo.status_code == 200 and undo.json()["page"]["version"] == 3
    assert len(store.load_page(key)["widgets"]) == 3 and fs.profile(key)["feedback_state"]["removed_aids"] == []
    assert client.post(f"/api/profile/{key}/undo", json={"page_version": 2, "target_version": 1}).status_code == 409


@needs_db
@pytest.mark.parametrize("kind", ["edit", "proposal"])
def test_missing_analytics_rejects_entire_change(db, services, intent, kind):
    key = request_page()
    before = fs.profile(key)
    intent[0].update(kind=kind, target_id=f"{key}_a1", text="Исправленный вывод")
    operation = process(submit(key, "Исправленный вывод"))
    assert operation["status"] == "blocked"
    assert operation["result"]["error"]["code"] == "analytics_dependency_unavailable"
    after = fs.profile(key)
    assert (after["page"], after["feedback_state"]) == (before["page"], before["feedback_state"])


@needs_db
@pytest.mark.parametrize("method", ["lexical", "dense_llm"])
def test_refinement_never_switches_method(db, services, intent, monkeypatch, method):
    monkeypatch.setattr(config, "NEWS_SEARCH_METHOD", method)
    key = request_page()
    intent[0].update(kind="extend", text="Рынок труда")
    operation = process(submit(key))
    assert operation["status"] == "blocked" and operation["result"]["error"]["code"] == "unsupported_search_method"
    assert store.load_page(key)["version"] == 1 and len(services) == 2


@needs_db
def test_clarification_and_invalid_target_never_mutate(db, services, intent):
    key = request_page()
    intent[0].update(kind="clarify", clarification="Какой блок?")
    assert process(submit(key))["status"] == "needs_clarification"
    intent[0].update(kind="remove", target_id="invented")
    assert process(submit(key))["status"] == "failed"
    assert store.load_page(key)["version"] == 1


@needs_db
def test_request_deduplication_and_stale_jobs_do_not_repeat_llm(db, services, intent):
    key = request_page()
    request_id = str(uuid.uuid4())
    first = submit(key, request_id=request_id)
    again = submit(key, request_id=request_id)
    assert first.json()["operation_id"] == again.json()["operation_id"]
    assert submit(key, "different", request_id=request_id).status_code == 409
    process(first)
    assert not feedback.run_once() and len(intent[1]) == 1
    stale = submit(key)
    with store.connect() as conn:
        conn.execute("UPDATE profiles SET page=jsonb_set(page,'{version}','2') WHERE key=%s", (key,))
    assert process(stale)["status"] == "conflict" and len(intent[1]) == 1


@needs_db
def test_extend_and_perspective_use_existing_contracts_and_keep_ai_authorship(db, services, intent, monkeypatch):
    key = request_page()
    calls = []
    new_news = {**NEWS["top"][0], "aid": 2, "link": "https://rbc.ru/2"}
    raw = copy.deepcopy(PAGE)
    raw["journal"] = [{"event": "N2", "evidence": ["N2"]}]

    def post(path, body, service):
        calls.append((path, body))
        return {"top": [new_news], "pairs": [], "cost": 0, "stats": {}} if service == "news_search" else raw

    monkeypatch.setattr(feedback, "post", post)
    intent[0].update(kind="extend", text="Рынок труда")
    assert process(submit(key))["status"] == "completed"
    page = store.load_page(key)
    assert page["version"] == 2 and len(page["widgets"]) == 6
    assert calls[0][1]["kind"] == "topic" and calls[0][1]["exclude_aids"] == [1]
    assert all(w["tags"]["source"] == "ai" for w in page["widgets"][3:] if w["column"] != "news")
    persisted = fs.profile(key)["feedback_state"]
    assert fp.initial_state(page, persisted)["widget_sources"] == persisted["widget_sources"]
    added_id = next(w["id"] for w in page["widgets"][3:] if w["column"] == "news")
    assert persisted["widget_sources"][added_id] == ["article:2"]
    intent[0].update(kind="perspective", line="Маркетинг", region="Казань")
    assert process(submit(key, version=2))["status"] == "completed"
    assert calls[-2][1]["page_line"] == "Финансовый директор" and calls[-2][1]["line"] == "Маркетинг"
    assert len(store.load_page(key)["widgets"]) == 3
    assert fs.profile(key)["feedback_state"]["effective"] == {"line": "Маркетинг", "region": "Казань"}


@needs_db
def test_link_fetch_is_profile_local_with_stable_user_provenance(db, services, intent, monkeypatch):
    key = request_page()
    source = {"source_id": "user:" + uuid.uuid4().hex, "title": "Статья пользователя", "link": "https://example.org/article", "summary": "Проверяемый текст", "origin": "human", "outlets": ["example.org"]}
    monkeypatch.setattr(feedback.article_fetch, "fetch", lambda url: copy.deepcopy(source))
    raw = copy.deepcopy(PAGE)
    raw["journal"] = [{"event": "N0", "evidence": ["N0"]}]
    monkeypatch.setattr(feedback, "post", lambda path, body, service: {"top": [], "pairs": [], "stats": {}, "cost": 0} if service == "news_search" else raw)
    intent[0].update(kind="link", url=source["link"])
    result = process(submit(key, source["link"]))
    assert result["status"] == "completed"
    page, state = store.load_page(key), fs.profile(key)["feedback_state"]
    added_news = [w for w in page["widgets"][3:] if w["column"] == "news"][0]
    assert added_news["tags"]["source"] == "human"
    assert state["widget_sources"][added_news["id"]] == [source["source_id"]]
    assert "aid" not in state["sources"][source["source_id"]]
    assert all(w["tags"]["source"] == "ai" for w in page["widgets"][3:] if w["column"] != "news")


@needs_db
def test_force_refresh_preserves_deletions_and_uses_new_page_version(db, services, intent):
    key = request_page()
    # Keep a second source available so exclusion does not empty the refreshed result.
    state = fs.profile(key)["feedback_state"]
    state["removed_aids"] = [99]
    with store.connect() as conn:
        from psycopg.types.json import Jsonb
        conn.execute("UPDATE profiles SET feedback_state=%s WHERE key=%s", (Jsonb(state), key))
    result = client.post("/api/profile", json={"company": "Делимобиль", "role": "Финансовый директор", "force": True}).json()
    assert result["status"] == "queued" and not result["cached"]
    assert worker.run_once()
    assert store.load_page(key)["version"] == 2
    assert fs.profile(key)["feedback_state"]["removed_aids"] == [99]


@needs_db
def test_restart_retention_and_twenty_revision_limit(db, services):
    key = request_page()
    queued = submit(key)
    fs.take()
    store.init()
    assert fs.get(queued.json()["operation_id"])["status"] == "failed"
    with store.connect() as conn, conn.transaction():
        for version in range(1, 25):
            page = copy.deepcopy(PAGE)
            page["version"] = version
            fs.snapshot(conn, key, page, {})
        assert conn.execute("SELECT count(*),min(version) FROM profile_revisions WHERE profile_key=%s", (key,)).fetchone() == (20, 5)
        conn.execute("UPDATE feedback_operations SET finished_at=now()-interval '8 days'")
    fs.cleanup()
    assert fs.get(queued.json()["operation_id"]) is None


def test_delete_preserves_shared_and_manually_authored_descendants():
    page = copy.deepcopy(PAGE)
    page["widgets"].append({"id": "n2", "column": "news", "title": "Второй источник"})
    page["links"].append({"id": "shared", "from": "n2", "to": "a1"})
    state = fp.initial_state(page, news=[NEWS["top"][0], {**NEWS["top"][0], "aid": 2}])
    fp.remove(page, state, "n1")
    assert {w["id"] for w in page["widgets"]} == {"n2", "a1", "d1"}
    assert all(l["from"] != "n1" for l in page["links"])


@needs_db
def test_idempotent_retry_after_deletion_returns_original_operation(db, services, intent):
    key = request_page()
    context = {"type": "widget", "id": f"{key}_n1"}
    intent[0].update(kind="remove", target_id=context["id"])
    request_id = str(uuid.uuid4())
    first = submit(key, "Удали", context=context, request_id=request_id)
    process(first)
    retry = submit(key, "Удали", context=context, request_id=request_id)
    assert retry.status_code == 202 and retry.json()["operation_id"] == first.json()["operation_id"]
    assert len(intent[1]) == 1


@needs_db
def test_version_change_during_service_calls_cannot_be_overwritten(db, services, intent, monkeypatch):
    key = request_page()
    intent[0].update(kind="extend", text="Новая тема")
    def post(path, body, service):
        if service == "news_search":
            return {"top": [{**NEWS["top"][0], "aid": 2}], "pairs": []}
        with store.connect() as conn:
            conn.execute("UPDATE profiles SET page=jsonb_set(page,'{version}','8') WHERE key=%s", (key,))
        return copy.deepcopy(PAGE)
    monkeypatch.setattr(feedback, "post", post)
    result = process(submit(key))
    assert result["status"] == "conflict" and store.load_page(key)["version"] == 8
    assert len(store.load_page(key)["widgets"]) == 3


@needs_db
def test_manual_leaf_edit_is_human_and_refresh_preserves_literal_text(db, services, intent):
    key = request_page()
    page = store.load_page(key)
    page["widgets"] = [page["widgets"][0]]
    page["links"] = []
    store.save_page(key, page)
    intent[0].update(kind="edit", target_id=f"{key}_n1", text="Моя точная поправка")
    operation = process(submit(key, "Моя точная поправка"))
    assert operation["status"] == "completed"
    widget = store.load_page(key)["widgets"][0]
    assert widget["tags"]["source"] == "human" and widget["details"]["text"] == "Моя точная поправка"
    refreshed = client.post("/api/profile", json={"company": "Делимобиль", "role": "Финансовый директор", "force": True})
    assert refreshed.json()["status"] == "queued" and worker.run_once()
    widget = next(w for w in store.load_page(key)["widgets"] if w["id"] == f"{key}_n1")
    assert widget["details"]["text"] == "Моя точная поправка"
    assert widget["tags"]["source"] == "human"


@needs_db
def test_redirect_or_fragment_variant_does_not_duplicate_shown_article(db, services, intent, monkeypatch):
    key = request_page()
    intent[0].update(kind="link", url=NEWS["top"][0]["link"] + "#fragment")
    monkeypatch.setattr(feedback.article_fetch, "fetch", lambda url: {"source_id": "user:" + uuid.uuid4().hex, "title": "Same article", "link": NEWS["top"][0]["link"], "summary": "text", "origin": "human"})
    result = process(submit(key, intent[0]["url"]))
    assert result["status"] == "completed" and result["result"]["patch"] is None
    assert store.load_page(key)["version"] == 1


@needs_db
def test_concurrent_consumers_claim_at_most_one_job_per_profile(db, services):
    import threading
    from concurrent.futures import ThreadPoolExecutor
    key = request_page()
    submit(key, "one")
    submit(key, "two")
    barrier = threading.Barrier(2)
    def take(_):
        barrier.wait(timeout=5)
        return fs.take()
    with ThreadPoolExecutor(2) as pool:
        claimed = list(pool.map(take, range(2)))
    assert sum(row is not None for row in claimed) == 1
