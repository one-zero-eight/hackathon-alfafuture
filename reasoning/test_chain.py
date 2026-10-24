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
    from reasoning.progress import remaining_sec
    assert remaining_sec(2, 10, 600, 600) == 2400
    assert remaining_sec(2, 10, 600, 601) == 2399
    assert remaining_sec(0, 10, 10, 20) is None
    rows = [{"step": "hop2.A1.0", "seconds": 10}, {"step": "hop3.A1", "seconds": 20},
            {"step": "hop2.A2.0", "seconds": 10}, {"step": "hop3.OLD", "seconds": 5}]
    assert [r["step"] for r in calls_for_run(rows, 30)] == ["hop3.A1", "hop2.A2.0", "hop3.OLD"]
    assert news_position(["hop2.A1081.0", "hop3.A0618", "hop2.A1081.0", "hop3.A1395"],
                         ["A1081", "A0618", "A1395"]) == (2, "A1395")
    assert news_position(["hop3.A1395", "verify"], ["A1081", "A0618", "A1395"]) == (3, None)


def test_unsupported_conclusion_stays_on_the_page():
    class Harsh(Fake):
        def json(self, model, prompt, step, tries=3, **_):
            if step.startswith("verify"):
                return {"verdicts": ["unsupported"]}
            return super().json(model, prompt, step, tries)

    items = {"A1": {"id": "A1", "title": "ЦБ сохранит ставку", "text": f"вчера {QUOTE} на прежнем уровне",
                    "card": {"okved": ["K"], "event_type": "monetary_policy"}}}
    events = [{"id": "A1", "title": items["A1"]["title"], "text": items["A1"]["text"]}]
    profile = {"id": "T", "okved": "B", "okved_name": "Добыча", "region": "siberia_fe", "role": "CFO", "products": ["credit"]}
    role = {"title": "CFO", "authority": "долг", "playbook": "если ставка высокая — фиксировать"}
    page = build(profile, role, events, items, Harsh())
    assert [w["column"] for w in page["widgets"]] == ["news", "analytics", "decisions"]
    assert page["widgets"][1]["tags"]["confidence"] == "possible"
    assert len(page["links"]) == 2


def test_bank_thesis_follows_the_headline_and_skips_another_year():
    from reasoning.chain import bank_position
    rate = {"id": "A1", "title": "Снижение ключевой ставки отложено"}
    oil = {"id": "A2", "title": "Цены на нефть снизились"}
    dollar = {"id": "A3", "title": "Курс доллара опустился до 82 рублей"}
    items = {
        "alfa:rate": {"title": "Ожидание снижения ключевой ставки", "text": "ключевая ставка сохранится высокой"},
        "alfa:oil": {"title": "Цены на нефть демонстрируют высокую волатильность", "text": "цены на нефть волатильны"},
        "alfa:old": {"title": "Курс доллара к рублю в 2022 году достиг 70 руб.", "text": "Курс доллара к рублю в 2022 году достиг 70 руб."},
    }
    docs = {i: items[i]["title"] + " " + items[i]["text"] for i in items}
    docs.update({e["id"]: e["title"] for e in (rate, oil, dollar)})
    index = Index(docs)
    bank = bank_position(index, rate, items)
    assert bank and bank["role"] == "alfa" and bank["evidence"][0]["id"] == "alfa:rate"
    assert bank_position(index, oil, items)["evidence"][0]["id"] == "alfa:oil"
    assert bank_position(index, dollar, items) is None


def test_embedding_hit_does_not_need_shared_words_but_still_drops_another_year():
    from reasoning.chain import bank_position
    headline = {"id": "A1", "title": "Рубль укрепился четвёртый день"}
    items = {
        "alfa:fx": {"title": "Курс рубля к доллару США снижается", "text": "рубль дешевеет к доллару"},
        "alfa:old": {"title": "Курс доллара к рублю в 2022 году достиг 70 руб.",
                     "text": "Курс доллара к рублю в 2022 году достиг 70 руб."},
    }

    class Hit:
        def __init__(self, picked):
            self.picked = picked

        def search(self, query, k=1, prefix=""):
            return [self.picked]

    assert bank_position(Index({}), headline, items) is None
    got = bank_position(Index({}), headline, items, Hit("alfa:fx"))
    assert got["evidence"][0]["id"] == "alfa:fx"
    old = {"id": "A2", "title": "Курс доллара опустился до 82 рублей"}
    assert bank_position(Index({}), old, items, Hit("alfa:old")) is None
    items["alfa:gold"] = {"title": "Китай ускоряет накопление золота", "text": "золото в резервах"}
    china = {"id": "A3", "title": "В Китае введут сертификацию стройматериалов"}
    assert bank_position(Index({}), china, items, Hit("alfa:gold")) is None


def test_loose_bank_sentence_is_removed():
    from reasoning.chain import hide_loose_bank
    page = {"widgets": [
        {"id": "n1", "column": "news", "title": "В Китае введут сертификацию стройматериалов"},
        {"id": "a1", "column": "analytics", "tags": {"source": "alfa"}, "url": "x.pdf",
         "details": {"text": "Позиция банка: Китай копит золото Для компании: закупки станут проще"}},
    ]}
    hide_loose_bank(page)
    assert page["widgets"][1]["details"]["text"] == "Для компании: закупки станут проще"
    assert "url" not in page["widgets"][1] and page["widgets"][1]["tags"]["source"] == "ai"


def test_followup_comes_from_the_risk_and_missing_pdf_has_no_link():
    from reasoning.chain import sources
    from reasoning.view import html
    page = {"widgets": [
        {"id": "n1", "column": "news", "title": "Ставка", "details": {"text": "x", "src": "Коммерсантъ", "date": "2026-10-21"}},
        {"id": "a1", "column": "analytics", "title": "Дорого", "details": {"text": "Позиция банка: пауза"}},
        {"id": "d1", "column": "decisions", "title": "Зафиксировать", "details": {"text": "Фикс"},
         "risks": {"risks": [{"name": "Ставка снизится раньше"}]}},
    ], "journal": [{"evidence": ["alfa:NO_SUCH_DOC:p3:t1"]}], "links": []}
    sources(page)
    assert "url" not in page["widgets"][1]
    chat = page["widgets"][2]["chat"]
    assert chat["followups"] == ["Что меняется, если ставка снизится раньше?"]
    assert chat["basis"] == ["Коммерсантъ, 2026-10-21", "NO_SUCH_DOC, стр. 3"]
    assert "Уточнить" in html(page) and "Материал банка" not in html(page)


def test_page_shows_the_chain():
    from reasoning.view import bar, html, tree
    assert bar(4, 10, width=10) == "████░░░░░░"
    page = {"widgets": [
        {"id": "n1", "column": "news", "title": "Ставка", "details": {"text": "Ставка"}},
        {"id": "a1", "column": "analytics", "title": "Дорого", "details": {"text": "Позиция банка: пауза. Для компании: долг дорогой."}},
        {"id": "d1", "column": "decisions", "title": "Зафиксировать", "details": {"text": "Фиксировать долю"}},
    ], "links": []}
    assert "→" in html(page) and "Позиция банка" in html(page) and "Зафиксировать" in tree(page)


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


def test_embed_gold_rejects_the_wrong_year():
    from reasoning.compare_embed import ok
    assert ok("alfa:rate:p2:t3", ["p4:t2"], ["p2:t3"]) is False
    assert ok("alfa:rate:p4:t2", ["p4:t2"], ["p2:t3"]) is True
    assert ok("alfa:rail", [], ["ставк"]) is True
    assert ok("alfa:ставк", [], ["ставк"]) is False
    blobs = {"A1": f"вчера {QUOTE} на прежнем уровне"}
    assert grounded([{"id": "A1", "quote": QUOTE}], blobs)
    assert not grounded([{"id": "A1", "quote": "ставка вырастет"}], blobs)
    assert not grounded([{"id": "нет", "quote": QUOTE}], blobs)


def test_company_line_uses_revenue_group_and_skips_self_payments(tmp_path, monkeypatch):
    import csv
    folder = tmp_path
    with (folder / "df_Uid_data_hack.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, delimiter=";", fieldnames=[
            "SYNTHETIC_U", "MAINOKVED_CODE", "MAINOKVED_NAME", "CITY", "REGION",
            "REVENUE_COMPANY", "GROUP_ID", "CL_PRODUCT_LOA_MARK", "CL_PRODUCT_LEA_MARK",
            "CL_PRODUCT_DEP_MARK", "CL_PRODUCT_ZPP_MARK", "CL_PRODUCT_RKO_MARK",
            "CL_PRODUCT_GAR_MARK", "FACTORING_MARK", "FTS_FLAG", "FTS_COUNTRY_NAME"])
        w.writeheader()
        w.writerow({"SYNTHETIC_U": "U_1", "MAINOKVED_CODE": "41.20", "MAINOKVED_NAME": "Строительство",
                    "CITY": "Иркутск", "REGION": "Иркутская область", "REVENUE_COMPANY": "20000000000",
                    "GROUP_ID": "g1", "CL_PRODUCT_LOA_MARK": "1.0", "CL_PRODUCT_LEA_MARK": "0.0",
                    "CL_PRODUCT_DEP_MARK": "0.0", "CL_PRODUCT_ZPP_MARK": "0.0", "CL_PRODUCT_RKO_MARK": "0.0",
                    "CL_PRODUCT_GAR_MARK": "0.0", "FACTORING_MARK": "0.0", "FTS_FLAG": "0.0", "FTS_COUNTRY_NAME": ""})
        w.writerow({"SYNTHETIC_U": "U_2", "MAINOKVED_CODE": "46.71", "MAINOKVED_NAME": "Торговля топливом",
                    "CITY": "Москва", "REGION": "Москва", "REVENUE_COMPANY": "1000", "GROUP_ID": "g1",
                    "CL_PRODUCT_LOA_MARK": "0.0", "CL_PRODUCT_LEA_MARK": "0.0", "CL_PRODUCT_DEP_MARK": "0.0",
                    "CL_PRODUCT_ZPP_MARK": "0.0", "CL_PRODUCT_RKO_MARK": "0.0", "CL_PRODUCT_GAR_MARK": "0.0",
                    "FACTORING_MARK": "0.0", "FTS_FLAG": "0.0", "FTS_COUNTRY_NAME": ""})
    with (folder / "df_Uid_payment_hack.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"])
        w.writerow(["U_1", "U_1", "999", "1"])
        w.writerow(["U_1", "U_2", "75", "2"])
        w.writerow(["U_1", "U_9", "25", "1"])
    monkeypatch.setenv("COMPANY_DIR", str(folder))
    from reasoning.company import card, line
    text = line("U_1")
    assert "20.0 млрд руб." in text and "2 комп." in text and "кредит" in text
    assert "U_2" in text and "75%" in text and "U_1:" in text
    assert line("Газпром") == ""
    profile = card("U_1", "CFO")
    assert profile["okved"] == "F" and profile["products"] == ["credit"] and profile["label"] == "U_1"
    assert "20.0 млрд" in profile["date_label"] and card("нет") is None


def test_company_news_keeps_construction_and_the_rate():
    from reasoning.chain import role_key
    from reasoning.data import okved_section, pick
    assert okved_section("42.99") == "F" and okved_section("06.10.1") == "B"
    assert role_key("финансовый директор") == "CFO" and role_key("неизвестно") == "CFO"
    rows = [
        {"sid": "A2", "okved": ["F"], "event_type": "other", "event": "Строительный суд"},
        {"sid": "A1", "okved": ["F"], "event_type": "macro_data", "event": "Число строительных компаний сократилось"},
        {"sid": "A3", "okved": ["K"], "event_type": "monetary_policy", "event": "Нацбанк Украины подал в отставку"},
        {"sid": "A4", "okved": ["K"], "event_type": "monetary_policy", "event": "ЦБ сохранит ключевую ставку"},
    ]
    library = {c["sid"]: {"text": "x" * 90} for c in rows}
    assert [c["sid"] for c in pick(rows, library, "F", ["credit"])] == ["A1", "A4"]
    rows += [
        {"sid": "A5", "okved": ["G"], "event_type": "macro_data", "event": "Оборот розницы вырос"},
        {"sid": "A6", "okved": ["C"], "event_type": "supply_logistics", "event": "Склад отгрузил партию"},
    ]
    library = {c["sid"]: {"text": "x" * 90} for c in rows}
    assert [c["sid"] for c in pick(rows, library, "G", [])] == ["A5"]
    assert [c["sid"] for c in pick(rows, library, "", [], topic="procurement")] == ["A6"]


def test_sphere_typos_share_a_page():
    from reasoning.focus import cache_key, interpret
    buy = interpret("ответственный за закупки")
    assert buy.topic == "procurement" and buy.role is None
    assert interpret("закупкки").topic == "procurement" and interpret("снабжение").topic == "procurement"
    assert interpret("строителство").section == "F" and interpret("нефть").section == "B"
    assert interpret("финансовй директор").role == "CFO"
    assert cache_key("U_9", interpret("закупкки"), "F") == cache_key("U_9", interpret("снабжение"), "F") == "U_9__procurement"
    assert cache_key("U_9", interpret("стройка"), "F") == "U_9"
    assert cache_key("U_9", interpret("нефть"), "F") == "U_9__B"
    assert cache_key("U_9", interpret("финансовй директор"), "F") == "U_9"


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
