"""Offline checks of the call log: what is written for a call, for the reasoning stream, for failures. Run: pytest agents"""
import contextlib
import json

import httpx

from agents import app as agents_app
from agents.test_agents import fake_chat


def lines(capsys):
    return [json.loads(x) for x in capsys.readouterr().out.splitlines() if x.startswith("{")]


def test_call_log_has_input_prompt_attempts_and_result(monkeypatch, capsys):
    fake_chat(monkeypatch, "не JSON", '{"needs": ["Как изменится ставка?"]}')
    agents_app.run("needs", {"company": "Ромашка", "line": "Закупки"})
    events = lines(capsys)
    assert [e["event"] for e in events] == ["call", "attempt", "attempt", "result"]
    assert len({e["call_id"] for e in events}) == 1 and all(e["agent"] == "needs" for e in events)
    assert events[0]["input"] == {"company": "Ромашка", "line": "Закупки"} and "Ромашка" in events[0]["prompt"]
    assert [(e["attempt"], e["outcome"]) for e in events[1:3]] == [(1, "retry"), (2, "ok")]
    assert events[2]["parsed"] == {"needs": ["Как изменится ставка?"]} and events[3]["output"] == {"needs": ["Как изменится ставка?"]}


def test_failed_call_logs_the_error_and_images_are_not_dumped(monkeypatch, capsys):
    fake_chat(monkeypatch, "nope")
    with contextlib.suppress(agents_app.LLMError):
        agents_app.run("alfa_page", {"page": 1, "text": "т", "images": ["data:image/png;base64," + "A" * 1000]})
    events = lines(capsys)
    assert events[0]["images"] == 1 and "images" not in events[0]["input"] and "AAAA" not in json.dumps(events)
    assert events[-1]["event"] == "error" and sum(e["event"] == "attempt" for e in events) == 3


def test_gateway_logs_reasoning_and_the_partial_answer_of_a_failed_try(monkeypatch, capsys):
    monkeypatch.setenv("LLM_API_KEY", "k")
    monkeypatch.setenv("LLM_BASE_URL", "https://gw.example/v1")
    monkeypatch.delenv("LLM_BASE_URL_BACKUP", raising=False)
    streams = iter([
        ['data: {"choices":[{"delta":{"reasoning_content":"думаю про ставку"}}]}',
         'data: {"choices":[{"delta":{"content":"{\\"a\\""}}]}', "data: not json"],
        ['data: {"choices":[{"delta":{"reasoning":"ещё"}}]}', 'data: {"choices":[{"delta":{"content":"{}"},"finish_reason":"stop"}],"usage":{"total_tokens":7}}', "data: [DONE]"],
    ])

    class Stream:
        def __init__(self, rows):
            self.rows = rows

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def raise_for_status(self):
            pass

        def iter_lines(self):
            return iter(self.rows)

    monkeypatch.setattr(httpx, "stream", lambda *a, **k: Stream(next(streams)))
    assert agents_app.chat(agents_app.GEMMA, "hi", 10) == ("{}", {"total_tokens": 7})
    failed, ok = lines(capsys)
    assert failed["ok"] is False and failed["reasoning"] == "думаю про ставку" and failed["content"] == '{"a"' and "JSONDecodeError" in failed["error"]
    assert ok["ok"] is True and ok["reasoning"] == "ещё" and ok["finish_reason"] == "stop" and ok["gateway"] == "gw.example"


def test_log_file_is_appended_and_a_broken_path_does_not_fail_the_call(monkeypatch, tmp_path, capsys):
    fake_chat(monkeypatch, '{"headlines": ["Ставка ЦБ выросла"]}')
    path = tmp_path / "calls.jsonl"
    monkeypatch.setenv("AGENTS_LOG_FILE", str(path))
    agents_app.run("hyde", {"company": "x", "line": "y"})
    assert [json.loads(x)["event"] for x in path.read_text(encoding="utf-8").splitlines()] == ["call", "attempt", "result"]
    monkeypatch.setenv("AGENTS_LOG_FILE", str(tmp_path / "missing" / "calls.jsonl"))
    assert agents_app.run("hyde", {"company": "x", "line": "y"}) == {"headlines": ["Ставка ЦБ выросла"]}
