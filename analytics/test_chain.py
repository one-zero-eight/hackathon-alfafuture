"""Offline checks of the analytics service: the agents are replaced by a fake that returns canned JSON; run: pytest analytics"""
import time

import pytest
from fastapi.testclient import TestClient

from agents.client import AgentError
from analytics import app as app_module, chain
from analytics.alfa import keep
from analytics.chain import ROLES, bank_position, build, events_from, grounded, hide_loose_bank, make_page, plan, reply, sources
from analytics.search import Index

QUOTE = "Банк России сохранит ставку"
ROLE = {"title": "CFO", "authority": "долг", "playbook": "если ставка высокая — фиксировать"}
PROFILE = {"label": "Тверь", "okved": "B", "okved_code": "06.10", "okved_name": "Добыча", "region": "Тверская область",
           "products": ["credit"], "products_ru": ["кредит"], "facts": "выручка 1 млрд"}


class Fake:
    """Writer answers when the headline concerns the central bank; everything else is irrelevant."""
    def __init__(self, decision_fails=False, verdict="supported", verify_fails=False):
        self.calls, self.decision_fails, self.verdict, self.verify_fails = [], decision_fails, verdict, verify_fails

    def run(self, name, data):
        self.calls.append((name, data))
        if name == "analytics_step":
            if "Банк России" not in data["title"] + data.get("text", ""):
                return {"relevant": False, "evidence": []}
            return {"relevant": True, "done": True, "thought": "Ставка не снизится, долг останется дорогим.",
                    "evidence": [{"id": self.event_id, "quote": QUOTE}]}
        if name == "decision":
            if self.decision_fails:
                raise AgentError("no json")
            return {"title": "Зафиксировать часть долга", "text": "Зафиксировать ставку по половине долга до заседания.",
                    "why": "Ставка не снизится.", "move": "предварительное действие", "contradiction": None,
                    "risks": [{"name": "Ставка всё же снизится", "probability": 2, "impact": 3, "mitigation": "Фиксировать долю."},
                              {"name": "плохая", "probability": 9, "impact": 1, "mitigation": "x"}]}
        if name == "verify":
            if self.verify_fails:
                raise AgentError("down")
            return {"verdicts": [self.verdict] * len(data["claims"])}
        if name == "reply":
            return {"text": "Ответ по разбору", "basis": ["строка", 5]}
        raise AssertionError(name)


NEWS = [{"aid": 1, "title": "ЦБ: Банк России сохранит ставку", "summary": f"вчера {QUOTE} на прежнем уровне", "outlets": ["РБК"],
         "date": "Fri, 23 Oct 2026 10:00:00 +0000", "link": "https://rbc.ru/1"},
        {"aid": 2, "title": "Матч завершился вничью", "summary": "счёт 1:1", "outlets": ["Матч ТВ"], "date": "", "link": "https://m.ru/2"}]


def fake_for(news=NEWS, **kw):
    fake = Fake(**kw)
    fake.event_id = events_from(news, [])[0][0]["id"]
    return fake


def test_page_has_a_chain_for_relevant_news_and_arrows_between_columns():
    page = make_page(fake_for(), PROFILE, "CFO", "", NEWS, [])
    cols = [w["column"] for w in page["widgets"]]
    assert cols.count("news") == 2 and cols.count("analytics") == 1 and cols.count("decisions") == 1
    assert {l["from"] + l["to"] for l in page["links"]} == {"n1a1", "a1d1"}
    news, ana, dec = page["widgets"][0], page["widgets"][1], page["widgets"][2]
    assert news["url"] == "https://rbc.ru/1" and news["details"]["src"] == "РБК" and ana["tags"]["source"] == "ai"
    assert dec["tags"]["confidence"] == "possible" and len(dec["risks"]["risks"]) == 1  # the risk with probability 9 is dropped
    assert dec["chat"]["followups"] == ["Что меняется, если ставка всё же снизится?"] and dec["chat"]["basis"] == ["РБК, 23.10.2026"]
    assert page["company"]["role"] == "Финансовый директор" and page["company"]["okved"] == "06.10 Добыча"


def test_one_failed_decision_keeps_the_news_and_analytics():
    page = make_page(fake_for(decision_fails=True), PROFILE, "CFO", "", NEWS, [])
    assert [w["column"] for w in page["widgets"]] == ["news", "analytics", "news"]


def test_unsupported_conclusion_stays_on_the_page_with_lower_confidence():
    page = make_page(fake_for(verdict="unsupported"), PROFILE, "CFO", "", NEWS, [])
    assert page["widgets"][1]["tags"]["confidence"] == "possible" and len(page["links"]) == 2


def test_failed_check_keeps_the_analytics():
    page = make_page(fake_for(verify_fails=True), PROFILE, "CFO", "", NEWS, [])
    assert any(w["column"] == "analytics" and w["tags"]["confidence"] == "probable" for w in page["widgets"])


def test_a_sphere_goes_to_the_writer_and_the_role_id_picks_the_playbook():
    fake = fake_for()
    page = make_page(fake, PROFILE, "chief_accountant", "закупки", NEWS, [])
    assert page["company"]["role"] == "закупки"
    assert all(d["sphere"] == "закупки" for n, d in fake.calls if n == "analytics_step")
    decision = next(d for n, d in fake.calls if n == "decision")
    assert decision["role"] == ROLES["chief_accountant"] and decision["sphere"] == "закупки"


def test_related_news_from_pairs_are_shown_to_the_writer_first():
    fake = fake_for()
    make_page(fake, PROFILE, "CFO", "", NEWS, [[0, 1]])
    first = next(d for n, d in fake.calls if n == "analytics_step")
    assert "Матч завершился вничью" in first["materials"]


def test_dates_are_shown_in_russian_format_and_unknown_ones_stay_empty():
    events, _, _ = events_from(NEWS, [])
    assert [e["date"] for e in events] == ["23.10.2026", ""]


def test_company_text_without_a_card_names_the_company():
    from analytics.chain import company_text
    assert company_text({"label": "Делимобиль", "region": "Москва"}) == "«Делимобиль», регион Москва"
    assert company_text(PROFILE) == "ОКВЭД 06.10 (Добыча), регион Тверская область, продукты банка: кредит"


def test_grounded_keeps_only_verbatim_quotes_of_known_sources():
    blobs = {"A1": f"вчера {QUOTE} на прежнем уровне"}
    assert grounded([{"id": "A1", "quote": QUOTE}], blobs)
    assert not grounded([{"id": "A1", "quote": "ставка вырастет"}], blobs)
    assert not grounded([{"id": "нет", "quote": QUOTE}], blobs)


def test_plan_uses_products_when_the_event_card_is_known():
    assert "product" in plan({"okved": ["K"], "event_type": "monetary_policy"}, {"okved": "B", "products": ["credit"]})
    assert plan({"okved": ["B"], "event_type": "labour"}, {"okved": "B", "products": ["credit"]}) == ["direct"]
    assert plan(None, PROFILE) == ["direct"]


def test_bank_thesis_follows_the_headline_and_skips_another_year():
    rate, oil = {"id": "A1", "title": "Снижение ключевой ставки отложено"}, {"id": "A2", "title": "Цены на нефть снизились"}
    dollar = {"id": "A3", "title": "Курс доллара опустился до 82 рублей"}
    items = {
        "alfa:rate": {"title": "Ожидание снижения ключевой ставки", "text": "ключевая ставка сохранится высокой"},
        "alfa:oil": {"title": "Цены на нефть демонстрируют высокую волатильность", "text": "цены на нефть волатильны"},
        "alfa:old": {"title": "Курс доллара к рублю в 2022 году достиг 70 руб.", "text": "Курс доллара к рублю в 2022 году достиг 70 руб."},
    }
    docs = {i: items[i]["title"] + " " + items[i]["text"] for i in items}
    docs.update({e["id"]: e["title"] for e in (rate, oil, dollar)})
    index = Index(docs)
    assert bank_position(index, rate, items)["evidence"][0]["id"] == "alfa:rate"
    assert bank_position(index, oil, items)["evidence"][0]["id"] == "alfa:oil"
    assert bank_position(index, dollar, items) is None


def test_embedding_hit_does_not_need_shared_words_but_still_drops_another_year():
    headline = {"id": "A1", "title": "Рубль укрепился четвёртый день"}
    items = {"alfa:fx": {"title": "Курс рубля к доллару США снижается", "text": "рубль дешевеет к доллару"},
             "alfa:old": {"title": "Курс доллара к рублю в 2022 году достиг 70 руб.", "text": "Курс доллара к рублю в 2022 году достиг 70 руб."}}

    class Hit:
        def __init__(self, picked):
            self.picked = picked

        def search(self, query, k=1, prefix=""):
            return [self.picked]

    assert bank_position(Index({}), headline, items) is None
    assert bank_position(Index({}), headline, items, Hit("alfa:fx"))["evidence"][0]["id"] == "alfa:fx"
    old = {"id": "A2", "title": "Курс доллара опустился до 82 рублей"}
    assert bank_position(Index({}), old, items, Hit("alfa:old")) is None


def test_loose_bank_sentence_is_removed():
    page = {"widgets": [
        {"id": "n1", "column": "news", "title": "В Китае введут сертификацию стройматериалов"},
        {"id": "a1", "column": "analytics", "tags": {"source": "alfa"}, "url": "x.pdf",
         "details": {"text": "Позиция банка: Китай копит золото Для компании: закупки станут проще"}}]}
    hide_loose_bank(page)
    assert page["widgets"][1]["details"]["text"] == "Для компании: закупки станут проще"
    assert "url" not in page["widgets"][1] and page["widgets"][1]["tags"]["source"] == "ai"


def test_sources_link_the_pdf_page_and_ask_a_followup_from_the_first_risk():
    page = {"widgets": [
        {"id": "n1", "column": "news", "title": "Ставка", "details": {"text": "x", "src": "Коммерсантъ", "date": "2026-10-21"}},
        {"id": "a1", "column": "analytics", "title": "Дорого", "details": {"text": "Позиция банка: пауза"}},
        {"id": "d1", "column": "decisions", "title": "Зафиксировать", "details": {"text": "Фикс"}, "risks": {"risks": [{"name": "Ставка снизится раньше"}]}}],
        "journal": [{"evidence": ["alfa:Macro:p3:t1"]}], "links": []}
    sources(page)
    assert page["widgets"][1]["url"] == "/api/papers/Macro.pdf#page=3"
    chat = page["widgets"][2]["chat"]
    assert chat["followups"] == ["Что меняется, если ставка снизится раньше?"] and chat["basis"] == ["Коммерсантъ, 2026-10-21", "Macro, стр. 3"]


def test_alfa_quote_filter_keeps_only_quotes_found_on_the_page():
    pages = {("brief", 2): "Ключевая ставка сохранена на уровне 14 процентов."}
    kept = keep([{"doc": "brief", "page": 2, "quote": "ставка сохранена на уровне 14", "claim": "пауза цикла"},
                 {"doc": "brief", "page": 2, "quote": "ставка вырастет до 20", "claim": "выдумка"}], pages)
    assert [t["claim"] for t in kept] == ["пауза цикла"]


def test_search_finds_the_rate_story():
    assert Index({"A1": "ключевая ставка сохранена", "A2": "футбол матч ничья"}).search("ставка ЦБ", k=1) == ["A1"]


def test_theses_are_searchable_next_to_the_news(monkeypatch):
    monkeypatch.setattr("analytics.chain.alfa_embed", lambda items: None)  # lexical thesis search: no encoder in the unit test
    thesis = {"id": "alfa:Macro:p2:t1", "claim": "Банк России сохранит ставку надолго", "quote": QUOTE}
    page = make_page(fake_for(), PROFILE, "CFO", "", NEWS, [], theses=[thesis])
    assert page["widgets"][1]["tags"]["source"] == "alfa" and "Позиция банка" in page["widgets"][1]["details"]["text"]
    assert page["widgets"][1]["url"] == "/api/papers/Macro.pdf#page=2"


def test_reply_keeps_only_text_basis():
    assert reply(Fake(), "Почему?", {"title": "t", "details": {"text": "x"}}, "") == {"text": "Ответ по разбору", "basis": ["строка"]}


def test_http_contract(monkeypatch):
    fake = fake_for()
    monkeypatch.setattr(app_module, "Agents", lambda: fake)
    monkeypatch.setattr(app_module, "load_theses", lambda: [])
    client = TestClient(app_module.app)
    assert client.post("/page", json={"profile": PROFILE, "role": "CFO", "news": []}).status_code == 422
    assert client.post("/page", json={"profile": PROFILE, "role": "janitor", "news": NEWS}).status_code == 422
    r = client.post("/page", json={"profile": PROFILE, "role": "CFO", "news": NEWS})
    assert r.status_code == 200 and len(r.json()["widgets"]) == 4
    assert client.post("/reply", json={"question": "?", "widget": {"title": "t"}}).json()["text"] == "Ответ по разбору"


class Slow(Fake):
    """Every call takes 50 ms, as a network call would."""
    def run(self, name, data):
        time.sleep(0.05)
        return super().run(name, data)


def test_news_are_analysed_at_once_and_the_page_keeps_their_order(monkeypatch):
    news = [{"aid": n, "title": f"Банк России сохранит ставку, часть {n}", "summary": QUOTE, "outlets": ["РБК"], "date": "", "link": f"https://rbc.ru/{n}"}
            for n in range(1, 9)]
    ids = [e["id"] for e in events_from(news, [])[0]]

    class Many(Slow):
        def run(self, name, data):
            if name == "analytics_step":  # the cited id depends on the news of this call, not on a shared attribute
                time.sleep(0.05)
                return {"relevant": True, "done": True, "thought": "Ставка не снизится.",
                        "evidence": [{"id": ids[int(data["title"].rsplit(" ", 1)[1]) - 1], "quote": QUOTE}]}
            return super().run(name, data)

    def timed(workers):
        monkeypatch.setattr(chain, "WORKERS", workers)
        start = time.time()
        page = make_page(Many(), PROFILE, "CFO", "", news, [])
        return page, time.time() - start

    one, t1 = timed(1)
    many, t8 = timed(8)
    assert [w["id"] for w in many["widgets"]] == [w["id"] for w in one["widgets"]]
    assert [w["title"] for w in many["widgets"] if w["column"] == "news"] == [n["title"] for n in news]
    assert t8 < t1 / 2


def test_parallel_analytics_and_verification_keep_trace_context_and_source_references():
    import uuid
    from agents import tracing
    events = []
    observed = []
    fake = fake_for()
    original = fake.run

    def run(name, data):
        observed.append((name, tracing.CURRENT.get().run_id, tracing.PARENT.get()))
        return original(name, data)

    fake.run = run
    trace = tracing.Trace(uuid.uuid4().hex, "cap", "analytics", sender=events.append)
    with tracing.activate(trace), tracing.span("run"):
        make_page(fake, PROFILE, "CFO", "", NEWS, [])
    assert not trace.incomplete
    assert {name for name, _, _ in observed} >= {"analytics_step", "decision", "verify"}
    assert all(run_id == trace.run_id and parent for _, run_id, parent in observed)
    completed = [e for e in events if e.status == "completed"]
    assert {"analytics", "decision", "verification"} <= {e.step for e in completed}
    assert any("N1" in e.source_ids for e in completed)
