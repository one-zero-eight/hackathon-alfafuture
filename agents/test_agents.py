"""Offline checks of the agents service: prompts, JSON retries, validation, HTTP. The gateway is replaced by a fake; run: pytest agents"""
import pytest
from fastapi.testclient import TestClient

from agents import app as agents_app
from agents.app import app

client = TestClient(app)


def fake_chat(monkeypatch, *answers):
    """Each call returns the next answer (text, usage); the last one repeats. Returns the list of prompts the agents sent."""
    prompts, queue = [], list(answers)

    def chat(model, content, max_tokens, read_timeout=600):
        prompts.append(content if isinstance(content, str) else content[0]["text"])
        text = queue.pop(0) if len(queue) > 1 else queue[0]
        return text, {"total_tokens": 10, "cost": 0.5}

    monkeypatch.setattr(agents_app, "chat", chat)
    return prompts


def test_render_fills_known_placeholders_and_keeps_json_braces():
    out = agents_app.render("hyde", company="Ромашка", where=" Регион: «Тверь».", line="Закупки")
    assert "«Ромашка». Регион: «Тверь»." in out and '{"headlines": [...]}' in out and "{company}" not in out


def test_every_agent_builds_a_prompt_from_minimal_input():
    inputs = {
        "feedback_intent": {"message": "Почему?", "context": {"widgets": [], "links": []}},
        "trace_description": {"events": []},
        "queries": {"company": "Ромашка", "line": "Закупки", "region": "Тверь"},
        "needs": {"company": "Ромашка", "line": "Закупки"},
        "hyde": {"company": "Ромашка", "line": "Закупки"},
        "pick": {"company": "Ромашка", "line": "Закупки", "candidates": [{"id": 1, "title": "Заголовок", "date": "", "outlets": ["РБК"]}]},
        "analytics_step": {"company": "ОКВЭД 49.41 (Перевозки), регион Тверь, продукты банка: кредит", "kinds": ["direct"],
                           "title": "Ставка выросла", "thoughts": [], "materials": "[A1] текст"},
        "decision": {"role": {"title": "CFO", "authority": "бюджет", "playbook": "правила"}, "moves": {}, "title": "Ставка", "notes": []},
        "verify": {"claims": [{"text": "вывод", "quote": "цитата"}]},
        "reply": {"question": "Почему?", "title": "Заголовок", "text": "Текст"},
        "alfa_page": {"page": 3, "text": "текст страницы"},
    }
    assert set(inputs) == set(agents_app.AGENTS)
    for name, data in inputs.items():
        prompt = agents_app.AGENTS[name].build(data)
        assert prompt and "{company}" not in prompt and "{title}" not in prompt, name


def test_json_call_retries_until_valid_json_with_key(monkeypatch):
    prompts = fake_chat(monkeypatch, "", '{"needs": []}', 'ответ: {"needs": ["Как изменится ставка?", " "]}')
    out = agents_app.run("needs", {"company": "Ромашка", "line": "Закупки"})
    assert out == {"needs": ["Как изменится ставка?"]} and len(prompts) == 3


def test_json_call_gives_up_after_tries(monkeypatch):
    fake_chat(monkeypatch, "nope")
    with pytest.raises(agents_app.LLMError):
        agents_app.run("hyde", {"company": "Ромашка", "line": "Закупки"})


def test_next_budget_grows_only_when_reasoning_ate_the_answer():
    assert agents_app.next_budget(1200, {"completion_tokens": 1200, "completion_tokens_details": {"reasoning_tokens": 1200}}) == 2400
    assert agents_app.next_budget(1200, {"completion_tokens": 900, "completion_tokens_details": {"reasoning_tokens": 100}}) == 1200
    assert agents_app.next_budget(32000, {"completion_tokens": 32000, "completion_tokens_details": {"reasoning_tokens": 32000}}) == 32000


def test_chat_rejects_models_outside_the_approved_list():
    with pytest.raises(ValueError):
        agents_app.chat("openai/gpt-4o", "hi", 10)


def test_pick_drops_ids_that_are_not_candidates(monkeypatch):
    fake_chat(monkeypatch, '{"top": [{"id": 2}, {"id": 99}, {"id": "x"}, {"id": 1}]}')
    cands = [{"id": 1, "title": "a"}, {"id": 2, "title": "b"}]
    assert agents_app.run("pick", {"company": "c", "line": "l", "candidates": cands}) == {"top": [2, 1]}


def test_queries_keeps_only_blocks_of_strings(monkeypatch):
    fake_chat(monkeypatch, '{"business_model": "B2B", "company_self": [" Ромашка суд ", 5], "government": ["Минфин"]}')
    assert agents_app.run("queries", {"company": "Ромашка", "line": "Закупки"}) == {"company_self": ["Ромашка суд"], "government": ["Минфин"]}


def test_http_contract(monkeypatch):
    fake_chat(monkeypatch, '{"headlines": ["Ставка ЦБ выросла"]}')
    assert client.get("/agents").json()["hyde"]["fields"] == ["company", "line"]
    assert client.post("/agents/nope", json={"input": {}}).status_code == 404
    assert client.post("/agents/hyde", json={"input": {"company": "x"}}).status_code == 422
    r = client.post("/agents/hyde", json={"input": {"company": "x", "line": "y"}})
    assert r.status_code == 200 and r.json()["output"] == {"headlines": ["Ставка ЦБ выросла"]} and r.json()["usage"]["calls"] == 1
    assert client.get("/usage").json()["by_agent"]["hyde"]["cost"] >= 0.5


def test_llm_failure_is_a_502(monkeypatch):
    fake_chat(monkeypatch, "nope")
    assert client.post("/agents/hyde", json={"input": {"company": "x", "line": "y"}}).status_code == 502
