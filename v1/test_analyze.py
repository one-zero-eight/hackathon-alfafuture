"""Self-check of analyze.build_page with a stubbed LLM answer (no network): `python test_analyze.py`."""
import analyze

TOP = [{"title": f"Новость {i}", "link": f"https://x.ru/{i}", "date": "Mon, 12 Oct 2026 10:00:00 +0000", "outlets": ["РБК"]} for i in range(10)]
ANSWER = {
    "news": [{"i": 0, "industry": "Банки", "why": "Ставка выросла."}, {"i": 99, "why": "bad index"}, {"i": 0, "why": "dup"}],
    "analytics": [{"id": "a1", "title": "Кредит дорожает", "text": "Вероятно.", "confidence": "bogus", "followups": ["Почему?"]}],
    "decisions": [{"id": "d1", "title": "Зафиксировать ставку", "text": "Сделать.", "urgency": "urgent", "steps": ["Шаг"],
                   "risks": [{"name": "Риск", "probability": 9, "impact": 0, "mitigation": "м"}, {"name": "без чисел"}], "bank_offer": None}],
    "news_to_analytics": [{"news": 0, "analytics": "a1", "text": "связь"}, {"news": 5, "analytics": "a1", "text": "новость не выбрана"}],
    "analytics_to_decisions": [{"analytics": "a1", "decision": "d1", "text": "связь"}, {"analytics": "a9", "decision": "d1", "text": "нет такого"}],
}
analyze.chat_json = lambda *a, **k: ANSWER
page = analyze.build_page("k1", "Компания", "Роль", TOP)
ids = {w["id"] for w in page["widgets"]}
assert ids == {"k1_n0", "k1_a1", "k1_d1"}, ids  # bad index and duplicate dropped
assert [(l["from"], l["to"]) for l in page["links"]] == [("k1_n0", "k1_a1"), ("k1_a1", "k1_d1")]
a = next(w for w in page["widgets"] if w["id"] == "k1_a1")
assert a["tags"]["confidence"] == "possible" and a["chat"]["basis"] == ["Новость 0"]
d = next(w for w in page["widgets"] if w["id"] == "k1_d1")
assert d["risks"]["risks"] == [{"name": "Риск", "probability": 4, "impact": 1, "mitigation": "м"}]  # clamped to 1..4, incomplete risk dropped
assert next(w for w in page["widgets"] if w["column"] == "news")["url"] == "https://x.ru/0"  # url comes from the corpus
ANSWER = {"news": [{"i": 0, "why": "x"}]}
try:
    analyze.build_page("k1", "c", "r", TOP); raise SystemExit("must fail on incomplete analysis")
except RuntimeError:
    pass
print("ok")
