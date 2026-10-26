"""Feedback orchestration: the queue, scenarios, exclusions, provenance, undo, conflicts. Services and the agent are fakes; PostgreSQL is real."""
import copy

import pytest
from fastapi.testclient import TestClient

from agents.feedback import validate
from backend import app as app_module, article_fetch, config, feedback, feedback_pages as fp, feedback_store as fs, store, worker
from backend.test_backend import NEWS, PAGE, db, needs_db  # noqa: F401  (db is a fixture)

client = TestClient(app_module.app)
EXTRA = [{"aid": 2, "title": "Рубль укрепился", "summary": "курс", "outlets": ["Коммерсантъ"], "date": "", "link": "https://kommersant.ru/2"},
         {"aid": 3, "title": "Импорт подорожал", "summary": "цены", "outlets": ["Ведомости"], "date": "", "link": "https://vedomosti.ru/3"}]


def analytics_page(news):
    """What /page returns for the given news: one chain n -> a -> d per news item (ids restart from 1, as the real service's)."""
    widgets, links = [], []
    for i, item in enumerate(news, 1):
        widgets += [{"id": f"n{i}", "column": "news", "title": item["title"], "url": item["link"], "tags": {}, "details": {"text": item["summary"]}},
                    {"id": f"a{i}", "column": "analytics", "title": f"Вывод {item['title']}", "tags": {"source": "ai", "confidence": "probable"}, "details": {"text": "вывод"}},
                    {"id": f"d{i}", "column": "decisions", "title": f"Решение {item['title']}", "tags": {"source": "ai", "urgency": "urgent"}, "details": {"text": "решение"}}]
        links += [{"id": f"l{i}a", "from": f"n{i}", "to": f"a{i}", "text": "почему"}, {"id": f"l{i}d", "from": f"a{i}", "to": f"d{i}", "text": "потому"}]
    return {"version": 1, "company": PAGE["company"], "widgets": widgets, "links": links, "journal": []}


@pytest.fixture
def world(db, monkeypatch):
    """Fake services and agent. world.sent: [(service path, body)]; world.refine: the news /refine returns; world.intent: the agent's raw answer."""
    class World:
        sent, refine, intent, revise = [], [EXTRA[0]], {}, None  # revise: the answer of analytics /revise; None = the endpoint does not exist yet
    w = World()
    w.sent = []

    def post(url, body, what):
        w.sent.append((url.rsplit("/", 1)[-1], body))
        if url.endswith("/search"):
            return {**NEWS, "top": [copy.deepcopy(NEWS["top"][0])]}
        if url.endswith("/page"):
            return analytics_page(body["news"])
        if url.endswith("/revise"):
            if w.revise is None:
                raise worker.ProfileError("analytics: HTTP 404: Not Found")
            return copy.deepcopy(w.revise)
        if url.endswith("/refine"):
            return {"top": copy.deepcopy(w.refine), "pairs": [], "stats": {}}
        return {"text": "Ответ по странице.", "basis": ["РБК"]}

    class FakeAgents:
        def __init__(self, *a, **kw): pass
        def run(self, name, data):
            assert name == "feedback_intent"
            return validate(w.intent, data)

    monkeypatch.setattr(worker, "_post", post)
    monkeypatch.setattr(feedback.Agents, "run", FakeAgents.run)
    monkeypatch.setattr(config, "NEWS_SEARCH_METHOD", "dense_xquad")
    w.key = client.post("/api/profile", json={"company": "Делимобиль", "role": "Финансовый директор"}).json()["key"]
    worker.run_once()
    w.sent.clear()
    return w


def send(world, intent, message="сообщение", ctx=None, version=None, request_id=None):
    world.intent = intent
    page = store.load_page(world.key)
    body = {"context": ctx or {"type": "widget", "id": f"{world.key}_n1"}, "message": message, "page_version": version or page["version"]}
    if request_id:
        body["request_id"] = request_id
    queued = client.post("/api/chat", json=body)
    assert queued.status_code == 202, queued.text
    assert feedback.run_once()
    return client.get(f"/api/feedback/{queued.json()['operation_id']}").json()


def current(world):
    return store.load_page(world.key)


def free_news(world):
    """The news widget without conclusions built on it (the only kind a plain edit may change): drop the chain's analytics first."""
    got = send(world, {"kind": "remove", "target_id": f"{world.key}_a1"}, ctx={"type": "widget", "id": f"{world.key}_a1"})
    assert got["status"] == "completed"
    world.sent.clear()


def ids(page, column=None):
    return {w["id"] for w in page["widgets"] if column in (None, w["column"])}


@needs_db
def test_profile_page_remembers_which_article_each_news_widget_came_from(world):
    row = fs.profile(world.key)
    assert row["feedback_state"]["widget_sources"] == {f"{world.key}_n1": ["article:1"]}
    assert row["feedback_state"]["sources"]["article:1"]["origin"] == "search"


@needs_db
def test_question_answers_with_sources_and_changes_nothing(world):
    got = send(world, {"kind": "question", "reason": "вопрос"})
    assert got["status"] == "completed" and got["result"]["scenario"]["kind"] == "question"
    assert got["result"]["reply"]["text"] == "Ответ по странице." and got["result"]["patch"] is None
    assert got["result"]["sources"] == [{"ref": "article:1", "title": "ЦБ сохранил ставку", "url": "https://rbc.ru/1", "origin": "search"}]
    assert current(world)["version"] == 1 and [s[0] for s in world.sent] == ["reply"]


@needs_db
def test_question_about_the_whole_page_and_about_a_link_use_the_page_context(world):
    got = send(world, {"kind": "question"}, ctx={"type": "page", "id": world.key})
    assert got["status"] == "completed" and "ЦБ сохранил ставку" in world.sent[0][1]["widget"]["details"]["text"]
    got = send(world, {"kind": "question"}, ctx={"type": "link", "id": f"{world.key}_l1a"})
    assert got["status"] == "completed" and world.sent[1][1]["widget"]["title"] == "почему"


@needs_db
def test_ambiguous_request_asks_for_clarification_and_calls_nothing(world):
    got = send(world, {"kind": "remove", "target_id": "no-such-widget"})
    assert got["status"] == "needs_clarification" and got["result"]["reply"]["text"] and current(world)["version"] == 1 and world.sent == []


@needs_db
def test_agent_failure_leaves_the_page_untouched_and_is_not_retried(world, monkeypatch):
    calls = []
    monkeypatch.setattr(feedback.Agents, "run", lambda self, name, data: calls.append(name) or (_ for _ in ()).throw(RuntimeError("gateway")))
    queued = client.post("/api/chat", json={"context": {"type": "widget", "id": f"{world.key}_n1"}, "message": "удали", "page_version": 1}).json()
    assert feedback.run_once() and not feedback.run_once()
    got = client.get(f"/api/feedback/{queued['operation_id']}").json()
    assert got["status"] == "failed" and got["result"]["error"]["code"] == "processing_failed" and calls == ["feedback_intent"] and current(world)["version"] == 1


@needs_db
def test_remove_deletes_exclusive_descendants_remembers_the_article_and_undo_restores(world):
    n1 = f"{world.key}_n1"
    got = send(world, {"kind": "remove", "target_id": n1})
    assert got["status"] == "completed" and got["result"]["patch"]["version"] == 2
    page = current(world)
    assert ids(page) == {f"{world.key}_{x}" for x in ("a1", "d1")} - {f"{world.key}_a1", f"{world.key}_d1"} or ids(page, "news") == set()
    assert ids(page) == set()  # the chain n1 -> a1 -> d1 had no other parent: all of it goes
    assert {c["op"] for c in got["result"]["changes"]} == {"removed"} and len(got["result"]["changes"]) == 3
    state = fs.profile(world.key)["feedback_state"]
    assert state["removed_aids"] == [1] and "https://rbc.ru/1" in state["removed_urls"] and state["widget_sources"] == {}
    undone = client.post(f"/api/profile/{world.key}/undo", json={"page_version": 2}).json()
    assert undone["version"] == 3 and {o["op"] for o in undone["patch"]["ops"]} == {"add_widget", "add_link"}
    page = current(world)
    assert page["version"] == 3 and len(page["widgets"]) == 3 and fs.profile(world.key)["feedback_state"]["removed_aids"] == []
    assert client.post(f"/api/profile/{world.key}/undo", json={"page_version": 3}).status_code == 404


def test_remove_keeps_shared_and_human_widgets():
    page = {"widgets": [{"id": i, "column": c, "title": i, "tags": t} for i, c, t in
                        [("n1", "news", {}), ("n2", "news", {}), ("a1", "analytics", {"source": "ai"}), ("a2", "analytics", {"source": "ai"}),
                         ("h", "analytics", {"source": "human"}), ("d1", "decisions", {"source": "ai"}), ("d2", "decisions", {"source": "ai"})]],
            "links": [{"id": "1", "from": "n1", "to": "a1"}, {"id": "2", "from": "n2", "to": "a1"}, {"id": "3", "from": "n1", "to": "a2"},
                      {"id": "4", "from": "n1", "to": "h"}, {"id": "5", "from": "a2", "to": "d2"}, {"id": "6", "from": "a1", "to": "d1"}]}
    state = fp.initial_state(page)
    fp.remove(page, state, "n1")
    assert {w["id"] for w in page["widgets"]} == {"n2", "a1", "h", "d1"}  # a1 is shared with n2, h is the user's, a2->d2 only hung on n1
    assert {l["id"] for l in page["links"]} == {"2", "6"}


@needs_db
def test_edit_of_a_news_widget_is_human_and_keeps_the_original_source(world):
    n1 = f"{world.key}_n1"
    free_news(world)
    got = send(world, {"kind": "edit", "target_id": n1, "text": "Ставка сохранена на 21%"})
    assert got["status"] == "completed"
    widget = next(w for w in current(world)["widgets"] if w["id"] == n1)
    assert widget["details"]["text"] == "Ставка сохранена на 21%" and widget["tags"]["source"] == "human"
    state = fs.profile(world.key)["feedback_state"]
    assert state["manual_ids"] == [n1] and state["widget_sources"][n1][1] == "article:1" and state["sources"][state["widget_sources"][n1][0]]["origin"] == "human"
    assert {s["origin"] for s in got["result"]["sources"]} == {"human", "search"}


@needs_db
@pytest.mark.parametrize("intent, target", [({"kind": "edit", "text": "иначе"}, "a1"), ({"kind": "edit", "text": "иначе"}, "n1"), ({"kind": "proposal", "text": "выйти на рынок Китая"}, "n1")])
def test_edit_with_dependants_and_proposals_are_refused_while_analytics_has_no_revise_endpoint(world, intent, target):
    before = current(world)
    got = send(world, {**intent, "target_id": f"{world.key}_{target}"}, ctx={"type": "widget", "id": f"{world.key}_{target}"})
    assert got["status"] == "blocked" and got["result"]["error"]["code"] == "analytics_unavailable" and got["result"]["scenario"]["kind"] == intent["kind"]
    assert current(world) == before and fs.profile(world.key)["feedback_state"]["manual_ids"] == []


@needs_db
def test_edit_of_a_conclusion_goes_to_analytics_revise_and_its_answer_is_applied(world):
    a1, d1 = f"{world.key}_a1", f"{world.key}_d1"
    world.revise = {"reply": {"text": "Пересмотрел решение.", "basis": ["правка пользователя"]},
                    "widgets": [{"id": "x", "column": "decisions", "title": "Рефинансировать кредит", "tags": {"source": "ai", "urgency": "urgent"}, "details": {"text": "решение"}}],
                    "links": [{"id": "y", "from": a1, "to": "x", "text": "после правки"}],
                    "updates": [{"id": a1, "fields": {"title": "Маржа падает из-за оборотного капитала", "bogus": 1}}], "removed": [d1]}
    got = send(world, {"kind": "edit", "target_id": a1, "text": "Маржа зависит от оборотного капитала"}, ctx={"type": "widget", "id": a1})
    assert got["status"] == "completed" and got["result"]["reply"] == {"text": "Пересмотрел решение.", "basis": ["правка пользователя"], "followups": []}
    body = next(b for p, b in world.sent if p == "revise")
    assert body["kind"] == "edit" and body["target"]["id"] == a1 and body["target"]["details"]["text"] == "Маржа зависит от оборотного капитала"
    assert {w["id"] for w in body["page"]["widgets"]} == {f"{world.key}_{x}" for x in ("n1", "a1", "d1")} and body["role"] == "CFO"
    page = current(world)
    titles = {w["id"]: w for w in page["widgets"]}
    assert d1 not in titles and titles[a1]["title"].startswith("Маржа падает") and "bogus" not in titles[a1]
    assert titles[a1]["tags"]["source"] == "human" and titles[a1]["details"]["text"] == "Маржа зависит от оборотного капитала"
    new = next(w for w in page["widgets"] if w["title"] == "Рефинансировать кредит")
    assert new["id"] == f"{world.key}_d1r2" and any(l["from"] == a1 and l["to"] == new["id"] for l in page["links"])
    assert not any(l["to"] == d1 or l["from"] == d1 for l in page["links"]) and a1 in fs.profile(world.key)["feedback_state"]["manual_ids"]


@needs_db
def test_proposal_goes_to_analytics_revise_and_adds_what_it_returns(world):
    a1 = f"{world.key}_a1"
    risks = {"steps": ["Купить склад"], "bank_offer": None, "risks": [{"name": "Ставка", "probability": 2, "impact": 3, "mitigation": "фикс"}]}
    world.revise = {"reply": {"text": "Согласуется с выводом про кредит."}, "widgets": [{"id": "p", "column": "decisions", "title": "Предложение: склад", "risks": risks, "tags": {"source": "human"}}],
                    "links": [{"id": "q", "from": a1, "to": "p", "text": "согласуется"}, {"id": "bad", "from": "ghost", "to": "p", "text": "нет такого"}]}
    got = send(world, {"kind": "proposal", "text": "Купить склад"})
    assert got["status"] == "completed" and got["result"]["reply"]["text"] == "Согласуется с выводом про кредит."
    body = next(b for p, b in world.sent if p == "revise")
    assert body["kind"] == "proposal" and body["target"] is None and body["text"] == "Купить склад"
    page = current(world)
    new = next(w for w in page["widgets"] if w["title"] == "Предложение: склад")
    assert new["risks"] == risks and [l["from"] for l in page["links"] if l["to"] == new["id"]] == [a1]
    assert {c["op"] for c in got["result"]["changes"]} == {"added"}


@needs_db
def test_malformed_revise_answer_is_refused_without_changing_the_page(world):
    world.revise = {"widgets": [{"id": "x", "column": "nowhere", "title": "?"}]}
    got = send(world, {"kind": "proposal", "text": "идея"})
    assert got["status"] == "blocked" and got["result"]["error"]["code"] == "analytics_bad_response" and current(world)["version"] == 1


@needs_db
def test_extend_adds_new_chains_next_to_the_old_ones_without_duplicates(world):
    got = send(world, {"kind": "extend", "text": "рынок Казахстана"})
    assert got["status"] == "completed"
    refine = next(b for p, b in world.sent if p == "refine")
    assert refine["kind"] == "topic" and refine["text"] == "рынок Казахстана" and refine["exclude_aids"] == [1]
    page = current(world)
    assert page["version"] == 2 and len(page["widgets"]) == 6 and ids(page) >= {f"{world.key}_n1", f"{world.key}_a1"}
    assert all(w["id"].startswith(f"{world.key}_") for w in page["widgets"])
    assert {c["op"] for c in got["result"]["changes"]} == {"added"} and len(got["result"]["changes"]) == 3
    analytics = next(b for p, b in world.sent if p == "page")
    assert [n["aid"] for n in analytics["news"]] == [2]  # only the new article is analysed
    assert {s["ref"] for s in got["result"]["sources"]} == {"article:1", "article:2"}


@needs_db
def test_extend_never_adds_a_removed_article_again(world):
    send(world, {"kind": "remove", "target_id": f"{world.key}_n1"})
    world.refine = [copy.deepcopy(NEWS["top"][0]), EXTRA[0]]
    send(world, {"kind": "extend", "text": "ставки"}, ctx={"type": "page", "id": world.key})
    page = current(world)
    assert [w["title"] for w in page["widgets"] if w["column"] == "news"] == ["Рубль укрепился"]
    assert next(b for p, b in world.sent if p == "refine")["removed_aids"] == [1]


@needs_db
def test_additional_search_always_uses_dense_xquad_whatever_method_computed_the_profile(world):
    with store.connect() as conn:
        conn.execute("UPDATE profiles SET method='lexical' WHERE key=%s", (world.key,))
    got = send(world, {"kind": "extend", "text": "рынок"})
    assert got["status"] == "completed" and next(b for p, b in world.sent if p == "refine")["method"] == "dense_xquad"


@needs_db
def test_perspective_replaces_generated_blocks_keeps_the_users_own_and_remembers_the_perspective(world):
    n1 = f"{world.key}_n1"
    free_news(world)
    send(world, {"kind": "edit", "target_id": n1, "text": "Моя формулировка"})
    world.sent.clear()
    world.refine = EXTRA
    got = send(world, {"kind": "perspective", "region": "Уральский федеральный округ", "line": "Закупки"})
    assert got["status"] == "completed"
    refine = next(b for p, b in world.sent if p == "refine")
    assert refine["kind"] == "perspective" and refine["region"] == "Уральский федеральный округ" and refine["line"] == "Закупки" and refine["page_line"] == "Финансовый директор"
    page = current(world)
    titles = {w["title"] for w in page["widgets"] if w["column"] == "news"}
    assert titles == {"ЦБ сохранил ставку", "Рубль укрепился", "Импорт подорожал"}
    old = next(w for w in page["widgets"] if w["id"] == n1)
    assert old["details"]["text"] == "Моя формулировка" and old["tags"]["source"] == "human"
    assert not ids(page) & {f"{world.key}_a1", f"{world.key}_d1"}  # the old generated chain is replaced
    state = fs.profile(world.key)["feedback_state"]
    assert state["effective"] == {"line": "Закупки", "region": "Уральский федеральный округ"} and state["manual_ids"] == [n1]
    analytics = next(b for p, b in world.sent if p == "page")
    assert analytics["profile"]["region"] == "Уральский федеральный округ" and [n["aid"] for n in analytics["news"]] == [2, 3]
    assert all(w.get("tags", {}).get("source") != "human" for w in page["widgets"] if w["id"] != n1)


@needs_db
def test_link_downloads_the_article_into_the_profile_only_and_marks_it_human(world, monkeypatch):
    article = {"ref": "user:abc", "title": "Новая пошлина", "link": "https://example.com/duty", "original_url": "https://example.com/duty",
               "summary": "Текст статьи " * 30, "outlets": ["example.com"], "date": "", "origin": "human"}
    monkeypatch.setattr(article_fetch, "fetch", lambda url: copy.deepcopy(article))
    world.refine = [EXTRA[0]]
    got = send(world, {"kind": "link", "url": "https://example.com/duty"}, message="вот https://example.com/duty")
    assert got["status"] == "completed"
    refine = next(b for p, b in world.sent if p == "refine")
    assert refine["kind"] == "link" and refine["text"].startswith("Новая пошлина\nТекст статьи")
    page = current(world)
    news = {w["title"]: w for w in page["widgets"] if w["column"] == "news"}
    assert news["Новая пошлина"]["tags"]["source"] == "human" and "Рубль укрепился" in news
    state = fs.profile(world.key)["feedback_state"]
    assert "user:abc" in state["sources"] and state["sources"]["user:abc"]["origin"] == "human" and state["sources"]["user:abc"]["aid"] is None
    assert {"https://example.com/duty"} <= {s["url"] for s in got["result"]["sources"]}
    again = send(world, {"kind": "link", "url": "https://example.com/duty"}, message="вот https://example.com/duty")
    assert again["status"] == "completed" and again["result"]["patch"] is None and current(world)["version"] == 2


@needs_db
@pytest.mark.parametrize("code, text", [("unsafe_or_unresolvable_url", "не разрешён"), ("fetch_timeout", "время"), ("article_too_large", "размер"), ("unsupported_content", "HTML")])
def test_unfetchable_link_fails_with_a_readable_reason_and_changes_nothing(world, monkeypatch, code, text):
    monkeypatch.setattr(article_fetch, "fetch", lambda url: (_ for _ in ()).throw(article_fetch.FetchError(code)))
    got = send(world, {"kind": "link", "url": "https://example.com/x"}, message="https://example.com/x")
    assert got["status"] == "failed" and got["result"]["error"]["code"] == "article_fetch_failed" and text in got["result"]["reply"]["text"]
    assert current(world)["version"] == 1 and "refine" not in [p for p, _ in world.sent]


@needs_db
def test_request_id_makes_a_retry_return_the_first_operation(world):
    body = {"context": {"type": "widget", "id": f"{world.key}_n1"}, "message": "удали", "page_version": 1, "request_id": "r-1"}
    first = client.post("/api/chat", json=body)
    second = client.post("/api/chat", json=body)
    assert first.status_code == 202 and second.status_code == 200 and first.json()["operation_id"] == second.json()["operation_id"]
    assert client.post("/api/chat", json={**body, "message": "другое"}).status_code == 409
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM feedback_operations").fetchone()[0] == 1


@needs_db
def test_page_changed_between_queueing_and_processing_is_a_conflict(world):
    world.intent = {"kind": "remove", "target_id": f"{world.key}_n1"}
    queued = client.post("/api/chat", json={"context": {"type": "widget", "id": f"{world.key}_n1"}, "message": "удали", "page_version": 1}).json()
    page = current(world)
    page["version"] = 2
    with store.connect() as conn:
        fs.publish(conn, world.key, page, None, 1)
    assert feedback.run_once()
    got = client.get(f"/api/feedback/{queued['operation_id']}").json()
    assert got["status"] == "conflict" and got["result"]["error"]["code"] == "page_conflict" and current(world)["version"] == 2


@needs_db
def test_publication_checks_the_version_and_two_racing_publications_cannot_both_win(world):
    page = current(world)
    first, second = {**page, "version": 2, "widgets": page["widgets"][:1]}, {**page, "version": 2, "widgets": page["widgets"][:2]}
    op = {"id": "x", "profile_key": world.key}
    with store.connect() as conn:
        conn.execute("INSERT INTO feedback_operations(id, profile_key, request_id, payload) VALUES ('x', %s, 'x', '{}'), ('y', %s, 'y', '{}')", (world.key, world.key))
    fs.complete(op, {"ok": 1}, "completed", first, None)
    with pytest.raises(fs.Conflict):
        fs.complete({"id": "y", "profile_key": world.key}, {"ok": 1}, "completed", second, None)
    assert len(current(world)["widgets"]) == 1
    with store.connect() as conn:
        assert conn.execute("SELECT status FROM feedback_operations WHERE id='y'").fetchone()[0] == "queued"


@needs_db
def test_only_the_last_20_revisions_are_kept_and_undo_steps_back_each_time(world):
    for i in range(23):
        page = current(world)
        with store.connect() as conn:
            fs.publish(conn, world.key, {**page, "version": page["version"] + 1, "company": {**page["company"], "name": f"v{i}"}}, None, page["version"])
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM page_revisions WHERE profile_key=%s", (world.key,)).fetchone()[0] == 20
    version = current(world)["version"]
    first = client.post(f"/api/profile/{world.key}/undo", json={"page_version": version}).json()
    second = client.post(f"/api/profile/{world.key}/undo", json={"page_version": first["version"]}).json()
    assert second["version"] == version + 2 and current(world)["company"]["name"] == "v20"
    assert client.post(f"/api/profile/{world.key}/undo", json={"page_version": 1}).status_code == 409


@needs_db
def test_finished_operations_are_deleted_after_7_days_and_interrupted_ones_fail(world):
    world.intent = {"kind": "question"}
    client.post("/api/chat", json={"context": {"type": "widget", "id": f"{world.key}_n1"}, "message": "почему?", "page_version": 1})
    feedback.run_once()
    pending = client.post("/api/chat", json={"context": {"type": "widget", "id": f"{world.key}_n1"}, "message": "ещё", "page_version": 1}).json()
    fs.take()
    with store.connect() as conn:
        fs.init(conn)
        conn.execute("UPDATE feedback_operations SET finished_at = now() - interval '8 days' WHERE status = 'completed'")
    fs.cleanup()
    with store.connect() as conn:
        assert conn.execute("SELECT count(*) FROM feedback_operations WHERE status='completed'").fetchone()[0] == 0
    assert client.get(f"/api/feedback/{pending['operation_id']}").json()["status"] == "failed"


@needs_db
def test_chat_validation_and_unknown_operation(world):
    ctx = {"type": "widget", "id": f"{world.key}_n1"}
    assert client.post("/api/chat", json={"context": ctx, "message": "  ", "page_version": 1}).status_code == 422
    assert client.post("/api/chat", json={"context": ctx, "message": "x" * 4001, "page_version": 1}).status_code == 422
    assert client.post("/api/chat", json={"context": {"type": "widget", "id": f"{world.key}_zz"}, "message": "что?", "page_version": 1}).status_code == 404
    assert client.post("/api/chat", json={"context": {"type": "page", "id": "unknown"}, "message": "что?", "page_version": 1}).status_code == 404
    assert client.get("/api/feedback/nope").status_code == 404
