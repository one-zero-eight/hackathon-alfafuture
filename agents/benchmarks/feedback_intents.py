"""Labeled classifier evaluation. Without --live, only validate the dataset; never fake accuracy."""
import argparse
import collections
import json
import statistics
import time
from pathlib import Path

from agents.client import Agents
from agents.feedback import KINDS, validate

DATASET = Path(__file__).with_name("feedback-intents.json")
CONTEXT = {"company": {"name": "Компания-фикстура", "role": "CFO"},
           "widgets": [{"id": "n1", "column": "news", "title": "Банк России сохранил ставку"},
                       {"id": "a1", "column": "analytics", "title": "Долг останется дорогим"},
                       {"id": "d1", "column": "decisions", "title": "Зафиксировать ставку по половине долга"}],
           "links": [{"id": "l1", "from": "n1", "to": "a1"}]}


def scores(rows):
    per_class = {}
    for label in KINDS:
        tp = sum(r["expected"] == label and r["predicted"] == label for r in rows)
        fp = sum(r["expected"] != label and r["predicted"] == label for r in rows)
        fn = sum(r["expected"] == label and r["predicted"] != label for r in rows)
        per_class[label] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    measured = [value for value in per_class.values() if value is not None]
    unsafe = sum(r["expected"] in ("question", "clarify") and r["predicted"] in ("extend", "perspective", "edit", "remove", "link", "proposal") for r in rows)
    return {"macro_f1": statistics.mean(measured) if measured else None, "per_class_f1": per_class, "unintended_mutations": unsafe,
            "confusion": dict(collections.Counter(f"{r['expected']} -> {r['predicted']}" for r in rows))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Actually invoke the configured agents service; requires approved budget")
    parser.add_argument("--max-cost", type=float, help="Stop after reported gateway cost reaches this limit; one call may exceed it")
    parser.add_argument("--limit", type=int, default=80)
    args = parser.parse_args()
    cases = json.loads(DATASET.read_text())
    assert len(cases) == 80 and len({c["id"] for c in cases}) == 80
    assert collections.Counter(c["expected"] for c in cases) == {kind: 10 for kind in KINDS}
    if not args.live:
        print(json.dumps({"cases": 80, "classes": list(KINDS), "accuracy": "not measured", "paid_calls": 0}))
        return
    if args.max_cost is None or args.max_cost <= 0 or not 1 <= args.limit <= 80:
        parser.error("--live requires --max-cost > 0 and --limit between 1 and 80")
    agents, rows = Agents(), []
    for case in cases[:args.limit]:
        if agents.cost >= args.max_cost or agents.unknown_cost_calls:
            break
        selected = case["selected"]
        context = {**CONTEXT, "selected": {"type": "page" if selected == "page" else ("link" if selected == "l1" else "widget"), "id": selected}}
        inputs = {"message": case["message"], "context": context}
        started = time.monotonic()
        try:
            predicted = validate(agents.run("feedback_intent", inputs), inputs)["kind"]
        except (RuntimeError, ValueError):
            predicted = "invalid"
        rows.append({"id": case["id"], "expected": case["expected"], "predicted": predicted, "ms": (time.monotonic() - started) * 1000})
        if predicted == "invalid":
            break  # Failed HTTP calls may have consumed unreported tokens; never continue spending blindly.
    print(json.dumps({**scores(rows), "cases_measured": len(rows), "reported_cost": agents.cost, "unknown_cost_calls": agents.unknown_cost_calls,
                      "tokens": agents.tokens, "median_ms": statistics.median(r["ms"] for r in rows) if rows else None, "rows": rows}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
