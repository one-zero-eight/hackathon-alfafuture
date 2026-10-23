"""Offline checks: no network, a fake model returns canned JSON."""
import json

from reasoning.alfa import keep
from reasoning.chain import build, grounded, plan
from reasoning.data import corpus, profiles, roles
from reasoning.evaluate import score
from reasoning.search import Index

QUOTE = "Банк России сохранит ставку"


class Fake:
    def json(self, model, prompt, step, tries=3, **_):
        if step.startswith("hop2"):
            if "Банк России" not in prompt.split("Материалы:")[0]:
                return {"relevant": False, "evidence": []}
            return {"relevant": True, "done": True, "thought": "Ставка не снизится, долг останется дорогим.",
                    "evidence": [{"id": "A1", "quote": QUOTE}]}
        if step.startswith("hop3"):
            return {"title": "Зафиксировать часть долга", "text": "Зафиксировать ставку по половине долга до заседания.",
                    "why": "Ставка не снизится.", "move": "предварительное действие",
                    "contradiction": "Нужны деньги, но долг дорожает.",
                    "risks": [{"name": "Ставка всё же снизится", "probability": 2, "impact": 3, "mitigation": "Фиксировать долю, не весь долг."}]}
        return {"verdicts": ["supported"]}


def test_budget_grows_when_reasoning_ate_the_answer():
    from reasoning.llm import next_budget
    eaten = {"completion_tokens": 1200, "completion_tokens_details": {"reasoning_tokens": 1200}}
    assert next_budget(1200, eaten) == 2400
    assert next_budget(3600, eaten) == 4000
    assert next_budget(1200, {"completion_tokens": 200, "completion_tokens_details": {"reasoning_tokens": 80}}) == 1200


def test_one_failed_decision_keeps_the_news():
    class Boom(Fake):
        def json(self, model, prompt, step, tries=3, **_):
            if step.startswith("hop3"):
                raise RuntimeError("no json")
            return super().json(model, prompt, step, tries)

    items = {"A1": {"id": "A1", "title": "ЦБ сохранит ставку", "text": f"вчера {QUOTE} на прежнем уровне",
                    "card": {"okved": ["K"], "event_type": "monetary_policy"}}}
    events = [{"id": "A1", "title": items["A1"]["title"], "text": items["A1"]["text"]}]
    profile = {"id": "T", "okved": "B", "okved_name": "Добыча", "region": "siberia_fe", "role": "CFO", "products": ["credit"]}
    role = {"title": "CFO", "authority": "долг", "playbook": "если ставка высокая — фиксировать"}
    page = build(profile, role, events, items, Boom())
    assert [w["column"] for w in page["widgets"]] == ["news", "analytics"]


def test_eta_from_finished_news():
    from reasoning.progress import calls_for_run, eta_min, etime_sec, news_position
    assert etime_sec("11:06") == 666
    assert etime_sec("1:02:03") == 3723
    assert eta_min(2, 10, 600) == 40
    assert eta_min(0, 10, 30) is None
    rows = [{"step": "hop2.A1.0", "seconds": 10}, {"step": "hop3.A1", "seconds": 20},
            {"step": "hop2.A2.0", "seconds": 10}, {"step": "hop3.OLD", "seconds": 5}]
    assert [r["step"] for r in calls_for_run(rows, 30)] == ["hop3.A1", "hop2.A2.0", "hop3.OLD"]
    assert news_position(["hop2.A1081.0", "hop3.A0618", "hop2.A1081.0", "hop3.A1395"],
                         ["A1081", "A0618", "A1395"]) == (2, "A1395")
    assert news_position(["hop3.A1395", "verify"], ["A1081", "A0618", "A1395"]) == (3, None)


def test_failed_check_keeps_the_analytics():
    class Nope(Fake):
        def json(self, model, prompt, step, tries=3, **_):
            if step.startswith("verify"):
                raise RuntimeError("no json")
            return super().json(model, prompt, step, tries)

    items = {"A1": {"id": "A1", "title": "ЦБ сохранит ставку", "text": f"вчера {QUOTE} на прежнем уровне",
                    "card": {"okved": ["K"], "event_type": "monetary_policy"}}}
    events = [{"id": "A1", "title": items["A1"]["title"], "text": items["A1"]["text"]}]
    profile = {"id": "T", "okved": "B", "okved_name": "Добыча", "region": "siberia_fe", "role": "CFO", "products": ["credit"]}
    role = {"title": "CFO", "authority": "долг", "playbook": "если ставка высокая — фиксировать"}
    page = build(profile, role, events, items, Nope())
    assert any(w["column"] == "analytics" for w in page["widgets"])


def test_quote_must_be_verbatim():
    blobs = {"A1": f"вчера {QUOTE} на прежнем уровне"}
    assert grounded([{"id": "A1", "quote": QUOTE}], blobs)
    assert not grounded([{"id": "A1", "quote": "ставка вырастет"}], blobs)
    assert not grounded([{"id": "нет", "quote": QUOTE}], blobs)


def test_plan_uses_products():
    assert "product" in plan({"okved": ["K"], "event_type": "monetary_policy"}, {"okved": "B", "products": ["credit"]})
    assert plan({"okved": ["B"], "event_type": "labour"}, {"okved": "B", "products": ["credit"]}) == ["direct"]


def test_chain_drops_unrelated_and_builds_arrows():
    items = {
        "A1": {"id": "A1", "title": "ЦБ сохранит ставку", "text": f"вчера {QUOTE} на прежнем уровне",
               "card": {"okved": ["K"], "event_type": "monetary_policy", "horizon": "weeks"}},
        "A2": {"id": "A2", "title": "Матч завершился вничью", "text": "счёт 1:1", "card": {"okved": [], "event_type": "other"}},
    }
    events = [{"id": "A1", "title": items["A1"]["title"], "text": items["A1"]["text"], "source": "тест", "date": "21.10.2026"},
              {"id": "A2", "title": items["A2"]["title"], "text": items["A2"]["text"], "source": "тест", "date": "21.10.2026"}]
    profile = {"id": "T", "okved": "B", "okved_name": "Добыча", "region": "siberia_fe", "role": "CFO", "products": ["credit"]}
    role = {"title": "CFO", "authority": "долг", "playbook": "если ставка высокая — фиксировать"}
    page = build(profile, role, events, items, Fake())
    cols = [w["column"] for w in page["widgets"]]
    assert cols.count("news") == 2 and cols.count("analytics") == 1 and cols.count("decisions") == 1
    assert {l["from"] + l["to"] for l in page["links"]} == {"n1a1", "a1d1"}
    assert page["widgets"][2]["tags"]["confidence"] == "possible"
    got = score(page, [{"n": "ставка долг останется дорогим", "vital": True}], {"A1"})
    assert got["arrows_ok"] and got["invented_ids"] == 0 and got["with_decision"] == 1


def test_alfa_quote_filter():
    pages = {("brief", 2): "Ключевая ставка сохранена на уровне 14 процентов."}
    kept = keep([
        {"doc": "brief", "page": 2, "quote": "ставка сохранена на уровне 14", "claim": "пауза цикла"},
        {"doc": "brief", "page": 2, "quote": "ставка вырастет до 20", "claim": "выдумка"},
    ], pages)
    assert [t["claim"] for t in kept] == ["пауза цикла"]


def test_search_finds_the_rate_story():
    index = Index({"A1": "ключевая ставка сохранена", "A2": "футбол матч ничья"})
    assert index.search("ставка ЦБ", k=1) == ["A1"]


def test_real_packet_parses_and_plans():
    events, items = corpus("U01")
    assert len(events) == 10 and "A1081" in items
    assert plan(items["A1081"].get("card"), profiles()["U01"])
    assert roles()["CFO"]["playbook"]
