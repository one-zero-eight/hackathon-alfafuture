"""Quality of the feedback_intent agent on the labelled set feedback-intents.json (80 requests, 8 kinds).

Offline: uv run python -m agents.benchmarks.feedback_intents          (checks the set, no LLM)
Live (paid Gemma calls, 80 requests): FEEDBACK_BENCH_CONFIRMED=1 AGENTS_URL=http://localhost:8001 uv run python -m agents.benchmarks.feedback_intents --live
Metrics: macro-F1 over kinds (target >= 0.90); wrong mutations = question/clarify requests that got a changing kind (target 0).
"""

import json
import os
import sys
from pathlib import Path

from agents.feedback import KINDS

DATA = Path(__file__).with_name("feedback-intents.json")
MUTATING = {"extend", "perspective", "edit", "remove", "link", "proposal"}


def load() -> tuple[dict, list[dict]]:
    data = json.loads(DATA.read_text(encoding="utf-8"))
    return data["context"], data["cases"]


def check(context: dict, cases: list[dict]) -> None:
    ids = {w["id"] for w in context["widgets"]}
    assert len(cases) == 80 and {c["expect"] for c in cases} == set(KINDS)
    for c in cases:
        assert c["selected"]["type"] in ("widget", "link", "page") and (
            c["selected"]["type"] != "widget" or c["selected"]["id"] in ids
        ), c
        assert c["expect"] not in ("edit", "remove") or c.get("target_id") in ids, c
        assert c["expect"] != "link" or c["url"] in c["message"], c


def agent_input(context: dict, case: dict) -> dict:
    sel = case["selected"]
    return {
        "message": case["message"],
        "context": {
            "selected": sel,
            "company": context["company"],
            "widgets": context["widgets"],
            "links": context["links"],
        },
    }


def score(cases: list[dict], predicted: list[dict]) -> dict:
    f1 = {}
    for kind in KINDS:
        tp = sum(c["expect"] == kind == p["kind"] for c, p in zip(cases, predicted))
        fp = sum(c["expect"] != kind == p["kind"] for c, p in zip(cases, predicted))
        fn = sum(c["expect"] == kind != p["kind"] for c, p in zip(cases, predicted))
        f1[kind] = 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else 1.0
    wrong = [
        c["message"]
        for c, p in zip(cases, predicted)
        if c["expect"] in ("question", "clarify") and p["kind"] in MUTATING
    ]
    fields = sum(
        p.get("target_id") == c.get("target_id") and p.get("url") == c.get("url")
        for c, p in zip(cases, predicted)
        if c["expect"] in ("edit", "remove", "link")
    )
    return {
        "macro_f1": sum(f1.values()) / len(f1),
        "f1": f1,
        "wrong_mutations": wrong,
        "accuracy": sum(c["expect"] == p["kind"] for c, p in zip(cases, predicted))
        / len(cases),
        "field_accuracy": fields
        / sum(c["expect"] in ("edit", "remove", "link") for c in cases),
    }


def main() -> None:
    context, cases = load()
    check(context, cases)
    if "--live" not in sys.argv:
        print("set is valid:", len(cases), "requests")
        return
    if os.environ.get("FEEDBACK_BENCH_CONFIRMED") != "1":
        raise SystemExit(
            "80 paid Gemma calls: confirm the currency and the daily budget, then set FEEDBACK_BENCH_CONFIRMED=1"
        )
    from agents.client import Agents

    agents = Agents()
    predicted = [agents.run("feedback_intent", agent_input(context, c)) for c in cases]
    print(
        json.dumps(score(cases, predicted), ensure_ascii=False, indent=1),
        f"\ncalls={agents.calls} tokens={agents.tokens} cost={agents.cost}",
    )


if __name__ == "__main__":
    main()
