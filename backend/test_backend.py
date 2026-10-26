"""Backend checks. The search and analytics services are replaced by fakes; PostgreSQL tests need TEST_DATABASE_URL.
Run: TEST_DATABASE_URL=postgres://... pytest backend"""
import csv
import importlib
import os
import uuid

import psycopg
import pytest
from fastapi.testclient import TestClient

from backend import app as app_module, companies, config, pages, store, worker
from backend.focus import interpret

needs_db = pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="set TEST_DATABASE_URL to run PostgreSQL tests")
NEWS = {"top": [{"aid": 1, "title": "ЦБ сохранил ставку", "summary": "текст", "outlets": ["РБК"], "date": "", "link": "https://rbc.ru/1"}],
        "pairs": [], "cost": 0.5, "stats": {"unique": 40}}
PAGE = {"version": 1, "company": {"name": "Тверь", "okved": "06.10 Добыча", "role": "Финансовый директор", "date": "24 октября 2026"},
        "widgets": [
            {"id": "n1", "column": "news", "title": "ЦБ сохранил ставку", "url": "https://rbc.ru/1", "tags": {},
             "details": {"text": "текст", "src": "РБК", "date": ""}, "chat": {"text": "текст", "basis": ["РБК"], "followups": []}},
            {"id": "a1", "column": "analytics", "title": "Долг дорогой", "tags": {"confidence": "probable", "source": "ai"}, "details": {"text": "Для компании: дорого"}},
            {"id": "d1", "column": "decisions", "title": "Зафиксировать", "tags": {"urgency": "urgent"}, "details": {"text": "Фикс"},
             "risks": {"steps": ["Фикс"], "bank_offer": None, "risks": [{"name": "Ставка снизится", "probability": 2, "impact": 3, "mitigation": "x"}]},
             "chat": {"text": "Зафиксировать", "basis": [], "followups": ["Что меняется, если ставка снизится?"]}}],
        "links": [{"id": "l1a", "from": "n1", "to": "a1", "text": "почему"}, {"id": "l1d", "from": "a1", "to": "d1", "text": "потому"}],
        "journal": []}


@pytest.fixture
def db(monkeypatch):
    dsn = os.environ.get("TEST_DATABASE_URL")
    if not dsn:
        pytest.skip("set TEST_DATABASE_URL to run PostgreSQL tests")
    schema = "bt_" + uuid.uuid4().hex[:8]
    with psycopg.connect(dsn, autocommit=True) as admin:
        admin.execute(f"CREATE SCHEMA {schema}")
        monkeypatch.setattr(config, "DATABASE_URL", dsn + ("&" if "?" in dsn else "?") + f"options=-csearch_path%3D{schema}")
        store.init()
        yield
        admin.execute(f"DROP SCHEMA {schema} CASCADE")


@pytest.fixture
def services(monkeypatch):
    """Fake news_search and analytics. Returns the list of requests they received."""
    sent = []

    def post(url, body, what):
        sent.append((url, body))
        if url.endswith("/search"):
            if body["company"] == "Пустая":
                raise worker.ProfileError("news_search: HTTP 422: too few news collected")
            return NEWS
        return PAGE

    monkeypatch.setattr(worker, "_post", post)
    return sent


client = TestClient(app_module.app)


def request_page(role="Финансовый директор", **extra):
    body = {"company": "Делимобиль", "role": role, **extra}
    key = client.post("/api/profile", json=body).json()["key"]
    worker.run_once()
    return key


@needs_db
def test_profile_goes_through_queue_search_and_analytics_to_a_page(db, services):
    queued = client.post("/api/profile", json={"company": "Делимобиль", "role": "Финансовый директор"}).json()
    assert queued["status"] == "queued" and client.get(f"/api/profile/{queued['key']}").json()["status"] == "queued"
    assert worker.run_once() and not worker.run_once()
    done = client.get(f"/api/profile/{queued['key']}").json()
    assert done["status"] == "ready" and done["error"] == "" and done["stage"] == "analysis" and (done["found"], done["selected"]) == (40, 1)
    search, analytics = services[0][1], services[1][1]
    assert search == {"company": "Делимобиль", "line": "Финансовый директор", "region": "", "method": "dense_xquad", "anonymised": False,
                      "locality": 0.1}
    assert analytics["role"] == "CFO" and analytics["sphere"] == "" and analytics["news"] == NEWS["top"] and analytics["profile"]["label"] == "Делимобиль"
    page = client.get(f"/api/page?profile={queued['key']}").json()
    k = queued["key"]
    assert [w["id"] for w in page["widgets"]] == [f"{k}_n1", f"{k}_a1", f"{k}_d1"] and "details" not in page["widgets"][0]
    assert page["links"][0] == {"id": f"{k}_l1a", "from": f"{k}_n1", "to": f"{k}_a1"} and page["company"]["name"] == "Тверь"
    assert client.get(f"/api/widgets/{k}_n1").json()["src"] == "РБК"
    assert client.get(f"/api/widgets/{k}_d1/risks").json()["risks"][0]["name"] == "Ставка снизится"
    assert client.get(f"/api/widgets/{k}_n1/risks").status_code == 404
    assert client.get(f"/api/links/{k}_l1a").json()["text"] == "почему"


@needs_db
def test_same_request_is_served_from_the_page_and_a_new_method_computes_a_new_one(db, services, monkeypatch):
    first = client.post("/api/profile", json={"company": "Делимобиль", "role": "CFO"}).json()
    worker.run_once()
    again = client.post("/api/profile", json={"company": "делимобиль", "role": "cfo"}).json()
    assert again == {"key": first["key"], "status": "ready", "error": "", "cached": True} and first["cached"] is False and not worker.run_once()
    monkeypatch.setattr(config, "NEWS_SEARCH_METHOD", "lexical")
    other = client.post("/api/profile", json={"company": "Делимобиль", "role": "CFO"}).json()
    assert other["key"] != first["key"] and other["status"] == "queued"
    worker.run_once()
    assert services[-2][1]["method"] == "lexical"


@needs_db
def test_a_failure_is_reported_on_the_profile_and_a_resubmit_requeues_it(db, services):
    key = client.post("/api/profile", json={"company": "Пустая", "role": "Закупки"}).json()["key"]
    worker.run_once()
    status = client.get(f"/api/profile/{key}").json()
    assert status["status"] == "failed" and "too few news" in status["error"]
    assert client.get(f"/api/page?profile={key}").status_code == 404
    assert client.post("/api/profile", json={"company": "Пустая", "role": "Закупки"}).json()["status"] == "queued"


@needs_db
def test_sphere_typos_share_a_page_but_a_job_changes_the_playbook(db, services):
    a = client.post("/api/profile", json={"company": "X", "role": "закупкки"}).json()["key"]
    b = client.post("/api/profile", json={"company": "X", "role": "снабжение"}).json()["key"]
    c = client.post("/api/profile", json={"company": "X", "role": "главный бухгалтер"}).json()["key"]
    assert a == b != c
    worker.run_once()
    analytics = next(body for url, body in services if url.endswith("/page"))
    assert analytics["sphere"] == "закупкки" and analytics["role"] == "CFO"


@needs_db
def test_chat_message_on_a_profile_page_is_queued_and_open_is_instant(db, services):
    k = request_page()
    ctx = {"type": "widget", "id": f"{k}_d1"}
    opened = client.post("/api/chat", json={"context": ctx, "message": None, "page_version": 1}).json()
    assert opened["patch"] is None and opened["reply"]["followups"]
    link_chat = client.post("/api/chat", json={"context": {"type": "link", "id": f"{k}_l1a"}, "message": None, "page_version": 1}).json()
    assert link_chat["reply"]["basis"] == ["ЦБ сохранил ставку", "Долг дорогой"]
    assert client.post("/api/chat", json={"context": ctx, "message": "что с долгом?", "page_version": 9}).status_code == 409
    queued = client.post("/api/chat", json={"context": ctx, "message": "что с долгом?", "page_version": 1})
    assert queued.status_code == 202 and set(queued.json()) == {"session_id", "operation_id", "status"}
    polled = client.get(f"/api/feedback/{queued.json()['operation_id']}").json()
    assert polled["status"] == "queued" and polled["result"] is None


def test_demo_page_is_the_default_and_its_edits_do_not_touch_the_database():
    page = client.get("/api/page").json()
    assert len(page["widgets"]) == 18 and len(page["links"]) == 15 and set(page["widgets"][0]) <= {"id", "column", "title", "url", "tags"}
    assert client.get("/api/widgets/a1").json()["chart"]["type"] == "line"
    assert len(client.get("/api/widgets/d1/risks").json()["risks"]) == 4
    assert client.get("/api/widgets/nope").status_code == 404
    before = app_module.DEMO_PAGE["version"]
    r = client.post("/api/chat", json={"context": {"type": "widget", "id": "n1"}, "message": "добавь аналитику", "page_version": before}).json()
    assert r["patch"]["version"] == before + 1 and r["patch"]["ops"][0]["widget"]["tags"]["source"] == "human"
    assert client.post("/api/chat", json={"context": {"type": "widget", "id": "n1"}, "message": "добавь", "page_version": 0}).status_code == 409


def test_profile_input_is_validated():
    for body in ({"company": "X", "role": ""}, {"role": "CFO"}, {"company": "X", "role": "CFO", "company_id": "abc"},
                 {"company": "X" * 201, "role": "CFO"}, {"company": "X", "role": "а" * 501}):
        assert client.post("/api/profile", json=body).status_code == 422, body


def test_company_id_typed_in_the_company_field_is_recognised(monkeypatch):
    seen = {}
    monkeypatch.setattr(store, "submit", lambda **kw: seen.update(kw) or (kw["key"], "queued", ""))
    client.post("/api/profile", json={"company": "U_42", "role": "CFO"})
    assert seen["company_id"] == "U_42" and seen["company"] == ""


def test_unknown_search_method_stops_the_service_at_startup(monkeypatch):
    monkeypatch.setenv("NEWS_SEARCH_METHOD", "graph")
    with pytest.raises(SystemExit):
        importlib.reload(config)
    monkeypatch.delenv("NEWS_SEARCH_METHOD")
    importlib.reload(config)


def test_publish_prefixes_every_id_and_keeps_the_input_intact():
    published = pages.publish("abc123abc123", PAGE, {"method": "x"})
    assert {w["id"] for w in published["widgets"]} == {"abc123abc123_n1", "abc123abc123_a1", "abc123abc123_d1"} and PAGE["widgets"][0]["id"] == "n1"
    assert published["links"][1]["from"] == "abc123abc123_a1" and published["meta"] == {"method": "x"}


def fixture_csv(folder):
    fields = ["SYNTHETIC_U", "MAINOKVED_CODE", "MAINOKVED_NAME", "CITY", "REGION", "REVENUE_COMPANY", "GROUP_ID", "AMOUNT_WORKERS_FNS_GRADATION",
              "COMPANY_AGE_YEARS_GRADATION", "CL_PRODUCT_LOA_MARK", "CL_PRODUCT_LEA_MARK", "CL_PRODUCT_DEP_MARK", "CL_PRODUCT_ZPP_MARK",
              "CL_PRODUCT_RKO_MARK", "CL_PRODUCT_GAR_MARK", "FACTORING_MARK", "FTS_FLAG", "FTS_COUNTRY_NAME"]
    zero = {f: "0.0" for f in fields}
    rows = [{**zero, "SYNTHETIC_U": "U_1", "MAINOKVED_CODE": "41.20", "MAINOKVED_NAME": "Строительство", "CITY": "Иркутск", "REGION": "Иркутская область",
             "REVENUE_COMPANY": "20000000000", "GROUP_ID": "g1", "AMOUNT_WORKERS_FNS_GRADATION": "101-250", "CL_PRODUCT_LOA_MARK": "1.0",
             "FTS_FLAG": "1.0", "FTS_COUNTRY_NAME": "Китай"},
            {**zero, "SYNTHETIC_U": "U_2", "MAINOKVED_CODE": "46.71", "MAINOKVED_NAME": "Торговля топливом", "CITY": "Москва", "REGION": "Москва", "GROUP_ID": "g1"},
            {**zero, "SYNTHETIC_U": "U_3", "MAINOKVED_CODE": "23.51", "MAINOKVED_NAME": "Производство цемента", "CITY": "Тверь", "REGION": "Тверская область"}]
    with (folder / "df_Uid_data_hack.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, delimiter=";", fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    with (folder / "df_Uid_payment_hack.csv").open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["BENEFICIARY", "PAYER", "PAY_AMT", "PAY_CNT"])
        w.writerows([["U_1", "U_1", "999", "1"], ["U_1", "U_2", "75", "2"], ["U_1", "U_9", "25", "1"], ["U_3", "U_1", "40", "1"]])


def test_company_profile_serves_search_and_analytics_and_hides_the_id(tmp_path):
    fixture_csv(tmp_path)
    p = companies.CompanyBook(tmp_path).profile("U_1")
    assert p["label"] == "Иркутск" and "U_1" not in p["description"] and "ОКВЭД 41.20 «Строительство»" in p["description"]
    assert "основные поставщики: Производство цемента" in p["description"] and "основные покупатели: Торговля топливом" in p["description"]
    assert "ведёт внешнеэкономическую деятельность (Китай)" in p["description"] and "сотрудников: 101-250" in p["description"]
    assert p["okved"] == "F" and p["products"] == ["credit"] and p["products_ru"] == ["кредиты"] and p["region"] == "Иркутская область"
    assert p["workers"] == "101-250" and p["suppliers"] == ["Производство цемента"] and "Торговля топливом" in p["customers"]
    assert "20.0 млрд руб." in p["facts"] and "2 комп." in p["facts"] and "U_2" in p["facts"] and "75%" in p["facts"] and "Внешняя торговля: Китай." in p["facts"]
    assert p["date_label"] == "выручка 20.0 млрд руб., Иркутск"
    with pytest.raises(companies.CompanyUnavailable):
        companies.CompanyBook(tmp_path).profile("U_404")
    with pytest.raises(companies.CompanyUnavailable):
        companies.CompanyBook(tmp_path / "missing").profile("U_1")


def test_company_list_is_paged_and_searchable(tmp_path, monkeypatch):
    fixture_csv(tmp_path)
    book = companies.CompanyBook(tmp_path)
    assert book.listing("", 0, 2) == {"total": 3, "items": [{"id": "U_1", "okved_name": "Строительство"}, {"id": "U_2", "okved_name": "Торговля топливом"}]}
    assert book.listing("", 2, 2)["items"] == [{"id": "U_3", "okved_name": "Производство цемента"}]
    assert [c["id"] for c in book.listing("ТОПЛИВ", 0, 10)["items"]] == ["U_2"] and book.listing("u_3", 0, 10)["total"] == 1
    monkeypatch.setattr(worker, "book", book)
    got = client.get("/api/companies?q=цемент&limit=5").json()
    assert got["total"] == 1 and got["items"][0]["id"] == "U_3"
    monkeypatch.setattr(worker, "book", companies.CompanyBook(tmp_path / "missing"))
    assert client.get("/api/companies").status_code == 503


def test_okved_sections():
    assert companies.okved_section("42.99") == "F" and companies.okved_section("06.10.1") == "B" and companies.okved_section("x") == ""


@needs_db
def test_company_id_profile_uses_bank_data_for_the_search_and_analytics(db, services, tmp_path, monkeypatch):
    fixture_csv(tmp_path)
    monkeypatch.setattr(worker, "book", companies.CompanyBook(tmp_path))
    key = client.post("/api/profile", json={"company_id": "U_1", "role": "CFO"}).json()["key"]
    worker.run_once()
    search, analytics = services[0][1], services[1][1]
    assert search["anonymised"] and search["region"] == "Иркутская область" and search["company"].startswith("компания, ОКВЭД 41.20")
    assert 0 <= search["locality"] <= 1
    assert analytics["profile"]["okved_name"] == "Строительство" and client.get(f"/api/profile/{key}").json()["status"] == "ready"
    missing = client.post("/api/profile", json={"company_id": "U_404", "role": "CFO"}).json()["key"]
    worker.run_once()
    assert "not found" in client.get(f"/api/profile/{missing}").json()["error"]


def test_role_line_is_read_once_for_playbook_and_sphere():
    assert interpret("главный бухгалтер").role == "chief_accountant" and interpret("главный бухгалтер").sphere == ""
    assert interpret("Маркетинг").sphere == "Маркетинг" and interpret("закупкки").topic == "procurement"


def test_locality_falls_with_revenue_and_foreign_trade(tmp_path):
    rows = [("U_1", "1000000", "0.0"), ("U_2", "50000000", "0.0"), ("U_3", "900000000", "0.0"), ("U_4", "900000000", "1.0"), ("U_5", "", "0.0")]
    head = "SYNTHETIC_U;REVENUE_COMPANY;FTS_FLAG;AMOUNT_WORKERS_FNS_GRADATION;MAINOKVED_CODE;MAINOKVED_NAME;CITY;REGION\n"
    (tmp_path / "df_Uid_data_hack.csv").write_text(head + "".join(f"{u};{r};{f};Менее 15;41.20;Строительство;г. Тверь;Тверская область\n"
                                                                   for u, r, f in rows), encoding="utf-8")
    book = companies.CompanyBook(tmp_path)
    small, mid, big, exporter, unknown = (book.profile(u)["locality"] for u, _, _ in rows)
    assert small == 0.8 and small >= mid > big and exporter == round(big / 2, 2) and unknown == 0.8  # staff "Менее 15" caps at 0.8
