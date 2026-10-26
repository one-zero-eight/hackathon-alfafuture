"""Classifier structure and retry tests, not a measurement of model accuracy."""
import json

import pytest

from agents import app, feedback

INPUT = {"message": "Исправь: точный текст https://example.org/article", "context": {"widgets": [{"id": "n1", "url": "https://example.org/article"}], "links": []}}


@pytest.mark.parametrize("answer", [
    {"kind": "shell", "reason": "x"},
    {"kind": "remove", "reason": "x", "target_id": "invented"},
    {"kind": "remove", "reason": "x"},
    {"kind": "link", "reason": "x", "url": "https://invented.org"},
    {"kind": "edit", "reason": "x", "target_id": "n1", "text": "invented text"},
    {"kind": "extend", "reason": "x"},
    {"kind": "perspective", "reason": "x"},
    {"kind": "clarify", "reason": "x"},
    {"kind": "question", "reason": "x", "refresh": True},
    {"kind": "question", "reason": "x", "execute": "anything"},
])
def test_unknown_targets_urls_and_actions_are_rejected(answer):
    with pytest.raises(ValueError): feedback.validate(answer, INPUT)


def test_manual_text_remains_verbatim_and_structural_failure_retries(monkeypatch):
    answers = iter([{"kind": "remove", "target_id": "invented", "reason": "x"}, {"kind": "edit", "target_id": "n1", "text": "точный текст", "reason": "x"}])
    calls = []
    def chat(*args):
        calls.append(1)
        return json.dumps(next(answers)), {"total_tokens": 10}
    monkeypatch.setattr(app, "chat", chat)
    answer = app.run("feedback_intent", INPUT)
    assert answer["text"] == "точный текст" and len(calls) == 2


def test_classifier_input_is_bounded_before_model_calls():
    from fastapi.testclient import TestClient
    client = TestClient(app.app)
    for data in ({"message": " ", "context": {}}, {"message": "x", "context": {"widgets": [{}] * 81}}, {"message": "x", "context": {"widgets": [{"id": "n1", "title": "x" * 40001}]}}):
        assert client.post("/agents/feedback_intent", json={"input": data}).status_code == 422


def test_labeled_dataset_and_metric_calculation_are_reproducible():
    from agents.benchmarks.feedback_intents import DATASET, scores
    cases = json.loads(DATASET.read_text())
    assert len(cases) == 80 and {case["expected"] for case in cases} == set(feedback.KINDS)
    perfect = [{"expected": case["expected"], "predicted": case["expected"]} for case in cases]
    assert scores(perfect)["macro_f1"] == 1 and scores(perfect)["unintended_mutations"] == 0
    perfect[0]["predicted"] = "remove"
    assert scores(perfect)["macro_f1"] < 1 and scores(perfect)["unintended_mutations"] == 1


def test_url_must_be_an_entire_supplied_url_not_a_prefix():
    inputs = {"message": "https://example.org.evil/article", "context": {"widgets": [], "links": []}}
    with pytest.raises(ValueError):
        feedback.validate({"kind": "link", "reason": "x", "url": "https://example.org"}, inputs)
