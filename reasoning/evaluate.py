"""Deterministic scores for a reasoning page. The LLM judge is separate and needs a key.

Nugget recall is a stem-overlap proxy: it counts whether the page states the nugget's words, not whether a
second model accepts the meaning. The study in exp/v2 showed that proxy and a real judge diverge, so treat
this number as a smoke signal and run the judge before trusting it.
"""
import json
import sys

from reasoning.data import corpus, nuggets
from reasoning.search import stems

OUT = __import__("pathlib").Path(__file__).resolve().parent / "out"


def recall(page: dict, gold: list[dict]) -> float:
    text = " ".join(w.get("details", {}).get("text", "") + " " + w.get("title", "") for w in page["widgets"])
    have = set(stems(text))
    vital = [g for g in gold if g.get("vital")]
    if not vital:
        return 0.0
    hit = 0
    for g in vital:
        need = set(stems(g["n"]))
        if need and len(need & have) / len(need) >= 0.25:
            hit += 1
    return hit / len(vital)


def score(page: dict, gold: list[dict], known_ids: set[str]) -> dict:
    widgets = {w["id"]: w for w in page["widgets"]}
    links = page["links"]
    journal = page.get("journal", [])
    ana = [w for w in page["widgets"] if w["column"] == "analytics"]
    dec = [w for w in page["widgets"] if w["column"] == "decisions"]
    arrows_ok = all(any(l["to"] == w["id"] and widgets.get(l["from"], {}).get("column") == "news" for l in links) for w in ana) \
        and all(any(l["to"] == w["id"] and widgets.get(l["from"], {}).get("column") == "analytics" for l in links) for w in dec)
    evidence = [e for row in journal for e in row.get("evidence", [])]
    invented = [e for e in evidence if e not in known_ids]
    reached = [r for r in journal if r["notes"]]
    deep = [r for r in reached if any(k != "direct" for k in r["plan"])]
    return {
        "events": len(journal),
        "with_analytics": len(reached),
        "with_decision": sum(r["decision"] for r in journal),
        "arrows_ok": arrows_ok,
        "invented_ids": len(invented),
        "alfa_share": (sum(w["tags"].get("source") == "alfa" for w in ana) / len(ana)) if ana else 0,
        "triz_share": (sum(bool(r.get("move")) for r in journal) / len(dec)) if dec else 0,
        "depth": (len(deep) / len(reached)) if reached else 0,
        "nugget_recall": round(recall(page, gold), 3),
    }


def main() -> None:
    pid = sys.argv[1]
    page = json.loads((OUT / f"{pid}.json").read_text())
    _, items = corpus(pid)
    known = set(items)
    theses = OUT / "theses.jsonl"
    if theses.exists():
        known.update(json.loads(row)["id"] for row in theses.read_text(encoding="utf-8").splitlines())
    print(json.dumps(score(page, nuggets()[pid], known), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
