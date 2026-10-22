import pytest
from fastapi.testclient import TestClient

import main

c = TestClient(main.app)


@pytest.fixture(autouse=True)
def fresh_state():
    main.WIDGETS.clear(); main.LINKS.clear()
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


def test_stale_version_conflict():
    assert chat("n1", "добавь", 99).status_code == 409
