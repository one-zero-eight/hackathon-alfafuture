"""Validation of the feedback_intent answer: targets and fields are checked, anything unusable is a question to the user."""

from agents.feedback import validate

CTX = {
    "selected": {"type": "widget", "id": "w1"},
    "widgets": [
        {"id": "w1", "column": "news", "title": "Новость"},
        {"id": "w2", "column": "analytics", "title": "Вывод"},
    ],
    "links": [],
}


def check(out, message="сообщение"):
    return validate(out, {"message": message, "context": CTX})


def test_valid_intents_keep_only_checked_fields():
    assert (
        check({"kind": "question", "reason": "вопрос", "target_id": "w9"})["target_id"]
        is None
    )
    remove = check({"kind": "remove", "reason": "r", "target_id": "w1"})
    assert remove["kind"] == "remove" and remove["target_id"] == "w1"
    assert (
        check(
            {
                "kind": "edit",
                "reason": "r",
                "target_id": "w2",
                "text": "Новая формулировка",
            }
        )["text"]
        == "Новая формулировка"
    )
    assert (
        check({"kind": "perspective", "reason": "r", "region": "Урал"})["region"]
        == "Урал"
    )
    assert (
        check({"kind": "extend", "reason": "r", "text": "рынок Казахстана"})["kind"]
        == "extend"
    )


def test_unknown_kind_missing_or_foreign_target_and_empty_fields_become_clarify():
    for out in (
        {"kind": "delete_all"},
        {"kind": "remove", "target_id": "zz"},
        {"kind": "remove"},
        {"kind": "edit", "target_id": "w1"},
        {"kind": "extend", "text": "  "},
        {"kind": "perspective"},
        {"kind": "proposal"},
        {},
    ):
        got = check(out)
        assert (
            got["kind"] == "clarify"
            and got["clarification"]
            and got["target_id"] is None
        ), out


def test_link_url_must_be_in_the_message_and_http():
    message = "вот статья https://example.com/a"
    assert (
        check({"kind": "link", "url": "https://example.com/a"}, message)["url"]
        == "https://example.com/a"
    )
    assert (
        check({"kind": "link", "url": "https://other.com/x"}, message)["kind"]
        == "clarify"
    )  # not in the message
    assert check({"kind": "link", "url": None}, message)["kind"] == "clarify"
    for url in ("file:///etc/passwd", "ftp://example.com/a", "javascript:alert(1)"):
        assert (
            check({"kind": "link", "url": url}, f"{message} {url}")["kind"] == "clarify"
        )


def test_clarify_keeps_the_agents_question():
    assert (
        check({"kind": "clarify", "clarification": "Что изменить?"})["clarification"]
        == "Что изменить?"
    )


def test_labelled_set_is_consistent_and_scoring_reaches_one_for_perfect_answers_and_catches_wrong_mutations():
    from agents.benchmarks import feedback_intents as bench

    context, cases = bench.load()
    bench.check(context, cases)
    perfect = [
        {"kind": c["expect"], "target_id": c.get("target_id"), "url": c.get("url")}
        for c in cases
    ]
    assert bench.score(cases, perfect)["macro_f1"] == 1.0
    broken = [
        dict(p, kind="remove") if c["expect"] == "question" else p
        for c, p in zip(cases, perfect)
    ]
    assert len(bench.score(cases, broken)["wrong_mutations"]) == 14
    # the set agrees with the validator: a perfect agent answer survives validation unchanged in kind
    for c in cases:
        out = {
            "kind": c["expect"],
            "reason": "r",
            "target_id": c.get("target_id"),
            "url": c.get("url"),
            "text": "текст",
            "clarification": "уточните",
            **c.get("fields", {}),
        }
        assert validate(out, bench.agent_input(context, c))["kind"] == c["expect"], c
