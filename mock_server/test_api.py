import json

import pytest
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh_state():
    main.WIDGETS.clear(); main.LINKS.clear(); main.PROFILE_IDS.clear(); main.PAGES.clear()
    main.WIDGETS.update({w["id"]: main.copy.deepcopy(w) for w in main.SEED["widgets"]})
    main.LINKS.update({l["id"]: main.copy.deepcopy(l) for l in main.SEED["links"]})
    main.STATE.update(version=1, n=0)


def chat(wid, message, version=1):
    return c.post("/api/chat", json={"context": {"type": "widget", "id": wid}, "message": message, "page_version": version})


def test_page_skeleton_has_tags_only_no_details():
    p = c.get("/api/page").json()
    assert len(p["widgets"]) == 18 and len(p["links"]) == 15
    w = {x["id"]: x for x in p["widgets"]}
    assert w["d2"]["tags"] == {"confidence": "probable", "source": "ai", "urgency": "urgent"}
    assert set(w["n1"]) <= {"id", "column", "title", "url", "tags"}


def test_details_risks_link_and_404():
    assert c.get("/api/widgets/a1").json()["chart"]["type"] == "line"
    assert len(c.get("/api/widgets/d1/risks").json()["risks"]) == 4
    assert c.get("/api/widgets/n1/risks").status_code == 404
    assert "text" in c.get("/api/links/l1").json()


def test_chat_open_has_no_patch():
    r = chat("n1", None).json()
    assert r["patch"] is None and r["reply"]["followups"]


def test_user_words_give_human_tag():
    added = chat("n1", "добавь аналитику").json()["patch"]
    assert added["version"] == 2 and added["ops"][0]["widget"]["tags"]["source"] == "human"
    changed = chat("a1", "измени заголовок", 2).json()["patch"]
    assert changed["ops"][0]["fields"]["tags"] == {"confidence": "probable", "source": "human"}


def test_reasoning_page_opens_without_replacing_the_demo(tmp_path, monkeypatch):
    page = {"version": 1, "company": {"name": "Профиль T", "okved": "B", "role": "CFO", "date": "неделя"},
            "widgets": [{"id": "n1", "column": "news", "title": "Ставка",
                         "url": "../../analytical-papers/doc.pdf#page=9", "tags": {"industry": "fx"},
                         "details": {"text": "текст", "src": "Ъ", "date": "2026-10-21"},
                         "chat": {"text": "текст", "basis": ["Ъ"], "followups": ["Что дальше?"]}}],
            "links": [{"id": "l1", "from": "n1", "to": "n1", "text": "связь"}]}
    (tmp_path / "T01.json").write_text(json.dumps(page), encoding="utf-8")
    monkeypatch.setenv("REASONING_OUT", str(tmp_path))
    monkeypatch.setattr("reasoning.company.line", lambda uid: "")
    ready = c.post("/api/profile", json={"company": "T01", "role": "CFO"}).json()
    assert ready == {"key": "T01", "status": "ready", "error": ""}
    demo = {w["id"] for w in c.get("/api/page").json()["widgets"]}
    assert "n1" in demo and "T01_n1" not in demo and len(demo) == 18
    got = c.get("/api/page?profile=T01").json()
    assert got["company"]["name"] == "Профиль T" and got["widgets"][0]["url"] == "/api/papers/doc.pdf#page=9"
    assert c.get("/api/widgets/T01_n1").json()["src"] == "Ъ"
    assert c.get("/api/links/T01_l1").json()["text"] == "связь"
    missing = c.post("/api/profile", json={"company": "нет", "role": "CFO"}).json()
    assert missing["status"] == "failed"


def test_followup_answers_from_the_chain(tmp_path, monkeypatch):
    page = {"version": 1, "company": {"name": "U_1", "okved": "41.20", "role": "CFO", "date": "выручка"},
            "widgets": [{"id": "d1", "column": "decisions", "title": "Фиксировать долю",
                         "details": {"text": "Ставка высокая."},
                         "chat": {"text": "Фиксировать долю", "basis": [], "followups": ["Что меняется?"]}}],
            "links": []}
    (tmp_path / "T02.json").write_text(json.dumps(page), encoding="utf-8")
    monkeypatch.setenv("REASONING_OUT", str(tmp_path))
    monkeypatch.setattr("reasoning.chain.reply", lambda *a, **k: {"text": "Долг останется дорогим.", "basis": ["ставка"]})
    assert c.post("/api/profile", json={"company": "T02", "role": "CFO"}).json()["status"] == "ready"
    answer = chat("T02_d1", "что с долгом?").json()
    assert answer["patch"] is None and answer["reply"]["text"] == "Долг останется дорогим."
    assert answer["reply"]["basis"] == ["ставка"]


def test_role_alone_opens_the_session_company(tmp_path, monkeypatch):
    page = {"version": 1, "company": {"name": "U_9", "okved": "42.99", "role": "CFO", "date": "выручка 1 млрд руб., г. Иркутск"},
            "widgets": [], "links": []}
    (tmp_path / "U_9.json").write_text(json.dumps(page), encoding="utf-8")
    monkeypatch.setenv("REASONING_OUT", str(tmp_path))
    monkeypatch.setenv("DEMO_COMPANY", "U_9")
    monkeypatch.setattr("reasoning.company.line", lambda uid: "")
    monkeypatch.setattr("reasoning.company.card", lambda uid, role="CFO": {"okved": "F"})
    ready = c.post("/api/profile", json={"role": "финансовй директор"}).json()
    assert ready["status"] == "ready" and ready["key"] == "U_9" and ready["error"] == ""
    shown = c.get("/api/page?profile=U_9").json()["company"]
    assert shown["name"] == "г. Иркутск" and shown["role"] == "Финансовый директор"
    other = c.post("/api/profile", json={"role": "ответственный за закупки"}).json()
    assert other["key"] == "U_9__procurement" and other["status"] == "failed"
    assert "финансового директора" not in other["error"]
    assert c.get("/api/page?profile=U_9").json()["company"]["role"] == "Финансовый директор"


def test_stale_version_conflict():
    assert chat("n1", "добавь", 99).status_code == 409
